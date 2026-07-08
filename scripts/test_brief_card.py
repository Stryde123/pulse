"""
Renders the Block Kit brief card for Vortex Inc (critical, compound-escalated)
and DMs it to you directly so you can see the real visual output in Slack.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

from db.queries import get_all_accounts, get_latest_health_score, get_health_history
from agents.intelligence import build_full_brief
from blocks.brief_card import build_brief_card, build_fallback_text

import main  # reuses the same App instance, does not start the handler

YOUR_USER_ID = "U0BDJU3U74P"  # Tirth Shah, from earlier session logs

accounts = get_all_accounts()
vortex = next((a for a in accounts if a["name"] == "Vortex Inc"), None)
if not vortex:
    print("Vortex Inc not found — run scripts/seed_demo.py first")
    sys.exit(1)

print("Generating brief for Vortex Inc...")
brief = build_full_brief(vortex)
if not brief:
    print("Brief generation failed")
    sys.exit(1)

health = get_latest_health_score(vortex["id"])
history = get_health_history(vortex["id"])

blocks = build_brief_card(vortex, brief, health["score"], health["urgency"], history)
fallback = build_fallback_text(vortex, health["urgency"])

print(f"Card built with {len(blocks)} blocks. Posting DM to {YOUR_USER_ID}...")

resp = main.app.client.chat_postMessage(
    channel=YOUR_USER_ID,
    text=fallback,
    blocks=blocks,
)

if resp.get("ok"):
    print("Sent! Check your Slack DMs from Pulse.")
else:
    print(f"Failed to send: {resp}")
