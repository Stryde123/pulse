import os
import logging
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from db.schema import init_db
from db.queries import (
    get_account_by_channel, insert_message, insert_account,
    get_all_accounts, snooze_account, get_health_history,
    update_toggles, delete_account, get_recent_signals,
)
from agents.pattern_detector import detect_patterns
from agents.health_scorer import score_account, get_score_breakdown
from agents.rts_monitor import answer_question
from agents.external_signals import scan_all_accounts
from agents.champion_tracker import auto_update_champion
from agents.backfill import backfill_channel_history
from agents.alert_dispatcher import maybe_send_alert

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = App(token=os.environ["SLACK_BOT_TOKEN"])

# Cached at startup so we don't call auth.test on every message
_BOT_TEAM_ID: str | None = None


def get_bot_team_id() -> str:
    global _BOT_TEAM_ID
    if _BOT_TEAM_ID is None:
        resp = app.client.auth_test()
        _BOT_TEAM_ID = resp["team_id"]
    return _BOT_TEAM_ID


def is_customer_message(event: dict, am_user_id: "str | None" = None) -> bool:
    """
    In Slack Connect channels the event payload carries `user_team` (the sender's
    workspace ID). If it differs from the bot's workspace, the sender is on the
    customer side. Falls back to checking `team` field for older API versions.

    The account's registered AM is never treated as the customer, regardless
    of what the workspace-ID comparison says — this is what actually lets
    the AM's own replies count as team responses (feeding the latency
    factor) rather than accidentally being scored as customer messages.
    """
    if am_user_id and event.get("user") == am_user_id:
        return False
    sender_team = event.get("user_team") or event.get("team")
    if sender_team:
        return sender_team != get_bot_team_id()
    # Fallback: bots and system messages have no user field
    return bool(event.get("user"))


# ---------------------------------------------------------------------------
# Message ingestion
# ---------------------------------------------------------------------------

def _resolve_name_fn(client):
    def resolve(user_id: str) -> str:
        info = client.users_info(user=user_id)
        return info["user"]["real_name"]
    return resolve


@app.event("message")
def handle_message(event, client, logger):
    # Ignore subtypes (edits, deletes, bot_messages we don't care about)
    if event.get("subtype"):
        return

    channel_id = event.get("channel")
    user_id = event.get("user")
    text = event.get("text", "").strip()
    ts = event.get("ts", "")

    if not user_id or not text:
        return

    account = get_account_by_channel(channel_id)
    if not account:
        return

    customer = is_customer_message(event, account.get("am_user_id"))

    # Run pattern detection on customer messages only
    flags = detect_patterns(text) if customer else []

    msg_id = insert_message(
        account_id=account["id"],
        channel_id=channel_id,
        user_id=user_id,
        text=text,
        is_customer=customer,
        timestamp=ts,
        flags=flags,
    )

    side = "customer" if customer else "team"
    if flags:
        labels = ", ".join(f["label"] for f in flags)
        logger.warning(f"[{account['name']}] FLAGS detected: {labels} | \"{text[:60]}\"")
    else:
        logger.info(f"[{account['name']}] stored msg {msg_id} from {side} ({user_id})")

    # Auto-identify champion if this account has champion tracking enabled
    # and none is set yet
    if customer and account.get("enable_champion_tracking") and not account.get("champion_user_id"):
        auto_update_champion(account)

    # Recalculate health score on every message
    score, urgency = score_account(account)
    logger.info(f"[{account['name']}] health recalculated: {score}/100 ({urgency.upper()})")

    # Fire an alert DM to the AM if urgency crossed the threshold and we're
    # not throttled/snoozed
    try:
        sent = maybe_send_alert(account, score, urgency, client, resolve_name_fn=_resolve_name_fn(client))
        if sent:
            logger.warning(f"[{account['name']}] ALERT SENT to AM ({urgency.upper()})")
    except Exception as e:
        logger.error(f"[{account['name']}] Alert dispatch failed: {e}")


# ---------------------------------------------------------------------------
# Account registration via app mention
# Usage: @Pulse register #channel-name  AccountName  AM:<@U...>
# Example: @Pulse register #brightline-saas  Brightline SaaS  AM:<@U012ABC>  value:120000  renewal:2026-12-01
# ---------------------------------------------------------------------------

