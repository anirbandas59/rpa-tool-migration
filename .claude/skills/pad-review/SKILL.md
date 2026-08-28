---
description: Manually triggers a pad-reviewer pass for a BP-to-PAD PID_171 migration task that's already been implemented, without going through /pad-task's implementation step. Use when you want a review re-run (e.g. after fixing something by hand) or a fresh look without re-implementing.
argument-hint: "[task-id]"
---

The task ID is `$1`. Read `docs/pad-generation-task-prompts.md`'s `## Task $1` section so you
know what's being reviewed, then spawn the `pad-reviewer` subagent (via the `Agent` tool,
`run_in_background: false`) with the task ID and any context you have about what was implemented
(recent git diff for the files in that task's scope is a reasonable substitute for an
implementer's summary if one isn't available — check `git log`/`git diff` for those files before
spawning the reviewer, so it isn't reviewing blind).

Relay the reviewer's `%` + per-dimension breakdown + gap list to the user plainly once it reports
back — don't summarize away the specifics.
