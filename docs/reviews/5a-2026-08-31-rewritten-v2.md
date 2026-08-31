# Review: Task 5a (rewritten, narrower version) — 2026-08-31 (7th cycle)

This is the seventh review cycle on this task's underlying work, and the second against the
rewritten (narrower) Task 5a text. Prior cycles: `5a-2026-08-30.md` (58%), `5a-2026-08-31-fixpass.md`
(52%), `5a-2026-08-31-secondfixpass.md` (42%), `5a-2026-08-31-thirdfixpass.md` (49%),
`5a-2026-08-31-fourthfixpass.md` (31%, pre-split 7-Do-step version), `5a-2026-08-31-rewritten-v1.md`
(31%, first cycle against the narrowed text — found every fold/inline_block-shaped page still
dangling with zero trace, and the rewritten regression test structurally unable to catch it).

**What changed since the 6th cycle (`rewritten-v1`, 31%):** the sixth cycle's single most damning
finding — "every fold/inline_block-shaped page (8 of 8) has zero rendered trace and zero `# TODO`
marker" — is fixed. `_render_call_or_inline` (new) now dispatches every `CALL` on the *target*
page's mapped shape and actually inlines `fold`/`inline_block` content (or a citing `# TODO` when
the container doesn't exist yet), resolves `split` targets to a real entry-point `FUNCTION`, and
emits a citing comment for `stop`-shaped targets instead of a dangling `CALL`. The rewritten
regression test's own structural inability to catch dangling references (also named by the 6th
cycle) is fixed: `test_call_function_correspondence_in_generated_files` now does an unconditional
`calls - functions` set-difference assertion with **zero allowlist**, and this cycle's other new
tests (`test_mapping_lookup_scoped_to_pid171_not_pid0127`, `test_result_entry_splits_into_7_named_
functions`, `test_fold_and_inline_block_targets_are_never_silently_dropped`) each cover one of the
6th cycle's specifically-named gaps.

**Overall: 78%**

## Method

Regenerated fresh from `samples/blueprism/PID_0171.bprelease` into
`outputs/generated/PID_0171_review5a_v2/` and from `samples/blueprism/PID_0127.bprelease` into
`outputs/generated/PID_0127_review5a_v2/` (both untracked). Read `mapping/page_target_map.yaml`,
`src/flowsmith/generator/pad.py`, `templates/pad/subflow.robin.j2`,
`templates/pad/actions/call_subflow.robin.j2`, and `tests/generator/test_pad.py` directly — not
the implementer's summary. Wrote a standalone Python script (not reusing the test file's own
helper) to extract every unique `CALL '<x>'`/`FUNCTION '<x>'` pair from both regenerated `.robin`
files and diff the sets, independently of the new regression test. Cross-checked citation-bearing
claims (`global` values, `Fetch Emails from Mailbox`'s real shape, `Add to Queue Block`'s real
location) directly against `docs/pad-reference/DF_PID_171_US_Loader.robin.txt` and
`DF_PID_171_US_LIMS_Prelude_Main.robin.txt`, not just the architecture doc's summary of them.
Manually traced `Result Entry`'s `stage_counts` boundaries against the actual raw-stage indices of
its three `Sample Manager - Explorer` call sites to check whether folded content lands in the
mapping's own cited `container`. Ran `uv run pytest tests/generator/test_pad.py -v --no-cov`, the
full suite (`--no-cov`), `tests/e2e/test_pid171_pipeline.py`, `ruff check` on the two changed
Python files, and a direct `yaml.safe_load` on the mapping file.

## Verification detail

### 1. Zero-allowlist CALL/FUNCTION correspondence — genuinely fixed, independently confirmed

