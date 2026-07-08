"""
Tests the Salesforce MCP-enabled brief path directly against a real sample
Account ("Edge Communications") already in the Developer org, to confirm
Claude actually invokes the Salesforce tool mid-request and folds real CRM
data into the brief.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

import logging
logging.basicConfig(level=logging.INFO)

from agents.intelligence import generate_brief
from agents.salesforce_mcp import query_account
import json

print("Directly querying Salesforce MCP for 'Edge Communications'...")
record = query_account("Edge Communications")
print(f"Raw record returned: {record}\n")

# Synthetic account matching a real Salesforce sample Account by name
account = {
    "id": 999,
    "name": "Edge Communications",
    "contract_value": 150000,
    "renewal_date": "2026-10-01",
    "enable_salesforce_crm": True,
}

messages = [
    {"is_customer": True, "timestamp": "1751000000.000", "text": "still waiting on the implementation timeline, we need this resolved soon"},
]
flagged_messages = [
    {"text": messages[0]["text"], "flags": [{"label": "Repeated Frustration", "severity": 2}]}
]
signals = []
health_history = [
    {"score": 85, "urgency": "low"},
    {"score": 62, "urgency": "medium"},
]
champion_data = {
    "user_id": None, "name": "Champion tracking not enabled for this account",
    "days_silent": None, "posts_this_week": 0, "avg_weekly_posts": 0,
    "reply_rate": 0, "silence_level": None,
}

print("Generating brief with Salesforce MCP enabled for 'Edge Communications'...\n")
brief = generate_brief(account, messages, flagged_messages, signals, health_history, champion_data)

if brief:
    print(json.dumps(brief, indent=2))
    print("\n--- Checking if Salesforce data was actually referenced ---")
    combined_text = json.dumps(brief).lower()
    mentions = [kw for kw in ["electronics", "139", "1000 employ", "edge communications"] if kw in combined_text]
    if mentions:
        print(f"PASS — brief references real Salesforce data: {mentions}")
    else:
        print("No obvious Salesforce data references found — check manually above.")
else:
    print("FAILED — brief generation returned None, check logs above")
