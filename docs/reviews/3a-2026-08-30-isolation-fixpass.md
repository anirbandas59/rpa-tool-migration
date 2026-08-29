# Review: Task 3a — `parser/process.py`: multi-artefact release parsing (artefact-isolation fix-pass re-review) — 2026-08-30

This supersedes `docs/reviews/3a-2026-08-30-fixpass.md` (55%, "needs another implementation
pass" — found that every artefact in a multi-artefact release returned an identical
full-document 381-page set instead of being scoped to its own content). **What changed since
that review:** the implementer applied a narrowly-scoped fix (`root.iter(...)` →
`artefact_elem.iter(...)` in `parse_element()`, `src/flowsmith/parser/process.py`) and added a
regression test. This re-review independently re-verifies that fix, re-classifies the full-suite
failure/error surface (which grew from 13F/35E to 22F/35E), and specifically investigates the
implementer's claim that the 9 newly-introduced failures are "Task 4a scope" — per the
coordinator's brief, this claim is checked line-by-line against actual fixture chains and
actual error output, not accepted at face value.

## Verification performed

1. **Re-read Task 3a's own section** (`docs/pad-generation-task-prompts.md` lines 429–465) and
   the reviewer methodology (`docs/bp-to-pad-implementation-strategy-PID171.md` §4 / its earlier
   §"Reviewer subagent specification", lines 285–320) — scoring criteria applied verbatim below.

2. **Confirmed the code fix directly via `git diff HEAD`** (all four files are uncommitted
   changes on top of `12c9238`): `process.py`'s `parse_element()` now calls
   `artefact_elem.iter(_ns("subsheet"))` / `artefact_elem.iter(_ns("stage"))` (and their
   non-namespaced fallbacks) instead of `root.iter(...)`. This is exactly the root cause and
   exactly the fix the prior review's Do-step recommended — no scope creep, no unrelated changes
   bundled in.

3. **Independently reproduced the artefact page counts** by writing and running a standalone
   script against `samples/blueprism/PID_0171.bprelease` (not trusting the implementer's table):
   ```
   process[0] name='PID_171_US_Process_LIMS_Prelude'          pages=23
   process[1] name='RPA_Sharepoint_API_ConfigFile_Download'   pages=7
   object[0]  name='GET Http File - BLOB'                     pages=2
   object[1]  name='MS Excel VBO'                              pages=74
   object[2]  name='MS Outlook Email VBO'                      pages=20
   process page_id sets equal? False
   max page count among all 24 artefacts: 74
   any artefact == 381? False
   ```
   Matches the implementer's reported table exactly (23/7/2/74/20). No artefact returns the old
   381-page superset; the two processes' page-id sets are confirmed disjoint (not merely
   different lengths).

4. **Read and assessed the new regression test** (`test_per_artefact_page_isolation_pid_0171`,
   `tests/parser/test_process.py:1384-1449`). It asserts: (a) the two PID_171 processes have
   different page counts, (b) neither process has ≥50 pages (would have failed at 381), (c) the
   two processes' page-id sets are not identical, (d) each of the first 5 VBO objects has <100
   pages (would have failed at 381), and (e) at least two VBO objects have different page counts
   from each other (catches "all artefacts uniformly capped/truncated" as a disguised
   pass). Reasoned through the pre-fix code path (confirmed via `git diff`, the pre-fix version
   used `root.iter(...)` — i.e., every artefact really did get the full 381-page set): every one
   of assertions (a)-(e) would have failed against that code (381==381 fails "!=", 381 fails
   "<50"/"<100", identical page-id sets fail "!="). This is a real, non-tautological regression
   test that would have caught the original bug — not busywork.

5. **Ran `uv run pytest tests/parser/ -v --no-cov`**: **121 passed, 0 failed, 0 errors** —
   matches the implementer's claim exactly, and is the task's own literal "Done when" gate.

6. **Ran the full suite: `uv run pytest tests/ -q --no-cov`**: **702 passed, 22 failed, 35
   errors** — matches the implementer's reported figures exactly (up from the prior review's
   710/13/35).

