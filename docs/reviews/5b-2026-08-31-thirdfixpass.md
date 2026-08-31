# Review: Task 5b — 2026-08-31 (3rd fix-pass, 4th implementation cycle)

**Overall: 44%**

Fourth review cycle for Task 5b. Prior reviews: `docs/reviews/5b-2026-08-31.md` (1st, 15%),
`docs/reviews/5b-2026-08-31-fixpass.md` (2nd, 32%), `docs/reviews/5b-2026-08-31-secondfixpass.md`
(3rd, 38%, "needs another narrowly-scoped pass" — found declaration-site vs. reference-site PAD
variable-name divergence for `Consecutive Exception Count/Limit` and `Retry Count/Limit`: `num_`
at the `DATA`-stage declaration, `txt_` everywhere else).

This cycle claims to fix exactly that divergence via one new process-wide
`_build_variable_name_mapping()`, plus the `CreateNewDataTable` prefix and sanitiser-illegal-char
findings from cycle 3. **The coordinator's single specified check — does the same BP variable
render under the identical PAD name at every declaration *and* reference site in the real
regenerated output — is only partially true.** It holds for one of the three named flagship
variable families (`Consecutive Exception Count/Limit`) and fails for the other two
(`Retry Count/Limit`, `FinalProduct_Collection`), for a root cause that is easy to state and
narrow to fix: the new mapping is built and threaded through the "function"/"fold" render paths,
but never threaded through `_split_page_into_functions` (the "split" shape's renderer) — and
`Result Entry`, the single largest BP page (161 stages) and the page the two broken variable
families' `Calculation` stages actually live on, is rendered exclusively through that path.
`FinalProduct_Collection` has a second, independent bug on top of that: dotted `Collection.Field`
references (e.g. `FinalProduct_Collection.Column8`) are not looked up in the mapping at all
(mapping keys are bare collection names, not `name.field` compounds), and the fallback sanitiser
path either passes the dotted BP name through completely raw (no prefix) or — for a different
reference shape — silently drops the `.` and appends the field name into a single fabricated
`txt_...` identifier. The result is **three** distinct, non-communicating spellings of the same
logical collection in the same file, which is a regression in spelling-variant *count* from cycle
3's already-flagged 2-way divergence for this exact variable, even though the individual
`CreateNewDataTable` declaration itself is now correctly `dtb_`-prefixed.

## Summary of method

- Re-read Task 5b's Do-steps/Done-when (`docs/pad-generation-task-prompts.md` lines 745-777),
  architecture doc §A4 (naming/prefix table, `dtb_FinalProduct` worked example, `GLOBAL.`
  qualification rule), and the strategy doc's §4 scoring methodology.
- Read all three prior reviews and confirmed the current working tree (`git status`) is the same
  uncommitted `pad.py`/`test_pad.py` set, further edited (cumulative diff across all four cycles;
  `git diff --stat` shows +1446/-… in `pad.py`, +810 in `test_pad.py`).
- Ran `uv run pytest tests/generator/test_pad.py -q` → **67 passed**. Ran
  `uv run pytest tests/e2e/test_pid171_pipeline.py -q` → **16 passed** (matches implementer's
  claim of 83 total; coverage-threshold failures printed by both runs are the global 85% gate,
  unrelated to this task's own pass/fail). `uv run ruff check src/flowsmith/generator/pad.py` →
  clean.
- Regenerated the real solution directly via `build_ast(parse_process(...))` →
  `create_annotator().annotate_process(...)` → `PADGenerator().generate_process(...)` against
  `samples/blueprism/PID_0171.bprelease` (same method the e2e suite uses), producing
  `PID_171_US_Process_LIMS_Prelude_Loader.robin` and `..._Performer.robin` under
  `outputs/generated/PID_0171_review_5b_4thcycle/`, and inspected both directly with `grep`/regex
  and a fresh AST build for ground truth, per the coordinator's explicit instruction not to trust
  the implementer's declaration-site-only verification.
- Read `_build_variable_name_mapping`, `_translate_bp_expression`, `_sanitise_variable_name`,
  `_sanitise_identifier_chars`, `_render_stage`'s `SetVariable`/`CreateNewDataTable` branches, and
  every call site of `_render_stage`/`_render_page_as_function`/`_split_page_into_functions` to
  trace exactly which render paths do and don't receive `variable_name_mapping`.

## The coordinator's specified check, verified directly against real output

**`Consecutive Exception Count`/`Limit` — fully consistent, genuinely fixed.** Every occurrence in
both generated files is `num_consecutiveExceptionCount`/`num_consecutiveExceptionLimit`; zero
`txt_` variants remain (`grep -rnoiE` sweep of both `.robin` files, 8 total occurrences, all
`num_`). This is the exact defect cycle 3 named for this variable pair, and it is resolved.

**`Retry Count`/`Limit` — still diverges, same shape of bug as cycle 3, now traced to a specific
missing wire.** The same `grep` sweep shows a genuine mix in the Performer file:
`num_retryCount`/`num_retryLimit` (correct, e.g. lines 130-148, 440-448, 742-754, 812-813) coexists
with `txt_retryCount`/`txt_retryLimit` (wrong — orphaned, uninitialised, e.g. lines 753-754,
807-808, 853-854, 981-984) for the identical logical BP variable. Traced the wrong occurrences to
their source: they all belong to `Result Entry`'s `Count` calculation stages
(`{'Retry Count': '[Retry Count]+1'}`, confirmed via a fresh AST dump — `Launch_Sample Manager`
2848a429, `Get Mails` 4c289a13, `Save Attachments` 4bf9cf94, `Result Entry` a24279c1/b7dfe435,
`Sample Manager - Explorer` 7ad3f751). `Result Entry` is mapped `shape: split` in
`mapping/page_target_map.yaml` (7 targets, 161 raw stages — the single largest page in the
process). `generate_process` calls `self._split_page_into_functions(page, targets, process,
process_name, stage_counts)` (`pad.py:738`) with **no `variable_name_mapping` argument**, and
`_split_page_into_functions`'s own signature (`pad.py:867-874`) never accepts one — both of its
internal `_render_page_as_function` calls (`pad.py:900`, `945-947`) fall back to the default
`variable_name_mapping=None`. Every `Calculation` stage rendered through this path therefore hits
`_translate_bp_expression`'s per-stage fallback (empty `data_items` on a bare `Calculation` stage
→ defaults to `txt_`) — precisely the mechanism cycle 3 diagnosed, just in a code path the new
mapping was never threaded into. `Close Retry Count/Limit` and `Enter Values_Retry Count/Limit`
(the other two retry-style constants, also declared on `Result Entry`) show the identical
`num_`/`txt_` split for the same reason.

**`FinalProduct_Collection` — worse than cycle 3's finding, now a 3-way split.** `grep` sweep
across both files (case-insensitive, `finalproduct`) shows:
1. `dtb_finalproductCollection` — the `CreateNewDataTable` declaration (Fix 2 correctly applied
   here, `pad.py:1217-1231`, `for_data_table=True`).
2. `FinalProduct_Collection.Column1`/`.Column8`/etc. — raw, completely unprefixed BP dotted name,
   passed straight through. Root cause: `_build_variable_name_mapping` only scans `StageType.DATA`
   stages (`pad.py:197`, `if stage.stage_type != StageType.DATA: continue`) — `FinalProduct_
   Collection` is declared by a `COLLECTION`-type stage (`StageType.COLLECTION`, confirmed 24 real
   instances in the AST), which the mapping builder skips entirely, so it was never in the mapping
   to begin with. The fallback logic at `pad.py:1176-1179` then treats any target name with no
   space as "already sanitised" and returns it verbatim — which is how a raw, un-namespaced BP
   identifier survives into generated Robin code.
3. `txt_finalproductCollectionidentity` / `txt_finalproductCollectioncomponent` / `txt_
   finalproductCollectionresults` — a third, independently-broken shape, produced when the same
   dotted reference reaches `_sanitise_identifier_chars` instead (which silently drops the `.`
   as an "other illegal character," `pad.py:83-88`, fusing the field name into the base
   identifier and defaulting to `txt_` since no `data_type` is available for a synthetic compound
   name).

None of these three forms refer to the same variable a PAD interpreter would recognise, and none
of them is the table actually instantiated by `DataTable.Create()`. This is a functional break,
not a cosmetic one — writes via forms 2/3 do not land in the table created under form 1.

## Regression check (cycles 2-3's fixes, still intact)

- `IF` count: 8 (Loader) + 42 (Performer) = 50 — unchanged from cycle 3's reported total (matches
  prior review's own count once its per-file split is added).
- `SET` count: 28 (Loader) + 277 (Performer) — unchanged from cycle 3.
- `%SomeVar%` placeholder: 0 occurrences in both files — still fully eliminated.
- `uv run pytest tests/generator/test_pad.py -q` (67/67), `uv run pytest
  tests/e2e/test_pid171_pipeline.py -q` (16/16, including the well-formedness/`<Definition>`-JSON
  subset specifically), `ruff check` clean — no regression in any existing suite.

## Verification of the three claimed fixes

**Fix 1 (declaration/reference divergence) — real, but incomplete.** The core mechanism
(`_build_variable_name_mapping`, threaded through `_translate_bp_expression` and the
`Calculation`/`SetVariable` render branch) is correctly designed and does close the gap for every
page rendered through the "function"/"fold" shapes. It does not reach the "split" shape at all
(missing parameter on `_split_page_into_functions` and its two internal
`_render_page_as_function` calls), and it does not cover `COLLECTION`-type stages (scanning
`StageType.DATA` only) or dotted `Collection.Field` reference syntax. Both gaps are directly
responsible for the two still-broken flagship variable families above.

**Fix 2 (`CreateNewDataTable` → `dtb_`) — real for the declaration site, 18 of 19 real instances
confirmed `dtb_`-prefixed (`grep` sweep of `SET <target> TO DataTable.Create()`), zero remaining
`obj_`.** One outlier, `dg_ItemData` (Performer, "Item_StartedOn" cluster), keeps a pre-existing
`dg_` prefix already present in the raw BP data-item name itself (`dg_StartedOn`, `dg_Tags`,
`dg_CompletedOn` are neighbouring real BP names in the same cluster) — the sanitiser's
"already-prefixed" heuristic correctly leaves an existing short-prefix BP name alone rather than
overriding it, which is defensible, not a bug, but does mean the implementer's claimed count ("14
in Performer... use dtb_ prefix correctly") is off by one against the real corpus (15 real
`DataTable.Create()` calls in Performer, 14 `dtb_` + 1 `dg_`). Declared-vs-referenced consistency
for the created table itself is separately broken by the `FinalProduct_Collection` 3-way-split
finding above — the prefix fix and the consistency fix are different things, and only the former
is solid.

