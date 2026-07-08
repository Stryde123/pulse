"""
Corrects the Vortex demo setup: instead of backdating the real customer
user's own messages (which conflicted with the pattern-flag 14-day window,
since that same user sent both the champion's messages and the risky
procurement messages), assign a distinct FAKE placeholder champion_user_id
representing "the actual decision-maker" who has gone silent — exactly
matching the original narrative (Marcus silent, Sarah/procurement escalating)
without touching any real message data at all.

Steps:
1. Clear Vortex's messages (their timestamps were corrupted by the previous
   backdating attempt).
2. Re-backfill from Slack directly — recovers the TRUE original timestamps,
   since Slack itself is the source of truth and was never touched.
3. Set champion_user_id to a fake placeholder with zero messages, so
   silence calculates to full (30-day/critical) without affecting the real
   customer messages used for pattern-flag scoring.
4. Re-score.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

import logging
logging.basicConfig(level=logging.INFO)

from db.schema import get_connection
from db.queries import get_all_accounts, get_account_by_channel, update_champion
from agents.backfill import backfill_channel_history
from agents.health_scorer import score_account
from agents.champion_tracker import get_champion_metrics

import main

accounts = get_all_accounts()
vortex = next(a for a in accounts if a["name"] == "Vortex Inc")

# 1. Clear corrupted messages
with get_connection() as conn:
    conn.execute("DELETE FROM messages WHERE account_id = ?", (vortex["id"],))
    conn.commit()
print("Cleared Vortex messages (corrupted timestamps)")

# 2. Re-backfill from Slack (true source of truth)
summary = backfill_channel_history(vortex, main.app.client, main.get_bot_team_id())
print(f"Re-backfilled: {summary}")

# 3. Assign a fake, permanently-silent champion identity — distinct from
# the real user (playing "Sarah from procurement") who sent the risky
# messages. This matches the intended narrative structurally instead of
# corrupting real message timestamps.
FAKE_SILENT_CHAMPION = "U_MARCUS_SILENT"
update_champion(vortex["id"], FAKE_SILENT_CHAMPION)
print(f"Set champion_user_id to fake silent identity: {FAKE_SILENT_CHAMPION}")

# 4. Re-score
vortex = get_account_by_channel(vortex["channel_id"])
score, urgency = score_account(vortex)
metrics = get_champion_metrics(vortex)
print(f"\nVortex Inc final state: {score}/100 ({urgency.upper()})")
print(f"Champion silence: {metrics['days_silent']} days ({metrics['silence_level']})")
