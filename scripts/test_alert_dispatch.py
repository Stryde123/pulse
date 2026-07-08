"""
Tests the live alert dispatch path against the real Test Account channel:
forces a high urgency to trigger maybe_send_alert(), which should DM you
(the registered AM) a real Block Kit card. Then click "Send Draft Message"
in Slack to test that button handler posts to the channel for real.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

from db.queries import get_all_accounts, get_connection
from agents.alert_dispatcher import maybe_send_alert

import main

account = next((a for a in get_all_accounts() if a["name"] == "Test Account"), None)
if not account:
    print("Test Account not found")
    sys.exit(1)

# Clear any prior alert throttle/snooze state for a clean test
with get_connection() as conn:
    conn.execute("DELETE FROM alerts WHERE account_id = ?", (account["id"],))
    conn.commit()

print(f"Forcing alert dispatch for {account['name']} (urgency=high)...")
resolve_fn = lambda uid: main.app.client.users_info(user=uid)["user"]["real_name"]

sent = maybe_send_alert(account, score=45, urgency="high", slack_client=main.app.client, resolve_name_fn=resolve_fn)
print(f"Alert sent: {sent}")

if sent:
    print("\nCheck your Slack DMs — you should see the brief card.")
    print("Click 'Send Draft Message' to test the button handler posts to #test2.")
else:
    print("Alert was NOT sent — check throttle/snooze state or brief generation logs above.")
