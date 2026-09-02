"""
bp_report.py — Blue Prism diagnostic report generator
Consumes the dict produced by bp_parser.parse() or bp_release_parser.parse_release()
and writes a .md report. No UUIDs in output — all IDs resolved to names.

Usage:
    python bp_report.py <file.xml|bprelease> [output.md]
    If output path is omitted, prints to stdout.

Supports: .bprelease, .bpprocess, .bpobject, and raw .xml files.
File type is detected from the XML root tag — not the file extension.
"""

import os
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))
from bp_parser_v2 import IMPLICIT_PAGE_ID, parse

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _name(stage_by_id: dict, sid: str | None, fallback: str = "?") -> str:
    """Resolve a stage UUID to its display name. Never returns a UUID."""
    if sid is None:
        return ""
    s = stage_by_id.get(sid)
    return s["name"] if s else fallback


def _page_order(pages: dict) -> list[tuple[str, dict]]:
    """Implicit page first, then alphabetical by name."""
    implicit = [(IMPLICIT_PAGE_ID, pages[IMPLICIT_PAGE_ID])]
    named = sorted(
        [(pid, p) for pid, p in pages.items() if pid != IMPLICIT_PAGE_ID],
        key=lambda x: x[1]["name"],
    )
    return implicit + named


def _bfs_order(page_id: str, stages: list, stage_by_id: dict) -> list[dict]:
    """
    Return stages on this page in BFS traversal order from Start.
    Unreachable stages (Recover/Resume entry points) appended after.
    Ensures End appears after happy-path stages, error-path stages last.
    """
    page_map = {s["id"]: s for s in stages if s["page_id"] == page_id}
    start = next((s for s in page_map.values() if s["type"] == "Start"), None)
    if not start:
        return list(page_map.values())

    visited, seen, queue = [], set(), [start["id"]]
    while queue:
        sid = queue.pop(0)
        if sid in seen or sid not in page_map:
            continue
        seen.add(sid)
        visited.append(page_map[sid])
        for key in ("onsuccess", "ontrue", "onfalse"):
            nxt = page_map[sid].get(key)
            if nxt and nxt not in seen and nxt in page_map:
                queue.append(nxt)

    for s in page_map.values():
        if s["id"] not in seen:
            visited.append(s)
    return visited


def _flow_line(stage: dict, stage_by_id: dict, pages: dict) -> str:
    """Build a compact flow summary line for a stage."""
    parts = []
    if stage["onsuccess"]:
        parts.append(f"→ {_name(stage_by_id, stage['onsuccess'])}")
    if stage["ontrue"]:
        parts.append(f"true → {_name(stage_by_id, stage['ontrue'])}")
    if stage["onfalse"]:
        parts.append(f"false → {_name(stage_by_id, stage['onfalse'])}")
    if stage.get("is_subsheet_call") or stage.get("is_process_call"):
        pid = stage.get("processid")
        target = pages.get(pid, {}).get("name", "?") if pid else "?"
        kind = "process" if stage.get("is_process_call") else "page"
        parts.append(f"calls {kind} → {target}")
    return "  " + " | ".join(parts) if parts else ""


def _fmt_inputs(inputs: list[dict]) -> str:
    if not inputs:
        return ""
    parts = []
    for i in inputs:
        expr = f"={i['expr']}" if i["expr"] else ""
        parts.append(f"{i['name']} ({i['type']}){expr}")
    return ", ".join(parts)


def _fmt_outputs(outputs: list[dict]) -> str:
    if not outputs:
        return ""
    parts = []
    for o in outputs:
        target = f" → {o['stage']}" if o["stage"] else ""
        parts.append(f"{o['name']} ({o['type']}){target}")
    return ", ".join(parts)


def _trunc(s: str, n: int = 80) -> str:
    if not s:
        return ""
    s = s.strip().replace("\n", " ")
    return s[:n] + "…" if len(s) > n else s


# ---------------------------------------------------------------------------
# Per-stage renderer
# ---------------------------------------------------------------------------


