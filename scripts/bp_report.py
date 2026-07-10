"""
bp_report.py — Blue Prism diagnostic report generator
Consumes the dict produced by bp_parser.parse() and writes a .md report.
No UUIDs in output — all IDs resolved to names.

Usage:
    python bp_report.py <file.xml> [output.md]
    If output path is omitted, prints to stdout.
"""

import os
import sys
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


def _flow_line(stage: dict, stage_by_id: dict) -> str:
    """Build a compact flow summary line for a stage."""
    parts = []
    if stage["onsuccess"]:
        parts.append(f"→ {_name(stage_by_id, stage['onsuccess'])}")
    if stage["ontrue"]:
        parts.append(f"true → {_name(stage_by_id, stage['ontrue'])}")
    if stage["onfalse"]:
        parts.append(f"false → {_name(stage_by_id, stage['onfalse'])}")
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


def _render_stage(s: dict, stage_by_id: dict, lines: list[str]) -> None:
    stype = s["type"]
    raw_type = s["raw_type"]
    type_tag = f"`{stype}`" if raw_type == stype else f"`{stype}` *(was {raw_type})*"

    lines.append(f"### {s['name']}  [{type_tag}]")

    if s.get("narrative"):
        lines.append(f"  > {_trunc(s['narrative'], 120)}")

    # Flow edges
    flow = _flow_line(s, stage_by_id)
    if flow:
        lines.append(flow)

    # SubSheet / Process call
    if s["is_subsheet_call"] or s["is_process_call"]:
        call_kind = "process call" if s["is_process_call"] else "page call"
        # Resolve processid to page name via stage_by_id lookup won't work
        # (processid is a page UUID, not a stage UUID) — handled by caller
        lines.append(f"  **{call_kind}** → see page section below")

    # VBO call
    if s["vbo_object"]:
        lines.append(f"  **VBO:** `{s['vbo_object']}` → `{s['vbo_action']}`")
        if s["is_alert"]:
            lines.append("  *(Alert — notification stage)*")
        if s["is_skill"]:
            lines.append("  *(Skill — Decipher/SDD, STUB at migration)*")

    # Inputs
    if s["inputs"]:
        lines.append(f"  **inputs:** {_fmt_inputs(s['inputs'])}")

    # Outputs
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

    # Exception details
    if stype == "Exception":
        if s["exception_usecurrent"]:
            lines.append("  **throws:** *(re-raises current exception)*")
        else:
            exc_t = s["exception_type"] or "?"
            exc_d = _trunc(s["exception_detail"] or "", 100)
            lines.append(f"  **throws:** `{exc_t}` — {exc_d}")

    # Recover / Resume — role annotation
    if stype == "Recover":
        lines.append("  *(error path entry — triggered implicitly by Block exception)*")
    if stype == "Resume":
        lines.append("  *(error path exit — resumes normal flow)*")

    # Block — role annotation
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
# Main report builder
# ---------------------------------------------------------------------------


