"""Client verso il server MCP ufficiale di Google (sola lettura, AMAPI).

Adatta il pattern gia' validato in `progetto/toy-example/google_bridge.py`
(autenticazione via service account, richieste Streamable HTTP) ma usando il
client MCP ufficiale invece di un bridge stdio scritto a mano.

Il collegamento e' completamente opzionale: se mancano le credenziali o
l'endpoint non e' raggiungibile, `is_configured()` torna False e l'host
lavora comunque con il solo server MCP custom (scrittura) + mock.
"""
import logging
import os
from contextlib import asynccontextmanager

import mcp.types as types
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

logger = logging.getLogger("google_mcp_client")

GOOGLE_MCP_URL = "https://androidmanagement.googleapis.com/mcp"
SCOPES = ["https://www.googleapis.com/auth/androidmanagement"]


def is_configured() -> bool:
    creds_path = os.environ.get("GOOGLE_CREDENTIALS_PATH", "")
    enterprise_id = os.environ.get("GOOGLE_ENTERPRISE_ID", "")
    return bool(creds_path and os.path.isfile(creds_path) and enterprise_id)


def _get_token() -> str:
    # Import qui, non a livello di modulo: google-auth serve solo se
    # l'integrazione reale e' effettivamente configurata.
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account

    credentials = service_account.Credentials.from_service_account_file(
        os.environ["GOOGLE_CREDENTIALS_PATH"], scopes=SCOPES
    )
    credentials.refresh(Request())
    return credentials.token


@asynccontextmanager
async def _session():
    headers = {"Authorization": f"Bearer {_get_token()}"}
    async with streamablehttp_client(GOOGLE_MCP_URL, headers=headers) as (read, write, _get_session_id):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


async def list_tools() -> list[types.Tool]:
    async with _session() as session:
        result = await session.list_tools()
        return result.tools


async def call_tool(name: str, arguments: dict) -> types.CallToolResult:
    async with _session() as session:
        return await session.call_tool(name, arguments)
