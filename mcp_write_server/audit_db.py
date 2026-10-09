"""Persistenza minima delle azioni critiche (proponi/conferma) su SQLite.

Lascia una traccia dell'azione che sopravvive al riavvio del processo del
server MCP (a differenza di `PendingActionStore` in risk.py, che e' solo in
memoria). Volutamente minimale: registra solo la proposta e, se avviene, la
conferma. Non gestisce il rifiuto (un'azione rifiutata resta semplicemente
'proposed' per sempre) ne' un campo confirmed_by.
"""
import json
import sqlite3
from pathlib import Path
from typing import Optional

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "audit_log.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS azioni_log (
    action_id TEXT PRIMARY KEY,
    tool_name TEXT NOT NULL,
    arguments TEXT NOT NULL,
    risk TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    resolved_at TEXT
);
"""


def _connect(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute(_SCHEMA)
    conn.commit()
    return conn


def log_proposed(action_id: str, tool_name: str, arguments: dict, risk: str, created_at: str, db_path: Path = DEFAULT_DB_PATH) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO azioni_log (action_id, tool_name, arguments, risk, status, created_at) "
            "VALUES (?, ?, ?, ?, 'proposed', ?)",
            (action_id, tool_name, json.dumps(arguments), risk, created_at),
        )
        conn.commit()
    finally:
        conn.close()


def log_confirmed(action_id: str, resolved_at: str, db_path: Path = DEFAULT_DB_PATH) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            "UPDATE azioni_log SET status = 'confirmed', resolved_at = ? WHERE action_id = ?",
            (resolved_at, action_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_entry(action_id: str, db_path: Path = DEFAULT_DB_PATH) -> Optional[dict]:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT action_id, tool_name, arguments, risk, status, created_at, resolved_at "
            "FROM azioni_log WHERE action_id = ?",
            (action_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return {
        "action_id": row[0],
        "tool_name": row[1],
        "arguments": json.loads(row[2]),
        "risk": row[3],
        "status": row[4],
        "created_at": row[5],
        "resolved_at": row[6],
    }
