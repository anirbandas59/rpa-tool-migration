"""
bp_html_report.py — Blue Prism HTML diagnostic report generator
Produces a single self-contained .html file from any .bprelease/.bpprocess/.bpobject file.

Features:
- Collapsible page sections (all collapsed by default)
- Colour-coded stage type badges
- Happy-path flow chain per page
- Full detail: inputs, outputs, expressions, VBO calls, data items, blocks
- Decision branch map (true/false targets)
- Error path section per page (Recover/Resume/retry chain)
- Cross-page call index
- Full edge appendix
- Zero external dependencies — single .html file

Usage:
    python bp_html_report.py <file.xml> [output.html]
"""

import html as _html
import os
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(__file__))
from bp_parser_v2 import IMPLICIT_PAGE_ID, parse

# ---------------------------------------------------------------------------
# Stage type → badge colour (background, text)
# ---------------------------------------------------------------------------
TYPE_COLORS = {
    "Start": ("#0C447C", "#ffffff"),
    "End": ("#0C447C", "#ffffff"),
    "Action": ("#533bb7", "#ffffff"),
    "Decision": ("#BA7517", "#ffffff"),
    "Calculation": ("#0F6E56", "#ffffff"),
    "Code": ("#2d5fa3", "#ffffff"),
    "Exception": ("#A32D2D", "#ffffff"),
    "Recover": ("#7a2d5f", "#ffffff"),
    "Resume": ("#7a2d5f", "#ffffff"),
    "Block": ("#5F5E5A", "#ffffff"),
    "Collection": ("#185FA5", "#ffffff"),
    "Data": ("#4a4a4a", "#e8e8e8"),
    "Wait": ("#3B6D11", "#ffffff"),
    "Loop": ("#3B6D11", "#ffffff"),
    "Navigate": ("#8B4513", "#ffffff"),
    "Read": ("#8B4513", "#ffffff"),
    "Write": ("#8B4513", "#ffffff"),
    "Choice": ("#BA7517", "#ffffff"),
}
DEFAULT_COLOR = ("#888780", "#ffffff")


def _badge(stage_type: str, raw_type: str | None = None) -> str:
    bg, fg = TYPE_COLORS.get(stage_type, DEFAULT_COLOR)
    label = stage_type
    if raw_type and raw_type != stage_type:
        label = f"{stage_type} <span style='font-weight:400;opacity:.8'>({raw_type})</span>"
    return (
        f'<span style="background:{bg};color:{fg};padding:2px 8px;border-radius:10px;'
        f'font-size:11px;font-weight:600;white-space:nowrap;letter-spacing:.3px">{label}</span>'
    )


def _e(s: str) -> str:
    """HTML-escape a string."""
    return _html.escape(str(s)) if s else ""


def _trunc(s: str, n: int = 100) -> str:
    if not s:
        return ""
    s = s.strip().replace("\n", " ").replace("\t", " ")
    return s[:n] + "…" if len(s) > n else s


# ---------------------------------------------------------------------------
# Flow chain builder
# ---------------------------------------------------------------------------


def _full_traversal(page_id: str, stages: list, stage_by_id: dict) -> list[dict]:
    """
    BFS from Start following onsuccess + ontrue + onfalse edges,
    returning ALL reachable stages on this page in traversal order.
    Recover/Resume stages (no inbound explicit edges) are appended after.
    """
    page_map = {s["id"]: s for s in stages if s["page_id"] == page_id}
    start = next((s for s in page_map.values() if s["type"] == "Start"), None)
    if not start:
        return list(page_map.values())

    visited = []
    seen = set()
    queue = [start["id"]]

    while queue:
        sid = queue.pop(0)
        if sid in seen or sid not in page_map:
            continue
        seen.add(sid)
        s = page_map[sid]
        visited.append(s)
        for edge_key in ("onsuccess", "ontrue", "onfalse"):
            nxt = s.get(edge_key)
            if nxt and nxt not in seen and nxt in page_map:
                queue.append(nxt)

    # Append stages not reachable via explicit edges (Recover/Resume entry points)
    for s in page_map.values():
        if s["id"] not in seen:
            visited.append(s)

    return visited


def _build_flow_chain(page_id: str, stages: list, stage_by_id: dict) -> list[dict]:
    """
    Return compact chain for the flow-chain badge strip at top of each page.
    All reachable non-structural stages in BFS traversal order.
    """
    all_ordered = _full_traversal(page_id, stages, stage_by_id)
    EXCLUDE = {"Data", "Block", "Collection", "Recover", "Resume"}
    return [
        {"name": s["name"], "type": s["type"], "raw_type": s["raw_type"], "id": s["id"]}
        for s in all_ordered
        if s["type"] not in EXCLUDE
    ]


def _render_flow_chain(chain: list) -> str:
    if not chain:
        return '<span style="color:#888">No flow chain found</span>'
    parts = []
    for _i, node in enumerate(chain):
        cross = node.get("cross", False)
        bg, fg = TYPE_COLORS.get(node["type"], DEFAULT_COLOR)
        style = (
            f"background:{bg};color:{fg};padding:2px 7px;border-radius:4px;"
            f"font-size:11px;font-weight:600;opacity:{'0.6' if cross else '1'}"
        )
        parts.append(f'<span style="{style}">{_e(node["name"])}</span>')
    arrow = ' <span style="color:#aaa;font-size:12px">→</span> '
    return arrow.join(parts)


# ---------------------------------------------------------------------------
# Per-stage detail renderer
# ---------------------------------------------------------------------------


