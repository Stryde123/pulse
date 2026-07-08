"""
Alert dispatcher — the piece that actually watches health scores and fires
DMs to account managers. This is what turns everything built so far (pattern
detection, scoring, briefs, Block Kit cards) into something that runs itself
instead of needing to be triggered manually.
"""

import json
import logging
import threading

from db.queries import (
    is_alert_snoozed, alert_sent_recently, insert_alert,
    get_health_history, get_account_by_channel,
)
from agents.intelligence import build_full_brief
from blocks.brief_card import build_brief_card, build_fallback_text

logger = logging.getLogger(__name__)

URGENCY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}
ALERT_THRESHOLD = "medium"

# Slack Bolt processes rapid incoming events concurrently (thread pool), so
# several messages arriving within seconds of each other can each pass the
# 48h-throttle DB check before any of them finishes writing its alert row —
# causing duplicate brief generation (wasted Claude/Salesforce calls, and
# potentially duplicate DMs). A per-account lock serializes dispatch so only
# one in-flight alert attempt exists per account at a time.
_account_locks: dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()


def _get_account_lock(account_id: int) -> threading.Lock:
    with _locks_guard:
        if account_id not in _account_locks:
            _account_locks[account_id] = threading.Lock()
        return _account_locks[account_id]


def maybe_send_alert(account: dict, score: int, urgency: str, slack_client, resolve_name_fn=None) -> bool:
    """
    Called after every health score recalculation. Decides whether to fire
    a DM alert to the account's AM, and does so if conditions are met.

    Conditions to send:
      - urgency >= medium
      - not currently snoozed
      - no alert sent for this account in the last 48 hours

    Returns True if an alert was sent, False otherwise.
    """
    if URGENCY_ORDER.get(urgency, 0) < URGENCY_ORDER[ALERT_THRESHOLD]:
        return False

    lock = _get_account_lock(account["id"])
    if not lock.acquire(blocking=False):
        logger.info(f"[{account['name']}] Alert dispatch already in progress for this account — skipping")
        return False

    try:
        return _dispatch(account, score, urgency, slack_client, resolve_name_fn)
    finally:
        lock.release()


def _dispatch(account: dict, score: int, urgency: str, slack_client, resolve_name_fn=None) -> bool:
    if is_alert_snoozed(account["id"]):
        logger.info(f"[{account['name']}] Urgency={urgency} but account is snoozed — skipping alert")
        return False

    if alert_sent_recently(account["id"], hours=48):
        logger.info(f"[{account['name']}] Urgency={urgency} but alert sent within 48h — skipping")
        return False

    logger.info(f"[{account['name']}] Urgency={urgency} — generating brief for alert")
    brief = build_full_brief(account, resolve_name_fn=resolve_name_fn)
    if not brief:
        logger.error(f"[{account['name']}] Brief generation failed — cannot send alert")
        return False

    history = get_health_history(account["id"])
    blocks = build_brief_card(account, brief, score, urgency, history)
    fallback = build_fallback_text(account, urgency)

    try:
        resp = slack_client.chat_postMessage(
            channel=account["am_user_id"],
            text=fallback,
            blocks=blocks,
        )
        if not resp.get("ok"):
            logger.error(f"[{account['name']}] Failed to DM alert: {resp}")
            return False
    except Exception as e:
        logger.error(f"[{account['name']}] Exception sending alert DM: {e}")
        return False

    # Store the full brief (not just draft text) so the send_draft button
    # handler can pull the draft_message back out later.
    insert_alert(account["id"], urgency, brief_text=json.dumps(brief))
    logger.info(f"[{account['name']}] Alert sent to AM {account['am_user_id']}")

    # Write the alert back to Salesforce as an Activity Task, so the CRM
    # becomes a real record of what Pulse detected — not just a read source
    if account.get("enable_salesforce_crm"):
        _log_alert_to_salesforce(account, brief, urgency)

    return True


def _log_alert_to_salesforce(account: dict, brief: dict, urgency: str) -> None:
    from agents.salesforce_mcp import query_account, log_activity

    record = query_account(account["name"])
    if not record or not record.get("Id"):
        logger.info(f"[{account['name']}] No matching Salesforce Account — skipping activity write-back")
        return

    subject = f"Pulse Alert ({urgency.upper()}): {account['name']} relationship shift detected"
    description = (
        f"What changed: {brief.get('what_changed', '')}\n\n"
        f"Why it matters: {brief.get('why_it_matters', '')}\n\n"
        f"Suggested action: {brief.get('suggested_action', '')}"
    )
    log_activity(record["Id"], subject, description)
