import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from db.queries import get_all_accounts
from agents.champion_tracker import identify_champion, get_champion_metrics, _silence_level

accounts = get_all_accounts()
all_pass = True

print("--- identify_champion (most frequent customer poster, last 30d) ---")
for account in accounts:
    detected = identify_champion(account["id"])
    print(f"  {account['name']}: registered={account.get('champion_user_id')!r}  detected={detected!r}")

print("\n--- get_champion_metrics ---")
for account in accounts:
    metrics = get_champion_metrics(account)
    print(f"  {account['name']}: champion={metrics['user_id']} "
          f"silent={metrics['days_silent']}d level={metrics['silence_level']} "
          f"posts_this_week={metrics['posts_this_week']} reply_rate={metrics['reply_rate']}%")

print("\n--- silence_level thresholds ---")
cases = [(0, None), (6, None), (7, "warning"), (13, "warning"), (14, "critical"), (30, "critical")]
for days, expected in cases:
    got = _silence_level(days)
    ok = got == expected
    status = "PASS" if ok else "FAIL"
    if not ok:
        all_pass = False
    print(f"  [{status}] {days} days -> {got} (expected {expected})")

# Sanity check: Brightline champion (Jennifer) was seeded to go silent partway through
# the 30-day window, so as real time passes since seeding, silence only grows —
# check it's flagged as at-risk (warning or critical), not "healthy" (None).
brightline = next(a for a in accounts if a["name"] == "Brightline SaaS")
bl_metrics = get_champion_metrics(brightline)
bl_ok = bl_metrics["silence_level"] in ("warning", "critical")
print(f"\n  [{'PASS' if bl_ok else 'FAIL'}] Brightline champion is flagged at-risk "
      f"(got {bl_metrics['silence_level']}, {bl_metrics['days_silent']}d silent)")
if not bl_ok:
    all_pass = False

# Sanity check: Vortex's detected active poster should differ from the registered
# champion — the seed data intentionally simulates the champion going silent and
# being replaced by a procurement contact partway through.
vortex = next(a for a in accounts if a["name"] == "Vortex Inc")
vortex_detected = identify_champion(vortex["id"])
drift_ok = vortex_detected != vortex.get("champion_user_id")
print(f"  [{'PASS' if drift_ok else 'FAIL'}] Vortex shows champion drift "
      f"(registered={vortex.get('champion_user_id')}, now posting={vortex_detected})")
if not drift_ok:
    all_pass = False

print()
print("All champion tracker tests passed!" if all_pass else "SOME TESTS FAILED.")
sys.exit(0 if all_pass else 1)
