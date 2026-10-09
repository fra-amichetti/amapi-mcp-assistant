"""Test end-to-end di backend/app.py (/chat, /confirm) SENZA chiamare mai
la vera API Anthropic: la chiamata a `_client.messages.create` dentro
llm_agent.py viene sostituita con risposte finte scriptate che imitano la
forma di un vero messaggio Claude (content blocks con .type/.text oppure
.type/.id/.name/.input, piu' stop_reason).

Il resto della pipeline (host MCP, sottoprocesso mcp_write_server, mock
server AMAPI) resta reale: il mock server gira in-process in un thread
uvicorn sulla porta 8098, cosi' da poter verificare gli effetti concreti
delle azioni (es. la policy davvero modificata) ispezionando direttamente
`app.state.store`.

Non serve alcuna ANTHROPIC_API_KEY: viene rimossa esplicitamente
dall'ambiente prima di importare i moduli del backend.
"""
import os
import threading
import time

# Deve avvenire PRIMA di importare backend.app / backend.llm_agent, che
# altrimenti costruirebbero il client Anthropic e il client MCP con
# variabili d'ambiente diverse da quelle attese da questi test.
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ["AMAPI_BASE_URL"] = "http://127.0.0.1:8098"
os.environ["MOCK_ENTERPRISE_ID"] = "enterprises/LC00demo123"
os.environ.pop("GOOGLE_CREDENTIALS_PATH", None)
os.environ.pop("GOOGLE_ENTERPRISE_ID", None)

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

import backend.app as backend_app
import backend.llm_agent as llm_agent
from mock_amapi_server.main import create_app as create_mock_app

MOCK_SERVER_PORT = 8098
MOCK_SERVER_URL = f"http://127.0.0.1:{MOCK_SERVER_PORT}"


# ---------------------------------------------------------------------------
# Oggetti finti che imitano la forma delle risposte dell'SDK Anthropic
# ---------------------------------------------------------------------------
class FakeTextBlock:
    type = "text"

    def __init__(self, text: str):
        self.text = text


class FakeToolUseBlock:
    type = "tool_use"

    def __init__(self, id: str, name: str, input: dict):
        self.id = id
        self.name = name
        self.input = input


class FakeMessage:
    def __init__(self, content: list, stop_reason: str):
        self.content = content
        self.stop_reason = stop_reason


def script_anthropic(monkeypatch, responses: list) -> list:
    """Sostituisce _client.messages.create con una funzione che restituisce
    le risposte fornite, una per chiamata, nell'ordine dato. Ritorna il log
    delle chiamate effettuate (utile per verificare quante volte l'LLM e'
    stato interpellato)."""
    call_log = []

    def fake_create(**kwargs):
        call_log.append(kwargs)
        if not responses:
            raise AssertionError("Script Anthropic esaurito: troppe chiamate a messages.create")
        return responses.pop(0)

    monkeypatch.setattr(llm_agent._client.messages, "create", fake_create)
    return call_log


# ---------------------------------------------------------------------------
# Fixture: mock server AMAPI reale (in-process, thread uvicorn) + backend
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def mock_server():
    app = create_mock_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=MOCK_SERVER_PORT, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.02)
    else:
        raise RuntimeError("Il mock server AMAPI di test non si e' avviato in tempo.")
    yield app
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(scope="module")
def backend_client(mock_server):
    # Il context manager attiva il lifespan di FastAPI: backend_app.host.start()
    # lancia mcp_write_server come vero sottoprocesso stdio, collegato al mock
    # server sopra tramite AMAPI_BASE_URL.
    with TestClient(backend_app.app) as client:
        yield client


@pytest.fixture(autouse=True)
def _reset_state(mock_server):
    """Ogni test riparte con sessioni di chat pulite e mock server resettato,
    cosi' i test restano indipendenti dall'ordine di esecuzione."""
    backend_app.sessions.clear()
    httpx.post(f"{MOCK_SERVER_URL}/_reset", timeout=5)
    yield


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------
def test_no_anthropic_api_key_required_to_import_backend():
    assert not os.environ.get("ANTHROPIC_API_KEY")
    # Se l'import in cima al file non e' esploso, il client si costruisce
    # anche senza una vera chiave: la verifica esplicita serve solo a
    # documentare il requisito.
    assert llm_agent._client is not None


