"""Loop di tool-calling tra Claude e l'host MCP.

Mantiene la cronologia dei messaggi per sessione ed espone `run_turn`, usata
sia da /chat (dopo aver aggiunto un nuovo messaggio utente) sia da /confirm
(dopo aver aggiunto l'esito di un'azione confermata o rifiutata): in
entrambi i casi si tratta di "far ripartire" la stessa conversazione con
Claude finche' non produce una risposta testuale finale oppure invoca un
tool ad alto rischio che richiede conferma umana esplicita.
"""
import json
import os
from dataclasses import dataclass, field
from typing import Optional

import ollama
from anthropic import Anthropic

from .fake_llm import fake_step_response
from .mcp_host import McpHost

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

# Provider dell'LLM usato per interpretare il linguaggio naturale:
# "anthropic" (default, Claude via API) oppure "ollama" (modello locale,
# nessuna chiave richiesta). Selezionabile solo tramite variabile
# d'ambiente, cosi' si puo' tornare a Claude senza toccare il codice.
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "anthropic").strip().lower()
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")

# Modalita' demo: se attiva, _step() non chiama mai la vera API Anthropic,
# ma genera risposte finte a parole chiave (vedi backend/fake_llm.py). Serve
# a poter testare la chat da frontend/index.html con click reali, senza
# spendere sull'API. Sul percorso reale (flag assente/0/false) il comportamento
# resta identico a prima: nessuna differenza di codice.
FAKE_LLM = os.environ.get("FAKE_LLM", "").strip().lower() in {"1", "true", "yes", "on"}

SYSTEM_PROMPT = (
    "Sei l'assistente di gestione dispositivi Android aziendali di una console MDM. "
    "Rispondi in italiano, in modo conciso. Usa i tool disponibili per leggere lo stato "
    "di dispositivi e policy e per proporre operazioni di scrittura (aggiornare policy, "
    "inviare comandi ai dispositivi, cancellare dati). "
    "Alcuni tool non eseguono subito l'azione ma rispondono con "
    "status='confirmation_required': in quel caso NON considerare l'azione eseguita, "
    "limitati a comunicare all'amministratore che e' richiesta una conferma esplicita. "
    "Chiama un solo tool per volta e attendi il suo risultato prima di proseguire."
)


@dataclass
class PendingAction:
    tool_use_id: str
    action_id: str
    summary: str
    risk: str
    tool_name: str


@dataclass
class ChatSession:
    messages: list = field(default_factory=list)
    pending: Optional[PendingAction] = None


# Se ANTHROPIC_API_KEY non e' impostata (es. nei test, dove le chiamate reali
# vengono sempre mockate) si usa un placeholder solo per non far fallire la
# costruzione del client: una chiamata reale con questo valore fallirebbe
# comunque con 401, esattamente come con una chiave sbagliata.
_client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


def _extract_text(content_blocks) -> str:
    return "\n".join(block.text for block in content_blocks if block.type == "text").strip()


async def _step_ollama(session: ChatSession, host: McpHost) -> dict:
    """Variante di _step per il provider locale Ollama: stessa logica di alto
    livello di quella Anthropic qui sotto (un tool per volta, gestione di
    'confirmation_required'), ma adattata al formato dei messaggi e delle
    tool_calls di Ollama, diverso da quello dei content-block Anthropic."""
    # chiamata all LLM
    response = ollama.chat(model=OLLAMA_MODEL, messages=session.messages, tools=host.list_tools())
    message = response["message"]
    session.messages.append(message) # Aggiorna lo stato della conversazione con la risposta dell LLM, per il prossimo ciclo se necessario

    tool_calls = message.get("tool_calls") or [] # Estrae le tool_calls dalla risposta dell LLM
    if not tool_calls:
        return {"done": True, "reply": message.get("content") or "(nessuna risposta testuale)"}

    tool_call = tool_calls[0]  # un solo tool per volta, come nel ramo Anthropic
    tool_name = tool_call["function"]["name"]
    tool_args = tool_call["function"]["arguments"]  # gia' un dict, non una stringa JSON
    preamble = message.get("content") or ""

    result = await host.call_tool(tool_name, tool_args) # chaimata al tool MCP tramite il server

    if result.get("status") == "confirmation_required":
        session.pending = PendingAction(
            tool_use_id=str(tool_call.get("id", tool_name)),
            action_id=result["action_id"],
            summary=result["summary"],
            risk=result["risk"],
            tool_name=tool_name,
        )
        return {
            "done": True,
            "reply": preamble or f"Azione ad alto rischio proposta: {result['summary']}",
            "pending": {
                "action_id": result["action_id"],
                "summary": result["summary"],
                "risk": result["risk"],
                "tool_name": tool_name,
            },
            "tool_used": tool_name,
        }

    session.messages.append({"role": "tool", "content": json.dumps(result)}) # aggiunge il risultato della tool call alla conversazione, in modo che l'LLM possa usarlo nel prossimo ciclo
    return {"done": False, "tool_used": tool_name} # il ciclo For di run_turn continua


