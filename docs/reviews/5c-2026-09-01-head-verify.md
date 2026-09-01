# Review: Task 5c — 2026-09-01 (from-scratch verification against current HEAD)

**This is an independent, from-scratch review of the current committed state** (`git rev-parse
HEAD` = `51d6ba16764d02b7a165c9bba6704bc5e011d586`, working tree clean — confirmed via `git status
--short` returning nothing). It does not assume any prior same-day review file is accurate.
Earlier files in this chain (`5c-2026-09-01.md`, `-firstpass.md`, `-firstpass-rereview.md`,
`-reverify.md`) are treated as unverified claims only, re-checked here from primary sources
(the committed `src/flowsmith/generator/pad.py`, a fresh regeneration of PID_0171, and the
reference PAD source under `docs/pad-reference/`).

**Headline finding: neither prior account is fully right.**

- The `-reverify.md` review's specific claim — "every processed item gets marked both Completed
  AND Exception because no gating `IF` was generated" and "typed `IsUserDefinedErrorCode` dispatch
  is dead code" — is **false against current HEAD**, confirmed by direct line-by-line trace below.
  The gating `IF`, the `GOTO 'Work end'` skip, and the typed 3-arm dispatch are all present, wired
  correctly, and unconditionally emitted (not gated on `stage.exception_type`, which the code
  itself correctly documents as never populated on `BLOCK` stages).
- However, the coordinator's optimistic read — that the current committed code is fully correct —
  is **also not right**. Regenerating the *whole* PID_0171 output (not just the one flagship
  `BLOCK 'Work'` case) surfaces a real, previously-undetected defect: **6 distinct `GOTO` targets
  across the two consolidated `.robin` files have no matching `LABEL`** — dangling jumps that would
  fail to compile/execute in real PAD. This is the fallback path in
  `_render_stage_list_with_coarse_blocks` (`pad.py` ~line 1938) that fires whenever a coarse
  `BLOCK`'s body has no `SubSheet` call to a page whose name contains "exception" — i.e. every
  coarse `BLOCK` *except* the two that happen to match the worked example's exact shape
  (`BLOCK 'Work'` in the Main page and `BLOCK 'Block24'`).

**Overall: 63%**

