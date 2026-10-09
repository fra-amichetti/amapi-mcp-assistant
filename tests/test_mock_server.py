"""Scenari REST del mock server AMAPI: happy path e casi di errore simulati."""
from fastapi.testclient import TestClient

from mock_amapi_server.fixtures import ENTERPRISE_ID
from mock_amapi_server.main import create_app


def make_client():
    app = create_app()
    return TestClient(app)


def test_list_devices_happy_path():
    client = make_client()
    resp = client.get(f"/v1/{ENTERPRISE_ID}/devices")
    assert resp.status_code == 200
    devices = resp.json()["devices"]
    assert len(devices) == 3
    assert any(d["connectivity"] == "OFFLINE" for d in devices)


def test_get_device_not_found():
    client = make_client()
    resp = client.get(f"/v1/{ENTERPRISE_ID}/devices/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["error"]["status"] == "NOT_FOUND"


def test_patch_policy_success_bumps_version():
    client = make_client()
    resp = client.patch(
        f"/v1/{ENTERPRISE_ID}/policies/policy_sales",
        json={"cameraDisabled": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["cameraDisabled"] is True
    assert body["version"] == "4"  # partiva da "3" nelle fixture


def test_patch_policy_invalid_enum_returns_400():
    client = make_client()
    resp = client.patch(
        f"/v1/{ENTERPRISE_ID}/policies/policy_sales",
        json={"passwordRequirements": {"passwordQuality": "NOT_A_REAL_ENUM"}},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["status"] == "INVALID_ARGUMENT"


def test_issue_command_online_device_executes_immediately():
    client = make_client()
    resp = client.post(
        f"/v1/{ENTERPRISE_ID}/devices/pixel-9-pro-sales-01:issueCommand",
        json={"type": "LOCK"},
    )
    assert resp.status_code == 200
    assert resp.json()["state"] == "EXECUTED"


def test_issue_command_offline_device_stays_pending():
    client = make_client()
    resp = client.post(
        f"/v1/{ENTERPRISE_ID}/devices/samsung-a54-warehouse-03:issueCommand",
        json={"type": "REBOOT"},
    )
    assert resp.status_code == 200
    assert resp.json()["state"] == "PENDING"


def test_issue_command_invalid_type_returns_400():
    client = make_client()
    resp = client.post(
        f"/v1/{ENTERPRISE_ID}/devices/pixel-9-pro-sales-01:issueCommand",
        json={"type": "FLY_TO_THE_MOON"},
    )
    assert resp.status_code == 400


def test_wipe_device_then_get_returns_404():
    client = make_client()
    resp = client.delete(f"/v1/{ENTERPRISE_ID}/devices/pixel-8-support-02")
    assert resp.status_code == 200
    resp2 = client.get(f"/v1/{ENTERPRISE_ID}/devices/pixel-8-support-02")
    assert resp2.status_code == 404


def test_scenario_injection_forces_rate_limit_once():
    client = make_client()
    set_resp = client.post("/_scenario", json={"status_code": 429, "path_prefix": "/v1", "times": 1})
    assert set_resp.status_code == 200

    resp = client.get(f"/v1/{ENTERPRISE_ID}/devices")
    assert resp.status_code == 429
    assert resp.json()["error"]["status"] == "RESOURCE_EXHAUSTED"

    # dopo aver consumato lo scenario, la richiesta successiva torna normale
    resp2 = client.get(f"/v1/{ENTERPRISE_ID}/devices")
    assert resp2.status_code == 200


def test_scenario_scoped_to_method_does_not_affect_other_verbs():
    client = make_client()
    client.post("/_scenario", json={"status_code": 403, "path_prefix": "/v1", "method": "DELETE", "times": 5})

    read_resp = client.get(f"/v1/{ENTERPRISE_ID}/devices")
    assert read_resp.status_code == 200

    delete_resp = client.delete(f"/v1/{ENTERPRISE_ID}/devices/pixel-9-pro-sales-01")
    assert delete_resp.status_code == 403
