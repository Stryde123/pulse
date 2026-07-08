import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

import logging
logging.basicConfig(level=logging.INFO)

from db.queries import get_account_by_channel
from agents.backfill import backfill_channel_history

import main

CHANNEL_ID = "C0BFMRL9W73"

account = get_account_by_channel(CHANNEL_ID)
if not account:
    print("Account not found for that channel")
    sys.exit(1)

print(f"Re-running backfill for {account['name']}...")
summary = backfill_channel_history(account, main.app.client, main.get_bot_team_id())
print(f"Backfill summary: {summary}")
