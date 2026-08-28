#!/usr/bin/env python3
"""PreToolUse guard: block git commits whose message mentions an author/co-author.

Wired globally in .claude/settings.json's `hooks.PreToolUse` key with matcher "Bash" - applies to
every session (main or subagent), not just one agent, since CLAUDE.md's git-discipline rule
("Do not mention author name") is a repo-wide convention, not specific to the PID_171 workflow.

Rationale: the harness's own default instruction is to end every commit message with a
`Co-Authored-By: <model> <email>` trailer. This project's CLAUDE.md explicitly overrides that with
"Do not mention author name" under its git-discipline rules - several prior commits on this branch
carry the trailer anyway (made before this override was made explicit), so this hook exists to
make the rule self-enforcing going forward instead of relying on remembering it each session.

Detects a `git commit` invocation in the Bash command and blocks it if the command text contains
a co-author/sign-off trailer or a name-mention author line. This inspects the command string
itself (which contains the -m message text, however it's quoted/heredoc'd), not a parsed message -
simpler and no meaningfully higher false-positive risk, since these trailer keywords essentially
never appear in a git-commit command for any other reason.

Exit 0 = allow. Exit 2 + stderr reason = block (per Claude Code's PreToolUse hook contract).
"""

import json
import re
import sys

GIT_COMMIT_RE = re.compile(r"\bgit\s+(?:[a-z-]+\s+)*commit\b")
FORBIDDEN_PATTERNS = [
    re.compile(r"co-authored-by\s*:", re.IGNORECASE),
    re.compile(r"signed-off-by\s*:", re.IGNORECASE),
    re.compile(r"^\s*author\s*:", re.IGNORECASE | re.MULTILINE),
    re.compile(r"generated\s+(?:with|by)\s+claude", re.IGNORECASE),
]


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # can't parse input - don't block on our own failure

    if payload.get("tool_name") != "Bash":
        return 0

    command = payload.get("tool_input", {}).get("command", "")
    if not command or not GIT_COMMIT_RE.search(command):
        return 0  # not a git commit invocation - nothing to check

    for pattern in FORBIDDEN_PATTERNS:
        if pattern.search(command):
            print(
                "Blocked: this git commit's message appears to mention an author/co-author "
                f"(matched pattern: {pattern.pattern!r}). CLAUDE.md's git-discipline rules say "
                "'Do not mention author name' - remove the trailer/attribution line and retry.",
                file=sys.stderr,
            )
            return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