def _render_stage(s: dict, stage_by_id: dict, pages: dict, lines: list[str]) -> None:
    stype = s["type"]
    raw_type = s["raw_type"]
    type_tag = f"`{stype}`" if raw_type == stype else f"`{stype}` *(was {raw_type})*"

    lines.append(f"### {s['name']}  [{type_tag}]")

    if s.get("narrative"):
        lines.append(f"  > {_trunc(s['narrative'], 120)}")

    # Flow edges (with page-call resolution)
    flow = _flow_line(s, stage_by_id, pages)
    if flow:
        lines.append(flow)

    # VBO call
    if s["vbo_object"]:
        lines.append(f"  **VBO:** `{s['vbo_object']}` → `{s['vbo_action']}`")
        if s["is_alert"]:
            lines.append("  *(Alert — notification stage)*")
        if s["is_skill"]:
            lines.append("  *(Skill — Decipher/SDD, STUB at migration)*")

    # Inputs / Outputs
    if s["inputs"]:
        lines.append(f"  **inputs:** {_fmt_inputs(s['inputs'])}")
    if s["outputs"]:
        lines.append(f"  **outputs:** {_fmt_outputs(s['outputs'])}")

    # Expression (Calculation / Decision)
    if stype == "Decision" and s["expression"]:
        lines.append(f"  **expression:** `{_trunc(s['expression'], 100)}`")

    if stype == "Calculation":
        if s["multi_steps"]:
            lines.append(f"  **assignments ({len(s['multi_steps'])}):**")
            for step in s["multi_steps"]:
                lines.append(f"    - `{step['target']}` ← `{_trunc(step['expression'], 80)}`")
        elif s["expression"]:
            lines.append(f"  **expression:** `{_trunc(s['expression'], 100)}`")

    # Wait bracket fields (WaitStart/WaitEnd)
    if stype == "Wait":
        bracket = "WaitStart" if raw_type == "WaitStart" else "WaitEnd"
        lines.append(f"  **bracket:** {bracket}")
        if s.get("timeout_seconds") is not None:
            lines.append(f"  **timeout:** {s['timeout_seconds']}s")
        if s.get("group_id"):
            lines.append(f"  **group_id:** `{s['group_id'][:8]}…` *(pairs WaitStart↔WaitEnd)*")

    # Loop bracket fields (LoopStart/LoopEnd)
    if stype == "Loop":
        bracket = "LoopStart" if raw_type == "LoopStart" else "LoopEnd"
        lines.append(f"  **bracket:** {bracket}")
        if s.get("group_id"):
            lines.append(f"  **group_id:** `{s['group_id'][:8]}…`")

    # Exception details
    if stype == "Exception":
        if s["exception_usecurrent"]:
            lines.append("  **throws:** *(re-raises current exception)*")
        else:
            exc_t = s["exception_type"] or "?"
            exc_d = _trunc(s["exception_detail"] or "", 100)
            lines.append(f"  **throws:** `{exc_t}` — {exc_d}")

    # Recover / Resume
    if stype == "Recover":
        lines.append("  *(error path entry — triggered implicitly by Block exception)*")
    if stype == "Resume":
        lines.append("  *(error path exit — resumes normal flow)*")

    # Block
    if stype == "Block":
        lines.append("  *(scope boundary — guards stages between here and matching Recover)*")

    # Data item
    if stype in ("Data", "Collection"):
        dt = s["datatype"] or "?"
        iv = s["initial_value"]
        iv_str = f"  initial=`{_trunc(iv, 60)}`" if iv else ""
        lines.append(f"  **datatype:** {dt}{iv_str}")

    # Code stage
    if stype == "Code":
        lines.append(f"  **code:** {s['code_length']} chars (VBScript)")

    lines.append("")


# ---------------------------------------------------------------------------
# Single-artefact report (process / object)
# ---------------------------------------------------------------------------


