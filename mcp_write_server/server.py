"""Server MCP custom per le operazioni di scrittura mancanti nel server MCP
ufficiale di Google (che espone solo la lettura dell'Android Management API).

Costruito con l'SDK ufficiale `mcp` (API low-level `Server`, non il wrapper
semplificato `FastMCP`) per avere controllo esplicito sullo schema JSON di
ogni tool e sulla gestione degli errori JSON-RPC, in linea con quanto
descritto nel capitolo 2 sul protocollo. Trasporto: stdio, lo stesso usato
da un host locale (Claude Desktop, o il backend di questo progetto) per
lanciare il server come sottoprocesso.

Le operazioni ad alto rischio (issue_command distruttivi, wipe_device,
delete_policy) non eseguono subito: `risk.py` le trasforma in un'azione
"pending" che deve essere confermata esplicitamente con il tool
`confirm_action`, cosi' la validazione umana e' imposta dal protocollo e non
solo suggerita all'LLM nel prompt.
"""
import asyncio
import logging
import os
from datetime import datetime, timezone

import mcp.server.stdio
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.models import InitializationOptions
from mcp.server.lowlevel import NotificationOptions

from . import audit_db
from .amapi_client import AmapiClient, AmapiError
from .risk import PendingActionStore, classify, requires_confirmation, summarize


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

logging.basicConfig(level=logging.INFO, stream=__import__("sys").stderr)
logger = logging.getLogger("mcp_write_server")

server = Server("android-mgmt-write-server")
pending_actions = PendingActionStore()
amapi = AmapiClient.from_env()

TOOLS: list[types.Tool] = [
    types.Tool(
        name="list_devices",
        description=(
            "Elenca i dispositivi registrati sul mock AMAPI locale. Operazione di sola "
            "lettura, rischio BASSO: eseguita subito, nessuna conferma richiesta."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="get_device",
        description=(
            "Recupera lo stato di un singolo dispositivo dal mock AMAPI locale. "
            "Operazione di sola lettura, rischio BASSO: eseguita subito."
        ),
        inputSchema={
            "type": "object",
            "properties": {"device_id": {"type": "string"}},
            "required": ["device_id"],
        },
    ),
    types.Tool(
        name="list_policies",
        description=(
            "Elenca le policy configurate sul mock AMAPI locale. Operazione di sola "
            "lettura, rischio BASSO: eseguita subito, nessuna conferma richiesta."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="update_policy",
        description=(
            "Crea o aggiorna (patch) una policy AMAPI. Operazione a rischio MEDIO: "
            "modifica lo stato desiderato dei dispositivi collegati, ma resta reversibile."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "policy_id": {"type": "string", "description": "Identificativo della policy, es. 'policy_sales'"},
                "policy_fields": {
                    "type": "object",
                    "description": "Sottoinsieme dei campi della risorsa Policy AMAPI da impostare/aggiornare",
                },
            },
            "required": ["policy_id", "policy_fields"],
        },
    ),
    types.Tool(
        name="delete_policy",
        description=(
            "Elimina definitivamente una policy AMAPI. Operazione CRITICA e irreversibile: "
            "richiede conferma esplicita tramite confirm_action prima di essere eseguita."
        ),
        inputSchema={
            "type": "object",
            "properties": {"policy_id": {"type": "string"}},
            "required": ["policy_id"],
        },
    ),
    types.Tool(
        name="issue_command",
        description=(
            "Invia un comando diretto e immediato a un dispositivo (LOCK, REBOOT, "
            "RESET_PASSWORD, START_LOST_MODE). Rischio ALTO o CRITICO a seconda del "
            "comando: richiede conferma esplicita tramite confirm_action."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "device_id": {"type": "string"},
                "command_type": {
                    "type": "string",
                    "enum": ["LOCK", "REBOOT", "RESET_PASSWORD", "START_LOST_MODE"],
                },
            },
            "required": ["device_id", "command_type"],
        },
    ),
    types.Tool(
        name="wipe_device",
        description=(
            "Cancella tutti i dati del dispositivo e ne rimuove la gestione (factory "
            "reset remoto). Operazione CRITICA e irreversibile: richiede conferma "
            "esplicita tramite confirm_action prima di essere eseguita."
        ),
        inputSchema={
            "type": "object",
            "properties": {"device_id": {"type": "string"}},
            "required": ["device_id"],
        },
    ),
    types.Tool(
        name="confirm_action",
        description=(
            "Esegue realmente un'azione ad alto rischio precedentemente proposta da "
            "un altro tool (identificata da action_id), dopo che un amministratore "
            "umano l'ha approvata esplicitamente."
        ),
        inputSchema={
            "type": "object",
            "properties": {"action_id": {"type": "string"}},
            "required": ["action_id"],
        },
    ),
]


def _propose(tool_name: str, arguments: dict) -> dict:
    risk = classify(tool_name, arguments)
    summary = summarize(tool_name, arguments)
    record = pending_actions.create(tool_name, arguments, risk, summary)
    audit_db.log_proposed(record["action_id"], tool_name, arguments, record["risk"], created_at=_now_iso())
    return {
        "status": "confirmation_required",
        "action_id": record["action_id"],
        "risk": record["risk"],
        "summary": record["summary"],
        "message": "Azione non eseguita: e' necessaria una conferma esplicita dell'amministratore tramite il tool confirm_action.",
    }


async def _execute(tool_name: str, arguments: dict) -> dict:
    try:
        if tool_name == "list_devices":
            result = await amapi.list_devices()
            return {"status": "executed", "result": result}
        if tool_name == "get_device":
            result = await amapi.get_device(arguments["device_id"])
            return {"status": "executed", "result": result}
        if tool_name == "list_policies":
            result = await amapi.list_policies()
            return {"status": "executed", "result": result}
        if tool_name == "update_policy":
            result = await amapi.patch_policy(arguments["policy_id"], arguments["policy_fields"])
            return {"status": "executed", "result": result}
        if tool_name == "delete_policy":
            await amapi.delete_policy(arguments["policy_id"])
            return {"status": "executed", "result": {"deleted": arguments["policy_id"]}}
        if tool_name == "issue_command":
            result = await amapi.issue_command(arguments["device_id"], arguments["command_type"])
            return {"status": "executed", "result": result}
        if tool_name == "wipe_device":
            await amapi.wipe_device(arguments["device_id"])
            return {"status": "executed", "result": {"wiped": arguments["device_id"]}}
        raise ValueError(f"Tool sconosciuto: {tool_name}")
    except AmapiError as exc:
        return {"status": "error", "error_code": exc.status_code, "message": exc.message}


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return TOOLS


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> dict:
    arguments = arguments or {}

    if name == "confirm_action":
        action_id = arguments.get("action_id", "")
        record = pending_actions.pop(action_id)
        if record is None:
            return {"status": "error", "message": "action_id sconosciuto, scaduto o gia' usato."}
        result = await _execute(record["tool_name"], record["arguments"])
        audit_db.log_confirmed(action_id, resolved_at=_now_iso())
        return result

    if name not in {"list_devices", "get_device", "list_policies", "update_policy", "delete_policy", "issue_command", "wipe_device"}:
        return {"status": "error", "message": f"Tool sconosciuto: {name}"}

    risk = classify(name, arguments)
    if requires_confirmation(risk):
        return _propose(name, arguments)
    return await _execute(name, arguments)


async def run():
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="android-mgmt-write-server",
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(run())
