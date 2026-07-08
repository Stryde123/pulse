"""
Test health scorer against the three seeded demo accounts.
Expected: Acme=low, Brightline=medium/high, Vortex=critical
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from db.queries import get_all_accounts
from agents.health_scorer import score_account, _factor_flags, _factor_signals, _factor_champion

EXPECTED = {
    "Acme Corp":       ("low",              lambda s: s >= 75),
    "Brightline SaaS": ("medium or high",   lambda s: 30 <= s < 75),
    "Vortex Inc":      ("high or critical", lambda s: s < 50),
}

accounts = get_all_accounts()
all_pass = True

print("Scoring all accounts...\n")
for account in accounts:
    score, urgency = score_account(account)
    name = account["name"]
    if name in EXPECTED:
        label, check = EXPECTED[name]
        ok = check(score)
        status = "PASS" if ok else "FAIL"
        if not ok:
            all_pass = False
        print(f"  [{status}] {name}: {score}/100 ({urgency.upper()})  expected={label}")
    else:
        print(f"  [INFO] {name}: {score}/100 ({urgency.upper()})")

print()
print("All scorer tests passed!" if all_pass else "SOME TESTS FAILED.")
sys.exit(0 if all_pass else 1)
