"""Modalita' demo FAKE_LLM: sostituisce la vera chiamata a Claude con una
logica a parole chiave, per poter testare la chat frontend/backend (click
reali su frontend/index.html) senza spendere sull'API Anthropic.

Questo modulo viene importato da `llm_agent.py` ma la sua logica viene
eseguita SOLO quando la variabile d'ambiente FAKE_LLM e' attiva: sul
percorso reale (FAKE_LLM assente/0/false) non viene mai invocato.

Le classi FakeTextBlock/FakeToolUseBlock/FakeMessage imitano la forma di un
vero messaggio Claude (content blocks con .type/.text oppure
.type/.id/.name/.input, piu' stop_reason) cosi' che `_step()` in
llm_agent.py possa trattarle esattamente come una risposta reale
dell'SDK Anthropic, senza rami di codice diversi a valle.
"""
import itertools
import json
import re

_id_counter = itertools.count(1)


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


_HYPHENATED_TOKEN = re.compile(r"[a-zA-Z0-9]+(?:-[a-zA-Z0-9]+)+")
_POLICY_TOKEN = re.compile(r"policy[_-][a-zA-Z0-9_-]+", re.IGNORECASE)

_DEFAULT_DEVICE_ID = "pixel-9-pro-sales-01"
_DEFAULT_POLICY_ID = "policy_sales"

_NO_TOOL_TEXT = "Non ho capito, prova a scrivere 'elenca i dispositivi' o 'blocca <device_id>'."


def _next_id(prefix: str) -> str:
    return f"fake-{prefix}-{next(_id_counter)}"


def _extract_device_id(message: str) -> str:
    for token in _HYPHENATED_TOKEN.findall(message):
        if not token.lower().startswith("policy"):
            return token
    return _DEFAULT_DEVICE_ID


def _extract_policy_id(message: str) -> str:
    match = _POLICY_TOKEN.search(message)
    return match.group(0) if match else _DEFAULT_POLICY_ID


def _last_user_text(messages: list) -> str | None:
    """Testo dell'ultimo messaggio utente in linguaggio naturale, oppure
    None se l'ultimo messaggio utente e' in realta' il tool_result di una
    tool call precedente (siamo cioe' a meta' di una continuazione)."""
    if not messages:
        return None
    last = messages[-1]
    if last.get("role") != "user":
        return None
    content = last.get("content")
    return content if isinstance(content, str) else None


def _last_tool_result(messages: list) -> dict | None:
    if not messages:
        return None
    last = messages[-1]
    if last.get("role") != "user":
        return None
    content = last.get("content")
    if isinstance(content, list) and content and content[0].get("type") == "tool_result":
        raw = content[0].get("content", "{}")
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {"status": "unknown", "raw": raw}
    return None


def _summarize_tool_result(result: dict) -> str:
    status = result.get("status")
    if status == "executed":
        return "[demo] Operazione completata."
    if status == "cancelled_by_admin":
        return "[demo] Operazione annullata su richiesta dell'amministratore."
    if status == "error":
        return f"[demo] Errore durante l'operazione: {result.get('message', 'errore sconosciuto')}."
    return f"[demo] Risultato: {json.dumps(result)}"


def fake_step_response(messages: list, available_tools: list[dict]) -> FakeMessage:
    """Genera una risposta finta al posto di Claude per la modalita' demo
    FAKE_LLM, nella stessa forma (.content / .stop_reason) usata da
    `llm_agent._step` per una vera risposta Anthropic.

    Se l'ultimo messaggio e' il tool_result di una tool call precedente,
    produce la risposta testuale finale di continuazione. Altrimenti
    interpreta l'ultimo messaggio utente con una logica a parole chiave e,
    se il tool corrispondente e' fra quelli esposti da `host.list_tools()`,
    genera una tool_use; se il tool non e' disponibile in questa sessione
    (es. lettura senza server MCP Google collegato) risponde con testo
    semplice spiegando il limite invece di inventare una chiamata a un tool
    inesistente.
    """
    available_names = {t["name"] for t in available_tools}

    tool_result = _last_tool_result(messages)
    if tool_result is not None:
        return FakeMessage(content=[FakeTextBlock(_summarize_tool_result(tool_result))], stop_reason="end_turn")

    user_text = _last_user_text(messages) or ""
    lowered = user_text.lower()

    if ("cancella" in lowered and "dati" in lowered) or "wipe" in lowered:
        if "wipe_device" in available_names:
            device_id = _extract_device_id(user_text)
            tool_use = FakeToolUseBlock(_next_id("wipe"), "wipe_device", {"device_id": device_id})
            return FakeMessage(
                content=[FakeTextBlock(f"[demo] Sto per cancellare tutti i dati di '{device_id}'."), tool_use],
                stop_reason="tool_use",
            )
        return FakeMessage(
            content=[FakeTextBlock("[demo] Il tool wipe_device non e' disponibile in questa sessione.")],
            stop_reason="end_turn",
        )

    if "blocca" in lowered:
        if "issue_command" in available_names:
            device_id = _extract_device_id(user_text)
            tool_use = FakeToolUseBlock(_next_id("lock"), "issue_command", {"device_id": device_id, "command_type": "LOCK"})
            return FakeMessage(content=[tool_use], stop_reason="tool_use")
        return FakeMessage(
            content=[FakeTextBlock("[demo] Il tool issue_command non e' disponibile in questa sessione.")],
            stop_reason="end_turn",
        )

    if "aggiorna" in lowered and "policy" in lowered:
        if "update_policy" in available_names:
            policy_id = _extract_policy_id(user_text)
            camera_disabled = not ("abilita" in lowered and "disabilita" not in lowered)
            tool_use = FakeToolUseBlock(
                _next_id("policy"),
                "update_policy",
                {"policy_id": policy_id, "policy_fields": {"cameraDisabled": camera_disabled}},
            )
            return FakeMessage(content=[tool_use], stop_reason="tool_use")
        return FakeMessage(
            content=[FakeTextBlock("[demo] Il tool update_policy non e' disponibile in questa sessione.")],
            stop_reason="end_turn",
        )

    if "elenca" in lowered or "dispositivi" in lowered:
        for candidate in ("list_devices", "list_policies", "get_enterprise"):
            if candidate in available_names:
                tool_use = FakeToolUseBlock(_next_id("read"), candidate, {})
                return FakeMessage(content=[tool_use], stop_reason="tool_use")
        return FakeMessage(
            content=[FakeTextBlock(
                "[demo] Nessun tool di lettura disponibile in questa sessione (richiede il collegamento al server "
                "MCP ufficiale di Google, non attivo in modalita' mock-only): prova invece 'aggiorna policy', "
                "'blocca <device_id>' o 'cancella tutti i dati di <device_id>'."
            )],
            stop_reason="end_turn",
        )

    return FakeMessage(content=[FakeTextBlock(_NO_TOOL_TEXT)], stop_reason="end_turn")
