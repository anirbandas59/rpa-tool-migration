---
paths:
  - "src/flowsmith/generator/**/*.py"
  - "templates/**/*.j2"
---

# `src/flowsmith/generator/` target-shape reminder

The generator is being redesigned away from its current output shape. Before editing anything
under `generator/` or `templates/`, confirm which shape your change is producing:

**Old (wrong) shape, still what the code does today unless a task has already fixed it:** one PAD
`.robin` file / one `<Workflow>` XML element **per BP page** — against PID_171's 24 main-process
pages this produces far more workflows than the real solution has.

**Target shape (`docs/bp-to-pad-architecture-PID171.md` §A2/§A3):** exactly 2 Desktop Flows
(Loader, Performer) + 2 Cloud Flows (orchestrator + config-read child flow), where each BP page
becomes one `FUNCTION '<page name>' ... END FUNCTION` block **inside** the appropriate Desktop
Flow's single `.robin` body (per its Loader/Performer role — architecture doc §B11's hard split at
BP stage `85fbb578`, `Get Next Item`), not a separate file or workflow of its own.

If you're touching this code outside a task that's explicitly about the consolidation itself
(`docs/pad-generation-task-prompts.md` Tasks 5a/6a), don't accidentally revert consolidated output
back to the old per-page shape, and don't build new per-page-file logic as if it were still
correct.

Also apply, on top of the above: `CLAUDE.md`'s existing rules for this layer still hold (Jinja2
templates only, never inline string concatenation for generated code; typed exceptions, never
return `None` on failure).
