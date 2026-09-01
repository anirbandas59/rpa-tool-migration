# Review: Task 5c — 2026-09-03 (fix pass 3, commit `97bd404`)

**Overall: 95%**

Prior reviews:
- `5c-2026-09-01.md` — 82%, Pass (wrong — missed double-execution bug)
- `5c-2026-09-01-reverify.md` — 58%, Needs Another Pass (correct — found double-execution bug)
- `5c-2026-09-02.md` — 91%, Pass (**wrong** — missed no-op GOTO bug: skip-GOTO from Completed section targeted `'Mark Item As Exception'`, the immediately-following label, making it a no-op in Robin; control fell through to `CALL 'Mark Exception'` unconditionally on every iteration)

**What changed in this pass:** `reset_label = f"{stage.name} end"` introduced; skip-GOTO now targets `reset_label` (e.g. `GOTO 'Work end'`); `LABEL 'Work end'` emitted after the last continuation section. Tests corrected to assert GOTO targets reset label AND that reset label appears after `CALL 'Mark Exception'`.

---

| Dimension | Score | Evidence |
|---|---|---|
| Structural | N/A (pre-existing) | 4-flow consolidation is out of scope for Task 5c (pre-existing architectural gap — 2 DF generated instead of 4-flow shape). No new structural regression introduced by this pass. `BLOCK 'Work'` placed correctly at top level of Performer body. |
| FUNCTION functional fidelity | 100% | Control flow at generated lines 338–348 verified by direct output trace. Line 338: `END` (closes BLOCK body). Line 339: `IF flg_ErrorOccurred = True THEN`. Line 340: `SET txt_ItemStatus TO $'''Failed'''`. Line 341: `GOTO 'Mark Item As Exception'`. Line 342: `END`. Line 343: `LABEL 'Mark Item As Completed'`. Line 344: `CALL 'Mark Complete'`. **Line 345: `GOTO 'Work end'`** ← this is the fix. Line 346: `LABEL 'Mark Item As Exception'`. Line 347: `CALL 'Mark Exception'`. Line 348: `LABEL 'Work end'`. Happy path: `CALL 'Mark Complete'` → `GOTO 'Work end'` → jumps **past** both `LABEL 'Mark Item As Exception'` and `CALL 'Mark Exception'` entirely. Error path: gating `IF flg_ErrorOccurred = True` → `GOTO 'Mark Item As Exception'` → `CALL 'Mark Exception'` → falls through to `LABEL 'Work end'`. Neither path double-executes the other section. Matches reference L1473–1490 (`LABEL 'Mark Item as Completed'` → `GOTO 'Reset All'` → `LABEL 'Mark Item as Exception'` → `LABEL 'Reset All'`). |
| VBO/action fidelity | N/A (out of scope) | Task 5c is control-flow only. Expression placeholder gap (`%SomeVar%`, etc.) is pre-existing Task 5b debt, not introduced here. Handler arm actions (`CALL 'Get Error'`, `SET flg_Screenshot TO True`) match reference lines 1386–1398 exactly — unchanged from pass 2. |
| Naming-convention compliance | 95% | `flg_ErrorOccurred` matches reference (L1389/1394/1398). `txt_ItemStatus` set to `$'''Failed'''` matches reference L1470. `txt_ExceptionType` variable in typed handler arms matches reference. Reset label `'Work end'` is synthesized as `f"{stage.name} end"` — matches reference's `'Reset All'` semantic pattern (a per-block unique label after all continuation sections). Minor: label casing `'Mark Item As Exception'` (capital `As`) vs reference `'Mark Item as Exception'` (lowercase `as`) — unchanged from prior reviews, derived from real BP page name, not a bug. |
| Error-handling/stop/consecutive-exception | 100% | All constraints upheld: (1) Handler body is flat — `SET flg_ErrorOccurred TO True`, no `IF`, no `GOTO` inside any handler arm. §A5 hard constraint verified by `test_coarse_block_synthetic_page_produces_flat_handler_and_goto_label` asserting `"IF " not in handler_section` and `"GOTO" not in handler_section` (PASS). (2) Post-block gating `IF flg_ErrorOccurred = True THEN` present. (3) Full 3-arm §A5 dispatch template emitted: `ON BLOCK ERROR 'Business Exception'`, `ON BLOCK ERROR 'System Unavailable Exception'`, `ON BLOCK ERROR` catch-all. (4) `CALL 'Mark Exception'` at depth=0 (outside any BLOCK) — confirmed by depth-tracking trace. (5) No `IF` anywhere inside any handler arm. |
| Well-formedness | 90% | `uv run pytest tests/generator/test_pad.py -v --no-cov -k "coarse_block"` → **3/3 PASS**. `uv run pytest tests/e2e/test_pid171_pipeline.py -q --no-cov` → **16/16 PASS**. Full `tests/generator/test_pad.py` → **71 pass / 2 fail** — both failures are pre-existing stale-baseline tests unrelated to Task 5c (`test_generate_process_one_file_per_page` expects 3 files → gets 2; `test_real_sample_generates_399_files` expects 19 → gets 2). Confirmed pre-Task-5c from prior reviews; no new regressions. Score docked to 90% because these 2 stale tests remain unfixed after three fix passes and the "Done when" condition for Task 5c specifies `uv run pytest tests/generator/test_pad.py -v` (the full suite, not just `-k "coarse_block"`); a strict reading of the done-condition is not met. |

