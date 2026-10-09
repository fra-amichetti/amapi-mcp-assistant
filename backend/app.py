"""Backend FastAPI: espone la chat conversazionale e serve il frontend.

`/chat`    riceve un messaggio utente e fa avanzare la conversazione con
           l'LLM, eventualmente segnalando un'azione critica in sospeso.
`/confirm` riceve la decisione esplicita dell'amministratore (conferma o
           rifiuto) su un'azione in sospeso e fa proseguire la conversazione.
"""
import logging
import os
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .llm_agent import FAKE_LLM, LLM_PROVIDER, SYSTEM_PROMPT, ChatSession, resolve_pending, run_turn
from .mcp_host import PROJECT_ROOT, McpHost

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backend.app")

host = McpHost()
sessions: dict[str, ChatSession] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    await host.start()
    yield
    await host.stop()


app = FastAPI(title="Assistente MCP per Android Management", lifespan=lifespan)

FRONTEND_DIR = PROJECT_ROOT / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/")
def index():
    return FileResponse(str(FRONTEND_DIR / "index.html"))


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    pending: dict | None = None
    tool_used: str | None = None


class ConfirmRequest(BaseModel):
    session_id: str
    action_id: str
    approve: bool


class DemoResetRequest(BaseModel):
    session_id: str | None = None


class DemoResetResponse(BaseModel):
    session_reset: bool
    mock_server_reset: bool


def _get_session(session_id: str | None) -> tuple[str, ChatSession]:
    if session_id and session_id in sessions:
        return session_id, sessions[session_id]
    new_id = session_id or str(uuid.uuid4())
    session = ChatSession()
    if LLM_PROVIDER == "ollama" and not FAKE_LLM:
        # Ollama non ha un parametro 'system' separato come l'API Anthropic:
        # il prompt di sistema va incluso come primo messaggio con
        # role='system' nella cronologia, altrimenti il modello non riceve
        # mai l'istruzione (es. "Rispondi in italiano").
        session.messages.append({"role": "system", "content": SYSTEM_PROMPT})
    sessions[new_id] = session
    return new_id, session


def _tool_name(tool: dict) -> str:
    # Lo schema del tool e' quello Anthropic ({"name": ...}) o quello Ollama
    # ({"function": {"name": ...}}) a seconda di LLM_PROVIDER: qui serve solo
    # a costruire l'elenco leggibile per /health, quindi gestiamo entrambi.
    return tool.get("name") or tool.get("function", {}).get("name", "?")


@app.get("/health")
def health():
    return {
        "status": "ok",
        "google_mcp_enabled": host.google_enabled,
        "fake_llm_enabled": FAKE_LLM,
        "tools": [_tool_name(t) for t in host.list_tools()],
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    session_id, session = _get_session(req.session_id)
    if session.pending is not None:
        raise HTTPException(
            status_code=409,
            detail="C'e' un'azione in sospeso in attesa di conferma: chiamare /confirm prima di inviare un nuovo messaggio.",
        )
    session.messages.append({"role": "user", "content": req.message})
    outcome = await run_turn(session, host)
    return ChatResponse(
        session_id=session_id,
        reply=outcome["reply"],
        pending=outcome.get("pending"),
        tool_used=outcome.get("tool_used"),
    )


@app.post("/confirm", response_model=ChatResponse)
async def confirm(req: ConfirmRequest):
    if req.session_id not in sessions:
        raise HTTPException(status_code=404, detail="Sessione sconosciuta.")
    session = sessions[req.session_id]
    if session.pending is None or session.pending.action_id != req.action_id:
        raise HTTPException(status_code=409, detail="Nessuna azione in sospeso corrispondente a questo action_id.")

    # Il tool MCP realmente eseguito da questa conferma e' quello dell'azione
    # pending (es. 'issue_command'), non 'confirm_action' stesso: lo teniamo da
    # parte prima che resolve_pending svuoti session.pending, per popolare il
    # badge "tool usato" anche quando la continuazione con l'LLM non chiama
    # un nuovo tool (il caso tipico: risponde solo con un riepilogo testuale).
    confirmed_tool_name = session.pending.tool_name

    if req.approve:
        execution_result = await host.call_tool("confirm_action", {"action_id": req.action_id})
    else:
        execution_result = {
            "status": "cancelled_by_admin",
            "message": "L'amministratore ha rifiutato l'esecuzione di questa azione.",
        }

    resolve_pending(session, req.approve, execution_result)
    outcome = await run_turn(session, host)
    return ChatResponse(
        session_id=req.session_id,
        reply=outcome["reply"],
        pending=outcome.get("pending"),
        tool_used=outcome.get("tool_used") or confirmed_tool_name,
    )


@app.post("/demo/reset", response_model=DemoResetResponse)
async def demo_reset(req: DemoResetRequest):
    """Azzera lo stato per ricominciare una demo da zero: rimuove la sessione
    di chat indicata (lato backend) e resetta il mock server AMAPI al
    dataset iniziale, cosi' non restano ne' cronologia ne' effetti collaterali
    dello scenario precedente."""
    session_reset = False
    if req.session_id and req.session_id in sessions:
        del sessions[req.session_id]
        session_reset = True

    mock_server_reset = False
    amapi_base_url = os.environ.get("AMAPI_BASE_URL", "http://127.0.0.1:8001")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"{amapi_base_url}/_reset")
        mock_server_reset = resp.status_code == 200
    except httpx.HTTPError:
        logger.warning("Impossibile raggiungere il mock server (%s) per il reset della demo.", amapi_base_url)

    return DemoResetResponse(session_reset=session_reset, mock_server_reset=mock_server_reset)
