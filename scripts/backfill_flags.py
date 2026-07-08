"""
Retroactively apply pattern detection to all existing customer messages that
have no flags yet. Run once after seed_demo.py to populate flags on demo data.

Usage: python scripts/backfill_flags.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from db.schema import get_connection
from db.queries import update_message_flags
from agents.pattern_detector import detect_patterns
import json

with get_connection() as conn:
    rows = conn.execute(
        "SELECT id, text FROM messages WHERE is_customer = 1 AND flags = '[]'"
    ).fetchall()

updated = 0
for row in rows:
    flags = detect_patterns(row["text"])
    if flags:
        update_message_flags(row["id"], flags)
        updated += 1
        print(f"  msg {row['id']}: {[f['label'] for f in flags]} | \"{row['text'][:60]}\"")

print(f"\nBackfill complete. {updated}/{len(rows)} messages flagged.")