@app.event("app_mention")
def handle_mention(event, say, client, logger):
    text = event.get("text", "")
    user_id = event.get("user")

    lowered = text.lower()

    import re as _re
    is_help = bool(_re.search(r"(^|\s)help(\s|$)", lowered))

    if is_help:
        _handle_help(say)
    elif "unregister" in lowered:
        _handle_unregister(text, say, logger)
    elif "register" in lowered:
        _handle_register(text, say, client, logger)
    elif "list" in lowered:
        accounts = get_all_accounts()
        if not accounts:
            say("No accounts registered yet.")
            return
        lines = ["*Monitored accounts:*"]
        for a in accounts:
            lines.append(f"• *{a['name']}* — <#{a['channel_id']}> (AM: <@{a['am_user_id']}>)")
        say("\n".join(lines))
    elif "ask" in lowered:
        _handle_ask(text, event, say, client, logger)
    elif "report" in lowered:
        _handle_report(text, say, logger)
    elif "status" in lowered:
        _handle_status(text, say, logger)
    elif "toggle" in lowered:
        _handle_toggle(text, say, logger)
    else:
        _handle_help(say)


def _handle_help(say):
    say(
        "Hi! I'm Pulse. Commands:\n"
        "• `@Pulse register <#channel> <Account Name> AM:<@user> [value:<n>] [renewal:<YYYY-MM-DD>] "
        "[champion:on/off] [signals:on/off] [crm:on/off]` — all three default OFF\n"
        "• `@Pulse toggle <account name or #channel> [champion:on/off] [signals:on/off] [crm:on/off]` — change anytime\n"
        "• `@Pulse unregister <account name or #channel>` — stop monitoring and delete all its data\n"
        "• `@Pulse list` — show all monitored accounts\n"
        "• `@Pulse status <account name or #channel>` — check current health instantly\n"
        "• `@Pulse report <account name or #channel>` — full per-factor health score breakdown\n"
        "• `@Pulse ask <question>` — search Slack Connect history plus any external "
        "signals already found for that account\n"
        "• `@Pulse help` — show this message"
    )


def _find_account(query: str) -> "dict | None":
    import re
    channel_match = re.search(r"<#(C[A-Z0-9]+)\|?[^>]*>", query)
    if channel_match:
        return get_account_by_channel(channel_match.group(1))

    accounts = get_all_accounts()
    query_lower = query.strip().lower()
    for a in accounts:
        if a["name"].lower() == query_lower:
            return a
    for a in accounts:
        if query_lower in a["name"].lower():
            return a
    return None


def _find_account_mentioned_in(free_text: str) -> "dict | None":
    """
    Reverse of _find_account's substring check — used for @Pulse ask, where
    the input is a full question rather than a short name/channel query.
    Looks for a registered account's name appearing anywhere in the text.
    Longest name wins, so a more specific match beats a shorter one that
    happens to be a substring of it.
    """
    accounts = get_all_accounts()
    text_lower = free_text.lower()
    matches = [a for a in accounts if a["name"].lower() in text_lower]
    if not matches:
        return None
    return max(matches, key=lambda a: len(a["name"]))


def _handle_status(text: str, say, logger):
    """
    @Pulse status <account name or #channel> — instant health check,
    recalculated live on every call (not read from the last stored row) so
    it reflects any resolution/decay since the last message, not just what
    happened to be true whenever the score last recomputed.
    """
    import re
    match = re.search(r"status\s+(.+)", text, re.IGNORECASE)
    if not match:
        say("Usage: `@Pulse status <account name or #channel>`")
        return

    query = match.group(1).strip()
    account = _find_account(query)
    if not account:
        say(f"Couldn't find an account matching \"{query}\". Try `@Pulse list` to see all accounts.")
        return

    from db.queries import get_recent_signals
    from agents.champion_tracker import get_champion_metrics
    from blocks.brief_card import URGENCY_EMOJI, _days_to_renewal

    score, urgency = score_account(account)
    health = {"score": score, "urgency": urgency}

    days_to_renewal = _days_to_renewal(account.get("renewal_date"))
    renewal_display = f"{days_to_renewal} days" if days_to_renewal is not None else "not set"

    emoji = URGENCY_EMOJI.get(health["urgency"], "🟡")

    lines = [
        f"{emoji} *{account['name']}* — {health['score']}/100 ({health['urgency'].upper()})",
        f"Contract: ${account.get('contract_value', 0):,} | Renewal: {renewal_display}",
    ]

    if account.get("enable_champion_tracking"):
        champion = get_champion_metrics(account)
        if champion["user_id"]:
            silence_note = f" — {champion['silence_level'].upper()}" if champion["silence_level"] else ""
            lines.append(
                f"Champion: {champion['name']} — silent {champion['days_silent']}d, "
                f"{champion['posts_this_week']} posts this week{silence_note}"
            )
        else:
            lines.append("Champion: tracking ON, not yet identified")
    else:
        lines.append("Champion: tracking OFF (`@Pulse toggle` to enable)")

    if account.get("enable_external_signals"):
        signals = get_recent_signals(account["id"], days=14)
        if signals:
            sig_summary = ", ".join(f"{s['signal_type']} (sev {s['severity']})" for s in signals[:3])
            lines.append(f"External signals (14d): {sig_summary}")
        else:
            lines.append("External signals (14d): none found")
    else:
        lines.append("External signals: OFF (`@Pulse toggle` to enable)")

    lines.append(f"Salesforce CRM: {'ON' if account.get('enable_salesforce_crm') else 'OFF'} "
                  f"(`@Pulse toggle` to enable)")

    say("\n".join(lines))