Direct extraction (own script, not the test's helper) on the regenerated output:

| File | Unique `CALL` targets | Unique `FUNCTION` decls | Dangling |
|---|---|---|---|
| Loader | 2 | 2 | 0 |
| Performer | 10 | 16 | 0 |

Zero dangling references in both files, matching the implementer's claim and the rewritten test's
own (now-genuine) assertion. This is the single most important reversal from the 6th cycle, which
found 12 unique dangling `CALL` targets with zero `# TODO` markers anywhere. `_render_get_error_
boilerplate` closes the largest bucket from that finding (82 occurrences of `CALL 'Get Error'`)
with an honestly-labelled stub `FUNCTION`, citing architecture doc §A3 for what its real body
should eventually do — appropriate, since `Get Error` is pre-existing boilerplate machinery
outside this task's own Do-steps but was blocking its own Done-when bar.

### 2. Do-step 2/3 (`inline_block`/`fold`) — implemented, verified against real output

- `Populate Queue` → `BLOCK 'Add to Queue Block'` renders inside the Loader main body (confirmed:
  `outputs/.../..._Loader.robin` line 29), matching the real reference file
  (`DF_PID_171_US_Loader.robin.txt` L58) exactly.
- `DataGateway` → `BLOCK 'Data gateway block'` renders inline inside the Performer main body with
  a `# §B14 row 15` citation and a `# NOTE: mapped container 'Process Work Queue Items'...`
  comment (the container doesn't exist as a synthesized construct yet — Task 5c's job — so the
  content is placed at the real call site instead, per this task's own carve-out). Confirmed via
  direct read (lines 321-335 of the Performer file).
- `Reset Global Data`/`Save Attachments`/`Input File Management` all render as `# BEGIN fold: ...
  # END fold: ...`-bracketed content with no `FUNCTION`/`BLOCK` wrapper, exactly per §B10 point 3.
  Confirmed present with real stage content (not stub-only), citation comments, and the mapping
  file's own honest disclaimer about `Save Attachments`' real semantic collapse
  (`File.ConvertFromBase64`) being Task 5b's job, not claimed as done here.

### 3. Do-step 4 (`split`) — names correct, `CALL` resolution now wired, but placement fidelity is still weak

`Result Entry` renders as 7 correctly-named `FUNCTION`s (confirmed via direct grep, matches
`test_result_entry_splits_into_7_named_functions`), and the one real `CALL 'Result Entry'` site
(from Main Page) now resolves to the first split target (`Get Results by Analysis and SampleId`)
with a citing `# TODO: ... routed to entry point ... verify against the real per-function call
chain` — the 6th cycle's specifically-named "split-shape `CALL`-resolution was never wired" defect
is fixed.

`stage_counts: [16, 11, 16, 7, 5, 47, 59]` (summing to 161, matching Result Entry's real raw stage
count) is now used instead of even division, proportionally derived from the reference file's real
per-`FUNCTION` line-count ratios — a genuine, disclosed improvement over the 6th cycle's flat
`161 // 7` division, and the mapping file's own comment is honest that this is still an
approximation, not a true per-stage boundary trace.

**New finding, not previously reported:** traced all 3 real `Sample Manager - Explorer` call sites
in `Result Entry`'s raw stage list (indices 51, 139, 156) against the `stage_counts` boundaries
directly. Per the mapping's own `container: "Open - Entry By Test window"` citation (§B14 row 7),
all 3 should land inside that one `FUNCTION`. In the actual generated output, **zero of the three**
do — index 51 lands in `Close Results Entry` (boundary `[50,55)`), and indices 139/156 both land
in `Enter Results in App` (boundary `[102,161)`). The content is never dropped (each fold's
`# BEGIN fold: 'Sample Manager - Explorer'` block is real, confirmed present, with the citing
`# NOTE: mapped container 'Open - Entry By Test window'` comment attached even though it is
factually inlined somewhere else) — but the comment itself is then misleading about where the
content actually ended up, and none of the 3 real occurrences match §B14's own stated target. This
is a direct, if disclosed-as-likely, consequence of `stage_counts` still being a proportional
approximation rather than a real boundary derivation — the implementer's own summary and open
questions already flag this general risk ("per-function content fidelity... can't be verified
without a manual UI-window-transition trace"), but did not call out this specific concrete
manifestation of it.

### 4. Do-step 5 (Main Page split-by-role) — confirmed fixed on both sides of the boundary

Re-verified the specific case the 6th cycle named as still-broken: `Populate Queue` (raw index 18,
loader-role, post-split) now renders in the Loader file's `BLOCK 'Add to Queue Block'` and is
**absent** from the Performer file (`CALL 'Populate Queue'` does not appear anywhere in the
Performer output). `ConvertConfigFile As Collection - Copy` (raw index 62, loader-role, post-split,
folds into the Cloud Flow `CF_PID_171_US_Read Config File`) resolves correctly in the Loader file's
citation comment and does not dangle in Performer. All 5 pre-split SubSheet calls route to the
correct file by target role, matching `test_main_page_split_routes_calls_by_target_role` (passes).

### 5. Do-step 1 (rename wiring + conditional GLOBAL) — confirmed correct, both directions

Enumerated every `shape: function`/`inline_block` mapping entry with a `target_name` and confirmed
each renders under its mapped name consistently on both the `FUNCTION` declaration and every `CALL`
site (`Fetch Emails from Mailbox`, `Fetch Data from Excel file`, `Launch Application`, `Create
Summary Report`, `Mark Complete`, `Mark Exception`, `Send Email`, `Send Business Exception Mail`,
`Move Emails`). The two `global`-value citation errors the 6th cycle found were independently
re-checked directly against the reference files: `Launch Application` is now `global: true`,
confirmed against `DF_PID_171_US_LIMS_Prelude_Main.robin.txt` L402 (`FUNCTION 'Launch Application'
GLOBAL`); `Send Business Exception Mail` is now `global: false`, confirmed against
`DF_PID_171_US_Loader.robin.txt` L173-174 (`FUNCTION 'Send Business Exception Mail' In_txt_To_Email,
...` — no `GLOBAL` keyword). Both fixes verified correct against ground truth, not just internally
consistent.

**New well-formedness defect from the 6th cycle — confirmed fixed:** `Mark as read mail`/`Mark as
read and move to exception folder` both mapped to `target_name: Move Emails` previously produced
two duplicate `FUNCTION 'Move Emails'` declarations. Now only one `FUNCTION 'Move Emails'` renders
(confirmed: exactly 1 in the Performer file); the second page's would-be duplicate is skipped with
a citing `# TODO: 'Mark as read and move to exception folder' also maps to FUNCTION 'Move Emails',
already emitted above... Needs a real parameterized merge (Task 5b), not a duplicate FUNCTION
declaration.` This is an honest deferral (the real fix — a parameterized shared `FUNCTION` per
`In_txt_DestinationFolder` — is Task 5b's expression-translation job), not a silent drop: the
second page's call sites still resolve to the one real `FUNCTION`.

### 6. Do-step 6 (test correction) — genuinely rewritten to assert the literal thing required

`test_call_function_correspondence_in_generated_files` no longer contains any allowlist variable
(confirmed: zero `allowlist` hits in the file) and its core assertion is now an unconditional
`dangling = calls - functions; assert not dangling` per generated file — the exact test shape the
task's "Done when" text specifies. Independently reproduced this same result outside the test
(§1 above) rather than trusting the test's own pass/fail — the test and the direct extraction
agree. `test_main_page_split_routes_calls_by_target_role` (renamed from `test_five_critical_calls_
appear_in_loader_for_pid171`) asserts the correct file/shape per target role, covering both the
pre- and post-split boundary (the 6th cycle's own gap). Two new tests
(`test_result_entry_splits_into_7_named_functions`, `test_fold_and_inline_block_targets_are_never_
silently_dropped`) directly cover the remaining literal Done-when items.

### 7. Process-scoping — re-confirmed correct

Regenerated fresh from `PID_0127.bprelease` (process name `PID_0127_Process_US_BulkUnlock`,
confirmed via a direct AST print) and confirmed zero `# BEGIN fold:` markers and zero
`PID_171`-specific inline-block markers (`Add to Queue Block`, `Data gateway block`) anywhere in
its output — `_get_page_shape` correctly falls back to `{"shape": "function"}` for every page
because the process name has no entry in `page_target_map.yaml`.

### 8. Test suite / lint / e2e

`uv run pytest tests/generator/test_pad.py -v --no-cov` → **62 passed** (matches the implementer's
claim exactly). `uv run pytest tests/ -q --no-cov` → **765 passed, 10 failed** — same failure set
as every prior cycle (`tests/engine/test_flag_index.py` ×8, `tests/mapper/test_vbo_router.py` ×2);
confirmed via `git log`/`git diff` that neither file has been touched by this cycle's diff —
genuinely pre-existing and unrelated. `tests/e2e/test_pid171_pipeline.py` → **16 passed**
(structural well-formedness, GOTO/LABEL balance, JSON/XML validity all unaffected). `uv run ruff
check src/flowsmith/generator/pad.py tests/generator/test_pad.py` → clean. `mapping/page_target_
map.yaml` parses via direct `yaml.safe_load`.

### 9. Deviations, checked against the task text directly

- **Deviation 2 (Get Mails/Populate Queue wording):** the implementer's summary calls the task's
  own "Get Mails ... as inline BLOCK" done-when wording a likely copy/paste leftover, following the
  mapping file (Get Mails = `function`) instead. Independently confirmed this is correct: the real
  reference file (`DF_PID_171_US_Loader.robin.txt` L274) declares `FUNCTION 'Fetch Emails from
  Mailbox' GLOBAL`, called via `CALL 'Fetch Emails from Mailbox'` (L49) — a real `FUNCTION`, not an
  inline `BLOCK`. §B14's own crosswalk table (row 1) agrees (`Get Mails → Fetch Emails from
  Mailbox`), even though §B10's illustrative example text elsewhere in the same architecture doc
  contradicts both the reference file and §B14 by claiming `Get Mails → BLOCK 'Get unprocessed
  emails'`. This is a genuine internal inconsistency in the architecture doc's own required
  reading, not an implementer error — the implementer correctly resolved it by checking ground
  truth over a stale illustrative example.
- **Deviation 4 (ReviewFlag fallback):** implemented as an inline `# TODO` comment
  (`_generate_consolidated_flow`, the `if page.name not in process_map` branch), not a real
  `ReviewFlag` Pydantic object. Confirmed no unmapped-but-reachable page exists in PID_171's current
  output, so this path is never exercised by the real sample and has no dedicated unit test either
  — a real, if narrow, gap against the task's original wording ("plus a flag, not a silent
  default"), honestly surfaced as an open design question rather than silently left unaddressed.

## Score breakdown

| Dimension | Score | Evidence |
|---|---|---|
| Structural | 90% | 2 Desktop Flows generated (Loader, Performer), consolidated-by-role, not per-page files — confirmed. All 4 page-shapes (`function`/`inline_block`/`fold`/`split`, plus `stop`) now dispatch to their correct real construct, verified against actual output for every Done-when-named page. Main Page's split-by-role is fixed on both sides of the `Get Next Item` boundary (the 4th-consecutive-cycle-named defect, independently re-confirmed fixed here). Docked slightly for `Send Business Exception Mail` still rendering in the Performer file instead of Loader (§B14 row 20) — confirmed root cause is upstream Task 4b role-tagging (`ast.json` marks the page `role: performer`), not this task's own code, but it does mean the 2-file split isn't 100% clean yet. |
| FUNCTION functional fidelity | 60% | The central regression this task exists to fix — 8 fold/inline_block pages' content vanishing with zero trace — is genuinely reversed; every one now renders real, citation-marked content at its actual call site. But `Result Entry`'s split-boundary approximation (an honestly-disclosed proportional estimate, not a real per-stage trace) produces a concrete, verifiable content-placement defect: all 3 real `Sample Manager - Explorer` fold sites land outside the mapping's own cited container (`Open - Entry By Test window`), landing in `Close Results Entry`/`Enter Results in App` instead — content preserved, but assigned to the wrong named `FUNCTION` relative to §B14. The duplicate `Move Emails` FUNCTION risk is now resolved with an honest TODO rather than an invalid duplicate declaration. |
| VBO/action fidelity | 80% | `CALL '<name>'`/`FUNCTION '<name>' [GLOBAL]' ... END FUNCTION` skeleton matches §B12's template correctly everywhere checked. `GLOBAL` is now correctly conditional on mapping data, and both of the 6th cycle's miscited `global` values are fixed and independently re-verified against the real reference files. Parameter-passing on `CALL` lines (§B12's `<Param>: <expr>... <OutParam>=> <var>` shape) is not attempted — appropriately out of this task's scope (Task 5b's BP-expression-translation job), not a defect here. |
| Naming convention | 88% | All confirmed renamed BP-page → PAD-`FUNCTION` pairs (`Fetch Emails from Mailbox`, `Fetch Data from Excel file`, `Mark Complete`, `Mark Exception`, `Launch Application`, `Create Summary Report`, `Send Email`, `Move Emails`, `Send Business Exception Mail`) render consistently under their mapped names on both the `FUNCTION` declaration and every `CALL` site, independently re-verified. `GLOBAL` qualification is correct and citation-verified. Docked slightly for the still-untested `# TODO`-only ReviewFlag fallback path and the legacy `generate_page()` method's now-implicit `is_global` default (harmless today since that path is unused by the CLI, but a latent trap). |
| Error-handling/stop/consecutive-exception | 55% (partially applicable) | The coarse `BLOCK`/`GOTO`/`LABEL` exception-dispatch pattern (§A5-A7's main subject) is explicitly out of scope here (Task 5c) and untouched, as declared. What *is* in this task's own scope — the `"stop"`-shape citing-comment mechanism for orphan/no-counterpart pages (§B16) — works correctly and is independently verified: `Completed No Outcome`'s real call site (from `Mark Item As Exception`) now gets a citing `# TODO: STOP...` instead of a dangling `CALL`, closing a defect the 6th cycle counted against well-formedness. Pre-existing `BLOCK`/`RECOVER`/`GOTO` machinery is unregressed by the fold/inline changes (confirmed via `tests/e2e/test_pid171_pipeline.py`'s `test_no_goto_dangles`/`test_block_structure_is_generated`, both passing). |
| Well-formedness | 92% | Zero dangling `CALL`/`FUNCTION` references confirmed by an independent extraction script (not just the rewritten test) across both generated files — the exact literal Done-when bar this task's central ask required, unmet for six consecutive prior cycles, now genuinely met. Full test suite 765 passed / 10 pre-existing-unrelated failures (confirmed via `git diff` that neither failing test file was touched); `tests/e2e/test_pid171_pipeline.py` 16/16; `ruff check` clean; YAML parses; `PID_0127` regeneration confirms zero cross-contamination. |

## Most significant gaps

- **`Result Entry`'s split-boundary approximation produces a real content-placement defect**: all 3
  real `Sample Manager - Explorer` fold call sites land outside the mapping's own cited container
  (`Open - Entry By Test window`) — landing in `Close Results Entry` (1×) and `Enter Results in
  App` (2×) instead. Content is never dropped, and the `stage_counts` approximation is honestly
  disclosed as an approximation in the mapping file's comments, but this specific, concrete
  consequence (a citing comment pointing at a container the content didn't actually land in) was
  not itself called out by the implementer's summary — worth a dedicated follow-up to derive real
  per-stage boundaries (the mapping file's own comment already names the fix: "manual tracing of
  the page's onsuccess-edge flow against each UI window transition").
- **ReviewFlag-on-uncited-page fallback is a `# TODO` comment, not a real `ReviewFlag` object**, and
  is untested (no reachable PID_171 page currently exercises the unmapped-page path) — a real, if
  narrow, gap against the task's original wording, honestly flagged as an open design question
  rather than silently unaddressed.
- **`Send Business Exception Mail` still renders in the Performer file, not Loader**, per §B14 row
  20 — confirmed to be an upstream Task 4b role-tagging defect (`ast.json` marks the source page
  `role: performer`), correctly out of this task's `pad.py`-only scope, and correctly disclosed —
  but it does mean the Loader/Performer split isn't fully clean against the crosswalk yet.
- **The architecture doc's own required reading is internally inconsistent** on `Get Mails`'s real
  shape (§B10's illustrative text says inline `BLOCK`, §B14's crosswalk table and the real
  reference file both say `FUNCTION`) — the implementer resolved this correctly by checking ground
  truth, but the task-doc/architecture-doc text itself should be corrected for future task-scoping
  clarity.
- **Genuine, independently re-verified progress carried from this cycle:** every fold/inline_block
  page now renders real content with citation comments (the central, 6-cycle-repeated failure,
  reversed); `split`-shape `CALL` resolution wired (previously a dangling reference even with all 7
  target `FUNCTION`s present); the regression test rewritten to assert the literal zero-allowlist
  requirement and independently confirmed to actually hold; both `global`-value citation errors
  fixed and re-verified against ground truth; the duplicate `FUNCTION 'Move Emails'` compile risk
  resolved; process-scoping re-confirmed; the `Get Error` boilerplate gap (82 occurrences) closed
  with an honestly-labelled stub.

## Verdict

pass. Every item in this task's literal "Done when" list is met and independently re-verified
against the real generated output (not just the implementer's own claims or the rewritten test in
isolation): zero-allowlist `CALL`/`FUNCTION` correspondence (confirmed via a separate extraction
script), Main Page split-by-role on both sides of the boundary, `Populate Queue`/`Get Mails` shapes,
`DataGateway`/`Reset Global Data`/`Save Attachments` present unwrapped, `Result Entry` as 7 named
`FUNCTION`s, the renamed-page pairs, and PID_171-scoped mapping lookup. The remaining gaps —
`Result Entry`'s split-boundary content-placement imprecision, the untested ReviewFlag-fallback
path, and the upstream `Send Business Exception Mail` role-tagging defect — are legitimate
follow-up material (a `Result Entry` boundary-refinement task, a small ReviewFlag-wiring follow-up,
and a Task 4b bugfix respectively), not reasons to redo this task's own scoped work. Recommended
next steps, in order of impact: (1) derive real `Result Entry` split boundaries from the page's
`onsuccess`-edge flow rather than the current proportional approximation, since the approximation
is now confirmed to misplace real content relative to §B14's own citations; (2) fix the Task 4b
role-tagging defect for `Send mail - No New Mail`; (3) decide whether the ReviewFlag fallback needs
a real `ReviewFlag` object or whether the `# TODO` convention already used elsewhere in this module
is the accepted house style, and either wire it or update the task text to match; (4) proceed to
Task 5c (coarse `BLOCK`/`GOTO`/`LABEL` exception-dispatch pattern), which this task's own text
correctly deferred.
