"""
Shared utilities for bp_html_report_v3.py and bp_report_v3.py.

Functions
---------
_reachable_vbo_actions  – collect every VBO object/action called across a list of processes
_reachable_stage_ids    – BFS from the Start stage on a page, following success/true/false edges
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


def _json_default(o: object) -> object:
    """``default=`` handler for :func:`json.dump` / :func:`json.dumps`.

    Converts:
    * ``set``   → ``sorted(list(o))``
    * anything else → ``str(o)``
    """
    if isinstance(o, set):
        return sorted(o)
    return str(o)
