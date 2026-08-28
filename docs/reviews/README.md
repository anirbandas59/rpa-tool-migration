# Reviews

One file per `pad-reviewer` run, named `<task-id>-<YYYY-MM-DD>.md` (e.g. `3a-2026-08-29.md`).

**Never overwrite an existing review file.** If a task is reviewed more than once (e.g. after a
re-implementation pass), write a new dated file and note in its opening paragraph what changed
since the previous review — the history is the point, not just the latest verdict.

See `docs/bp-to-pad-implementation-strategy-PID171.md` §4 for the scoring methodology every
review follows, and `.claude/agents/pad-reviewer.md` for the agent that produces these.