FACTOR_LABELS = {
    "frequency": "Message frequency",
    "latency": "Response latency",
    "flags": "Pattern flags",
    "champion": "Champion activity",
    "signals": "External signals",
}


def _handle_report(text: str, say, logger):
    """
    @Pulse report <account name or #channel> — full per-factor health score
    breakdown, recalculated live (not just the last stored total). Unlike
    @Pulse status, this shows exactly how many points each of the five
    factors contributed, plus whether compound-risk escalation is active.
    """
    import re
    match = re.search(r"report\s+(.+)", text, re.IGNORECASE)
    if not match:
        say("Usage: `@Pulse report <account name or #channel>`")
        return

    query = match.group(1).strip()
    account = _find_account(query)
    if not account:
        say(f"Couldn't find an account matching \"{query}\". Try `@Pulse list` to see all accounts.")
        return

    result = get_score_breakdown(account)
    score, urgency, breakdown = result["score"], result["urgency"], result["breakdown"]
    escalated_from = breakdown.pop("compound_risk_escalated_from", None)

    lines = [f"*{account['name']}* health report — {score}/100 ({urgency.upper()})", ""]
    for key, penalty in breakdown.items():
        label = FACTOR_LABELS.get(key, key)
        sign = f"{penalty}" if penalty <= 0 else f"+{penalty}"
        lines.append(f"• {label}: {sign}")

    if escalated_from:
        lines.append("")
        lines.append(
            f"⚠️ Compound risk escalation active — urgency bumped from "
            f"{escalated_from.upper()} to {urgency.upper()} (severe pattern flag + "
            f"critically silent champion + severe external signal, all present at once)"
        )

    say("\n".join(lines))


