"""Test del server MCP custom: classificazione del rischio e flusso
propose/confirm per le operazioni di scrittura, senza passare per l'LLM ne'
per un vero processo stdio (si chiamano direttamente gli handler)."""
import httpx
import pytest

import mcp_write_server.server as ws
from mcp_write_server.amapi_client import AmapiClient, AmapiError
from mcp_write_server.risk import PendingActionStore
from mock_amapi_server.fixtures import ENTERPRISE_ID
from mock_amapi_server.main import create_app


@pytest.fixture(autouse=True)
def wired_mock_backend(monkeypatch):
    """Ogni test riparte con un mock AMAPI e una coda di azioni pending puliti,
    collegati in-process via ASGITransport (nessuna rete reale coinvolta)."""
    mock_app = create_app()
    transport = httpx.ASGITransport(app=mock_app)
    test_amapi = AmapiClient(
        base_url="http://mock-amapi.local",
        enterprise_id=ENTERPRISE_ID,
        transport=transport,
    )
    monkeypatch.setattr(ws, "amapi", test_amapi)
    monkeypatch.setattr(ws, "pending_actions", PendingActionStore())
    return test_amapi


async def test_update_policy_executes_immediately_no_confirmation():
    result = await ws.handle_call_tool("update_policy", {"policy_id": "policy_sales", "policy_fields": {"cameraDisabled": True}})
    assert result["status"] == "executed"
    assert result["result"]["cameraDisabled"] is True


async def test_update_policy_accepts_full_resource_name_same_as_short_id():
    """Il tool deve accettare sia l'ID breve (es. 'policy_sales') sia il nome
    di risorsa AMAPI completo (es. 'enterprises/LC00demo123/policies/policy_sales'),
    con lo stesso esito verso il mock server: nessun 404 per un ID non ripulito,
    e lo stesso nome di risorsa risultante in entrambi i casi."""
    full_resource_name = f"{ENTERPRISE_ID}/policies/policy_sales"

    result_full = await ws.handle_call_tool(
        "update_policy", {"policy_id": full_resource_name, "policy_fields": {"cameraDisabled": True}}
    )
    result_short = await ws.handle_call_tool(
        "update_policy", {"policy_id": "policy_sales", "policy_fields": {"cameraDisabled": True}}
    )

    assert result_full["status"] == "executed"
    assert result_short["status"] == "executed"
    assert result_full["result"]["name"] == f"{ENTERPRISE_ID}/policies/policy_sales"
    assert result_full["result"]["name"] == result_short["result"]["name"]
    assert result_full["result"]["cameraDisabled"] is True
    assert result_short["result"]["cameraDisabled"] is True


async def test_wipe_device_is_proposed_not_executed():
    result = await ws.handle_call_tool("wipe_device", {"device_id": "pixel-8-support-02"})
    assert result["status"] == "confirmation_required"
    assert result["risk"] == "CRITICAL"
    assert "action_id" in result

    # Il dispositivo non deve essere stato toccato finche' non arriva la conferma.
    device = await ws.amapi.get_device("pixel-8-support-02")
    assert device["name"].endswith("pixel-8-support-02")


async def test_wipe_device_confirmed_executes_and_removes_device(wired_mock_backend):
    propose = await ws.handle_call_tool("wipe_device", {"device_id": "pixel-8-support-02"})
    action_id = propose["action_id"]

    confirm = await ws.handle_call_tool("confirm_action", {"action_id": action_id})
    assert confirm["status"] == "executed"

    with pytest.raises(AmapiError) as exc_info:
        await wired_mock_backend.get_device("pixel-8-support-02")
    assert exc_info.value.status_code == 404


async def test_wipe_device_rejected_leaves_device_untouched(wired_mock_backend):
    propose = await ws.handle_call_tool("wipe_device", {"device_id": "pixel-8-support-02"})
    assert propose["status"] == "confirmation_required"
    # L'admin rifiuta: il backend (livello superiore) semplicemente non invoca
    # confirm_action. Il dispositivo deve restare invariato.
    device = await wired_mock_backend.get_device("pixel-8-support-02")
    assert device["state"] == "ACTIVE"


async def test_confirm_action_with_unknown_id_returns_error():
    result = await ws.handle_call_tool("confirm_action", {"action_id": "non-esiste"})
    assert result["status"] == "error"


async def test_confirm_action_cannot_be_replayed_twice():
    propose = await ws.handle_call_tool("wipe_device", {"device_id": "pixel-9-pro-sales-01"})
    action_id = propose["action_id"]
    first = await ws.handle_call_tool("confirm_action", {"action_id": action_id})
    assert first["status"] == "executed"
    second = await ws.handle_call_tool("confirm_action", {"action_id": action_id})
    assert second["status"] == "error"


@pytest.mark.parametrize(
    "command_type,expected_risk",
    [("LOCK", "HIGH"), ("REBOOT", "HIGH"), ("RESET_PASSWORD", "HIGH"), ("START_LOST_MODE", "CRITICAL")],
)
async def test_issue_command_risk_classification(command_type, expected_risk):
    result = await ws.handle_call_tool(
        "issue_command", {"device_id": "pixel-9-pro-sales-01", "command_type": command_type}
    )
    assert result["status"] == "confirmation_required"
    assert result["risk"] == expected_risk


async def test_issue_command_confirmed_reaches_mock_server():
    propose = await ws.handle_call_tool(
        "issue_command", {"device_id": "pixel-9-pro-sales-01", "command_type": "LOCK"}
    )
    confirm = await ws.handle_call_tool("confirm_action", {"action_id": propose["action_id"]})
    assert confirm["status"] == "executed"
    assert confirm["result"]["state"] == "EXECUTED"


async def test_delete_policy_requires_confirmation_and_is_critical():
    result = await ws.handle_call_tool("delete_policy", {"policy_id": "policy_support"})
    assert result["status"] == "confirmation_required"
    assert result["risk"] == "CRITICAL"


async def test_list_tools_exposes_all_write_tools():
    tools = await ws.handle_list_tools()
    names = {t.name for t in tools}
    assert names == {
        "list_devices",
        "get_device",
        "list_policies",
        "update_policy",
        "delete_policy",
        "issue_command",
        "wipe_device",
        "confirm_action",
    }