**Fix 3 (sanitiser illegal characters) — fully confirmed, no caveats found.** Full regex sweep of
every `SET <target> TO` line in both files (`grep -hoE '^\s*SET [^ ]+' ... | grep -vE
'^[A-Za-z0-9_.]+$'`) returns zero matches — no illegal-character identifiers survive anywhere in
the real corpus, not just the one named `Sleep-2s` example (confirmed independently:
`SET num_sleep2s TO 2` at both of its two real occurrences, correctly de-hyphenated).

## New unit tests — representativeness

`grep`ing the test file for `variable_name_mapping`/`_build_variable_name_mapping` returns **zero
matches** — the new mapping function that is the centrepiece of this cycle's fix is not directly
unit-tested at all, and the tests exercising the related `SetVariable`/`CreateNewDataTable`/
`_sanitise_variable_name` behaviour (`test_data_stage_set_variable_reads_initial_value_from_
annotation`, `test_collection_stage_sanitises_variable_name`, `test_type_aware_prefixes_wired_
through_sanitiser`) remain single-stage-fixture tests calling `_render_stage`/`_sanitise_variable_
name` in isolation, per the same structural blind spot flagged in cycles 2 and 3. No test builds
two stages (a `DATA`/`COLLECTION` declaration and a separate `Calculation`/`Decision` reference)
in the same rendered page or process and asserts they agree on a name — and, consistent with that
gap, no test exercises the "split" shape's rendering path with a `variable_name_mapping` present,
which is exactly where the real defect above lives. This is the fourth consecutive cycle where the
test suite stays green while the real regenerated corpus contains the exact class of bug the cycle
claims to have fixed.

