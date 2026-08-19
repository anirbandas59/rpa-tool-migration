"""Tests for connection reference derivation."""

from __future__ import annotations

from flowsmith.generator.connections import (
    DATAVERSE_CONNECTION,
    OFFICE365_CONNECTION,
    SHAREPOINT_CONNECTION,
    UIFLOW_CONNECTION,
    build_cloudflow_connection_references,
    build_workflow_connection_references,
    connection_for_module,
    logical_name,
    resolve_connection_names,
)

# ── connection_for_module ──────────────────────────────────────────────────


def test_workqueues_module_maps_to_dataverse() -> None:
    """WorkQueues stages need the Dataverse connector."""
    assert connection_for_module("WorkQueues") == DATAVERSE_CONNECTION


def test_outlook_module_maps_to_office365() -> None:
    """Outlook stages need the Office 365 connector."""
    assert connection_for_module("Outlook") == OFFICE365_CONNECTION


def test_sharepoint_module_maps_to_sharepoint() -> None:
    """SharePoint stages need the SharePoint connector."""
    assert connection_for_module("SharePoint") == SHAREPOINT_CONNECTION


def test_unknown_module_maps_to_none() -> None:
    """Modules with no cloud connector map to None."""
    assert connection_for_module("System") is None


def test_empty_module_maps_to_none() -> None:
    """Empty/None modules map to None rather than raising."""
    assert connection_for_module("") is None
    assert connection_for_module(None) is None


# ── resolve_connection_names ───────────────────────────────────────────────


def test_resolve_deduplicates_and_preserves_order() -> None:
    """Duplicate modules yield one entry, in first-seen order."""
    names = resolve_connection_names(["WorkQueues", "Outlook", "WorkQueues"])
    assert names == [DATAVERSE_CONNECTION, OFFICE365_CONNECTION]


def test_resolve_puts_always_entries_first() -> None:
    """`always` connections are emitted ahead of module-derived ones."""
    names = resolve_connection_names(["WorkQueues"], always=[UIFLOW_CONNECTION])
    assert names[0] == UIFLOW_CONNECTION
    assert DATAVERSE_CONNECTION in names


def test_resolve_ignores_unknown_modules() -> None:
    """Modules without a connector contribute nothing."""
    assert resolve_connection_names(["System", "Calculation"]) == []


# ── rendering ──────────────────────────────────────────────────────────────


def test_logical_name_is_deterministic() -> None:
    """The same connection always yields the same logical name."""
    first = logical_name(OFFICE365_CONNECTION, "cr3ac")
    second = logical_name(OFFICE365_CONNECTION, "cr3ac")
    assert first == second
    assert first.startswith("cr3ac_sharedoffice365_")


def test_cloudflow_references_shape() -> None:
    """Cloud Flow references are a mapping keyed by connection name."""
    refs = build_cloudflow_connection_references([UIFLOW_CONNECTION, OFFICE365_CONNECTION], "cr3ac")
    assert set(refs) == {UIFLOW_CONNECTION, OFFICE365_CONNECTION}
    assert refs[UIFLOW_CONNECTION]["runtimeSource"] == "invoker"
    assert refs[OFFICE365_CONNECTION]["runtimeSource"] == "embedded"
    assert refs[OFFICE365_CONNECTION]["api"] == {"name": "shared_office365"}
    assert refs[OFFICE365_CONNECTION]["connection"][
        "connectionReferenceLogicalName"
    ] == logical_name(OFFICE365_CONNECTION, "cr3ac")


def test_workflow_references_shape() -> None:
    """customizations.xml references are an array of richer descriptors."""
    refs = build_workflow_connection_references([DATAVERSE_CONNECTION], "cr3ac")
    assert len(refs) == 1
    entry = refs[0]
    assert entry["api"]["name"].startswith("/providers/Microsoft.PowerApps/apis/")
    assert entry["connectionReferenceLogicalName"] == logical_name(DATAVERSE_CONNECTION, "cr3ac")
    assert entry["isEmbedded"] is True
    assert entry["isDisabled"] is False


def test_empty_input_renders_empty_containers() -> None:
    """No connections produce an empty mapping and an empty array."""
    assert build_cloudflow_connection_references([], "cr3ac") == {}
    assert build_workflow_connection_references([], "cr3ac") == []
