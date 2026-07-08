"""
Completes Vortex Inc's critical demo narrative:
1. Re-adds the external signal (leadership change) that was wiped when the
   fake seeded account was retired.
2. Backdates the champion's last message timestamp so silence duration
   calculates to 15 days (crossing the 14-day critical threshold) — the one
   deliberate exception since real elapsed time isn't available before the
   demo recording date. Everything else about this account is fully live.
3. Clears any existing alert record so the next score recalculation can
   fire a clean, fresh CRITICAL alert during the actual demo.
4. Re-scores and reports the result.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

import logging
logging.basicConfig(level=logging.INFO)

from datetime import datetime, timedelta, timezone
from db.schema import get_connection
from db.queries import get_all_accounts, insert_signal
from agents.champion_tracker import identify_champion, get_champion_metrics
from agents.health_scorer import score_account
from db.queries import get_recent_signals

accounts = get_all_accounts()
vortex = next(a for a in accounts if a["name"] == "Vortex Inc")

# 1. Re-add external signal (skip if already present from a prior run)
existing_signals = get_recent_signals(vortex["id"], days=30)
if any(s["signal_type"] == "leadership_change" for s in existing_signals):
    print("External signal already present — skipping duplicate insert")
else:
    insert_signal(
        vortex["id"],
        "leadership_change",
        "Vortex Inc CEO Marcus Webb steps down, CFO named interim",
        None,
        3,
    )
    print("Added external signal: leadership_change (severity 3)")

# 2. Backdate champion's last message
champion_id = identify_champion(vortex["id"])
if not champion_id:
    print("No champion identified yet — make sure customer messages were sent first.")
    sys.exit(1)

with get_connection() as conn:
    # Backdate ALL of the champion's messages (they were sent live within
    # seconds of each other, so leaving even one at "now" would still read
    # as zero days silent). Spread them a few minutes apart, ending 15 days
    # ago, so relative order is preserved.
    rows = conn.execute(
        """SELECT id FROM messages WHERE account_id = ? AND user_id = ?
           ORDER BY CAST(timestamp AS REAL) ASC""",
        (vortex["id"], champion_id),
    ).fetchall()

    base_ts = datetime.now(timezone.utc) - timedelta(days=15)
    for i, row in enumerate(rows):
        msg_ts = base_ts - timedelta(minutes=(len(rows) - i) * 5)
        conn.execute(
            "UPDATE messages SET timestamp = ? WHERE id = ?",
            (str(msg_ts.timestamp()), row[0]),
        )
    conn.commit()
    print(f"Backdated all {len(rows)} of champion ({champion_id})'s messages, ending 15 days ago")

# 3. Clear existing alert throttle for a clean demo-day fire
with get_connection() as conn:
    conn.execute("DELETE FROM alerts WHERE account_id = ?", (vortex["id"],))
    conn.commit()
print("Cleared alert throttle for Vortex Inc")

# 4. Re-score
score, urgency = score_account(vortex)
metrics = get_champion_metrics(vortex)
print(f"\nVortex Inc final state: {score}/100 ({urgency.upper()})")
print(f"Champion silence: {metrics['days_silent']} days ({metrics['silence_level']})")
