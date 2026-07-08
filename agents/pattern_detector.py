"""
Pattern detector — runs on every incoming customer message and returns a list
of matched risk flags. Each flag is stored as JSON in messages.flags.
"""

import re
from typing import Optional

RISK_PATTERNS = {
    # HIGH SEVERITY — strong intent signals
    "data_export": {
        "patterns": [
            "export our data", "download our data", "extract all",
            "data portability", "how do we export", "get our data out",
        ],
        "severity": 3,
        "label": "Data Export Request",
        "implication": "Evaluating alternatives or preparing to leave",
    },
    "contract_inquiry": {
        "patterns": [
            "contract terms", "cancellation policy", "notice period",
            "termination clause", "end our contract", "contract end date",
            "termination request", "terminate our contract", "terminate the contract",
            "cancel our contract", "cancel the contract", "wind down our",
            "exit the contract", "terminating our contract", "cancel our subscription",
        ],
        "severity": 3,
        "label": "Contract Term Inquiry",
        "implication": "Looking for the exit clause",
    },
    "competitor_mention": {
        "patterns": [
            "we're also looking at", "comparing with", "alternative to",
            "instead of", "switching to", "evaluating other", "evaluating alternatives",
            "evaluating other options",
        ],
        "severity": 3,
        "label": "Competitor Evaluation Signal",
        "implication": "Actively evaluating alternatives",
    },

    # MEDIUM SEVERITY — frustration and disengagement signals
    "frustration": {
        "patterns": [
            "still waiting", "still haven't", "following up again",
            "as mentioned before", "reached out last week", "no response",
            "per my last", "have not heard",
        ],
        "severity": 2,
        "label": "Repeated Frustration",
        "implication": "Unresolved friction building up",
    },
    "internal_discussion": {
        "patterns": [
            "our team has been discussing", "we've been talking internally",
            "had a meeting about", "leadership wants to",
            "our leadership", "internally reviewed",
        ],
        "severity": 2,
        "label": "Internal Discussion Signal",
        "implication": "Conversation about you happening without you",
    },
    "deprioritization": {
        "patterns": [
            "been really busy", "on the back burner", "circle back later",
            "not a priority right now", "revisit this", "back burner",
            "when we have bandwidth",
        ],
        "severity": 2,
        "label": "Deprioritization Signal",
        "implication": "Your product losing internal attention",
    },

    # LOW SEVERITY — early warning signals
    "formality_shift": {
        "patterns": [
            "to whom it may concern", "as per our agreement",
            "please advise", "per my last email", "as previously discussed",
            "for the record",
        ],
        "severity": 1,
        "label": "Tone Formality Shift",
        "implication": "Relationship becoming transactional",
    },
}


def detect_patterns(text: str) -> list[dict]:
    """
    Returns a list of matched flag dicts. Each dict:
        { "key": str, "label": str, "severity": int,
          "implication": str, "matched_phrase": str }
    Multiple patterns from the same category can match if distinct phrases hit.
    One entry per category maximum (first match wins within a category).
    """
    text_lower = text.lower()
    flags = []

    for key, spec in RISK_PATTERNS.items():
        patterns = spec.get("patterns")
        if not patterns:
            continue

        matched_phrase = _first_match(text_lower, patterns)
        if matched_phrase:
            flags.append({
                "key": key,
                "label": spec["label"],
                "severity": spec["severity"],
                "implication": spec["implication"],
                "matched_phrase": matched_phrase,
            })

    # Sort highest severity first
    flags.sort(key=lambda f: f["severity"], reverse=True)
    return flags


def _first_match(text_lower: str, patterns: list[str]) -> Optional[str]:
    for phrase in patterns:
        if phrase in text_lower:
            return phrase
    return None


# ---------------------------------------------------------------------------
# Response latency calculator
# ---------------------------------------------------------------------------

def calculate_response_latency(
    messages: list[dict],
    account_id: int,
) -> Optional[float]:
    """
    Given the recent message list for an account (ordered by timestamp ASC),
    calculates the average team response latency in hours over the last 30 days.

    Returns None if there are not enough pairs to calculate.
    """
    latencies = []

    for i in range(len(messages) - 1):
        current = messages[i]
        next_msg = messages[i + 1]

        # We want: customer message followed by a team reply
        if current["is_customer"] and not next_msg["is_customer"]:
            try:
                customer_ts = float(current["timestamp"])
                team_ts = float(next_msg["timestamp"])
                latency_hours = (team_ts - customer_ts) / 3600
                if 0 < latency_hours < 168:  # ignore gaps > 1 week (weekends etc.)
                    latencies.append(latency_hours)
            except (ValueError, TypeError):
                continue

    if not latencies:
        return None

    return sum(latencies) / len(latencies)


def calculate_latency_trend(
    recent_messages: list[dict],
    baseline_messages: list[dict],
) -> dict:
    """
    Compares response latency in the last 7 days vs the 30-day baseline.
    Returns a dict with baseline_hours, recent_hours, ratio, and a penalty score.
    """
    baseline_avg = calculate_response_latency(baseline_messages, 0)
    recent_avg = calculate_response_latency(recent_messages, 0)

    result = {
        "baseline_hours": round(baseline_avg, 2) if baseline_avg else None,
        "recent_hours": round(recent_avg, 2) if recent_avg else None,
        "ratio": None,
        "latency_penalty": 0,
    }

    if baseline_avg and recent_avg and baseline_avg > 0:
        ratio = recent_avg / baseline_avg
        result["ratio"] = round(ratio, 2)
        if ratio >= 4:
            result["latency_penalty"] = 20
        elif ratio >= 2:
            result["latency_penalty"] = 10

    return result
