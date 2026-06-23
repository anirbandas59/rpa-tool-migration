"""
bp_release_parser.py — Blue Prism .bprelease diagnostic parser
Parses a .bprelease file and extracts all processes, objects,
and environment variables using bp_parser.parse_element() for each artefact.

Usage:
    python bp_release_parser.py <file.bprelease>

Returns a structured dict via parse_release(filepath).
"""

import os
import sys
import xml.etree.ElementTree as ET
from typing import Any

sys.path.insert(0, os.path.dirname(__file__))
from bp_parser_v2 import NS as BP_NS
from bp_parser_v2 import parse_element

# ---------------------------------------------------------------------------
# Namespace constants
# ---------------------------------------------------------------------------

NS_RELEASE = "http://www.blueprism.co.uk/product/release"
NS_PROCESS = BP_NS  # "http://www.blueprism.co.uk/product/process"
NS_ENV_VAR = "http://www.blueprism.co.uk/product/environment-variable"
NS_PROC_GRP = "http://www.blueprism.co.uk/product/process-group"
NS_OBJ_GRP = "http://www.blueprism.co.uk/product/object-group"

BPR = f"{{{NS_RELEASE}}}"
BP = f"{{{NS_PROCESS}}}"
ENV = f"{{{NS_ENV_VAR}}}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bpr_txt(el: ET.Element, tag: str) -> str:
    """Return stripped text of a direct bpr: child, or empty string."""
    child = el.find(f"{BPR}{tag}")
    return child.text.strip() if child is not None and child.text else ""


def _parse_env_var(el: ET.Element) -> dict[str, str]:
    """Parse a single <environment-variable> element."""
    desc_el = el.find(f"{ENV}description")
    # Some BP versions omit the namespace on description
    if desc_el is None:
        desc_el = el.find("description")
    return {
        "id": el.attrib.get("id", ""),
        "name": el.attrib.get("name", ""),
        "type": el.attrib.get("type", "text"),
        "value": el.attrib.get("value", ""),
        "description": desc_el.text.strip() if desc_el is not None and desc_el.text else "",
    }


def _parse_group(el: ET.Element) -> dict[str, Any]:
    """Parse a process-group or object-group element."""
    tag = el.tag.split("}")[-1]
    ns = el.tag.split("}")[0][1:] if "{" in el.tag else ""
    members = el.find(f"{{{ns}}}members") if ns else el.find("members")
    member_ids = []
    if members is not None:
        for m in members:
            mid = m.attrib.get("id", "")
            if mid:
                member_ids.append(mid)
    return {
        "id": el.attrib.get("id", ""),
        "name": el.attrib.get("name", ""),
        "type": tag,  # "process-group" or "object-group"
        "is_default": el.attrib.get("isDefaultGroup", "False").lower() == "true",
        "member_ids": member_ids,
    }


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------


