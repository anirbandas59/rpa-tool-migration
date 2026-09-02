"""Tests for scripts/bp_common.py"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bp_common import _full_traversal, _json_default, _reachable_stage_ids, _reachable_vbo_actions

# ---------------------------------------------------------------------------
# _reachable_vbo_actions
# ---------------------------------------------------------------------------


def test_reachable_vbo_actions_basic():
    stages = [
        {"vbo_object": "Utility - File Management", "vbo_action": "Read Text File"},
        {"vbo_object": "Utility - File Management", "vbo_action": "File Exists"},
        {"vbo_object": "Utility - String", "vbo_action": "Trim"},
    ]
    result = _reachable_vbo_actions([{"stages": stages}])
    assert result["Utility - File Management"] == {"Read Text File", "File Exists"}
    assert result["Utility - String"] == {"Trim"}


def test_reachable_vbo_actions_empty_stages():
    result = _reachable_vbo_actions([{"stages": [{"vbo_object": None, "vbo_action": None}]}])
    assert result == {}


def test_reachable_vbo_actions_multiple_procs():
    proc1 = {"stages": [{"vbo_object": "VBO A", "vbo_action": "Action 1"}]}
    proc2 = {"stages": [{"vbo_object": "VBO A", "vbo_action": "Action 2"}]}
    result = _reachable_vbo_actions([proc1, proc2])
    assert result["VBO A"] == {"Action 1", "Action 2"}


def test_reachable_vbo_actions_ignores_empty_strings():
    stages = [
        {"vbo_object": "", "vbo_action": "Something"},
        {"vbo_object": "VBO X", "vbo_action": ""},
        {"vbo_object": "VBO X", "vbo_action": "Real Action"},
    ]
    result = _reachable_vbo_actions([{"stages": stages}])
    assert result == {"VBO X": {"Real Action"}}


# ---------------------------------------------------------------------------
# _reachable_stage_ids
# ---------------------------------------------------------------------------


def _s(sid, stype, page_id, onsuccess=None, ontrue=None, onfalse=None):
    return {
        "id": sid,
        "type": stype,
        "page_id": page_id,
        "onsuccess": onsuccess,
        "ontrue": ontrue,
        "onfalse": onfalse,
    }


def test_reachable_stage_ids_linear():
    stages = [
        _s("s1", "Start", "p1", onsuccess="s2"),
        _s("s2", "Action", "p1", onsuccess="s3"),
        _s("s3", "Action", "p1", onsuccess="s4"),
        _s("s4", "End", "p1"),
    ]
    by_id = {s["id"]: s for s in stages}
    assert _reachable_stage_ids("p1", stages, by_id) == {"s1", "s2", "s3", "s4"}


def test_reachable_stage_ids_decision_branches():
    stages = [
        _s("s1", "Start", "p1", onsuccess="s2"),
        _s("s2", "Decision", "p1", ontrue="s3", onfalse="s4"),
        _s("s3", "Action", "p1", onsuccess="s5"),
        _s("s4", "Action", "p1", onsuccess="s5"),
        _s("s5", "End", "p1"),
    ]
    by_id = {s["id"]: s for s in stages}
    assert _reachable_stage_ids("p1", stages, by_id) == {"s1", "s2", "s3", "s4", "s5"}


def test_reachable_stage_ids_orphan_not_included():
    stages = [
        _s("s1", "Start", "p1", onsuccess="s2"),
        _s("s2", "End", "p1"),
        _s("s3", "Action", "p1"),  # orphan — unreachable
    ]
    by_id = {s["id"]: s for s in stages}
    result = _reachable_stage_ids("p1", stages, by_id)
    assert "s3" not in result
    assert result == {"s1", "s2"}


def test_reachable_stage_ids_no_start_returns_empty():
    stages = [_s("s1", "Action", "p1"), _s("s2", "End", "p1")]
    by_id = {s["id"]: s for s in stages}
    assert _reachable_stage_ids("p1", stages, by_id) == set()


def test_reachable_stage_ids_only_this_page():
    """Edges pointing to stages on another page are not followed."""
    stages = [
        _s("s1", "Start", "p1", onsuccess="s2"),
        _s("s2", "Action", "p1", onsuccess="other"),
        _s("other", "Action", "p2"),
    ]
    by_id = {s["id"]: s for s in stages}
    result = _reachable_stage_ids("p1", stages, by_id)
    assert "other" not in result


# ---------------------------------------------------------------------------
# _full_traversal (Task O: moved here from bp_html_report_v3.py so both it and
# bp_graph_v3.py share one implementation instead of two independent copies —
# bp_graph_v3.py previously imported its own from the deprecated
# bp_html_report_v2.py)
# ---------------------------------------------------------------------------


def test_full_traversal_linear_order():
    stages = [
        _s("s1", "Start", "p1", onsuccess="s2"),
        _s("s2", "Action", "p1", onsuccess="s3"),
        _s("s3", "End", "p1"),
    ]
    by_id = {s["id"]: s for s in stages}
    result = _full_traversal("p1", stages, by_id)
    assert [s["id"] for s in result] == ["s1", "s2", "s3"]


def test_full_traversal_appends_orphans_after_reached():
    """Recover/Resume-style stages with no inbound edge are appended after the
    BFS-reached ones, not dropped (unlike _reachable_stage_ids, which excludes
    them entirely) — _full_traversal must return every stage on the page.
    """
    stages = [
        _s("s1", "Start", "p1", onsuccess="s2"),
        _s("s2", "End", "p1"),
        _s("s3", "Recover", "p1"),  # orphan — no inbound edge
    ]
    by_id = {s["id"]: s for s in stages}
    result = _full_traversal("p1", stages, by_id)
    ids = [s["id"] for s in result]
    assert ids[:2] == ["s1", "s2"]
    assert ids[2] == "s3"
    assert len(ids) == 3


def test_full_traversal_no_start_returns_all_in_dict_order():
    stages = [_s("s1", "Action", "p1"), _s("s2", "End", "p1")]
    by_id = {s["id"]: s for s in stages}
    result = _full_traversal("p1", stages, by_id)
    assert [s["id"] for s in result] == ["s1", "s2"]


def test_full_traversal_only_this_page():
    stages = [
        _s("s1", "Start", "p1", onsuccess="s2"),
        _s("s2", "Action", "p1", onsuccess="other"),
        _s("other", "Action", "p2"),
    ]
    by_id = {s["id"]: s for s in stages}
    result = _full_traversal("p1", stages, by_id)
    assert "other" not in [s["id"] for s in result]
    assert len(result) == 2


# ---------------------------------------------------------------------------
# _json_default
# ---------------------------------------------------------------------------


def test_json_default_set_becomes_sorted_list():
    data = {"actions": {"Trim", "Read Text File", "File Exists"}}
    serialised = json.dumps(data, default=_json_default)
    parsed = json.loads(serialised)
    assert parsed["actions"] == sorted(["Trim", "Read Text File", "File Exists"])


def test_json_default_non_serialisable_becomes_str():
    class Custom:
        def __str__(self):
            return "custom_value"

    data = {"obj": Custom()}
    serialised = json.dumps(data, default=_json_default)
    assert json.loads(serialised)["obj"] == "custom_value"
