"""
Champion tracker — identifies each account's primary customer contact and
tracks their engagement pattern over time.

A "champion" is the customer-side user who posts most frequently in the
account's Slack Connect channel. This module owns:
  - auto-identifying the champion when none is set
  - computing champion-specific metrics (frequency, reply rate, silence)
  - silence-level classification used by the health scorer and alerts
"""

import logging
from datetime import datetime, timezone
from typing import Callable, Optional

from db.queries import get_recent_messages, update_champion

logger = logging.getLogger(__name__)


def identify_champion(account_id: int, days: int = 30) -> Optional[str]:
    """
    Returns the user_id of the customer-side user with the most messages
    in the given window. Returns None if there are no customer messages.
    """
    messages = get_recent_messages(account_id, days=days, customer_only=True)
    if not messages:
        return None

    counts: dict[str, int] = {}
    for m in messages:
        counts[m["user_id"]] = counts.get(m["user_id"], 0) + 1

    return max(counts, key=counts.get)


def auto_update_champion(account: dict) -> Optional[str]:
    """
    If the account has no champion set, auto-identify one from message
    history and persist it. Returns the champion_id (existing or newly set),
    or None if there's not enough data yet.
    """
    if account.get("champion_user_id"):
        return account["champion_user_id"]

    champion_id = identify_champion(account["id"])
    if champion_id:
        update_champion(account["id"], champion_id)
        account["champion_user_id"] = champion_id
        logger.info(f"[{account['name']}] Auto-identified champion: {champion_id}")

    return champion_id


def get_champion_metrics(
    account: dict,
    messages: Optional[list[dict]] = None,
    resolve_name_fn: Optional[Callable[[str], str]] = None,
) -> dict:
    """
    Computes champion engagement metrics for the intelligence brief and
    health scorer.

    `messages` — optional pre-fetched 30-day message list (avoids refetching
                 when the caller already has it). If omitted, fetched here.
    `resolve_name_fn` — optional callable(user_id) -> display name. Pass a
                 Slack client lookup from main.py to avoid circular imports.
    """
    champion_id = account.get("champion_user_id")

    if messages is None:
        messages = get_recent_messages(account["id"], days=30)

    if not champion_id:
        return {
            "user_id": None,
            "name": "No champion identified",
            "days_silent": None,
            "posts_this_week": 0,
            "avg_weekly_posts": 0,
            "reply_rate": 0,
            "silence_level": None,
        }

    champion_name = champion_id
    if resolve_name_fn:
        try:
            champion_name = resolve_name_fn(champion_id)
        except Exception:
            pass

    champion_msgs = [m for m in messages if m["user_id"] == champion_id]
    customer_msgs = [m for m in messages if m["is_customer"]]

    now_ts = datetime.now(timezone.utc).timestamp()
    week_ago_ts = now_ts - 7 * 86400

    posts_this_week = sum(1 for m in champion_msgs if float(m["timestamp"]) >= week_ago_ts)
    avg_weekly_posts = len(champion_msgs) / (30 / 7) if champion_msgs else 0

    if champion_msgs:
        latest_ts = max(float(m["timestamp"]) for m in champion_msgs)
        days_silent = int((now_ts - latest_ts) / 86400)
    else:
        days_silent = 30  # never posted in window — treat as fully silent

    reply_rate = (
        int(len(champion_msgs) / len(customer_msgs) * 100) if customer_msgs else 0
    )

    return {
        "user_id": champion_id,
        "name": champion_name,
        "days_silent": days_silent,
        "posts_this_week": posts_this_week,
        "avg_weekly_posts": avg_weekly_posts,
        "reply_rate": reply_rate,
        "silence_level": _silence_level(days_silent),
    }


def _silence_level(days_silent: Optional[int]) -> Optional[str]:
    if days_silent is None:
        return None
    if days_silent >= 14:
        return "critical"
    if days_silent >= 7:
        return "warning"
    return None