---

## Key verification: no-op GOTO bug is fixed

The bug the coordinator identified in the pass-2 review: `GOTO 'Mark Item As Exception'` was targeting the *immediately-following* label, which Robin treats as a no-op — control fell through to `CALL 'Mark Exception'` unconditionally on every iteration regardless of the `IF flg_ErrorOccurred` gate.

**Verified fixed.** Direct output trace confirms:

```
343: LABEL 'Mark Item As Completed'
344: CALL 'Mark Complete'
345: GOTO 'Work end'          ← targets reset label, NOT the next label
346: LABEL 'Mark Item As Exception'
347: CALL 'Mark Exception'
348: LABEL 'Work end'         ← reset label appears AFTER exception section
```

- `GOTO 'Work end'` (line 345) is between `LABEL 'Mark Item As Completed'` and `LABEL 'Mark Item As Exception'` — confirmed by string-position check (`between` contains `GOTO 'Work end'`, not `GOTO 'Mark Item As Exception'`).
- `LABEL 'Work end'` at char 16636 > `LABEL 'Mark Item As Exception'` at char 16583 — reset label correctly post-dates the entire exception section.
- `CALL 'Mark Exception'` is at depth=0 (outside any BLOCK).

This matches reference L1477 (`GOTO 'Reset All'`) → L1490 (`LABEL 'Reset All'`).

---

## Most significant gaps

1. **[Low — pre-existing, Task 5b scope]** Continuation section bodies are sparse. `LABEL 'Mark Item As Completed'` contains only `CALL 'Mark Complete'`; it omits `SET num_ItemsCompleted TO num_ItemsCompleted + 1` (reference L1476). `LABEL 'Mark Item As Exception'` contains only `CALL 'Mark Exception'`; it omits `SET num_ItemsException TO num_ItemsException + 1`, `SET txt_FailedItemsLog TO ...`, `CALL 'Move Emails'`, `CALL 'Close Application'` (reference L1481–1489). These are expression-translation content gaps, not control-flow structure gaps — out of scope for Task 5c, owned by Task 5b.

2. **[Low — housekeeping]** Two pre-existing stale-baseline test failures remain unfixed after three fix passes: `test_generate_process_one_file_per_page` (expects 3 files, gets 2) and `test_real_sample_generates_399_files` (expects 19, gets 2). These are architectural-gap reflections (old 1-file-per-page baseline vs. current 2-consolidated-flow output) — not Task 5c regressions — but they prevent `uv run pytest tests/generator/test_pad.py -v` (the Task 5c "Done when" command without any `-k` filter) from passing cleanly. The 3 Task 5c `coarse_block` tests all pass; the 2 failures are pre-Task-5c baseline drift.

3. **[Cosmetic]** Label casing `'Mark Item As Exception'` (capital `As`) vs reference `'Mark Item as Exception'` (lowercase `as`). Generated from real BP page name — correct approach; reference-doc text is mildly inconsistent. Not a functional issue.

---

## Verdict

**Pass.**

The no-op GOTO bug identified by the coordinator is confirmed fixed. The generated control flow at lines 338–348 is now correct: `GOTO 'Work end'` from the Completed section genuinely clears the entire exception section (both `LABEL 'Mark Item As Exception'` and `CALL 'Mark Exception'`), matching reference L1477→L1490. All three Task 5c tests pass. 16/16 e2e tests pass. The 2 pre-existing stale-baseline failures are unrelated to this task and pre-date it.

The score is 95% rather than 100% because the full `test_pad.py` suite (the literal "Done when" command) does not pass cleanly due to those 2 stale failures. Fixing them is recommended housekeeping before Task 6a.
