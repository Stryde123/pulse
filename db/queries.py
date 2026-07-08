import json
from datetime import datetime, timedelta
from typing import Optional
from .schema import get_connection


# --- Accounts ---

def insert_account(name: str, channel_id: str, am_user_id: str,
                   champion_user_id: Optional[str] = None,
                   contract_value: int = 0, renewal_date: Optional[str] = None,
                   enable_champion_tracking: bool = False,
                   enable_external_signals: bool = False,
                   enable_salesforce_crm: bool = False) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO accounts (name, channel_id, am_user_id, champion_user_id,
               contract_value, renewal_date, enable_champion_tracking, enable_external_signals,
               enable_salesforce_crm)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, channel_id, am_user_id, champion_user_id, contract_value, renewal_date,
             enable_champion_tracking, enable_external_signals, enable_salesforce_crm)
        )
        conn.commit()
        return cur.lastrowid


def update_toggles(account_id: int, enable_champion_tracking: Optional[bool] = None,
                   enable_external_signals: Optional[bool] = None,
                   enable_salesforce_crm: Optional[bool] = None) -> None:
    """Pass only the flags you want to change — None leaves that flag untouched."""
    with get_connection() as conn:
        if enable_champion_tracking is not None:
            conn.execute(
                "UPDATE accounts SET enable_champion_tracking = ? WHERE id = ?",
                (enable_champion_tracking, account_id)
            )
        if enable_external_signals is not None:
            conn.execute(
                "UPDATE accounts SET enable_external_signals = ? WHERE id = ?",
                (enable_external_signals, account_id)
            )
        if enable_salesforce_crm is not None:
            conn.execute(
                "UPDATE accounts SET enable_salesforce_crm = ? WHERE id = ?",
                (enable_salesforce_crm, account_id)
            )
        conn.commit()


def get_account_by_channel(channel_id: str) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM accounts WHERE channel_id = ?", (channel_id,)
        ).fetchone()
        return dict(row) if row else None


def get_all_accounts() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM accounts").fetchall()
        return [dict(r) for r in rows]


def update_champion(account_id: int, champion_user_id: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE accounts SET champion_user_id = ? WHERE id = ?",
            (champion_user_id, account_id)
        )
        conn.commit()


# --- Messages ---

def insert_message(account_id: int, channel_id: str, user_id: str,
                   text: str, is_customer: bool, timestamp: str,
                   flags: list | None = None) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO messages (account_id, channel_id, user_id, text,
               is_customer, timestamp, flags)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (account_id, channel_id, user_id, text, is_customer, timestamp,
             json.dumps(flags or []))
        )
        conn.commit()
        return cur.lastrowid


def update_message_flags(message_id: int, flags: list) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE messages SET flags = ? WHERE id = ?",
            (json.dumps(flags), message_id)
        )
        conn.commit()


def _since_ts(days: int) -> float:
    """Unix timestamp for N days ago — used for Slack-timestamp-based queries."""
    return (datetime.utcnow() - timedelta(days=days)).timestamp()


def get_recent_messages(account_id: int, days: int = 30, customer_only: bool = False) -> list[dict]:
    """Returns messages within the window, ordered by Slack send time (timestamp field)."""
    since = _since_ts(days)
    query = "SELECT * FROM messages WHERE account_id = ? AND CAST(timestamp AS REAL) >= ?"
    params: list = [account_id, since]
    if customer_only:
        query += " AND is_customer = 1"
    query += " ORDER BY CAST(timestamp AS REAL) ASC"
    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d['flags'] = json.loads(d['flags'])
            result.append(d)
        return result


def get_message_count_in_window(account_id: int, days: int, customer_only: bool = False) -> int:
    since = _since_ts(days)
    query = "SELECT COUNT(*) FROM messages WHERE account_id = ? AND CAST(timestamp AS REAL) >= ?"
    params: list = [account_id, since]
    if customer_only:
        query += " AND is_customer = 1"
    with get_connection() as conn:
        return conn.execute(query, params).fetchone()[0]