def generate(result: dict) -> str:
    meta = result["meta"]
    pages = result["pages"]
    stages = result["stages"]
    edges = result["edges"]
    stage_by_id = result["stage_by_id"]
    stats = result["stats"]

    page_callers: dict[str, list[str]] = defaultdict(list)
    for s in stages:
        if s["processid"] and s["processid"] in pages:
            page_callers[s["processid"]].append(s["name"])

    lines: list[str] = []

    # Header
    lines.append(f"# {meta['name']}")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|---|---|")
    lines.append(f"| Artefact type | {meta['artefact_type']} |")
    lines.append(f"| Version | {meta['version']} |")
    lines.append(f"| BP version | {meta['bpversion']} |")
    lines.append(f"| Description | {meta['narrative'] or '—'} |")
    if meta.get("runmode"):
        lines.append(f"| Run mode | {meta['runmode']} |")
    if result.get("release_id"):
        lines.append(f"| Release ID | `{result['release_id']}` |")
    lines.append("")

    # Summary
    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Count |")
    lines.append("|---|---|")
    lines.append(f"| Pages | {stats['pages']} |")
    lines.append(f"| Stages (parsed) | {stats['parsed']} |")
    lines.append(
        f"| Stages (skipped) | {stats['skipped']} (Anchor, Note, SubSheetInfo, ProcessInfo) |"
    )
    lines.append(f"| Flow edges (explicit) | {stats['explicit_edges']} |")
    lines.append(f"| Flow edges (implicit Block→Recover) | {stats['implicit_edges']} |")
    lines.append("")

    # Page index
    lines.append("## Pages")
    lines.append("")
    lines.append("| Page | Type | Published | Stages | Called by |")
    lines.append("|---|---|---|---|---|")
    for pid, p in _page_order(pages):
        n = len([s for s in stages if s["page_id"] == pid])
        callers = ", ".join(page_callers.get(pid, [])) or "—"
        pub = "—" if p["published"] is None else ("yes" if p["published"] else "no")
        lines.append(f"| {p['name']} | {p['type']} | {pub} | {n} | {callers} |")
    lines.append("")

    lines.append("---")
    lines.append("")

    FLOW = {
        "Start",
        "End",
        "Action",
        "Decision",
        "Calculation",
        "Code",
        "Exception",
        "Recover",
        "Resume",
        "Wait",
        "Loop",
        "Navigate",
        "Read",
        "Write",
        "Choice",
    }
    DATA = {"Data", "Collection"}
    SCOPE = {"Block"}

    for pid, page in _page_order(pages):
        pub_str = (
            ""
            if page["published"] is None
            else (" · published=yes" if page["published"] else " · published=no")
        )
        lines.append(f"## Page: {page['name']}  *({page['type']}{pub_str})*")
        lines.append("")

        if page_callers.get(pid):
            lines.append(f"**Called by:** {', '.join(page_callers[pid])}")
            lines.append("")

        ordered = _bfs_order(pid, stages, stage_by_id)
        if not ordered:
            lines.append("*No parsed stages on this page.*")
            lines.append("")
            continue

        flow_stages = [s for s in ordered if s["type"] in FLOW]
        data_stages = [s for s in ordered if s["type"] in DATA]
        block_stages = [s for s in ordered if s["type"] in SCOPE]
        other_stages = [s for s in ordered if s["type"] not in FLOW | DATA | SCOPE]

        if flow_stages:
            lines.append("### Flow stages")
            lines.append("")
            for s in flow_stages:
                _render_stage(s, stage_by_id, pages, lines)

        if block_stages:
            lines.append("### Scope blocks")
            lines.append("")
            lines.append("| Block name | Scope purpose |")
            lines.append("|---|---|")
            for s in block_stages:
                lines.append(f"| {s['name']} | {_trunc(s.get('narrative') or '', 60) or '—'} |")
            lines.append("")

        if data_stages:
            lines.append("### Data items")
            lines.append("")
            lines.append("| Name | Type | Initial value |")
            lines.append("|---|---|---|")
            for s in data_stages:
                iv = _trunc(s["initial_value"] or "", 50) or "—"
                lines.append(f"| {s['name']} | {s['datatype'] or '?'} | {iv} |")
            lines.append("")

        if other_stages:
            lines.append("### Other stages")
            lines.append("")
            for s in other_stages:
                _render_stage(s, stage_by_id, pages, lines)

    # Edge appendix
    lines.append("---")
    lines.append("")
    lines.append("## Appendix: all flow edges")
    lines.append("")
    lines.append("| Page | From | Label | To |")
    lines.append("|---|---|---|---|")
    for e in edges:
        src_stage = stage_by_id.get(e["from_id"])
        tgt_stage = stage_by_id.get(e["to_id"])
        src = src_stage["name"] if src_stage else f"[{e['from_id'][:8]}]"
        tgt = tgt_stage["name"] if tgt_stage else f"[{e['to_id'][:8]}]"
        src_page = pages.get((src_stage or {}).get("page_id", ""), {}).get("name", "?")
        lines.append(f"| {src_page} | {src} | {e['label']} | {tgt} |")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Release report
# ---------------------------------------------------------------------------


