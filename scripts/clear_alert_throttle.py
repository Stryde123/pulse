import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from db.schema import get_connection
from db.queries import get_all_accounts

name = sys.argv[1] if len(sys.argv) > 1 else "Vortex Inc"
account = next(a for a in get_all_accounts() if a["name"] == name)

with get_connection() as conn:
    conn.execute("DELETE FROM alerts WHERE account_id = ?", (account["id"],))
    conn.commit()

print(f"Cleared alert throttle for {name} (account_id={account['id']})")
