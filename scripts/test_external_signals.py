import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

from agents.external_signals import _fetch_news_rss, scan_account
from db.queries import get_all_accounts

# Quick RSS fetch sanity check against a real, well-known company
print("Testing RSS fetch against a real company...")
items = _fetch_news_rss("Salesforce", "layoffs")
print(f"  Found {len(items)} headlines")
for item in items[:2]:
    print(f"   - {item['headline']}")

print()
print("Testing full scan pipeline (fetch + classify) on demo accounts...")
accounts = get_all_accounts()
for account in accounts:
    if account["name"] in ("Brightline SaaS", "Vortex Inc"):
        # Skip full scan (would hit real news for fake companies, likely 0 results)
        # Just confirm the function runs without error
        try:
            count = scan_account(account)
            print(f"  {account['name']}: scan completed, {count} new signals")
        except Exception as e:
            print(f"  {account['name']}: FAILED — {e}")
