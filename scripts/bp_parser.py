"""
bp_parser.py — Blue Prism XML diagnostic parser
Parses .bprelease / .bpprocess / .bpobject files into a plain dict.
No external dependencies beyond the Python standard library.

Schema reference: bp_xml_schema.md
"""

import xml.etree.ElementTree as ET
from collections import defaultdict
from typing import Any

NS = "http://www.blueprism.co.uk/product/process"
BP = f"{{{NS}}}"

# Stage types that produce no AST node
SKIP_TYPES = {"Anchor", "Note", "SubSheetInfo", "ProcessInfo"}

# Stage types that are normalised into another type
NORMALISE_MAP = {
    "SubSheet": "Action",
    "Process": "Action",
    "MultipleCalculation": "Calculation",
    "Alert": "Action",
    "Skill": "Action",
    "WaitStart": "Wait",
    "WaitEnd": "Wait",
    "LoopStart": "Loop",
    "LoopEnd": "Loop",
}

IMPLICIT_PAGE_ID = "IMPLICIT_MAIN"


def _txt(el: ET.Element, tag: str) -> str | None:
    """Return stripped text of a direct child element, or None."""
    child = el.find(f"{BP}{tag}")
    if child is not None and child.text:
        return child.text.strip()
    return None


def _parse_inputs(stage: ET.Element) -> list[dict[str, str]]:
    inputs: list[dict[str, str]] = []
    container = stage.find(f"{BP}inputs")
    if container is None:
        return inputs
    for inp in container.findall(f"{BP}input"):
        inputs.append(
            {
                "name": inp.attrib.get("name", ""),
                "type": inp.attrib.get("type", ""),
                "expr": inp.attrib.get("expr", ""),
                "friendlyname": inp.attrib.get("friendlyname", ""),
            }
        )
    return inputs


def _parse_outputs(stage: ET.Element) -> list[dict[str, str]]:
    outputs: list[dict[str, str]] = []
    container = stage.find(f"{BP}outputs")
    if container is None:
        return outputs
    # Both <output> and <o> are valid (schema §8)
    for tag in (f"{BP}output", f"{BP}o"):
        for out in container.findall(tag):
            outputs.append(
                {
                    "name": out.attrib.get("name", ""),
                    "type": out.attrib.get("type", ""),
                    "stage": out.attrib.get("stage", ""),
                    "friendlyname": out.attrib.get("friendlyname", ""),
                }
            )
    return outputs


def _build_anchor_map(raw_stages: list[ET.Element]) -> dict[str, str]:
    """
    Build a map of anchor_id -> real_target_id by following Anchor onsuccess.
    Anchors can chain (Anchor → Anchor → real stage), so we resolve fully.
    """
    # First pass: collect all anchor onsuccess values
    anchor_raw: dict[str, str] = {}
    for s in raw_stages:
        if s.attrib.get("type") == "Anchor":
            sid = s.attrib["stageid"]
            succ = _txt(s, "onsuccess")
            if succ:
                anchor_raw[sid] = succ

    # Second pass: resolve chains (Anchor → Anchor → real)
    resolved: dict[str, str] = {}
    for anchor_id in anchor_raw:
        visited = set()
        current = anchor_raw[anchor_id]
        while current in anchor_raw and current not in visited:
            visited.add(current)
            current = anchor_raw[current]
        resolved[anchor_id] = current

    return resolved


def _resolve_edge(target_id: str | None, anchor_map: dict[str, str]) -> str | None:
    """Follow anchor indirection to get the real target stage id."""
    if target_id is None:
        return None
    return anchor_map.get(target_id, target_id)


