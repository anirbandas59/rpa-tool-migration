# Review: Task 5a (fourth fix pass) — 2026-08-31

**Overall: 31%**

This is the fifth review of Task 5a, following `docs/reviews/5a-2026-08-30.md` (58%),
`docs/reviews/5a-2026-08-31-fixpass.md` (52%), `docs/reviews/5a-2026-08-31-secondfixpass.md` (42%)
and `docs/reviews/5a-2026-08-31-thirdfixpass.md` (49%). The task prompt itself was rewritten
between the third fix-pass review and this attempt (commits `db4390e`, `9fff88c`) to correct §B10's
"1 page → 1 FUNCTION" rule and add the §B15 exception-bubbling model, and Task 5a's own text was
rewritten with a new 7-step Do-list (page-shape mapping file, CALL resolution through that
mapping, §B15 coarse `BLOCK` wrapping, mapping-driven Main Page split routing, unreachable-page
skipping, header logic) plus an explicit worked example (`Mark Item As Exception`) to
pattern-match against. This review grades that new attempt, not a further tweak of the third
fix-pass's diff — and finds it materially *regresses* dangling-reference count relative to the
third fix-pass baseline while leaving the task's two most heavily-specified new asks (shape
differentiation, §B15 coarse-`BLOCK` dispatch) almost entirely unimplemented.

**Headline finding: `mapping/page_target_map.yaml` is a real, well-cited artefact — every shape
decision documented in it faithfully transcribes architecture doc §B14, including getting
`Result Entry`'s 7 target names and `Sample Manager - Explorer`'s fold target exactly right. But
`generator/pad.py` reads exactly one field from it (`shape`), and only distinguishes two outcomes:
`fold`/`stop` → skip rendering entirely, everything else (`function`, `inline_block`, `split`,
unmapped) → render as one plain `FUNCTION '<raw BP page name>'`.** `target_name`, `block_name`,
`container`, and `targets` are never read anywhere in `pad.py` (confirmed by grep — the only
mapping-dict access is `page_config.get("shape", "function")`). Concretely, against the task's own
four minimum "Done when" examples:

| Done-when requirement | Actual generated output | Verdict |
|---|---|---|
| `Get Mails`/`Populate Queue` as inline `BLOCK`s, no `FUNCTION` | Both render as `FUNCTION 'Get Mails' GLOBAL` / `FUNCTION 'Populate Queue' GLOBAL` | **Failed** |
| `DataGateway`/`Reset Global Data` folded, no wrapper | `DataGateway` (mapped `inline_block`) still renders as `FUNCTION 'DataGateway' GLOBAL`; `Reset Global Data` (mapped `fold`) is skipped but its content is never emitted anywhere — not folded into a target, just gone | **Failed** (both directions) |
| `Result Entry` as 7 named `FUNCTION`s | Renders as one `FUNCTION 'Result Entry' GLOBAL` | **Failed** |
| Every unique `CALL` has a matching `FUNCTION` in the same file | 5/6 unique `CALL` targets dangle in the Loader; 7/16 dangle in the Performer (see below) | **Failed** |

None of the four is met. The implementer's own summary is honest about the first three
(self-reported as deviations/TODOs); the fourth is where the summary is materially incomplete —
it frames the residual dangling-`CALL` problem as "4 known cross-role dangling calls" plus fold-
related dangling, without noting that this is the *exact* same-role Main-Page-split misrouting bug
the third fix-pass review already diagnosed precisely and that this task's Do-step 5 explicitly
names as a "finding [that] stands and must not recur" — it recurs, unchanged, byte-for-byte
(`Mark Item As Completed`, `Mark Item As Exception`, `Read Input Data From Excel`,
`Reset Global Data` still land in the Loader body via raw stage-list index although all four are
performer-role targets).

## Method

Regenerated fresh output from `samples/blueprism/PID_0171.bprelease` into
`outputs/generated/PID_0171_review_5a_new/` (untracked). Read `mapping/page_target_map.yaml` and
`src/flowsmith/generator/pad.py` directly (not the diff summary), confirmed the diff against `git
diff HEAD` (all three changed files are still **uncommitted** working-tree changes — no new commit
exists for this task). Cross-referenced every mapping-file entry against architecture doc §B14's
crosswalk table row-by-row. Wrote a small Python script to extract `page.reachable`/`role` from
`ast.json` and cross-check against the mapping file's page-name keys (found the missing
`Save Attachments` entry this way). Extracted every unique `CALL '<x>'`/`FUNCTION '<x>'` pair from
both generated `.robin` files via regex and diffed the sets. Ran
`uv run pytest tests/generator/test_pad.py -v`, the full suite, `tests/e2e/
test_pid171_pipeline.py`, and `ruff check` on the changed Python files, plus a direct
`yaml.safe_load` on the new mapping file.

