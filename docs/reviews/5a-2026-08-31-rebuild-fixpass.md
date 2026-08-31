# Review: Task 5a — Rebuild fix-pass — 2026-08-31

This reviews the **fix pass on top of the rebuild** (`docs/reviews/5a-2026-08-31-rebuild.md`, 58%,
"needs another implementation pass" — 4 gaps: zero committed regression tests, a `Move Emails`
duplicate-`FUNCTION` regression, an untraced stub-count baseline change, and a silently-regressed
unmapped-page fallback comment). Committed as `516326d` then `ed7bdf5`, current `HEAD`. All four
claimed fixes were independently re-verified against real regenerated output and real test runs
(not trusted from the implementer's summary), per the parent agent's instructions.

**Overall: 78%**

| Dimension | Score | Evidence |
|---|---|---|
| Structural | 90% | Regenerating both `PID_0171.bprelease` and `PID_0127.bprelease` from a clean output dir produces exactly 2 files each (`..._Loader.robin`, `..._Performer.robin`) — the real 2-Desktop-Flow-per-role shape, unchanged from the rebuild cycle. Same residual, pre-existing dock as before (`Send Business Exception Mail` still renders in Performer, not Loader, per §B14 row 20 — an upstream Task 4b role-tagging issue, not this fix pass's scope). |
| FUNCTION functional fidelity | 65% | The `Move Emails` duplicate is fixed and, on inspection, the *retained* body is not a lossy truncation: it contains both the "Mark Email As Read" and "Move Email to Inbox Sub Folder" steps, i.e. the richer of the two source pages' content survived, consistent with `mapping/page_target_map.yaml`'s own note ("Shares Move Emails FUNCTION with row 10 (parameterized by In_txt_DestinationFolder)"). Fold/inline_block/split content, citations, and the `Result Entry` 7-way split all re-verified unchanged and correct (same disclosed split-boundary-placement approximation as the rebuild cycle — not a new gap). Docked because the skipped second-occurrence page produces **no comment at the skip site in the actual `.robin` output** (only in Python source comments) — the 78%-scored cycle two reviews ago had a citing in-file marker for this same case; this fix pass's version is silent in-file, a minor regression relative to that (not relative to the immediately-prior rebuild, which had the duplicate bug outright). |
| VBO/action fidelity | 80% | Unaffected by this fix pass's changes (dedup tracking, test additions, fallback-comment restoration) — re-verified unchanged: `CALL`/`FUNCTION ... [GLOBAL] ... END FUNCTION` skeleton still matches §B12 everywhere checked; conditional `GLOBAL` still correctly limited to exactly 2 real cases (`Fetch Emails from Mailbox`, `Launch Application`). Parameter-passing on `CALL` lines remains explicitly out of this task's scope (Task 5b). |
| Naming convention | 86% | All 9 renamed BP-page→PAD-`FUNCTION` pairs still render consistently under mapped names, and the naming-uniqueness violation from the rebuild (`Move Emails` declared twice) is now independently confirmed gone — exactly 1 declaration, 16/16 unique names in the Performer file. Docked slightly for a real citation-accuracy defect: the restored fallback comment and its code-comment justification cite "architecture doc §B9" for the ReviewFlag-vs-TODO design question, but §B9 ("Scope & ground rules") is actually about the UI-selector-out-of-scope rule — it says nothing about `ReviewFlag`/unmapped-page fallback. This is a mis-citation, not a correct trace, contrary to the project's own "every concrete value must trace to a citation" rule. |
| Error-handling/stop/consecutive-exception | 55% (partially applicable) | Unaffected and unchanged from the rebuild cycle — coarse `BLOCK`/`GOTO`/`LABEL` exception-dispatch correctly remains out of scope (Task 5c); the in-scope `"stop"`-shape citing-comment mechanism still works, re-verified present. |
| Well-formedness | 90% | This is the fix pass's central achievement. All 6 named regression tests exist, are committed (`git diff 5697f29 ed7bdf5 -- tests/generator/test_pad.py` shows the +370-line addition), and pass. Two of them (`test_no_duplicate_function_declarations`, `test_call_function_correspondence_in_generated_files`) were independently proven to actually catch a reintroduced `Move Emails`-style duplicate: temporarily reverting the 4-line dedup guard in `pad.py` and re-running made both fail with the exact expected `{'Move Emails': 2}` assertion message, then the file was restored to a clean `git diff`-empty state. Independent extraction script (not the tests' own helper) confirms zero dangling `CALL`/`FUNCTION` and zero duplicate `FUNCTION` names across both regenerated `PID_0171` files (2/2 Loader, 10/16 Performer, 16 raw = 16 unique) and both regenerated `PID_0127` files (5/5, 14/14). `uv run pytest tests/generator/test_pad.py -v --no-cov` → 59 passed, 2 failed (both genuinely-obsolete one-file-per-page assertions, matching the implementer's claim — `test_real_sample_stub_count`, previously failing, now passes at the fix pass's own baseline). `uv run pytest tests/ -q --no-cov` → 762 passed, 12 failed (the same 10 pre-existing, independently-reproduced-as-pre-existing `test_flag_index.py`/`test_vbo_router.py` failures from every prior cycle, plus the 2 known-obsolete `test_pad.py` failures — no new regressions). `tests/e2e/test_pid171_pipeline.py` → 16/16 passed. `uv run ruff check src/flowsmith/generator/pad.py` → clean. Docked slightly because `test_main_page_split_routes_calls_by_target_role` retains a small `allowed_external` allowlist (`{"Get Error", "<page/subprocess>"}`) that the task's literal "zero allowlist exceptions" bar technically disallows — independently confirmed harmless (`Get Error` really is declared as its own `FUNCTION` in every file that calls it; `<page/subprocess>` only ever appears inside a `#`-prefixed comment line that a stricter, comment-stripping extraction — like the other new tests use — would never have flagged in the first place), but it is a literal-wording miss, not a substantive one. |

## Verification detail

### Git history: what's actually in `516326d` vs `ed7bdf5`

The implementer's summary correctly flagged this as confusing and it is: `516326d`'s tree is
**byte-identical** to the orphaned rebuild commit `5697f29` (`git diff 5697f29 516326d` is empty)
despite `516326d`'s own commit message claiming to add the dedup logic and 6 tests. The real,
substantive fix-pass diff — the 32-line `pad.py` dedup/fallback-comment change and the 370-line
test-file addition — is entirely in `ed7bdf5` (`git diff 5697f29 ed7bdf5` shows exactly those two
files and nothing else). Net effect: `516326d` appears to exist mainly to give the previously-lost
`5697f29` rebuild tree a real, reachable commit on the branch again (fixing the rebuild review's
process-discipline complaint about lost uncommitted work), and `ed7bdf5` is where the actual fixes
live. This is a commit-message/attribution inaccuracy worth a note for house-cleaning, but **HEAD's
final tree state is correct regardless of how the two commits divide the labour** — confirmed
directly by re-running everything against the actual checked-out `ed7bdf5` working tree, not by
trusting either commit message.

### Fix 1 — `Move Emails` duplicate — confirmed fixed in real regenerated output

Regenerated fresh from `samples/blueprism/PID_0171.bprelease` into a clean output directory (not
reusing any prior review's stale directory, which was independently found to produce a
contamination artefact during this review's stub-count investigation — see below). Independent
extraction script (not the implementer's or the tests' own helper):

| File | Unique `CALL` | Unique `FUNCTION` | Raw `FUNCTION` lines | Dangling | Duplicate names |
|---|---|---|---|---|---|
| PID_171 Loader | 2 | 2 | 2 | none | none |
| PID_171 Performer | 10 | 16 | 16 | none | none |
| PID_0127 Loader | 5 | 5 | 5 | none | none |
| PID_0127 Performer | 14 | 14 | 14 | none | none |

`FUNCTION 'Move Emails'` now appears exactly once (line 1217 of the regenerated Performer file),
with real body content — not empty, not a stub. All 3 real `CALL 'Move Emails'` sites resolve to it.

### Regression-catch verification (not just "tests exist and pass")

Per the review brief's explicit ask, the dedup guard was temporarily disabled in
`src/flowsmith/generator/pad.py` (the `if target_name in seen_function_names: continue` block
replaced with a no-op comment) and the affected tests re-run:

```
FAILED tests/generator/test_pad.py::test_no_duplicate_function_declarations
  AssertionError: File PID_171_US_Process_LIMS_Prelude_Performer.robin has duplicate FUNCTION
  declarations: {'Move Emails': 2}
FAILED tests/generator/test_pad.py::test_call_function_correspondence_in_generated_files
  AssertionError: File PID_171_US_Process_LIMS_Prelude_Performer.robin has duplicate FUNCTION
  declarations: {'Move Emails': 2}
```

Both fail with the exact expected shape. The file was restored immediately after
(`git diff src/flowsmith/generator/pad.py` empty afterwards — confirmed clean). This closes the
rebuild review's own explicit warning that "a set-based `calls - functions` correspondence check...
would not have caught this" — `test_call_function_correspondence_in_generated_files` was rewritten
in this fix pass to additionally do a `Counter`-based duplicate check (not just a set diff),
which is exactly why it now catches the regression a pure set-based check would miss.

### Fix 3 — stub-count baseline (20→18) — number is correct, but the implementer's own trace falls short of project precedent, independently completed here

The committed docstring says: "The reduction from 20 to 18 stubs (exactly 2 fewer) suggests that 2
stub FUNCTION bodies are no longer being emitted... though a per-stage trace would be needed to
pinpoint the exact pages affected" — i.e. the implementer explicitly did **not** do the trace the
project's own established precedent (Task 4a step 8 / this review's brief) requires before updating
a baseline: "Recompute each expected value from a fresh run and confirm by inspection it's explained
by an already-understood cause before updating — don't paper over a real regression as a 'stale
count.'"

This review did the trace directly. Regenerating `PID_0127` with the pre-Task-5a-rebuild `pad.py`
(`git show 23b867a:src/flowsmith/generator/pad.py`, swapped in temporarily then restored) into a
clean directory reproduces the old baseline exactly: 19 files, 20 stubs — confirming the docstring's
"20" starting point is itself correct (a first regeneration attempt without a clean output directory
produced a misleading 38, caused by directory-reuse contamination between two different generator
architectures writing into the same untracked `outputs/` folder — a review-tooling artefact, not a
project defect, and not present in either the implementer's or this review's final numbers once a
clean directory was used).

Diffing the exact stub UUID+name lines between the old (20-stub) and new (18-stub) runs isolates the
change to precisely 2 lines: both instances of `# STUB: [...] Correct Collection for Comma`
that used to render inside a standalone `GetAllFilesFromSharePoint.robin` file. That page is
completely absent from the new consolidated output — not folded, not renamed, not silently dropped
as live content — because `create_annotator().annotate_process()` marks it `reachable = False`
(independently confirmed: `GetAllFilesFromSharePoint reachable=False`, `GetAllFilesPowerShell
reachable=True`), and Task 5a's own Do-step 7 ("Pages tagged unreachable are skipped entirely — not
emitted as dead FUNCTIONs") is doing exactly what it was asked to do. The old, pre-Task-5a-rebuild
`pad.py` never implemented that unreachable-page skip at all, so it rendered the dead page anyway.
**The 20→18 number is correct and fully, traceably benign** — but the implementer shipped it on an
unconfirmed guess rather than the trace the project's own rules require, and got lucky that the guess
was right; this review had to independently do the work the fix pass's own docstring admits it
skipped.

### Fix 4 — unmapped-page fallback comment — confirmed firing on real (non-synthetic) output

The implementer's own summary correctly notes no *PID_171* page currently exercises this path (all
reachable PID_171 pages are curated in `mapping/page_target_map.yaml`). But the same investigation
above incidentally exercises it for real on `PID_0127` (out-of-scope-for-curation by design, since
the mapping is process-scoped to PID_171 only): the regenerated `PID_0127` Performer file contains

