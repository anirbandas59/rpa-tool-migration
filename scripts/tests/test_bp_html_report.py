"""
Targeted tests for bp_html_report_v3.py — split-output writer and manifest.
Does NOT require Graphviz (graph_fn=None throughout).
"""

import html
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import bp_html_report_v3 as bp_html_report


def _make_stage(sid, vbo_object=None, vbo_action=None, page_id="pp1"):
    return {
        "id": sid,
        "name": sid,
        "page_id": page_id,
        "type": "Action",
        "raw_type": "Action",
        "onsuccess": None,
        "ontrue": None,
        "onfalse": None,
        "vbo_object": vbo_object,
        "vbo_action": vbo_action,
        "expression": None,
        "multi_steps": [],
        "inputs": [],
        "outputs": [],
        "is_subsheet_call": False,
        "is_process_call": False,
        "processid": None,
        "is_alert": False,
        "is_skill": False,
        "datatype": None,
        "initial_value": None,
        "code_length": 0,
        "exception_type": None,
        "exception_detail": None,
        "exception_usecurrent": False,
        "timeout_seconds": None,
        "group_id": None,
        "narrative": None,
    }


# ---------------------------------------------------------------------------
# generate_split — folder structure
# ---------------------------------------------------------------------------


def test_generate_split_creates_folder_structure(make_release_result, tmp_path):
    """generate_split() creates index.html, styles.css, pages/, images/, data/."""
    release = make_release_result(
        processes=[
            {
                "name": "My Process",
                "pages": {"p1": {"name": "Main", "type": "SubSheet", "published": None}},
                "stages": [],
            }
        ],
    )
    bp_html_report.generate_split(release, str(tmp_path), graph_fn=None)
    assert os.path.isfile(os.path.join(str(tmp_path), "index.html"))
    assert os.path.isfile(os.path.join(str(tmp_path), "styles.css"))
    assert os.path.isdir(os.path.join(str(tmp_path), "pages"))
    assert os.path.isdir(os.path.join(str(tmp_path), "images"))
    assert os.path.isdir(os.path.join(str(tmp_path), "data"))


def test_generate_split_returns_manifest_keys(make_release_result, tmp_path):
    """Manifest dict contains expected top-level keys."""
    release = make_release_result(
        processes=[{"name": "Proc A", "pages": {}, "stages": []}],
    )
    manifest = bp_html_report.generate_split(release, str(tmp_path), graph_fn=None)
    for key in ("out_dir", "index", "styles", "pages", "images", "artefact_count"):
        assert key in manifest, f"manifest missing key: {key}"


def test_generate_split_creates_artefact_pages(make_release_result, tmp_path):
    """One HTML page per artefact written to pages/."""
    release = make_release_result(
        processes=[{"name": "My Process", "pages": {}, "stages": []}],
        objects=[{"name": "Utility - File", "pages": {}, "stages": []}],
    )
    bp_html_report.generate_split(release, str(tmp_path), graph_fn=None)
    html_files = [
        f for f in os.listdir(os.path.join(str(tmp_path), "pages")) if f.endswith(".html")
    ]
    assert len(html_files) == 2


def test_generate_split_index_links_to_pages(make_release_result, tmp_path):
    """index.html contains a link to each artefact page."""
    release = make_release_result(
        processes=[{"name": "My Process", "pages": {}, "stages": []}],
    )
    bp_html_report.generate_split(release, str(tmp_path), graph_fn=None)
    with open(os.path.join(str(tmp_path), "index.html"), encoding="utf-8") as f:
        index_html = f.read()
    assert "pages/" in index_html


