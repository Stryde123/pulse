"""
Uses the OAuth token to run a real SOQL query against Account data,
confirming there's sample data to work with before wiring up MCP.
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
token_data = token_resp.json()
access_token = token_data["access_token"]
instance_url = token_data["instance_url"]

query = "SELECT Id, Name, Industry, AnnualRevenue, NumberOfEmployees FROM Account LIMIT 10"
resp = requests.get(
    f"{instance_url}/services/data/v60.0/query",
    headers={"Authorization": f"Bearer {access_token}"},
    params={"q": query},
)

print(f"Status: {resp.status_code}")
if resp.status_code == 200:
    records = resp.json().get("records", [])
    print(f"\nFound {len(records)} Account records:\n")
    for r in records:
        print(f"  {r['Name']} | Industry: {r.get('Industry')} | Revenue: {r.get('AnnualRevenue')} | Employees: {r.get('NumberOfEmployees')}")
else:
    print(resp.text[:500])