def _parse_stage(stage: ET.Element, anchor_map: dict[str, str]) -> dict[str, Any] | None:
    """Parse a single stage element into a dict. Returns None for skip types."""
    raw_type = stage.attrib.get("type", "")

    if raw_type in SKIP_TYPES:
        return None

    sid = stage.attrib["stageid"]
    sname = stage.attrib.get("name", "")

    # Page membership (schema §4 page identity rule)
    ssid_el = stage.find(f"{BP}subsheetid")
    page_id = ssid_el.text.strip() if ssid_el is not None and ssid_el.text else IMPLICIT_PAGE_ID

    # Normalisation flags
    normalised_type = NORMALISE_MAP.get(raw_type, raw_type)
    is_subsheet_call = raw_type == "SubSheet"
    is_process_call = raw_type == "Process"
    is_alert = raw_type == "Alert"
    is_skill = raw_type == "Skill"

    # Flow edges (resolve through anchors)
    onsuccess = _resolve_edge(_txt(stage, "onsuccess"), anchor_map)
    ontrue = _resolve_edge(_txt(stage, "ontrue"), anchor_map)
    onfalse = _resolve_edge(_txt(stage, "onfalse"), anchor_map)
    processid = _txt(stage, "processid")

    # VBO call (Action, SubSheet normalised to Action)
    vbo_object = vbo_action = None
    res = stage.find(f"{BP}resource")
    if res is not None:
        vbo_object = res.attrib.get("object", "")
        vbo_action = res.attrib.get("action", "")

    # Expression (Calculation, Decision)
    expression = None
    calc_el = stage.find(f"{BP}calculation")
    if calc_el is not None:
        expression = calc_el.attrib.get("expression", "")

    dec_el = stage.find(f"{BP}decision")
    if dec_el is not None:
        expression = dec_el.attrib.get("expression", "")

    # MultipleCalculation — fan out into sub-steps
    multi_steps = []
    steps_el = stage.find(f"{BP}steps")
    if steps_el is not None:
        for step in steps_el.findall(f"{BP}calculation"):
            multi_steps.append(
                {
                    "expression": step.attrib.get("expression", ""),
                    "target": step.attrib.get("stage", ""),
                }
            )

    # Exception details
    exc_type = exc_detail = exc_usecurrent = None
    exc_el = stage.find(f"{BP}exception")
    if exc_el is not None:
        exc_type = exc_el.attrib.get("type", "")
        exc_detail = exc_el.attrib.get("detail", "")
        exc_usecurrent = exc_el.attrib.get("usecurrent", "no").lower() == "yes"

    # Data / Collection
    datatype = _txt(stage, "datatype")
    initial_value = _txt(stage, "initialvalue")

    # Code
    code_el = stage.find(f"{BP}code")
    code_text = code_el.text if code_el is not None else None

    # Inputs / Outputs
    inputs = _parse_inputs(stage)
    outputs = _parse_outputs(stage)

    # Narrative
    narrative = _txt(stage, "narrative")

    return {
        "id": sid,
        "name": sname,
        "raw_type": raw_type,
        "type": normalised_type,
        "page_id": page_id,
        # flow edges
        "onsuccess": onsuccess,
        "ontrue": ontrue,
        "onfalse": onfalse,
        "processid": processid,
        # VBO
        "vbo_object": vbo_object,
        "vbo_action": vbo_action,
        # expression
        "expression": expression,
        "multi_steps": multi_steps,
        # exception
        "exception_type": exc_type,
        "exception_detail": exc_detail,
        "exception_usecurrent": exc_usecurrent,
        # data
        "datatype": datatype,
        "initial_value": initial_value,
        # code
        "code_text": code_text,
        "code_length": len(code_text) if code_text else 0,
        # params
        "inputs": inputs,
        "outputs": outputs,
        # normalisation flags
        "is_subsheet_call": is_subsheet_call,
        "is_process_call": is_process_call,
        "is_alert": is_alert,
        "is_skill": is_skill,
        # narrative
        "narrative": narrative,
    }


