import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from db.schema import get_connection
from db.queries import get_all_accounts

vortex = next(a for a in get_all_accounts() if a["name"] == "Vortex Inc")
with get_connection() as conn:
    conn.execute(
        "DELETE FROM signals WHERE account_id = ? AND signal_type = 'acquisition'",
        (vortex["id"],),
    )
    conn.commit()
print("Cleaned up polluted signals for Vortex Inc")
