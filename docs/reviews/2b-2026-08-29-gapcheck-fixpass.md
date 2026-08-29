# Review: Task 2b — gap-check fix-pass — 2026-08-29

**Overall: 91%**

This is a fourth pass on Task 2b, reviewing the fix-pass the implementer ran in direct response to
`docs/reviews/2b-2026-08-29-gapcheck.md` (55%, "needs another implementation pass" — the pass that
first caught that most of this task's `method_actions` **keys** did not match any real
`action="..."` string in `samples/blueprism/PID_0171.bprelease`, and that
`Utility_Object_Generic_ImageSearch` was a real, uncovered VBO). This pass independently re-derives
the real action strings from the raw sample (not carried over from the prior report), reads every
cited `vbo-action-mapping.md` line directly, builds a real `VBORouter` from the current
`mapping/vbo_catalogue.yaml` and routes it against real stages parsed from
`samples/blueprism/PID_0171.bprelease`, diffs the working tree against the last committed version to
confirm scope discipline, and does a fresh broader sweep of untouched entries. **The core defect
class the gap-check found is now fully closed for the 6 entries this fix pass touched** — every
`method_actions` key matches a real action string exactly, and live routing against real parsed
stages confirms `resolved_action_template` genuinely resolves (not a coincidental dict-key match).
One new, minor finding not raised by the prior review: the `MS Outlook Email VBO Extended`
confidence (`0.35`) is inconsistent with the identical "STOP, no template" category's established
value elsewhere in the same file (`0.15`, used by both Image Search entries and `PID_0003`/`PID_0005`)
— cosmetic (both fall in the same `<0.50` MANUAL confidence band) but worth tidying. The two
previously-flagged out-of-this-task's-scope issues (the `Close Workbook`/`Close Instance` fusion's
structural unreachability against real data — a Task 1b builder gap — and the systemic
method-pattern mismatch in untouched Task-2a-era entries) are re-confirmed present and correctly
left alone.

## Scope recap

Task 2b (`docs/pad-generation-task-prompts.md`, `## Task 2b`) is a pure data-addition/correction
task against `mapping/vbo_catalogue.yaml` only. "Done when": file still parses as YAML and
`uv run pytest tests/mapper/ -v` passes. This fix pass's own summary claims 6 entries
touched/added: `MS Excel VBO` (method key rename), `MS Outlook Email VBO` (method_actions added),
`MS Outlook Email VBO Extended` (rekeyed to real methods, confidence lowered), `MS Outlook Extended
VBO` (rekeyed), `Utility_Object_Generic_ScreenShot` (key rename), and the new
`Utility_Object_Generic_ImageSearch` entry.

## Independent verification performed

### 1. Re-derived real `action="..."` strings directly (not trusted from the prior report)

```
grep -o 'resource object="<VBO>"[^/]*action="[^"]*"' samples/blueprism/PID_0171.bprelease
```
run fresh for all 6 touched/added entries:

| VBO | Real `action=` strings found (count) |
|---|---|
| `MS Excel VBO` | `Create Instance`(5), `Open Workbook`(5), `Get Worksheet As Collection`(4), `Get Worksheet Name`(3), `Close Workbook`(8), `Close Instance`(8), `Write Collection`(1), `Save Current Workbook As`(1) |
| `MS Outlook Email VBO` | `Send Email`(6), `Mark Email As Read`(2), `Move Email to Inbox Sub Folder`(2) |
| `MS Outlook Email VBO Extended` | `Save Attachments`(1) — only one, and it's the only action for this exact VBO name |
| `MS Outlook Extended VBO` | `Get Received Items (Basic) - Group Email`(1) |
| `Utility_Object_Generic_ScreenShot` | `Capture Screenshot`(1) |
| `Utility_Object_Generic_ImageSearch` | `Clipboard image to PNG File`(2), `Take ScreenShot`(2) |