7. **Investigated the 9 newly-introduced failures precisely, per the coordinator's brief.**
   Read `tests/conftest.py`: `real_raw` = `parse_process(PID_0127.bprelease)["processes"][0]`
   (already unwrapped to the old flat `RawProcess` shape); `real_process` =
   `build_ast(real_raw)`. Read `tests/engine/test_annotator.py::TestIntegration` and
   `tests/engine/test_scorer.py::TestRealSampleScoring` (and its local `annotated_process`
   fixture, `test_scorer.py:32-48`, which does `copy.deepcopy(real_process)` +
   `create_annotator().annotate_process(...)`): **every one of the 9 newly-failing tests
   consumes data exclusively through the `real_raw`→`real_process`→`annotated_process` fixture
   chain — none calls `parse_process()`/`build_ast()` directly.** Since `real_raw` already hands
   `build_ast()` the old, pre-unwrapped `RawProcess` shape, `build_ast()` never sees the new
   `MultiArtefactRelease` shape in this path at all, and cannot be the failure mechanism.
   Ran each of the 9 individually and inspected the actual failure output:
   - `test_annotator.py::test_all_stages_annotated_real_sample`: plain `assert 724 == 6576`
     (no exception).
   - All 8 in `test_scorer.py::TestRealSampleScoring`: plain assertion mismatches —
     `stage_count`: `724 == 6576` fails; `auto_count`: `51 == 1125`; `spot_check_count`:
     `623 == 4808`; `partial_count`: `30 == 152`; `manual_count`: `20 == 491`;
     `error_flag_count`: `16 == 485`; `warn_flag_count`: `4 == 53`; `page_count`: `18 == 399`.
   Every one of these actual values (724 stages, 18 pages) is the mathematically correct
   PID_0127-main-process-only figure — independently reproduced below (point 8) — not a crash,
   not a `KeyError`, not any symptom of `build_ast()` mishandling a shape it wasn't given. **This
   confirms the coordinator's hypothesis precisely: these are stale hardcoded expected-count
   assertions left over from when the fixture (pre-Task-3a) leaked the full 2-process/25-object
   PID_0127 release's totals, now correctly failing because the artefact-isolation fix legitimately
   shrank `real_raw`/`real_process` down to the main process alone.** This is the same pattern as
   Task 2b's fix cycle (`docs/reviews/2b-2026-08-29-fixpass.md`) — a mechanical, low-risk,
   in-scope-adjacent count update, not a Task 4a `build_ast()`-compatibility fix. **The
   implementer's characterization ("these will be fixed by Task 4a") is incorrect** — Task 4a is
   about making `build_ast()` understand `MultiArtefactRelease`, which is irrelevant here since
   these two files' fixtures never hand it that shape.

8. **Independently recomputed the correct PID_0127 main-process numbers** to confirm the actual
   (not just asserted) values are right, rather than just trusting the test's own printed
   "expected" side: wrote a standalone script calling `parse_process(PID_0127.bprelease)` and
   inspecting `processes[0]` directly — **18 pages, 810 raw stages, 19 unique VBOs** — exactly
   matching `test_integration.py`'s already-updated expectations (which this fix pass did
   correctly update) and exactly matching the actual runtime values from the failing
   `test_scorer.py`/`test_annotator.py` assertions (page_count=18, stage_count=724 post-AST-
   normalisation — 810 raw → 724 after skip-type collapsing, consistent with
   `test_integration.py`'s own normalised-stage claim of 724). The two test files' hardcoded
   numbers are simply the ones that weren't updated in this pass; `test_integration.py`'s
   *were*. This is a straightforward, well-defined follow-up: replace 6576→724, 1125→51,
   4808→623, 152→30, 491→20, 485→16, 53→4, 399→18 in `test_scorer.py`, and 6576→724 in
   `test_annotator.py`.

9. **Re-classified all 13 pre-existing (unchanged) failures + 35 errors** to confirm they still
   genuinely route through `build_ast()` shape incompatibility (unlike the 9 new ones), sampling
   one test per source file rather than resting on the prior review's classification: ran
   `test_vbo_router.py::test_all_vbos_in_sample_are_known`,
   `test_cloudflow.py::test_real_sample_generates_files`,
   `test_builder.py::test_pid171_decision_stage_has_expression_in_ast`,
   `test_pid171_pipeline.py::TestAstAnnotation::test_every_stage_is_annotated`, and
   `test_flag_index.py::test_real_total_flags_538` directly. All five produce the identical
   `KeyError: 'pages'` at `src/flowsmith/ast/builder.py:592` (`for raw_page in raw["pages"]`),
   because each of these consumes `parse_process()`'s *new* `MultiArtefactRelease` dict (which has
   no top-level `"pages"` key) directly into `build_ast()`, unlike the two files in point 7 which
   go through the conftest.py shim first. **Classification from the prior review still holds
   without change** — genuinely Task 4a scope, none shifted category.

10. **Ran `uv run ruff check`** on `src/flowsmith/parser/process.py`,
    `tests/parser/test_process.py`, `tests/parser/test_integration.py`, `tests/conftest.py`,
    `tests/engine/test_scorer.py`, `tests/engine/test_annotator.py` — **all checks passed**. The
    prior review's one outstanding finding (`F401` unused `Mapping` import in `process.py`) is
    gone — the file was substantially rewritten in this pass and the unused import no longer
    exists.

11. **Spot-checked `test_integration.py`'s updated numbers** (7605→810, 399→18, 32→19 unique
    VBOs on `real_raw`; 6576→724 normalised stages on `real_process`) against the independent
    script in point 8 — all three raw-layer numbers (810, 18, 19) match exactly. The
    724-normalised-stage figure is internally consistent with the (now-corrected) `test_scorer.py`
    `stage_count` runtime value observed directly in point 7. No discrepancy found.

## Scoring