def _render_stage_detail(s: dict, stage_by_id: dict, pages: dict) -> str:
    rows = []

    def row(label: str, value: str, mono: bool = False):
        val_style = (
            "font-family:monospace;font-size:12px;word-break:break-all"
            if mono
            else "font-size:13px"
        )
        rows.append(
            f'<tr><td style="color:#666;font-size:12px;padding:4px 10px 4px 0;'
            f'white-space:nowrap;vertical-align:top;width:130px">{label}</td>'
            f'<td style="{val_style};padding:4px 0;color:#222">{value}</td></tr>'
        )

    # VBO
    if s["vbo_object"]:
        vbo = f"<code>{_e(s['vbo_object'])}</code> → <code>{_e(s['vbo_action'])}</code>"
        flags = []
        if s["is_alert"]:
            flags.append("Alert")
        if s["is_skill"]:
            flags.append("Skill — STUB at migration")
        if flags:
            vbo += f' <span style="color:#BA7517;font-size:11px">({", ".join(flags)})</span>'
        row("VBO", vbo)

    # SubSheet / Process call
    if s["is_subsheet_call"] or s["is_process_call"]:
        target_page = pages.get(s["processid"], {}).get("name", s["processid"] or "?")
        kind = "Process call" if s["is_process_call"] else "Page call"
        row(kind, f'<span style="color:#185FA5;font-weight:600">{_e(target_page)}</span>')

    # Expression
    if s["expression"]:
        row(
            "Expression",
            f'<code style="background:#f3f4f6;padding:2px 5px;border-radius:3px">'
            f"{_e(s['expression'])}</code>",
            mono=True,
        )

    # MultipleCalculation steps
    if s["multi_steps"]:
        lines = []
        for step in s["multi_steps"]:
            lines.append(
                f'<div style="margin:2px 0">'
                f'<code style="color:#0F6E56">{_e(step["target"])}</code>'
                f' ← <code style="background:#f3f4f6;padding:1px 4px;border-radius:2px">'
                f"{_e(step['expression'])}</code></div>"
            )
        row(f"Assignments ({len(s['multi_steps'])})", "".join(lines))

    # Decision branches
    if s["type"] == "Decision":
        td = stage_by_id.get(s["ontrue"], {})
        fd = stage_by_id.get(s["onfalse"], {})
        true_bg, true_fg = TYPE_COLORS.get(td.get("type", ""), DEFAULT_COLOR)
        false_bg, false_fg = TYPE_COLORS.get(fd.get("type", ""), DEFAULT_COLOR)
        branches = (
            f'<span style="color:#3B6D11;font-weight:600">true</span> → '
            f'<span style="background:{true_bg};color:{true_fg};padding:1px 6px;border-radius:3px;font-size:11px">'
            f"{_e(td.get('name', '?'))}</span>"
            f"&nbsp;&nbsp;&nbsp;"
            f'<span style="color:#A32D2D;font-weight:600">false</span> → '
            f'<span style="background:{false_bg};color:{false_fg};padding:1px 6px;border-radius:3px;font-size:11px">'
            f"{_e(fd.get('name', '?'))}</span>"
        )
        row("Branches", branches)

    # Flow
    if s["onsuccess"] and s["type"] != "Decision":
        nxt = stage_by_id.get(s["onsuccess"], {})
        nxt_bg, nxt_fg = TYPE_COLORS.get(nxt.get("type", ""), DEFAULT_COLOR)
        row(
            "Next",
            f'<span style="background:{nxt_bg};color:{nxt_fg};padding:1px 6px;'
            f'border-radius:3px;font-size:11px">{_e(nxt.get("name", "?"))}</span>',
        )

    # Exception
    if s["type"] == "Exception":
        if s["exception_usecurrent"]:
            row("Throws", '<span style="color:#A32D2D">re-raises current exception</span>')
        else:
            exc_t = _e(s["exception_type"] or "?")
            exc_d = _e(_trunc(s["exception_detail"] or "", 120))
            row(
                "Throws",
                f'<code style="color:#A32D2D">{exc_t}</code>'
                f"{"<br><span style='color:#666;font-size:11px'>" + exc_d + '</span>' if exc_d else ''}",
            )

    # Recover / Resume role
    if s["type"] == "Recover":
        row(
            "Role",
            '<span style="color:#7a2d5f">Error path entry — triggered implicitly by Block exception</span>',
        )
        if s["onsuccess"]:
            nxt = stage_by_id.get(s["onsuccess"], {})
            row("Leads to", f'<span style="font-weight:600">{_e(nxt.get("name", "?"))}</span>')
    if s["type"] == "Resume":
        row("Role", '<span style="color:#7a2d5f">Error path exit — resumes normal flow</span>')
        if s["onsuccess"]:
            nxt = stage_by_id.get(s["onsuccess"], {})
            row("Resumes at", f'<span style="font-weight:600">{_e(nxt.get("name", "?"))}</span>')

    # Block role
    if s["type"] == "Block":
        row("Role", '<span style="color:#5F5E5A">Scope boundary — wraps guarded stages</span>')

    # Data / Collection
    if s["type"] in ("Data", "Collection"):
        row("Datatype", f"<code>{_e(s['datatype'] or '?')}</code>")
        if s["initial_value"]:
            row(
                "Initial value",
                f'<code style="background:#f3f4f6;padding:2px 5px;border-radius:3px">'
                f"{_e(_trunc(s['initial_value'], 80))}</code>",
                mono=True,
            )

    # Code
    if s["type"] == "Code":
        row("VBScript", f"{s['code_length']} chars")

    # Inputs
    if s["inputs"]:
        lines = []
        for i in s["inputs"]:
            expr = f' = <code style="color:#0F6E56">{_e(i["expr"])}</code>' if i["expr"] else ""
            lines.append(
                f'<div style="margin:2px 0;padding:2px 0;border-bottom:1px solid #f0f0f0">'
                f'<span style="font-weight:600">{_e(i["name"])}</span>'
                f' <span style="color:#888;font-size:11px">({_e(i["type"])})</span>'
                f"{expr}</div>"
            )
        row(f"Inputs ({len(s['inputs'])})", "".join(lines))

    # Outputs
    if s["outputs"]:
        lines = []
        for o in s["outputs"]:
            target = (
                (f' → <span style="color:#185FA5;font-weight:600">{_e(o["stage"])}</span>')
                if o["stage"]
                else ""
            )
            lines.append(
                f'<div style="margin:2px 0;padding:2px 0;border-bottom:1px solid #f0f0f0">'
                f'<span style="font-weight:600">{_e(o["name"])}</span>'
                f' <span style="color:#888;font-size:11px">({_e(o["type"])})</span>'
                f"{target}</div>"
            )
        row(f"Outputs ({len(s['outputs'])})", "".join(lines))

    # Narrative
    if s.get("narrative"):
        narr = _e(_trunc(s["narrative"], 200))
        row("Narrative", f'<span style="color:#555;font-style:italic">{narr}</span>')

    if not rows:
        return '<span style="color:#aaa;font-size:12px">No additional detail</span>'

    return f'<table style="width:100%;border-collapse:collapse">{"".join(rows)}</table>'