Cross-checked against the current `mapping/vbo_catalogue.yaml`: every `method_patterns` entry for
these 6 VBOs now matches this real list exactly (no extras, no misses), and every `method_actions`
**key** (`Get Worksheet As Collection`, `Write Collection`, `Save Current Workbook As`, `Send
Email`, `Mark Email As Read`, `Move Email to Inbox Sub Folder`, `Get Received Items (Basic) - Group
Email`, `Capture Screenshot`) is byte-identical to a real action string. This is a complete reversal
of the gap-check's finding (previously 9/10 keys never matched).

### 2. Read every cited `vbo-action-mapping.md` line directly — confirmed genuine correspondence

- L41 (`:: Write to cell` → `Excel.WriteToExcel.WriteCell Instance: <ins> Value: <val> Column: <n>
  Row: <n>`) — matches the catalogue's `"Write Collection"` template verbatim. Rekeying to the real
  action name (`Write Collection`) while keeping the cited template's literal text is the correct
  move — the table's row label (`Write to cell`) was BP's *friendly* method label, not the raw
  `action=` string; the actual PAD template content is unaffected by the key rename.
- L43 (`:: Save As` → `Excel.SaveExcel.SaveAs Instance: <ins> DocumentFormat:
  Excel.ExcelFormat.FromExtension DocumentPath: <path>`) — matches `"Save Current Workbook As"`
  verbatim, same reasoning.
