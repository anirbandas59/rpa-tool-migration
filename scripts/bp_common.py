"""
Shared utilities for bp_html_report_v3.py, bp_graph_v3.py, and bp_report_v3.py.

Functions
---------
_reachable_vbo_actions  – collect every VBO object/action called across a list of processes
_reachable_stage_ids    – BFS from the Start stage on a page, following success/true/false edges
_full_traversal         – BFS from Start returning ALL stages on a page in traversal order
_json_default           – json.dump default= handler that serialises sets and unknown objects
"""

from __future__ import annotations

from collections import deque


def _reachable_vbo_actions(procs: list[dict]) -> dict[str, set[str]]:
    """Return a mapping of vbo_object_name -> set[vbo_action_name] for every VBO
    action actually called across all stages in *procs*.

    Parameters
    ----------
    procs:
        List of parsed process result dicts.  Each dict must contain a ``"stages"``
        key whose value is a list of stage dicts.  Each stage dict may carry
        ``"vbo_object"`` (str | None) and ``"vbo_action"`` (str | None) keys.

    Returns
    -------
    dict[str, set[str]]
        Only entries where both ``vbo_object`` and ``vbo_action`` are non-empty
        strings are included.
    """
    result: dict[str, set[str]] = {}
    for proc in procs:
        for stage in proc.get("stages", []):
            obj = stage.get("vbo_object") or ""
            action = stage.get("vbo_action") or ""
            if obj and action:
                result.setdefault(obj, set()).add(action)
    return result


def _reachable_stage_ids(
    page_id: str,
    stages: list[dict],
    stage_by_id: dict[str, dict],
) -> set[str]:
    """Return the set of stage IDs reachable from the ``Start`` stage on *page_id*
    via BFS following ``onsuccess``, ``ontrue``, and ``onfalse`` edges.

    Parameters
    ----------
    page_id:
        The page whose ``Start`` stage is the BFS root.
    stages:
        All stage dicts for the process (used to locate the Start stage on the page).
    stage_by_id:
        Mapping of stage ``id`` -> stage dict for fast lookup.

    Returns
    -------
    set[str]
        IDs of reachable stages that belong to *page_id*.  Returns an empty set
        if no ``Start`` stage exists on the page.
    """
    # Find the Start stage on this page.
    start_stage = next(
        (s for s in stages if s.get("page_id") == page_id and s.get("type") == "Start"),
        None,
    )
    if start_stage is None:
        return set()

    visited: set[str] = set()
    queue: deque[str] = deque([start_stage["id"]])

    while queue:
        sid = queue.popleft()
        if sid in visited:
            continue
        stage = stage_by_id.get(sid)
        if stage is None:
            continue
        # Only count stages that belong to this page.
        if stage.get("page_id") != page_id:
            continue
        visited.add(sid)
        for edge in ("onsuccess", "ontrue", "onfalse"):
            next_id = stage.get(edge)
            if next_id and next_id not in visited:
                queue.append(next_id)

    return visited


def _full_traversal(page_id: str, stages: list[dict], stage_by_id: dict[str, dict]) -> list[dict]:
    """BFS from the Start stage on *page_id*, following ``onsuccess``, ``ontrue``,
    and ``onfalse`` edges, returning ALL stages on that page in traversal order.

    Unlike :func:`_reachable_stage_ids`, this returns the full stage dicts (not
    just IDs) in a stable rendering order, and never drops a stage: any stage not
    reached via the BFS (typically Recover/Resume entry points, which have no
    inbound explicit edge) is appended after the reached ones, in dict order.
    Used wherever a page's stages need to be rendered or drawn in a sensible
    order — the HTML report's page sections and the Graphviz page-graph builder
    both need this same ordering, hence its home here rather than in either.

    Parameters
    ----------
    page_id:
        The page whose Start stage is the BFS root.
    stages:
        All stage dicts to search (only those with a matching ``page_id`` are
        considered).
    stage_by_id:
        Present for signature parity with call sites that already have it on
        hand; not used internally (stage lookup here is by page_id, not by id).

    Returns
    -------
    list[dict]
        Every stage dict on *page_id*: BFS-reached ones first, in traversal
        order, followed by any unreached ones. If no Start stage exists on the
        page, returns all of the page's stages in their original (dict) order.
    """
    page_map = {s["id"]: s for s in stages if s["page_id"] == page_id}
    start = next((s for s in page_map.values() if s["type"] == "Start"), None)
    if not start:
        return list(page_map.values())

    visited: list[dict] = []
    seen: set[str] = set()
    queue: deque[str] = deque([start["id"]])

    while queue:
        sid = queue.popleft()
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


def _json_default(o: object) -> object:
    """``default=`` handler for :func:`json.dump` / :func:`json.dumps`.

    Converts:
    * ``set``   → ``sorted(list(o))``
    * anything else → ``str(o)``
    """
    if isinstance(o, set):
        return sorted(o)
    return str(o)