## Scoring

| Dimension | Score | Evidence |
|---|---|---|
| Structural | N/A | Task 5b's scope is expression translation, not flow/workflow shape. |
| FUNCTION functional fidelity | 45% | `DATA`-stage initial values remain correctly wired (Fix 1 from cycle 2, unregressed). The new process-wide mapping genuinely closes the declaration/reference gap for `Consecutive Exception Count/Limit` — confirmed zero divergence across 8 real occurrences, a real functional fix for that flagship pair. But `Retry Count`/`Limit`/`Close Retry Count/Limit`/`Enter Values_Retry Count/Limit` — declared on the same `Result Entry` page, using the same retry-loop pattern — remain split into two non-communicating PAD variables because `Result Entry` is rendered via the "split" shape, which the mapping was never threaded into. `FinalProduct_Collection` is worse: 3 distinct name forms for the same table in the same file, meaning writes via 2 of the 3 forms do not touch the table that was actually instantiated — a genuine, business-logic-breaking regression in variant count versus cycle 3's already-flagged defect. |
| VBO/action fidelity | N/A for this cycle | Do-step 3 explicitly and correctly out of scope this cycle, per the coordinator's instruction — not scored. Confirmed no regression in the underlying gap (0 `%SomeVar%` placeholders, same as cycle 3). |
| Naming convention | 40% | Real, verified wins: illegal-character sanitisation is now complete (0 illegal `SET` targets across a full regex sweep of both files, not just the named `Sleep-2s` example); `CreateNewDataTable` is `dtb_`-prefixed for 18 of 19 real instances (0 `obj_`, correcting cycle 3's flagged §A4 contradiction — matches the doc's own `dtb_FinalProduct` worked example in spirit, though the generated name itself, `dtb_finalproductCollection`, doesn't match the doc's exact casing); `Consecutive Exception Count/Limit` fully consistent. Real, verified continuing failures: `Retry Count/Limit` diverges via the split-render path (same root cause as above); `FinalProduct_Collection` has 3 incompatible spellings in the same file — the naming-convention dimension is exactly what this cycle's fixes targeted, and 2 of its own 3 named flagship examples are still broken. |
| Error-handling/stop/consecutive-exception | N/A for this task's scope | Owned by Task 5c. Worth flagging forward, more positively than prior cycles: the `Consecutive Exception Count/Limit` state Task 5c's `BLOCK`/`RECOVER` dispatch will need to read/write is now correctly wired end-to-end — genuine forward progress. `Retry Count/Limit`'s retry-loop state is not, and will need the same split-path fix before Task 5c (or any later work) can build reliably on top of it. Also noted, informationally: zero `GLOBAL.` qualifications appear anywhere in either generated file (architecture doc §A4's `GLOBAL.` rule, e.g. `GLOBAL.num_ConsecutiveExcLimit`) — outside this cycle's named scope, but relevant to the exact variables this task is centred on. |
| Well-formedness | 90% | `uv run pytest tests/generator/test_pad.py -q` (67/67), `uv run pytest tests/e2e/test_pid171_pipeline.py -q` (16/16, including the `<Definition>`-JSON/well-formedness subset specifically), `ruff check` clean — all reused checks pass, no regression from cycle 3. `IF`/`SET`/`%SomeVar%` counts unchanged. Docked below cycle 3's 75% floor only nominally (kept lower, not raised, despite the new sanitiser fix) because the suite's green status continues to certify a materially incomplete slice of the real corpus — the exact "split" render path where the real defect lives is untested by any unit test, the fourth consecutive cycle this has been true. |

