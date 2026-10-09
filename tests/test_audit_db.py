"""Test minimo di persistenza per mcp_write_server/audit_db.py: verifica che
i dati scritti sopravvivano alla chiusura della connessione sqlite3 (ogni
funzione pubblica del modulo apre e chiude la propria connessione, quindi
richiamarle di nuovo sullo stesso file equivale a "chiudere e riaprire")."""
from mcp_write_server import audit_db


def test_audit_log_survives_closing_and_reopening_connection(tmp_path):
    db_path = tmp_path / "audit_log_test.db"

    audit_db.log_proposed(
        action_id="test-action-1",
        tool_name="wipe_device",
        arguments={"device_id": "pixel-8-support-02"},
        risk="CRITICAL",
        created_at="2026-01-01T00:00:00+00:00",
        db_path=db_path,
    )

    # Nuova chiamata pubblica: apre una connessione sqlite3 nuova sullo
    # stesso file, indipendente da quella usata per la scrittura sopra.
    entry = audit_db.get_entry("test-action-1", db_path=db_path)
    assert entry is not None
    assert entry["status"] == "proposed"
    assert entry["tool_name"] == "wipe_device"
    assert entry["arguments"] == {"device_id": "pixel-8-support-02"}
    assert entry["resolved_at"] is None

    audit_db.log_confirmed("test-action-1", resolved_at="2026-01-01T00:05:00+00:00", db_path=db_path)

    entry_after_confirm = audit_db.get_entry("test-action-1", db_path=db_path)
    assert entry_after_confirm["status"] == "confirmed"
    assert entry_after_confirm["resolved_at"] == "2026-01-01T00:05:00+00:00"
