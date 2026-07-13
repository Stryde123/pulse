"""
Health score engine — calculates a 0-100 score for each monitored account.
Called on every new message and also on a scheduler tick (Day 6).

Scoring factors (spec section 7):
  Factor 1 — Message frequency vs baseline  (-30 max)
  Factor 2 — Customer response latency       (-20 max)
  Factor 3 — Pattern flags                   (-30 max)
  Factor 4 — Champion activity               (-15 max)
  Factor 5 — External signals                (-20 max)
"""

import logging
from datetime import datetime, timedelta, timezone

from db.queries import (
    get_recent_messages,
    get_message_count_in_window,
    get_flagged_messages,
    get_recent_signals,
    get_latest_health_score,
    insert_health_score,
    get_health_history,
)
from agents.pattern_detector import calculate_latency_trend

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def _compute(account: dict) -> tuple[int, str, dict]:
    """Shared by score_account and get_score_breakdown — computes but does
    not persist. Returns (score, urgency, breakdown)."""
    account_id = account["id"]
    champion_id = account.get("champion_user_id")
    champion_enabled = bool(account.get("enable_champion_tracking"))
    signals_enabled = bool(account.get("enable_external_signals"))

    score = 100
    breakdown = {}

    # Factor 1 — message frequency
    f1 = _factor_frequency(account_id)
    score += f1
    breakdown["frequency"] = f1

    # Factor 2 — response latency
    f2 = _factor_latency(account_id)
    score += f2
    breakdown["latency"] = f2

    # Factor 3 — pattern flags
    f3 = _factor_flags(account_id)
    score += f3
    breakdown["flags"] = f3

    # Factor 4 — champion activity (only if this account has champion tracking enabled)
    f4 = _factor_champion(account_id, champion_id) if champion_enabled else 0
    score += f4
    breakdown["champion"] = f4

    # Factor 5 — external signals (only if this account has signal monitoring enabled)
    f5 = _factor_signals(account_id) if signals_enabled else 0
    score += f5
    breakdown["signals"] = f5

    score = max(0, min(100, score))
    urgency = _urgency(score)

    # Compound risk escalation: if the account is simultaneously showing a
    # high-intent pattern flag, a critically silent champion, AND a severe
    # external signal, that combination is a stronger churn predictor than
    # any single factor's score deduction captures on its own — bump urgency
    # up one level regardless of the raw score. Requires both toggles on,
    # since the signal is meaningless without champion + external data.
    escalated_from = None
    if champion_enabled and signals_enabled and _has_compound_risk(account_id, champion_id):
        escalated = _escalate(urgency)
        if escalated != urgency:
            escalated_from = urgency
            logger.warning(
                f"[{account['name']}] Compound risk detected — "
                f"escalating urgency {urgency.upper()} -> {escalated.upper()}"
            )
        urgency = escalated

    breakdown["compound_risk_escalated_from"] = escalated_from

    logger.info(
        f"[{account['name']}] Health score: {score}/100 ({urgency.upper()}) "
        f"breakdown={breakdown}"
    )

    return score, urgency, breakdown


def score_account(account: dict) -> tuple[int, str]:
    """
    Recalculates health for one account and persists the result.
    Returns (score, urgency).
    """
    score, urgency, _ = _compute(account)
    insert_health_score(account["id"], score, urgency)
    return score, urgency


def get_score_breakdown(account: dict) -> dict:
    """
    Read-only variant for @Pulse report — same computation as score_account,
    but doesn't write a new health_scores row. Returns score, urgency, and
    the per-factor breakdown.
    """
    score, urgency, breakdown = _compute(account)
    return {"score": score, "urgency": urgency, "breakdown": breakdown}


def _has_compound_risk(account_id: int, champion_id: str | None) -> bool:
    """
    True only when ALL THREE hold at once:
      - at least one severity-3 pattern flag in the last 14 days
      - champion silence_level == 'critical' (14+ days silent)
      - at least one severity-3 external signal in the last 14 days
    Requiring all three (not just any one) keeps this a genuine compound
    signal rather than double-penalizing accounts that already score low
    for a single reason.
    """
    flagged = get_flagged_messages(account_id, days=14)
    has_sev3_flag = any(
        f["severity"] == 3 for m in flagged for f in m.get("flags", [])
    )
    if not has_sev3_flag:
        return False

    signals = get_recent_signals(account_id, days=14)
    has_sev3_signal = any(s["severity"] == 3 for s in signals)
    if not has_sev3_signal:
        return False

    if not champion_id:
        return False

    from agents.champion_tracker import get_champion_metrics
    metrics = get_champion_metrics({"id": account_id, "champion_user_id": champion_id})
    return metrics["silence_level"] == "critical"


def _escalate(urgency: str) -> str:
    order = ["low", "medium", "high", "critical"]
    idx = order.index(urgency)
    return order[min(idx + 1, len(order) - 1)]


# ---------------------------------------------------------------------------
# Factor 1 — Message frequency vs 30-day baseline
# ---------------------------------------------------------------------------

