"""Derive Power Platform connection references from annotated stage modules.

Two consumers need the same set of connections, in two different shapes:

  * `CloudFlowGenerator` — `properties.connectionReferences` in the Cloud Flow
    JSON, a **mapping** of connection name → runtimeSource/api descriptor.
  * `WorkflowBuilder` — the `<ConnectionReferences>` element in
    customizations.xml, a JSON **array** of richer descriptors.

`resolve_connection_names()` produces the shared, ordered set; the two
`build_*` functions render it into the respective shapes.

Logical names are derived deterministically (md5 of the connection name) so
that repeated runs over the same process produce byte-identical output.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

# Connection names as they appear in `connectionName` inside Cloud Flow actions.
UIFLOW_CONNECTION = "shared_uiflow"
OFFICE365_CONNECTION = "shared_office365-1"
DATAVERSE_CONNECTION = "shared_commondataserviceforapps"
SHAREPOINT_CONNECTION = "shared_sharepointonline"

# connection name → (api name, runtimeSource, display name)
_CONNECTION_SPECS: dict[str, tuple[str, str, str]] = {
    UIFLOW_CONNECTION: ("shared_uiflow", "invoker", "Desktop flows"),
    OFFICE365_CONNECTION: ("shared_office365", "embedded", "Office 365 Outlook"),
    DATAVERSE_CONNECTION: (
        "shared_commondataserviceforapps",
        "embedded",
        "Microsoft Dataverse",
    ),
    SHAREPOINT_CONNECTION: ("shared_sharepointonline", "embedded", "SharePoint"),
}

# Substrings of an annotation's `target_module` that imply a connection.
# Checked case-insensitively, first match wins.
_MODULE_MARKERS: tuple[tuple[str, str], ...] = (
    ("workqueue", DATAVERSE_CONNECTION),
    ("sharepoint", SHAREPOINT_CONNECTION),
    ("external", SHAREPOINT_CONNECTION),
    ("outlook", OFFICE365_CONNECTION),
    ("office365", OFFICE365_CONNECTION),
    ("mail", OFFICE365_CONNECTION),
    ("email", OFFICE365_CONNECTION),
)


def connection_for_module(module: str | None) -> str | None:
    """Map an annotation `target_module` to a connection name.

    Args:
        module: The `PAAnnotation.target_module` value, may be None/empty.

    Returns:
        The connection name, or None when the module needs no cloud connector.
    """
    if not module:
        return None

    lowered = module.lower()
    for marker, connection in _MODULE_MARKERS:
        if marker in lowered:
            return connection
    return None


def resolve_connection_names(
    modules: Iterable[str | None],
    always: Iterable[str] = (),
) -> list[str]:
    """Resolve the ordered, deduplicated set of connections a flow needs.

    Args:
        modules: `target_module` values of every annotated stage in scope.
        always: Connection names to include regardless of the modules seen
            (e.g. `shared_uiflow` when the flow invokes a desktop flow).

    Returns:
        Connection names in first-seen order, `always` entries first.
    """
    names: list[str] = []
    for name in [*always, *(connection_for_module(m) for m in modules)]:
        if name and name in _CONNECTION_SPECS and name not in names:
            names.append(name)
    return names


def logical_name(connection_name: str, publisher_prefix: str) -> str:
    """Build a deterministic connection reference logical name.

    Args:
        connection_name: A connection name (e.g. "shared_office365-1").
        publisher_prefix: Publisher customisation prefix (e.g. "cr3ac").

    Returns:
        A name of the form ``<prefix>_<apiname>_<5 hex chars>``.
    """
    api_name = _CONNECTION_SPECS[connection_name][0]
    flat = api_name.replace("_", "").replace("-", "")
    digest = hashlib.md5(connection_name.encode("utf-8")).hexdigest()[:5]
    return f"{publisher_prefix}_{flat}_{digest}"


def build_cloudflow_connection_references(
    connection_names: Iterable[str],
    publisher_prefix: str,
) -> dict[str, dict[str, object]]:
    """Render connections as the Cloud Flow `connectionReferences` mapping.

    Args:
        connection_names: Connection names from `resolve_connection_names`.
        publisher_prefix: Publisher customisation prefix.

    Returns:
        Mapping of connection name → descriptor dict, matching the shape used
        by the reference CF JSON.
    """
    references: dict[str, dict[str, object]] = {}
    for name in connection_names:
        api_name, runtime_source, _display = _CONNECTION_SPECS[name]
        references[name] = {
            "runtimeSource": runtime_source,
            "connection": {"connectionReferenceLogicalName": logical_name(name, publisher_prefix)},
            "api": {"name": api_name},
        }
    return references


def build_workflow_connection_references(
    connection_names: Iterable[str],
    publisher_prefix: str,
) -> list[dict[str, object]]:
    """Render connections as the customizations.xml `<ConnectionReferences>` array.

    Args:
        connection_names: Connection names from `resolve_connection_names`.
        publisher_prefix: Publisher customisation prefix.

    Returns:
        List of connection reference descriptors.
    """
    references: list[dict[str, object]] = []
    for name in connection_names:
        api_name, runtime_source, display = _CONNECTION_SPECS[name]
        references.append(
            {
                "api": {"name": f"/providers/Microsoft.PowerApps/apis/{api_name}"},
                "displayName": display,
                "isDisabled": False,
                "connectionReferenceLogicalName": logical_name(name, publisher_prefix),
                "connectionDisplayName": None,
                "ownerId": None,
                "isEmbedded": runtime_source == "embedded",
            }
        )
    return references
