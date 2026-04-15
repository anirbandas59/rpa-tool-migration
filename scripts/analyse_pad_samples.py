"""One-off script: analyse Power Automate Desktop sample package.

Inspects all artefact types present in samples/pad/:
  - ManifestFile JSON     → PAD module references + engine version
  - ConnectorDefinition JSON → Cloud connector IDs and operations
  - Cloud Flow Workflow JSON → Cloud Flow action types and structure
  - ControlRepository JSON   → UI element count and automation protocol
  - desktopflowbinary XML    → Binary type registry
  - solution.xml             → Solution component summary
  - customizations.xml        → Desktop flow Robin scripts (inputs, outputs, subflows, actions)

Robin scripts are embedded in customizations.xml <Definition> elements.
PAD module usage is derived from both ManifestFile references and Robin
action calls. Cloud Flow actions come from Workflows/*.json definitions.

Outputs:
  - Rich terminal report
  - docs/pad_action_inventory.md

Run with:
  uv run python scripts/analyse_pad_samples.py
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

from lxml import etree
from rich.console import Console
from rich.table import Table

SAMPLES_DIR = Path("samples/pad")
DOCS_DIR = Path("docs")
OUTPUT_MD = DOCS_DIR / "pad_action_inventory.md"

console = Console()


# ---------------------------------------------------------------------------
# Parsers for each artefact type
# ---------------------------------------------------------------------------


def parse_manifest(path: Path) -> dict:
    """Extract module references and engine version from a ManifestFile JSON.

    Args:
        path: Path to a ManifestFile_*.json file.

    Returns:
        Dict with 'modules' (list[str]) and 'engine_version' (str).
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    modules = [m.get("Name", "") for m in data.get("ModuleReferences", [])]
    ev = data.get("CreatedEngineVersion", {})
    engine_ver = f"{ev.get('Major', 0)}.{ev.get('Minor', 0)}.{ev.get('Build', 0)}"
    return {"modules": [m for m in modules if m], "engine_version": engine_ver, "file": str(path)}


def parse_connector_definition(path: Path) -> dict:
    """Extract connector ID and available operations from a ConnectorDefinition JSON.

    Args:
        path: Path to a ConnectorDefinition_*.json file.

    Returns:
        Dict with 'connector_id' (str) and 'operations' (list[str]).
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    connector_id = data.get("ConnectorId", "")
    swagger = data.get("Definition", {}).get("Properties", {}).get("Swagger", {})
    paths = swagger.get("paths", {})
    operations: list[str] = []
    for _path_key, methods in paths.items():
        for _method, op in methods.items():
            op_id = op.get("operationId", "")
            summary = op.get("summary", "")
            if op_id:
                operations.append(f"{op_id} — {summary}")
    return {"connector_id": connector_id, "operations": operations, "file": str(path)}


def _extract_cloud_flow_actions(actions_dict: dict, depth: int = 0) -> list[dict]:
    """Recursively walk Cloud Flow actions dict.

    Args:
        actions_dict: The 'actions' dict from a Cloud Flow definition.
        depth: Current nesting depth.

    Returns:
        List of dicts with 'name', 'type', 'depth'.
    """
    results: list[dict] = []
    for name, action in actions_dict.items():
        atype = action.get("type", "")
        results.append({"name": name, "type": atype, "depth": depth})
        # Descend into child action blocks
        for branch_key in ("actions", "else"):
            branch = action.get(branch_key, {})
            if isinstance(branch, dict) and branch:
                results.extend(_extract_cloud_flow_actions(branch, depth + 1))
        cases = action.get("cases", {})
        if isinstance(cases, dict):
            for case_val in cases.values():
                sub = case_val.get("actions", {})
                if sub:
                    results.extend(_extract_cloud_flow_actions(sub, depth + 1))
    return results


def parse_cloud_flow(path: Path) -> dict:
    """Extract action inventory from a Cloud Flow workflow JSON.

    Args:
        path: Path to a workflow .json file.

    Returns:
        Dict with 'flow_name', 'actions' (list[dict]), 'triggers' (list[str]),
        'connections' (list[str]).
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    props = data.get("properties", {})
    defn = props.get("definition", {})
    flow_name = path.stem
    actions = _extract_cloud_flow_actions(defn.get("actions", {}))
    triggers = list(defn.get("triggers", {}).keys())
    connections = list(props.get("connectionReferences", {}).keys())
    return {
        "flow_name": flow_name,
        "actions": actions,
        "triggers": triggers,
        "connections": connections,
        "file": str(path),
    }


