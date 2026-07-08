"""
1. Points all 3 demo accounts' am_user_id at your real Slack user ID so
   alert DMs actually deliver during the demo.
2. Directly tests Salesforce write-back (log_activity) against the real
   Vortex Inc Account created earlier, in isolation from the slow full
   pipeline, to confirm the mechanism itself works.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

import logging
logging.basicConfig(level=logging.INFO)

from db.schema import get_connection
from db.queries import get_all_accounts
from agents.salesforce_mcp import log_activity

REAL_AM_USER_ID = "U0BDJU3U74P"  # Tirth Shah

with get_connection() as conn:
    conn.execute(
        "UPDATE accounts SET am_user_id = ? WHERE name IN ('Acme Corp','Brightline SaaS','Vortex Inc')",
        (REAL_AM_USER_ID,),
    )
    conn.commit()
print(f"Updated demo accounts' AM to real Slack user {REAL_AM_USER_ID}\n")

# Directly test write-back using the known Vortex Inc Salesforce Account Id
VORTEX_SF_ID = "001g500000UcLLVAA3"
print("Testing Salesforce write-back (log_activity)...")
success = log_activity(
    VORTEX_SF_ID,
    "Pulse Alert (CRITICAL): Vortex Inc relationship shift detected [TEST]",
    "What changed: Champion went silent, procurement took over with hostile signals.\n\n"
    "Why it matters: CEO departure + data export request + contract termination inquiry.\n\n"
    "Suggested action: Escalate to executive sponsor immediately.",
)
print(f"\nWrite-back success: {success}")
if success:
    print("Check Salesforce -> Vortex Inc Account -> Activity History for the new Task.")
