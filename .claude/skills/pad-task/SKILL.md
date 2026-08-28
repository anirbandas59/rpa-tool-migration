---
name: pad-task
description: Coordinates one full implement-then-review cycle for a BP-to-PAD PID_171 migration task. Reads the task from docs/pad-generation-task-prompts.md, spawns pad-implementer to do the work, then spawns pad-reviewer to grade it, and relays the review to the user.
argument-hint: "[task-id]"
---

You are acting as **coordinator** for one task from `docs/pad-generation-task-prompts.md`. The
task ID is `$1`. Run this whole cycle in this conversation (you are the coordinator — do not fork yourself into a subagent for this).

1. Read `docs/pad-generation-task-prompts.md` and find the `## Task $1` section. If it doesn't
   exist, tell the user and stop — don't guess at a task.
2. Check the task's "Depends on" line. If a dependency task hasn't been completed yet (check
   `docs/reviews/` for a prior passing review of it, or ask the user if unsure), tell the user and ask whether to proceed anyway or do the dependency first — don't silently skip the check.
3. Write the task's declared "Files in scope" to `.claude/.active-task-scope.json` as `{"task_id":
"$1", "agent": "pad-implementer", "paths": [...]}` — this is what
   `.claude/hooks/pre-hooks/guard_implementer_scope.py` reads to enforce the scope boundary while the implementer subagent runs.
4. Spawn the `pad-implementer` subagent (via the `Agent` tool, `run_in_background: false` — your next step depends on its result) with a prompt telling it the task ID (`$1`) and pointing it at `docs/pad-generation-task-prompts.md` for the details, per that agent's own instructions.
5. Once it reports back, spawn the `pad-reviewer` subagent (also foreground) with the task ID and the implementer's full summary, asking it to review per its own instructions.
6. Relay the reviewer's `%` + per-dimension breakdown + gap list to the user, plainly — don't
   summarize away the specifics.
7. If the reviewer's verdict is "needs another implementation pass," ask the user whether to
   re-invoke `pad-implementer` with the reviewer's findings appended (do this automatically only if the user has told you to loop without asking each time); if "pass," mark the task done and suggest the next task in dependency order. If "blocked pending a design decision," surface the specific decision needed rather than guessing at it yourself.
8. Clear `.claude/.active-task-scope.json` (or overwrite it to an empty/inert state) once the
   cycle ends, so it doesn't stale-guard an unrelated later action.