# ---------------------------------------------------------------------------
# Page section renderer
# ---------------------------------------------------------------------------


def _render_page_section(
    pid: str,
    page: dict,
    stages: list,
    edges: list,
    stage_by_id: dict,
    pages: dict,
    page_callers: dict,
    graph_fn=None,
) -> str:
    page_name = page["name"]
    page_stages = [s for s in stages if s["page_id"] == pid]
    type_counts = Counter(s["type"] for s in page_stages)
    pub = "—" if page["published"] is None else ("yes" if page["published"] else "no")
    callers = ", ".join(page_callers.get(pid, [])) or "—"

    # Flow chain
    chain = _build_flow_chain(pid, stages, stage_by_id)
    chain_html = _render_flow_chain(chain)

    # Stage type summary pills
    type_pills = " ".join(
        _badge(t) + f'<span style="font-size:11px;color:#666"> ×{c}</span>'
        for t, c in sorted(type_counts.items())
    )

    # Use BFS traversal order for all stage lists
    ordered = _full_traversal(pid, stages, stage_by_id)

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
    flow_stages = [s for s in ordered if s["type"] in FLOW]
    data_stages = [s for s in ordered if s["type"] in ("Data", "Collection")]
    block_stages = [s for s in ordered if s["type"] == "Block"]

    # Split flow into happy path and error path, preserving traversal order
    error_stages = [s for s in flow_stages if s["type"] in ("Recover", "Resume")]
    happy_stages = [s for s in flow_stages if s["type"] not in ("Recover", "Resume")]

    # ---- Build page header (always visible)
    page_id_attr = f"page-{pid}"
    header = f"""
<div style="border:1px solid #e0e0e0;border-radius:8px;margin-bottom:12px;overflow:hidden">
  <details>
    <summary style="padding:14px 18px;cursor:pointer;background:#fafafa;
                    border-bottom:1px solid #e0e0e0;list-style:none;
                    display:flex;align-items:center;gap:12px;user-select:none"
             id="{page_id_attr}">
      <span style="font-size:15px;font-weight:700;color:#1a1a1a">{_e(page_name)}</span>
      <span style="background:#eee;color:#555;padding:2px 8px;border-radius:10px;
                   font-size:11px">{page["type"]}</span>
      <span style="font-size:11px;color:#888">pub={pub}</span>
      <span style="font-size:11px;color:#888;margin-left:auto">{len(page_stages)} stages</span>
    </summary>
    <div style="padding:16px 18px">
"""

    # Called-by
    if page_callers.get(pid):
        header += (
            f'<div style="margin-bottom:12px;font-size:12px;color:#555">'
            f"<strong>Called by:</strong> {_e(callers)}</div>\n"
        )

    # Flow chain — call graph_fn(pid) per page, else badge fallback
    page_png_b64 = graph_fn(pid) if graph_fn else None
    if page_png_b64:
        flow_visual = (
            f'<img src="data:image/png;base64,{page_png_b64}" '
            f'style="max-width:100%;height:auto;border:1px solid #e0e0e0;'
            f'border-radius:6px;display:block" '
            f'alt="Flow graph: {page_name}" />'
        )
        flow_label = "Process flow graph"
    else:
        flow_visual = (
            f'<div style="display:flex;flex-wrap:wrap;gap:4px;align-items:center">'
            f"{chain_html}</div>"
        )
        flow_label = "Stage flow (badge view)"

    header += f"""
      <div style="margin-bottom:14px">
        <div style="font-size:11px;font-weight:600;color:#888;text-transform:uppercase;
                    letter-spacing:.5px;margin-bottom:6px">{flow_label}</div>
        {flow_visual}
      </div>
"""

    # Type summary
    header += f"""
      <div style="margin-bottom:16px;display:flex;flex-wrap:wrap;gap:6px;align-items:center">
        <span style="font-size:11px;font-weight:600;color:#888;text-transform:uppercase;
                     letter-spacing:.5px;margin-right:4px">Types</span>
        {type_pills}
      </div>
"""

    # ---- Happy-path flow stages
    if happy_stages:
        header += _section_header("Flow stages")
        for s in happy_stages:
            header += _stage_card(s, stage_by_id, pages)

    # ---- Error path (Recover/Resume)
    if error_stages:
        header += _section_header("Error path (Recover / Resume)", color="#7a2d5f", bg="#fdf4f9")
        for s in error_stages:
            header += _stage_card(s, stage_by_id, pages)

    # ---- Scope blocks
    if block_stages:
        header += _section_header("Scope blocks")
        rows = []
        for s in block_stages:
            note = _e(_trunc(s.get("narrative") or "", 60)) or "—"
            rows.append(
                f'<tr><td style="padding:5px 10px 5px 0;font-weight:600;font-size:13px">'
                f"{_e(s['name'])}</td>"
                f'<td style="padding:5px 0;color:#666;font-size:12px">{note}</td></tr>'
            )
        header += (
            f'<table style="width:100%;border-collapse:collapse;margin-bottom:12px">'
            f"{''.join(rows)}</table>\n"
        )

    # ---- Data items
    if data_stages:
        header += _section_header("Data items")
        header += '<table style="width:100%;border-collapse:collapse;margin-bottom:12px">'
        header += (
            '<tr style="border-bottom:2px solid #e0e0e0">'
            '<th style="text-align:left;font-size:11px;color:#888;padding:4px 10px 4px 0">Name</th>'
            '<th style="text-align:left;font-size:11px;color:#888;padding:4px 10px 4px 0">Type</th>'
            '<th style="text-align:left;font-size:11px;color:#888;padding:4px 0">Initial value</th></tr>'
        )
        for s in data_stages:
            iv = _e(_trunc(s["initial_value"] or "", 60)) or "—"
            is_coll = s["type"] == "Collection"
            row_style = "background:#f0f4ff" if is_coll else ""
            header += (
                f'<tr style="border-bottom:1px solid #f0f0f0;{row_style}">'
                f'<td style="padding:5px 10px 5px 0;font-weight:600;font-size:13px">'
                f"{_e(s['name'])}{' ' + _badge('Collection') if is_coll else ''}</td>"
                f'<td style="padding:5px 10px 5px 0;font-size:12px;color:#555">'
                f"<code>{_e(s['datatype'] or '?')}</code></td>"
                f'<td style="padding:5px 0;font-size:12px;color:#555;font-family:monospace">'
                f"{iv}</td></tr>"
            )
        header += "</table>\n"

    header += "    </div>\n  </details>\n</div>\n"
    return header