def test_generate_split_index_has_no_dead_expand_collapse_buttons(make_release_result, tmp_path):
    """index.html's nav list is a flat <ul>, not <details> — the Expand/Collapse-all
    buttons had nothing to toggle there (Pass 1 bug) and must not be rendered.
    """
    release = make_release_result(
        processes=[{"name": "My Process", "pages": {}, "stages": []}],
    )
    bp_html_report.generate_split(release, str(tmp_path), graph_fn=None)
    with open(os.path.join(str(tmp_path), "index.html"), encoding="utf-8") as f:
        index_html = f.read()
    assert "Expand all" not in index_html
    assert "Collapse all" not in index_html
    assert 'id="search-box"' in index_html  # search itself is kept


def test_generate_split_index_search_targets_nav_list(make_release_result, tmp_path):
    """doSearch() in index.html's embedded JS must filter the artefact table's
    rows (Task L: a sortable <table>, not a <ul>), not just <summary>/<td> —
    Pass 1's selector missed the nav list entirely.
    """
    release = make_release_result(
        processes=[{"name": "My Process", "pages": {}, "stages": []}],
    )
    bp_html_report.generate_split(release, str(tmp_path), graph_fn=None)
    with open(os.path.join(str(tmp_path), "index.html"), encoding="utf-8") as f:
        index_html = f.read()
    assert "#artefacts-container tbody tr" in index_html
    assert "row.hidden" in index_html


def test_generate_split_index_has_cross_page_search_and_fallback(make_release_result, tmp_path):
    """index.html's embedded JS must fetch data/stages.jsonl for cross-page search
    AND retain the same-page nav-list fallback for when fetch() is unavailable
    (blocked on file:// in Chrome/Safari, or 404 in single-file mode).
    """
    release = make_release_result(
        processes=[{"name": "My Process", "pages": {}, "stages": []}],
    )
    bp_html_report.generate_split(release, str(tmp_path), graph_fn=None)
    with open(os.path.join(str(tmp_path), "index.html"), encoding="utf-8") as f:
        index_html = f.read()
    assert "data/stages.jsonl" in index_html
    assert "_loadStageIndex" in index_html
    assert "_renderCrossPageResults" in index_html
    assert "_samePageSearch" in index_html  # fallback path retained, not removed
    assert 'id="search-results"' in index_html


def test_generate_split_artefact_page_has_cross_page_search(make_release_result, tmp_path):
    """pages/*.html must also load the cross-page index (via ../data/stages.jsonl,
    one level up from index.html's data/stages.jsonl) so search reaches every
    artefact from within any single artefact's page too.
    """
    release = make_release_result(
        processes=[{"name": "My Process", "pages": {}, "stages": []}],
    )
    bp_html_report.generate_split(release, str(tmp_path), graph_fn=None)
    with open(os.path.join(str(tmp_path), "pages", "my-process.html"), encoding="utf-8") as f:
        page_html = f.read()
    assert "_loadStageIndex" in page_html
    assert 'id="search-results"' in page_html


def test_generate_split_styles_css_has_stage_card(make_release_result, tmp_path):
    """styles.css contains the .stage-card class extracted from _SHARED_CSS."""
    release = make_release_result(
        processes=[{"name": "P", "pages": {}, "stages": []}],
    )
    bp_html_report.generate_split(release, str(tmp_path), graph_fn=None)
    with open(os.path.join(str(tmp_path), "styles.css"), encoding="utf-8") as f:
        css = f.read()
    assert ".stage-card" in css


# ---------------------------------------------------------------------------
# write_data_exports
# ---------------------------------------------------------------------------


def test_write_data_exports_creates_all_files(make_release_result, tmp_path):
    release = make_release_result(
        processes=[
            {
                "name": "Proc A",
                "pages": {"p1": {"name": "Main", "type": "SubSheet", "published": None}},
                "stages": [],
            }
        ],
    )
    data_dir = os.path.join(str(tmp_path), "data")
    os.makedirs(data_dir)
    bp_html_report.write_data_exports(release, data_dir, release["processes"], release["objects"])
    assert os.path.isfile(os.path.join(data_dir, "release.json"))
    assert os.path.isfile(os.path.join(data_dir, "stages.jsonl"))
    assert os.path.isfile(os.path.join(data_dir, "manifest.json"))


