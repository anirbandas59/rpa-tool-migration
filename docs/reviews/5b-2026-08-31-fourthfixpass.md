# Review: Task 5b — 2026-08-31 (4th fix-pass, 5th implementation cycle)

**Overall: 58%**

Fifth review cycle for Task 5b. Prior reviews: `docs/reviews/5b-2026-08-31.md` (1st, 15%),
`docs/reviews/5b-2026-08-31-fixpass.md` (2nd, 32%), `docs/reviews/5b-2026-08-31-secondfixpass.md`
(3rd, 38%), `docs/reviews/5b-2026-08-31-thirdfixpass.md` (4th, 44%, "needs another
narrowly-scoped pass" — root-caused to exactly two gaps: (a) `variable_name_mapping` never
threaded through `_split_page_into_functions`, causing `Retry Count`/`Retry Limit` to diverge on
the `split`-shape `Result Entry` page; (b) `_build_variable_name_mapping` never scanned
`COLLECTION` stages, causing `FinalProduct_Collection` to render as 3 non-communicating
spellings).

This cycle (Do-steps 5-6) claims to fix both. **Verified directly against a freshly regenerated
real `PID_0171.bprelease` corpus: gap (a) is genuinely and completely fixed. Gap (b) is real
progress but not complete** — `FinalProduct_Collection` is down from cycle 4's 3-way spelling
split to a 2-way split, and the remaining divergence is a genuine, unreported functional bug: a
`CALCULATION` stage whose *target* (the dict key on the left of `SET ... TO`, e.g.
`FinalProduct_Collection.Column8`) is itself a dotted collection-field reference never goes
through the new dotted-reference resolution logic at all — that logic (`_translate_bp_expression`)
was only wired into the *value* (right-hand) side of a `SET`. The implementer's summary's silence
on `FinalProduct_Collection`'s count, flagged by the coordinator as suspicious, is confirmed to
be exactly that: the variable it didn't report is the one still broken.

## Summary of method

- Re-read Task 5b's Do-steps 5-6/Done-when (`docs/pad-generation-task-prompts.md` lines 745-799),
  the strategy doc's §4 scoring methodology (`docs/bp-to-pad-implementation-strategy-PID171.md`
  lines 285-320), and `docs/reviews/5b-2026-08-31-thirdfixpass.md` in full (the review this cycle
  claims to close out).