## Verification detail

### 1. `mapping/page_target_map.yaml` — citation quality is good, but coverage has a real gap

23 of the 24 §B14 rows are present with a correct `citation` field (spot-checked every row against
architecture doc §B14's table — `Result Entry`'s 7 `targets` match the row-6 list verbatim,
`Sample Manager - Explorer`'s fold target `Open - Entry By Test window` matches row 7 exactly, the
4 orphan/`stop` pages match rows 16/18/21/14 correctly). **Missing entirely: `Save Attachments`
(§B14 row 3)** — confirmed `reachable=True` in the regenerated `ast.json`, confirmed absent as a
key in `page_target_map.yaml`. Do-step 1 explicitly requires "a page with no §B14 row... falls back
to `function`... plus a `ReviewFlag` — never silently invent a different shape for an uncited
page." No `ReviewFlag` mechanism exists anywhere in the diff (confirmed by grep for `ReviewFlag` in
`pad.py` — zero hits); `Save Attachments` silently defaults to `function` shape with its raw BP
name, with no flag raised and no note in the implementer's summary that this page was missed.

**Cross-automation contamination risk, unflagged:** the mapping is keyed purely by page name, with
no process-id scoping. `PID_0127.bprelease` (used by this same task's own updated
`test_real_sample_stub_count`) independently has pages named `Mark Item As Completed`,
`Mark Item As Exception`, `Read Excel As Collection`, `Completed No Outcome`, `Reset Global Data`,
and `DataGateway` — every one of these silently inherits PID_171-specific shape decisions (fold/
stop/inline_block) it was never curated for. The updated test's own comment ("PID_0127 has some
pages that match fold-mapped pages from the mapping file") shows this was noticed and accepted as
expected rather than treated as a defect. This directly contradicts the project's own stated
curation discipline (strategy doc §5, this task's "Out of scope" line: "populating
`mapping/page_target_map.yaml` for any automation other than PID_171 ... is that automation's own
task") — nothing in `pad.py` scopes the mapping lookup to `process.name == "PID_171..."` or
similar, so it silently cross-applies today, to a second real sample already in the repo.

### 2. Shape dispatch in `pad.py` — only `fold`/`stop` actually change behaviour

Read `_generate_consolidated_flow`'s per-page loop directly (lines 372–400). `shape == "fold"` or
`"stop"` → `continue` (skip). `shape == "inline_block"` → explicit `pass` with a `# TODO: Handle
"inline_block" shape` comment, falls through to `_render_page_as_function`. `shape == "split"` →
same `pass`-and-fall-through pattern. Unmapped pages → default `{"shape": "function"}` from
`_get_page_shape`. Net effect: 3 of the mapping file's 4 real shape values (`function`,
`inline_block`, `split`, plus the unmapped-default) all produce byte-identical output — a single
plain `FUNCTION '<raw page.name>' GLOBAL` block, regardless of what the mapping file says the real
target name/split/container should be. This matches the implementer's self-reported deviations
exactly (credit for honest disclosure) — but the practical result is that the mapping file, while
well-researched, is presently almost entirely decorative.

### 3. `_resolve_call_target`/`_render_page_as_function` — `target_name` never applied

Confirmed by grep: `target_name`, `block_name`, `container`, `targets` do not appear anywhere in
`pad.py`'s logic (only in a docstring and an unused local variable named `target_name` that is
actually the *raw resolved page name* from `_resolve_call_target`, not the mapping file's
`target_name` field — a naming collision that makes the code read as if renaming is happening when
it isn't). Generated output confirms this directly: `FUNCTION 'Get Mails' GLOBAL` (not `'Fetch
Emails from Mailbox'`), `FUNCTION 'Mark Item As Completed' GLOBAL` (not `'Mark Complete'`),
`FUNCTION 'Mark Item As Exception' GLOBAL` (not `'Mark Exception'`) — every one of the 9 real
page→`FUNCTION`-rename pairs in §B14 renders under its raw BP page name instead. The implementer's
summary does not call this out as a distinct gap (it's folded into the general "deviations" note
about inline_block/split but not named for the plain `function`-shape pages that were supposed to
get a `target_name` too).

### 4. Do-step 4 (§B15 coarse `BLOCK` wrapping) — not attempted