def parse(filepath: str) -> dict[str, Any]:
    """
    Parse a Blue Prism XML file and return a structured dict.

    Returns:
        {
            meta: {name, version, bpversion, artefact_type, narrative, runmode},
            pages: {page_id: {name, type, published}},
            stages: [...],
            edges: [{from_id, to_id, label}],
            stats: {total_raw, parsed, skipped, pages, edges}
        }
    """
    tree = ET.parse(filepath)
    root = tree.getroot()

    # Root discriminator (schema §2)
    root_tag = root.tag.replace(BP, "")
    artefact_type = "object" if root_tag == "object" else "process"

    inner_proc = root.find(f"{BP}process")
    if inner_proc is None:
        raise ValueError(f"No inner <process> element found in {filepath}")

    # Metadata
    meta = {
        "name": inner_proc.attrib.get("name", root.attrib.get("name", "")),
        "version": inner_proc.attrib.get("version", ""),
        "bpversion": inner_proc.attrib.get("bpversion", ""),
        "artefact_type": artefact_type,
        "narrative": inner_proc.attrib.get("narrative", ""),
        "runmode": inner_proc.attrib.get("runmode", ""),
        "type": inner_proc.attrib.get("type", artefact_type),
    }

    # Subsheet registry (schema §3)
    implicit_page_name = "Initialize" if artefact_type == "object" else "Main Page"
    pages = {
        IMPLICIT_PAGE_ID: {
            "name": implicit_page_name,
            "type": "implicit",
            "published": None,
        }
    }
    for ss in inner_proc.findall(f"{BP}subsheet"):
        ssid = ss.attrib["subsheetid"]
        name_el = ss.find(f"{BP}name")
        raw_pub = ss.attrib.get("published", "false")
        pages[ssid] = {
            "name": name_el.text if name_el is not None else "?",
            "type": ss.attrib.get("type", "Normal"),
            "published": raw_pub.lower() == "true",
        }

    # Raw stage list
    raw_stages = inner_proc.findall(f"{BP}stage")
    total_raw = len(raw_stages)

    # Build anchor resolution map before parsing stages
    anchor_map = _build_anchor_map(raw_stages)

    # Parse all stages
    parsed_stages = []
    skipped_count = 0
    for raw_s in raw_stages:
        result = _parse_stage(raw_s, anchor_map)
        if result is None:
            skipped_count += 1
        else:
            parsed_stages.append(result)

    # Build stage lookup for edge resolution (name lookup)
    stage_by_id: dict[str, dict] = {s["id"]: s for s in parsed_stages}

    # Build edge list (schema §7)
    edges = []
    seen_edges = set()

    def add_edge(from_id: str, to_id: str, label: str):
        if to_id is None:
            return
        # Skip edges that point to skipped/anchor stages not in stage_by_id
        # (they were already resolved through anchors; if still missing, target
        # is a skipped type like Note — drop the edge)
        if to_id not in stage_by_id:
            return
        key = (from_id, to_id, label)
        if key not in seen_edges:
            seen_edges.add(key)
            edges.append({"from_id": from_id, "to_id": to_id, "label": label})

    for s in parsed_stages:
        sid = s["id"]
        if s["onsuccess"]:
            add_edge(sid, s["onsuccess"], "→")
        if s["ontrue"]:
            add_edge(sid, s["ontrue"], "true")
        if s["onfalse"]:
            add_edge(sid, s["onfalse"], "false")

    # Implicit Block → Recover edges (schema §7)
    # Group by page, find Block/Recover pairs
    page_blocks: dict[str, list] = defaultdict(list)
    page_recovers: dict[str, list] = defaultdict(list)
    for s in parsed_stages:
        if s["type"] == "Block":
            page_blocks[s["page_id"]].append(s)
        if s["type"] == "Recover":
            page_recovers[s["page_id"]].append(s)

    for page_id, recovers in page_recovers.items():
        blocks = page_blocks.get(page_id, [])
        for recover in recovers:
            for block in blocks:
                add_edge(block["id"], recover["id"], "on_exception")

    stats = {
        "total_raw": total_raw,
        "parsed": len(parsed_stages),
        "skipped": skipped_count,
        "pages": len(pages),
        "explicit_edges": len([e for e in edges if e["label"] != "on_exception"]),
        "implicit_edges": len([e for e in edges if e["label"] == "on_exception"]),
        "total_edges": len(edges),
    }

    return {
        "meta": meta,
        "pages": pages,
        "stages": parsed_stages,
        "edges": edges,
        "stage_by_id": stage_by_id,
        "stats": stats,
    }


def print_summary(result: dict, filepath: str) -> None:
    meta = result["meta"]
    stats = result["stats"]
    pages = result["pages"]
    print(f"\n{'=' * 60}")
    print(f"FILE : {filepath}")
    print(f"name          : {meta['name']}")
    print(f"artefact_type : {meta['artefact_type']}")
    print(f"version       : {meta['version']} (BP {meta['bpversion']})")
    print(f"narrative     : {meta['narrative'][:80]}")
    print(f"\npages         : {stats['pages']}")
    for pid, p in pages.items():
        print(
            f"  {'[implicit]' if pid == IMPLICIT_PAGE_ID else pid[:8] + '...'}"
            f"  {p['name']}  ({p['type']}, pub={p['published']})"
        )
    print(f"\nstages total  : {stats['total_raw']}")
    print(f"  parsed      : {stats['parsed']}")
    print(f"  skipped     : {stats['skipped']}")
    print("\nedges")
    print(f"  explicit    : {stats['explicit_edges']}")
    print(f"  implicit    : {stats['implicit_edges']}  (Block→Recover)")
    print(f"  total       : {stats['total_edges']}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python bp_parser.py <file.xml>")
        sys.exit(1)

    filepath = sys.argv[1]
    result = parse(filepath)
    print_summary(result, filepath)