async def _step(session: ChatSession, host: McpHost) -> dict:
    """Esegue un singolo giro di richiesta a Claude e, se necessario, un
    singolo tool call; ritorna il risultato finale oppure segnala che serve
    un'altra iterazione (gestita dal chiamante in un ciclo)."""
    if LLM_PROVIDER == "ollama" and not FAKE_LLM:
        return await _step_ollama(session, host)

    if FAKE_LLM:
        response = fake_step_response(session.messages, host.list_tools())
    else:
        response = _client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=session.messages,
            tools=host.list_tools(),
            tool_choice={"type": "auto", "disable_parallel_tool_use": True},
        )
    session.messages.append({"role": "assistant", "content": response.content})

    if response.stop_reason != "tool_use":
        return {"done": True, "reply": _extract_text(response.content) or "(nessuna risposta testuale)"}

    tool_use = next(block for block in response.content if block.type == "tool_use")
    preamble = _extract_text(response.content)

    result = await host.call_tool(tool_use.name, tool_use.input)

    if result.get("status") == "confirmation_required":
        session.pending = PendingAction(
            tool_use_id=tool_use.id,
            action_id=result["action_id"],
            summary=result["summary"],
            risk=result["risk"],
            tool_name=tool_use.name,
        )
        return {
            "done": True,
            "reply": preamble or f"Azione ad alto rischio proposta: {result['summary']}",
            "pending": {
                "action_id": result["action_id"],
                "summary": result["summary"],
                "risk": result["risk"],
                "tool_name": tool_use.name,
            },
            "tool_used": tool_use.name,
        }

    session.messages.append(
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": tool_use.id, "content": json.dumps(result)}
            ],
        }
    )
    return {"done": False, "tool_used": tool_use.name}


async def run_turn(session: ChatSession, host: McpHost, max_iterations: int = 6) -> dict:
    tool_used = None
    for _ in range(max_iterations):
        outcome = await _step(session, host)
        if outcome.get("tool_used"):
            tool_used = outcome["tool_used"]
        if outcome["done"]:
            return {"reply": outcome["reply"], "pending": outcome.get("pending"), "tool_used": tool_used}
    return {
        "reply": "Troppi passaggi di ragionamento senza una risposta conclusiva: riprova riformulando la richiesta.",
        "pending": None,
        "tool_used": tool_used,
    }


def resolve_pending(session: ChatSession, approved: bool, execution_result: dict) -> None:
    """Inserisce nella conversazione l'esito di un'azione confermata/rifiutata
    dall'admin, cosi' l'LLM possa proseguire nel turno successivo. Il formato
    del messaggio dipende dal provider attivo: Ollama non usa i content-block
    'tool_result' di Anthropic, ma un messaggio con role='tool'."""
    pending = session.pending
    assert pending is not None
    if LLM_PROVIDER == "ollama" and not FAKE_LLM:
        session.messages.append({"role": "tool", "content": json.dumps(execution_result)})
    else:
        session.messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": pending.tool_use_id,
                        "content": json.dumps(execution_result),
                    }
                ],
            }
        )
    session.pending = None