def get_flagged_messages(account_id: int, days: int = 14) -> list[dict]:
    since = _since_ts(days)
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT * FROM messages WHERE account_id = ?
               AND CAST(timestamp AS REAL) >= ?
               AND flags != '[]' ORDER BY CAST(timestamp AS REAL) DESC""",
            (account_id, since)
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d['flags'] = json.loads(d['flags'])
            result.append(d)
        return result


# --- Health Scores ---

def insert_health_score(account_id: int, score: int, urgency: str) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO health_scores (account_id, score, urgency) VALUES (?, ?, ?)",
            (account_id, score, urgency)
        )
        conn.commit()
        return cur.lastrowid


def get_health_history(account_id: int, limit: int = 30) -> list[dict]:
    # created_at has only 1-second resolution (SQLite CURRENT_TIMESTAMP), so
    # rapid successive inserts (e.g. multiple rescores in the same script
    # run) can tie — id DESC as a tiebreaker guarantees true insertion order.
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT * FROM health_scores WHERE account_id = ?
               ORDER BY created_at DESC, id DESC LIMIT ?""",
            (account_id, limit)
        ).fetchall()
        return [dict(r) for r in reversed(rows)]


def get_latest_health_score(account_id: int) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            """SELECT * FROM health_scores WHERE account_id = ?
               ORDER BY created_at DESC, id DESC LIMIT 1""",
            (account_id,)
        ).fetchone()
        return dict(row) if row else None


# --- Signals ---

def insert_signal(account_id: int, signal_type: str, headline: str,
                  url: Optional[str] = None, severity: int = 1) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO signals (account_id, signal_type, headline, url, severity)
               VALUES (?, ?, ?, ?, ?)""",
            (account_id, signal_type, headline, url, severity)
        )
        conn.commit()
        return cur.lastrowid


def get_recent_signals(account_id: int, days: int = 14) -> list[dict]:
    since = (datetime.utcnow() - timedelta(days=days)).isoformat()
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT * FROM signals WHERE account_id = ? AND created_at >= ?
               ORDER BY severity DESC, created_at DESC""",
            (account_id, since)
        ).fetchall()
        return [dict(r) for r in rows]


# --- Alerts ---

def insert_alert(account_id: int, urgency: str, brief_text: Optional[str] = None) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO alerts (account_id, urgency, brief_text) VALUES (?, ?, ?)",
            (account_id, urgency, brief_text)
        )
        conn.commit()
        return cur.lastrowid


def get_last_alert(account_id: int) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            """SELECT * FROM alerts WHERE account_id = ?
               ORDER BY created_at DESC LIMIT 1""",
            (account_id,)
        ).fetchone()
        return dict(row) if row else None


def is_alert_snoozed(account_id: int) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            """SELECT snoozed_until FROM alerts WHERE account_id = ?
               AND snoozed_until IS NOT NULL
               ORDER BY created_at DESC LIMIT 1""",
            (account_id,)
        ).fetchone()
        if not row or not row[0]:
            return False
        return datetime.fromisoformat(row[0]) > datetime.utcnow()


def snooze_account(account_id: int, days: int = 7) -> None:
    snoozed_until = (datetime.utcnow() + timedelta(days=days)).isoformat()
    with get_connection() as conn:
        conn.execute(
            """UPDATE alerts SET snoozed_until = ? WHERE id = (
               SELECT id FROM alerts WHERE account_id = ? ORDER BY created_at DESC LIMIT 1)""",
            (snoozed_until, account_id)
        )
        conn.commit()


def alert_sent_recently(account_id: int, hours: int = 48) -> bool:
    since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    with get_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM alerts WHERE account_id = ? AND created_at >= ?",
            (account_id, since)
        ).fetchone()[0]
        return count > 0