- Read the diff area of `src/flowsmith/generator/pad.py`: `_build_variable_name_mapping` (now
  scans `DATA` and `COLLECTION`), `_split_page_into_functions`/`_render_page_as_function`
  (both now accept and thread `variable_name_mapping`), `_render_stage`'s `CALCULATION`/`SET
  <var> TO <expr>` branch (the LHS target-name-resolution logic), and `_translate_bp_expression`
  (the new dotted-reference split/re-append logic).
- Ran `uv run pytest tests/generator/test_pad.py -q` → **70 passed** (matches implementer's
  claim). Ran `uv run pytest tests/e2e/test_pid171_pipeline.py -q` → **16 passed**. Ran
  `uv run ruff check src/flowsmith/generator/pad.py` → clean. (Coverage-threshold failures in
  both runs are the global 85% gate, unrelated to this task.)
- Regenerated the real solution directly via `build_ast(parse_process(...))` →
  `create_annotator().annotate_process(...)` → `PADGenerator().generate_process(...)` against
  `samples/blueprism/PID_0171.bprelease` (same method the e2e suite and prior reviews use),
  producing fresh `PID_171_US_Process_LIMS_Prelude_Loader.robin` /
  `..._Performer.robin` under `outputs/generated/PID_0171_review_5b_5thcycle/`, and grep-swept
  both files independently rather than trusting the implementer's declaration-site-only claims.
- Cross-checked the `FinalProduct_Collection` finding against a fresh AST dump
  (`stage.params_map` on every real `CALCULATION` stage) to confirm the exact root cause and
  real-corpus occurrence count (13) before writing this report.
- Read the 3 new tests (`test_split_shape_preserves_variable_name_consistency`,
  `test_collection_stage_in_mapping_enables_dotted_reference_resolution`,
  `test_split_shape_with_collection_and_reference_consistency`) and confirmed which functions
  each actually exercises (vs. what their docstrings claim).

## The coordinator's specified check, verified directly against real output

**`Consecutive Exception Count`/`Limit` — still fully consistent, unregressed.** 8 real
occurrences across both files, all `num_consecutiveExceptionCount`/`num_consecutiveExceptionLimit`,
zero `txt_` variants. Same result as cycle 4.

**`Retry Count`/`Limit` — now fully fixed, confirmed.** Full case-insensitive sweep for
`retrycount`/`retrylimit` across both `.robin` files (34 + 20 = 54 occurrences) returns **only**
`num_retryCount`/`num_retryLimit` — zero `txt_retryCount`/`txt_retryLimit` anywhere. The two
sibling constant pairs on the same `Result Entry` `split`-shape page that share the identical root
cause — `Close Retry Count/Limit` and `Enter Values_Retry Count/Limit` — are also each fully
consistent (`num_closeRetryCount`/`num_closeRetryLimit`,
`num_enterValuesRetryCount`/`num_enterValuesRetryLimit`, one spelling each). This is a real,
verified fix: `_split_page_into_functions` and its two internal `_render_page_as_function` calls
(`pad.py:752-755`, `923`, `968-971`) do now receive `variable_name_mapping`, and the one real call
site in `_generate_consolidated_flow` (`pad.py:752-755`) does pass it. Matches the implementer's
own claim exactly.

**`FinalProduct_Collection` — improved (3-way → 2-way split), Done-when bar still not met.**
Case-sensitive sweep of both files:

```
13 FinalProduct_Collection   (raw, unprefixed)
14 dtb_finalproductCollection (correctly mapped)
```

The `txt_finalproductCollectionidentity`-style fused third form from cycle 4 is genuinely gone
(confirmed: `grep -noiE 'txt_finalproduct[a-zA-Z]*'` returns zero matches) — Do-step 6's COLLECTION
scan and dotted-reference handling inside `_translate_bp_expression` do work, and are exercised
correctly at every site where the dotted reference sits *inside* a BP expression value (e.g.
`IF dtb_finalproductCollection.Identity="" THEN`, line 549; `Trim(dtb_finalproductCollection.
Identity)`, line 541). But **all 13 remaining raw occurrences are `SET FinalProduct_Collection.
ColumnN TO ...` lines** (Performer lines 552, 777-780, 837-840, 896-899) — i.e. every case where
the dotted collection-field reference is the *target* of a `CALCULATION` stage (the dict key, not
the value). Traced to source: `_render_stage`'s `CALCULATION`/`SET <var> TO <expr>` branch
(`pad.py:1185-1207`) extracts `target_var_name = next(iter(stage.params_map.keys()), "")` and
resolves it with **hand-rolled inline logic that never calls `_translate_bp_expression` or does
any dot-splitting** — it does an exact-match lookup of the *whole* dotted string against
`variable_name_mapping` (line 1194: `target_var_name.lower() in variable_name_mapping`, which
fails since the mapping's key is the bare `finalproduct_collection`, not
`finalproduct_collection.column8`), then falls through to the "no space → already sanitised"
heuristic (line 1201) and returns the raw dotted BP name completely unprefixed. Confirmed against
a fresh AST dump that this is exactly the real BP pattern: `Read Input Data From Excel`'s
`'FinalProduct_Collection.Identity' = '[Identity]'` and `Result Entry`'s (×3 near-duplicate
`Calculation` stage sets) `'FinalProduct_Collection.Column8' = '[Output_value]'` etc. — 1 + 12 =
13, matching the grep count exactly. This is a genuine functional break, not cosmetic: writes via
the 13 raw-named `SET` statements do not land in the `dtb_finalproductCollection` object actually
created by `DataTable.Create()` (line 540) — the exact defect class cycle 3/4 named, now narrowed
to one specific code path (CALCULATION-target resolution) rather than eliminated.

## Regression check (cycles 2-4's fixes, still intact)

- `%SomeVar%` placeholder: 0 occurrences in both files.
- `IF` count: 8 (Loader) + 42 (Performer) = 50 — unchanged from cycle 4.
- `SET` count: 28 (Loader) + 277 (Performer) — unchanged from cycle 4.
- Illegal-character `SET` targets: 0 (full regex sweep of `^\s*SET [^ ]+` against
  `^[A-Za-z0-9_.]+$` in both files) — sanitiser fix from cycle 3 still holds.
- `CreateNewDataTable` → `dtb_` prefix: 18 `dtb_` + 1 legitimate `dg_` outlier (pre-existing BP
  short-prefix name, same defensible exception cycle 4 noted) = 19 real instances, unchanged.
- `uv run pytest tests/generator/test_pad.py -q` (70/70, up from 67/67 — 3 new tests), `uv run
  pytest tests/e2e/test_pid171_pipeline.py -q` (16/16), `ruff check` clean.
- No `method_actions`/`vbo_router` references introduced (`grep` confirms zero) — Do-step 3
  correctly stayed out of scope, as instructed.

## Verification of the two claimed fixes

**Do-step 5 (thread mapping through split-shape path) — fully confirmed, real.** The parameter is
present on `_split_page_into_functions`'s signature and both its internal
`_render_page_as_function` calls, and the one real call site passes it. Verified both by reading
the code and by the real-corpus `Retry Count`/`Limit`/`Close Retry`/`Enter Values Retry` sweep
above — zero `txt_` variants anywhere in the regenerated output.

**Do-step 6 (COLLECTION stages + dotted references) — partially confirmed, incomplete.**
`_build_variable_name_mapping` does now scan `StageType.COLLECTION` (`pad.py:211-218`) and
`_translate_bp_expression` does now resolve `[CollectionName.Field]` bracket references and bare
`CollectionName.Field` references inside an expression's *value* correctly (`pad.py:1715-1734`,
`1761-1777`). But the fix was never extended to the `CALCULATION` stage's *target*-name resolution
branch (`pad.py:1185-1207`), which is a separate, hand-rolled code path that doesn't call
`_translate_bp_expression` at all for the left-hand side. This is exactly the kind of "one code
path fixed, sibling code path not" gap this task's fix-pass lineage has repeatedly hit.

## New unit tests — representativeness

The 3 new tests do meaningfully improve coverage over cycle 4 (which had zero tests referencing
`variable_name_mapping`/`_build_variable_name_mapping` at all), but two specific overclaims/gaps
were found on inspection:

- **`test_split_shape_preserves_variable_name_consistency`'s docstring claims it "verifies that
  the mapping is properly threaded through `_split_page_into_functions` to both internal
  `_render_page_as_function` calls,"** but the test body never calls `_split_page_into_functions`
  (or `_render_page_as_function`) — it calls `_build_variable_name_mapping` and then
  `_render_stage` directly on each stage, passing the pre-built mapping in by hand. **No test in
  the entire file calls `_split_page_into_functions` at all** (`grep -n
  "_split_page_into_functions("  tests/generator/test_pad.py` → zero matches). The real fix
  (threading the parameter through that specific function's two internal call sites) is therefore
  unit-tested only indirectly/not at all — its correctness in this review rests on this reviewer's
  own real-corpus regeneration, not on the test suite. A future regression to that exact function
  (e.g. reverting one of the two internal calls to drop the new kwarg) would not be caught by any
  current unit test.
- **`test_collection_stage_in_mapping_enables_dotted_reference_resolution` and
  `test_split_shape_with_collection_and_reference_consistency` both use
  `params_map={"Set Result": "[FinalProduct_Collection.Column8]"}`-shaped fixtures** — i.e. the
  dotted reference is placed on the *value* (right-hand) side of an unrelated target variable
  (`"Set Result"`). **Neither test uses the real BP shape** — `params_map={"FinalProduct_
  Collection.Column8": "[Output_value]"}`, where the dotted reference is the *target itself* —
  which is exactly the shape 13 real stages in `PID_0171.bprelease` use and exactly where the
  remaining bug lives. This is the fifth consecutive review cycle (per the task doc's own
  fix-pass history) where the new tests pass by construction while sidestepping the precise shape
  of the real defect; this cycle's version of the pattern is narrower than prior cycles' (2 of 3
  named flagship variables are now genuinely fully fixed) but the pattern itself continues.

## Scoring

| Dimension | Score | Evidence |
|---|---|---|
| Structural | N/A | Task 5b's scope is expression translation, not flow/workflow shape. |
| FUNCTION functional fidelity | 65% | Real, verified progress from cycle 4's 45%: `Consecutive Exception Count/Limit` remains fully consistent (unregressed), and `Retry Count/Limit` plus its two sibling constant pairs (`Close Retry Count/Limit`, `Enter Values_Retry Count/Limit`) — all four living on `Result Entry`, the largest page in the process, rendered via the `split` shape — are now genuinely and completely fixed end-to-end in the real regenerated corpus. `FinalProduct_Collection` remains a real functional break: 13 of 27 real occurrences (the entire "write into the table" pattern, `Read Input Data From Excel` + 3× `Result Entry` Summary Report clusters) use the raw, unprefixed BP name and do not touch the actual `dtb_finalproductCollection` object created by `DataTable.Create()` — roughly half of this one variable's real occurrences are still wrong, even though the "declare" and "read from" occurrences are now correct. |
| VBO/action fidelity | N/A for this cycle | Do-step 3 explicitly and correctly out of scope this cycle, per the coordinator's instruction — confirmed via `grep` (zero `method_actions`/`vbo_router` references added). No regression in the underlying gap (0 `%SomeVar%` placeholders, unchanged). |
| Naming convention | 65% | Illegal-character sanitisation remains fully clean (0 illegal `SET` targets, full regex sweep). `CreateNewDataTable` remains 18/19 `dtb_`-prefixed (1 defensible `dg_` outlier, unchanged from cycle 4). `Consecutive Exception Count/Limit` fully consistent. `Retry Count/Limit` (+2 siblings) now fully consistent — this closes the single largest remaining naming gap named by cycle 4. `FinalProduct_Collection` still has 2 distinct spellings in the same file (`dtb_finalproductCollection` vs. raw `FinalProduct_Collection`) — down from cycle 4's 3, a real improvement, but the task's own explicitly-named flagship variable still fails the "zero spelling variants" bar. |
| Error-handling/stop/consecutive-exception | N/A for this task's scope | Owned by Task 5c. Forward-looking note, more positive than cycle 4: the retry-loop state (`Retry Count/Limit`) that Task 5c's `BLOCK`/`RECOVER` dispatch will need to read/write is now correctly wired end-to-end, in addition to `Consecutive Exception Count/Limit` (already correct as of cycle 4) — both of `Result Entry`'s counter mechanisms are now sound building blocks for 5c. `FinalProduct_Collection`'s write-path gap is orthogonal to 5c's scope (it's data-table population, not exception counting) but remains a real defect a later reader of this output would hit. Zero `GLOBAL.` qualifications still appear anywhere in either file (§A4's rule) — still out of this cycle's named scope, unchanged from cycle 4's note. |
| Well-formedness | 88% | `uv run pytest tests/generator/test_pad.py -q` (70/70, up from 67/67), `uv run pytest tests/e2e/test_pid171_pipeline.py -q` (16/16, including the `<Definition>`-JSON/well-formedness subset specifically), `ruff check` clean — no regression, and 3 new tests were added (an improvement in coverage breadth over cycle 4's zero direct tests of the new mapping mechanism). `IF`/`SET`/`%SomeVar%` counts unchanged. Held below a higher score because: (a) no test in the file calls `_split_page_into_functions` directly — the exact function this cycle's headline fix modifies — so the suite's green status doesn't by itself certify that fix, only this review's independent real-corpus regeneration does; (b) the two new dotted-reference tests use a fixture shape that sidesteps the real remaining bug (CALCULATION-target-as-dotted-name), continuing the fifth-consecutive-cycle pattern named in every prior review. |

## Most significant gaps

- **`CALCULATION` stage target-name resolution (`pad.py:1185-1207`) never routes through the
  dotted-reference logic added to `_translate_bp_expression`.** When a `Calculation` stage's
  target itself is a dotted `CollectionName.Field` string (the real BP shape used by `Read Input
  Data From Excel` and 3× on `Result Entry` — 13 real occurrences), the exact-match mapping lookup
  fails silently and the "no space → already sanitised" fallback returns the raw BP name
  unprefixed and unmapped. Fix: either route `target_var_name` through the same dot-split/
  base-lookup/field-reappend logic already built for expression values (extracting it into a
  shared helper both call), or extend the exact-match lookup at line 1194 to also try a dot-split
  before falling through to the "already sanitised" heuristic.
- **No unit test calls `_split_page_into_functions` directly.** The function this cycle's Do-step
  5 was specifically about (per cycle 4's diagnosis) has zero direct test coverage; the new
  `test_split_shape_preserves_variable_name_consistency` test's docstring overclaims what it
  verifies (it tests `_render_stage` + a manually-built mapping, not the actual threading through
  `_split_page_into_functions`'s two internal call sites). A regression there would currently only
  be caught by regenerating the real corpus, not by `pytest`.
- **The two new dotted-reference tests use an expression-value fixture shape
  (`params_map={"Set Result": "[FinalProduct_Collection.Column8]"}`) instead of the real
  target-name fixture shape (`params_map={"FinalProduct_Collection.Column8": "[Output_value]"}`)**
  that 13 real stages actually use — this is why the remaining bug shipped despite green tests,
  continuing the exact structural test-blind-spot pattern named in cycles 2, 3, and 4.
- **Implementer's self-reported verification again checked only the two variable families it
  could show were fully fixed** (`Retry Count/Limit`) and stayed silent on `FinalProduct_
  Collection`, exactly as the coordinator anticipated — confirmed to be the one still-broken
  flagship, not an oversight-free omission.

## Verdict

Needs another narrowly-scoped implementation pass — not a restart. This is genuine, verified
forward progress: 2 of the task's 3 named flagship variable families (`Consecutive Exception
Count/Limit`, `Retry Count/Limit` and its two siblings) are now fully consistent across the whole
real regenerated corpus, closing the single largest defect named by the 4th review. What remains,
scoped tightly: extend the dotted-reference resolution already built for expression *values* in
`_translate_bp_expression` to also cover a `CALCULATION` stage's *target* name when that target
itself is a dotted `CollectionName.Field` reference (`pad.py:1185-1207`) — this is the one
remaining root cause blocking `FinalProduct_Collection`'s last 13 raw occurrences, and it is a
single, well-localised code path, not a new investigation. Pair it with a test built on the real
target-name fixture shape (dotted string as the `params_map` *key*, not value) so this exact class
of gap is caught by `pytest` rather than only by re-regenerating the real corpus, and — if time
allows — a test that calls `_split_page_into_functions` directly so Do-step 5's own fix has direct
unit coverage rather than depending entirely on manual real-corpus verification.
