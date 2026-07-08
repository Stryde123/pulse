"""
Test Anthropic brief generation against the Brightline SaaS demo account.
Usage: python scripts/test_brief.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

from db.queries import (
    get_all_accounts, get_recent_messages,
    get_flagged_messages, get_recent_signals, get_health_history,
)
from agents.intelligence import generate_brief, get_champion_data
import json

accounts = get_all_accounts()
account = next((a for a in accounts if a["name"] == "Brightline SaaS"), None)
if not account:
    print("Brightline SaaS not found — run seed_demo.py first")
    sys.exit(1)

print(f"Generating brief for: {account['name']} (health: see below)\n")

messages       = get_recent_messages(account["id"], days=30, customer_only=True)
flagged        = get_flagged_messages(account["id"], days=14)
signals        = get_recent_signals(account["id"], days=14)
health_history = get_health_history(account["id"])
champion_data  = get_champion_data(account, get_recent_messages(account["id"], days=30))

print(f"Champion: {champion_data['name']} | Silent {champion_data['days_silent']}d | "
      f"{champion_data['posts_this_week']} posts this week\n")

brief = generate_brief(account, messages, flagged, signals, health_history, champion_data)

if brief:
    print("=" * 60)
    print(json.dumps(brief, indent=2))
    print("=" * 60)
    print("\nDRAFT MESSAGE TO SEND:")
    print(f"\n  {brief['draft_message']}\n")
else:
    print("Brief generation failed — check logs above")
    sys.exit(1)
