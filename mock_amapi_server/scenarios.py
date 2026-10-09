"""Iniezione configurabile di errori realistici sugli endpoint del mock AMAPI.

Serve a riprodurre, in un ambiente di test locale, le condizioni di errore che
un'infrastruttura reale puo' presentare (credenziali scadute, quota superata,
guasti temporanei) senza dover disporre di una flotta reale di dispositivi.
"""
from fastapi import HTTPException

_ERROR_BODIES = {
    401: {"error": {"code": 401, "status": "UNAUTHENTICATED", "message": "Request had invalid authentication credentials."}},
    403: {"error": {"code": 403, "status": "PERMISSION_DENIED", "message": "The caller does not have permission to execute this operation."}},
    404: {"error": {"code": 404, "status": "NOT_FOUND", "message": "Requested resource not found."}},
    429: {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "Quota exceeded for quota metric 'Write requests'."}},
    500: {"error": {"code": 500, "status": "INTERNAL", "message": "Internal error encountered."}},
    503: {"error": {"code": 503, "status": "UNAVAILABLE", "message": "The service is currently unavailable."}},
}


class ScenarioController:
    """Stato dello scenario di errore attivo, condiviso da tutte le richieste
    finche' non viene consumato (times) o resettato esplicitamente."""

    def __init__(self):
        self.reset()

    def reset(self):
        self._active = None  # dict con status_code, path_prefix, method, remaining

    def set(self, status_code: int, path_prefix: str = "", method: str | None = None, times: int = 1):
        if status_code not in _ERROR_BODIES:
            raise ValueError(f"Codice di errore non simulabile: {status_code}")
        self._active = {
            "status_code": status_code,
            "path_prefix": path_prefix,
            "method": method.upper() if method else None,
            "remaining": max(1, times),
        }

    def current(self):
        return dict(self._active) if self._active else None

    def maybe_raise(self, request_path: str, request_method: str):
        scenario = self._active
        if not scenario:
            return
        if scenario["path_prefix"] and not request_path.startswith(scenario["path_prefix"]):
            return
        if scenario["method"] and scenario["method"] != request_method.upper():
            return

        status_code = scenario["status_code"]
        body = _ERROR_BODIES[status_code]
        scenario["remaining"] -= 1
        if scenario["remaining"] <= 0:
            self._active = None
        raise HTTPException(status_code=status_code, detail=body)
