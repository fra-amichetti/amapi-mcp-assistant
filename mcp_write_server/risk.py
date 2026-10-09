"""Classificazione del rischio dei tool di scrittura e flusso propose/confirm.

Implementa a livello di protocollo (non solo nel prompt dell'LLM) la
validazione umana preventiva richiesta per i comandi ADM piu' critici
(capitolo 3.4 della tesi): un tool ad alto impatto non esegue subito, ma
restituisce un'azione "pending" con un riassunto leggibile; solo una chiamata
esplicita a `confirm_action` la esegue davvero. Un rifiuto (o il semplice
mancato invio della conferma) lascia il sistema reale invariato.
"""
import time
import uuid
from enum import Enum
from typing import Callable, Optional


class RiskLevel(str, Enum):
    LOW = "LOW"           # sola lettura
    MEDIUM = "MEDIUM"      # scrittura reversibile e circoscritta (patch policy)
    HIGH = "HIGH"          # azione diretta su dispositivo, disruptiva ma recuperabile
    CRITICAL = "CRITICAL"  # distruttiva o difficilmente reversibile


# Comandi issueCommand: alcuni sono piu' distruttivi di altri.
_ISSUE_COMMAND_RISK = {
    "LOCK": RiskLevel.HIGH,
    "REBOOT": RiskLevel.HIGH,
    "RESET_PASSWORD": RiskLevel.HIGH,
    "START_LOST_MODE": RiskLevel.CRITICAL,
}

_TOOL_RISK = {
    "list_devices": RiskLevel.LOW,
    "get_device": RiskLevel.LOW,
    "list_policies": RiskLevel.LOW,
    "update_policy": RiskLevel.MEDIUM,
    "delete_policy": RiskLevel.CRITICAL,
    "wipe_device": RiskLevel.CRITICAL,
    # issue_command viene valutato caso per caso in base al campo command_type
}

# Solo i livelli qui sotto richiedono conferma esplicita prima dell'esecuzione.
_REQUIRES_CONFIRMATION = {RiskLevel.HIGH, RiskLevel.CRITICAL}


def classify(tool_name: str, arguments: dict) -> RiskLevel:
    if tool_name == "issue_command":
        command_type = arguments.get("command_type", "")
        return _ISSUE_COMMAND_RISK.get(command_type, RiskLevel.CRITICAL)
    return _TOOL_RISK.get(tool_name, RiskLevel.CRITICAL)


def requires_confirmation(risk: RiskLevel) -> bool:
    return risk in _REQUIRES_CONFIRMATION


def summarize(tool_name: str, arguments: dict) -> str:
    if tool_name == "update_policy":
        return f"Aggiornare la policy '{arguments.get('policy_id')}' con i campi: {arguments.get('policy_fields')}"
    if tool_name == "delete_policy":
        return f"ELIMINARE definitivamente la policy '{arguments.get('policy_id')}'. I dispositivi collegati resteranno senza policy."
    if tool_name == "issue_command":
        return f"Inviare il comando {arguments.get('command_type')} al dispositivo '{arguments.get('device_id')}'."
    if tool_name == "wipe_device":
        return f"CANCELLARE tutti i dati e rimuovere la gestione dal dispositivo '{arguments.get('device_id')}'. Operazione irreversibile."
    return f"Eseguire il tool '{tool_name}' con argomenti {arguments}."


class PendingActionStore:
    """Tiene traccia delle azioni ad alto rischio proposte ma non ancora
    confermate da un amministratore umano. Puramente in memoria: alla
    riavvio del server MCP le azioni sospese decadono, per non lasciare
    conferme "orfane" in giro."""

    def __init__(self, ttl_seconds: int = 15 * 60):
        self._actions: dict[str, dict] = {}
        self._ttl_seconds = ttl_seconds

    def create(self, tool_name: str, arguments: dict, risk: RiskLevel, summary: str) -> dict:
        action_id = str(uuid.uuid4())
        record = {
            "action_id": action_id,
            "tool_name": tool_name,
            "arguments": arguments,
            "risk": risk.value,
            "summary": summary,
            "created_at": time.time(),
        }
        self._actions[action_id] = record
        return record

    def get(self, action_id: str) -> Optional[dict]:
        self._evict_expired()
        return self._actions.get(action_id)

    def pop(self, action_id: str) -> Optional[dict]:
        self._evict_expired()
        return self._actions.pop(action_id, None)

    def _evict_expired(self):
        now = time.time()
        expired = [aid for aid, rec in self._actions.items() if now - rec["created_at"] > self._ttl_seconds]
        for aid in expired:
            self._actions.pop(aid, None)
