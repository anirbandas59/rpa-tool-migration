# Review: Task 1 (rework) — 2026-08-29

**Overall: 95%**

This is a review of the **fusion-pattern-schema rework** of Task 1, whose spec was rewritten in
commit `dd32149` on top of the already-committed `method_actions` work (commit `40cd1c3`, itself
graded in `docs/reviews/1-2026-08-28.md` and `docs/reviews/1-2026-08-28-followup.md`). This is a
new dated report, not an edit of those — the prior two reports concern the `method_actions`-only
pass and the regression/encoding-defect follow-up fix; neither touched fusion patterns, which did
not exist in the spec until `dd32149`. All findings below are specific to the fusion-pattern
schema addition (`VBOFusionPattern`, `VBOEntry.fusion_patterns`, `VBORouter.resolve_fusion_pattern`),
currently **uncommitted working-tree changes** on top of `40cd1c3`.

## Scope recap

Task 1's current spec (`docs/pad-generation-task-prompts.md` lines 28-84) is schema-only: no PAD
output is produced by this task. Files in scope: `src/flowsmith/mapper/config.py`,
`src/flowsmith/mapper/vbo_router.py`, `tests/mapper/test_config.py`, `tests/mapper/test_vbo_router.py`.
The rework's added scope (Do step 3, step 5's second bullet, step 6's fusion-resolution test) is:
add `VBOFusionPattern` (`sequence`, `fused_action`, `vestigial_stages`), add `VBOEntry.fusion_patterns`,
and give the router a way to **resolve** (not detect — that's Task 1b's job) a fusion candidate
sequence it's handed, against the catalogue.

## Independent verification performed

- Confirmed via `git diff HEAD -- <4 scoped files>` that all changes are **strictly additive**:
  `config.py` gains `VBOFusionPattern` + the `fusion_patterns` field only; `vbo_router.py` gains
  two new `RoutingDecision` fields, an import, and the new `resolve_fusion_pattern()` method —
  the existing `route()` method body (the original Task 1 `method_actions` precedence logic) has
  **zero diff**, confirming it is untouched/uncontaminated by this rework (verifies reviewer
  checklist item 3).
