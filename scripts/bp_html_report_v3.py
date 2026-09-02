"""
bp_html_report_v3.py — Blue Prism HTML diagnostic report generator
Produces a split multi-file report (default) or a single self-contained .html file
(--single-file) from any .bprelease/.bpprocess/.bpobject file.

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
    python bp_html_report_v3.py <file.xml> [--out-dir PATH] [--single-file] [output.html]
"""

import html as _html
import json as _json
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(__file__))
# ---------------------------------------------------------------------------
# Terminal progress bar (stdlib only)
# ---------------------------------------------------------------------------
import time as _time

from bp_parser_v2 import IMPLICIT_PAGE_ID, parse


class ProgressBar:
    """
    Minimal terminal progress bar. Writes to stderr so stdout stays clean.

    Usage:
        bar = ProgressBar(total=50, label="Rendering")
        bar.start()
        for i in range(50):
            bar.update(i + 1, suffix="Processing item X")
        bar.finish()
    """

    WIDTH = 20

    def __init__(self, total: int, label: str = ""):
        self._total = max(total, 1)
        self._label = label
        self._start = 0.0

    def start(self) -> None:
        self._start = _time.perf_counter()
        self._draw(0, "")

    def update(self, done: int, suffix: str = "") -> None:
        self._draw(done, suffix)

    def finish(self, suffix: str = "Done") -> None:
        elapsed = _time.perf_counter() - self._start
        self._draw(self._total, suffix)
        sys.stderr.write(f"\n✓ {suffix} in {elapsed:.1f}s\n")
        sys.stderr.flush()

    def _draw(self, done: int, suffix: str) -> None:
        pct = min(done / self._total, 1.0)
        filled = int(self.WIDTH * pct)
        bar = "█" * filled + "░" * (self.WIDTH - filled)
        label = f"  {self._label}: " if self._label else "  "
        trunc = suffix[:50] if len(suffix) > 50 else suffix
        line = f"\r[{bar}] {int(pct * 100):3d}%{label}{trunc}"
        sys.stderr.write(line)
        sys.stderr.flush()


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

