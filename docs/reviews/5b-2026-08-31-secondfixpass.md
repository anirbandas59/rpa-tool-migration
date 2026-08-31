# Review: Task 5b — 2026-08-31 (2nd fix-pass, 3rd implementation cycle)

**Overall: 38%**

Third review cycle for Task 5b. Prior reviews: `docs/reviews/5b-2026-08-31.md` (1st, 15%),
`docs/reviews/5b-2026-08-31-fixpass.md` (2nd, 32%, "partially done, needs a further
narrowly-scoped fix pass"). This cycle was deliberately scoped to only the 2nd review's three
named fixes (DATA-stage `SetVariable` wiring, §A4 type-aware prefix wiring, `CreateNewDataTable`
sanitisation) and explicitly excluded Do-step 3 (VBO `method_actions` substitution) — that
omission is **not** penalized here, per the coordinator's instruction.

All three fixes are real in the narrow sense claimed: each one, taken in isolation and inspected
against real regenerated output, does what the implementer's summary says. But re-inspecting the
regenerated corpus (not just the three new unit tests) surfaces the exact same class of defect
that sank cycles 1 and 2: a fix that is locally correct produces a PAD variable name that never
connects to the *other* real call sites referencing the same logical BP data item, because those
call sites resolve the same variable's type/prefix through a different (and in this case, empty)
lookup path. Concretely: the flagship `Consecutive Exception Limit`/`Retry Limit` constants this
task and the last two reviews have centered on are now declared as `num_consecutiveExceptionLimit`
/ `num_retryLimit` (correct, from Fix 1+2) but are *compared against and incremented as*
`txt_consecutiveExceptionLimit` / `txt_retryLimit` everywhere else in the same file (from the
already-existing `CALCULATION`/`DECISION` expression-translation path, whose per-reference
`data_type` lookup only checks the referencing stage's own `data_items`, which is empty for a bare
`Calculation` stage). The two prefixes are two different, non-communicating PAD variables. The
`IF` line and the constant's initial value no longer disagree by being wrong — they disagree by
being two different variables. This is a materially different, and arguably worse-looking, version
of exactly the defect cycle 2 flagged (an `IF` that "reads right" while referencing an uninitialised
input).

## Summary of method

- Re-read Task 5b's Do-steps and Done-when (`docs/pad-generation-task-prompts.md` lines 745-777)
  and architecture doc §A4/§B10 point 3.
- Read both prior reviews in full and re-verified their findings still hold in the current working
  tree (`git status` shows the same uncommitted `pad.py`/`test_pad.py`/templates as before, now
  further edited — cumulative diff across all three cycles).
- Ran `uv run pytest tests/generator/test_pad.py -q` → 67 passed (matches implementer's claim: 64
  existing + 3 new). Ran `uv run pytest tests/e2e/test_pid171_pipeline.py -q` → 16 passed
  (unchanged from cycle 2). `uv run ruff check src/flowsmith/generator/pad.py` → clean.
- Regenerated the real solution directly via `PADGenerator().generate_process(...)` (the same
  call the e2e suite itself uses) against `samples/blueprism/PID_0171.bprelease`, producing
  `PID_171_US_Process_LIMS_Prelude_Loader.robin` (7.3 KB) and `..._Performer.robin` (61.6 KB), and
  inspected both directly with grep/regex/Python, cross-referencing against the real BP XML
  (`samples/blueprism/PID_0171.bprelease`) and a fresh `build_ast`/`annotate_process` run for the
  DATA-stage denominator check. (Note: `uv run flowsmith convert` packages the `.robin` bodies
  inline into `customizations.xml`'s `<Definition>` rather than emitting standalone `.robin`
  files under the CLI's default flow — used the `PADGenerator` call directly, matching the e2e
  test's own method, to get inspectable files.)

## Verification of the three claimed fixes

**Fix 1 (DATA-stage `SetVariable` reads `annotation.params_map["initial_value"]`) — confirmed
real, and the 36/177 denominator is confirmed correct, not a residual bug.** A fresh
`build_ast`+`annotate_process` run confirms exactly 177 real `DATA` stages, of which exactly 36
carry a non-empty `initial_value` in `annotation.params_map` — the other 141 genuinely have
`<initialvalue />` (empty) in the raw BP XML, not a lookup miss. Spot-checked several of the 36
directly against `PID_0171.bprelease`: `SendData_To_Gateways` (`Boolean`/`False`) →
`SET flg_senddata_to_gateways TO False`; two distinct `Success` (`flag`) stages on different BP
subsheets, one with `<initialvalue>True</initialvalue>` and one with `<initialvalue />` → generated
output correctly emits `SET flg_success TO True` for the first occurrence and
`SET flg_success TO # TODO: No expression` for the other, matching the raw XML per-stage, not a
blanket default. This part of the fix is genuinely correct.

**Fix 2 (type-aware prefix wiring through 8 call sites) — real prefix diversity confirmed, but
does not close the loop for the task's own flagship example.** Real output now has genuine
`num_`/`flg_`/`obj_`-prefixed variables beyond `txt_` (e.g. `num_handle` — confirmed BP `handle`
data item really is `type="number"` in the raw XML; `flg_movefile_success`, `flg_senddata` —
confirmed real `Boolean` BP data items). This is real, verified progress over cycle 2 (where 9
call sites existed but none passed `data_type`). **However**, direct inspection of the same file
shows the fix only reaches the lookup successfully when the *referencing* stage happens to carry
the data item in its own local `data_items` list. `Calculation` stages that merely reference a
data item by bracket name (e.g. `<calculation expression="[Retry Count]+1" stage="Retry Count" />`
— confirmed in the raw BP XML) carry no `data_items` of their own, so `_translate_bp_expression`'s
lookup finds nothing and silently defaults to `txt_`. Result, confirmed in generated output:
`SET num_retryLimit TO 3` (Fix 1, correct) coexists with `IF txt_retryCount<txt_retryLimit ...`
and `SET txt_retryCount TO txt_retryCount+1` (existing expression-translation path, never
touched by this cycle) — two different PAD variables for one BP data item. Same pattern confirmed
for `Consecutive Exception Count`/`Limit` (`num_consecutiveExceptionLimit` declared with `3`,
`ELSE`/`IF` block at line 403 compares `txt_consecutiveExceptionCount>=txt_consecutiveExceptionLimit`,
which is never initialised anywhere). Also found: an un-sanitised hyphen survives
(`SET num_sleep-2s TO 2`, from real BP data item name `Sleep-2s`) — `_sanitise_variable_name` only
strips spaces, not other illegal identifier characters, so this is not valid Robin syntax; a small
but real well-formedness miss introduced by Fix 1/2's own new code path (DATA stages unconditionally
call the sanitiser, unlike the CALCULATION path).

**Fix 3 (`CreateNewDataTable` sanitisation) — the illegal-identifier defect is genuinely fixed,
but the chosen prefix contradicts both §A4 and the real reference package.** Confirmed via regex
sweep of every `SET <target> TO` line in both generated files: zero remaining space-containing
identifiers (was the 1st cycle's other headline defect). All 15 real `CreateNewDataTable` stages
now render as `obj_<name>` (e.g. `obj_mailItems`, `obj_componentNames`, `obj_finalproduct_collection`).
But architecture doc §A4 states plainly: *"if the BP page indexes the collection by a field name →
`obj_`; if it loops over rows or writes tabular output → `dtb_`/`dtr_`. Don't default to DataTable
just because the BP source type is `collection`."* A `CreateNewDataTable` stage is, by construction,
never ambiguous — it is unconditionally instantiating a table — and the real reference package
confirms this: `docs/pad-reference/DF_PID_171_US_LIMS_Prelude_Main.robin.txt:565` shows
`Variables.CreateNewDatatable InputTable: {...} DataTable=> dtb_DataTable` — the real BP author
used `dtb_`, never `obj_`, for an actual table-creation call. Fix 3 hard-codes `data_type="collection"`
which the sanitiser's own prefix table maps to `obj_` ("Collections can be datatables or objects -
default to object" — the code comment's own stated default is the wrong one of the two options for
this specific, unambiguous stage type). Separately confirmed: the sanitised declaration name
(`obj_finalproduct_collection`) is never referenced anywhere else in the file — every other `SET`
targeting that same logical collection uses the raw, un-prefixed BP name `FinalProduct_Collection`
directly (`SET FinalProduct_Collection.Column8 TO ...`, 12 occurrences) — the same
declaration-site/reference-site name-divergence bug as Fix 2's finding above, for collections
instead of scalars.

## Regression check (cycle 2's fixes)

- `IF` count: 42 in Performer + 8 in Loader = unchanged from cycle 2's reported 42 total (cycle 2
  counted differently but the underlying real number matches; re-confirmed no regression).