`_render_structural_stage`/`_render_block_open` are **unchanged** from before this task (confirmed
— this logic pre-dates Task 5a's current diff and implements per-stage `BLOCK`/`RECOVER`/`RESUME`
rendering, not the coarse one-`BLOCK`-per-real-`Block`-stage/flat-handler/`GOTO`-`LABEL`-dispatch
pattern the task's worked example (`Mark Item As Exception` / `Process Work Queue Items`) spends
several paragraphs specifying as the literal required shape). There is no `Process Work Queue
Items` container anywhere in either generated file (confirmed by grep — zero hits) for the fold
targets that name it (`Input File Management`, `Reset Global Data`, `DataGateway`'s `container`
field all point at a `FUNCTION`/body that is never synthesized). This is the single most heavily
documented Do-step in the task text (it cites §A5, §B15, and includes the multi-paragraph worked
example specifically because four prior review cycles had already exhausted the "obvious" fixes) —
and the implementer's summary states plainly it was not attempted ("No mention of §B15/§A5's
coarse BLOCK/ON BLOCK ERROR wrapping... being implemented at all"), which this review confirms is
accurate.

### 5. Do-step 5 (Main Page split routing by target role) — unchanged, same defect recurs

Exhaustive extraction (method identical to the third fix-pass review, for direct comparability):

| File | Unique CALL targets | Unique FUNCTION decls | Dangling CALLs |
|---|---|---|---|
| Loader | 6 | 2 | `Get Error`, `Mark Item As Completed`, `Mark Item As Exception`, `Read Input Data From Excel`, `Reset Global Data` (5 of 6) |
| Performer | 16 | 12 | `<page/subprocess>` (comment, not a real CALL), `Completed No Outcome`, `ConvertConfigFile As Collection - Copy`, `Get Error`, `Input File Management`, `Populate Queue`, `Sample Manager - Explorer` (6 real, excluding the comment) |

The 4 same-role misrouted calls (`Mark Item As Completed`, `Mark Item As Exception`,
`Read Input Data From Excel`, `Reset Global Data`) are byte-identical to the third fix-pass
review's finding — `_split_main_page_if_needed` still splits by raw stage-list index relative to
`Get Next Item`, with no role-aware routing added despite Do-step 5 explicitly naming this as the
required fix. **Net dangling-reference count (11, excluding the 2 pre-existing/comment items) is
worse than the third fix-pass's count (6)** — the 5 new fold-shape dangling references
(`Completed No Outcome`, `ConvertConfigFile As Collection - Copy`, `Input File Management`,
`Populate Queue`, `Sample Manager - Explorer`) are a new regression class introduced by this pass's
own fold-skip logic, since previously every page (even in the "wrong" file) at least got rendered
as *some* `FUNCTION` its `CALL` could resolve to.

### 6. The 2 pre-existing regression tests — still not corrected, as this task's own text required