def _factor_frequency(account_id: int) -> int:
    count_7d  = get_message_count_in_window(account_id, days=7,  customer_only=True)
    count_30d = get_message_count_in_window(account_id, days=30, customer_only=True)

    if count_30d == 0:
        return 0

    # Weekly baseline = 30d total / (30/7)
    baseline_weekly = count_30d / (30 / 7)
    if baseline_weekly == 0:
        return 0

    drop_ratio = 1 - (count_7d / baseline_weekly)

    if drop_ratio >= 0.80:
        return -30
    elif drop_ratio >= 0.50:
        # Linear interpolation between -20 and -30
        return -20 - int((drop_ratio - 0.50) / 0.30 * 10)
    elif drop_ratio >= 0.25:
        return -10
    return 0


# ---------------------------------------------------------------------------
# Factor 2 — Customer response latency trend
# ---------------------------------------------------------------------------

def _factor_latency(account_id: int) -> int:
    baseline = get_recent_messages(account_id, days=30)
    recent   = get_recent_messages(account_id, days=7)
    trend    = calculate_latency_trend(recent, baseline)
    contribution = -trend["latency_penalty"]

    # A team reply shouldn't need enough message history to compute a
    # meaningful baseline/recent ratio before it counts for anything — any
    # team engagement in the last 7 days earns a flat, guaranteed bonus on
    # top of the ratio comparison, so a single AM response has immediate,
    # unconditional positive impact rather than only showing up once
    # there's enough data for the trend comparison to diverge.
    team_engaged = any(not m["is_customer"] for m in recent)
    if team_engaged:
        contribution += 5

    return min(contribution, 15)


# ---------------------------------------------------------------------------
# Factor 3 — Pattern flags in last 14 days
# ---------------------------------------------------------------------------

def _factor_flags(account_id: int) -> int:
    flagged = get_flagged_messages(account_id, days=14)

    # Collect all individual flags across messages
    all_flags: list[dict] = []
    for msg in flagged:
        all_flags.extend(msg.get("flags", []))

    sev3 = [f for f in all_flags if f["severity"] == 3]
    sev2 = [f for f in all_flags if f["severity"] == 2]
    sev1 = [f for f in all_flags if f["severity"] == 1]

    penalty = 0
    penalty += min(len(sev3), 2) * 15   # -15 each, max 2 → -30
    penalty += min(len(sev2), 3) * 8    # -8 each, max 3 → -24, capped at -20
    penalty += min(len(sev1), 3) * 3    # -3 each, max 3 → -9, capped at -10

    # Apply caps per severity tier
    sev2_penalty = min(min(len(sev2), 3) * 8, 20)
    sev1_penalty = min(min(len(sev1), 3) * 3, 10)
    total = min(len(sev3), 2) * 15 + sev2_penalty + sev1_penalty

    return -min(total, 30)


# ---------------------------------------------------------------------------
# Factor 4 — Champion activity
# ---------------------------------------------------------------------------

def _factor_champion(account_id: int, champion_id: str | None) -> int:
    if not champion_id:
        return 0

    from agents.champion_tracker import get_champion_metrics

    account_stub = {"id": account_id, "champion_user_id": champion_id}
    metrics = get_champion_metrics(account_stub)

    penalty = 0
    if metrics["silence_level"] == "critical":
        penalty = 15
    elif metrics["silence_level"] == "warning":
        penalty = 8

    # Champion-to-colleague reply ratio: if champion is <30% of customer msgs
    # while there's enough volume to judge, that's a minor additional signal
    all_msgs = get_recent_messages(account_id, days=30)
    customer_msgs = [m for m in all_msgs if m["is_customer"]]
    if customer_msgs:
        champion_msg_count = sum(1 for m in customer_msgs if m["user_id"] == champion_id)
        champion_ratio = champion_msg_count / len(customer_msgs)
        if champion_ratio < 0.30 and len(customer_msgs) >= 5:
            penalty += 5

    return -min(penalty, 15)


# ---------------------------------------------------------------------------
# Factor 5 — External signals
# ---------------------------------------------------------------------------

def _factor_signals(account_id: int) -> int:
    signals = get_recent_signals(account_id, days=14)
    if not signals:
        return 0

    penalty = 0
    for sig in signals:
        sev = sig.get("severity", 1)
        if sev == 3:
            penalty += 15
        elif sev == 2:
            penalty += 10
        else:
            penalty += 5

    return -min(penalty, 20)


# ---------------------------------------------------------------------------
# Urgency thresholds
# ---------------------------------------------------------------------------

def _urgency(score: int) -> str:
    if score >= 75:
        return "low"
    elif score >= 50:
        return "medium"
    elif score >= 30:
        return "high"
    return "critical"


# ---------------------------------------------------------------------------
# Convenience: score all accounts
# ---------------------------------------------------------------------------

def score_all_accounts() -> list[dict]:
    from db.queries import get_all_accounts
    accounts = get_all_accounts()
    results = []
    for account in accounts:
        score, urgency = score_account(account)
        results.append({"account": account["name"], "score": score, "urgency": urgency})
    return results
