"""
Verifies Salesforce OAuth Client Credentials Flow works before wiring the
MCP server into Claude. Fetches an access token directly.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

import requests

domain = os.environ["SALESFORCE_DOMAIN"]
client_id = os.environ["SALESFORCE_CLIENT_ID"]
client_secret = os.environ["SALESFORCE_CLIENT_SECRET"]

token_url = f"https://{domain}/services/oauth2/token"

resp = requests.post(
    token_url,
    data={
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    },
)

print(f"Status: {resp.status_code}")
print(f"Response: {resp.text[:500]}")

if resp.status_code == 200:
    data = resp.json()
    print(f"\nSUCCESS — access token acquired (first 20 chars): {data['access_token'][:20]}...")
    print(f"Instance URL: {data.get('instance_url')}")
else:
    print("\nFAILED — check Client ID/Secret/Domain and that the Connected App is fully activated.")
