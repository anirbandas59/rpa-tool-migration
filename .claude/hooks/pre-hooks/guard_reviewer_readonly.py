#!/usr/bin/env python3
"""PreToolUse guard for the pad-reviewer subagent.

Registered in .claude/agents/pad-reviewer.md's own `hooks:` frontmatter (scoped to fire only
while that subagent is running).

pad-reviewer needs Write access for exactly one thing: creating its own dated report under
docs/reviews/. It must never modify code, config, mapping data, or existing review files. This
hook enforces that narrow exception rather than a blanket block, since a blanket block would also
stop the reviewer from doing the one write action its job actually requires.

Rules:
- Edit is always blocked (the reviewer never has a reason to modify an existing file in place).
- Write is allowed only when the target path is under docs/reviews/ AND the file does not already
  exist (never overwrite a prior review - see docs/bp-to-pad-implementation-strategy-PID171.md
  section 4's "never silently overwrite" rule).
- Any other Write target is blocked.

Exit 0 = allow. Exit 2 + stderr reason = block (per Claude Code's PreToolUse hook contract).
"""

import json
import os
import sys

ALLOWED_WRITE_DIR = "docs/reviews/"


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # can't parse input - don't block on our own failure

    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {})
    target_path = tool_input.get("file_path") or tool_input.get("path") or ""
    normalized = os.path.normpath(target_path).replace("\\", "/") if target_path else ""

    if tool_name == "Edit":
        print(
            "Blocked: pad-reviewer is read-only for existing files - it must not Edit anything. "
            "Report findings in the review file instead.",
            file=sys.stderr,
        )
        return 2

    if tool_name == "Write":
        if normalized.startswith(ALLOWED_WRITE_DIR) or ("/docs/reviews/" in normalized):
            if os.path.isfile(target_path):
                print(
                    f"Blocked: '{target_path}' already exists - never overwrite a prior review. "
                    "Write a new dated file instead, per the strategy doc's review-history rule.",
                    file=sys.stderr,
                )
                return 2
            return 0  # new file under docs/reviews/ - allowed
        print(
            f"Blocked: pad-reviewer may only Write new files under {ALLOWED_WRITE_DIR} "
            f"(attempted: '{target_path}').",
            file=sys.stderr,
        )
        return 2

    return 0  # not Edit/Write - nothing for this guard to do


if __name__ == "__main__":
    sys.exit(main())
