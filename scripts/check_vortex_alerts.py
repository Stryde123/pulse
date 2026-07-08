import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from db.schema import get_connection
from db.queries import get_all_accounts

vortex = next(a for a in get_all_accounts() if a["name"] == "Vortex Inc")
with get_connection() as conn:
    rows = conn.execute(
        "SELECT id, urgency, snoozed_until, created_at FROM alerts WHERE account_id = ? ORDER BY created_at DESC",
        (vortex["id"],),
    ).fetchall()

print(f"Alerts for Vortex Inc (account_id={vortex['id']}):")
for r in rows:
    print(f"  id={r[0]} urgency={r[1]} snoozed_until={r[2]} created_at={r[3]}")
