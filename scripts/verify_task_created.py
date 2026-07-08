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
token_data = token_resp.json()
access_token = token_data["access_token"]
instance_url = token_data["instance_url"]

query = "SELECT Subject, Description, ActivityDate, WhatId FROM Task WHERE Subject LIKE 'Pulse Alert%' ORDER BY CreatedDate DESC LIMIT 5"
resp = requests.get(
    f"{instance_url}/services/data/v60.0/query",
    headers={"Authorization": f"Bearer {access_token}"},
    params={"q": query},
)
records = resp.json().get("records", [])
print(f"Found {len(records)} Pulse-created Task(s):\n")
for r in records:
    print(f"  Subject: {r['Subject']}")
    print(f"  WhatId (Account): {r['WhatId']}")
    print(f"  Description: {r['Description'][:150]}...")
    print()
