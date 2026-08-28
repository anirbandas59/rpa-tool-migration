# BP → PAD (PID_171) coding-phase workflow

This project is mid-way through transforming `samples/blueprism/PID_0171.bprelease` into the real
Power Automate Desktop/Cloud solution shape (2 Desktop Flows + 2 Cloud Flows, BP pages as `FUNCTION`s
inside one consolidated Desktop Flow body per role) — not the flattened one-workflow-per-page
output the generator currently produces.

**Read these in order before touching `src/flowsmith`, `mapping/`, or the generator/parser code:**
1. `docs/bp-to-pad-architecture-PID171.md` — the *what*/*why* ground truth (real 4-flow
   architecture, stage/VBO mapping rules, naming/error/stop conventions).
2. `docs/bp-to-pad-implementation-strategy-PID171.md` — the *how* (codebase audit, task
   sequencing, reviewer scoring methodology).
3. `docs/pad-generation-task-prompts.md` — the actual per-task work orders. Nothing gets
   implemented outside a named task from this file.
4. `docs/pad-reference/` — extracted ground-truth PAD source
   (`DF_PID_171_US_Loader.robin.txt`, `DF_PID_171_US_LIMS_Prelude_Main.robin.txt`) and
   `vbo-action-mapping.md` (the canonical VBO → PAD action table).

**Method:** the top-level session acts as coordinator, driven by `/pad-task <task-id>` (implement
+ auto-review one task) or `/pad-review <task-id>` (review only). The coordinator spawns the
`pad-implementer` subagent (Haiku) to do the work, then the `pad-reviewer` subagent to grade it.
Neither subagent picks its own task or scope — both are told exactly what to do by the invoking
skill/coordinator.

**Core discipline, binding on every change in this initiative:**
- Every concrete value (a PAD syntax template, a stage-type mapping, a VBO action) must trace to a
  citation in the docs above — never an invented, plausible-looking guess.
- Stay inside a task's declared file scope; if more is needed, report it rather than doing it.
- Never silently drop an untranslatable BP construct — leave a `# TODO` comment naming what it was
  and why (usually: needs a UI selector, per architecture doc §B9).
- Generated output goes to `outputs/generated/PID_0171/`. Review reports go to `docs/reviews/`,
  one dated file per review — never overwrite a prior one.

This file is global (loaded at session start) precisely so this context is available even if a
task is worked on outside the `/pad-task` flow (e.g. by hand, or by a differently-invoked agent).