def test_write_data_exports_release_json_valid(make_release_result, tmp_path):
    release = make_release_result(
        processes=[{"name": "Proc A", "pages": {}, "stages": []}],
    )
    data_dir = os.path.join(str(tmp_path), "data")
    os.makedirs(data_dir)
    bp_html_report.write_data_exports(release, data_dir, release["processes"], release["objects"])
    with open(os.path.join(data_dir, "release.json"), encoding="utf-8") as f:
        parsed = json.load(f)
    assert parsed["release_meta"]["name"] == "Test Release"


def test_write_data_exports_manifest_has_expected_types(make_release_result, tmp_path):
    release = make_release_result(
        processes=[{"name": "Proc A", "pages": {}, "stages": []}],
    )
    data_dir = os.path.join(str(tmp_path), "data")
    os.makedirs(data_dir)
    bp_html_report.write_data_exports(release, data_dir, release["processes"], release["objects"])
    with open(os.path.join(data_dir, "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    types = {e["type"] for e in manifest}
    assert "release-json" in types
    assert "stages-jsonl" in types
    assert "manifest" in types


def test_write_data_exports_stages_jsonl_has_stage_id(make_release_result, tmp_path):
    """Each stages.jsonl record carries the stage's real id — needed so a search
    result can deep-link to #stage-{id} once Task K adds those DOM anchors.
    """
    release = make_release_result(
        processes=[
            {
                "name": "Proc A",
                "pages": {"p1": {"name": "Main", "type": "Normal", "published": None}},
                "stages": [_make_stage("s1", page_id="p1")],
            }
        ],
    )
    data_dir = os.path.join(str(tmp_path), "data")
    os.makedirs(data_dir)
    bp_html_report.write_data_exports(release, data_dir, release["processes"], release["objects"])
    with open(os.path.join(data_dir, "stages.jsonl"), encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]
    assert records
    assert records[0]["id"] == "s1"


def test_write_data_exports_artefact_md_written(make_release_result, tmp_path):
    """Per-artefact .md file is written to data/."""
    release = make_release_result(
        processes=[{"name": "Proc A", "pages": {}, "stages": []}],
    )
    data_dir = os.path.join(str(tmp_path), "data")
    os.makedirs(data_dir)
    bp_html_report.write_data_exports(release, data_dir, release["processes"], release["objects"])
    md_files = [f for f in os.listdir(data_dir) if f.endswith(".md")]
    assert len(md_files) >= 1


# ---------------------------------------------------------------------------
# VBO pruning
# ---------------------------------------------------------------------------


def test_generate_split_prunes_uncalled_vbo_pages(make_release_result, tmp_path):
    """VBO has 3 action pages (real BP page type "Normal"), process calls only 1 → 2 pruned.

    Regression test for the Pass 1 bug where the pruning check compared
    page["type"] == "Action" — a string that never appears in real parsed data
    (bp_parser_v2.py emits "implicit"/"CleanUp"/"Normal" only). Using "Normal"
    here, not "Action", is the point: this is what real VBO action pages look like.
    """
    proc_stages = [_make_stage("s1", vbo_object="My VBO", vbo_action="Action A")]
    release = make_release_result(
        processes=[
            {
                "name": "My Process",
                "pages": {"pp1": {"name": "Main", "type": "Normal", "published": None}},
                "stages": proc_stages,
            }
        ],
        objects=[
            {
                "name": "My VBO",
                "pages": {
                    "pa": {"name": "Action A", "type": "Normal", "published": None},
                    "pb": {"name": "Action B", "type": "Normal", "published": None},
                    "pc": {"name": "Action C", "type": "Normal", "published": None},
                },
                "stages": [],
            }
        ],
    )
    manifest = bp_html_report.generate_split(
        release, str(tmp_path), graph_fn=None, include_all=False
    )
    assert manifest.get("total_pages_pruned", 0) >= 2

    # Bug 2 regression: pruned pages must be absent from the rendered artefact
    # page body, not just counted/listed in the "omitted" footer.
    slug = "my-vbo"
    page_html = (tmp_path / "pages" / f"{slug}.html").read_text(encoding="utf-8")
    assert "Action B" in page_html  # listed in the omitted-pages footer
    assert "Action C" in page_html
    assert page_html.count("Action B") == 1  # only the footer mention — no stage card
    assert page_html.count("Action C") == 1
    assert page_html.count("Action A") >= 1  # the called action IS rendered in full


def test_generate_split_structural_pages_never_pruned(make_release_result, tmp_path):
    """ "implicit" (Initialize/Main) and "CleanUp" pages are never pruned, even if unused."""
    proc_stages = [_make_stage("s1", vbo_object="My VBO", vbo_action="Action A")]
    release = make_release_result(
        processes=[
            {
                "name": "My Process",
                "pages": {"pp1": {"name": "Main", "type": "Normal", "published": None}},
                "stages": proc_stages,
            }
        ],
        objects=[
            {
                "name": "My VBO",
                "pages": {
                    "IMPLICIT_MAIN": {"name": "Initialize", "type": "implicit", "published": None},
                    "cu": {"name": "Clean Up", "type": "CleanUp", "published": None},
                    "pa": {"name": "Action A", "type": "Normal", "published": None},
                },
                "stages": [],
            }
        ],
    )
    manifest = bp_html_report.generate_split(
        release, str(tmp_path), graph_fn=None, include_all=False
    )
    assert manifest.get("total_pages_pruned", 0) == 0
    page_html = (tmp_path / "pages" / "my-vbo.html").read_text(encoding="utf-8")
    assert "Initialize" in page_html
    assert "Clean Up" in page_html


def test_generate_split_include_all_disables_pruning(make_release_result, tmp_path):
    """include_all=True renders at least as many pages as include_all=False."""
    vbo_pages = {
        "pa": {"name": "Action A", "type": "Normal", "published": None},
        "pb": {"name": "Action B", "type": "Normal", "published": None},
    }
    release = make_release_result(
        processes=[{"name": "P", "pages": {}, "stages": []}],
        objects=[{"name": "VBO", "pages": vbo_pages, "stages": []}],
    )
    m_pruned = bp_html_report.generate_split(
        release, str(tmp_path / "pruned"), graph_fn=None, include_all=False
    )
    m_all = bp_html_report.generate_split(
        release, str(tmp_path / "all"), graph_fn=None, include_all=True
    )
    assert m_all["total_pages_rendered"] >= m_pruned["total_pages_rendered"]


def test_generate_split_prunes_entirely_unused_vbo(make_release_result, tmp_path):
    """Regression: a VBO never called by ANY process must still be pruned down to
    just its structural pages — the pruning gate previously required
    `called_actions` to be non-empty, so a completely-unused VBO (empty
    called_actions) skipped pruning entirely and rendered every page.
    """
    release = make_release_result(
        processes=[{"name": "P", "pages": {}, "stages": []}],  # calls nothing
        objects=[
            {
                "name": "Unused VBO",
                "pages": {
                    "IMPLICIT_MAIN": {"name": "Initialize", "type": "implicit", "published": None},
                    "pa": {"name": "Action A", "type": "Normal", "published": None},
                    "pb": {"name": "Action B", "type": "Normal", "published": None},
                },
                "stages": [],
            }
        ],
    )
    manifest = bp_html_report.generate_split(
        release, str(tmp_path), graph_fn=None, include_all=False
    )
    assert manifest.get("total_pages_pruned", 0) == 2  # both actions, none called
    page_html = (tmp_path / "pages" / "unused-vbo.html").read_text(encoding="utf-8")
    assert "Initialize" in page_html  # structural page always kept
    assert page_html.count("Action A") == 1  # footer-only mention, not a full card
    assert page_html.count("Action B") == 1


def test_generate_split_nav_shows_actions_used_badge(make_release_result, tmp_path):
    """index.html's nav list shows an 'N / M actions used' badge for a VBO with
    partial reachability (Task K) — not just the raw page count from Task H.
    """
    proc_stages = [_make_stage("s1", vbo_object="My VBO", vbo_action="Action A")]
    release = make_release_result(
        processes=[{"name": "My Process", "pages": {}, "stages": proc_stages}],
        objects=[
            {
                "name": "My VBO",
                "pages": {
                    "pa": {"name": "Action A", "type": "Normal", "published": None},
                    "pb": {"name": "Action B", "type": "Normal", "published": None},
                },
                "stages": [],
            }
        ],
    )
    bp_html_report.generate_split(release, str(tmp_path), graph_fn=None, include_all=False)
    with open(os.path.join(str(tmp_path), "index.html"), encoding="utf-8") as f:
        index_html = f.read()
    assert ">1 / 2<" in index_html
    assert 'data-ratio="0.5"' in index_html  # sortable by reachability (Task L)


def test_generate_split_index_has_sortable_artefact_table(make_release_result, tmp_path):
    """index.html's artefact list is a sortable <table> (Task L), not a flat <ul>."""
    release = make_release_result(
        processes=[{"name": "My Process", "pages": {}, "stages": []}],
    )
    bp_html_report.generate_split(release, str(tmp_path), graph_fn=None)
    with open(os.path.join(str(tmp_path), "index.html"), encoding="utf-8") as f:
        index_html = f.read()
    assert 'id="artefact-table"' in index_html
    assert "_sortArtefacts" in index_html
    assert 'data-sort="name"' in index_html
    assert 'data-sort="pages"' in index_html
    assert 'data-sort="ratio"' in index_html


def test_generate_split_index_uses_extracted_css_classes(make_release_result, tmp_path):
    """Task M: index.html's header, env-vars/xref/groups/errors tables, and
    controls bar use named classes (styles.css) instead of repeated inline
    style="..." attributes — only per-item dynamic colours (pill badges) stay
    inline, per Enhancement 5's original structural-vs-dynamic split.
    """
    release = make_release_result(
        processes=[{"name": "My Process", "pages": {}, "stages": []}],
        objects=[{"name": "My VBO", "pages": {}, "stages": []}],
    )
    release["environment_variables"] = [
        {"name": "EnvA", "type": "text", "value": "x", "description": "d"}
    ]
    release["groups"] = [
        {"name": "G1", "type": "process-group", "member_ids": ["a"], "is_default": True}
    ]
    release["errors"] = [{"item_type": "process", "name": "Bad", "error": "boom"}]
    bp_html_report.generate_split(release, str(tmp_path), graph_fn=None)
    with open(os.path.join(str(tmp_path), "index.html"), encoding="utf-8") as f:
        index_html = f.read()

    # Structural classes present — collect every class actually used, robust to
    # multi-class attributes (e.g. class="plain-card plain-card--error").
    used_classes: set[str] = set()
    for attr_value in re.findall(r'class="([^"]*)"', index_html):
        used_classes.update(attr_value.split())
    for cls in (
        "header-top",
        "header-title",
        "header-meta",
        "controls-bar",
        "plain-card",
        "info-card",
        "info-card-summary",
        "data-table",
        "data-table--error",
        "cell-strong",
        "cell-mono",
        "cell-muted",
        "cell-dim",
    ):
        assert cls in used_classes, f"expected class {cls!r} to appear in index.html"

    # Only the intentional dynamic-colour pill badges keep inline style=
    styled = re.findall(r'style="([^"]*)"', index_html)
    for s in styled:
        assert s.startswith("background:"), f"unexpected leftover inline style: {s!r}"


def test_artefact_page_has_jump_to_artefact_dropdown(make_release_result, tmp_path):
    """pages/*.html offers a way to switch artefacts without a round-trip through
    index.html (Task L) — a <select> listing every other artefact in the release.
    """
    release = make_release_result(
        processes=[{"name": "My Process", "pages": {}, "stages": []}],
        objects=[{"name": "My VBO", "pages": {}, "stages": []}],
    )
    bp_html_report.generate_split(release, str(tmp_path), graph_fn=None)
    with open(os.path.join(str(tmp_path), "pages", "my-process.html"), encoding="utf-8") as f:
        page_html = f.read()
    assert 'id="artefact-jump"' in page_html
    assert ">My Process<" in page_html
    assert ">My VBO<" in page_html
    assert 'value="my-vbo.html"' in page_html


def test_stage_card_has_stage_id_anchor(make_release_result, tmp_path):
    """Every stage card carries id="stage-{id}" — Task J's search results link to
    #stage-{id}; this is the DOM anchor that makes those links actually land on
    the right stage (and lets browsers auto-expand its <details> chain).
    """
    release = make_release_result(
        processes=[
            {
                "name": "My Process",
                "pages": {"p1": {"name": "Main", "type": "Normal", "published": None}},
                "stages": [_make_stage("abc-123", page_id="p1")],
            }
        ],
    )
    bp_html_report.generate_split(release, str(tmp_path), graph_fn=None)
    page_html = (tmp_path / "pages" / "my-process.html").read_text(encoding="utf-8")
    assert 'id="stage-abc-123"' in page_html


def test_stage_card_has_copy_buttons_with_valid_payloads(make_release_result, tmp_path):
    """Every stage card carries a Copy JSON / Copy MD button (Task N), with the
    copyable payload embedded as a data-* attribute at generation time — must
    work even where fetch() can't reach data/stages.jsonl (file://; see Task J).
    """
    release = make_release_result(
        processes=[
            {
                "name": "My Process",
                "pages": {"p1": {"name": "Main", "type": "Normal", "published": None}},
                "stages": [
                    _make_stage("abc-123", vbo_object="My VBO", vbo_action="Do Thing", page_id="p1")
                ],
            }
        ],
    )
    bp_html_report.generate_split(release, str(tmp_path), graph_fn=None)
    page_html = (tmp_path / "pages" / "my-process.html").read_text(encoding="utf-8")

    assert "_copyStageData" in page_html
    assert "onclick=\"_copyStageData(this,'json')\"" in page_html
    assert "onclick=\"_copyStageData(this,'md')\"" in page_html

    m = re.search(r'data-copy-json="([^"]*)"', page_html)
    assert m, "expected a data-copy-json attribute on the stage card"
    payload = json.loads(html.unescape(m.group(1)))
    assert payload["id"] == "abc-123"
    assert payload["page"] == "Main"
    assert payload["vbo_object"] == "My VBO"
    assert payload["vbo_action"] == "Do Thing"

    m_md = re.search(r'data-copy-md="([^"]*)"', page_html)
    assert m_md, "expected a data-copy-md attribute on the stage card"
    md = html.unescape(m_md.group(1))
    assert "My VBO" in md and "Do Thing" in md


def test_styles_css_has_print_stylesheet(make_release_result, tmp_path):
    """styles.css includes an @media print block that hides screen-only UI
    chrome and forces closed <details> open, so printing/save-as-PDF from the
    browser shows real content instead of collapsed cards (Task N).
    """
    release = make_release_result(
        processes=[{"name": "My Process", "pages": {}, "stages": []}],
    )
    bp_html_report.generate_split(release, str(tmp_path), graph_fn=None)
    css = (tmp_path / "styles.css").read_text(encoding="utf-8")
    assert "@media print" in css
    assert "details:not([open])" in css
    assert ".controls-bar" in css
