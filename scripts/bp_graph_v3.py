"""
bp_graph.py — Blue Prism diagnostic graph generator
Produces a .png (and optionally .svg) process map from any .bprelease/.bpprocess/.bpobject file.

Layout:
- One Graphviz cluster per page
- Flow stages only (Data/Block/Collection excluded from graph for readability)
- Nodes shaped and coloured by stage type
- Edges coloured by label (→ black, true green, false red, on_exception orange dashed)
- Node labels include stage name + expression/VBO truncated to 35 chars

Usage:
    python bp_graph.py <file.xml> [output_stem]
    # Produces <output_stem>.png and <output_stem>.svg
    # Default output_stem = <basename>_graph
"""

import base64
import os
import sys

import graphviz

sys.path.insert(0, os.path.dirname(__file__))
from bp_common import _full_traversal

# Verified before swapping: bp_parser_v2's stage dict is a strict superset of
# bp_parser's (same keys, plus timeout_seconds/group_id for WaitStart/WaitEnd
# that this module doesn't read), stats/top-level keys match exactly, and
# parse()'s signature is identical — this module's standalone CLI (main(),
# below) behaves the same, just parsed by the actively-maintained pipeline.
from bp_parser_v2 import IMPLICIT_PAGE_ID, parse

# ---------------------------------------------------------------------------
# Visual constants
# ---------------------------------------------------------------------------

# Node fill colour per stage type
NODE_FILL = {
    "Start": "#0C447C",
    "End": "#0C447C",
    "Action": "#533bb7",
    "Decision": "#BA7517",
    "Calculation": "#0F6E56",
    "Code": "#2d5fa3",
    "Exception": "#A32D2D",
    "Recover": "#7a2d5f",
    "Resume": "#7a2d5f",
    "Block": "#5F5E5A",
    "Collection": "#185FA5",
    "Data": "#888780",
    "Wait": "#3B6D11",
    "Loop": "#3B6D11",
    "Navigate": "#8B4513",
    "Read": "#8B4513",
    "Write": "#8B4513",
    "Choice": "#BA7517",
}
DEFAULT_FILL = "#888780"

# Graphviz shape per stage type
NODE_SHAPE = {
    "Start": "ellipse",
    "End": "ellipse",
    "Decision": "diamond",
    "Calculation": "parallelogram",
    "Exception": "octagon",
    "Recover": "trapezium",
    "Resume": "trapezium",
    "Block": "rectangle",
    "Code": "component",
    "Collection": "note",
    "Data": "note",
}
DEFAULT_SHAPE = "box"

# Edge colour per label
EDGE_COLOR = {
    "→": "#333333",
    "true": "#3B6D11",
    "false": "#A32D2D",
    "on_exception": "#BA7517",
}

