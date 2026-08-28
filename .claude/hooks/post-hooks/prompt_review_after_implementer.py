#!/usr/bin/env python3
"""SubagentStop hook: nudges the coordinator to invoke pad-reviewer after pad-implementer finishes.

Wired globally in .claude/settings.json's `hooks.SubagentStop` key with matcher "pad-implementer"
(SubagentStop hooks support agent-type-name matchers at the settings.json level, unlike PreToolUse
- this is the automatic "post hook" review trigger the request asked for, as an alternative to the
manual /pad-review command).

Always exits 0 (this hook never blocks the subagent's own completion) but returns a "block"
decision in its structured output for the *coordinator's turn* - i.e. it doesn't stop the
implementer, it stops the coordinating session from quietly ending its own turn without following
through to the review step. If the coordinator is already mid-way through the documented
/pad-task cycle (which spawns pad-reviewer itself, right after this fires), this is a harmless
reminder; it only matters when pad-implementer was invoked some other way (e.g. directly, or via
/pad-review's read-only review-only path bypasses this - that path never spawns an implementer -
or a bespoke prompt) and the review step could otherwise be missed.
"""

import json
import sys


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = {}

    agent_type = payload.get("agent_type", "pad-implementer")

    result = {
        "hookSpecificOutput": {
            "hookEventName": "SubagentStop",
            "decision": "block",
            "reason": (
                f"The '{agent_type}' subagent just finished. Before ending this turn, invoke "
                "the pad-reviewer subagent on the same task (per docs/bp-to-pad-implementation-"
                "strategy-PID171.md section 4's review methodology) unless a review was already "
                "run for this exact task in this turn."
            ),
        }
    }
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