def _handle_toggle(text: str, say, logger):
    """
    @Pulse toggle <account name or #channel> [champion:on/off] [signals:on/off]
    """
    import re
    match = re.search(r"toggle\s+(.+)", text, re.IGNORECASE)
    if not match:
        say("Usage: `@Pulse toggle <account name or #channel> [champion:on/off] [signals:on/off] [crm:on/off]`")
        return

    rest = match.group(1).strip()
    champion_flag = _parse_toggle_flag(rest, "champion")
    signals_flag = _parse_toggle_flag(rest, "signals")
    crm_flag = _parse_toggle_flag(rest, "crm")

    if champion_flag is None and signals_flag is None and crm_flag is None:
        say("Specify at least one of `champion:on/off`, `signals:on/off`, or `crm:on/off`.\n"
            "Usage: `@Pulse toggle <account name or #channel> [champion:on/off] [signals:on/off] [crm:on/off]`")
        return

    # Strip the flag tokens back out to isolate the account query
    query = re.sub(r"(champion|signals|crm):(on|off)", "", rest, flags=re.IGNORECASE).strip()
    account = _find_account(query)
    if not account:
        say(f"Couldn't find an account matching \"{query}\". Try `@Pulse list` to see all accounts.")
        return

    update_toggles(
        account["id"],
        enable_champion_tracking=champion_flag,
        enable_external_signals=signals_flag,
        enable_salesforce_crm=crm_flag,
    )
    account = get_account_by_channel(account["channel_id"])  # refetch with updated flags

    changes = []
    if champion_flag is not None:
        changes.append(f"Champion tracking: {'ON' if champion_flag else 'OFF'}")
    if signals_flag is not None:
        changes.append(f"External signals: {'ON' if signals_flag else 'OFF'}")
    if crm_flag is not None:
        changes.append(f"Salesforce CRM: {'ON' if crm_flag else 'OFF'}")

    say(f"✅ *{account['name']}* updated — {', '.join(changes)}")

    # Turning a feature ON should apply immediately against existing message
    # history, not wait for the next incoming message to happen to trigger it
    if champion_flag is True:
        from agents.champion_tracker import auto_update_champion
        champion_id = auto_update_champion(account)
        if champion_id:
            say(f"👤 Champion identified from existing history: {champion_id}")
        else:
            say("👤 No customer messages yet to identify a champion from.")

    if signals_flag is True:
        from agents.external_signals import scan_account
        say("🌐 Running an immediate external signal scan...")
        count = scan_account(account)
        say(f"🌐 Signal scan complete — {count} new signal(s) found." if count
            else "🌐 Signal scan complete — nothing found yet.")

    if crm_flag is True:
        from agents.salesforce_mcp import query_account
        say("☁️ Testing Salesforce MCP connection (first run may take ~20s to start the server)...")
        record = query_account(account["name"])
        if record:
            say(f"☁️ Salesforce CRM connected — matched Account *{record.get('Name')}* "
                f"({record.get('Industry', 'unknown industry')}). Future briefs will pull this live.")
        else:
            say(f"☁️ Salesforce CRM connected, but no Account named \"{account['name']}\" was found in the org — "
                f"briefs will proceed without CRM context until a matching Account exists.")

    if champion_flag is not None or signals_flag is not None:
        score, urgency = score_account(account)
        say(f"📊 Health score recalculated: {score}/100 ({urgency.upper()})")

    logger.info(f"[{account['name']}] Toggles updated: champion={champion_flag}, signals={signals_flag}, crm={crm_flag}")


def _handle_unregister(text: str, say, logger):
    """
    @Pulse unregister <account name or #channel> — stops monitoring the
    account and permanently deletes its messages, health scores, signals,
    and alerts. Does not touch the Slack channel itself.
    """
    import re
    match = re.search(r"unregister\s+(.+)", text, re.IGNORECASE)
    if not match:
        say("Usage: `@Pulse unregister <account name or #channel>`")
        return

    query = match.group(1).strip()
    account = _find_account(query)
    if not account:
        say(f"Couldn't find an account matching \"{query}\". Try `@Pulse list` to see all accounts.")
        return

    delete_account(account["id"])
    say(f"🗑️ *{account['name']}* unregistered — stopped monitoring and deleted its history. "
        f"The Slack channel itself is untouched; re-register it any time with `@Pulse register`.")
    logger.info(f"Unregistered account '{account['name']}' (ID {account['id']})")


def _handle_ask(text: str, event: dict, say, client, logger):
    """
    @Pulse ask <question> — uses Slack's Real-time Search API to find relevant
    messages across every channel the bot has access to, then Claude answers.
    Requires the action_token from this app_mention event (short-lived, only
    present because the bot was directly @-mentioned).
    """
    import re
    question_match = re.search(r"ask\s+(.+)", text, re.IGNORECASE)
    if not question_match:
        say("Usage: `@Pulse ask <your question>`")
        return

    action_token = event.get("action_token")
    if not action_token:
        say("Sorry, I need to be directly @-mentioned to search (no action token on this event).")
        return

    question = question_match.group(1).strip()
    say(f"🔍 Searching Slack for: _{question}_")

    # Prefer the account tied to the current channel, but AMs often ask from
    # a separate internal channel (deliberately, so nothing about the ask
    # itself is visible to the customer in a shared Slack Connect channel) —
    # fall back to matching an account name mentioned in the question itself.
    channel_id = event.get("channel")
    account = get_account_by_channel(channel_id) if channel_id else None
    if not account:
        account = _find_account_mentioned_in(question)
    signals = get_recent_signals(account["id"]) if account and account.get("enable_external_signals") else None

    answer = answer_question(client, question, action_token, signals=signals)
    say(answer)
    logger.info(f"RTS ask: \"{question[:60]}\" -> answered")


def _parse_toggle_flag(text: str, name: str) -> "bool | None":
    """Returns True/False if `name:on` or `name:off` is present, else None."""
    import re
    match = re.search(rf"{name}:(on|off)", text, re.IGNORECASE)
    if not match:
        return None
    return match.group(1).lower() == "on"


