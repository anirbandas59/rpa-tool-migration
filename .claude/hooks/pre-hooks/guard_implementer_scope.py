#!/usr/bin/env python3
"""PreToolUse guard for the pad-implementer subagent.

Registered in .claude/agents/pad-implementer.md's own `hooks:` frontmatter (scoped to fire only
while that subagent is running — not wired globally in settings.json, since a global hook has no
reliable way to tell which subagent triggered a given tool call; a subagent-scoped hook does not
have that ambiguity).

Blocks Edit/Write calls whose target path falls outside the current task's declared file scope.
The scope is read from .claude/.active-task-scope.json, written by the /pad-task skill before it
spawns the implementer. If that file is missing or unreadable, this hook does NOT block (fails
open) - a missing scope file means /pad-review or a manual invocation is driving the subagent
without going through /pad-task, not that nothing is in scope.

Exit 0 = allow. Exit 2 + stderr reason = block (per Claude Code's PreToolUse hook contract).
"""

import json
import os
import sys

SCOPE_FILE = os.path.join(
    os.environ.get("CLAUDE_PROJECT_DIR", "."), ".claude", ".active-task-scope.json"
)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # can't parse input - don't block on our own failure

    tool_input = payload.get("tool_input", {})
    target_path = tool_input.get("file_path") or tool_input.get("path") or ""
    if not target_path:
        return 0  # nothing to check against

    if not os.path.isfile(SCOPE_FILE):
        return 0  # fail open - no active task-scope manifest, nothing to enforce

    try:
        with open(SCOPE_FILE, encoding="utf-8") as f:
            scope = json.load(f)
    except (json.JSONDecodeError, OSError):
        return 0  # unreadable/corrupt scope file - fail open rather than block everything

    paths = scope.get("paths") or []
    if not paths:
        return 0  # empty scope list means nothing declared yet - don't block

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", ".")
    abs_target = (
        target_path if os.path.isabs(target_path) else os.path.join(project_dir, target_path)
    )
    try:
        relative_target = os.path.relpath(abs_target, project_dir)
    except ValueError:
        # target_path is on a different drive than project_dir (Windows) - can't be in scope
        relative_target = target_path

    # Normalize separators and case (Windows paths are case-insensitive) so a scope entry like
    # "src/flowsmith/mapper/config.py" matches a tool-supplied absolute path on the same file
    # regardless of slash direction or drive-letter casing.
    normalized_target = os.path.normpath(relative_target).replace("\\", "/").lower()
    in_scope = not normalized_target.startswith("..") and any(
        normalized_target == os.path.normpath(p).replace("\\", "/").lower()
        or normalized_target.startswith(os.path.normpath(p).replace("\\", "/").lower() + "/")
        for p in paths
    )

    if not in_scope:
        task_id = scope.get("task_id", "?")
        print(
            f"Blocked: '{target_path}' is outside Task {task_id}'s declared file scope "
            f"({paths}). If this file genuinely needs to change, report it in your task "
            f"summary instead of editing it directly - the coordinator will decide.",
            file=sys.stderr,
        )
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