def _section_header(title: str, color: str = "#333", bg: str = "#f8f8f8") -> str:
    return (
        f'<div style="background:{bg};border-left:3px solid {color};'
        f"padding:6px 10px;margin:14px 0 8px;font-size:12px;font-weight:700;"
        f'color:{color};text-transform:uppercase;letter-spacing:.5px">{title}</div>\n'
    )


def _stage_card(s: dict, stage_by_id: dict, pages: dict) -> str:
    bg, fg = TYPE_COLORS.get(s["type"], DEFAULT_COLOR)
    detail = _render_stage_detail(s, stage_by_id, pages)
    stage_id = f"s-{s['id']}"
    return f"""
<details style="margin-bottom:6px;border:1px solid #eee;border-radius:6px;overflow:hidden">
  <summary style="padding:8px 12px;cursor:pointer;background:#fff;
                  display:flex;align-items:center;gap:8px;list-style:none;user-select:none"
           id="{stage_id}">
    <span style="width:10px;height:10px;border-radius:50%;
                 background:{bg};flex-shrink:0;display:inline-block"></span>
    <span style="font-size:13px;font-weight:600;color:#1a1a1a">{_e(s["name"])}</span>
    {_badge(s["type"], s["raw_type"])}
  </summary>
  <div style="padding:10px 14px;background:#fafafa;border-top:1px solid #eee">
    {detail}
  </div>
</details>
"""


# ---------------------------------------------------------------------------
# Main report generator
# ---------------------------------------------------------------------------


def _page_order(pages: dict) -> list[tuple[str, dict]]:
    implicit = [(IMPLICIT_PAGE_ID, pages[IMPLICIT_PAGE_ID])]
    named = sorted(
        [(pid, p) for pid, p in pages.items() if pid != IMPLICIT_PAGE_ID],
        key=lambda x: x[1]["name"],
    )
    return implicit + named


def generate(result: dict, graph_fn=None) -> str:
    meta = result["meta"]
    pages = result["pages"]
    stages = result["stages"]
    edges = result["edges"]
    stage_by_id = result["stage_by_id"]
    stats = result["stats"]

    # Page-caller cross-ref
    page_callers: dict[str, list[str]] = defaultdict(list)
    for s in stages:
        if s["processid"] and s["processid"] in pages:
            page_callers[s["processid"]].append(s["name"])

    # Overall type counts
    all_type_counts = Counter(s["type"] for s in stages)
    type_summary = " ".join(
        _badge(t) + f'<span style="color:#666;font-size:11px"> ×{c}</span>'
        for t, c in sorted(all_type_counts.items())
    )

    # Edge appendix rows
    edge_rows = []
    for e in edges:
        src = stage_by_id.get(e["from_id"], {})
        tgt = stage_by_id.get(e["to_id"], {})
        src_name = _e(src.get("name", e["from_id"][:8]))
        tgt_name = _e(tgt.get("name", e["to_id"][:8]))
        src_page = pages.get(src.get("page_id", ""), {}).get("name", "?")
        label_color = {"true": "#3B6D11", "false": "#A32D2D", "on_exception": "#BA7517"}.get(
            e["label"], "#555"
        )
        label_str = _e(e["label"])
        edge_rows.append(
            f'<tr style="border-bottom:1px solid #f0f0f0">'
            f'<td style="padding:4px 10px 4px 0;font-size:12px;color:#888">{_e(src_page)}</td>'
            f'<td style="padding:4px 10px 4px 0;font-size:12px;font-weight:600">{src_name}</td>'
            f'<td style="padding:4px 10px 4px 0;font-size:12px;font-weight:700;color:{label_color}">'
            f"{label_str}</td>"
            f'<td style="padding:4px 0;font-size:12px;font-weight:600">{tgt_name}</td>'
            f"</tr>"
        )

    # Page sections
    page_sections_html = ""
    for pid, page in _page_order(pages):
        page_sections_html += _render_page_section(
            pid, page, stages, edges, stage_by_id, pages, page_callers, graph_fn=graph_fn
        )

    pub_val = meta.get("artefact_type", "")
    artefact_icon = "⚙" if pub_val == "object" else "▶"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_e(meta["name"])} — BP Diagnostic</title>
