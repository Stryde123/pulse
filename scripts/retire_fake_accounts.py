import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from db.schema import get_connection
from db.queries import get_all_accounts

TARGET_NAMES = ["Acme Corp", "Vortex Inc"]

accounts = get_all_accounts()
for name in TARGET_NAMES:
    fake = next((a for a in accounts if a["name"] == name and a["channel_id"].startswith("C_")), None)
    if not fake:
        print(f"No fake '{name}' account found — skipping.")
        continue

    with get_connection() as conn:
        conn.execute("DELETE FROM messages WHERE account_id = ?", (fake["id"],))
        conn.execute("DELETE FROM health_scores WHERE account_id = ?", (fake["id"],))
        conn.execute("DELETE FROM signals WHERE account_id = ?", (fake["id"],))
        conn.execute("DELETE FROM alerts WHERE account_id = ?", (fake["id"],))
        conn.execute("DELETE FROM accounts WHERE id = ?", (fake["id"],))
        conn.commit()
    print(f"Retired fake '{name}' account (id={fake['id']}, channel={fake['channel_id']})")
