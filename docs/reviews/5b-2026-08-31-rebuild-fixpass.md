# Review: Task 5b — 2026-08-31 (fix pass on the rebuild, commit `85efcbc`)

This is the 8th review of Task 5b overall, and the 1st review of the fix pass applied on top of
the `109a7e6` rebuild that the previous review (`docs/reviews/5b-2026-08-31-rebuild.md`, 12%)
found severely broken (78–79% of `SET` lines rendering as `SET variable_name TO <raw BP name>`).
This review independently re-derives the coordinator's headline finding rather than taking it on
trust, and root-causes the specific `Retry Limit`/`Retry Count` symptom the coordinator flagged as
under-described by the implementer's own summary.

## Headline: the corpus-wide DATA-stage bug is genuinely fixed — but a second, structurally
guaranteed (not sporadic) mapping-drop bug remains, in a code path this fix pass never touched

**What's fixed, independently confirmed against a fresh regeneration
(`outputs/review_5b_fixpass/`, byte-identical across two separate `uv run python` processes —
`sha256sum` match on both `.robin` files):**

- `grep -c "SET variable_name TO"` → **0** in both Loader and Performer (was 148/29 = 177).
- `num_`/`dtb_` prefixes present broadly: 6/25 and 2/15 occurrences respectively in
  Loader/Performer.
- `Consecutive Exception Count/Limit` — fully clean, single spelling each
  (`num_consecutiveExceptionCount`, `num_consecutiveExceptionLimit`), confirmed independently.
- `FinalProduct_Collection` — confirmed independently: exactly one raw occurrence per file, and
  in both cases it is only the `@INPUT FinalProduct_Collection : { 'Type': 'RecordSet', ... }`
  header/parameter-list line, never a `SET` line. Low priority, agrees with the coordinator's
  own assessment.
- `id(match)` — grepped the source directly (`src/flowsmith/generator/pad.py`): the only surviving
  occurrence of the string is in a comment explaining what was replaced. The `Trim`/`Lower` temp
  variable naming now uses a per-expression `temp_var_counter`. Confirmed deterministic: two
  independent full regenerations produced byte-identical `.robin` output.
- Test fixtures for the `_build_variable_name_mapping` tests were rewritten to the real shape read
  directly from `engine/annotator.py` (`_annotate_data` lines 219–253,
  `{"variable_name", "variable_type", "initial_value"}`; `_annotate_collection` lines 255–269,
  `{"table_name", "variable_type"}`) — verified by reading `annotator.py` directly, not merely
  trusting the summary's line-number citation. The citation is accurate.

**What's still broken — root-caused, not just symptom-matched, and the coordinator's own
characterization ("some ... stages ... on certain pages") undersells how systematic it is:**

`generate_process` (pad.py:343–355) explicitly **skips top-level rendering of any page shaped
`fold` or `inline_block`** in `page_target_map.yaml` — 6 `fold` pages + 2 `inline_block` pages in
the current map (`Reset Global Data`, `Save Attachments`, and others) — with the comment "these
will be rendered when called from other pages." The *only* place they get rendered is
`_render_call_or_inline` (pad.py:591–724), reached exclusively from `_render_stage`'s
`is_subsheet_call` branch (pad.py:1338–1339). That function's signature
(`_render_call_or_inline(self, stage, process, process_map)`) **never accepts
`variable_name_mapping` at all**, and its two internal calls to `_render_stage` for the
`inline_block` and `fold` branches (pad.py:654, 688) call `self._render_stage(s, process,
process_map)` with the parameter omitted — silently defaulting to `None`. Since
`_render_stage`'s `SetVariable` branch falls back to the raw, unmapped `target_var_name` whenever
`variable_name_mapping` is falsy (pad.py:1410–1414), **every DATA/CALCULATION/COLLECTION stage
inside every `fold`/`inline_block`-shaped page renders unprefixed, space-and-all, unconditionally**
— this is not a sporadic or page-specific glitch, it is a deterministic consequence of the render
dispatch structure for that entire page-shape category.