def _handle_register(text: str, say, client, logger):
    """
    Parse: @Pulse register #C_CHANNEL_ID|name  Account Name  AM:<@USERID>
           [value:N] [renewal:DATE] [champion:on/off] [signals:on/off]
    Slack encodes channel mentions as <#C123|name> and user mentions as <@U123>.
    Champion tracking and external signal monitoring default OFF unless
    explicitly turned on here or later via @Pulse toggle.
    """
    import re

    channel_match = re.search(r"<#(C[A-Z0-9]+)\|?[^>]*>", text)
    am_match = re.search(r"AM:<@(U[A-Z0-9]+)>", text)
    value_match = re.search(r"value:(\d+)", text)
    renewal_match = re.search(r"renewal:([\d-]+)", text)

    if not channel_match or not am_match:
        say("Usage: `@Pulse register <#channel> <Account Name> AM:<@user> [value:120000] "
            "[renewal:2026-12-01] [champion:on/off] [signals:on/off]`")
        return

    channel_id = channel_match.group(1)
    am_user_id = am_match.group(1)
    contract_value = int(value_match.group(1)) if value_match else 0
    renewal_date = renewal_match.group(1) if renewal_match else None
    enable_champion = _parse_toggle_flag(text, "champion") or False
    enable_signals = _parse_toggle_flag(text, "signals") or False
    enable_crm = _parse_toggle_flag(text, "crm") or False

    # Extract account name: everything between channel mention and AM:
    name_match = re.search(r"<#[^>]+>\s+(.+?)\s+AM:", text)
    account_name = name_match.group(1).strip() if name_match else "Unknown Account"

    try:
        # Join the channel so the bot can read messages
        client.conversations_join(channel=channel_id)
    except Exception as e:
        logger.warning(f"Could not join {channel_id}: {e}")

    try:
        account_id = insert_account(
            name=account_name,
            channel_id=channel_id,
            am_user_id=am_user_id,
            contract_value=contract_value,
            renewal_date=renewal_date,
            enable_champion_tracking=enable_champion,
            enable_external_signals=enable_signals,
            enable_salesforce_crm=enable_crm,
        )
        say(
            f"✅ *{account_name}* registered (ID: {account_id})\n"
            f"Channel: <#{channel_id}> | AM: <@{am_user_id}> | "
            f"Value: ${contract_value:,} | Renewal: {renewal_date or 'not set'}\n"
            f"Champion tracking: {'ON' if enable_champion else 'OFF'} | "
            f"External signals: {'ON' if enable_signals else 'OFF'} | "
            f"Salesforce CRM: {'ON' if enable_crm else 'OFF'} "
            f"(use `@Pulse toggle` to change anytime)\n"
            f"📥 Pulling channel history to catch up on this relationship..."
        )
        logger.info(f"Registered account '{account_name}' → channel {channel_id}")

        account = get_account_by_channel(channel_id)
        summary = backfill_channel_history(account, client, get_bot_team_id())

        say(
            f"✅ Backfill complete for *{account_name}*: "
            f"{summary['messages_imported']} messages imported "
            f"({summary['flagged']} flagged) — "
            f"current health: {summary['score']}/100 ({summary['urgency'].upper()})"
        )
    except Exception as e:
        say(f"❌ Failed to register account: {e}")
        logger.error(f"Registration error: {e}")


# ---------------------------------------------------------------------------
# member_joined_channel — auto-detect new members in monitored channels
# ---------------------------------------------------------------------------

@app.event("member_joined_channel")
def handle_member_joined(event, logger):
    channel_id = event.get("channel")
    account = get_account_by_channel(channel_id)
    if account:
        logger.info(f"New member in monitored channel [{account['name']}]: {event.get('user')}")


# ---------------------------------------------------------------------------
# Button action handlers
# ---------------------------------------------------------------------------

