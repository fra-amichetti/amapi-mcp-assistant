"""Mock Server AMAPI — riproduce gli endpoint REST dell'Android Management API.

Accetta le stesse richieste (stessi path, stessi verbi HTTP, stesso formato
JSON) del servizio reale di Google, ma risponde con dati fittizi tenuti in
memoria e puo' simulare casi di errore realistici tramite l'endpoint di
controllo `/_scenario`. Questo permette di validare il server MCP custom
(`mcp_write_server`) senza dover disporre di un'enterprise AMAPI reale ne' di
una flotta di dispositivi Android fisici.
"""
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from .fixtures import Store, VALID_COMMAND_TYPES, VALID_PASSWORD_QUALITIES
from .scenarios import ScenarioController


class ScenarioRequest(BaseModel):
    status_code: int
    path_prefix: str = ""
    method: Optional[str] = None
    times: int = 1


def create_app() -> FastAPI:
    store = Store()
    scenario = ScenarioController()
    app = FastAPI(title="Mock AMAPI Server", version="1.0.0")
    app.state.store = store
    app.state.scenario = scenario

    @app.middleware("http")
    async def enforce_scenario(request: Request, call_next):
        # Il controllo dello scenario non si applica agli endpoint di gestione
        # del mock stesso, solo alle rotte che imitano l'AMAPI reale (/v1/...).
        # L'eccezione va intercettata qui (non tramite @app.exception_handler,
        # che nello stack di Starlette si trova "sotto" a questo middleware e
        # non la vedrebbe mai) e trasformata subito in risposta JSON.
        if request.url.path.startswith("/v1/"):
            try:
                scenario.maybe_raise(request.url.path, request.method)
            except HTTPException as exc:
                from fastapi.responses import JSONResponse

                body = exc.detail if isinstance(exc.detail, dict) else {"error": {"code": exc.status_code, "message": str(exc.detail)}}
                return JSONResponse(status_code=exc.status_code, content=body)
        return await call_next(request)

    @app.exception_handler(HTTPException)
    async def amapi_style_errors(request: Request, exc: HTTPException):
        # Restituisce direttamente il corpo stile-Google se presente in detail,
        # cosi' come farebbe l'errore reale di AMAPI, altrimenti fallback standard.
        from fastapi.responses import JSONResponse

        body = exc.detail if isinstance(exc.detail, dict) else {"error": {"code": exc.status_code, "message": str(exc.detail)}}
        return JSONResponse(status_code=exc.status_code, content=body)

    def _device_or_404(device_id: str):
        device = store.devices.get(device_id)
        if device is None:
            raise HTTPException(status_code=404, detail={"error": {"code": 404, "status": "NOT_FOUND", "message": f"Device {device_id} not found"}})
        return device

    def _policy_id(raw_id: str) -> str:
        return raw_id.rsplit("/", 1)[-1]

    # ---- Controllo scenari (non fa parte dell'AMAPI reale) ----
    @app.post("/_scenario")
    def set_scenario(payload: ScenarioRequest):
        try:
            scenario.set(payload.status_code, payload.path_prefix, payload.method, payload.times)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return {"active_scenario": scenario.current()}

    @app.delete("/_scenario")
    def clear_scenario():
        scenario.reset()
        return {"active_scenario": None}

    @app.post("/_reset")
    def reset_store():
        store.reset()
        scenario.reset()
        return {"status": "reset"}

    # ---- enterprises.get ----
    @app.get("/v1/enterprises/{enterprise_id}")
    def get_enterprise(enterprise_id: str):
        if enterprise_id != store.enterprise["name"].split("/")[-1]:
            raise HTTPException(status_code=404, detail={"error": {"code": 404, "status": "NOT_FOUND", "message": "Enterprise not found"}})
        return store.enterprise

    # ---- enterprises.devices.list ----
    @app.get("/v1/enterprises/{enterprise_id}/devices")
    def list_devices(enterprise_id: str, pageSize: int = 50, pageToken: str = ""):
        devices = list(store.devices.values())
        return {"devices": devices}

    # ---- enterprises.devices.get ----
    @app.get("/v1/enterprises/{enterprise_id}/devices/{device_id}")
    def get_device(enterprise_id: str, device_id: str):
        return _device_or_404(device_id)

    # ---- enterprises.devices.delete (wipe) ----
    @app.delete("/v1/enterprises/{enterprise_id}/devices/{device_id}")
    def wipe_device(enterprise_id: str, device_id: str):
        _device_or_404(device_id)
        del store.devices[device_id]
        return {}

    # ---- enterprises.devices.issueCommand ----
    @app.post("/v1/enterprises/{enterprise_id}/devices/{device_id}:issueCommand")
    def issue_command(enterprise_id: str, device_id: str, payload: dict):
        device = _device_or_404(device_id)
        command_type = payload.get("type")
        if command_type not in VALID_COMMAND_TYPES:
            raise HTTPException(status_code=400, detail={"error": {"code": 400, "status": "INVALID_ARGUMENT", "message": f"Unsupported command type: {command_type}"}})

        command_id = store.next_command_id()
        # Un dispositivo offline non puo' eseguire il comando immediatamente:
        # AMAPI reale lo terrebbe in coda finche' il device non torna online.
        state = "EXECUTED" if device["connectivity"] == "ONLINE" else "PENDING"
        operation = {
            "name": f"{device['name']}/operations/{command_id}",
            "commandId": command_id,
            "type": command_type,
            "state": state,
            "createTime": "2026-08-17T10:00:00Z",
        }
        return operation

    # ---- enterprises.policies.list ----
    @app.get("/v1/enterprises/{enterprise_id}/policies")
    def list_policies(enterprise_id: str, pageSize: int = 50, pageToken: str = ""):
        return {"policies": list(store.policies.values())}

    # ---- enterprises.policies.patch ----
    @app.patch("/v1/enterprises/{enterprise_id}/policies/{policy_id}")
    def patch_policy(enterprise_id: str, policy_id: str, payload: dict):
        pid = _policy_id(policy_id)
        quality = (payload.get("passwordRequirements") or {}).get("passwordQuality")
        if quality is not None and quality not in VALID_PASSWORD_QUALITIES:
            raise HTTPException(status_code=400, detail={"error": {"code": 400, "status": "INVALID_ARGUMENT", "message": f"Invalid passwordQuality enum value: {quality}"}})

        existing = store.policies.get(pid, {"name": f"{store.enterprise['name']}/policies/{pid}", "version": "0"})
        updated = {**existing, **payload}
        updated["name"] = f"{store.enterprise['name']}/policies/{pid}"
        updated["version"] = str(int(existing.get("version", "0")) + 1)
        store.policies[pid] = updated
        return updated

    # ---- enterprises.policies.delete ----
    @app.delete("/v1/enterprises/{enterprise_id}/policies/{policy_id}")
    def delete_policy(enterprise_id: str, policy_id: str):
        pid = _policy_id(policy_id)
        if pid not in store.policies:
            raise HTTPException(status_code=404, detail={"error": {"code": 404, "status": "NOT_FOUND", "message": f"Policy {pid} not found"}})
        del store.policies[pid]
        return {}

    return app


app = create_app()
