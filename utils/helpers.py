from datetime import datetime, timezone


def slack_ts_to_datetime(ts: str) -> datetime:
    return datetime.fromtimestamp(float(ts), tz=timezone.utc)


def days_since(dt: datetime) -> int:
    now = datetime.now(tz=timezone.utc)
    return (now - dt).days


def format_messages(messages: list[dict]) -> str:
    lines = []
    for m in messages:
        role = "Customer" if m["is_customer"] else "Team"
        lines.append(f"[{m['timestamp']}] {role}: {m['text']}")
    return "\n".join(lines) if lines else "(no messages)"


def format_flags(flagged_messages: list[dict]) -> str:
    all_flags = []
    for m in flagged_messages:
        for flag in m.get("flags", []):
            all_flags.append(f"• [{flag['label']}] \"{m['text'][:80]}\"")
    return "\n".join(all_flags) if all_flags else "(no flags detected)"


def format_signals(signals: list[dict]) -> str:
    if not signals:
        return "(no external signals)"
    lines = []
    for s in signals:
        sev = "!!!" if s["severity"] == 3 else ("!!" if s["severity"] == 2 else "!")
        lines.append(f"[{sev} {s['signal_type'].upper()}] {s['headline']}")
    return "\n".join(lines)
