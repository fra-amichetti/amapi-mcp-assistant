"""Flotta e policy fittizie usate come stato in memoria del mock server AMAPI.

Il dataset e' deterministico (nessuna randomizzazione) cosi' che i test e la demo
diano sempre lo stesso risultato di partenza. Ogni riavvio del processo resetta
lo stato: e' un mock, non un database persistente.
"""
import copy
import os

ENTERPRISE_ID = os.environ.get("MOCK_ENTERPRISE_ID", "enterprises/LC00demo123")

_INITIAL_DEVICES = [
    {
        "name": f"{ENTERPRISE_ID}/devices/pixel-9-pro-sales-01",
        "state": "ACTIVE",
        "connectivity": "ONLINE",
        "policyName": f"{ENTERPRISE_ID}/policies/policy_sales",
        "policyCompliant": True,
        "nonComplianceDetails": [],
        "apiLevel": 34,
        "hardwareInfo": {
            "brand": "Google",
            "model": "Pixel 9 Pro",
            "serialNumber": "MOCK-SALES-001",
        },
        "softwareInfo": {"androidVersion": "14"},
        "lastStatusReportTime": "2026-08-15T09:12:00Z",
    },
    {
        "name": f"{ENTERPRISE_ID}/devices/pixel-8-support-02",
        "state": "ACTIVE",
        "connectivity": "ONLINE",
        "policyName": f"{ENTERPRISE_ID}/policies/policy_support",
        "policyCompliant": False,
        "nonComplianceDetails": [
            {"settingName": "cameraDisabled", "nonComplianceReason": "MANAGEMENT_MODE"}
        ],
        "apiLevel": 34,
        "hardwareInfo": {
            "brand": "Google",
            "model": "Pixel 8",
            "serialNumber": "MOCK-SUPPORT-002",
        },
        "softwareInfo": {"androidVersion": "14"},
        "lastStatusReportTime": "2026-08-16T18:40:00Z",
    },
    {
        "name": f"{ENTERPRISE_ID}/devices/samsung-a54-warehouse-03",
        "state": "ACTIVE",
        "connectivity": "OFFLINE",
        "policyName": f"{ENTERPRISE_ID}/policies/policy_sales",
        "policyCompliant": True,
        "nonComplianceDetails": [],
        "apiLevel": 33,
        "hardwareInfo": {
            "brand": "Samsung",
            "model": "Galaxy A54",
            "serialNumber": "MOCK-WAREHOUSE-003",
        },
        "softwareInfo": {"androidVersion": "13"},
        "lastStatusReportTime": "2026-08-10T07:05:00Z",
    },
]

_INITIAL_POLICIES = {
    "policy_sales": {
        "name": f"{ENTERPRISE_ID}/policies/policy_sales",
        "version": "3",
        "debuggingFeaturesAllowed": False,
        "cameraDisabled": False,
        "passwordRequirements": {
            "passwordQuality": "NUMERIC_COMPLEX",
            "passwordMinimumLength": 6,
        },
        "applications": [
            {"packageName": "com.google.android.youtube", "installType": "FORCE_INSTALLED"}
        ],
    },
    "policy_support": {
        "name": f"{ENTERPRISE_ID}/policies/policy_support",
        "version": "1",
        "debuggingFeaturesAllowed": True,
        "cameraDisabled": False,
        "passwordRequirements": {
            "passwordQuality": "ALPHABETIC",
            "passwordMinimumLength": 4,
        },
        "applications": [],
    },
}

_ENTERPRISE_INFO = {
    "name": ENTERPRISE_ID,
    "enterpriseDisplayName": "Tesi MCP Demo Corp",
    "appAutoApprovalEnabled": True,
}

VALID_PASSWORD_QUALITIES = {
    "PASSWORD_QUALITY_UNSPECIFIED",
    "NONE",
    "BIOMETRIC_WEAK",
    "SOMETHING",
    "NUMERIC",
    "NUMERIC_COMPLEX",
    "ALPHABETIC",
    "ALPHANUMERIC",
    "COMPLEX",
}

VALID_COMMAND_TYPES = {"LOCK", "REBOOT", "RESET_PASSWORD", "START_LOST_MODE"}


class Store:
    """Contenitore mutabile dello stato del mock, isolato per ogni istanza
    dell'app (utile nei test, che creano una Store pulita per ogni caso)."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.enterprise = copy.deepcopy(_ENTERPRISE_INFO)
        self.devices = {
            d["name"].rsplit("/", 1)[-1]: copy.deepcopy(d) for d in _INITIAL_DEVICES
        }
        self.policies = copy.deepcopy(_INITIAL_POLICIES)
        self._command_counter = 0
        self._commands = {}

    def next_command_id(self):
        self._command_counter += 1
        return f"cmd-{self._command_counter:06d}"