def parse_release(filepath: str) -> dict[str, Any]:
    """
    Parse a Blue Prism .bprelease file.

    Returns:
        {
          release_meta: {
            name, release_notes, created, package_id,
            package_name, created_by, declared_count
          },
          processes: [ bp_parser.parse_element() result, ... ],
          objects:   [ bp_parser.parse_element() result, ... ],
          environment_variables: [
            { id, name, type, value, description }, ...
          ],
          groups: [
            { id, name, type, is_default, member_ids }, ...
          ],
          errors: [
            { item_type, name, release_id, error }, ...
          ],
          stats: {
            declared_count,   # from count="" attribute
            process_count,
            object_count,
            env_var_count,
            group_count,
            skipped_groups,
            error_count,
            total_stages,
            total_edges,
            total_parsed_stages,
            total_skipped_stages,
          }
        }
    """
    tree = ET.parse(filepath)
    root = tree.getroot()

    # Validate root element
    if "release" not in root.tag:
        raise ValueError(
            f"Expected a <release> root element, got <{root.tag.split('}')[-1]}>. "
            f"This does not appear to be a .bprelease file."
        )

    # ---- Release metadata ----
    release_meta = {
        "name": _bpr_txt(root, "name"),
        "release_notes": _bpr_txt(root, "release-notes"),
        "created": _bpr_txt(root, "created"),
        "package_id": _bpr_txt(root, "package-id"),
        "package_name": _bpr_txt(root, "package-name"),
        "created_by": _bpr_txt(root, "user-created-by"),
        "declared_count": 0,
    }

    contents = root.find(f"{BPR}contents")
    if contents is None:
        raise ValueError("No <bpr:contents> element found in release file.")

    release_meta["declared_count"] = int(contents.attrib.get("count", 0))

    # ---- Iterate contents ----
    processes: list[dict] = []
    objects: list[dict] = []
    env_vars: list[dict] = []
    groups: list[dict] = []
    errors: list[dict] = []

    for child in contents:
        tag = child.tag.split("}")[-1]
        name = child.attrib.get("name", "?")
        release_id = child.attrib.get("id", "")

        if tag == "process":
            try:
                result = parse_element(child, release_id=release_id)
                # Tag published status from release wrapper (not inner process)
                raw_pub = child.attrib.get("published", "false")
                result["meta"]["published"] = raw_pub.lower() == "true"
                processes.append(result)
            except Exception as exc:
                errors.append(
                    {
                        "item_type": "process",
                        "name": name,
                        "release_id": release_id,
                        "error": str(exc),
                    }
                )

        elif tag == "object":
            try:
                result = parse_element(child, release_id=release_id)
                result["meta"]["published"] = None  # objects don't have top-level published
                objects.append(result)
            except Exception as exc:
                errors.append(
                    {
                        "item_type": "object",
                        "name": name,
                        "release_id": release_id,
                        "error": str(exc),
                    }
                )

        elif tag == "environment-variable":
            env_vars.append(_parse_env_var(child))

        elif tag in ("process-group", "object-group"):
            groups.append(_parse_group(child))

        # All other tags are silently skipped

    # ---- Build cross-reference: process/object id → group names ----
    # Attach group membership to each artefact's meta
    id_to_groups: dict[str, list[str]] = {}
    for g in groups:
        for mid in g["member_ids"]:
            id_to_groups.setdefault(mid, []).append(g["name"])

    for result in processes + objects:
        rid = result.get("release_id", "")
        result["meta"]["groups"] = id_to_groups.get(rid, [])

    # ---- Stats ----
    total_stages = sum(r["stats"]["total_raw"] for r in processes + objects)
    total_parsed = sum(r["stats"]["parsed"] for r in processes + objects)
    total_skipped = sum(r["stats"]["skipped"] for r in processes + objects)
    total_edges = sum(r["stats"]["total_edges"] for r in processes + objects)

    stats = {
        "declared_count": release_meta["declared_count"],
        "process_count": len(processes),
        "object_count": len(objects),
        "env_var_count": len(env_vars),
        "group_count": len(groups),
        "skipped_groups": len(groups),  # groups are parsed but not migrated
        "error_count": len(errors),
        "total_stages": total_stages,
        "total_parsed_stages": total_parsed,
        "total_skipped_stages": total_skipped,
        "total_edges": total_edges,
    }

    return {
        "release_meta": release_meta,
        "processes": processes,
        "objects": objects,
        "environment_variables": env_vars,
        "groups": groups,
        "errors": errors,
        "stats": stats,
    }


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------


def print_summary(result: dict, filepath: str) -> None:
    meta = result["release_meta"]
    stats = result["stats"]

    print(f"\n{'=' * 60}")
    print(f"FILE         : {filepath}")
    print(f"release      : {meta['name']}")
    print(f"created      : {meta['created']}")
    print(f"created_by   : {meta['created_by']}")
    print(f"package      : {meta['package_name']} (id={meta['package_id']})")
    print(f"declared     : {meta['declared_count']} items in release")

    print(f"\nprocesses    : {stats['process_count']}")
    for p in result["processes"]:
        m = p["meta"]
        s = p["stats"]
        grps = ", ".join(m.get("groups", [])) or "—"
        print(f"  [{m['artefact_type']}] {m['name']}")
        print(f"    version={m['version']}  BP={m['bpversion']}")
        print(
            f"    pages={s['pages']}  parsed={s['parsed']}  "
            f"skipped={s['skipped']}  edges={s['total_edges']}"
        )
        print(f"    groups: {grps}")
        if m.get("narrative"):
            print(f"    narrative: {m['narrative'][:80]}")

    print(f"\nobjects      : {stats['object_count']}")
    for o in result["objects"]:
        m = o["meta"]
        s = o["stats"]
        grps = ", ".join(m.get("groups", [])) or "—"
        print(f"  [{m['artefact_type']}] {m['name']}")
        print(f"    version={m['version']}  BP={m['bpversion']}")
        print(
            f"    pages={s['pages']}  parsed={s['parsed']}  "
            f"skipped={s['skipped']}  edges={s['total_edges']}"
        )
        print(f"    groups: {grps}")

    print(f"\nenv_vars     : {stats['env_var_count']}")
    for ev in result["environment_variables"]:
        print(f"  {ev['name']} ({ev['type']}) = {ev['value'][:60]}")
        if ev["description"]:
            print(f"    desc: {ev['description'][:80]}")

    print(f"\ngroups       : {stats['group_count']} (not migrated)")
    for g in result["groups"]:
        print(
            f"  [{g['type']}] {g['name']}  "
            f"({len(g['member_ids'])} members, default={g['is_default']})"
        )

    if result["errors"]:
        print(f"\nERRORS       : {stats['error_count']}")
        for e in result["errors"]:
            print(f"  [{e['item_type']}] {e['name']}: {e['error']}")

    print("\ntotals")
    print(f"  stages (raw)    : {stats['total_stages']}")
    print(f"  stages (parsed) : {stats['total_parsed_stages']}")
    print(f"  stages (skipped): {stats['total_skipped_stages']}")
    print(f"  edges           : {stats['total_edges']}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python bp_release_parser.py <file.bprelease>")
        sys.exit(1)

    filepath = sys.argv[1]
    result = parse_release(filepath)
    print_summary(result, filepath)