```
# TODO: no page_target_map.yaml entry for 'GetAllFilesPowerShell' — treating as default FUNCTION
FUNCTION 'GetAllFilesPowerShell'
```

confirming the restored comment fires correctly on a real, non-synthetic unmapped page, not just a
hypothetical one. `_get_page_shape`'s fallback dict (`{"shape": "function", "unmapped_fallback":
True, "fallback_page_name": page_name}`) and `_render_page_in_consolidated_flow`'s consumption of it
were both read directly and match this behaviour.

### Do-steps 1–5, process-scoping, unreachable-page skip, header-once-per-file — all re-verified unchanged from the rebuild cycle

Regenerated into a clean directory and spot-checked directly (not re-trusted from either review):
`Populate Queue`→`BLOCK 'Add to Queue Block'` (Loader), `DataGateway`→`BLOCK 'Data gateway block'`
(Performer), 6 fold pages with `# BEGIN/END fold:` markers and real content, `Result Entry`'s 7 named
`FUNCTION`s all present, exactly 2 `GLOBAL`-qualified `FUNCTION`s (`Fetch Emails from Mailbox`,
`Launch Application`), `mapping/page_target_map.yaml` nested under a single
`PID_171_US_Process_LIMS_Prelude:` key with 24 entries, `yaml.safe_load` parses cleanly.