def parse_control_repository(path: Path) -> dict:
    """Count UI elements and protocols in a ControlRepository JSON.

    Args:
        path: Path to a ControlRepository_*.json file.

    Returns:
        Dict with 'element_count' (int), 'protocols' (set[str]), 'screen_count' (int).
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    screens = data.get("Screens", [])
    protocols: set[str] = set()
    element_count = 0
    for screen in screens:
        for ctrl in screen.get("Controls", []):
            element_count += 1
            proto = ctrl.get("AutomationProtocol", "")
            if proto:
                protocols.add(proto)
            # Nested controls
            for nested in ctrl.get("Controls", []):
                element_count += 1
                p2 = nested.get("AutomationProtocol", "")
                if p2:
                    protocols.add(p2)
    return {
        "element_count": element_count,
        "protocols": protocols,
        "screen_count": len(screens),
        "file": str(path),
    }


def parse_desktop_flow_binary(path: Path) -> dict:
    """Extract type and process reference from desktopflowbinary.xml.

    Args:
        path: Path to a desktopflowbinary.xml file.

    Returns:
        Dict with 'binary_type' (str), 'data_file' (str), 'workflow_id' (str).
    """
    tree = etree.parse(str(path))
    root = tree.getroot()
    binary_type = root.findtext("type") or ""
    data_file = root.findtext("data") or ""
    workflow_id = root.findtext("process/workflowid") or ""
    return {
        "binary_type": binary_type,
        "data_file": data_file.strip(),
        "workflow_id": workflow_id.strip(),
        "file": str(path),
    }


def parse_solution_xml(path: Path) -> dict:
    """Extract solution component summary from solution.xml.

    Args:
        path: Path to solution.xml.

    Returns:
        Dict with 'unique_types' (list[str]) and 'component_count' (int).
    """
    tree = etree.parse(str(path))
    root = tree.getroot()
    type_counter: Counter[str] = Counter()
    for elem in root.iter():
        t = elem.get("type", "")
        if t:
            type_counter[t] += 1
    return {
        "unique_types": sorted(type_counter.keys()),
        "component_counts": dict(type_counter),
        "file": str(path),
    }


# ---------------------------------------------------------------------------
# Robin script parsers
# ---------------------------------------------------------------------------

_ACTION_RE = re.compile(r"^(?:DISABLE\s+)?([A-Z][A-Za-z]+\.[A-Z][A-Za-z]+(?:\.[A-Z][A-Za-z]+)?)\b")
_FUNCTION_RE = re.compile(r"^FUNCTION\s+(?:'([^']+)'|(\w+))\s+(?:GLOBAL|LOCAL)", re.MULTILINE)
_INPUT_RE = re.compile(
    r"^@INPUT\s+(\w+)\s*:.*?'Type'\s*:\s*'([^']+)'.*?'IsOptional'\s*:\s*(True|False)",
    re.MULTILINE | re.DOTALL,
)
_OUTPUT_RE = re.compile(r"^@OUTPUT\s+(\w+)\s*:.*?'Type'\s*:\s*'([^']+)'", re.MULTILINE | re.DOTALL)
_SENSITIVE_RE = re.compile(r"^@SENSITIVE:\s*\[([^\]]*)\]", re.MULTILINE)
_RUN_FLOW_RE = re.compile(r"External\.RunFlow\s+FlowId:\s*'([0-9a-f\-]+)'")
_CONNECTOR_RE = re.compile(
    r"External\.InvokeCloudConnector\s+.*?ConnectorId:\s*'([^']+)'\s+OperationId:\s*'([^']+)'"
)

_SKIP_PREFIXES = (
    "#",
    "/#",
    "@@",
    "@INPUT",
    "@OUTPUT",
    "@SENSITIVE",
    "IF",
    "ELSE",
    "END",
    "LOOP",
    "BLOCK",
    "ON",
    "SET",
    "CALL",
    "WAIT",
    "GOTO",
    "LABEL",
    "THROW",
    "ERROR",
    "EXIT",
    "REPEAT",
    "FUNCTION",
    "IMPORT",
    "DISABLE IF",
)


def _parse_robin_metadata(script: str) -> tuple[list[dict], list[dict], list[str]]:
    """Extract @INPUT, @OUTPUT and @SENSITIVE declarations from a Robin script.

    Args:
        script: Raw Robin script text.

    Returns:
        Tuple of (inputs, outputs, sensitive_vars).
    """
    inputs: list[dict] = []
    outputs: list[dict] = []
    sensitive_vars: list[str] = []

    for m in _INPUT_RE.finditer(script):
        inputs.append(
            {
                "name": m.group(1),
                "type": m.group(2),
                "is_optional": m.group(3) == "True",
            }
        )
    for m in _OUTPUT_RE.finditer(script):
        outputs.append({"name": m.group(1), "type": m.group(2)})
    for m in _SENSITIVE_RE.finditer(script):
        raw = m.group(1).strip()
        if raw:
            sensitive_vars = [v.strip() for v in raw.split(",") if v.strip()]

    return inputs, outputs, sensitive_vars


def _parse_robin_subflows(script: str) -> list[str]:
    """Extract FUNCTION declaration names from a Robin script.

    Args:
        script: Raw Robin script text.

    Returns:
        List of subflow (function) names.
    """
    names: list[str] = []
    for m in _FUNCTION_RE.finditer(script):
        name = m.group(1) or m.group(2)
        if name:
            names.append(name)
    return names


def _parse_robin_actions(script: str) -> list[dict]:
    """Extract PAD module action calls from a Robin script.

    A line is treated as a PAD action call if, after stripping leading
    whitespace and an optional DISABLE prefix, it starts with two or three
    dot-separated UpperCamelCase identifiers.

    Args:
        script: Raw Robin script text.

    Returns:
        List of dicts with keys 'module', 'full_action', 'line_no'.
    """
    actions: list[dict] = []
    for line_no, raw_line in enumerate(script.splitlines(), start=1):
        line = raw_line.lstrip()
        # Quick pre-filter: skip lines that start with known non-action keywords
        skip = False
        for prefix in _SKIP_PREFIXES:
            if line.startswith(prefix):
                skip = True
                break
        if skip:
            continue
        m = _ACTION_RE.match(line)
        if m:
            full_action = m.group(1)
            module = full_action.split(".")[0]
            actions.append({"module": module, "full_action": full_action, "line_no": line_no})
    return actions


def _parse_robin_external_calls(
    script: str,
) -> tuple[list[str], list[dict]]:
    """Extract External.RunFlow and External.InvokeCloudConnector calls.

    Args:
        script: Raw Robin script text.

    Returns:
        Tuple of (child_flow_ids, connector_calls).
        child_flow_ids: list of target FlowId GUIDs.
        connector_calls: list of {connector_id, operation_id} dicts.
    """
    child_flow_ids: list[str] = []
    connector_calls: list[dict] = []
    for m in _RUN_FLOW_RE.finditer(script):
        child_flow_ids.append(m.group(1))
    for m in _CONNECTOR_RE.finditer(script):
        connector_calls.append(
            {
                "connector_id": m.group(1),
                "operation_id": m.group(2),
            }
        )
    return child_flow_ids, connector_calls


def parse_robin_script(script: str, flow_name: str, flow_id: str) -> dict:
    """Parse a Robin desktop flow script and extract structured metadata.

    Args:
        script: Raw Robin script text.
        flow_name: Display name of the flow.
        flow_id: Workflow GUID (without braces).

    Returns:
        Dict with keys: flow_name, flow_id, inputs, outputs, sensitive_vars,
        subflows, actions, child_flow_calls, connector_calls.
    """
    inputs, outputs, sensitive_vars = _parse_robin_metadata(script)
    subflows = _parse_robin_subflows(script)
    actions = _parse_robin_actions(script)
    child_flow_calls, connector_calls = _parse_robin_external_calls(script)
    return {
        "flow_name": flow_name,
        "flow_id": flow_id,
        "inputs": inputs,
        "outputs": outputs,
        "sensitive_vars": sensitive_vars,
        "subflows": subflows,
        "actions": actions,
        "child_flow_calls": child_flow_calls,
        "connector_calls": connector_calls,
    }


def parse_customizations_xml(path: Path) -> list[dict]:
    """Extract desktop flow Robin scripts from customizations.xml.

    Each <Workflow> element whose <Definition> is non-empty contains a
    JSON-encoded Robin script string.  Workflows with an empty <Definition>
    (cloud flows whose logic lives in the Workflows/*.json file) are skipped.

    Args:
        path: Path to customizations.xml.

    Returns:
        List of parsed desktop flow dicts (from parse_robin_script).
    """
    tree = etree.parse(str(path))
    root = tree.getroot()
    results: list[dict] = []
    for wf in root.iter("Workflow"):
        flow_name = wf.get("Name", "")
        flow_id = wf.get("WorkflowId", "").strip("{}")
        defn_el = wf.find("Definition")
        if defn_el is None or not defn_el.text:
            continue
        raw = defn_el.text.strip()
        try:
            script: str = json.loads(raw) if raw.startswith('"') else raw
        except json.JSONDecodeError:
            script = raw
        if not script:
            continue
        results.append(parse_robin_script(script, flow_name, flow_id))
    return results


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def analyse_all(samples_dir: Path) -> dict:
    """Walk samples_dir and dispatch each file to the correct parser.

    Args:
        samples_dir: Root directory to walk.

    Returns:
        Aggregated dict with all parsed results by category.
    """
    manifests: list[dict] = []
    connectors: list[dict] = []
    cloud_flows: list[dict] = []
    control_repos: list[dict] = []
    df_binaries: list[dict] = []
    desktop_flows: list[dict] = []
    solution: dict | None = None

    for path in sorted(samples_dir.rglob("*")):
        if not path.is_file():
            continue
        name = path.name
        suffix = path.suffix.lower()

        if suffix == ".json":
            if name.startswith("ManifestFile"):
                manifests.append(parse_manifest(path))
            elif name.startswith("ConnectorDefinition"):
                connectors.append(parse_connector_definition(path))
            elif name.startswith("ControlRepository"):
                control_repos.append(parse_control_repository(path))
            elif name.startswith("Shell_PP") or (
                path.parent.name == "Workflows" and suffix == ".json"
            ):
                parsed = parse_cloud_flow(path)
                if parsed["actions"] or parsed["triggers"]:
                    cloud_flows.append(parsed)
            # DependenciesFile and ImageRepository are skipped (no useful action data)

        elif suffix == ".xml":
            if name == "desktopflowbinary.xml":
                df_binaries.append(parse_desktop_flow_binary(path))
            elif name == "solution.xml":
                solution = parse_solution_xml(path)
            elif name == "customizations.xml":
                desktop_flows.extend(parse_customizations_xml(path))

    return {
        "manifests": manifests,
        "connectors": connectors,
        "cloud_flows": cloud_flows,
        "control_repos": control_repos,
        "df_binaries": df_binaries,
        "desktop_flows": desktop_flows,
        "solution": solution,
    }


def aggregate_pad_modules(manifests: list[dict]) -> dict[str, int]:
    """Count how many manifests reference each PAD module.

    Args:
        manifests: List of parsed manifest dicts.

    Returns:
        Dict mapping module name → count of manifests referencing it.
    """
    counter: Counter[str] = Counter()
    for m in manifests:
        for mod in m["modules"]:
            counter[mod] += 1
    return dict(counter)


def aggregate_cloud_flow_actions(cloud_flows: list[dict]) -> dict[str, int]:
    """Count occurrences of each Cloud Flow action type across all flows.

    Args:
        cloud_flows: List of parsed cloud flow dicts.

    Returns:
        Dict mapping action type → total count.
    """
    counter: Counter[str] = Counter()
    for cf in cloud_flows:
        for action in cf["actions"]:
            atype = action["type"] or "(untyped)"
            counter[atype] += 1
    return dict(counter)


def aggregate_robin_actions(desktop_flows: list[dict]) -> dict[str, int]:
    """Count Robin action calls by PAD module across all desktop flows.

    Args:
        desktop_flows: List of parsed desktop flow dicts.

    Returns:
        Dict mapping module name to total action call count.
    """
    counter: Counter[str] = Counter()
    for df in desktop_flows:
        for action in df["actions"]:
            counter[action["module"]] += 1
    return dict(counter)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def print_rich_report(data: dict) -> None:
    """Print structured Rich terminal report.

    Args:
        data: Aggregated analysis dict from analyse_all().
    """
    console.rule("[bold cyan]Power Automate Desktop - Sample Inventory[/bold cyan]")

    # PAD modules from manifests
    if data["manifests"]:
        console.print()
        pad_modules = aggregate_pad_modules(data["manifests"])
        t = Table(
            title=f"PAD Module References ({len(pad_modules)} unique modules)",
            header_style="bold magenta",
        )
        t.add_column("Module Name", style="cyan")
        t.add_column("Manifest count", justify="right")
        for mod, cnt in sorted(pad_modules.items()):
            t.add_row(mod, str(cnt))
        console.print(t)

    # Desktop flows from customizations.xml
    if data.get("desktop_flows"):
        console.print()
        t_df = Table(
            title=f"Desktop Flows ({len(data['desktop_flows'])} flows)",
            header_style="bold magenta",
        )
        t_df.add_column("Flow Name", style="green")
        t_df.add_column("Subflows", justify="right")
        t_df.add_column("Actions", justify="right")
        t_df.add_column("Inputs", justify="right")
        t_df.add_column("Outputs", justify="right")
        for df in data["desktop_flows"]:
            t_df.add_row(
                df["flow_name"],
                str(len(df["subflows"])),
                str(len(df["actions"])),
                str(len(df["inputs"])),
                str(len(df["outputs"])),
            )
        console.print(t_df)

        console.print()
        robin_modules = aggregate_robin_actions(data["desktop_flows"])
        t_rm = Table(
            title=f"Robin Action Module Usage ({len(robin_modules)} modules)",
            header_style="bold magenta",
        )
        t_rm.add_column("Module", style="cyan")
        t_rm.add_column("Action call count", justify="right")
        for mod, cnt in sorted(robin_modules.items()):
            t_rm.add_row(mod, str(cnt))
        console.print(t_rm)

    # Cloud Flow action types
    if data["cloud_flows"]:
        console.print()
        cf_types = aggregate_cloud_flow_actions(data["cloud_flows"])
        t2 = Table(
            title=f"Cloud Flow Action Types ({len(cf_types)} unique)",
            header_style="bold magenta",
        )
        t2.add_column("Action Type", style="yellow")
        t2.add_column("Count", justify="right")
        for atype, cnt in sorted(cf_types.items()):
            t2.add_row(atype, str(cnt))
        console.print(t2)

        console.print()
        t3 = Table(
            title=f"Cloud Flows ({len(data['cloud_flows'])} flows)",
            header_style="bold magenta",
        )
        t3.add_column("Flow Name", style="green")
        t3.add_column("Actions", justify="right")
        t3.add_column("Triggers")
        t3.add_column("Connections")
        for cf in data["cloud_flows"]:
            t3.add_row(
                cf["flow_name"],
                str(len(cf["actions"])),
                ", ".join(cf["triggers"]) or "—",
                str(len(cf["connections"])),
            )
        console.print(t3)

    # Connectors
    if data["connectors"]:
        console.print()
        t4 = Table(
            title=f"Connectors ({len(data['connectors'])} definitions)",
            header_style="bold magenta",
        )
        t4.add_column("Connector ID", style="blue")
        t4.add_column("Operations", justify="right")
        for c in data["connectors"]:
            t4.add_row(c["connector_id"], str(len(c["operations"])))
        console.print(t4)

    # Control repos
    if data["control_repos"]:
        console.print()
        total_elems = sum(c["element_count"] for c in data["control_repos"])
        all_protos: set[str] = set()
        for c in data["control_repos"]:
            all_protos |= c["protocols"]
        console.print(
            f"[bold]Control Repositories:[/bold] {len(data['control_repos'])} files, "
            f"{total_elems} total UI elements, protocols: {', '.join(sorted(all_protos)) or 'none'}"
        )

    # Desktop flow binaries
    if data["df_binaries"]:
        console.print()
        binary_types = Counter(b["binary_type"] for b in data["df_binaries"])
        t5 = Table(title="Desktop Flow Binary Types", header_style="bold magenta")
        t5.add_column("Type", style="cyan")
        t5.add_column("Count", justify="right")
        for btype, cnt in sorted(binary_types.items()):
            t5.add_row(btype or "(none)", str(cnt))
        console.print(t5)

    # Solution
    if data["solution"]:
        console.print()
        console.print("[bold]Solution components:[/bold]")
        for comp_type, cnt in sorted(data["solution"]["component_counts"].items()):
            console.print(f"  type={comp_type}: {cnt}")


def build_md_report(data: dict) -> str:
    """Render the PAD analysis as a Markdown string.

    Args:
        data: Aggregated analysis dict from analyse_all().

    Returns:
        Markdown string ready to write to disk.
    """
    lines: list[str] = []
    lines.append("# Power Automate Desktop — Sample Action Inventory\n")
    lines.append("_Generated by `scripts/analyse_pad_samples.py`_\n")
    lines.append(
        "> Note: Robin scripts are embedded in `customizations.xml` `<Definition>` elements.\n"
        "> PAD module usage is derived from both ManifestFile references and Robin action calls.\n"
        "> Cloud Flow actions are extracted from `Workflows/*.json` definitions.\n"
    )

    # Desktop flows from customizations.xml
    if data.get("desktop_flows"):
        lines.append("## Desktop Flows\n")
        lines.append(
            f"Total desktop flows parsed from `customizations.xml`: **{len(data['desktop_flows'])}**\n"
        )
        for df in data["desktop_flows"]:
            lines.append(f"### `{df['flow_name']}`\n")
            lines.append(f"- Flow ID: `{df['flow_id']}`")
            lines.append(f"- Subflows: {len(df['subflows'])}")
            lines.append(f"- Action calls: {len(df['actions'])}")
            if df["sensitive_vars"]:
                lines.append(
                    f"- Sensitive variables: {', '.join(f'`{v}`' for v in df['sensitive_vars'])}"
                )
            if df["inputs"]:
                lines.append("")
                lines.append("**Inputs:**")
                lines.append("")
                lines.append("| Name | Type | Optional |")
                lines.append("| ---- | ---- | -------- |")
                for inp in df["inputs"]:
                    lines.append(f"| `{inp['name']}` | `{inp['type']}` | {inp['is_optional']} |")
            if df["outputs"]:
                lines.append("")
                lines.append("**Outputs:**")
                lines.append("")
                lines.append("| Name | Type |")
                lines.append("| ---- | ---- |")
                for out in df["outputs"]:
                    lines.append(f"| `{out['name']}` | `{out['type']}` |")
            if df["subflows"]:
                lines.append("")
                lines.append("**Subflows:**")
                lines.append("")
                for sf in df["subflows"]:
                    lines.append(f"- `{sf}`")
            if df["child_flow_calls"]:
                lines.append("")
                lines.append("**Child flow calls (External.RunFlow):**")
                lines.append("")
                for fid in set(df["child_flow_calls"]):
                    lines.append(f"- `{fid}`")
            if df["connector_calls"]:
                lines.append("")
                lines.append("**Connector calls (External.InvokeCloudConnector):**")
                lines.append("")
                lines.append("| ConnectorId | OperationId |")
                lines.append("| ----------- | ----------- |")
                for cc in df["connector_calls"]:
                    lines.append(f"| `{cc['connector_id']}` | `{cc['operation_id']}` |")
            lines.append("")

        # Robin action module usage
        robin_modules = aggregate_robin_actions(data["desktop_flows"])
        lines.append("## Robin Action Module Usage\n")
        lines.append(f"Total unique modules called in Robin scripts: **{len(robin_modules)}**\n")
        lines.append("| Module | Action call count |")
        lines.append("| ------ | ----------------- |")
        for mod, cnt in sorted(robin_modules.items()):
            lines.append(f"| `{mod}` | {cnt} |")
        lines.append("")

    # PAD modules
    pad_modules = aggregate_pad_modules(data["manifests"])
    lines.append("## PAD Module References\n")
    lines.append(f"Total unique PAD modules referenced: **{len(pad_modules)}**\n")
    lines.append("| Module | Manifest count |")
    lines.append("| ------ | -------------- |")
    for mod, cnt in sorted(pad_modules.items()):
        lines.append(f"| `{mod}` | {cnt} |")
    lines.append("")

    # Cloud Flow actions
    cf_types = aggregate_cloud_flow_actions(data["cloud_flows"])
    lines.append("## Cloud Flow Action Types\n")
    lines.append(f"Total unique Cloud Flow action types: **{len(cf_types)}**\n")
    lines.append("| Action Type | Count |")
    lines.append("| ----------- | ----- |")
    for atype, cnt in sorted(cf_types.items()):
        lines.append(f"| `{atype}` | {cnt} |")
    lines.append("")

    # Per-flow summary
    lines.append("## Cloud Flow Summaries\n")
    for cf in data["cloud_flows"]:
        lines.append(f"### `{cf['flow_name']}`\n")
        lines.append(f"- Actions: {len(cf['actions'])}")
        lines.append(f"- Triggers: {', '.join(cf['triggers']) or '—'}")
        lines.append(f"- Connection references: {len(cf['connections'])}")
        lines.append("")
        if cf["actions"]:
            lines.append("| Action name | Type | Depth |")
            lines.append("| ----------- | ---- | ----- |")
            for a in cf["actions"]:
                lines.append(f"| `{a['name']}` | `{a['type'] or '—'}` | {a['depth']} |")
        lines.append("")

    # Connectors
    lines.append("## Connector Definitions\n")
    for c in data["connectors"]:
        lines.append(f"### `{c['connector_id']}`\n")
        lines.append(f"- Operations available: {len(c['operations'])}")
        if c["operations"]:
            lines.append("")
            for op in c["operations"][:20]:
                lines.append(f"  - `{op}`")
            if len(c["operations"]) > 20:
                lines.append(f"  - _(+ {len(c['operations']) - 20} more)_")
        lines.append("")

    # Control repos
    lines.append("## Control Repositories\n")
    for cr in data["control_repos"]:
        proto_str = ", ".join(sorted(cr["protocols"])) or "—"
        lines.append(
            f"- `{Path(cr['file']).name}`: {cr['screen_count']} screens, "
            f"{cr['element_count']} elements, protocol(s): {proto_str}"
        )
    lines.append("")

    # Binary types
    lines.append("## Desktop Flow Binary Types\n")
    binary_types = Counter(b["binary_type"] for b in data["df_binaries"])
    lines.append("| Type | Count |")
    lines.append("| ---- | ----- |")
    for btype, cnt in sorted(binary_types.items()):
        lines.append(f"| `{btype or '(none)'}` | {cnt} |")
    lines.append("")

    # Mapping guidance
    lines.append("## Mapping guidance\n")
    lines.append("The following PAD modules are available for mapping Blue Prism stages:\n")
    module_guidance = {
        "System": "General system actions (run application, terminate process)",
        "Excel": "Excel file read/write — maps to BP MS Excel VBO",
        "File": "File copy/move/delete — maps to BP Utility - File Management",
        "Folder": "Folder operations",
        "Text": "String manipulation — maps to BP Utility - Strings",
        "Variables": "Set/get variable — maps to BP Calculation/Data stages",
        "Web": "Web browser automation — maps to BP Navigate/Read/Write stages",
        "UIAutomation": "Desktop UI automation — maps to BP Navigate/Read/Write stages",
        "SAP": "SAP GUI automation",
        "TerminalEmulation": "Mainframe terminal automation",
        "Database": "Database queries — maps to BP Data stage with SQL",
        "DateTime": "Date/time manipulation",
        "Cryptography": "Encryption — maps to BP Utility - General cryptographic actions",
        "WorkQueues": "Work queue operations — maps to BP queue management",
    }
    lines.append("| Module | Usage guidance |")
    lines.append("| ------ | -------------- |")
    for mod in sorted(pad_modules.keys()):
        guidance = module_guidance.get(mod, "— no guidance yet")
        lines.append(f"| `{mod}` | {guidance} |")
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    """Entry point: run analysis, print report, save Markdown."""
    console.print(f"[dim]Scanning {SAMPLES_DIR} ...[/dim]")
    data = analyse_all(SAMPLES_DIR)

    total_files = (
        len(data["manifests"])
        + len(data["connectors"])
        + len(data["cloud_flows"])
        + len(data["control_repos"])
        + len(data["df_binaries"])
        + len(data.get("desktop_flows", []))
        + (1 if data["solution"] else 0)
    )

    if total_files == 0:
        console.print(f"[red]No recognised PAD artefact files found in {SAMPLES_DIR}[/red]")
        sys.exit(1)

    print_rich_report(data)

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    md = build_md_report(data)
    OUTPUT_MD.write_text(md, encoding="utf-8")
    console.print(f"\n[green]OK[/green] Markdown report saved -> [bold]{OUTPUT_MD}[/bold]")


if __name__ == "__main__":
    main()