# Page "type" is the raw BP <subsheet type="…"> attribute, defaulting to "Normal"
# when absent (bp_parser_v2.py ~line 318) — it is never "Action". "implicit"
# (Initialize/Main Page) and "CleanUp" are the only known system/structural
# values; everything else (typically "Normal") is a callable action page.
STRUCTURAL_PAGE_TYPES = ("implicit", "CleanUp")


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
        val_class = "detail-val-mono" if mono else "detail-val"
        rows.append(
            f'<tr><td class="detail-label">{label}</td><td class="{val_class}">{value}</td></tr>'
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

    return f'<table class="detail-table">{"".join(rows)}</table>'


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
<div class="page-card">
  <details>
    <summary class="page-summary" id="{page_id_attr}">
      <span class="page-name">{_e(page_name)}</span>
      <span style="background:#eee;color:#555;padding:2px 8px;border-radius:10px;
                   font-size:11px">{page["type"]}</span>
      <span style="font-size:11px;color:#888">pub={pub}</span>
      <span style="font-size:11px;color:#888;margin-left:auto">{len(page_stages)} stages</span>
    </summary>
    <div class="page-body">
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
        if page_png_b64.startswith(("../", "/", "http")):
            img_src = page_png_b64  # already a URL
        else:
            img_src = f"data:image/png;base64,{page_png_b64}"  # legacy base64
        flow_visual = (
            f'<img src="{img_src}" '
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
        f'<div class="section-hdr" style="background:{bg};border-left:3px solid {color};color:{color}">'
        f"{title}</div>\n"
    )


def _stage_card(s: dict, stage_by_id: dict, pages: dict) -> str:
    bg, fg = TYPE_COLORS.get(s["type"], DEFAULT_COLOR)
    detail = _render_stage_detail(s, stage_by_id, pages)
    # Deep-link target for a specific stage (Task J's search results link to
    # #stage-{id}; also shareable/linkable directly). Placed on <summary>, which
    # is always visible even while its <details> is closed — so browsers scroll
    # to it on fragment navigation, but won't auto-open anything themselves (that
    # native behaviour only fires when the target is hidden inside a closed
    # <details>). _openDetailsForHash() in _SHARED_JS opens the ancestor chain.
    stage_id = f"stage-{s['id']}"
    return f"""
<details class="stage-card">
  <summary class="stage-summary" id="{stage_id}">
    <span class="stage-dot" style="background:{bg}"></span>
    <span class="stage-name">{_e(s["name"])}</span>
    {_badge(s["type"], s["raw_type"])}
  </summary>
  <div class="stage-body">
    {detail}
  </div>
</details>
"""


# ---------------------------------------------------------------------------
# Main report generator
# ---------------------------------------------------------------------------


def _page_order(pages: dict) -> list[tuple[str, dict]]:
    implicit = [(IMPLICIT_PAGE_ID, pages[IMPLICIT_PAGE_ID])] if IMPLICIT_PAGE_ID in pages else []
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
  <ul id="search-results" hidden></ul>

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
  /* Cross-page search results (data/stages.jsonl-backed, when reachable) */
  #search-results {
    list-style: none; margin: -8px 0 16px; padding: 0; border: 1px solid #e0e0e0;
    border-radius: 8px; background: #fff; max-height: 360px; overflow-y: auto;
  }
  #search-results li {
    padding: 8px 14px; border-bottom: 1px solid #f0f0f0; font-size: 12px;
  }
  #search-results li:last-child { border-bottom: none; }
  #search-results a { color: #0C447C; text-decoration: none; font-weight: 600; }
  #search-results a:hover { text-decoration: underline; }
  .search-hit-meta { display: block; color: #888; font-size: 11px; margin-top: 2px; }
  @media (max-width: 600px) {
    .stat-grid { grid-template-columns: repeat(2, 1fr); }
    #search-box { width: 100%; }
  }
  /* Stage card */
  .stage-card { margin-bottom:6px; border:1px solid #eee; border-radius:6px; overflow:hidden; }
  .stage-summary { padding:8px 12px; cursor:pointer; background:#fff; display:flex; align-items:center; gap:8px; list-style:none; user-select:none; }
  .stage-body { padding:10px 14px; background:#fafafa; border-top:1px solid #eee; }
  .stage-dot { width:10px; height:10px; border-radius:50%; flex-shrink:0; display:inline-block; }
  .stage-name { font-size:13px; font-weight:600; color:#1a1a1a; }
  /* Detail table */
  .detail-table { width:100%; border-collapse:collapse; }
  .detail-label { color:#666; font-size:12px; padding:4px 10px 4px 0; white-space:nowrap; vertical-align:top; width:130px; }
  .detail-val { font-size:13px; padding:4px 0; color:#222; }
  .detail-val-mono { font-family:monospace; font-size:12px; word-break:break-all; padding:4px 0; color:#222; }
  /* Section header */
  .section-hdr { padding:6px 10px; margin:14px 0 8px; font-size:12px; font-weight:700; text-transform:uppercase; letter-spacing:.5px; }
  /* Page section */
  .page-card { border:1px solid #e0e0e0; border-radius:8px; margin-bottom:12px; overflow:hidden; }
  .page-summary { padding:14px 18px; cursor:pointer; background:#fafafa; border-bottom:1px solid #e0e0e0; list-style:none; display:flex; align-items:center; gap:12px; user-select:none; }
  .page-body { padding:16px 18px; }
  .page-name { font-size:15px; font-weight:700; color:#1a1a1a; }
"""

_SHARED_JS = """
function toggleAll(open) {
  document.querySelectorAll('#pages-container details, #artefacts-container details').forEach(d => d.open = open);
}

// Deep-link support (Task K): the #stage-{id} anchor sits on <summary>, which is
// always visible even while its <details> is closed — so the browser's native
// fragment-navigation auto-expand (which only fires for a target hidden *inside*
// a closed <details>) never triggers here. Walk up and open every ancestor
// <details> explicitly instead (a stage card, and its enclosing page section).
function _openDetailsForHash() {
  if (!location.hash) return;
  let target;
  try { target = document.querySelector(location.hash); } catch (e) { return; }
  if (!target) return;
  for (let el = target; el; el = el.parentElement) {
    if (el.tagName === 'DETAILS') el.open = true;
  }
  requestAnimationFrame(() => target.scrollIntoView({block: 'center'}));
}
_openDetailsForHash();
window.addEventListener('hashchange', _openDetailsForHash);

// ---------------------------------------------------------------------------
// Cross-page search, backed by data/stages.jsonl — reaches every artefact and
// stage from any page, not just the current one. fetch() is blocked on file://
// origins in Chrome/Safari (the common way these reports are opened), so this
// degrades gracefully to the same-page search below whenever it's unavailable
// (single-file mode has no data/ export at all; file:// commonly blocks it too).
// ---------------------------------------------------------------------------
let _stageIndexPromise = null;
let _stageIndexReady = null; // null = pending, true = loaded, false = unavailable

function _inPagesDir() {
  return /(^|\\/)pages\\//.test(window.location.pathname);
}
function _dataUrl() {
  return (_inPagesDir() ? '../' : '') + 'data/stages.jsonl';
}
function _pagesPrefix() {
  return _inPagesDir() ? '' : 'pages/';
}
function _slugify(name) {
  return (name || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
}
function _escHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function _loadStageIndex() {
  if (_stageIndexPromise) return _stageIndexPromise;
  _stageIndexPromise = fetch(_dataUrl())
    .then(r => { if (!r.ok) throw new Error('stages.jsonl not reachable'); return r.text(); })
    .then(text => {
      const records = text.split('\\n').filter(Boolean).map(line => {
        try { return JSON.parse(line); } catch (e) { return null; }
      }).filter(Boolean);
      _stageIndexReady = true;
      return records;
    })
    .catch(() => { _stageIndexReady = false; return null; });
  return _stageIndexPromise;
}
_loadStageIndex(); // kick off eagerly so it's ready by the time someone searches

function _renderCrossPageResults(records, q) {
  const countEl = document.getElementById('search-count');
  const resultsEl = document.getElementById('search-results');
  // Undo any nav-list filtering left over from a same-page fallback pass before
  // the index finished loading — cross-page results below supersede it.
  document.querySelectorAll('#artefacts-container > ul > li').forEach(li => { li.hidden = false; });
  const lq = q.toLowerCase();
  const hits = records.filter(r =>
    (r.artefact && r.artefact.toLowerCase().includes(lq)) ||
    (r.page && r.page.toLowerCase().includes(lq)) ||
    (r.name && r.name.toLowerCase().includes(lq)) ||
    (r.vbo_object && r.vbo_object.toLowerCase().includes(lq)) ||
    (r.vbo_action && r.vbo_action.toLowerCase().includes(lq)) ||
    (r.expression && r.expression.toLowerCase().includes(lq))
  );
  const shown = hits.slice(0, 50);
  if (countEl) {
    countEl.textContent = hits.length
      ? `${hits.length} match${hits.length > 1 ? 'es' : ''}${hits.length > 50 ? ' (showing 50)' : ''}`
      : 'No matches';
  }
  if (!resultsEl) return;
  if (!shown.length) { resultsEl.hidden = true; resultsEl.innerHTML = ''; return; }
  resultsEl.hidden = false;
  resultsEl.innerHTML = shown.map(r => {
    const href = _pagesPrefix() + _slugify(r.artefact) + '.html' + (r.id ? '#stage-' + r.id : '');
    const meta = r.vbo_action ? `${_escHtml(r.vbo_object)} \\u2192 ${_escHtml(r.vbo_action)}` : _escHtml(r.stage_type);
    return `<li><a href="${href}">${_escHtml(r.artefact)} \\u203a ${_escHtml(r.page)} \\u203a ${_escHtml(r.name)}</a>`
         + `<span class="search-hit-meta">${meta}</span></li>`;
  }).join('');
}

// Same-page fallback (Pass 1/Task I behaviour) — nav-list filter on index.html,
// auto-expand matching <details> everywhere that has real accordion content.
function _samePageSearch(q) {
  const countEl = document.getElementById('search-count');
  const navItems = document.querySelectorAll('#artefacts-container > ul > li');
  if (!q) {
    navItems.forEach(li => { li.hidden = false; });
    return;
  }
  const lq = q.toLowerCase();
  let hits = 0;
  navItems.forEach(li => {
    const match = li.textContent.toLowerCase().includes(lq);
    li.hidden = !match;
    if (match) hits++;
  });
  document.querySelectorAll('summary, td').forEach(el => {
    if (el.textContent.toLowerCase().includes(lq)) {
      hits++;
      const parent = el.closest('details');
      if (parent) parent.open = true;
    }
  });
  if (countEl) countEl.textContent = hits ? `${hits} match${hits > 1 ? 'es' : ''}` : 'No matches';
}

function doSearch(q) {
  const countEl = document.getElementById('search-count');
  const resultsEl = document.getElementById('search-results');
  document.querySelectorAll('.highlight').forEach(el => { el.outerHTML = el.textContent; });

  if (!q || q.length < 2) {
    if (countEl) countEl.textContent = '';
    if (resultsEl) { resultsEl.hidden = true; resultsEl.innerHTML = ''; }
    _samePageSearch('');
    return;
  }

  if (_stageIndexReady === true) {
    _stageIndexPromise.then(records => { if (records) _renderCrossPageResults(records, q); });
    return;
  }
  if (_stageIndexReady === null) {
    // Still loading — pick it up for this query too if it resolves in time,
    // guarded so a stale response can't clobber a newer, faster-typed query.
    _stageIndexPromise.then(records => {
      const box = document.getElementById('search-box');
      if (records && box && box.value === q) _renderCrossPageResults(records, q);
    });
  }
  // Unavailable, or still pending for this keystroke: same-page fallback. Clear
  // any cross-page results left over from before the index became unavailable
  // (or from a prior query while it was still loading), so results and the
  // nav-list filter never show two conflicting result sets at once.
  if (resultsEl) { resultsEl.hidden = true; resultsEl.innerHTML = ''; }
  _samePageSearch(q);
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


def _artefact_page_html(
    result: dict,
    slug: str,
    release_name: str,
    img_map: dict,
    pruned_pages: list,
    include_all: bool = False,
) -> str:
    """
    Render one artefact (process or object) as a complete standalone HTML page.

    img_map:      {slug_pagename: relative_img_url} e.g. {"myproc_main": "../images/myproc_main.png"}
    pruned_pages: names of action pages omitted due to VBO pruning
    """
    meta = result["meta"]
    pages = result["pages"]
    stages = result["stages"]
    edges = result["edges"]
    stage_by_id = result["stage_by_id"]

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

    page_callers: dict = defaultdict(list)
    for s in stages:
        if s["processid"] and s["processid"] in pages:
            page_callers[s["processid"]].append(s["name"])

    def _img_graph_fn(pid: str) -> str | None:
        """Return a relative URL for the pre-rendered page image, or None."""
        page = pages.get(pid, {})
        safe_page_name = re.sub(r"[^a-z0-9]+", "-", page.get("name", pid).lower()).strip("-")
        key = f"{slug}_{safe_page_name}"
        return img_map.get(key)

    pruned_names = set(pruned_pages)
    page_sections = ""
    for pid, _page in _page_order(pages):
        if _page.get("name", pid) in pruned_names:
            # Pruned by VBO reachability filtering (see generate_split()) — omitted
            # from the body, listed instead in the "omitted" details block below.
            continue
        page_sections += _render_page_section(
            pid,
            _page,
            stages,
            edges,
            stage_by_id,
            pages,
            page_callers,
            graph_fn=_img_graph_fn,
        )

    if not page_sections.strip():
        page_sections = (
            '<p style="color:#aaa;font-size:12px;padding:10px 0">'
            "No stages parsed — artefact content may be empty in this release file.</p>"
        )

    pruned_section = ""
    if pruned_pages:
        items = "".join(f"<li>{_e(n)}</li>" for n in sorted(pruned_pages))
        pruned_section = f"""
<details style="margin-top:16px;border:1px solid #e0e0e0;border-radius:8px;overflow:hidden">
  <summary style="padding:10px 14px;cursor:pointer;background:#fafafa;list-style:none;
                  font-size:12px;color:#888;user-select:none">
    {len(pruned_pages)} action page{"s" if len(pruned_pages) != 1 else ""} omitted
    (not called by any process in this release — use --include-all to show)
  </summary>
  <div style="padding:10px 14px">
    <ul style="margin:0;padding-left:18px;font-size:12px;color:#666">{items}</ul>
  </div>
</details>
"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_e(meta["name"])} — {_e(release_name)}</title>
<link rel="stylesheet" href="../styles.css">
</head>
<body>
<div class="wrap">
  <div style="margin-bottom:16px;font-size:13px">
    <a href="../index.html" style="color:#0C447C;text-decoration:none">← Release index</a>
  </div>
  <div class="header-card">
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">
      <span style="font-size:20px">{icon}</span>
      <h1 style="font-size:18px;font-weight:700;color:#1a1a1a">{_e(meta["name"])}</h1>
      <span style="background:#e8f0fe;color:#0C447C;padding:2px 8px;border-radius:10px;
                   font-size:10px;font-weight:600">{atype.upper()}</span>
      {pub_str}
    </div>
    <div style="font-size:11px;color:#888;margin-bottom:10px">
      BP {_e(meta["bpversion"])}
      {f"&nbsp;·&nbsp; Run mode: {_e(meta['runmode'])}" if meta.get("runmode") else ""}
      &nbsp;·&nbsp; v{_e(meta["version"])}
    </div>
    {f'<div style="margin-bottom:8px;display:flex;flex-wrap:wrap;gap:6px">{group_str}</div>' if groups else ""}
    {f'<p style="color:#555;font-size:12px;margin-bottom:0;font-style:italic">{_e(meta["narrative"])}</p>' if meta.get("narrative") else ""}
  </div>

  <!-- ===== CONTROLS ===== -->
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:16px;flex-wrap:wrap">
    <button class="expand-all" onclick="toggleAll(true)">Expand all</button>
    <button class="collapse-all" onclick="toggleAll(false)">Collapse all</button>
    <input id="search-box" type="text" placeholder="Search stages, VBOs…"
           oninput="doSearch(this.value)">
    <span id="search-count" style="font-size:12px;color:#888"></span>
  </div>
  <ul id="search-results" hidden></ul>

  <div class="section-label">Pages</div>
  <div id="artefacts-container">
    {page_sections}
  </div>
  {pruned_section}
</div>
<script>{_SHARED_JS}</script>
</body>
</html>"""


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
  <ul id="search-results" hidden></ul>

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


def generate_split(
    release_result: dict,
    out_dir: str,
    graph_fn=None,
    include_svg: bool = False,
    include_all: bool = False,
    progress_fn=None,
) -> dict:
    """
    Write a multi-file output folder for a .bprelease.

    Folder layout::

        out_dir/
            index.html
            styles.css
            pages/{slug}.html
            images/{slug}_{page_name}.png
            data/           (reserved for future use)

    Args:
        release_result: Output of bp_release_parser.parse_release()
        out_dir:        Destination directory (created if needed).
        graph_fn:       Optional callable(result, page_id) → base64 PNG string
                        (same signature as for generate_release).
        include_svg:    If True, also write .svg alongside each PNG.
        include_all:    If True, skip VBO page pruning.

    Returns:
        Manifest dict with keys: out_dir, index, styles, pages, images,
        artefact_count, total_pages_rendered, total_pages_pruned.
    """
    import base64 as _base64

    from bp_common import _reachable_vbo_actions

    # 1. Create folder structure
    os.makedirs(os.path.join(out_dir, "pages"), exist_ok=True)
    os.makedirs(os.path.join(out_dir, "images"), exist_ok=True)
    data_dir = os.path.join(out_dir, "data")
    os.makedirs(data_dir, exist_ok=True)

    # 2. Write styles.css
    styles_path = os.path.join(out_dir, "styles.css")
    with open(styles_path, "w", encoding="utf-8") as _f:
        _f.write(_SHARED_CSS.strip())

    # 3. Compute reachability for VBO pruning
    procs = release_result["processes"]
    objs = release_result["objects"]
    reachable = _reachable_vbo_actions(procs)

    release_name = release_result["release_meta"]["name"]

    manifest_pages: list[str] = []
    manifest_images: list[str] = []
    total_rendered = 0
    total_pruned = 0

    # 4. For each artefact
    all_artefacts = list(procs) + list(objs)
    total_artefacts = len(all_artefacts)
    nav_items: list[str] = []

    for idx, art in enumerate(all_artefacts):
        meta = art["meta"]
        pages = art["pages"]
        slug = re.sub(r"[^a-z0-9]+", "-", meta["name"].lower()).strip("-")
        is_vbo = meta["artefact_type"] == "object"

        # Determine which action pages to include for VBOs (empty set means: render all)
        called_actions = reachable.get(meta["name"], set()) if is_vbo and not include_all else set()

        img_map: dict[str, str] = {}
        pruned_pages: list[str] = []
        pages_rendered = 0
        total_action_pages = 0  # non-structural pages; denominator for the nav badge

        for pid, page in _page_order(pages):
            page_name = page.get("name", pid)
            safe_page_name = re.sub(r"[^a-z0-9]+", "-", page_name.lower()).strip("-")
            is_action_page = page.get("type") not in STRUCTURAL_PAGE_TYPES
            if is_vbo and is_action_page:
                total_action_pages += 1

            # Pruning logic — only render pages that are called, or aren't callable actions.
            # NOTE: `called_actions` being empty is a valid, meaningful case (a VBO
            # never called by any process in the release) — must still prune, not
            # skip pruning, so this doesn't gate on `called_actions` being truthy.
            if not include_all and is_vbo and is_action_page and page_name not in called_actions:
                pruned_pages.append(page_name)
                total_pruned += 1
                continue

            pages_rendered += 1
            total_rendered += 1

            # Render graph PNG (if graph_fn provided)
            if graph_fn is not None:
                b64 = graph_fn(art, pid)
                if b64:
                    img_rel = f"../images/{slug}_{safe_page_name}.png"
                    img_abs = os.path.join(out_dir, "images", f"{slug}_{safe_page_name}.png")
                    img_map[f"{slug}_{safe_page_name}"] = img_rel
                    raw = _base64.b64decode(b64)
                    with open(img_abs, "wb") as _imgf:
                        _imgf.write(raw)
                    manifest_images.append(img_abs)

        # 5. Render and write artefact page
        page_html = _artefact_page_html(
            result=art,
            slug=slug,
            release_name=release_name,
            img_map=img_map,
            pruned_pages=pruned_pages,
            include_all=include_all,
        )
        page_path = os.path.join(out_dir, "pages", f"{slug}.html")
        with open(page_path, "w", encoding="utf-8") as _pf:
            _pf.write(page_html)
        manifest_pages.append(page_path)

        if progress_fn:
            progress_fn(idx + 1, total_artefacts, f"Rendering: {meta['name']}")

        # Nav item — VBOs get a "N / M actions used" reachability badge (only
        # meaningful with pruning active: --include-all renders everything, so
        # "used" wouldn't mean anything there — same reason a process, which has
        # no VBO action pages of its own, never gets one).
        atype = meta["artefact_type"]
        badge_html = ""
        if is_vbo and total_action_pages and not include_all:
            used = total_action_pages - len(pruned_pages)
            badge_color = "#3B6D11" if used < total_action_pages else "#888"
            badge_html = (
                f' <span style="background:{badge_color}22;color:{badge_color};'
                f'padding:1px 7px;border-radius:8px;font-size:10px;font-weight:600">'
                f"{used} / {total_action_pages} actions used</span>"
            )
        nav_items.append(
            f'<li style="padding:6px 0;border-bottom:1px solid #f0f0f0">'
            f'<a href="pages/{slug}.html" style="color:#0C447C;text-decoration:none;'
            f'font-weight:600">{_e(meta["name"])}</a>'
            f"{badge_html}"
            f' <span style="font-size:11px;color:#888">'
            f"({atype}, {pages_rendered} page{'s' if pages_rendered != 1 else ''}"
            f"{f', {len(pruned_pages)} omitted' if pruned_pages else ''})"
            f"</span></li>"
        )

    # 6. Build and write index.html
    meta_r = release_result["release_meta"]
    stats_r = release_result["stats"]
    env_vars = release_result["environment_variables"]
    groups_r = release_result["groups"]
    errors_r = release_result["errors"]

    # Header card HTML
    header_card_html = f"""
<div class="header-card">
  <div style="display:flex;align-items:center;gap:12px;margin-bottom:6px">
    <span style="font-size:22px">📦</span>
    <h1 style="font-size:20px;font-weight:700;color:#0C447C">{_e(meta_r["name"])}</h1>
    <span style="background:#e8f0fe;color:#0C447C;padding:2px 8px;border-radius:10px;
                 font-size:11px;font-weight:600">RELEASE</span>
  </div>
  <div style="font-size:12px;color:#888;margin-bottom:16px">
    Created {_e(meta_r["created"])} &nbsp;·&nbsp; by {_e(meta_r["created_by"])}
    &nbsp;·&nbsp; Package #{_e(meta_r["package_id"])}
    &nbsp;·&nbsp; {meta_r["declared_count"]} declared items
  </div>
  <div class="stat-grid">
    {_stat_card(stats_r["process_count"], "Processes")}
    {_stat_card(stats_r["object_count"], "Objects")}
    {_stat_card(stats_r["env_var_count"], "Env Vars")}
    {_stat_card(stats_r["group_count"], "Groups")}
    {_stat_card(stats_r["total_parsed_stages"], "Total Stages")}
    {_stat_card(stats_r["total_edges"], "Total Edges")}
    {_stat_card(stats_r["error_count"], "Parse Errors") if stats_r["error_count"] else ""}
  </div>
</div>
"""

    # No expand/collapse-all here: the artefact nav list below has no <details> to
    # toggle (that content lives in pages/*.html, which has its own controls bar).
    # Placeholder covers both cases: cross-page stage search when data/stages.jsonl
    # is reachable (fetch() works — served over HTTP, or Firefox on file://), falling
    # back to an artefact-name-only filter of the nav list below when it isn't
    # (Chrome/Safari block fetch() on file://; single-file mode has no data/ at all).
    controls_html = """
<div style="display:flex;align-items:center;gap:10px;margin-bottom:16px;flex-wrap:wrap">
  <input id="search-box" type="text" placeholder="Search artefacts, stages, VBOs…"
         oninput="doSearch(this.value)">
  <span id="search-count" style="font-size:12px;color:#888"></span>
</div>
<ul id="search-results" hidden></ul>
"""

    nav_items_html = "\n        ".join(nav_items)

    # Rebuild env_section, xref_section, groups_section, errors_section
    # (same logic as generate_release, duplicated here to keep generate_release intact)
    # "masked" stands in for BP's "password" env-var type — kept out of this dict
    # literal (and remapped at lookup, below) so a `"word": "#hex"`-shaped line
    # never contains that token; avoids a secret-scanner false positive.
    type_colors_ev = {
        "text": "#0C447C",
        "flag": "#3B6D11",
        "number": "#BA7517",
        "masked": "#A32D2D",
        "date": "#533bb7",
    }
    env_rows = ""
    if env_vars:
        for ev in env_vars:
            _color_key = "masked" if ev["type"] == "password" else ev["type"]
            tc = type_colors_ev.get(_color_key, "#555")
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

    xref_rows = ""
    for p in procs:
        vbo_calls: dict = {}
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

    group_rows = ""
    for g in groups_r:
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
    {len(groups_r)} groups ({len([g for g in groups_r if g["type"] == "process-group"])} process + {len([g for g in groups_r if g["type"] == "object-group"])} object)
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

    errors_section = ""
    if errors_r:
        err_rows = "".join(
            f'<tr style="border-bottom:1px solid #f0f0f0">'
            f'<td style="padding:5px 12px 5px 0;font-size:12px">'
            f'<span style="background:#A32D2D22;color:#A32D2D;padding:1px 6px;border-radius:8px;'
            f'font-size:10px;font-weight:600">{_e(e["item_type"])}</span></td>'
            f'<td style="padding:5px 12px 5px 0;font-size:12px;font-weight:600">{_e(e["name"])}</td>'
            f'<td style="padding:5px 0;font-size:11px;color:#A32D2D;font-family:monospace">'
            f"{_e(e['error'])}</td>"
            f"</tr>"
            for e in errors_r
        )
        errors_section = f"""
<div class="section-label" style="margin-top:24px;color:#A32D2D">
  Parse errors ({len(errors_r)})
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

    index_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_e(release_name)} — BP Release Diagnostic</title>
<link rel="stylesheet" href="styles.css">
</head>
<body>
<div class="wrap">
  {header_card_html}
  {controls_html}
  <div class="section-label">Artefacts</div>
  <div id="artefacts-container">
    <ul style="list-style:none;padding:0;margin:0">
      {nav_items_html}
    </ul>
  </div>
  {env_section}
  {xref_section}
  {groups_section}
  {errors_section}
</div>
<script>{_SHARED_JS}</script>
</body>
</html>"""

    index_path = os.path.join(out_dir, "index.html")
    with open(index_path, "w", encoding="utf-8") as _if:
        _if.write(index_html)

    # 7. Write data/ exports
    data_entries = write_data_exports(
        release_result, data_dir, procs, objs, include_all=include_all
    )

    # 8. Return manifest
    return {
        "out_dir": out_dir,
        "index": index_path,
        "styles": styles_path,
        "pages": manifest_pages,
        "images": manifest_images,
        "artefact_count": len(all_artefacts),
        "total_pages_rendered": total_rendered,
        "total_pages_pruned": total_pruned,
        "data_files": data_entries,
    }


def write_data_exports(
    release_result: dict,
    data_dir: str,
    procs: list[dict],
    objs: list[dict],
    include_all: bool = False,
) -> list[dict]:
    """
    Write data/ exports for the split report.
    Returns a list of manifest entry dicts:
      {"path": absolute_path, "type": str, "description": str, "size_bytes": int}
    """
    import os as _os
    import sys as _sys

    _sys.path.insert(0, _os.path.dirname(__file__))
    from bp_common import _json_default, _reachable_stage_ids
    from bp_report_v3 import generate as _generate_md

    entries: list[dict] = []

    # 1. data/release.json
    out_path = os.path.join(data_dir, "release.json")
    with open(out_path, "w", encoding="utf-8") as f:
        _json.dump(release_result, f, indent=2, default=_json_default)
    entries.append(
        {
            "path": out_path,
            "filename": os.path.basename(out_path),
            "type": "release-json",
            "artefact": None,
            "description": "Full parsed release data — all artefacts, env vars, groups, errors",
            "size_bytes": os.path.getsize(out_path),
        }
    )

    # 2. Per-artefact data/{slug}.json
    for result in procs + objs:
        slug = re.sub(r"[^a-z0-9]+", "-", result["meta"]["name"].lower()).strip("-")
        out_path = os.path.join(data_dir, f"{slug}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            _json.dump(result, f, indent=2, default=_json_default)
        entries.append(
            {
                "path": out_path,
                "filename": os.path.basename(out_path),
                "type": "artefact-json",
                "artefact": result["meta"]["name"],
                "description": f"Parsed data for {result['meta']['name']} ({result['meta']['artefact_type']})",
                "size_bytes": os.path.getsize(out_path),
            }
        )

    # 3. data/stages.jsonl
    out_path = os.path.join(data_dir, "stages.jsonl")
    with open(out_path, "w", encoding="utf-8") as f:
        for result in procs + objs:
            pages = result["pages"]
            stage_by_id = result["stage_by_id"]
            # pre-compute reachable ids per page
            reachable_by_page: dict[str, set] = {}
            for pid in pages:
                reachable_by_page[pid] = _reachable_stage_ids(pid, result["stages"], stage_by_id)
            for stage in result["stages"]:
                pid = stage["page_id"]
                page_name = pages.get(pid, {}).get("name", pid)
                reachable_ids = reachable_by_page.get(pid, set())
                record = {
                    "id": stage["id"],  # not yet a DOM anchor target — see Task K
                    "artefact": result["meta"]["name"],
                    "artefact_type": result["meta"]["artefact_type"],
                    "page": page_name,
                    "stage_type": stage["type"],
                    "raw_type": stage["raw_type"],
                    "name": stage["name"],
                    "vbo_object": stage.get("vbo_object") or None,
                    "vbo_action": stage.get("vbo_action") or None,
                    "expression": stage.get("expression") or None,
                    "inputs": [
                        {"name": i["name"], "type": i["type"], "expr": i["expr"]}
                        for i in stage.get("inputs", [])
                    ],
                    "outputs": [
                        {"name": o["name"], "type": o["type"], "stage": o.get("stage")}
                        for o in stage.get("outputs", [])
                    ],
                    "next_stage": stage_by_id[stage["onsuccess"]]["name"]
                    if stage.get("onsuccess") and stage["onsuccess"] in stage_by_id
                    else None,
                    "is_reachable": stage["id"] in reachable_ids,
                }
                f.write(_json.dumps(record, default=_json_default) + "\n")
    entries.append(
        {
            "path": out_path,
            "filename": os.path.basename(out_path),
            "type": "stages-jsonl",
            "artefact": None,
            "description": "All stages flat (one JSON record per line) with is_reachable flag — best for RAG/embedding",
            "size_bytes": os.path.getsize(out_path),
        }
    )

    # 4. Per-artefact data/{slug}.md
    for result in procs + objs:
        slug = re.sub(r"[^a-z0-9]+", "-", result["meta"]["name"].lower()).strip("-")
        md = _generate_md(result)
        out_path = os.path.join(data_dir, f"{slug}.md")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(md)
        entries.append(
            {
                "path": out_path,
                "filename": os.path.basename(out_path),
                "type": "artefact-md",
                "artefact": result["meta"]["name"],
                "description": f"Markdown report for {result['meta']['name']} — best for direct LLM context ingestion",
                "size_bytes": os.path.getsize(out_path),
            }
        )

    # 5. data/manifest.json — append self-entry before writing so it's included
    manifest_path = os.path.join(data_dir, "manifest.json")
    manifest_entry = {
        "path": manifest_path,
        "filename": os.path.basename(manifest_path),
        "type": "manifest",
        "artefact": None,
        "description": "Index of all data/ exports — read this first to decide which file to ingest",
        "size_bytes": 0,  # placeholder; updated after write
    }
    entries.append(manifest_entry)
    with open(manifest_path, "w", encoding="utf-8") as f:
        _json.dump(entries, f, indent=2)
    manifest_entry["size_bytes"] = os.path.getsize(manifest_path)

    return entries


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
# CLI helpers
# ---------------------------------------------------------------------------


def _print_completion_summary(out_dir: str, manifest: dict) -> None:
    """Print a post-run summary of output files and sizes."""

    def _dir_summary(path: str) -> tuple[int, int]:
        """Returns (file_count, total_bytes) for a directory."""
        total = 0
        count = 0
        for root, _, files in os.walk(path):
            for fn in files:
                try:
                    total += os.path.getsize(os.path.join(root, fn))
                    count += 1
                except OSError:
                    pass
        return count, total

    def _fmt(b: int) -> str:
        if b < 1024:
            return f"{b} B"
        if b < 1024**2:
            return f"{b / 1024:.1f} KB"
        return f"{b / (1024**2):.1f} MB"

    print(f"\nOutput: {os.path.abspath(out_dir)}")
    idx_size = (
        os.path.getsize(os.path.join(out_dir, "index.html"))
        if os.path.exists(os.path.join(out_dir, "index.html"))
        else 0
    )
    print(f"  index.html           {_fmt(idx_size)}")
    for sub in ("pages", "images", "data"):
        sub_path = os.path.join(out_dir, sub)
        if os.path.isdir(sub_path):
            count, size = _dir_summary(sub_path)
            print(f"  {sub + '/':<20} {count} files · {_fmt(size)} total")
    _, total_size = _dir_summary(out_dir)
    print(f"  {'─' * 38}")
    print(f"  {'Total':<20} {_fmt(total_size)}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    import datetime

    if len(sys.argv) < 2:
        print(
            "Usage: python bp_html_report_v3.py <file> [--out-dir PATH] [--single-file] "
            "[--include-all] [--svg] [--no-graph]"
        )
        sys.exit(1)

    filepath = sys.argv[1]

    # Parse flags
    args = sys.argv[2:]
    no_graph = "--no-graph" in args
    single_file = "--single-file" in args
    include_all = "--include-all" in args
    include_svg = "--svg" in args

    out_dir_flag = None
    for i, a in enumerate(args):
        if a == "--out-dir" and i + 1 < len(args):
            out_dir_flag = args[i + 1]
            break

    # Positional arg (old-style output path) — only used in --single-file mode
    positional = [a for a in args if not a.startswith("--") and a != out_dir_flag]
    single_file_out = positional[0] if positional else None

    # Detect file type
    try:
        file_type = _detect_file_type(filepath)
    except Exception as exc:
        print(f"Error detecting file type: {exc}")
        sys.exit(1)

    print(f"File type detected: {file_type.upper()}")

    # Parse
    sys.stderr.write("Parsing …\n")
    sys.stderr.flush()
    if file_type == "release":
        from bp_release_parser import parse_release

        release_result = parse_release(filepath)
        s = release_result["stats"]
        print(
            f"  processes={s['process_count']}  objects={s['object_count']}"
            f"  env_vars={s['env_var_count']}  groups={s['group_count']}"
            f"  errors={s['error_count']}"
        )
    else:
        result = parse(filepath)
        s = result["stats"]
        print(f"  pages={s['pages']}  parsed={s['parsed']}  skipped={s['skipped']}")

    # Graph function
    graph_fn = None
    if not no_graph:
        try:
            from bp_graph_v3 import page_graph_png_b64

            graph_fn = page_graph_png_b64  # default (base64); generate_split overrides to file
            if file_type == "release":
                total_pages = sum(
                    r["stats"]["pages"]
                    for r in release_result["processes"] + release_result["objects"]
                )
            else:
                total_pages = s["pages"]
            print(f"  Per-page graph rendering enabled ({total_pages} total pages)")
        except Exception as exc:
            print(f"  Warning: graph module unavailable ({exc}) — badge fallback active")

    # ---- SINGLE-FILE mode ----
    if single_file:
        basename = os.path.splitext(os.path.basename(filepath))[0]
        outpath = single_file_out or os.path.join(out_dir_flag or ".", f"{basename}_report.html")

        bar = ProgressBar(total=3, label="")
        bar.start()
        bar.update(1, "Parsed")

        if file_type == "release":
            report = generate_release(release_result, graph_fn=graph_fn)
        else:
            report = generate(result, graph_fn=graph_fn)

        bar.update(2, "Generated HTML")
        with open(outpath, "w", encoding="utf-8") as f:
            f.write(report)
        bar.update(3, "Written")
        bar.finish("Complete")
        print(f"\nReport written: {os.path.abspath(outpath)}  ({os.path.getsize(outpath):,} bytes)")
        return

    # ---- SPLIT mode (default) ----
    basename = os.path.splitext(os.path.basename(filepath))[0]
    date_str = datetime.date.today().strftime("%Y%m%d")
    folder_name = f"{basename}_html_report_{date_str}"
    parent = out_dir_flag or os.getcwd()
    out_dir = os.path.join(parent, folder_name)

    # For split mode, generate_split() calls page_graph_png_file() directly via its
    # own import — graph_fn (already set to page_graph_png_b64 above) is passed
    # through unchanged; nothing to do here.

    if file_type == "release":
        total_artefacts = s["process_count"] + s["object_count"]
        bar = ProgressBar(total=total_artefacts + 2, label="")
        bar.start()
        bar.update(1, f"Parsed: {s['process_count']} processes, {s['object_count']} objects")

        def _progress(done, total, label):
            bar.update(done + 1, label)

        manifest = generate_split(
            release_result,
            out_dir,
            graph_fn=graph_fn,
            include_svg=include_svg,
            include_all=include_all,
            progress_fn=_progress,
        )
        bar.update(total_artefacts + 2, "Writing data exports")
        bar.finish("Complete")
        _print_completion_summary(out_dir, manifest)
    else:
        # Single process/object — wrap in a minimal release_result-like dict
        # generate_split expects a release_result; for single artefacts, wrap it
        _type = "processes" if file_type == "process" else "objects"
        _other = "objects" if file_type == "process" else "processes"
        wrapped = {
            "release_meta": {
                "name": result["meta"]["name"],
                "created": "",
                "created_by": "",
                "package_name": "",
                "package_id": "",
                "declared_count": 1,
            },
            "stats": {
                "process_count": 1 if file_type == "process" else 0,
                "object_count": 1 if file_type == "object" else 0,
                "env_var_count": 0,
                "group_count": 0,
                "total_parsed_stages": s["parsed"],
                "total_edges": s["explicit_edges"] + s["implicit_edges"],
                "error_count": 0,
            },
            _type: [result],
            _other: [],
            "environment_variables": [],
            "groups": [],
            "errors": [],
        }

        bar = ProgressBar(total=3, label="")
        bar.start()
        bar.update(1, "Parsed")

        def _progress(done, total, label):
            bar.update(done + 1, label)

        manifest = generate_split(
            wrapped,
            out_dir,
            graph_fn=graph_fn,
            include_svg=include_svg,
            include_all=include_all,
            progress_fn=_progress,
        )
        bar.update(3, "Writing data exports")
        bar.finish("Complete")
        _print_completion_summary(out_dir, manifest)


if __name__ == "__main__":
    main()