@app.action("send_draft")
def handle_send_draft(ack, body, client, logger):
    """
    Opens an editable compose modal pre-filled with Claude's draft, rather
    than sending it straight to the customer channel. The AM should always
    review — and can edit — the message before it goes out; auto-sending an
    AI-written message to a customer without a human in the loop reads as
    tone-deaf, especially in a churn-risk situation.
    """
    ack()
    value = body["actions"][0]["value"]
    account_id_str, channel_id = value.split("|")
    account_id = int(account_id_str)
    am_user_id = body["user"]["id"]
    trigger_id = body["trigger_id"]

    import json
    from db.queries import get_last_alert, get_account_by_channel

    alert = get_last_alert(account_id)
    if not alert or not alert.get("brief_text"):
        client.chat_postMessage(channel=am_user_id, text="No draft available for this account.")
        logger.warning(f"No draft available for account {account_id}")
        return

    try:
        brief = json.loads(alert["brief_text"])
        draft_message = brief["draft_message"]
    except (json.JSONDecodeError, KeyError) as e:
        client.chat_postMessage(channel=am_user_id, text="Couldn't read the saved draft — try regenerating the brief.")
        logger.error(f"Failed to parse stored brief for account {account_id}: {e}")
        return

    account = get_account_by_channel(channel_id)
    account_name = account["name"] if account else "this account"

    try:
        client.views_open(
            trigger_id=trigger_id,
            view={
                "type": "modal",
                "callback_id": "send_draft_modal",
                "private_metadata": json.dumps({"account_id": account_id, "channel_id": channel_id}),
                "title": {"type": "plain_text", "text": "Review & Send"},
                "submit": {"type": "plain_text", "text": "Send to Customer"},
                "close": {"type": "plain_text", "text": "Cancel"},
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"Pulse drafted this message for *{account_name}* in <#{channel_id}>. "
                                    f"Review and edit before sending — nothing goes out until you hit Send.",
                        },
                    },
                    {
                        "type": "input",
                        "block_id": "draft_block",
                        "label": {"type": "plain_text", "text": "Message"},
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "draft_input",
                            "multiline": True,
                            "initial_value": draft_message,
                        },
                    },
                ],
            },
        )
    except Exception as e:
        client.chat_postMessage(channel=am_user_id, text=f"❌ Failed to open compose window: {e}")
        logger.error(f"Failed to open send_draft modal: {e}")


@app.view("send_draft_modal")
def handle_send_draft_submission(ack, body, client, view, logger):
    ack()

    import json
    metadata = json.loads(view["private_metadata"])
    channel_id = metadata["channel_id"]
    account_id = metadata["account_id"]
    am_user_id = body["user"]["id"]

    final_text = view["state"]["values"]["draft_block"]["draft_input"]["value"]

    try:
        client.chat_postMessage(channel=channel_id, text=final_text)
        client.chat_postMessage(
            channel=am_user_id,
            text=f"✅ Sent to <#{channel_id}>:\n>{final_text}",
        )
        logger.warning(f"AM-approved draft sent to channel {channel_id} for account {account_id}")
    except Exception as e:
        client.chat_postMessage(channel=am_user_id, text=f"❌ Failed to send message: {e}")
        logger.error(f"Failed to post approved draft to {channel_id}: {e}")


@app.action("snooze_alert")
def handle_snooze(ack, body, logger):
    ack()
    account_id = int(body["actions"][0]["value"])
    snooze_account(account_id, days=7)
    logger.info(f"Snoozed alerts for account {account_id} for 7 days")


@app.action("view_history")
def handle_view_history(ack, body, client, logger):
    ack()
    account_id = int(body["actions"][0]["value"])
    history = get_health_history(account_id, limit=5)
    user_id = body["user"]["id"]
    if not history:
        client.chat_postMessage(channel=user_id, text="No health score history yet.")
        return
    lines = [f"*Health score history (last {len(history)} readings):*"]
    for h in history:
        lines.append(f"• {h['created_at'][:10]}: {h['score']}/100 — {h['urgency'].upper()}")
    client.chat_postMessage(channel=user_id, text="\n".join(lines))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_daily_signal_scan():
    logger.info("Running daily external signal scan...")
    try:
        results = scan_all_accounts()
        for name, count in results.items():
            if count:
                logger.info(f"[{name}] {count} new external signal(s) found")
    except Exception as e:
        logger.error(f"Signal scan failed: {e}")


if __name__ == "__main__":
    init_db()
    logger.info("Database initialized.")
    # Warm the bot team ID cache before handling events
    team_id = get_bot_team_id()
    logger.info(f"Bot team ID: {team_id}")

    from apscheduler.schedulers.background import BackgroundScheduler
    scheduler = BackgroundScheduler()
    from datetime import datetime as _dt
    scheduler.add_job(run_daily_signal_scan, "interval", hours=24, next_run_time=_dt.now())
    scheduler.start()
    logger.info("Scheduler started — daily external signal scan every 24h.")

    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    logger.info("Pulse is running in Socket Mode...")
    handler.start()