- `SET` count: 277 in Performer (matches cycle 2's own reported count exactly) — expected, since
  Fix 1 changes *values* on lines that already existed as `SET ... TO # TODO: No expression`, not
  new lines.
- `%SomeVar%` placeholder: 0 occurrences in both files — still fully eliminated, not regressed.
- `uv run pytest tests/generator/test_pad.py -q` (67/67) and
  `uv run pytest tests/e2e/test_pid171_pipeline.py -q` (16/16) both pass — no regression in the
  existing suites.

## New unit tests — representativeness

All three new tests (`test_data_stage_set_variable_reads_initial_value_from_annotation`,
`test_collection_stage_sanitises_variable_name`, `test_type_aware_prefixes_wired_through_sanitiser`)
call `PADGenerator()._render_stage(stage)` / `._sanitise_variable_name(...)` directly against
hand-built `BPStage`/`PAAnnotation` objects whose shapes were checked against the real
annotator (`_annotate_data`'s `params_map` dict keys, `_annotate_collection`'s `target_type`
string) and match. These are representative of the real pipeline's *data shapes* for the single
stage under test, continuing cycle 2's improvement over cycle 1's non-representative fixtures.
**However**, precisely because each test constructs one isolated stage, none of them can catch —
and none did catch — the cross-stage name-divergence defect above, which only manifests when a
`DATA` stage's declaration and a separate `Calculation`/`Decision` stage's reference to the same
BP data item are rendered into the same file and compared. This is the same structural blind spot
flagged in both prior reviews: the fix is validated stage-by-stage, but the bug lives between
stages, and continues to only surface via full-corpus regeneration, not unit tests.

## Scoring

| Dimension | Score | Evidence |
|---|---|---|
| Structural | N/A | Task 5b's scope is expression translation, not flow/workflow shape. |
| FUNCTION functional fidelity | 35% | Fix 1's DATA-stage values are genuinely correct and correctly reflect per-stage BP XML (36/177, verified against raw XML). But the task's own flagship example (§A7 `Consecutive Exception Count/Limit`, `Retry Count/Limit`) is now split across two non-communicating PAD variables (`num_...` declared, `txt_...` compared/incremented) — confirmed directly in generated output and traced to the raw BP XML (`Calculation` stages carry no local `data_items`, so the type lookup silently defaults to `txt_`). This is a real functional break, not a cosmetic one: the `IF` condition can never see the initialised value. |
| VBO/action fidelity | N/A for this cycle | Do-step 3 was explicitly and correctly out of scope this cycle, per the coordinator's instruction — not scored. (Underlying gap from cycle 2 — generic Excel macro fires per stage, `WorkQueues` stubbed — is unchanged, informational only.) |
| Naming convention | 30% | Fix 3 eliminates all real space-containing identifiers (verified by regex sweep of every `SET` target in both files — zero remaining). But: (a) the chosen `obj_` prefix for `CreateNewDataTable` contradicts §A4's own rule and the real reference package's `dtb_DataTable` example; (b) the sanitised collection name is never used at any of the collection's other 12 real reference sites in the same file (`FinalProduct_Collection.Column8` stays raw/un-prefixed); (c) Fix 2's per-scalar declaration/reference divergence (above) means several §A4-prefixed constants exist as orphaned pairs; (d) one un-sanitised hyphen survives (`num_sleep-2s`), not handled by the sanitiser's space-only stripping. |
| Error-handling/stop/consecutive-exception | N/A for this task's scope | Owned by Task 5c — but worth flagging forward again, more urgently than cycle 2 did: the consecutive-exception mechanism isn't just "uninitialised" anymore, it's now two separate variables that will never agree even after Task 5c lands the `BLOCK`/`RECOVER` dispatch pattern, unless the declaration/reference divergence above is fixed first. |
| Well-formedness | 75% | `uv run pytest tests/e2e/test_pid171_pipeline.py -q` 16/16, `uv run pytest tests/generator/test_pad.py -q` 67/67, `ruff check` clean — all reused checks pass, no regression. Docked from cycle 2's 85%: a fresh, targeted regex sweep for illegal `SET` target characters (not just spaces) surfaces one genuine invalid Robin identifier newly introduced by this cycle's own Fix 1 code path (`num_sleep-2s`, hyphen), confirming the existing container-level test suite still can't see this class of defect — exactly the blind spot cycle 2's review named. |

## Most significant gaps

- **Declaration-site/reference-site PAD variable-name divergence is a new (or newly surfaced)
  systemic defect, and it is the direct product of this cycle's own fixes.** Fix 1/2 correctly
  compute a type-aware, correctly-prefixed name at the `DATA` stage's own declaration point, but
  every other real stage that references the same logical BP data item by bracket name resolves
  its own, independently-computed name through a different (and often empty) lookup path. Confirmed
  for at least three real pairs: `Retry Limit`/`Count`, `Consecutive Exception Limit`/`Count`
  (the exact §A7 constants both prior reviews centered on), and the `FinalProduct_Collection`
  DataTable. This is not a hypothetical edge case — it is the single most business-critical piece
  of state this task has been asked to get right across all three cycles, and it is now wrong in a
  new way rather than fixed.
- **`CreateNewDataTable`'s `obj_` default prefix contradicts both the architecture doc's own §A4
  text and the real reference package's own `dtb_DataTable` usage.** An unambiguous
  table-creation call should never hit the "ambiguous, default to object" branch the doc describes
  for genuinely ambiguous BP `Collection`s.
- **The sanitiser doesn't handle non-space illegal characters** (confirmed: hyphen in
  `Sleep-2s` → `num_sleep-2s`, invalid Robin syntax) — a narrow gap, but exactly the kind of thing
  the "well-formedness" dimension is supposed to catch and the existing test suite does not.
