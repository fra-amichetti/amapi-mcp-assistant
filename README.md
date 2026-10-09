# AMAPI MCP Assistant

A thesis project exploring how Large Language Models (LLMs) can provide a natural-language interface for Android Enterprise device management through the Model Context Protocol (MCP).

The prototype combines a conversational web UI, an LLM-driven MCP host, a custom MCP server for write operations, and a local mock Android Management API (AMAPI). Sensitive operations use an explicit human-confirmation flow. The mock environment makes it possible to explore the workflow without connecting to a real enterprise or device fleet.

> **Research prototype:** This project is intended for educational and demonstration purposes. Do not connect it to production infrastructure without a thorough security review.

## Highlights

- Conversational interface for device-management tasks.
- MCP host connecting to a custom write server and, optionally, Google's official read-only MCP server.
- Risk classification for write operations and explicit confirmation for high-risk actions.
- Local mock AMAPI service with fixtures and configurable error scenarios.
- Automated tests for mock API behavior, write-operation safeguards, and backend endpoints.
- Multiple demo modes: Anthropic API, a local Ollama model, or a scripted `FAKE_LLM` mode.

## Architecture

```text
Browser UI (frontend/index.html)
          |
          v
FastAPI backend (backend/app.py)
          |
          +--> LLM agent (backend/llm_agent.py)
          |
          +--> MCP host (backend/mcp_host.py)
                    |
                    +--> Custom MCP write server (mcp_write_server/)
                    |          |
                    |          v
                    |     AMAPI client
                    |          |
                    |          v
                    |     Local mock AMAPI (mock_amapi_server/)
                    |
                    +--> Optional official Google MCP server (read-only)
```

## Tech stack

- Python, FastAPI, Uvicorn
- Model Context Protocol (`mcp` Python SDK)
- Anthropic API or Ollama for LLM tool-calling
- HTTPX and Google authentication libraries
- HTML, CSS, and JavaScript frontend
- Pytest for automated tests

## Requirements

- Python 3.10+ (a recent supported Python version is recommended)
- `pip`
- An Anthropic API key **only** if using the Anthropic provider
- Ollama and a downloaded model **only** if using the Ollama provider

## Setup

```bash
git clone <YOUR_REPOSITORY_URL>
cd amapi-mcp-assistant
python3 -m venv .venv
source .venv/bin/activate        # macOS/Linux
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and configure only the provider you intend to use. Never commit `.env` or real credentials.

## Run the demo

Start the mock AMAPI service in Terminal 1:

```bash
source .venv/bin/activate
uvicorn mock_amapi_server.main:app --host 127.0.0.1 --port 8001
```

Start the backend in Terminal 2:

```bash
source .venv/bin/activate
uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

Then open `http://127.0.0.1:8000` in your browser. The backend starts the custom MCP write server as a subprocess; it does not need to be started separately.

### Demo without an external LLM API

For a scripted demo that does not call an LLM provider, set `FAKE_LLM=1` before starting the backend:

```bash
export FAKE_LLM=1
uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

This mode uses keyword-based scripted behavior and is not equivalent to a real language model.

### Use a local Ollama model

Install and start Ollama, then download a model, for example:

```bash
ollama pull qwen2.5:7b
export LLM_PROVIDER=ollama
export OLLAMA_MODEL=qwen2.5:7b
uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

### Optional Google MCP read-only integration

The integration with Google's official MCP server is optional. It requires valid Google service-account credentials and an enterprise ID configured through environment variables. The default mock setup does not require Google credentials. **Do not add service-account JSON files to this repository.** If you configure the real integration, keep credentials outside the repository and follow Google's security guidance.

## Tests

With the virtual environment activated, run:

```bash
pytest tests/ -v
```

The tests cover the mock API, custom MCP write operations and safeguards, and backend chat/confirmation endpoints. Tests are designed to use mocked or scripted LLM behavior rather than making real Anthropic API calls.

## Example interactions

- List the organization's devices.
- Update a device policy, such as disabling the camera.
- Lock a device (high-risk action requiring confirmation).
- Request a device data wipe (critical and potentially irreversible action requiring confirmation).

The mock server includes scenarios for common API errors. Use these only in the local demo environment.

## Repository layout

```text
backend/             FastAPI application, LLM agent, and MCP host
frontend/            Conversational web interface
mcp_write_server/    Custom MCP tools, risk checks, and AMAPI client
mock_amapi_server/   Local mock API, fixtures, and error scenarios
tests/               Automated tests
.env.example         Environment-variable template
requirements.txt     Python dependencies
```

## Thesis context

This repository accompanies a bachelor's thesis on integrating LLMs into Android device management using MCP. The implementation focuses on bridging natural-language requests and AMAPI operations while keeping a human in control of sensitive actions.

## Security notes

- Do not commit API keys, service-account files, access tokens, `.env`, local databases, or logs.
- The mock API is intended for local testing, not public deployment.
- Human confirmation is one safeguard, not a complete security guarantee. Review authorization, validation, audit logging, and deployment configuration before any real-world use.

## License

No license has been added yet. Unless a license is included, others do not automatically have permission to reuse, modify, or redistribute the code. Choose a license before inviting reuse.
