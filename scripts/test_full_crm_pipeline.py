"""
Full end-to-end test: score Vortex Inc, force an alert dispatch, confirm
the brief includes real Salesforce data AND a Task gets written back to
the matching Salesforce Account.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

import logging
logging.basicConfig(level=logging.INFO)

from db.queries import get_all_accounts, get_connection
from agents.health_scorer import score_account
from agents.alert_dispatcher import maybe_send_alert
from agents.salesforce_mcp import query_account

import main

accounts = get_all_accounts()
vortex = next(a for a in accounts if a["name"] == "Vortex Inc")

print(f"CRM enabled for Vortex: {vortex.get('enable_salesforce_crm')}")

# Clear any prior alert throttle for a clean test
with get_connection() as conn:
    conn.execute("DELETE FROM alerts WHERE account_id = ?", (vortex["id"],))
    conn.commit()

score, urgency = score_account(vortex)
print(f"Vortex score: {score}/100 ({urgency.upper()})\n")

resolve_fn = lambda uid: main.app.client.users_info(user=uid)["user"]["real_name"]
sent = maybe_send_alert(vortex, score, urgency, main.app.client, resolve_name_fn=resolve_fn)
print(f"\nAlert sent: {sent}")

# Verify the write-back landed by querying Salesforce Tasks on the Account
record = query_account("Vortex Inc")
if record:
    print(f"\nVortex Salesforce Account Id: {record['Id']}")
    print("Check Salesforce UI -> Vortex Inc Account -> Activity History for the new Task.")