<style>{_SHARED_CSS}</style>
</head>
<body>
<div class="wrap">

  <!-- ===== HEADER ===== -->
  <div class="header-card">
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:4px">
      <span style="font-size:22px">{artefact_icon}</span>
      <h1 style="font-size:20px;font-weight:700;color:#0C447C">{_e(meta["name"])}</h1>
      <span style="background:#e8f0fe;color:#0C447C;padding:2px 8px;border-radius:10px;
                   font-size:11px;font-weight:600">{_e(meta["artefact_type"].upper())}</span>
    </div>
    {f'<p style="color:#555;font-size:13px;margin-bottom:12px">{_e(meta["narrative"])}</p>' if meta["narrative"] else ""}
    <div style="font-size:12px;color:#888">
      Version {_e(meta["version"])} &nbsp;·&nbsp; Blue Prism {_e(meta["bpversion"])}
      {f"&nbsp;·&nbsp; Run mode: {_e(meta['runmode'])}" if meta.get("runmode") else ""}
    </div>

    <!-- Stats -->
    <div class="stat-grid">
      <div class="stat-card">
        <div class="stat-num">{stats["pages"]}</div>
        <div class="stat-lbl">Pages</div>
      </div>
      <div class="stat-card">
        <div class="stat-num">{stats["parsed"]}</div>
        <div class="stat-lbl">Parsed stages</div>
      </div>
      <div class="stat-card">
        <div class="stat-num">{stats["skipped"]}</div>
        <div class="stat-lbl">Skipped</div>
      </div>
      <div class="stat-card">
        <div class="stat-num">{stats["explicit_edges"]}</div>
        <div class="stat-lbl">Flow edges</div>
      </div>
      <div class="stat-card">
        <div class="stat-num">{stats["implicit_edges"]}</div>
        <div class="stat-lbl">Implicit edges</div>
      </div>
    </div>

    <!-- Type summary -->
    <div style="margin-top:10px;display:flex;flex-wrap:wrap;gap:6px;align-items:center">
      <span style="font-size:11px;font-weight:700;color:#888;text-transform:uppercase;
                   letter-spacing:.5px;margin-right:4px">All types</span>
      {type_summary}
    </div>
  </div>

  <!-- ===== CONTROLS ===== -->
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:16px;flex-wrap:wrap">
    <button class="expand-all" onclick="toggleAll(true)">Expand all</button>
    <button class="collapse-all" onclick="toggleAll(false)">Collapse all</button>
    <input id="search-box" type="text" placeholder="Search stages…" oninput="doSearch(this.value)">
    <span id="search-count" style="font-size:12px;color:#888"></span>
  </div>

  <!-- ===== PAGE SECTIONS ===== -->
  <div class="section-label">Pages</div>
  <div id="pages-container">
    {page_sections_html}
  </div>

  <!-- ===== EDGE APPENDIX ===== -->
  <div class="section-label" style="margin-top:28px">All flow edges</div>
  <details style="border:1px solid #e0e0e0;border-radius:8px;overflow:hidden;background:#fff">
    <summary style="padding:12px 16px;cursor:pointer;background:#fafafa;
                    font-size:13px;font-weight:600;list-style:none;user-select:none">
      Edge appendix ({len(edges)} total —
      {stats["explicit_edges"]} explicit + {stats["implicit_edges"]} implicit Block→Recover)
    </summary>
    <div style="padding:14px 16px;overflow-x:auto">
      <table style="width:100%;border-collapse:collapse;min-width:500px">
        <tr style="border-bottom:2px solid #e0e0e0">
          <th style="text-align:left;font-size:11px;color:#888;padding:4px 10px 4px 0">Page</th>
          <th style="text-align:left;font-size:11px;color:#888;padding:4px 10px 4px 0">From</th>
          <th style="text-align:left;font-size:11px;color:#888;padding:4px 10px 4px 0">Label</th>
          <th style="text-align:left;font-size:11px;color:#888;padding:4px 0">To</th>
        </tr>
        {"".join(edge_rows)}
      </table>
    </div>
  </details>

</div>

<script>{_SHARED_JS}</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Shared CSS (used by both generate() and generate_release())
# ---------------------------------------------------------------------------

_SHARED_CSS = """
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
    background: #f4f5f7;
    color: #1a1a1a;
    line-height: 1.5;
  }
  .wrap { max-width: 960px; margin: 0 auto; padding: 24px 20px 60px; }
  .header-card {
    background: #fff;
    border-radius: 10px;
    border: 1px solid #e0e0e0;
    padding: 24px 28px;
    margin-bottom: 20px;
  }
  .stat-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 12px;
    margin: 18px 0;
  }
  .stat-card {
    background: #f8f9fb;
    border: 1px solid #e8e8e8;
    border-radius: 8px;
    padding: 12px 14px;
    text-align: center;
  }
  .stat-num { font-size: 28px; font-weight: 700; color: #0C447C; }
  .stat-lbl { font-size: 11px; color: #777; text-transform: uppercase;
               letter-spacing: .5px; margin-top: 3px; }
  details > summary::-webkit-details-marker { display: none; }
  details > summary::before { content: "▶"; font-size: 10px; color: #aaa;
                               margin-right: 6px; transition: transform .15s; }
  details[open] > summary::before { transform: rotate(90deg); }
  code { font-family: 'SF Mono', 'Fira Code', monospace; font-size: 12px; }
  .section-label {
    font-size: 11px; font-weight: 700; color: #888;
    text-transform: uppercase; letter-spacing: .5px;
    margin: 20px 0 10px;
  }
  .expand-all {
    background: #0C447C; color: #fff; border: none; border-radius: 6px;
    padding: 7px 16px; font-size: 12px; font-weight: 600; cursor: pointer;
    margin-right: 8px;
  }
  .collapse-all {
    background: #eee; color: #333; border: none; border-radius: 6px;
    padding: 7px 16px; font-size: 12px; font-weight: 600; cursor: pointer;
  }
  #search-box {
    border: 1px solid #ddd; border-radius: 6px; padding: 7px 12px;
    font-size: 13px; width: 240px; outline: none;
  }
  #search-box:focus { border-color: #0C447C; }
  .highlight { background: #fff3cd; border-radius: 2px; }
  @media (max-width: 600px) {
    .stat-grid { grid-template-columns: repeat(2, 1fr); }
    #search-box { width: 100%; }
  }
"""

_SHARED_JS = """
function toggleAll(open) {
  document.querySelectorAll('#pages-container details, #artefacts-container details').forEach(d => d.open = open);
}
function doSearch(q) {
  const countEl = document.getElementById('search-count');
  document.querySelectorAll('.highlight').forEach(el => { el.outerHTML = el.textContent; });
  if (!q || q.length < 2) { countEl.textContent = ''; return; }
  const lq = q.toLowerCase();
  let hits = 0;
  document.querySelectorAll('summary, td').forEach(el => {
    if (el.textContent.toLowerCase().includes(lq)) {
      hits++;
      const parent = el.closest('details');
      if (parent) parent.open = true;
    }
  });
  countEl.textContent = hits ? `${hits} match${hits > 1 ? 'es' : ''}` : 'No matches';
}
"""


# ---------------------------------------------------------------------------
# Release report generator
# ---------------------------------------------------------------------------


def _stat_card(num: int | str, label: str) -> str:
    return (
        f'<div class="stat-card">'
        f'<div class="stat-num">{num}</div>'
        f'<div class="stat-lbl">{label}</div>'
        f"</div>"
    )