| Dimension | Score | Evidence |
|---|---|---|
| Structural | N/A | Task 5c only changes exception-flow rendering inside `FUNCTION`/inlined-body content — it does not touch flow/workflow topology (Task 6a's scope). |
| FUNCTION functional fidelity | 70% | Body-stage order and content inside the coarse `BLOCK` is preserved faithfully (verified against `ast.json` for the Main page's `BLOCK 'Work'`/`RECOVER Recover20`/`RESUME Resume1` triple — stages 5-38 render in source order, minus the two continuation `SubSheet` calls correctly excluded and relocated). But dispatch-target correctness is itself part of "does the control flow do what the source page's flow did," and that fails for 6 of ~8 coarse `BLOCK`s in the real output (see Well-formedness/Error-handling rows) — items processed through those `BLOCK`s would hit an undefined `LABEL` on error, not the correct continuation. |
| VBO/action fidelity | 90% | `CALL 'Get Error'`, `FlowControl.ThrowCustomError CustomErrorCode: ... CustomErrorMessage: ...` all match the real reference syntax verbatim (`docs/pad-reference/DF_PID_171_US_LIMS_Prelude_Main.robin.txt` L1387-1398, L1415 etc.) — not placeholders. Minor: this task's scope is control-flow, not VBO mapping per se, so this is a supporting-evidence score, not the task's core deliverable. |
| Naming convention | 90% | `flg_ErrorOccurred`, `txt_ExceptionType`, `flg_Screenshot`, `txt_ItemStatus` all correctly prefixed per §A4 and match the reference's own names exactly. One real, minor gap: generated labels use `'Mark Item As Exception'`/`'Mark Item As Completed'` (capital "As") vs. the reference's `'Mark Item as Exception'`/`'Mark Item as Completed'` (lowercase "as") — traced to the generator using the literal BP page name verbatim (confirmed in `ast.json`: BP source page is genuinely named `"Mark Item As Exception"`, capital A), which is defensible, but the task's own Done-when text explicitly names the lowercase string as what should appear, and the implementer's own tests (`tests/generator/test_pad.py` L2092 etc.) assert the capitalized form instead of reconciling this. Cosmetic, not functional. |
| Error-handling/stop/consecutive-exception pattern | 58% | The §A5 dispatch *template* itself (2 typed arms + catch-all, no `IF` inside any handler body, flat `SET`+`GOTO` actions) is implemented correctly and matches the reference byte-for-byte in structure (compare `pad.py`'s `_COARSE_TYPED_HANDLERS`/`_COARSE_CATCHALL_ACTIONS` + `templates/pad/actions/error_block.robin.j2` output against reference L1385-1399). The post-`BLOCK` gating `IF`/`GOTO` dispatch (§A5 Do-step 2/3) is also correctly wired for the flagship worked example. But the "`GOTO`/`LABEL` dispatch to named continuation points" requirement (Do-step 3, explicit in the task text) is broken for the general case: 6 of ~8 real coarse `BLOCK`s in the generated PID_0171 output (`Step 1 Block`, `Input` ×2, `Input_Excel Details`, `Input_Mail` ×2, `Mail`) emit `GOTO '<name> recovery'` with **no corresponding `LABEL`** anywhere in the file — see Well-formedness row for the exact list. |
| Well-formedness | 55% | XML/JSON structure is fine — `uv run pytest tests/e2e/test_pid171_pipeline.py -v` passes all 17 tests including `test_all_xml_is_well_formed`, `test_all_json_is_valid`, and `test_no_goto_dangles`. But `test_no_goto_dangles` only checks the two hardcoded targets `'Error Block'`/`'End'`, not the dynamic dispatch labels this task's feature introduces — so it doesn't catch the real gap. Direct scripted GOTO/LABEL-set-difference check against the freshly regenerated output (see below) found: Loader — `'Mail Details recovery'` dangling; Performer — `'Input recovery'`, `'Mail recovery'`, `'Step 1 Block recovery'`, `'Input_Mail recovery'`, `'Input_Excel Details recovery'` dangling (6 total unique dangling targets across both files). |

## What was actually traced (control-flow verification)

Regenerated fresh: `uv run flowsmith convert --input samples/blueprism/PID_0171.bprelease --output
outputs/generated/PID_0171_review_5c_head/ --managed` against clean `HEAD` (no working-tree diff).
`PID_171_US_Process_LIMS_Prelude_Performer.robin` lines 127-348, `BLOCK 'Work'`:

```
127  BLOCK 'Work'
128  ON BLOCK ERROR 'Business Exception' IsUserDefinedErrorCode: True
     ... CALL 'Get Error' / SET txt_ExceptionType / SET flg_ErrorOccurred TO True
132  ON BLOCK ERROR 'System Unavailable Exception' IsUserDefinedErrorCode: True
     ... SET flg_Screenshot TO True / CALL 'Get Error' / SET txt_ExceptionType / SET flg_ErrorOccurred TO True
137  ON BLOCK ERROR all
     ... SET flg_Screenshot TO True / CALL 'Get Error' / SET flg_ErrorOccurred TO True
141  END                              <- closes handler-arm section (matches reference L1399)
142..337  <body: per-item processing, incl. nested singleton BLOCKs>
338  END                              <- closes the BLOCK itself (matches reference L1468)
339  IF flg_ErrorOccurred = True THEN
340      SET txt_ItemStatus TO 'Failed'
341      GOTO 'Mark Item As Exception'
342  END
343  LABEL 'Mark Item As Completed'
344  CALL 'Mark Complete'
345  GOTO 'Work end'
346  LABEL 'Mark Item As Exception'
347  CALL 'Mark Exception'
348  LABEL 'Work end'
```

**Happy path:** body completes with `flg_ErrorOccurred` still `False` → `IF` at 339 is false → falls
through `LABEL 'Mark Item As Completed'` → `CALL 'Mark Complete'` → `GOTO 'Work end'` → skips
`LABEL 'Mark Item As Exception'`/`CALL 'Mark Exception'` entirely, lands at `LABEL 'Work end'`.
**Exception path:** a handler sets `flg_ErrorOccurred = True` → `IF` at 339 is true → `GOTO 'Mark
Item As Exception'` jumps straight past `LABEL 'Mark Item As Completed'`/`CALL 'Mark Complete'` →
lands at `LABEL 'Mark Item As Exception'` → `CALL 'Mark Exception'` → falls through to `LABEL 'Work
end'`. **No double-marking in either path** — the `-reverify.md` claim does not hold for this code.

Also confirmed directly: `stage.exception_type` is documented in `ast/models.py` (L219-225) as
"only populated for EXCEPTION stages," never `BLOCK` — but `pad.py`'s typed-handler arms
(`_COARSE_TYPED_HANDLERS`) are a module-level constant always rendered by
`_render_stage_list_with_coarse_blocks`, **not conditioned on `stage.exception_type` at all** — so
the "dead code" claim is also false; the typed arms are unconditionally reachable and correctly
rendered for every coarse `BLOCK`.

## The real defect found (not previously reported)

Script (run against the freshly regenerated output, both consolidated `.robin` files):

```python
gotos = set(re.findall(r"GOTO '([^']+)'", text))
labels = set(re.findall(r"LABEL '([^']+)'", text))
dangling = gotos - labels
```

Result: **Loader** — `{'Mail Details recovery'}`. **Performer** —
`{'Input recovery', 'Mail recovery', 'Step 1 Block recovery', 'Input_Mail recovery',
'Input_Excel Details recovery'}`. Traced to `pad.py`'s fallback:
`dispatch_label = exception_label if exception_label is not None else f"{stage.name} recovery"`
(pad.py ~L1938) — when a coarse `BLOCK`'s body (the range between `BLOCK` and its paired `RECOVER`)
contains no `SubSheet` call to a page whose name contains "exception", the code invents this
`'<name> recovery'` label text but **never emits a matching `LABEL` for it anywhere**. Cross-checked
against `ast.json`: every one of the 6 affected `BLOCK`s (`Step 1 Block` in `Launch_Sample
Manager`, `Input_Excel Details` in `Read Input Data From Excel`, `Input_Mail` in `Send mail` and
`Send mail - No New Mail`, `Mail` in `Summary_Report`, `Input` in several fold/inline pages) does
have a real `recover_stage_id` (so it correctly enters the coarse-`BLOCK` path and gets typed
handler arms) — it's specifically the label-dispatch step, not the handler template, that's broken
for these. Only the two `BLOCK`s whose body happens to contain an "Exception"/"Completed"-named
`SubSheet` call (`BLOCK 'Work'`, `BLOCK 'Block24'`) produce a valid, landing `LABEL`. These
fold/inline sub-pages are the majority of coarse `BLOCK`s in the real PID_0171 output, so this is
not an edge case — it affects most of the feature's actual output. A low-risk fix exists: these
FUNCTIONs already have a working `LABEL 'Error Block'` (from the pre-existing singleton-`BLOCK`
`GOTO_ERROR_BLOCK` epilogue mechanism) in the same scope — routing the fallback dispatch there
instead of a never-defined synthetic label would close the gap without new design work.

## Test results (re-run against current HEAD, not trusted from any prior report)

- `uv run pytest tests/generator/test_pad.py -v` → **75 passed**, 0 failed (coverage gate failure
  is the pytest.ini/pyproject global 85% threshold applied to a single-file subset run — expected
  and not a Task 5c regression; irrelevant to this task's own Done-when, which only names the test
  command, not the coverage gate).
- `uv run pytest tests/e2e/test_pid171_pipeline.py -v` → **17 passed**, 0 failed (same coverage-gate
  caveat).
- Both of Task 5c's own named synthetic tests
  (`test_coarse_block_synthetic_page_produces_flat_handler_and_goto_label`,
  `test_coarse_block_two_continuation_labels_routes_correctly`) and the real-sample test
  (`test_coarse_block_pid171_process_work_queue_items_structure`) pass — but all three exercise
  only the worked-example shape (an exception-continuation `SubSheet` call present in the body),
  never the fallback path that's actually broken.

## Most significant gaps

- **Dangling `GOTO` targets for the non-worked-example case.** 6 confirmed instances across the
  two consolidated `.robin` files (`Step 1 Block recovery`, `Input recovery`, `Mail recovery`,
  `Input_Excel Details recovery`, `Input_Mail recovery` ×2, `Mail Details recovery`) — real PAD
  would fail to resolve these jumps. This is the task's own Do-step 3 ("Implement `GOTO`/`LABEL`
  dispatch to named continuation points") not actually satisfied outside the one shape the task's
  tests check.
- Existing e2e coverage (`test_no_goto_dangles`) only validates the two pre-existing hardcoded
  targets (`'Error Block'`, `'End'`) and doesn't catch dynamically-named dispatch labels — a test
  gap that let this ship unnoticed through the task's own Done-when.
- Minor: label casing (`'Mark Item As Exception'` vs. reference `'Mark Item as Exception'`) is
  defensible (traces to the real BP page name) but is a literal mismatch against the task's own
  Done-when wording and the implementer's tests assert the mismatched form as correct rather than
  flagging the discrepancy.

## Verdict

**Needs another (narrow, targeted) implementation pass** — but not the same pass the
`-reverify.md` review called for. That review's specific diagnosis (double-marking, dead typed
dispatch) is disproven against current `HEAD`; the flagship worked example
(`Process Work Queue Items` / `BLOCK 'Work'`) is genuinely correct and matches the reference
exactly. The real outstanding defect is narrower and different: the fallback dispatch-label path
for coarse `BLOCK`s that don't match the worked example's exact shape (no in-body
exception-named `SubSheet` call) emits a `GOTO` to a `LABEL` that's never defined — a small,
localized fix (e.g. route the fallback to the already-present `'Error Block'` label instead of
inventing an undefined one), not a redesign of the dispatch template or the gating `IF`, which are
both already correct.
