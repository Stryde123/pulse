import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from db.schema import get_connection
from db.queries import update_message_flags
from agents.pattern_detector import detect_patterns
from agents.health_scorer import score_account
from db.queries import get_all_accounts

text = "Please confirm receipt of our termination request"
flags = detect_patterns(text)
print(f"Detected flags now: {[f['label'] for f in flags]}")

if flags:
    update_message_flags(64, flags)
    print("Updated message 64 with correct flags")

vortex = next(a for a in get_all_accounts() if a["name"] == "Vortex Inc")
score, urgency = score_account(vortex)
print(f"Vortex re-scored: {score}/100 ({urgency.upper()})")