Independently regenerating and grepping confirms this is not limited to `Retry Limit`/`Retry
Count`: inside the `Save Attachments` and `Reset Global Data` folds alone, raw/unmapped `SET`
targets include `Retry Limit`, `Retry Count`, `Entry ID`, `Input File Path`, `Output File Path`,
`Patterns CSV`, `JPG_Patterns CSV`, `Exception Type`, `Exception Detail`, plus several where the
*original BP developer* had already hand-prefixed the data item name with their own convention
(`flg_IsCompleted`, `datetm_Loaded DateTime`, `datetm_Exception DateTime`,
`datetm_Completed DateTime`, `datetm_InputReceivedOn`, `txt_Exception Detail`,
`txt_Exception Stage`) — confirmed via direct XML grep against `PID_0171.bprelease` that these
are the stage's literal BP `name` attribute, not something our code partially transformed; they
pass through completely untouched because `variable_name_mapping` is `None` for this whole render
path, so even a BP-author-supplied prefix with an embedded space (`datetm_Loaded DateTime`) comes
out exactly as authored, which is itself illegal Robin syntax the tool did nothing to sanitize.

Corpus-wide count: of 227 total `SET` lines across both regenerated files (39 Loader + 188
Performer), **26 (≈11.5%)** have a space-containing (illegal Robin identifier) target — all inside
`fold`-shaped page content, all traceable to this one code path. This is a smaller blast radius
than the 78% bug just fixed, but it is the same *severity class*: a space-containing PAD variable
name is invalid Robin syntax, not a cosmetic naming-style miss — the same defect class this task's
own history already flagged and fixed once for `CreateNewDataTable` and the general sanitizer.

**Is this the same bug recurring, or a different one?** Mechanically different, though the same
root category ("`variable_name_mapping` not actually applied"): the just-fixed bug was a
`params_map`-key-shape mismatch inside `_build_variable_name_mapping`/`_render_stage`'s
`SetVariable` branch (the mapping *dict* was being built/read wrong). This one is a missing
parameter-thread-through in an entirely different, untouched function
(`_render_call_or_inline`) — the mapping dict itself is now correct, but it's never *handed to*
the renderer for this one page-shape category. Neither this fix pass's diff (`git show 85efcbc`)
nor its 8 updated/added tests touch or exercise `_render_call_or_inline` at all, so nothing in the
test suite could have caught it — a variant of the same "test doesn't exercise the real code path"
pattern flagged in every prior review of this task, now in a new location.

## Commit-hygiene / `.gitignore` verification

- `git show 85efcbc --stat`: exactly 3 files changed — `.gitignore`, `src/flowsmith/generator/
  pad.py`, `tests/generator/test_pad.py`. No scratch/`outputs/` content in the commit.
- `.gitignore` diff: adds `outputs/` (plural) alongside the pre-existing `output/` (singular).
  Confirmed via `git check-ignore -v` against a freshly generated file
  (`outputs/review_5b_cli/ast.json`) that the new pattern is live.
- `git ls-files | grep '^outputs/'` → empty; no `outputs/` content is or ever was tracked.
- `git status --short` shows only untracked review-report `.md` files (expected, pre-existing from
  other review cycles) — no scratch generation output.

Commit hygiene is sound.

## Test / lint verification

