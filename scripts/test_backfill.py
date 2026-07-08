"""
Test channel history backfill against the real #test2 channel.
Wipes Test Account's existing messages first so we can see backfill import
the full history from scratch, simulating "bot added 3 months in."
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

from db.queries import get_all_accounts, get_recent_messages, insert_account, get_account_by_channel
from db.schema import get_connection
from agents.backfill import backfill_channel_history

# Import main.py's App instance without triggering handler.start()
import main

KNOWN_TEST_CHANNEL = "C0BECSB1C3H"  # #test2, from earlier session logs
KNOWN_AM_USER = "U0BDJU3U74P"

account = next((a for a in get_all_accounts() if a["name"] == "Test Account"), None)
if not account:
    account = get_account_by_channel(KNOWN_TEST_CHANNEL)
if not account:
    print(f"Re-registering Test Account against known channel {KNOWN_TEST_CHANNEL}...")
    insert_account(
        name="Test Account",
        channel_id=KNOWN_TEST_CHANNEL,
        am_user_id=KNOWN_AM_USER,
    )
    account = get_account_by_channel(KNOWN_TEST_CHANNEL)

before_count = len(get_recent_messages(account["id"], days=365))
print(f"Messages in DB before backfill: {before_count}")

# Wipe existing messages for this account to simulate a fresh bot-join backfill
with get_connection() as conn:
    conn.execute("DELETE FROM messages WHERE account_id = ?", (account["id"],))
    conn.execute("DELETE FROM health_scores WHERE account_id = ?", (account["id"],))
    conn.commit()
print("Wiped existing messages + health scores for Test Account (simulating fresh bot join)\n")

bot_team_id = main.get_bot_team_id()
print(f"Bot team ID: {bot_team_id}")
print(f"Backfilling channel {account['channel_id']}...\n")

summary = backfill_channel_history(account, main.app.client, bot_team_id)

print("Backfill summary:")
print(f"  Messages imported: {summary['messages_imported']}")
print(f"  Flagged: {summary['flagged']}")
print(f"  Health score: {summary['score']}/100 ({summary['urgency'].upper()})")

after_count = len(get_recent_messages(account["id"], days=365))
print(f"\nMessages in DB after backfill: {after_count}")

if summary["messages_imported"] > 0:
    print("\nPASS — backfill successfully reconstructed channel history")
else:
    print("\nFAIL — no messages were imported")
    sys.exit(1)