def generate(result: dict) -> str:
    meta = result["meta"]
    pages = result["pages"]
    stages = result["stages"]
    edges = result["edges"]
    stage_by_id = result["stage_by_id"]
    stats = result["stats"]

    # Group stages by page
    page_stages: dict[str, list] = defaultdict(list)
    for s in stages:
        page_stages[s["page_id"]].append(s)

    # Build incoming-edge index (for cross-reference)
    incoming: dict[str, list] = defaultdict(list)
    for e in edges:
        incoming[e["to_id"]].append((e["from_id"], e["label"]))

    # Build page-call cross-reference: page_id → list of SubSheet caller stage names
    page_callers: dict[str, list[str]] = defaultdict(list)
    for s in stages:
        if s["processid"] and s["processid"] in pages:
            page_callers[s["processid"]].append(s["name"])

    lines: list[str] = []

    # -----------------------------------------------------------------------
    # Header
    # -----------------------------------------------------------------------
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
    lines.append("")

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

    # -----------------------------------------------------------------------
    # Page index
    # -----------------------------------------------------------------------
    lines.append("## Pages")
    lines.append("")
    lines.append("| Page | Type | Published | Stages | Called by |")
    lines.append("|---|---|---|---|---|")
    for pid, p in _page_order(pages):
        n = len(page_stages.get(pid, []))
        callers = ", ".join(page_callers.get(pid, [])) or "—"
        pub = "—" if p["published"] is None else ("yes" if p["published"] else "no")
        lines.append(f"| {p['name']} | {p['type']} | {pub} | {n} | {callers} |")
    lines.append("")

    # -----------------------------------------------------------------------
    # Per-page sections
    # -----------------------------------------------------------------------
    lines.append("---")
    lines.append("")

    for pid, page in _page_order(pages):
        page_name = page["name"]
        pub_str = (
            ""
            if page["published"] is None
            else (" · published=yes" if page["published"] else " · published=no")
        )
        lines.append(f"## Page: {page_name}  *({page['type']}{pub_str})*")
        lines.append("")

        if pid in page_callers and page_callers[pid]:
            lines.append(f"**Called by:** {', '.join(page_callers[pid])}")
            lines.append("")

        stage_list = page_stages.get(pid, [])
        if not stage_list:
            lines.append("*No parsed stages on this page.*")
            lines.append("")
            continue

        # Separate flow stages from data/block/structural stages for clarity
        FLOW_TYPES = {
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
        DATA_TYPES = {"Data", "Collection"}
        SCOPE_TYPES = {"Block"}

        flow_stages = [s for s in stage_list if s["type"] in FLOW_TYPES]
        data_stages = [s for s in stage_list if s["type"] in DATA_TYPES]
        block_stages = [s for s in stage_list if s["type"] in SCOPE_TYPES]
        other_stages = [
            s for s in stage_list if s["type"] not in FLOW_TYPES | DATA_TYPES | SCOPE_TYPES
        ]

        # Flow section
        if flow_stages:
            lines.append("### Flow stages")
            lines.append("")
            for s in flow_stages:
                _render_stage(s, stage_by_id, lines)

        # Scope blocks
        if block_stages:
            lines.append("### Scope blocks")
            lines.append("")
            lines.append("| Block name | Scope purpose |")
            lines.append("|---|---|")
            for s in block_stages:
                note = s.get("narrative") or "—"
                lines.append(f"| {s['name']} | {_trunc(note, 60)} |")
            lines.append("")

        # Data items
        if data_stages:
            lines.append("### Data items")
            lines.append("")
            lines.append("| Name | Type | Initial value |")
            lines.append("|---|---|---|")
            for s in data_stages:
                iv = _trunc(s["initial_value"] or "", 50) or "—"
                lines.append(f"| {s['name']} | {s['datatype'] or '?'} | {iv} |")
            lines.append("")

        # Any remaining types
        if other_stages:
            lines.append("### Other stages")
            lines.append("")
            for s in other_stages:
                _render_stage(s, stage_by_id, lines)

    # -----------------------------------------------------------------------
    # Full edge list (appendix)
    # -----------------------------------------------------------------------
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
        # Page from the source stage
        src_page_id = src_stage["page_id"] if src_stage else ""
        src_page = pages.get(src_page_id, {}).get("name", "?")
        lines.append(f"| {src_page} | {src} | {e['label']} | {tgt} |")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    if len(sys.argv) < 2:
        print("Usage: python bp_report.py <file.xml> [output.md]")
        sys.exit(1)

    filepath = sys.argv[1]
    outpath = sys.argv[2] if len(sys.argv) > 2 else None

    result = parse(filepath)
    report = generate(result)

    if outpath:
        with open(outpath, "w", encoding="utf-8") as f:
            f.write(report)
        s = result["stats"]
        print(f"Report written: {outpath}")
        print(
            f"  pages={s['pages']} parsed={s['parsed']} "
            f"explicit_edges={s['explicit_edges']} implicit_edges={s['implicit_edges']}"
        )
    else:
        print(report)


if __name__ == "__main__":
    main()