# Cluster fill colours (subtle, alternating)
CLUSTER_FILLS = [
    "#f8f9fb",
    "#f3f7f0",
    "#fdf8f2",
    "#f0f4fb",
    "#faf0f8",
    "#f0fbf8",
    "#fbf5f0",
    "#f5f0fb",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_id(stage_id: str) -> str:
    """Graphviz node IDs must not contain hyphens in some contexts."""
    return "n_" + stage_id.replace("-", "_")


def _node_label(s: dict, include_data: bool = False) -> str:
    """Build a multi-line node label."""
    MAX = 32
    name = s["name"]
    stype = s["type"]
    raw_type = s["raw_type"]

    # First line: name (truncated)
    label = name if len(name) <= MAX else name[: MAX - 1] + "…"

    # Second line: type tag (show raw if normalised)
    type_tag = stype if stype == raw_type else f"{stype} ({raw_type})"
    label += f"\n[{type_tag}]"

    # Third line: expression or VBO
    extra = ""
    if s.get("expression"):
        expr = s["expression"].strip()
        extra = expr if len(expr) <= MAX else expr[: MAX - 1] + "…"
    elif s.get("vbo_object"):
        vbo = f"{s['vbo_object']} → {s['vbo_action']}"
        extra = vbo if len(vbo) <= MAX else vbo[: MAX - 1] + "…"
    elif s.get("multi_steps"):
        n = len(s["multi_steps"])
        first = s["multi_steps"][0]
        t = first["target"]
        extra = f"{t} ← …  (+{n - 1})" if n > 1 else f"{t} ←"
        extra = extra if len(extra) <= MAX else extra[: MAX - 1] + "…"
    elif s.get("is_subsheet_call") or s.get("is_process_call"):
        extra = "→ page call"
    elif stype == "Exception" and s.get("exception_type"):
        exc = s["exception_type"]
        extra = exc if len(exc) <= MAX else exc[: MAX - 1] + "…"
    elif stype == "Code":
        extra = f"VBScript ({s.get('code_length', 0)} chars)"

    if extra:
        label += f"\n{extra}"

    return label


def _node_attrs(s: dict) -> dict:
    """Return Graphviz node attribute dict for a stage."""
    fill = NODE_FILL.get(s["type"], DEFAULT_FILL)
    shape = NODE_SHAPE.get(s["type"], DEFAULT_SHAPE)
    label = _node_label(s)

    attrs = {
        "label": label,
        "shape": shape,
        "style": "filled",
        "fillcolor": fill,
        "fontcolor": "white",
        "fontsize": "9",
        "fontname": "Helvetica",
        "margin": "0.15,0.08",
    }

    # Block: dashed border, lighter fill
    if s["type"] == "Block":
        attrs["style"] = "filled,dashed"
        attrs["fillcolor"] = "#e8e8e8"
        attrs["fontcolor"] = "#333333"

    # Data/Collection: lighter fill
    if s["type"] in ("Data", "Collection"):
        attrs["fillcolor"] = "#cccccc"
        attrs["fontcolor"] = "#333333"

    return attrs


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

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


def build_graph(result: dict, include_data: bool = False) -> graphviz.Digraph:
    """
    Build and return a Graphviz Digraph from parsed BP data.

    Args:
        result:       Output of bp_parser.parse()
        include_data: If True, include Data/Collection nodes in each cluster.
                      False by default — keeps graph readable.
    """
    meta = result["meta"]
    pages = result["pages"]
    stages = result["stages"]
    edges = result["edges"]
    stage_by_id = result["stage_by_id"]

    # Determine which types to render
    render_types = FLOW_TYPES.copy()
    if include_data:
        render_types |= {"Data", "Collection"}

    g = graphviz.Digraph(
        name=meta["name"],
        engine="dot",
        format="png",
    )
    g.attr(
        rankdir="TB",
        compound="true",
        dpi="150",
        fontname="Helvetica",
        fontsize="11",
        bgcolor="white",
        label=f"{meta['name']}  |  {meta['artefact_type'].upper()}  |  BP {meta['bpversion']}",
        labelloc="t",
        labeljust="l",
        pad="0.4",
        nodesep="0.35",
        ranksep="0.55",
    )
    g.attr("node", fontname="Helvetica", fontsize="9")
    g.attr("edge", fontname="Helvetica", fontsize="8", penwidth="1.2")

    # Track which node IDs are rendered (for edge filtering)
    rendered: set[str] = set()

    # One cluster per page, in display order
    page_order = [IMPLICIT_PAGE_ID] + sorted(
        [pid for pid in pages if pid != IMPLICIT_PAGE_ID], key=lambda pid: pages[pid]["name"]
    )

    for i, pid in enumerate(page_order):
        page = pages[pid]
        # Use BFS traversal order within each cluster
        ordered = _full_traversal(pid, stages, stage_by_id)
        page_nodes = [s for s in ordered if s["type"] in render_types]

        if not page_nodes:
            continue

        cluster_name = f"cluster_{pid.replace('-', '_')}"
        cluster_fill = CLUSTER_FILLS[i % len(CLUSTER_FILLS)]
        pub_str = (
            ""
            if page["published"] is None
            else ("  ✓ published" if page["published"] else "  ✗ unpublished")
        )
        cluster_label = f"{page['name']}  [{page['type']}{pub_str}]"

        with g.subgraph(name=cluster_name) as c:  # type: ignore[attr-defined]
            c.attr(
                label=cluster_label,
                style="rounded,filled",
                fillcolor=cluster_fill,
                color="#0C447C",
                penwidth="1.5",
                fontname="Helvetica Bold",
                fontsize="10",
                fontcolor="#0C447C",
                margin="16",
            )

            # Add nodes in BFS order (Graphviz respects declaration order for rank)
            for s in page_nodes:
                nid = _safe_id(s["id"])
                c.node(nid, **_node_attrs(s))
                rendered.add(s["id"])

    # ---- Edges ----
    for e in edges:
        if e["from_id"] not in rendered or e["to_id"] not in rendered:
            continue  # skip edges to/from non-rendered nodes

        src = _safe_id(e["from_id"])
        tgt = _safe_id(e["to_id"])
        label = e["label"]
        color = EDGE_COLOR.get(label, "#555555")

        edge_attrs = {
            "color": color,
            "fontcolor": color,
        }

        if label == "→":
            edge_attrs["label"] = ""
        elif label == "true":
            edge_attrs["label"] = "true"
            edge_attrs["penwidth"] = "1.5"
        elif label == "false":
            edge_attrs["label"] = "false"
            edge_attrs["penwidth"] = "1.5"
        elif label == "on_exception":
            edge_attrs["label"] = "exception"
            edge_attrs["style"] = "dashed"
            edge_attrs["penwidth"] = "1.0"
            edge_attrs["weight"] = "0"  # don't affect main layout ranking

        g.edge(src, tgt, **edge_attrs)

    return g


# ---------------------------------------------------------------------------
# Per-page graph builder
# ---------------------------------------------------------------------------


def build_page_graph(result: dict, page_id: str, include_data: bool = False) -> graphviz.Digraph:
    """
    Build a Graphviz Digraph for a single page only.
    Used by the HTML report to embed one PNG per page section.

    Args:
        result:       Output of bp_parser.parse()
        page_id:      The page UUID (or IMPLICIT_PAGE_ID) to render
        include_data: If True, include Data/Collection nodes

    Returns:
        A Graphviz Digraph configured for PNG output
    """
    pages = result["pages"]
    stages = result["stages"]
    edges = result["edges"]
    stage_by_id = result["stage_by_id"]

    page = pages.get(page_id, {})
    page_name = page.get("name", "Unknown")

    render_types = FLOW_TYPES.copy()
    if include_data:
        render_types |= {"Data", "Collection"}

    g = graphviz.Digraph(
        name=page_name,
        engine="dot",
        format="png",
    )
    g.attr(
        rankdir="TB",
        dpi="150",
        fontname="Helvetica",
        fontsize="10",
        bgcolor="white",
        label=page_name,
        labelloc="t",
        labeljust="l",
        pad="0.3",
        nodesep="0.3",
        ranksep="0.5",
    )
    g.attr("node", fontname="Helvetica", fontsize="9")
    g.attr("edge", fontname="Helvetica", fontsize="8", penwidth="1.2")

    # BFS traversal order for clean top-to-bottom layout
    ordered = _full_traversal(page_id, stages, stage_by_id)
    page_nodes = [s for s in ordered if s["type"] in render_types]

    if not page_nodes:
        return g

    rendered: set[str] = set()
    for s in page_nodes:
        nid = _safe_id(s["id"])
        g.node(nid, **_node_attrs(s))
        rendered.add(s["id"])

    # Only edges where both endpoints are on this page and rendered
    for e in edges:
        src_stage = stage_by_id.get(e["from_id"], {})
        tgt_stage = stage_by_id.get(e["to_id"], {})
        if src_stage.get("page_id") != page_id or tgt_stage.get("page_id") != page_id:
            continue
        if e["from_id"] not in rendered or e["to_id"] not in rendered:
            continue

        src = _safe_id(e["from_id"])
        tgt = _safe_id(e["to_id"])
        label = e["label"]
        color = EDGE_COLOR.get(label, "#555555")

        edge_attrs = {"color": color, "fontcolor": color}

        if label == "→":
            edge_attrs["label"] = ""
        elif label in ("true", "false"):
            edge_attrs["label"] = label
            edge_attrs["penwidth"] = "1.5"
        elif label == "on_exception":
            edge_attrs["label"] = "exception"
            edge_attrs["style"] = "dashed"
            edge_attrs["penwidth"] = "1.0"
            edge_attrs["weight"] = "0"

        g.edge(src, tgt, **edge_attrs)

    return g


def page_graph_png_b64(result: dict, page_id: str, include_data: bool = False) -> str | None:
    """
    Render a single-page graph to PNG and return as base64 string.
    Returns None on any failure (caller falls back gracefully).
    """
    import tempfile

    try:
        g = build_page_graph(result, page_id, include_data=include_data)
        g.format = "png"
        with tempfile.TemporaryDirectory() as tmp:
            path = g.render(filename=os.path.join(tmp, "page"), cleanup=True)
            with open(path, "rb") as f:
                return base64.b64encode(f.read()).decode()
    except FileNotFoundError as e:
        if "graphviz" in str(e).lower() or "dot" in str(e).lower():
            print(
                "Warning: Graphviz binary not found. Install it with: "
                "Windows: choco install graphviz | Linux: apt install graphviz | macOS: brew install graphviz",
                file=sys.stderr,
            )
        else:
            print(
                f"Warning: File not found during graph rendering for page {page_id}: {e}",
                file=sys.stderr,
            )
        return None
    except Exception as e:
        print(
            f"Warning: Graph rendering failed for page {page_id}: {type(e).__name__}: {e}",
            file=sys.stderr,
        )
        return None


def page_graph_png_file(
    result: dict,
    page_id: str,
    out_path: str,
    include_data: bool = False,
    include_svg: bool = False,
) -> str | None:
    """
    Render a single-page graph to a PNG file at out_path.
    If include_svg is True, also writes out_path.replace('.png', '.svg').
    Returns the written PNG path on success, None on failure.
    """
    try:
        g = build_page_graph(result, page_id, include_data=include_data)
        g.format = "png"
        # graphviz.render appends the format extension; strip .png from stem
        stem = out_path[:-4] if out_path.endswith(".png") else out_path
        png_path = g.render(filename=stem, cleanup=True)
        if include_svg:
            g.format = "svg"
            g.render(filename=stem + "_svg", cleanup=True)
        return png_path
    except FileNotFoundError as e:
        if "graphviz" in str(e).lower() or "dot" in str(e).lower():
            print(
                "Warning: Graphviz binary not found. "
                "Windows: choco install graphviz | Linux: apt install graphviz | macOS: brew install graphviz",
                file=sys.stderr,
            )
        else:
            print(
                f"Warning: File not found during graph render for page {page_id}: {e}",
                file=sys.stderr,
            )
        return None
    except Exception as e:
        print(
            f"Warning: Graph render failed for page {page_id}: {type(e).__name__}: {e}",
            file=sys.stderr,
        )
        return None


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def render(result: dict, output_stem: str, include_data: bool = False) -> tuple:
    """
    Render PNG and SVG to output_stem.png and output_stem.svg.
    Returns (png_path, svg_path).
    """
    g = build_graph(result, include_data=include_data)

    # PNG
    g.format = "png"
    png_path = g.render(filename=output_stem, cleanup=True)

    # SVG (same graph, different format)
    g.format = "svg"
    svg_path = g.render(filename=output_stem + "_svg", cleanup=True)

    return png_path, svg_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    import contextlib

    # Same fix as bp_html_report_v3.py's main(): make console output
    # crash-proof on non-UTF-8 terminals (e.g. Windows cp1252, which can't
    # encode the "→" below) instead of a UnicodeEncodeError right after a
    # fully successful parse. Scoped to main(), not import time.
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            with contextlib.suppress(Exception):
                _stream.reconfigure(errors="replace")

    if len(sys.argv) < 2:
        print("Usage: python bp_graph_v3.py <file.xml> [output_stem] [--with-data]")
        sys.exit(1)

    filepath = sys.argv[1]
    include_data = "--with-data" in sys.argv
    args = [a for a in sys.argv[2:] if not a.startswith("--")]
    basename = os.path.splitext(os.path.basename(filepath))[0]
    output_stem = args[0] if args else basename + "_graph"

    result = parse(filepath)
    s = result["stats"]

    print(f"Parsed: pages={s['pages']}  stages={s['parsed']}  edges={s['total_edges']}")
    print(f"Rendering graph → {output_stem}.png / .svg ...")

    png_path, svg_path = render(result, output_stem, include_data=include_data)

    print(f"PNG: {png_path}  ({os.path.getsize(png_path):,} bytes)")
    print(f"SVG: {svg_path}  ({os.path.getsize(svg_path):,} bytes)")


if __name__ == "__main__":
    main()
