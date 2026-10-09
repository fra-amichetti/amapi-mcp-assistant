"""Client REST verso l'Android Management API.

Punta di default al mock server locale (`AMAPI_BASE_URL`), ma lo stesso codice
funziona senza modifiche contro l'endpoint reale di Google
(`https://androidmanagement.googleapis.com`), a patto di fornire un token
Bearer valido: cambia solo la configurazione, non la logica del client.

Asincrono per non bloccare il loop dell'event loop del server MCP mentre
attende la risposta HTTP, e per poter essere testato in-process contro il
mock server tramite `httpx.ASGITransport` senza aprire una porta di rete.
"""
import os
from dataclasses import dataclass
from typing import Optional

import httpx


class AmapiError(Exception):
    def __init__(self, status_code: int, message: str, raw: Optional[dict] = None):
        super().__init__(f"AMAPI error {status_code}: {message}")
        self.status_code = status_code
        self.message = message
        self.raw = raw or {}


def _short_id(raw_id: str) -> str:
    """Riduce un nome di risorsa AMAPI completo (es.
    'enterprises/LC00demo123/policies/policy_sales') al solo ultimo
    segmento ('policy_sales'). Se non c'e' nessun '/' restituisce raw_id
    invariato. Stesso comportamento di _policy_id() nel mock server
    (mock_amapi_server/main.py), cosi' l'LLM puo' passare indifferentemente
    l'ID breve o il nome di risorsa completo senza differenze di esito."""
    return raw_id.rsplit("/", 1)[-1]


@dataclass
class AmapiClient:
    base_url: str
    enterprise_id: str
    token_provider: Optional[callable] = None  # () -> str, usato solo contro AMAPI reale
    transport: Optional[httpx.AsyncBaseTransport] = None  # iniettabile nei test (ASGITransport)

    @classmethod
    def from_env(cls) -> "AmapiClient":
        base_url = os.environ.get("AMAPI_BASE_URL", "http://127.0.0.1:8001")
        enterprise_id = os.environ.get("MOCK_ENTERPRISE_ID", "enterprises/LC00demo123")
        return cls(base_url=base_url, enterprise_id=enterprise_id)

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.token_provider is not None:
            headers["Authorization"] = f"Bearer {self.token_provider()}"
        return headers

    async def _request(self, method: str, path: str, json_body: Optional[dict] = None) -> dict:
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=15.0, transport=self.transport) as client:
            response = await client.request(method, url, headers=self._headers(), json=json_body)
        if response.status_code >= 400:
            try:
                body = response.json()
            except ValueError:
                body = {}
            message = body.get("error", {}).get("message", response.text)
            raise AmapiError(response.status_code, message, raw=body)
        if response.text:
            return response.json()
        return {}

    # ---- operazioni di scrittura implementate dal server MCP custom ----

    async def patch_policy(self, policy_id: str, policy_fields: dict) -> dict:
        path = f"/v1/{self.enterprise_id}/policies/{_short_id(policy_id)}"
        return await self._request("PATCH", path, json_body=policy_fields)

    async def delete_policy(self, policy_id: str) -> dict:
        path = f"/v1/{self.enterprise_id}/policies/{_short_id(policy_id)}"
        return await self._request("DELETE", path)

    async def issue_command(self, device_id: str, command_type: str, extra: Optional[dict] = None) -> dict:
        path = f"/v1/{self.enterprise_id}/devices/{_short_id(device_id)}:issueCommand"
        body = {"type": command_type, **(extra or {})}
        return await self._request("POST", path, json_body=body)

    async def wipe_device(self, device_id: str) -> dict:
        path = f"/v1/{self.enterprise_id}/devices/{_short_id(device_id)}"
        return await self._request("DELETE", path)

    async def get_device(self, device_id: str) -> dict:
        path = f"/v1/{self.enterprise_id}/devices/{_short_id(device_id)}"
        return await self._request("GET", path)

    # ---- operazioni di sola lettura (solo per il mock locale) ----

    async def list_devices(self) -> dict:
        path = f"/v1/{self.enterprise_id}/devices"
        return await self._request("GET", path)

    async def list_policies(self) -> dict:
        path = f"/v1/{self.enterprise_id}/policies"
        return await self._request("GET", path)