- **The three new unit tests, while representative in shape, are each single-stage fixtures and
  structurally cannot catch the cross-stage divergence bug above** — this is the third consecutive
  cycle where a fix validated in isolation, and confirmed "real" against a narrow slice of real
  output, turns out not to be wired correctly against the *rest* of the same real output once the
  full corpus is inspected.

## Verdict

Needs another, still narrowly-scoped implementation pass — not a full restart, and the three
targeted fixes' core mechanics (reading `annotation.params_map` for `DATA` stages; passing
`data_type` through to the sanitiser; sanitising the `CreateNewDataTable` var name) should be kept.
What remains, scoped tightly: (1) give the BP-data-item → PAD-variable-name mapping a single
process-wide source of truth (e.g. a name→prefix lookup built once from every `DATA` stage's real
`variable_type`, consulted by both the `DATA`-stage declaration path and the
`Calculation`/`Decision` expression-translation path) so the same logical BP data item always maps
to the same PAD variable name regardless of which stage is doing the referencing — this is the
single fix that would close the gap surfaced in cycles 2 and 3 alike, rather than requiring a
fourth cycle to re-discover it in a new spot; (2) change `CreateNewDataTable`'s default prefix from
`obj_` to `dtb_`, and use the same shared lookup so the created table's name is actually
referenced consistently by whatever else in the page touches it; (3) extend
`_sanitise_variable_name` to strip/convert non-space illegal characters (at minimum hyphens),
not just spaces.