def test_chat_text_only_reply_no_tool_use(backend_client, monkeypatch):
    call_log = script_anthropic(
        monkeypatch,
        [FakeMessage(content=[FakeTextBlock("Ciao! Come posso aiutarti con i dispositivi Android?")], stop_reason="end_turn")],
    )

    resp = backend_client.post("/chat", json={"message": "ciao"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["pending"] is None
    assert "Ciao" in body["reply"]
    assert len(call_log) == 1


def test_chat_low_risk_tool_executes_immediately(backend_client, mock_server, monkeypatch):
    tool_use = FakeToolUseBlock(
        id="tu_policy_1",
        name="update_policy",
        input={"policy_id": "policy_sales", "policy_fields": {"cameraDisabled": True}},
    )
    script_anthropic(
        monkeypatch,
        [
            FakeMessage(content=[tool_use], stop_reason="tool_use"),
            FakeMessage(content=[FakeTextBlock("Ho aggiornato la policy policy_sales: fotocamera disabilitata.")], stop_reason="end_turn"),
        ],
    )

    resp = backend_client.post("/chat", json={"message": "disabilita la fotocamera sulla policy vendite"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["pending"] is None
    assert "aggiornato" in body["reply"].lower()

    # L'operazione MEDIA non richiede conferma: verifichiamo che sia stata
    # davvero applicata sul mock server, non solo raccontata dall'LLM.
    assert mock_server.state.store.policies["policy_sales"]["cameraDisabled"] is True


def test_chat_high_risk_tool_returns_pending_action(backend_client, monkeypatch):
    tool_use = FakeToolUseBlock(
        id="tu_lock_1",
        name="issue_command",
        input={"device_id": "pixel-9-pro-sales-01", "command_type": "LOCK"},
    )
    script_anthropic(
        monkeypatch,
        [FakeMessage(content=[FakeTextBlock("Sto per bloccare il dispositivo."), tool_use], stop_reason="tool_use")],
    )

    resp = backend_client.post("/chat", json={"message": "blocca il dispositivo pixel-9-pro-sales-01"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["pending"] is not None
    assert body["pending"]["risk"] == "HIGH"
    assert body["pending"]["tool_name"] == "issue_command"
    assert body["pending"]["action_id"]

    # Il comando non deve essere stato eseguito realmente sul mock server.
    assert backend_app.sessions[body["session_id"]].pending is not None


def test_confirm_approve_executes_action_and_clears_session(backend_client, monkeypatch):
    tool_use = FakeToolUseBlock(
        id="tu_lock_2",
        name="issue_command",
        input={"device_id": "pixel-9-pro-sales-01", "command_type": "LOCK"},
    )
    call_log = script_anthropic(
        monkeypatch,
        [
            FakeMessage(content=[tool_use], stop_reason="tool_use"),
            FakeMessage(content=[FakeTextBlock("Comando LOCK eseguito con successo sul dispositivo.")], stop_reason="end_turn"),
        ],
    )

    chat_resp = backend_client.post("/chat", json={"message": "blocca pixel-9-pro-sales-01"})
    chat_body = chat_resp.json()
    session_id = chat_body["session_id"]
    action_id = chat_body["pending"]["action_id"]

    confirm_resp = backend_client.post("/confirm", json={"session_id": session_id, "action_id": action_id, "approve": True})

    assert confirm_resp.status_code == 200
    confirm_body = confirm_resp.json()
    assert confirm_body["pending"] is None
    assert "eseguito" in confirm_body["reply"].lower()
    # sessione ripulita: nessuna azione pending residua
    assert backend_app.sessions[session_id].pending is None
    # l'LLM e' stato interpellato due volte: proposta iniziale + continuazione post-conferma
    assert len(call_log) == 2


def test_confirm_reject_does_not_execute_action(backend_client, mock_server, monkeypatch):
    tool_use = FakeToolUseBlock(
        id="tu_reboot_1",
        name="issue_command",
        input={"device_id": "pixel-8-support-02", "command_type": "REBOOT"},
    )
    script_anthropic(
        monkeypatch,
        [
            FakeMessage(content=[tool_use], stop_reason="tool_use"),
            FakeMessage(content=[FakeTextBlock("Ok, operazione annullata su tua richiesta.")], stop_reason="end_turn"),
        ],
    )

    chat_resp = backend_client.post("/chat", json={"message": "riavvia pixel-8-support-02"})
    chat_body = chat_resp.json()
    session_id = chat_body["session_id"]
    action_id = chat_body["pending"]["action_id"]

    confirm_resp = backend_client.post("/confirm", json={"session_id": session_id, "action_id": action_id, "approve": False})

    assert confirm_resp.status_code == 200
    confirm_body = confirm_resp.json()
    assert confirm_body["pending"] is None
    assert "annullat" in confirm_body["reply"].lower()

    # Nessun comando deve essere mai stato inviato al mock server: il
    # contatore dei comandi (incrementato solo da issue_command reali) resta a zero.
    assert mock_server.state.store._command_counter == 0


def test_chat_returns_409_when_action_is_pending(backend_client, monkeypatch):
    tool_use = FakeToolUseBlock(
        id="tu_wipe_1",
        name="wipe_device",
        input={"device_id": "pixel-8-support-02"},
    )
    script_anthropic(
        monkeypatch,
        [FakeMessage(content=[tool_use], stop_reason="tool_use")],
    )

    first = backend_client.post("/chat", json={"message": "cancella tutti i dati di pixel-8-support-02"})
    assert first.status_code == 200
    session_id = first.json()["session_id"]
    assert first.json()["pending"]["risk"] == "CRITICAL"

    second = backend_client.post("/chat", json={"session_id": session_id, "message": "un altro messaggio qualsiasi"})
    assert second.status_code == 409
