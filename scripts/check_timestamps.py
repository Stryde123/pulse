import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from db.schema import get_connection
from datetime import datetime, timezone

TIMESTAMPS = ["1783467488", "1783468127"]

with get_connection() as conn:
    for ts in TIMESTAMPS:
        print(f"\n--- Timestamp {ts} ---")
        dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
        print(f"Converts to: {dt.isoformat()}")

        rows = conn.execute(
            "SELECT id, account_id, user_id, text, is_customer, timestamp, flags FROM messages WHERE timestamp LIKE ?",
            (f"{ts}%",),
        ).fetchall()
        if rows:
            for r in rows:
                print(f"  Message id={r[0]} account_id={r[1]} user={r[2]} customer={r[4]} flags={r[6]}")
                print(f"  Text: {r[3][:100]}")
        else:
            print("  No exact match in messages table")