def generate_release(release_result: dict) -> str:
    meta = release_result["release_meta"]
    stats = release_result["stats"]
    procs = release_result["processes"]
    objs = release_result["objects"]
    envs = release_result["environment_variables"]
    groups = release_result["groups"]
    errors = release_result["errors"]

    lines: list[str] = []

    lines.append(f"# {meta['name']}")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|---|---|")
    lines.append("| Type | RELEASE |")
    lines.append(f"| Created | {meta['created']} |")
    lines.append(f"| Created by | {meta['created_by']} |")
    lines.append(f"| Package | {meta['package_name']} (id={meta['package_id']}) |")
    lines.append(f"| Declared items | {meta['declared_count']} |")
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Count |")
    lines.append("|---|---|")
    lines.append(f"| Processes | {stats['process_count']} |")
    lines.append(f"| Objects / VBOs | {stats['object_count']} |")
    lines.append(f"| Environment variables | {stats['env_var_count']} |")
    lines.append(f"| Groups (not migrated) | {stats['group_count']} |")
    lines.append(f"| Total stages (parsed) | {stats['total_parsed_stages']} |")
    lines.append(f"| Total edges | {stats['total_edges']} |")
    if stats["error_count"]:
        lines.append(f"| Parse errors | {stats['error_count']} |")
    lines.append("")

    # Environment variables
    lines.append("## Environment Variables")
    lines.append("")
    if envs:
        lines.append("| Name | Type | Value | Description |")
        lines.append("|---|---|---|---|")
        for ev in envs:
            lines.append(
                f"| {ev['name']} | {ev['type']} "
                f"| {_trunc(ev['value'], 60)} "
                f"| {_trunc(ev['description'], 80)} |"
            )
    else:
        lines.append("*No environment variables in this release.*")
    lines.append("")

    # Processes
    lines.append("## Processes")
    lines.append("")
    if procs:
        for p in procs:
            lines.append(f"### {p['meta']['name']}")
            lines.append("")
            lines.append(generate(p))
    else:
        lines.append("*No processes in this release.*")
    lines.append("")

    # Objects
    lines.append("## Objects / VBOs")
    lines.append("")
    if objs:
        for o in objs:
            lines.append(f"### {o['meta']['name']}")
            lines.append("")
            lines.append(generate(o))
    else:
        lines.append("*No objects in this release.*")
    lines.append("")

    # Groups (reference only)
    lines.append("## Groups (not migrated — reference only)")
    lines.append("")
    pg = [g for g in groups if g["type"] == "process-group"]
    og = [g for g in groups if g["type"] == "object-group"]
    if groups:
        lines.append("| Name | Type | Members | Default |")
        lines.append("|---|---|---|---|")
        for g in pg + og:
            lines.append(
                f"| {g['name']} | {g['type']} "
                f"| {len(g['member_ids'])} "
                f"| {'yes' if g['is_default'] else 'no'} |"
            )
    lines.append("")

    # VBO cross-reference
    xref_rows = []
    for p in procs:
        vbo_map: dict[str, set] = {}
        for s in p["stages"]:
            if s.get("vbo_object"):
                vbo_map.setdefault(s["vbo_object"], set()).add(s["vbo_action"] or "")
        for vbo, actions in sorted(vbo_map.items()):
            in_rel = any(o["meta"]["name"] == vbo for o in objs)
            xref_rows.append(
                (
                    p["meta"]["name"],
                    vbo,
                    ", ".join(sorted(a for a in actions if a)),
                    "yes" if in_rel else "no",
                )
            )

    if xref_rows:
        lines.append("## VBO Dependency Cross-Reference")
        lines.append("")
        lines.append("| Process | VBO | Actions called | In release? |")
        lines.append("|---|---|---|---|")
        for row in xref_rows:
            lines.append(f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} |")
        lines.append("")

    # Errors
    if errors:
        lines.append("## Parse Errors")
        lines.append("")
        lines.append("| Type | Name | Error |")
        lines.append("|---|---|---|")
        for e in errors:
            lines.append(f"| {e['item_type']} | {e['name']} | {_trunc(e['error'], 100)} |")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# File type detection
# ---------------------------------------------------------------------------


def _detect_file_type(filepath: str) -> str:
    root = ET.parse(filepath).getroot()
    local = root.tag.split("}")[-1] if "}" in root.tag else root.tag
    if local == "release":
        return "release"
    if local in ("process", "object"):
        return local
    raise ValueError(
        f"Unrecognised root element <{local}>. Expected <release>, <process>, or <object>."
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    if len(sys.argv) < 2:
        print("Usage: python bp_report.py <file.xml|bprelease> [output.md]")
        sys.exit(1)

    filepath = sys.argv[1]
    args = [a for a in sys.argv[2:] if not a.startswith("--")]
    outpath = args[0] if args else None

    try:
        file_type = _detect_file_type(filepath)
    except Exception as exc:
        print(f"Error: {exc}")
        sys.exit(1)

    print(f"File type: {file_type.upper()}")

    if file_type == "release":
        from bp_release_parser import parse_release

        result = parse_release(filepath)
        s = result["stats"]
        print(
            f"  processes={s['process_count']}  objects={s['object_count']}"
            f"  env_vars={s['env_var_count']}  errors={s['error_count']}"
        )
        report = generate_release(result)
    else:
        result = parse(filepath)
        s = result["stats"]
        print(f"  pages={s['pages']}  parsed={s['parsed']}  skipped={s['skipped']}")
        report = generate(result)

    if outpath:
        with open(outpath, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"Report written: {outpath}")
    else:
        print(report)


if __name__ == "__main__":
    main()