- L49–52 (Outlook table, `GetEmailsV3`/`MarkAsRead_V3`/`MoveV2`/`SendEmailV2`) — read complete, not
  excerpted; all four rows correctly attributed to their respective real action names across the
  two Outlook VBOs and the no-suffix VBO. Confirmed byte-identical to the catalogue content
  (this was already correct per the gap-check review's own finding #2, unaffected by this pass).
- `DF_PID_171_US_LIMS_Prelude_Main.robin.txt` L1361 — read directly:
  `Workstation.TakeScreenshot.TakeScreenshotAndSaveToFile File: txt_LastScreenshotPath
  ImageFormat: System.ImageFormat.Png` — matches the catalogue's `"Capture Screenshot"` template
  (parameterised as `<path>` in place of the real variable name, consistent with every other
  entry's templating convention).

All 7 templates the implementer's summary claims (Excel's 2, Outlook no-suffix's 3, Outlook
Extended VBO's 1, Screenshot's 1) check out as genuine, correctly-cited correspondences — not
plausible-sounding fabrications.

### 3. Built a real `VBORouter` and routed real parsed stages — templates genuinely resolve

Ran `build_ast(parse_process("samples/blueprism/PID_0171.bprelease"), router=VBORouter(load_rules()))`
(the actual production code path, not a synthetic router) and called `router.route_stage()` on every
real stage in the parsed AST, filtering for the 6 touched VBOs. Every targeted `(vbo, method)` pair
was found among real stages and resolved correctly:

```
'MS Excel VBO'/'Get Worksheet As Collection' -> is_known=True conf=0.8  template='Excel.ReadFromExcel.ReadAllCells ...'
'MS Excel VBO'/'Write Collection'            -> is_known=True conf=0.8  template='Excel.WriteToExcel.WriteCell ...'
'MS Excel VBO'/'Save Current Workbook As'    -> is_known=True conf=0.8  template='Excel.SaveExcel.SaveAs ...'
'MS Outlook Email VBO'/'Send Email'                       -> is_known=True conf=0.75 template='External.InvokeCloudConnector ... SendEmailV2 ...'
'MS Outlook Email VBO'/'Mark Email As Read'               -> is_known=True conf=0.75 template='... MarkAsRead_V3 ...'
'MS Outlook Email VBO'/'Move Email to Inbox Sub Folder'   -> is_known=True conf=0.75 template='... MoveV2 ...'
'MS Outlook Extended VBO'/'Get Received Items (Basic) - Group Email' -> is_known=True conf=0.75 template='... GetEmailsV3 ...'
'MS Outlook Email VBO Extended'/'Save Attachments'        -> is_known=True conf=0.35 template=''  (correctly empty — no template exists, STOP-noted)
'Utility_Object_Generic_ScreenShot'/'Capture Screenshot'  -> is_known=True conf=0.75 template='Workstation.TakeScreenshot.TakeScreenshotAndSaveToFile ...'
'Utility_Object_Generic_ImageSearch'/'Clipboard image to PNG File' -> is_known=True conf=0.15 template='' (correctly empty — STOP-noted)
'Utility_Object_Generic_ImageSearch'/'Take ScreenShot'             -> is_known=True conf=0.15 template='' (correctly empty — STOP-noted)
```

No entries in the "missing" check (every targeted pair was actually found among real stages, i.e.
these aren't hypothetical pairs). This directly confirms `resolved_action_template` fires for real
data, not merely that the dict keys match in isolation — closing the exact gap the prior review
flagged as the task's most significant defect.

### 4. `MS Outlook Email VBO Extended` confidence (0.35) vs. sibling STOP-note entries (0.15) — inconsistency found, not disqualifying

`.claude/rules/mapping-yaml-conventions.md` requires only "a low `confidence_base`" for
no-confirmed-template rows — it doesn't mandate a specific number. Surveying every `confidence_base`
value in the file: `PID_0003`, `PID_0005`, `Utility - Image Search`, and the new
`Utility_Object_Generic_ImageSearch` — all four "STOP, no confirmed template / needs UI selector"
entries — are set to exactly `0.15`. `MS Outlook Email VBO Extended`, added by this same fix pass
for the identical "real VBO usage confirmed, no confirmed PAD template" situation, is set to `0.35`
— more than double, with no note explaining the difference. Per the confidence-band table in
`CLAUDE.md` (`AUTO >=0.90`, `SPOT-CHECK 0.70-0.89`, `PARTIAL 0.50-0.69`, `MANUAL <0.50`), both
values land in the same `MANUAL` band, so there is no functional difference in generated-output
behaviour today — but it is an unexplained inconsistency in a file whose own stated discipline is
to apply the same treatment to the same category of gap, and it's worth tidying in the next pass
rather than leaving as unexplained drift.

### 5. `Utility_Object_Generic_ImageSearch` — confirmed distinct and correctly captured

`grep -o 'resource object="[^"]*"' samples/blueprism/PID_0171.bprelease | sort -u` re-run fresh:
confirms `Utility_Object_Generic_ImageSearch` is a real, distinct `resource object=` string, separate
from `Utility - Image Search` (whose own real action is `Find Image`, not either of
`Utility_Object_Generic_ImageSearch`'s two actions). The new entry's `method_patterns`
(`Clipboard image to PNG File`, `Take ScreenShot`) exactly match the two real action strings found
for that VBO name (2 occurrences each = 4 stages total, matching the implementer's claimed count).
No conflation with either sibling entry. Correctly STOP-noted, confidence `0.15`.

### 6. `Close Workbook`/`Close Instance` fusion — confirmed genuinely untouched

`git diff mapping/vbo_catalogue.yaml` (working tree vs. last committed `b904885`) shows the fix
pass's edits are exactly the six items described in the implementer's summary — the
`fusion_patterns` block (both the `Create Instance`/`Open Workbook` entry and the `Close
Workbook`/`Close Instance` entry) is byte-identical, untouched. Leaving it alone is the right call:
the gap-check review already established (independently, via `build_ast` + real sample) that this
fusion's unreachability is a **Task 1b `_detect_vbo_call_fusions` structural precondition gap**
(`ast/builder.py:418-535` requires a numeric output→input handoff between the two stages that this
BP idiom never has — both `Close Workbook` and `Close Instance` independently consume `handle` as
an input only), not a catalogue-content defect. Task 2b's own scope is `mapping/vbo_catalogue.yaml`
only; fixing the builder-side detection heuristic would be out of scope for this task.

### 7. Full suite, ruff, YAML validity — fresh run

- `uv run pytest tests/ -q` → **754 passed, 0 failed**, 94.85% coverage (>= 85% threshold).
  Confirms the implementer's/coordinator's reported number exactly.
- `uv run pytest tests/mapper/ -v` → **178 passed** (task's literal "Done when" bar met; the
  coverage-threshold failure line that also prints is a global `--cov-fail-under` artifact of
  running a narrow test subset, not a real test failure — same as in every prior review of this
  task).
- `uv run python -c "import yaml; yaml.safe_load(open('mapping/vbo_catalogue.yaml'))"` → parses
  clean, 39 top-level entries (confirmed the coordinator's independent `== 39` fix to
  `tests/mapper/test_config.py` is correct — `git diff` shows exactly 3 lines changed, `38` → `39`,
  matching the 3 assertions the implementer disclosed as out-of-scope).
- `uv run ruff check tests/mapper/test_config.py` → **All checks passed!** (ruff doesn't lint YAML
  — running it directly against `mapping/vbo_catalogue.yaml` produces Python-syntax noise, as
  expected and as noted by the prior review; not a real defect).

### 8. Broader sanity sweep of untouched entries — confirms the systemic risk is real but correctly out of scope

Only 4 entries in the whole file have `method_actions` populated at all: the 4 already checked above
(`MS Excel VBO`, `MS Outlook Email VBO`, `MS Outlook Extended VBO`,
`Utility_Object_Generic_ScreenShot`) — there is no other populated `method_actions` entry left to
spot-check that wasn't already covered by this pass. Spot-checked `method_patterns` instead (which,
per `vbo_router.py` lines 130-146, has no functional effect on `resolved_action_template` or
confidence today, unlike `method_actions`) on 4 untouched Task-2a-era entries:

| VBO | Catalogue `method_patterns` | Real `action=` strings in sample |
|---|---|---|
| `Utility - Environment` | `Get Value`, `Get Environment Variable`, `Get All Settings` | `Clear Clipboard`, `Get Clipboard`, `Get User Name`, `Kill Process` — **zero overlap** |
| `GET Http File - BLOB` | `Download BLOB` | `HTTP Request File` — no overlap |
| `Utility_Object_Generic_RandomNumberGenerator` | `Generate Random Number` | `Get n Random Numbers (Text)` — no overlap |
| `Utility_Generic_Process_General_Actions`, `Utility_Object_Generic_KillProcess` | (n/a) | **zero occurrences in the sample at all** — these VBOs are not used by PID_0171; likely carried over unmodified from the PID_0127-derived original catalogue (per the file's own header) |

This confirms the gap-check review's "systemic risk" finding is real and extends well beyond Task
2b's own additions — but since these entries have no populated `method_actions` (only inert
`method_patterns`), there is no current functional defect, and none of them are in this task's
declared scope (`mapping/vbo_catalogue.yaml` entries not named in Task 2b's "Do" list, e.g.
`Utility - Environment` is a Task 2a-era entry). Correctly out of scope for this fix pass; flagged
here per the coordinator's explicit ask, for whoever eventually re-curates the Task-2a-era rows or
wires `method_actions`/`resolved_action_template` into a generator task.

## Dimension scores

| Dimension | Score | Evidence |
|---|---|---|
| Structural | N/A | Task touches no flow/workflow generation output — pure `mapping/vbo_catalogue.yaml` data edit. |
| `FUNCTION` functional fidelity | N/A | `resolved_action_template`/`method_actions` are still not consumed anywhere in `src/flowsmith/generator/` (unaffected by this fix pass) — not a defect of this task's scope. |
| VBO/action fidelity | 95% | Every `method_actions` key across all 6 touched/added entries now matches a real `action="..."` string in `samples/blueprism/PID_0171.bprelease` exactly (re-derived independently, not trusted); every cited `vbo-action-mapping.md`/`.robin.txt` line genuinely contains the template claimed; live-routed a real `VBORouter` against real parsed stages and confirmed `resolved_action_template` resolves correctly for all 8 templated pairs and correctly stays empty (with STOP-noted low confidence) for the 3 no-template pairs. This is a complete reversal of the prior gap-check's core finding (9/10 keys previously unreachable; now 0/8 are unreachable). Deducted 5% for: (a) the `MS Outlook Email VBO Extended` confidence (`0.35`) being unexplained/inconsistent with the identical-category sibling entries' `0.15` (cosmetic — same MANUAL band, no functional difference), and (b) the `Close Workbook`/`Close Instance` fusion pattern remaining structurally unreachable against real data — correctly a Task 1b cross-task gap, not a content defect, but it means one of the task's two fusion deliverables still doesn't function end-to-end. |
| Naming convention | N/A | No PAD identifiers / `In_`/`Out_` / `GLOBAL.` qualification touched by this data-only task. |
| Error-handling/stop/consecutive-exception | 90% | STOP-note discipline correctly applied to all 3 no-template entries this pass touched (`MS Outlook Email VBO Extended`, `Utility_Object_Generic_ImageSearch`, plus the unchanged `Utility - Image Search`) — none silently drop a gap. Deducted 10% for the unexplained confidence-level drift (`0.35` vs. `0.15`) noted above, which is a minor internal-consistency lapse in how the STOP discipline is calibrated, not a missing-STOP defect. |
| Well-formedness | 100% | YAML parses (39 entries); `load_rules()`/pydantic schema loads via live router construction; `tests/mapper/ -v` 178/0 (task's literal "Done when" bar); full suite `tests/ -q` 754 passed/0 failed at 94.85% coverage; `git diff` confirms scope discipline (only the 6 claimed entries + the 3 disclosed `test_config.py` count fixes changed); ruff clean on the touched Python test file. |

## Most significant gaps

1. **`MS Outlook Email VBO Extended` confidence (`0.35`) is inconsistent with sibling "STOP, no
   template" entries (`0.15`)** — same category of gap (real VBO usage confirmed, no confirmed PAD
   template), no note explaining the different value. Cosmetic today (both land in the same
   `<0.50` MANUAL band) but should be reconciled — either bring it to `0.15` to match
   `PID_0003`/`PID_0005`/both Image Search entries, or add a note explaining why this case
   legitimately warrants a higher floor than the others.
2. **`Close Workbook`/`Close Instance` fusion remains structurally unreachable against real data** —
   re-confirmed present, correctly untouched by this fix pass (it's a Task 1b `ast/builder.py`
   detection-heuristic gap, not a catalogue-content defect), but still means one of Task 2b's two
   requested fusion-pattern deliverables doesn't fire end-to-end. Needs a Task-1b-side follow-up,
   not a further vbo_catalogue.yaml edit.
3. **The same method-name mismatch bug class this fix pass closed for its own 6 entries still exists
   broadly in untouched Task-2a-era catalogue rows** (`Utility - Environment`, `GET Http File -
   BLOB`, `Utility_Object_Generic_RandomNumberGenerator`, and two entries — `Utility_Generic_Process
   _General_Actions`, `Utility_Object_Generic_KillProcess` — that don't even occur in the sample at
   all). No current functional impact (none have populated `method_actions`, and `method_patterns`
   is inert in `vbo_router.py` today), but confirms the gap-check review's "systemic risk" framing
   is accurate and will need a dedicated pass before any future task wires `method_actions` more
   broadly or before this catalogue is trusted as complete for entries outside Task 2b's explicit
   list.

## Verdict

pass — the specific, serious defect the gap-check review identified (`method_actions` keys that
looked "verbatim correct" against `vbo-action-mapping.md` but never matched any real BP action
string, making them silently inert against the one ground-truth sample this project targets) is
now genuinely and completely closed for every entry this fix pass touched, confirmed independently
via fresh re-derivation of the real action strings, direct citation-content verification, and live
`VBORouter` routing against real parsed stages — not just re-trusting the implementer's dict-key
claims. The two remaining items (the Outlook Extended VBO confidence-level inconsistency, and the
`Close Workbook`/`Close Instance` fusion's continued unreachability) are minor and correctly scoped
as out of this task's remit respectively — neither rises to "needs another implementation pass" on
its own. Recommend a quick, low-effort follow-up to align the `0.35`/`0.15` confidence values before
this file is considered fully closed, and flagging the Task 1b builder gap and the untouched
Task-2a-era mismatches to whoever picks up those respective threads next.