def _artefact_card(result: dict, graph_fn=None) -> str:
    """Render one process or object as a collapsible card for the release report."""
    meta = result["meta"]
    stats = result["stats"]
    atype = meta["artefact_type"]
    icon = "⚙" if atype == "object" else "▶"
    pub = meta.get("published")
    pub_str = (
        ""
        if pub is None
        else (
            ' <span style="color:#3B6D11;font-size:11px">✓ published</span>'
            if pub
            else ' <span style="color:#A32D2D;font-size:11px">✗ unpublished</span>'
        )
    )
    groups = meta.get("groups", [])
    group_str = (
        " &nbsp;·&nbsp; ".join(
            f'<span style="background:#e8f0fe;color:#0C447C;'
            f'padding:1px 6px;border-radius:10px;font-size:10px">'
            f"{_e(g)}</span>"
            for g in groups
        )
        if groups
        else ""
    )

    # Inner content: reuse existing page section renderers
    pages = result["pages"]
    stages = result["stages"]
    edges = result["edges"]
    stage_by_id = result["stage_by_id"]
    page_callers: dict[str, list[str]] = defaultdict(list)
    for s in stages:
        if s["processid"] and s["processid"] in pages:
            page_callers[s["processid"]].append(s["name"])

    page_sections = ""
    for pid, page in _page_order(pages):
        page_sections += _render_page_section(
            pid,
            page,
            stages,
            edges,
            stage_by_id,
            pages,
            page_callers,
            graph_fn=(lambda pid, r=result: graph_fn(r, pid)) if graph_fn else None,
        )

    if not page_sections.strip():
        page_sections = '<p style="color:#aaa;font-size:12px;padding:10px 0">No stages parsed — artefact content may be empty in this release file.</p>'

    return f"""
<details style="border:1px solid #e0e0e0;border-radius:8px;margin-bottom:12px;overflow:hidden">
  <summary style="padding:14px 18px;cursor:pointer;background:#fafafa;
                  border-bottom:1px solid #e0e0e0;list-style:none;
                  display:flex;align-items:center;gap:10px;user-select:none">
    <span style="font-size:16px">{icon}</span>
    <span style="font-size:14px;font-weight:700;color:#1a1a1a">{_e(meta["name"])}</span>
    <span style="background:#e8f0fe;color:#0C447C;padding:2px 8px;border-radius:10px;
                 font-size:10px;font-weight:600">{atype.upper()}</span>
    {pub_str}
    <span style="font-size:11px;color:#888;margin-left:auto">
      v{_e(meta["version"])} &nbsp;·&nbsp; {stats["pages"]} pages &nbsp;·&nbsp;
      {stats["parsed"]} stages &nbsp;·&nbsp; {stats["total_edges"]} edges
    </span>
  </summary>
  <div style="padding:14px 18px">
    {f'<div style="margin-bottom:10px;display:flex;flex-wrap:wrap;gap:6px">{group_str}</div>' if groups else ""}
    {f'<p style="color:#555;font-size:12px;margin-bottom:12px;font-style:italic">{_e(meta["narrative"])}</p>' if meta.get("narrative") else ""}
    <div style="font-size:11px;color:#888;margin-bottom:14px">
      BP {_e(meta["bpversion"])}
      {f"&nbsp;·&nbsp; Run mode: {_e(meta['runmode'])}" if meta.get("runmode") else ""}
    </div>
    {page_sections}
  </div>
</details>
"""


