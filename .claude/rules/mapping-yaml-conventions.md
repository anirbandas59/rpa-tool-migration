---
paths:
  - "mapping/**/*.yaml"
---

# `mapping/*.yaml` editing conventions

These files (`stage_rules.yaml`, `vbo_catalogue.yaml`) drive the BP-to-PAD generator's stage-type
and VBO-action mapping decisions — they are consumed as data by `src/flowsmith/mapper/`, not
inspected casually. Wrong data here produces wrong generated PAD code silently.

**Discipline (from `docs/bp-to-pad-implementation-strategy-PID171.md` §2.4):**
- Never add a `pa_target_action`/`method_actions` entry without a citation to
  `docs/pad-reference/vbo-action-mapping.md` or `docs/bp-to-pad-architecture-PID171.md`. A row
  with no confirmed real PAD call gets a low `confidence_base` and a `**STOP**`-style note in
  `notes`, not an invented action.
- Don't assume an existing entry is already correct just because a VBO/stage-type name matches —
  several entries in this project were generated from a *different* BP sample (`PID_0127`) and
  contradict now-confirmed real PAD behavior for PID_171 (e.g. wrong `runtime`, wrong `pa_module`,
  wrong `method_patterns`). Cross-check against the sources above before trusting what's there.
- `CHOICE` stays absent from `stage_rules.yaml` — do not add a speculative row for it; `CLAUDE.md`
  explicitly says not to implement it until a real BP sample with `Choice` stages is obtained.
- After any edit, confirm the file still parses (`uv run python -c "import yaml;
  yaml.safe_load(open('mapping/<file>.yaml'))"`) and the relevant `tests/mapper/` suite passes.