`test_call_function_correspondence_in_generated_files` and
`test_five_critical_calls_appear_in_loader_for_pid171` are **present, unchanged in their core
assertion shape** from the third fix-pass's version — the task text explicitly called this out as
required work: "the third fix-pass review's own two new tests... encode the old wrong shape as
expected baseline and must be corrected to assert the right file/shape, not just left as-is." They
were not corrected. `test_call_function_correspondence_in_generated_files`'s
`cross_role_loader_calls` allowlist still hardcodes the same 4 same-role dangling calls labelled
"known architectural limitation" (still an incorrect characterisation per the third fix-pass
review's own structural analysis, reproduced independently in §5 above) — and a new
`folded_pages` allowlist was added on top, extending the same weakened-assertion pattern to the 5
new fold-related dangling calls rather than fixing CALL resolution through the fold target (Do-step
3's explicit ask). `test_five_critical_calls_appear_in_loader_for_pid171` still asserts the 4
misplaced calls belong in the Loader as the desired end state.

### 7. Test suite / well-formedness

`uv run pytest tests/generator/test_pad.py -v` → **59 passed** (matches implementer's claim
exactly). `uv run pytest tests/ -q` → **762 passed, 10 failed** — identical failure set to every
prior review cycle (`tests/engine/test_flag_index.py` ×8, `tests/mapper/test_vbo_router.py` ×2),
confirmed pre-existing and unrelated to this task. `tests/e2e/test_pid171_pipeline.py` → **16
passed**, unmodified — this suite's `test_no_goto_dangles` only checks `GOTO`/`LABEL` pairing, not
`CALL`/`FUNCTION`, so it does not (and did not previously) catch any of the dangling-CALL findings
above; XML/JSON well-formedness of the outer package (the `<Definition>` wrapper) is unaffected by
dangling references inside the embedded Robin script text, so those checks pass regardless.
`yaml.safe_load('mapping/page_target_map.yaml')` succeeds. `ruff check
src/flowsmith/generator/pad.py tests/generator/test_pad.py` → clean.

### 8. Implementer summary accuracy check

The self-reported summary is largely honest about what it didn't do (inline_block/split
deviations, no §B15 wrapping, CALL-resolution-through-folding as an open question) — better
disclosure than some prior cycles. Two inaccuracies found: (1) the summary claims the mapping file
carries "a `role` field" — confirmed absent from every entry in `mapping/page_target_map.yaml`
(grep for `role:` returns zero matches); (2) the residual dangling-CALL count is characterised as
"4 known cross-role dangling calls" without noting these are the *same-role* misrouting bug
Do-step 5 was specifically written to fix, nor that 5 *additional* dangling calls now exist from
the new fold logic — a net dangling-reference increase this review's exhaustive extraction confirms
directly, not merely 4 pre-accepted exceptions.

## Score breakdown

| Dimension | Score | Evidence |
|---|---|---|
| Structural | 30% | The file-level skeleton this task inherited (2 files, correct Loader/Performer role split, correct filenames) holds unregressed. But the task's own central structural ask — page-shape differentiation (`function`/`inline_block`/`fold`/`split`) — is implemented for exactly one of four outcomes (`fold`/`stop` → skip); `inline_block` and `split` are no-ops that fall through to plain `function` rendering, confirmed by direct code read and matching generated output. |
| FUNCTION functional fidelity | 20% | Per-stage rendering inside each `FUNCTION` is unregressed from before this task. But cross-page wiring is worse than the immediately preceding cycle: 11 real dangling CALL/FUNCTION mismatches across both files (vs. 6 previously), and 5 pages' entire content (`Reset Global Data`, `Sample Manager - Explorer`, `Input File Management`, `Read Excel As Collection`, `ConvertConfigFile As Collection - Copy`) is now silently dropped with zero `# TODO`/comment trace — a direct violation of the project's own "never silently drop a BP construct" rule, worse than the pre-task baseline where these pages at least rendered as *some* `FUNCTION`. |
| VBO/action fidelity | 45% | `CALL '<name>'`/`FUNCTION '<name>' GLOBAL` syntax skeleton matches architecture doc §B12's literal template wherever it renders. But `GLOBAL` is applied unconditionally to every `FUNCTION` (confirmed in `templates/pad/subflow.robin.j2`, which was in this task's file scope and left untouched) though architecture doc §A3's own FUNCTION inventory marks most Performer functions non-`GLOBAL` — a real, in-scope, unaddressed fidelity defect. |
| Naming convention | 15% | None of the 9 real BP-page→renamed-`FUNCTION` pairs in §B14 (`Get Mails`→`Fetch Emails from Mailbox`, `Mark Item As Exception`→`Mark Exception`, etc.) are applied — every `FUNCTION` renders under its raw BP page name. `target_name`/`block_name` fields exist in the mapping file but are never read by the generator (confirmed by grep). `GLOBAL` qualifier misapplied as above. |
| Error-handling/stop/consecutive-exception | 20% | Pre-existing per-stage `BLOCK`/`RECOVER`/`RESUME` rendering still functions and is unregressed. But Do-step 4 — the task's single most heavily documented requirement (§A5/§B15 citations plus a dedicated worked example) — was not attempted at all, confirmed by the implementer's own summary and by direct code diff (no change to `_render_structural_stage`/`_render_block_open`). |
| Well-formedness | 40% | Outer package XML/JSON well-formedness and the existing `test_no_goto_dangles`-style checks pass unregressed (16/16 e2e tests). But by this dimension's own explicit "no dangling references" criterion, exhaustive CALL/FUNCTION extraction finds 11 real dangling references across both files — a higher count than the immediately preceding review cycle found (6) — and the two regression tests specifically added to guard this area were left with the same weakened/incorrect allowlist-based assertions the prior review explicitly said must be corrected, not merely retained. |

## Most significant gaps

- **The mapping file's `shape` values are ~75% decorative.** `mapping/page_target_map.yaml` is
  well-cited and structurally sound, but `generator/pad.py` only branches on 2 of its 4 possible
  shape outcomes (`fold`/`stop` vs. everything else). `target_name`, `block_name`, `container`, and
  `targets` — the fields that would actually produce the task's required output shapes — are never
  read anywhere in the generator.