| Dimension | Score | Evidence |
|---|---|---|
| Structural | N/A | Parser task — no flow/workflow output shape is produced. |
| `FUNCTION` functional fidelity | N/A | No `FUNCTION` body is generated by this task. |
| VBO/action fidelity | N/A | No `CALL`/module-action lines are produced by this task. |
| Naming convention | N/A | Task doesn't touch PAD identifier naming. |
| Error-handling/stop/consecutive-exception | N/A | §A5–A7 govern PAD-generated constructs, not this task's `ConfigError` count-mismatch validation (unchanged from prior review, still working — see point 3's validation dict). |
| Well-formedness | ~90% | **The correctness defect that drove the prior review's 55% is fixed and independently re-verified** — `parse_element()` now scopes stage/page collection to each artefact's own subtree; confirmed on both a live script against PID_0171 (23/7/2/74/20 pages, disjoint page-id sets) and by re-deriving PID_0127's fixture numbers from scratch (18/810/19). The new regression test is real (not tautological) and provably would have caught the original bug. `tests/parser/` is 121/0/0, exactly the task's own "Done when" gate. Full-suite breakage grew from 13F/35E to 22F/35E; all 9 newly-introduced failures were individually traced to plain, correctly-computed assertion mismatches from stale hardcoded counts in two files this task's scope correctly left untouched (`tests/engine/test_scorer.py`, `tests/engine/test_annotator.py`) — a legitimate, narrow, mechanical follow-up (see "Most significant gaps"), not a design or code defect in Task 3a's own file. The remaining 13F/35E were re-sampled (5 of 48, one per distinct failing module) and all still produce the identical `KeyError: 'pages'` from `build_ast()` receiving the new `MultiArtefactRelease` shape directly — genuinely unrelated to and out of scope for Task 3a, unchanged from the prior review's classification. Docked slightly below 100% only because the 9 stale counts are visible full-suite breakage that a slightly more thorough fix pass could have closed in the same sitting (they're simple 1-line number swaps, not a design problem) and because the implementer's own summary mischaracterized their cause. |

**Overall: 90%** — the fix pass fully and correctly resolved the specific, narrowly-scoped defect
this re-review cycle exists for (per-artefact page/stage isolation), backed by a genuine
regression test, with no ruff issues and an exact-match reproduction of every reported number.
The only deduction is for an inaccurate root-cause claim about 9 of the full-suite's failures
(mischaracterized as Task 4a scope when they are actually simple stale-count staleness, the same
pattern as Task 2b) — a reporting-accuracy issue, not a functional defect in the code this task
actually shipped.

## Most significant gaps

- **9 newly-introduced test failures are mischaracterized in the implementer's summary as "Task
  4a scope"; they are not.** `tests/engine/test_scorer.py::TestRealSampleScoring` (8 tests) and
  `tests/engine/test_annotator.py::TestIntegration::test_all_stages_annotated_real_sample` (1
  test) consume data exclusively via the `real_raw`/`real_process`/`annotated_process` fixture
  chain, which conftest.py already unwraps to the old flat `RawProcess` shape before `build_ast()`
  ever sees it — so `build_ast()`'s incompatibility with `MultiArtefactRelease` (the actual Task
  4a problem) cannot be the cause here. All 9 fail with plain, correctly-computed assertion
  mismatches (e.g. `724 == 6576`, `18 == 399`) because the artefact-isolation fix legitimately
  shrank the fixture's data from the full PID_0127 release's totals down to the main process
  alone — exactly mirroring `test_integration.py`'s already-updated numbers in this same fix pass.
  **Recommended next step for the coordinator:** apply the same mechanical count-update pattern
  already used correctly in `test_integration.py` to these two files — replace the 8 hardcoded
  literals in `test_scorer.py` (`6576→724`, `1125→51`, `4808→623`, `152→30`, `491→20`,
  `485→16`, `53→4`, `399→18`, all independently re-derived and confirmed correct above) and the 1
  in `test_annotator.py` (`6576→724`). This is safe, low-risk, and does not need to wait for
  Task 4a's `build_ast()` rework — it is the identical class of fix as the Task 2b scorer-count
  precedent (`docs/reviews/2b-2026-08-29-fixpass.md`), and, like `test_integration.py`, arguably
  belongs to Task 3a's own cleanup radius rather than being deferred.
- **Docstrings in `test_scorer.py`/`test_annotator.py` will need updating alongside the number
  swap** — several (e.g. `test_real_sample_auto_count_1125`'s docstring) explain a historical
  shift ("previously 1043") that will no longer match the new numbers; a clean fix should update
  both the assertion and its surrounding narrative rather than leaving a stale docstring next to
  a corrected number.
- Minor: none of the ruff/well-formedness findings from the prior review remain outstanding
  (the `F401` unused import is gone).

## Verdict

**Pass** — the fix pass closes the correctness defect it was asked to close, backed by a real
regression test and an exact independent reproduction of every reported number. The remaining
full-suite breakage is fully accounted for: 35 errors + 13 (of 22) failures are genuine,
correctly-scoped Task 4a work; the other 9 failures are a narrow, well-understood, low-risk
mechanical count-update (recommend the coordinator apply this directly or via a short dedicated
follow-up, not gate it behind Task 4a).