- `uv run pytest tests/mapper/ -v` → **178 passed** (the task's literal "Done when" command),
  including 2 new `test_config.py` tests for the `fusion_patterns` field and 3 for the
  `VBOFusionPattern` model, plus 7 new `test_vbo_router.py` `TestFusionPatternResolution` tests.
  (Coverage gate reports "FAIL … 38.85%" when this subset is run alone — this is the
  known pre-existing artifact of the project's global 85% threshold being checked against a
  partial test selection, already noted in the prior Task 1 follow-up review; `mapper/config.py`,
  `mapper/vbo_router.py`, `mapper/type_mapper.py` themselves show 100% coverage in that same run.)
- `uv run pytest tests/ -q` (full suite, not just the mapper subset the implementer reported) →
  **732 passed**, coverage **93.93%** (threshold 85%, reached). No regressions anywhere in the
  suite.
- `uv run pytest tests/engine/test_scorer.py -v -k RealSampleScoring` → all **11 passed** —
  re-confirms the exact regression class the original Task 1 pass broke (invented confidence
  degradation) has **not** resurfaced in this rework.
- `uv run ruff check src/flowsmith/mapper/config.py src/flowsmith/mapper/vbo_router.py
  tests/mapper/test_config.py tests/mapper/test_vbo_router.py` → **All checks passed** (the
  UTF-8 mojibake defect from the prior `method_actions` follow-up review is not present in this
  diff and remains fixed).
- Loaded the real `mapping/vbo_catalogue.yaml` via `load_rules(force_reload=True)`: parses
  cleanly, every existing `VBOEntry` gets `method_actions == {}` and `fusion_patterns == []` by
  default (real data population is Task 2b's job, correctly out of scope here) — confirms
  reviewer checklist item 4.
- Read `resolve_fusion_pattern()` in full and traced its contract against what a Task 1b consumer
  in `ast/builder.py` would need (checklist item 1): it takes `(vbo_name, method_sequence:
  list[str])` and returns `(VBOFusionPattern | None, vestigial_method_names: list[str])`. This
  matches the task's own framing precisely — Task 1's Do step 5 explicitly says the router "only
  needs to resolve a sequence **it's given** against the catalogue's fusion patterns," and
  explicitly defers *detection* of adjacent stages to Task 1b. The method does exactly that: exact
  ordered-sequence match against `entry.fusion_patterns[i].sequence`, fuzzy VBO name lookup via the
  existing `get_vbo_entry_fuzzy`, and a safe `(None, [])` for unknown VBOs/no match — never raises,
  as required. This is a real, connectable primitive for Task 1b, not a disconnected/plausible-only
  addition.
- Checked `vestigial_stages` handling (checklist item 2): the second tuple element returned is
  exactly `pattern.vestigial_stages` (method names, e.g. `["Create Instance"]`) — verified against
  Task 1b's own Do step 2 wording ("mark the vestigial stage(s) so the generator emits nothing
  standalone for them") — Task 1b will map these method names back to concrete stage IDs itself
  (it has the stage objects; the router only has method names), which is the correct division of
  responsibility per Task 1's explicit "Out of scope: detecting which adjacent stages form a
  fusion candidate ... (Task 1b)" line.
- **Gap found**: `RoutingDecision` was extended with two new fields, `is_vestigial: bool` and
  `fused_action_template: str` (summary's item 3) — but neither field is ever set by any method in
  `vbo_router.py`. `route()`'s body is untouched (confirmed above) and never populates them;
  `resolve_fusion_pattern()` returns a bare tuple, not a `RoutingDecision`, so it never touches
  them either. A repo-wide grep (`src/`) confirms zero non-declaration references. No test in the
  diff exercises either field (`test_vbo_router.py`'s new `TestFusionPatternResolution` class only
  asserts against the tuple return of `resolve_fusion_pattern`, never against a `RoutingDecision`
  instance's `is_vestigial`/`fused_action_template`). This is exactly the "plausible-looking but
  disconnected addition" pattern the review brief flagged to check for — it was not requested by
  Task 1's Do steps (which only ask for `resolve_fusion_pattern()`), does no harm (both fields
  default safely and don't perturb any existing consumer since `RoutingDecision` is
  `frozen`/immutable and additive fields don't break existing construction), but it is dead code
  today and its presence could mislead a Task 1b implementer into assuming `route()`/
  `RoutingDecision` itself already carries fusion resolution, when in fact `resolve_fusion_pattern()`
  is the only wired path. Worth removing or wiring before/during Task 1b, not blocking.

## Score breakdown

| Dimension | Score | Evidence |
|---|---|---|
| Structural | N/A | Schema-only task; no flow/workflow output shape produced. |
| `FUNCTION` functional fidelity | N/A | No `FUNCTION` body generation in this task's scope. |
| VBO/action fidelity | 90% | `VBOFusionPattern`/`fusion_patterns` schema correctly expresses §B_FUSION's sequence/fused_action/vestigial_stages concept (verified against the architecture doc's own Excel worked example, which the tests cite verbatim: `Excel.LaunchExcel.LaunchAndOpenUnderExistingProcess`, `Excel.CloseExcel.Close`). `resolve_fusion_pattern()`'s contract (given a sequence, resolve against the catalogue; detection is Task 1b's job) matches the task spec precisely and is a genuinely connectable primitive. Docked 10% for the dead `RoutingDecision.is_vestigial`/`fused_action_template` fields — declared but never populated by any code path, untested, and not requested by the Do steps (real data population is correctly deferred to Task 2b, not penalized here). |
| Naming convention | N/A | No PAD/architecture-doc §A4 naming surfaces in a Pydantic schema task. |
| Error-handling/stop/consecutive-exception | N/A | Not relevant to a schema/router task; `resolve_fusion_pattern()`'s own "never raises" contract (§ design goal, not §A5-7) is verified — returns `(None, [])` for unknown VBOs/no match rather than raising, consistent with the router's existing `route()` never-raises behavior. |
| Well-formedness | 100% | `uv run pytest tests/mapper/ -v` → 178/178 pass (task's literal Done-when command). Full suite `uv run pytest tests/ -q` → 732/732 pass, 93.93% coverage (threshold 85%). `tests/engine/test_scorer.py::TestRealSampleScoring` → 11/11 pass (re-verifies the original Task 1 regression stays fixed). `uv run ruff check` on all four scoped files → clean. Real `mapping/vbo_catalogue.yaml` loads without error; `fusion_patterns` defaults to `[]` for every existing entry (no data yet — correctly Task 2b's job). |

## Most significant gaps

- `RoutingDecision.is_vestigial` and `RoutingDecision.fused_action_template` are declared but
  never set or tested anywhere — dead fields, not requested by the task spec, and not disclosed as
  a deviation in the implementer's summary (which claims "Deviations from the task spec: None").
  Should either be wired (if there's a design reason `route()` itself should surface fusion state)
  or removed before Task 1b starts building against this router, to avoid ambiguity about which
  path (`route()` vs. `resolve_fusion_pattern()`) is the real integration point.
- Everything else the task's Do steps specify is implemented, tested, and verified independently
  (not just trusted from the summary): schema fields, YAML-optionality, router precedence
  untouched, `resolve_fusion_pattern()`'s signature/behavior aligned with what Task 1b will need,
  full test suite and `TestRealSampleScoring` clean, ruff clean.

## Verdict

pass (minor, non-blocking cleanup recommended: remove or wire the two dead `RoutingDecision`
fields before/during Task 1b, so Task 1b's implementer isn't misled about the router's actual
integration surface).