## Most significant gaps

- **The `Move Emails` skip is silent in the actual generated `.robin` output.** The code that skips
  the second occurrence has an explanatory comment in `pad.py`'s Python source, but nothing is
  emitted into the `.robin` file itself at the `FUNCTION 'Move Emails'` declaration noting it also
  serves the second source page — a real (if minor) step down from the immediately-prior 78%-scored
  cycle two reviews ago, which had a citing in-file marker for this exact case.
- **The `# TODO`/`ReviewFlag` design-question comment cites architecture doc §B9, which is the wrong
  section** — §B9 is "Scope & ground rules" (UI-selector-out-of-scope), not anything about
  `ReviewFlag` or unmapped-page fallback handling. A real citation-accuracy defect against the
  project's own "every concrete value must trace to a citation" discipline, not a substantive
  functional bug.
- **The stub-count baseline update (Fix 3) was not independently traced by the implementer before
  shipping**, despite the project's own established precedent (cited directly in this review's brief)
  requiring exactly that before accepting a changed baseline as benign. The number turned out to be
  correct and fully explainable (an unreachable page, `GetAllFilesFromSharePoint`, is now correctly
  skipped per Do-step 7) — but that was independently confirmed by this review, not delivered by the
  fix pass itself; the committed docstring still says "a per-stage trace would be needed," i.e. it
  ships an admittedly-incomplete trace as if it were sufficient.
