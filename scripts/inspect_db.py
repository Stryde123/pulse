"""
Quick DB inspection tool — run any time to see current state.
Usage: python scripts/inspect_db.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from db.queries import get_all_accounts, get_recent_messages, get_latest_health_score, get_recent_signals

accounts = get_all_accounts()
if not accounts:
    print("No accounts registered yet.")
    sys.exit(0)

for a in accounts:
    print(f"\n{'='*60}")
    print(f"  {a['name']}  (id={a['id']})")
    print(f"  Channel: {a['channel_id']} | AM: {a['am_user_id']}")
    print(f"  Value: ${a['contract_value']:,} | Renewal: {a['renewal_date']}")

    msgs = get_recent_messages(a['id'], days=90)
    customer_msgs = [m for m in msgs if m['is_customer']]
    team_msgs     = [m for m in msgs if not m['is_customer']]
    print(f"  Messages: {len(msgs)} total ({len(customer_msgs)} customer / {len(team_msgs)} team)")
    if msgs:
        print(f"  Latest: \"{msgs[-1]['text'][:70]}\"")

    score = get_latest_health_score(a['id'])
    if score:
        print(f"  Health: {score['score']}/100 — {score['urgency'].upper()}")

    signals = get_recent_signals(a['id'], days=90)
    if signals:
        for s in signals:
            print(f"  Signal [{s['severity']}]: {s['signal_type']} — {s['headline'][:60]}")