## Most significant gaps

- **`_split_page_into_functions` never receives or threads `variable_name_mapping`.** This is a
  narrow, mechanical, single-function fix (add the parameter, pass it through both internal
  `_render_page_as_function` calls at `pad.py:900` and `945-947`, and thread it from the one real
  call site at `pad.py:738-740`) that would close the `Retry Count/Limit`/`Close Retry Count/
  Limit`/`Enter Values_Retry Count/Limit` divergence entirely — `Result Entry` is the only page
  using the "split" shape in the current mapping, so this is a bounded, verifiable change.
- **`_build_variable_name_mapping` only scans `StageType.DATA`, never `StageType.COLLECTION`.**
  `FinalProduct_Collection` (and any other BP `Collection`) is invisible to the mapping regardless
  of which render path touches it, which is the root cause of its 3-way name split. Extending the
  scan to include `COLLECTION` stages, and teaching the `[Data Item]`/dotted-reference translator
  to recognise `CollectionName.Field` as a namespaced reference into the mapped collection name
  (not a single opaque identifier to sanitise-and-fuse) rather than dropping the `.`, would close
  this.
- **No new test exercises cross-stage consistency inside the same rendered output** — the fourth
  consecutive cycle where this exact structural gap in the test suite is named, and the fourth
  consecutive cycle where a fix verified "real" against isolated fixtures turns out incomplete
  against the full real corpus. A test that renders `Result Entry` (or any `split`-shape page)
  end-to-end and asserts a `Calculation` stage's target variable name matches its `DATA`-stage
  declaration elsewhere in the same file would have caught this before this review did.
- **Implementer's self-reported verification, as the coordinator anticipated, checked only the
  declaration site** ("Confirmed `num_consecutiveExceptionLimit` appears at declaration site with
  correct num_ prefix") and did not check any reference site for any of the three named variable
  families — which is exactly why 2 of 3 remained broken and unreported.

## Verdict

Needs another narrowly-scoped implementation pass — not a restart. The infrastructure this cycle
built (`_build_variable_name_mapping`, its use inside `_translate_bp_expression` and the
`SetVariable` render branch) is sound and already correctly closes the gap for every page rendered
through the "function"/"fold" shapes. What remains, scoped tightly: (1) thread
`variable_name_mapping` through `_split_page_into_functions` and its two internal
`_render_page_as_function` calls — this alone fixes `Retry Count/Limit` and its two siblings;
(2) extend `_build_variable_name_mapping`'s scan to include `StageType.COLLECTION` stages, and
teach the expression translator to resolve `CollectionName.Field`-shaped references against the
mapped collection name rather than sanitising the whole dotted string as one opaque identifier —
this fixes `FinalProduct_Collection`'s 3-way split; (3) add at least one test that renders two
stages referencing the same BP data item through the *same* page-shape path this cycle didn't
cover (a `split`-shape page with a `DATA`/`COLLECTION` declaration plus a `Calculation` reference)
and asserts they agree — closing the recurring test-blind-spot named in every review so far.