- **All four of the task's explicit minimum "Done when" examples fail**: `Get Mails`/`Populate
  Queue` still render as `FUNCTION`s, not inline `BLOCK`s; `DataGateway` still renders as a
  `FUNCTION` (not folded, not wrapped as its mapped `inline_block`); `Result Entry` renders as one
  `FUNCTION`, not 7; and CALL/FUNCTION correspondence is worse (11 dangling) than before this task
  ran.
- **Do-step 5's exact defect ("must not recur") recurs unchanged.** The 4 same-role calls
  (`Mark Item As Completed`, `Mark Item As Exception`, `Read Input Data From Excel`,
  `Reset Global Data`) still land in the Loader file via raw stage-list index despite targeting
  performer-role pages — byte-identical to the third fix-pass review's finding, which this task's
  own text quoted verbatim as the thing to fix.
- **Do-step 4 (§B15 coarse `BLOCK`/`GOTO`/`LABEL` dispatch, the task's most heavily specified new
  requirement) was not attempted at all** — confirmed by the implementer's own disclosure and by a
  direct diff showing zero change to the relevant rendering functions.
- **New silent content loss for 5 fold-shaped pages**, with no `# TODO`/comment marking what was
  dropped or where it should go — a direct, unflagged violation of this project's core "never
  silently drop a BP construct" rule (`CLAUDE.md`, `.claude/rules/pad-pipeline-workflow.md`), and a
  regression relative to the pre-task baseline where every page at least rendered as *a* `FUNCTION`.
- **The 2 regression tests this task's own text required to be corrected were instead extended
  with the same pattern** — a new `folded_pages` allowlist was added alongside the existing
  `cross_role_loader_calls`/`cross_role_performer_calls` allowlists rather than fixing the
  underlying routing/resolution bugs, so both tests will continue to pass regardless of whether the
  real defects are ever fixed.
- **Unflagged cross-automation contamination risk**: the mapping file has no process-id scoping,
  so PID_171-specific shape curation (fold/stop/inline_block) silently applies to any other
  automation with a same-named page — already demonstrably true for `PID_0127.bprelease`, which is
  in this same test file's own integration tests.
- **Missing `Save Attachments` mapping entry** (§B14 row 3, confirmed `reachable=True`) with no
  `ReviewFlag` raised, despite Do-step 1 explicitly requiring one for any uncited-but-reachable
  page.
- **Minor summary inaccuracies**: claimed "role field" in the mapping file does not exist; the
  residual dangling-CALL characterisation undercounts and mischaracterises the same-role vs.
  fold-related split.

## Verdict

needs another implementation pass. The mapping-file research (`mapping/page_target_map.yaml`) is
genuinely good work and should be kept — its shape/target-name/container decisions are accurately
cited against §B14 (bar the one missing `Save Attachments` row) and don't need re-deriving. But the
generator-side wiring that was supposed to consume it does not: `target_name`/`block_name`/
`container`/`targets` are dead fields, `inline_block`/`split` are unimplemented no-ops, Do-step 4's
coarse-`BLOCK` dispatch (the task's central new ask) was not attempted, and the specific
Main-Page-split-routing defect this task was rewritten to fix recurs unchanged. Net dangling-
reference count is higher than the immediately preceding review cycle, and the two regression tests
meant to guard against exactly this were extended with more of the same weakened-assertion pattern
rather than corrected, as this task's own text explicitly instructed. A fifth pass should: (1) wire
`_render_page_as_function`/`_resolve_call_target` to read `target_name` from the mapping when
resolving both `CALL` targets and `FUNCTION` declarations; (2) implement `inline_block` by
collecting those pages' rendered bodies into the main-body/`container` stream instead of a separate
`FUNCTION`; (3) implement `split` by dividing `page.stages` across the `targets` list (even a naive
per-region split would satisfy the `Result Entry`-as-7-`FUNCTION`s requirement better than the
current single-`FUNCTION` fallback); (4) fix `_split_main_page_if_needed` to route each pre-split
SubSheet call by its own target's role, not the caller's list index (independently re-confirmed as
the correct fix in two consecutive reviews now); (5) actually attempt Do-step 4's coarse-`BLOCK`
pattern against the `Mark Item As Exception` worked example, since it has not yet been tried in any
of five review cycles; (6) add the missing `Save Attachments` mapping entry plus a `ReviewFlag`
mechanism for any future uncited-but-reachable page; (7) scope the mapping lookup to the target
process rather than applying it unconditionally by page name.