- `uv run pytest tests/generator/test_pad.py -q` → **67 passed, 2 failed**. Both failures
  (`test_generate_process_one_file_per_page`, `test_real_sample_generates_399_files`) confirmed
  pre-existing and unrelated: they assert the old one-file-per-page shape that predates Task 5a's
  consolidation (present unchanged since commit `3e58284`, long before this task's rebuild).
- `uv run pytest tests/e2e/test_pid171_pipeline.py -q` → **16 passed, 0 failed**. Covers XML
  well-formedness, JSON validity, `<Definition>` non-empty/JSON-decodable, `GOTO`-dangle check —
  the exact checks this review's dimension 6 is supposed to reuse rather than reinvent.
- `uv run ruff check src/flowsmith/generator/pad.py tests/generator/test_pad.py` → clean, 0
  errors.
- Full CLI (`uv run flowsmith convert --input samples/blueprism/PID_0171.bprelease --output
  outputs/review_5b_cli`) completes and produces a well-formed, unzippable `.zip`.
- Coverage-threshold failure shown by the generator-only test run (69.83% / 76.87%) is the
  project-wide 85% gate applied to a partial test run, not something this cycle's change caused or
  could pass in isolation — not counted against this task.

## Scoring

| Dimension | Score | Evidence |
|---|---|---|
| Structural | N/A | Task 5b's scope is expression translation, not flow/workflow shape. |
| `FUNCTION` functional fidelity | 68% | The corpus-wide flagship bug (78–79% of all `SET` lines rendering as literal `SET variable_name TO <raw BP name>`) is genuinely fixed, independently confirmed against a fresh regeneration. But a second, structurally guaranteed mapping-drop bug remains untouched by this fix pass: every `fold`/`inline_block`-shaped page (6 + 2 = 8 pages in the current `page_target_map.yaml`) renders its DATA/CALCULATION/COLLECTION stages with `variable_name_mapping=None` unconditionally, because `_render_call_or_inline` never accepts or threads the parameter — 26 of 227 real `SET` lines (≈11.5%) carry an illegal, space-containing target as a direct, deterministic consequence, not an edge case. `Trim`/`Lower`-to-separate-action-line translation (do-step 2) remains real code with passing unit tests but 0 real invocations against `PID_0171` (same standing gap as every prior cycle — the pages with real `Trim(`/`Lower(` calls are still outside the currently-rendered subset). |
| VBO/action fidelity | N/A for this cycle | Do-step 3 (real VBO input/output substitution via `mapper/vbo_router.py`) was not in this fix pass's stated scope and is unchanged: `grep -rn "vbo_router\|method_actions" src/flowsmith/generator/pad.py` → 0 matches; Excel/File action lines still show literal placeholder values (`'C:\path\to\file.xlsx'`, `'Sheet1'`, generic `ExcelInstance`/`DataTable` names), consistent with every prior cycle's note on this dimension. |
| Naming convention | 55% | Where the mapping is actually applied (the majority of DATA/COLLECTION/CALCULATION stages, reached via `_render_page_as_function`/`_render_inline_block`/`_render_fold`'s direct `variable_name_mapping` threading), §A4 prefixes render correctly and camelCased. But: (1) ≈11.5% of real `SET` lines bypass naming entirely via the `_render_call_or_inline` gap above, producing illegal space-containing identifiers; (2) the new `_apply_type_prefix` helper's boolean prefix is `bool_`, not canonical §A4 `flg_`, and it doesn't strip a pre-existing BP-author-supplied prefix before prepending its own — confirmed in real output as double-prefixed names like `bool_flgSendDatatoDataGateways`, `bool_flgCompletedWithoutOutcomeExactMatchLogic`; (3) §A4's `dt_` (DateTime) prefix is never produced by `_apply_type_prefix` (no `datetime`/`date` branch — falls through to the `txt_` default), though this wasn't directly observed in real output because the affected items happen to route through the unmapped fold path first. `GLOBAL.` qualification remains 0 occurrences anywhere — pre-existing, out-of-this-task's-declared-scope gap, unchanged note carried from every prior cycle. |
| Error-handling/stop/consecutive-exception | N/A for this task's scope | Owned by Task 5c. Worth flagging as a positive: `Consecutive Exception Count/Limit`, the state 5c's `BLOCK`/`RECOVER` dispatch will need to read/write, is confirmed clean and internally consistent in this cycle (independently re-verified, not just taken from the coordinator's note) — a sound building block for that task, unlike the destroyed rebuild cycle which had corrupted it. |
| Well-formedness | 78% | `tests/generator/test_pad.py`: 67/69 (2 pre-existing, unrelated failures). `tests/e2e/test_pid171_pipeline.py`: 16/16, covering the exact XML/JSON/`<Definition>`/`GOTO`-dangle checks this dimension is supposed to reuse. `ruff check` clean on both scoped files. Full CLI pipeline produces a well-formed `.zip`. Two independent regenerations are byte-identical (determinism restored). Held meaningfully below full marks because the e2e suite's "well-formed" checks operate at the XML/JSON/zip-envelope level and do not parse the Robin script text inside `<Definition>` for its own syntax validity — so they do not and cannot catch that ≈11.5% of `SET` lines are actually invalid Robin (a bare identifier cannot legally contain a space), a defect this project's own history treats as a well-formedness-severity issue (the same class previously fixed for `CreateNewDataTable`/the general sanitizer), not merely a naming-style nit. |

**Overall: ~62%**

## Most significant gaps

- **[Blocking, same severity class as the just-fixed bug] `_render_call_or_inline` never accepts
  or threads `variable_name_mapping`.** `pad.py:591` (signature) and its two internal
  `_render_stage` calls at `pad.py:654` and `pad.py:688` omit the parameter, defaulting to `None`.
  Because `generate_process` (`pad.py:343-355`) deliberately routes every `fold`/`inline_block`
  page exclusively through this function, this is a 100%-reproducible gap for that entire page
  category (6 `fold` + 2 `inline_block` pages currently mapped), not a sporadic one. Fix: add
  `variable_name_mapping: dict[str, str] | None = None` to `_render_call_or_inline`'s signature,
  thread it from both call sites (`pad.py:521`, `pad.py:1339`), and pass it through to the
  `inline_block`/`fold` branches' `_render_stage` calls.
- **The resulting raw `SET <space-containing name> TO ...` lines are invalid Robin syntax, not a
  cosmetic miss** — confirmed via direct BP-XML cross-reference that several of the raw names come
  straight from the BP author's own (already-prefixed) data-item naming, meaning even names that
  look superficially "already handled" pass through completely unprocessed by this path.
- **`_apply_type_prefix`'s boolean prefix (`bool_`) doesn't match architecture doc §A4's canonical
  `flg_`**, and the function never strips a pre-existing BP-author prefix before prepending its
  own — producing doubled prefixes (`bool_flgSendDatatoDataGateways`) in real output.
- **§A4's `dt_` (DateTime) prefix has no dedicated branch in `_apply_type_prefix`** — DateTime-typed
  DATA stages that *do* route through the mapping would fall through to the `txt_` default; not
  observed as a live defect in this corpus only because the specific DateTime items present happen
  to be routed through the still-broken fold path instead.
- **Do-step 2 (`Trim`/`Lower` → separate action lines) still has zero real-corpus invocations**,
  same standing gap as every prior cycle of this task — real code, passing isolated unit tests,
  never exercised against `PID_0171` output.
- **Do-step 3 (real VBO input/output substitution) remains entirely unimplemented** across every
  cycle of this task, including this one — `vbo_router`/`method_actions` are referenced nowhere in
  `pad.py`. Out of this fix pass's stated scope, but still an open item against the task's full
  Do-list before Task 5b can be called complete.

## Verdict

**Needs another implementation pass.** The specific, corpus-crippling bug this fix pass targeted
(the DATA-stage `params_map`-shape mismatch, ~78% of `SET` lines) is genuinely and verifiably
fixed — real progress, not a re-description of the same failure. But the coordinator's
independent verification surfaced a second, mechanically distinct but same-severity-class defect
(`_render_call_or_inline` silently dropping `variable_name_mapping` for an entire, deterministic
page-shape category) that this fix pass's diff never touched and its tests never exercise. Given
this task's history — eight review cycles, and every cycle so far has either introduced or left
standing at least one code path where the naming mapping silently fails to apply — the next pass
should (1) fix the `_render_call_or_inline` parameter-threading gap identified here, (2) add a
regression test that specifically exercises a `fold`/`inline_block`-shaped page through
`generate_process` (not just `_build_variable_name_mapping` or `_split_page_into_functions` in
isolation) to catch this class of gap going forward, and (3) do a full-file `SET .*TO` regex sweep
for space-containing targets across a fresh regeneration as a standing verification step before
declaring this task done, since two consecutive cycles now have shipped a "verified" fix that a
corpus-wide grep the implementer's own summary didn't run would have caught.