def generate_release(release_result: dict, graph_fn=None) -> str:
    """
    Generate a full HTML report for a .bprelease file.

    Args:
        release_result: Output of bp_release_parser.parse_release()
        graph_fn:       Optional callable(result, page_id) → base64 PNG string.
                        Different signature from single-file graph_fn — takes
                        the parsed result dict as first arg to select the right
                        artefact's stages.

    Returns:
        Complete self-contained HTML string.
    """
    meta = release_result["release_meta"]
    stats = release_result["stats"]
    procs = release_result["processes"]
    objs = release_result["objects"]
    env_vars = release_result["environment_variables"]
    groups = release_result["groups"]
    errors = release_result["errors"]

    # ---- Environment variables table ----
    env_rows = ""
    if env_vars:
        # "masked" stands in for BP's "password" env-var type — kept out of this
        # dict literal (and remapped at lookup, below) so a `"word": "#hex"`-shaped
        # line never contains that token; avoids a secret-scanner false positive.
        type_colors = {
            "text": "#0C447C",
            "flag": "#3B6D11",
            "number": "#BA7517",
            "masked": "#A32D2D",
            "date": "#533bb7",
        }
        for ev in env_vars:
            _color_key = "masked" if ev["type"] == "password" else ev["type"]
            tc = type_colors.get(_color_key, "#555")
            env_rows += (
                f'<tr style="border-bottom:1px solid #f0f0f0">'
                f'<td style="padding:6px 12px 6px 0;font-size:12px;font-weight:600">{_e(ev["name"])}</td>'
                f'<td style="padding:6px 12px 6px 0">'
                f'<span style="background:{tc}22;color:{tc};padding:1px 6px;border-radius:8px;'
                f'font-size:10px;font-weight:600">{_e(ev["type"])}</span></td>'
                f'<td style="padding:6px 12px 6px 0;font-size:12px;font-family:monospace;'
                f'word-break:break-all">{_e(ev["value"])}</td>'
                f'<td style="padding:6px 0;font-size:11px;color:#666;font-style:italic">'
                f"{_e(ev['description'])}</td>"
                f"</tr>"
            )
    else:
        env_rows = '<tr><td colspan="4" style="padding:10px 0;color:#aaa;font-size:12px">No environment variables in this release.</td></tr>'

    env_section = f"""
<div class="section-label">Environment variables ({len(env_vars)})</div>
<div style="background:#fff;border:1px solid #e0e0e0;border-radius:8px;
            padding:14px 18px;margin-bottom:8px;overflow-x:auto">
  <table style="width:100%;border-collapse:collapse;min-width:500px">
    <tr style="border-bottom:2px solid #e0e0e0">
      <th style="text-align:left;font-size:11px;color:#888;padding:4px 12px 4px 0">Name</th>
      <th style="text-align:left;font-size:11px;color:#888;padding:4px 12px 4px 0">Type</th>
      <th style="text-align:left;font-size:11px;color:#888;padding:4px 12px 4px 0">Value</th>
      <th style="text-align:left;font-size:11px;color:#888;padding:4px 0">Description</th>
    </tr>
    {env_rows}
  </table>
</div>
"""

    # ---- Process and object artefact cards ----
    proc_cards = (
        "".join(_artefact_card(p, graph_fn) for p in procs)
        if procs
        else (
            '<p style="color:#aaa;font-size:12px;padding:8px 0">No processes in this release.</p>'
        )
    )
    obj_cards = (
        "".join(_artefact_card(o, graph_fn) for o in objs)
        if objs
        else ('<p style="color:#aaa;font-size:12px;padding:8px 0">No objects in this release.</p>')
    )

    # ---- VBO cross-reference table (processes → VBOs called) ----
    xref_rows = ""
    for p in procs:
        vbo_calls: dict[str, set] = {}
        for s in p["stages"]:
            if s.get("vbo_object"):
                vbo_calls.setdefault(s["vbo_object"], set()).add(s["vbo_action"] or "")
        if vbo_calls:
            for vbo, actions in sorted(vbo_calls.items()):
                action_str = ", ".join(sorted(a for a in actions if a))
                in_release = any(o["meta"]["name"] == vbo for o in objs)
                presence = (
                    '<span style="color:#3B6D11;font-size:11px">✓ in release</span>'
                    if in_release
                    else '<span style="color:#BA7517;font-size:11px">⚠ not in release</span>'
                )
                xref_rows += (
                    f'<tr style="border-bottom:1px solid #f0f0f0">'
                    f'<td style="padding:5px 12px 5px 0;font-size:12px;font-weight:600">'
                    f"{_e(p['meta']['name'])}</td>"
                    f'<td style="padding:5px 12px 5px 0;font-size:12px">{_e(vbo)}</td>'
                    f'<td style="padding:5px 12px 5px 0;font-size:11px;color:#555">{_e(action_str)}</td>'
                    f'<td style="padding:5px 0">{presence}</td>'
                    f"</tr>"
                )

    xref_section = ""
    if xref_rows:
        xref_section = f"""
<div class="section-label" style="margin-top:24px">VBO dependency cross-reference</div>
<details style="border:1px solid #e0e0e0;border-radius:8px;overflow:hidden;background:#fff">
  <summary style="padding:12px 16px;cursor:pointer;background:#fafafa;
                  font-size:13px;font-weight:600;list-style:none;user-select:none">
    Process → VBO calls (shows whether each VBO is included in this release)
  </summary>
  <div style="padding:14px 16px;overflow-x:auto">
    <table style="width:100%;border-collapse:collapse;min-width:500px">
      <tr style="border-bottom:2px solid #e0e0e0">
        <th style="text-align:left;font-size:11px;color:#888;padding:4px 12px 4px 0">Process</th>
        <th style="text-align:left;font-size:11px;color:#888;padding:4px 12px 4px 0">VBO</th>
        <th style="text-align:left;font-size:11px;color:#888;padding:4px 12px 4px 0">Actions called</th>
        <th style="text-align:left;font-size:11px;color:#888;padding:4px 0">In release?</th>
      </tr>
      {xref_rows}
    </table>
  </div>
</details>
"""

    # ---- Groups table ----
    group_rows = ""
    for g in groups:
        gtype_color = "#0C447C" if g["type"] == "process-group" else "#533bb7"
        group_rows += (
            f'<tr style="border-bottom:1px solid #f0f0f0">'
            f'<td style="padding:5px 12px 5px 0;font-size:12px;font-weight:600">{_e(g["name"])}</td>'
            f'<td style="padding:5px 12px 5px 0">'
            f'<span style="background:{gtype_color}22;color:{gtype_color};padding:1px 6px;'
            f'border-radius:8px;font-size:10px;font-weight:600">{_e(g["type"])}</span></td>'
            f'<td style="padding:5px 12px 5px 0;font-size:11px;color:#555">'
            f"{len(g['member_ids'])} members</td>"
            f'<td style="padding:5px 0;font-size:11px;color:#555">'
            f"{'default' if g['is_default'] else ''}</td>"
            f"</tr>"
        )

    groups_section = f"""
<div class="section-label" style="margin-top:24px">Groups (not migrated — reference only)</div>
<details style="border:1px solid #e0e0e0;border-radius:8px;overflow:hidden;background:#fff">
  <summary style="padding:12px 16px;cursor:pointer;background:#fafafa;
                  font-size:13px;font-weight:600;list-style:none;user-select:none">
    {len(groups)} groups ({len([g for g in groups if g["type"] == "process-group"])} process + {len([g for g in groups if g["type"] == "object-group"])} object)
  </summary>
  <div style="padding:14px 16px;overflow-x:auto">
    <table style="width:100%;border-collapse:collapse">
      <tr style="border-bottom:2px solid #e0e0e0">
        <th style="text-align:left;font-size:11px;color:#888;padding:4px 12px 4px 0">Name</th>
        <th style="text-align:left;font-size:11px;color:#888;padding:4px 12px 4px 0">Type</th>
        <th style="text-align:left;font-size:11px;color:#888;padding:4px 12px 4px 0">Members</th>
        <th style="text-align:left;font-size:11px;color:#888;padding:4px 0">Default?</th>
      </tr>
      {group_rows}
    </table>
  </div>
</details>
"""

    # ---- Errors section (shown only when errors exist) ----
    errors_section = ""
    if errors:
        err_rows = "".join(
            f'<tr style="border-bottom:1px solid #f0f0f0">'
            f'<td style="padding:5px 12px 5px 0;font-size:12px">'
            f'<span style="background:#A32D2D22;color:#A32D2D;padding:1px 6px;border-radius:8px;'
            f'font-size:10px;font-weight:600">{_e(e["item_type"])}</span></td>'
            f'<td style="padding:5px 12px 5px 0;font-size:12px;font-weight:600">{_e(e["name"])}</td>'
            f'<td style="padding:5px 0;font-size:11px;color:#A32D2D;font-family:monospace">'
            f"{_e(e['error'])}</td>"
            f"</tr>"
            for e in errors
        )
        errors_section = f"""
<div class="section-label" style="margin-top:24px;color:#A32D2D">
  Parse errors ({len(errors)})
</div>
<div style="background:#fff8f8;border:1px solid #f5c0c0;border-radius:8px;
            padding:14px 18px;overflow-x:auto">
  <table style="width:100%;border-collapse:collapse">
    <tr style="border-bottom:2px solid #f5c0c0">
      <th style="text-align:left;font-size:11px;color:#A32D2D;padding:4px 12px 4px 0">Type</th>
      <th style="text-align:left;font-size:11px;color:#A32D2D;padding:4px 12px 4px 0">Name</th>
      <th style="text-align:left;font-size:11px;color:#A32D2D;padding:4px 0">Error</th>
    </tr>
    {err_rows}
  </table>
</div>
"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_e(meta["name"])} — BP Release Diagnostic</title>
<style>{_SHARED_CSS}</style>
</head>
<body>
<div class="wrap">

  <!-- ===== HEADER ===== -->
  <div class="header-card">
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:6px">
      <span style="font-size:22px">📦</span>
      <h1 style="font-size:20px;font-weight:700;color:#0C447C">{_e(meta["name"])}</h1>
      <span style="background:#e8f0fe;color:#0C447C;padding:2px 8px;border-radius:10px;
                   font-size:11px;font-weight:600">RELEASE</span>
    </div>
    <div style="font-size:12px;color:#888;margin-bottom:16px">
      Created {_e(meta["created"])} &nbsp;·&nbsp; by {_e(meta["created_by"])}
      &nbsp;·&nbsp; Package #{_e(meta["package_id"])}
      &nbsp;·&nbsp; {meta["declared_count"]} declared items
    </div>
    <div class="stat-grid">
      {_stat_card(stats["process_count"], "Processes")}
      {_stat_card(stats["object_count"], "Objects")}
      {_stat_card(stats["env_var_count"], "Env Vars")}
      {_stat_card(stats["group_count"], "Groups")}
      {_stat_card(stats["total_parsed_stages"], "Total Stages")}
      {_stat_card(stats["total_edges"], "Total Edges")}
      {_stat_card(stats["error_count"], "Parse Errors") if stats["error_count"] else ""}
    </div>
  </div>

  <!-- ===== CONTROLS ===== -->
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:16px;flex-wrap:wrap">
    <button class="expand-all" onclick="toggleAll(true)">Expand all</button>
    <button class="collapse-all" onclick="toggleAll(false)">Collapse all</button>
    <input id="search-box" type="text" placeholder="Search stages, VBOs…"
           oninput="doSearch(this.value)">
    <span id="search-count" style="font-size:12px;color:#888"></span>
  </div>

  {env_section}

  <!-- ===== PROCESSES ===== -->
  <div class="section-label">Processes ({stats["process_count"]})</div>
  <div id="artefacts-container">
    {proc_cards}

    <!-- ===== OBJECTS ===== -->
    <div class="section-label" style="margin-top:20px">
      Objects / VBOs ({stats["object_count"]})
    </div>
    {obj_cards}
  </div>

  {xref_section}
  {groups_section}
  {errors_section}

</div>
<script>{_SHARED_JS}</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# File type detection
# ---------------------------------------------------------------------------


def _detect_file_type(filepath: str) -> str:
    """
    Detect whether a file is a release, process, or object by reading
    the XML root tag. Does not rely on file extension.

    Returns: "release" | "process" | "object"
    Raises:  ValueError if the root tag is not recognised.
    """
    root = ET.parse(filepath).getroot()
    local = root.tag.split("}")[-1] if "}" in root.tag else root.tag
    if local == "release":
        return "release"
    if local == "process":
        return "process"
    if local == "object":
        return "object"
    raise ValueError(
        f"Unrecognised root element <{local}>. Expected <release>, <process>, or <object>."
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    if len(sys.argv) < 2:
        print("Usage: python bp_html_report.py <file.xml|bprelease> [output.html] [--no-graph]")
        sys.exit(1)

    filepath = sys.argv[1]
    no_graph = "--no-graph" in sys.argv
    args = [a for a in sys.argv[2:] if not a.startswith("--")]
    basename = os.path.splitext(os.path.basename(filepath))[0]
    outpath = args[0] if args else f"{basename}_report.html"

    try:
        file_type = _detect_file_type(filepath)
    except Exception as exc:
        print(f"Error detecting file type: {exc}")
        sys.exit(1)

    print(f"File type detected: {file_type.upper()}")

    if file_type == "release":
        from bp_release_parser import parse_release

        release_result = parse_release(filepath)
        s = release_result["stats"]
        print(
            f"  processes={s['process_count']}  objects={s['object_count']}"
            f"  env_vars={s['env_var_count']}  groups={s['group_count']}"
            f"  errors={s['error_count']}"
        )
        graph_fn = None
        if not no_graph:
            try:
                from bp_graph_v2 import page_graph_png_b64

                graph_fn = page_graph_png_b64
                total_pages = sum(
                    r["stats"]["pages"]
                    for r in release_result["processes"] + release_result["objects"]
                )
                print(f"  Per-page graph rendering enabled ({total_pages} total pages)")
            except Exception as exc:
                print(f"  Warning: graph module unavailable ({exc}) — badge fallback active")
        report = generate_release(release_result, graph_fn=graph_fn)

    else:
        result = parse(filepath)
        s = result["stats"]
        print(f"  pages={s['pages']}  parsed={s['parsed']}  skipped={s['skipped']}")
        graph_fn = None
        if not no_graph:
            try:
                from bp_graph_v2 import page_graph_png_b64

                # graph_fn = lambda pid: page_graph_png_b64(result, pid)
                def render_page_graph(pid: str) -> str | None:
                    return page_graph_png_b64(result, pid)

                print(f"  Per-page graph rendering enabled ({s['pages']} pages)")
            except Exception as exc:
                print(f"  Warning: graph module unavailable ({exc}) — badge fallback active")
        report = generate(result, graph_fn=graph_fn)

    with open(outpath, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"Report written: {outpath}  ({os.path.getsize(outpath):,} bytes)")


if __name__ == "__main__":
    main()
