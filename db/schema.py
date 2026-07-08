import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "pulse.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    channel_id TEXT UNIQUE NOT NULL,
    am_user_id TEXT NOT NULL,
    champion_user_id TEXT,
    contract_value INTEGER DEFAULT 0,
    renewal_date TEXT,
    enable_champion_tracking BOOLEAN DEFAULT 0,
    enable_external_signals BOOLEAN DEFAULT 0,
    enable_salesforce_crm BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER REFERENCES accounts(id),
    channel_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    text TEXT NOT NULL,
    is_customer BOOLEAN DEFAULT FALSE,
    timestamp TEXT NOT NULL,
    flags TEXT DEFAULT '[]',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS health_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER REFERENCES accounts(id),
    score INTEGER NOT NULL,
    urgency TEXT DEFAULT 'low',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER REFERENCES accounts(id),
    signal_type TEXT NOT NULL,
    headline TEXT NOT NULL,
    url TEXT,
    severity INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER REFERENCES accounts(id),
    urgency TEXT NOT NULL,
    brief_text TEXT,
    snoozed_until TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def _migrate(conn: sqlite3.Connection):
    """Adds columns to existing tables that CREATE TABLE IF NOT EXISTS won't
    retroactively add. Safe to run every startup — checks before altering."""
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(accounts)")}
    if "enable_champion_tracking" not in existing_cols:
        conn.execute("ALTER TABLE accounts ADD COLUMN enable_champion_tracking BOOLEAN DEFAULT 0")
    if "enable_external_signals" not in existing_cols:
        conn.execute("ALTER TABLE accounts ADD COLUMN enable_external_signals BOOLEAN DEFAULT 0")
    if "enable_salesforce_crm" not in existing_cols:
        conn.execute("ALTER TABLE accounts ADD COLUMN enable_salesforce_crm BOOLEAN DEFAULT 0")
    conn.commit()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    conn.commit()
    _migrate(conn)
    conn.close()


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_PATH}")
