"""
Day 8 test — verifies compound risk escalation and the unified brief builder.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

from db.queries import get_all_accounts
from agents.health_scorer import score_account, _has_compound_risk
from agents.intelligence import build_full_brief
import json

accounts = get_all_accounts()
all_pass = True

print("--- Compound risk detection ---")
for account in accounts:
    if account["name"] not in ("Acme Corp", "Brightline SaaS", "Vortex Inc"):
        continue
    compound = _has_compound_risk(account["id"], account.get("champion_user_id"))
    print(f"  {account['name']}: compound_risk={compound}")

# Vortex should trigger compound risk (sev3 flags + critical champion silence + sev3 signal)
vortex = next(a for a in accounts if a["name"] == "Vortex Inc")
vortex_compound = _has_compound_risk(vortex["id"], vortex.get("champion_user_id"))
ok = vortex_compound is True
print(f"\n  [{'PASS' if ok else 'FAIL'}] Vortex triggers compound risk escalation")
if not ok:
    all_pass = False

# Re-score all accounts and confirm Vortex lands at CRITICAL (escalated from HIGH)
print("\n--- Re-scoring with escalation applied ---")
for account in accounts:
    if account["name"] not in ("Acme Corp", "Brightline SaaS", "Vortex Inc"):
        continue
    score, urgency = score_account(account)
    print(f"  {account['name']}: {score}/100 ({urgency.upper()})")
    if account["name"] == "Vortex Inc":
        vortex_escalated = urgency == "critical"
        print(f"  [{'PASS' if vortex_escalated else 'FAIL'}] Vortex urgency == CRITICAL after escalation")
        if not vortex_escalated:
            all_pass = False

print("\n--- Unified brief builder (Vortex — should reflect critical urgency) ---")
brief = build_full_brief(vortex)
if brief:
    print(f"  champion_status: {brief['champion_status']}")
    print(f"  urgency_reasoning: {brief['urgency_reasoning']}")
    print(f"  suggested_action: {brief['suggested_action'][:100]}...")
else:
    print("  [FAIL] Brief generation returned None")
    all_pass = False

print()
print("All Day 8 tests passed!" if all_pass else "SOME TESTS FAILED.")
sys.exit(0 if all_pass else 1)
