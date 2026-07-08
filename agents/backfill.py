"""
Channel history backfill — runs when an account is registered so Pulse isn't
starting blind on relationships that predate the bot joining the channel.

Uses conversations.history (channels:history scope, already granted) to pull
the full message backlog, classifies customer vs. team side per message,
runs pattern detection, then does one full champion + health score pass on
the reconstructed history.
"""

import logging
from typing import Optional

from db.queries import insert_message
from agents.pattern_detector import detect_patterns

logger = logging.getLogger(__name__)

MAX_PAGES = 10       # safety cap: up to ~2000 messages per channel
PAGE_SIZE = 200


def backfill_channel_history(account: dict, slack_client, bot_team_id: str) -> dict:
    """
    Pulls the full message history for account['channel_id'], stores every
    message with correct customer/team tagging and pattern flags, then
    updates champion identification and recomputes the health score.

    Returns a summary dict: {messages_imported, flagged, score, urgency}
    """
    channel_id = account["channel_id"]
    user_team_cache: dict[str, str] = {}

    def resolve_team(user_id: str) -> str:
        if user_id not in user_team_cache:
            try:
                info = slack_client.users_info(user=user_id)
                user_team_cache[user_id] = info["user"].get("team_id", bot_team_id)
            except Exception as e:
                logger.warning(f"Could not resolve team for user {user_id}: {e}")
                user_team_cache[user_id] = bot_team_id
        return user_team_cache[user_id]

    cursor: Optional[str] = None
    imported = 0
    flagged_count = 0
    pages = 0

    while pages < MAX_PAGES:
        try:
            resp = slack_client.conversations_history(
                channel=channel_id, cursor=cursor, limit=PAGE_SIZE
            )
        except Exception as e:
            logger.error(f"[{account['name']}] Backfill fetch failed: {e}")
            break

        for m in resp.get("messages", []):
            if m.get("subtype"):
                continue

            user_id = m.get("user")
            text = (m.get("text") or "").strip()
            ts = m.get("ts")
            if not user_id or not text or not ts:
                continue

            sender_team = m.get("user_team") or resolve_team(user_id)
            is_customer = sender_team != bot_team_id

            flags = detect_patterns(text) if is_customer else []
            insert_message(
                account_id=account["id"],
                channel_id=channel_id,
                user_id=user_id,
                text=text,
                is_customer=is_customer,
                timestamp=ts,
                flags=flags,
            )
            imported += 1
            if flags:
                flagged_count += 1

        pages += 1
        if not resp.get("has_more"):
            break
        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

    logger.info(f"[{account['name']}] Backfill complete: {imported} messages imported "
                f"({flagged_count} flagged) across {pages} page(s)")

    # Now that full history is in, identify the champion (if this account has
    # champion tracking enabled) and score for real
    from agents.champion_tracker import auto_update_champion
    from agents.health_scorer import score_account

    if account.get("enable_champion_tracking"):
        auto_update_champion(account)
    score, urgency = score_account(account)

    return {
        "messages_imported": imported,
        "flagged": flagged_count,
        "score": score,
        "urgency": urgency,
    }