- **`test_main_page_split_routes_calls_by_target_role` keeps a small, harmless-but-real allowlist**
  (`allowed_external = {"Get Error", "<page/subprocess>"}`), against the task's literal "zero
  allowlist exceptions" wording. Independently confirmed inert (both entries are either always a real
  declared `FUNCTION` or only ever appear inside a comment line the test's own regex doesn't filter
  out) — a wording/rigor gap, not a masked defect.
- **Commit-message/attribution mismatch between `516326d` and `ed7bdf5`** (`516326d`'s tree is
  byte-identical to the pre-fix, still-buggy `5697f29`; the real dedup/test changes are entirely in
  `ed7bdf5`, despite `516326d`'s message claiming to contain them) — a git-hygiene issue, not a
  correctness one; `HEAD`'s final state was independently verified correct regardless.

## Verdict

pass. All four gaps named in the rebuild review are genuinely fixed and independently re-verified,
not just re-asserted: the `Move Emails` duplicate is gone from real regenerated output and the new
tests were proven (via a deliberate revert-and-rerun) to actually catch it if reintroduced; 6 named
regression tests are committed, pass, and are durable, re-runnable infrastructure — closing the
rebuild cycle's central, disqualifying well-formedness gap; the stub-count baseline is correct and
this review supplies the missing trace the implementer's own docstring admits it didn't do; the
unmapped-page fallback comment fires correctly on real (PID_0127) output. The full test suite shows
no new regressions beyond the same 10 pre-existing, independently-reproduced-as-unrelated failures
plus the 2 tests the prior cycles already agreed are obsolete. Remaining gaps are real but minor and
non-blocking: a wrong citation (§B9) for the ReviewFlag design question, a silent (in-file) skip at
the `Move Emails` de-dup site, one small inert allowlist against the literal "zero allowlist" wording,
and a stub-count trace that shipped without the diligence the project's own rules call for (though the
number itself holds up). None of these rises to "needs another implementation pass" on its own;
recommend a quick follow-up (not a new task) to: fix the §B9 citation or replace it with the correct
one, add an in-file comment at the `Move Emails` skip site, and paste this review's stub-count trace
into the test docstring so the next reader doesn't have to redo it. Clear to proceed to Task 5c.
