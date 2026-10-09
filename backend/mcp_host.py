"""Host MCP dell'assistente: coordina due client verso due server MCP diversi.

- Il server MCP custom (`mcp_write_server`), lanciato come sottoprocesso
  locale via stdio, sempre disponibile: espone le operazioni di scrittura.
- Il server MCP ufficiale di Google (Streamable HTTP, sola lettura),
  collegato solo se sono presenti credenziali valide.

Espone all'agente LLM un unico elenco di tool aggregato, e instrada ogni
chiamata al client giusto in base a chi possiede quel tool — lo stesso
principio di isolamento tra server descritto nel capitolo 2 della tesi: ogni
client conosce solo il proprio server, e' l'host che aggrega il contesto.
"""
import json
import logging
import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path

import mcp.types as types
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from . import google_mcp_client

logger = logging.getLogger("mcp_host")

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Determina il formato dei tool da esporre all'LLM: Anthropic (default) o
# Ollama. Letto qui (non importato da llm_agent.py) per evitare un
# dipendenza circolare tra i due moduli.
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "anthropic").strip().lower()


def _tool_to_anthropic_schema(tool: types.Tool) -> dict:
    return {
        "name": tool.name,
        "description": tool.description or "",
        "input_schema": tool.inputSchema,
    }


def _tool_to_ollama_schema(tool: types.Tool) -> dict:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": tool.inputSchema,
        },
    }


def _tool_schema(tool: types.Tool) -> dict:
    if LLM_PROVIDER == "ollama":
        return _tool_to_ollama_schema(tool)
    return _tool_to_anthropic_schema(tool)


def _parse_call_tool_result(result: types.CallToolResult) -> dict:
    if result.structuredContent is not None:
        return result.structuredContent
    text_parts = [block.text for block in result.content if isinstance(block, types.TextContent)]
    joined = "\n".join(text_parts)
    if result.isError:
        return {"status": "error", "message": joined or "Errore sconosciuto dal server MCP."}
    if not joined:
        return {"status": "executed", "result": {}}
    try:
        return json.loads(joined)
    except (json.JSONDecodeError, TypeError):
        return {"status": "executed", "result": joined}


class McpHost:
    def __init__(self):
        self._stack = AsyncExitStack()
        self.write_session: ClientSession | None = None
        self._tools: list[dict] = []
        self._tool_source: dict[str, str] = {}  # tool_name -> "write" | "google"
        self.google_enabled = False

    async def start(self):
        server_params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "mcp_write_server.server"],
            cwd=str(PROJECT_ROOT),
            env=dict(os.environ),
        )
        read, write = await self._stack.enter_async_context(stdio_client(server_params))
        self.write_session = await self._stack.enter_async_context(ClientSession(read, write))
        await self.write_session.initialize()

        write_tools = (await self.write_session.list_tools()).tools
        for tool in write_tools:
            self._tools.append(_tool_schema(tool))
            self._tool_source[tool.name] = "write"
        logger.info("Server MCP custom (scrittura) collegato: %d tool disponibili.", len(write_tools))

        if google_mcp_client.is_configured():
            try:
                google_tools = await google_mcp_client.list_tools()
                for tool in google_tools:
                    self._tools.append(_tool_schema(tool))
                    self._tool_source[tool.name] = "google"
                self.google_enabled = True
                logger.info("Server MCP ufficiale di Google collegato: %d tool disponibili.", len(google_tools))
            except Exception:
                logger.exception(
                    "Credenziali Google presenti ma connessione al server MCP ufficiale fallita: "
                    "si prosegue in modalita' mock-only."
                )
        else:
            logger.info(
                "Nessuna credenziale Google configurata (GOOGLE_CREDENTIALS_PATH / GOOGLE_ENTERPRISE_ID): "
                "modalita' mock-only, solo server MCP custom."
            )

    async def stop(self):
        await self._stack.aclose()

    def list_tools(self) -> list[dict]:
        return self._tools

    async def call_tool(self, name: str, arguments: dict) -> dict:
        source = self._tool_source.get(name)
        if source == "write":
            result = await self.write_session.call_tool(name, arguments)
            return _parse_call_tool_result(result)
        if source == "google":
            result = await google_mcp_client.call_tool(name, arguments)
            return _parse_call_tool_result(result)
        return {"status": "error", "message": f"Tool sconosciuto o server non disponibile: {name}"}
