"""
Creates (or updates) Salesforce Account records matching Pulse's 3 demo
companies, so the CRM lookup during the demo returns real, narrative-fitting
data instead of "no match found."

Uses the OAuth Client Credentials Flow we already have working (same creds
used for the earlier REST verification) — direct REST, no MCP needed here
since this is one-time setup data seeding, not part of Pulse's runtime path.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

import requests

domain = os.environ["SALESFORCE_DOMAIN"]
client_id = os.environ["SALESFORCE_CLIENT_ID"]
client_secret = os.environ["SALESFORCE_CLIENT_SECRET"]

token_resp = requests.post(
    f"https://{domain}/services/oauth2/token",
    data={"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret},
)
token_resp.raise_for_status()
token_data = token_resp.json()
access_token = token_data["access_token"]
instance_url = token_data["instance_url"]
headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}

# Fields chosen to fit each account's demo narrative
DEMO_ACCOUNTS = [
    {
        "Name": "Acme Corp",
        "Industry": "Manufacturing",
        "AnnualRevenue": 45000000,
        "NumberOfEmployees": 300,
        "Description": "Healthy, stable customer. Regular engagement, positive sentiment.",
    },
    {
        "Name": "Brightline SaaS",
        "Industry": "Technology",
        "AnnualRevenue": 12000000,
        "NumberOfEmployees": 85,
        "Description": "Mid-market SaaS company. Recently announced workforce reduction.",
    },
    {
        "Name": "Vortex Inc",
        "Industry": "Energy",
        "AnnualRevenue": 210000000,
        "NumberOfEmployees": 1200,
        "Description": "Large enterprise account. Recent leadership change and hiring freeze.",
    },
]

for acct in DEMO_ACCOUNTS:
    # Check if it already exists (idempotent — safe to re-run)
    query = f"SELECT Id FROM Account WHERE Name = '{acct['Name']}' LIMIT 1"
    q_resp = requests.get(
        f"{instance_url}/services/data/v60.0/query",
        headers=headers,
        params={"q": query},
    )
    q_resp.raise_for_status()
    records = q_resp.json().get("records", [])

    if records:
        account_id = records[0]["Id"]
        update_resp = requests.patch(
            f"{instance_url}/services/data/v60.0/sobjects/Account/{account_id}",
            headers=headers,
            json={k: v for k, v in acct.items() if k != "Name"},
        )
        if update_resp.status_code in (200, 204):
            print(f"  Updated existing Account: {acct['Name']} (Id={account_id})")
        else:
            print(f"  FAILED to update {acct['Name']}: {update_resp.status_code} {update_resp.text[:200]}")
    else:
        create_resp = requests.post(
            f"{instance_url}/services/data/v60.0/sobjects/Account",
            headers=headers,
            json=acct,
        )
        if create_resp.status_code == 201:
            account_id = create_resp.json()["id"]
            print(f"  Created Account: {acct['Name']} (Id={account_id})")
        else:
            print(f"  FAILED to create {acct['Name']}: {create_resp.status_code} {create_resp.text[:200]}")

print("\nDone. Verify with: SELECT Name, Industry, AnnualRevenue FROM Account WHERE Name IN "
      "('Acme Corp','Brightline SaaS','Vortex Inc')")
