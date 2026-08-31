# Review: Task 5b — 2026-08-31 (second fix pass on the rebuild, commit `2666d35`)

This is the 9th review of Task 5b overall, and the review of the fix pass applied on top of
`85efcbc` (itself reviewed in `docs/reviews/5b-2026-08-31-rebuild-fixpass.md`, ~62%, "needs
another implementation pass"). That review's headline finding was that `_render_call_or_inline`
— the sole render path for every `fold`/`inline_block`-shaped page (8 pages: 6 `fold` + 2
`inline_block` in `mapping/page_target_map.yaml`) — never threaded `variable_name_mapping`
through, causing ≈11.5% of real `SET` lines (26/227) to carry illegal, space-containing targets,
plus two secondary naming bugs (`bool_` instead of canonical `flg_`; doubled prefixes from not
stripping a BP-author's own pre-existing prefix). This review independently verifies commit
`2666d35`'s fix for all three, and — per this task's now well-established pattern across 9 review
cycles — runs a broader independent sweep than the implementer's own narrow verification to check
for anything it didn't cover.

## Headline: the three claimed fixes are genuinely correct and independently confirmed — but the
broader sweep found a real, previously-undetected, corpus-wide naming-casing defect this fix pass
did not touch, plus one new (small) illegal-identifier case its own narrow regex missed

**What's fixed, independently confirmed against a fresh regeneration
(`outputs/review_5b_secondfixpass/`, byte-identical across two separate `uv run flowsmith`
processes):**

- `git show 2666d35`: exactly 1 file changed (`src/flowsmith/generator/pad.py`), 48 insertions /
  10 deletions — matches the implementer's claim exactly, no scratch content.
- `_render_call_or_inline` now accepts and threads `variable_name_mapping` through both its
  `inline_block` and `fold` branches' internal `_render_stage` calls, and both call sites
  (`_render_stage_in_main_page`, `_render_stage`'s `is_subsheet_call` branch) pass it in.
  Confirmed by direct trace of two of the eight fold/inline_block pages, not just the one example
  the implementer's summary cited:
  - **`Reset Global Data`** (fold into `Process Work Queue Items`, §B14 row 17): its rendered
    `# BEGIN fold` block (Performer lines 133–149) now shows correctly prefixed, space-free
    targets — `txt_exceptionType`, `txt_exceptionDetail`, `dt_loadedDateTime`,
    `dt_exceptionDateTime`, `dt_completedDateTime`, `txt_itemkey`, `dt_inputreceivedon` — versus
    the previous cycle's raw, space-containing `datetm_Loaded DateTime`-style targets.
  - **`DataGateway`** (inline_block into `Process Work Queue Items`, §B14 row 15): its rendered
    `BLOCK 'Data gateway block'` (Performer lines 450–465) shows `flg_senddatatodatagateways` and
    `flg_completedwithoutoutcomeexactmatchlogic` — correctly threaded and prefixed (not `None`),
    confirming the parameter fix works for `inline_block` as well as `fold`.
- Corpus-wide independent regex sweep for space-containing `SET` targets
  (`SET [A-Za-z_][A-Za-z0-9_ ]* [A-Za-z_][A-Za-z0-9_ ]* TO`): **0 matches** in both files (was 26
  in the prior cycle). A second, stricter sweep validating every `SET <target> TO` target against
  `^[A-Za-z_][A-Za-z0-9_]*$` found the same 0-for-spaces result (see below for the one thing it did
  catch that isn't space-related).
- `bool_` count: 0. Doubled-prefix sweep (`bool_flg_`, `flg_flg_`, `txt_txt_`, etc.): 0 matches.
- `dt_` (DateTime) prefix now produced: 7 real occurrences (`dt_loadedDateTime`,
  `dt_exceptionDateTime`, `dt_completedDateTime`, `dt_inputreceivedon`, plus 3 more), confirming
  the new `datetime`/`date`/`time` branch in `_apply_type_prefix` is live, not just unit-tested.
- `Consecutive Exception Count/Limit`, `Retry Count/Limit`: single spelling variant each
  (`num_consecutiveExceptionCount`/`Limit`, `num_retryCount`/`Limit`), confirmed corpus-wide, no
  regression.
- `FinalProduct_Collection`: exactly one raw occurrence per file (the `@INPUT` header line only,
  pre-existing low-priority gap, unchanged), all `SET` usages correctly `dtb_finalproductCollection`.
- `Trim`/`Lower` → separate-action-line logic (`_translate_bp_expression`, pad.py:1223–1291) is
  untouched by this diff (confirmed — the diff doesn't cover those line ranges) and remains
  deterministic (counter-based temp-var naming), but still has 0 real invocations against the
  `PID_0171` corpus — same standing gap flagged every cycle since this task began.

## The `flg_iscompleted` casing question — traced to source, and it is a real, previously-uncaught
bug, not an intentional rule

Cross-referencing the real BP XML (`samples/blueprism/PID_0171.bprelease`) confirms the data item
behind `flg_iscompleted` is literally named `flg_IsCompleted` — the BP author had **already**
applied their own `flg_` prefix, in PascalCase, with no internal space. `_apply_type_prefix`
correctly strips the pre-existing `flg_` (that part of this fix pass's work is right), leaving
`IsCompleted`. But the camelCase-conversion step (pad.py:1179–1185) only preserves per-word
casing across **space/underscore-delimited** words:

```python
parts = name_normalized.split()
camel_case = parts[0].lower() + "".join(parts[1:])
```

Because `IsCompleted` has no internal delimiter, it is treated as a single "word" — `parts[0]` —
and unconditionally lowercased in full, producing `iscompleted`, not `IsCompleted`/`isCompleted`.
Compare `dt_loadedDateTime` (source `Loaded DateTime`, has a space, so `parts[1:]` = `["DateTime"]`
survives unlowercased) against `flg_completedwithoutoutcomeexactmatchlogic` (source
`flg_CompletedWithoutOutcomeExactMatchLogic`, no space after prefix-strip — the entire 40-character
name collapses to lowercase). **This is a real, corpus-wide casing-consistency bug, not a
deliberate simplification** — the same semantic role (a §A4-prefixed identifier) renders with
completely different internal-casing fidelity purely depending on whether the BP author happened
to delimit their original name with a space/underscore.

## A bigger, previously-undetected finding: the whole naming pipeline uses camelCase, but the real
reference ground truth is PascalCase — confirmed against `docs/pad-reference/*.robin.txt`

Independently cross-referencing every unique `<prefix>_<Name>` identifier in the two real deployed
reference files found **159 of 159** use a capitalized first letter after the prefix
(`flg_ConfigError`, `num_MaxRetryLimit`, `txt_AnalysisValue`, `dtb_FinalTable`,
`dt_CurrentDateTime`, `lst_ComponentList`, `obj_Config`, …) — architecture doc §A4's own table
examples (`txt_ExceptionMessage`, `num_MaxRetryLimit`, `flg_HaltRun`, `dtb_FinalProduct`,
`dt_CurrentDateTime`) already show the same convention, on closer reading. But
`_apply_type_prefix`'s camel-case step (`parts[0].lower() + ...`) always lowercases the first
letter — it produces camelCase, not PascalCase. A corpus-wide sweep of every `SET <prefix>_<name>
TO` target in the freshly regenerated output found **200 of 200** lowercase-first, **0**
PascalCase. This is a systemic, ~100%-reproducible mismatch against the real reference package's
actual convention, present since the Task 5b rebuild (`109a7e6`) and evidently missed across all
9 review cycles so far — every prior review's naming-convention scoring anchored on architecture
doc §A4's prefix *vocabulary* (which this fix pass now correctly completes: `dt_`/`dtr_`/`obj_`/
`lst_`) without independently cross-checking the *casing* of real examples in
`docs/pad-reference/`. This fix pass did not introduce this defect and it is not part of what it
claimed to fix, but it is real, large in scope, and directly adjacent to the exact function
(`_apply_type_prefix`) this fix pass rewrote — a broader sweep of the very function being changed
would have caught it.

## One new illegal-identifier case the implementer's own regex missed (narrower blind spot, as
flagged): a hyphen, not a space

The implementer's own verification searched specifically for space-containing `SET` targets. A
broader sweep validating every `SET <target> TO` target against `^[A-Za-z_][A-Za-z0-9_]*$` (not
just "no spaces") found:

```
SET num_sleep-2s TO 2 # VERIFY: Sleep-2s (confidence 0.85)
```

(Performer, lines 441 and 578 — two occurrences of the same variable.) The BP source data item is
literally named `Sleep-2s` (confirmed via XML grep). Because the name has no space or underscore,
`_apply_type_prefix`'s word-splitting never touches the embedded hyphen, and it passes straight
through into the identifier — `num_sleep-2s` is not a legal Robin identifier (a bare hyphen inside
an unquoted token is not a valid identifier character; it would most likely be mis-parsed as a
subtraction operator by the real PAD engine). This is a narrow case (1 unique variable, 2 lines)
but it is real, and it is exactly the kind of blind spot a "no spaces" regex — rather than a
"matches `^[A-Za-z_][A-Za-z0-9_]*$`" regex — would miss. `%...%` variable *references* elsewhere in
both files were separately swept and are all clean (no bad characters found there); `CALL '<name>'`
targets use quoted labels, so BP page-name punctuation there is legal Robin syntax and out of scope
for this check.

## Test / lint / determinism verification

- `uv run pytest tests/generator/test_pad.py -q` → **67 passed, 2 failed**, matching the claim
  exactly. Both failures (`test_generate_process_one_file_per_page`,
  `test_real_sample_generates_399_files`) confirmed pre-existing/unrelated — they assert the old
  one-file-per-page shape superseded by Task 5a.
- `uv run pytest tests/e2e/test_pid171_pipeline.py -q` → **16 passed, 0 failed** — covers XML
  well-formedness, all-JSON-valid, `<Definition>` non-empty/JSON-decodable, and the `GOTO`/`LABEL`
  dangle check (`test_no_goto_dangles`), reused as-is per the strategy doc's instruction rather than
  reinvented.
- `uv run ruff check src/flowsmith/generator/pad.py tests/generator/test_pad.py` → clean, 0 errors.
- Two independent full `uv run flowsmith convert` regenerations of `PID_0171.bprelease` produced
  byte-identical `.robin` output (`sha256sum` match on both files) — determinism holds.
- **No new or updated regression test accompanies this fix pass** (`git show 2666d35 --stat` shows
  only `pad.py` changed; `tests/generator/test_pad.py::test_fold_and_inline_block_targets_are_never
  _silently_dropped`, the one existing test that exercises fold/inline_block rendering end-to-end,
  predates this fix pass — from Task 5a — and only asserts the fold/BLOCK markers exist, never
  checks the naming/identifier-legality of content inside them). This repeats a pattern the prior
  review explicitly recommended fixing ("add a regression test that specifically exercises a
  fold/inline_block-shaped page through `generate_process`") — the underlying bug is fixed, but
  nothing in the suite would catch a regression of it going forward.

## Scoring

| Dimension | Score | Evidence |
|---|---|---|
| Structural | N/A | Task 5b's scope is expression translation, not flow/workflow shape. |
| `FUNCTION` functional fidelity | 70% | The fold/inline_block threading fix means DATA/CALCULATION/COLLECTION stages on all 8 previously-broken pages now resolve to the *correct* semantic variable via the same mapping used everywhere else — a real functional win (previously these stages didn't even produce syntactically valid targets). Spot-checked several `%SomeVar%` placeholder cases against the real BP XML (`Exception Type`, `Run Count`) and confirmed most are legitimate — BP `<initialvalue />` genuinely empty, or a `WorkQueues.Get Next Item` output populated at runtime — not silently-dropped real expressions; this is correct behavior, not a gap. But do-step 2's second half (`Trim`/`Lower` → separate action lines) and do-step 3 (VBO `method_actions` substitution) remain wholly unexercised against this corpus (0 real invocations, 0 `vbo_router` references), unchanged standing gaps from every prior cycle, not addressed by this fix pass. |
| VBO/action fidelity | N/A for this cycle | Do-step 3 explicitly out of scope for this fix pass (confirmed by task framing as permanently deferred); `grep -rn "vbo_router\|method_actions" src/flowsmith/generator/pad.py` → 0 matches, consistent with every prior cycle, no regression. |
| Naming convention | 50% | The three specifically claimed fixes are real and independently verified: 0 space-containing `SET` targets (was 26/227), 0 `bool_`, 0 doubled prefixes, `dt_`/`dtr_`/`obj_`/`lst_` branches now live in real output. But the broader sweep this task's history calls for found two defects this fix pass didn't touch: (1) a systemic, ~100%-reproducible casing mismatch against the real reference ground truth — `docs/pad-reference/*.robin.txt` uses PascalCase after every prefix (159/159 unique identifiers), the generator produces camelCase (200/200 `SET` targets sampled), a defect present since the rebuild and missed by all 9 review cycles until this one cross-checked casing specifically, not just prefix vocabulary; (2) a hyphen-containing BP name (`Sleep-2s`) passes through un-sanitized into `num_sleep-2s`, an illegal Robin identifier the implementer's own space-only regex sweep couldn't have caught. `GLOBAL.` qualification remains 0 occurrences anywhere — pre-existing, out-of-this-task's-declared-scope gap, unchanged note carried from every prior cycle. |
| Error-handling/stop/consecutive-exception | N/A for this task's scope | Owned by Task 5c. `Consecutive Exception Count/Limit` state (which 5c's dispatch will read/write) confirmed clean and unchanged, a sound building block. |
| Well-formedness | 88% | `tests/generator/test_pad.py`: 67/69 (2 pre-existing, unrelated failures). `tests/e2e/test_pid171_pipeline.py`: 16/16 (XML/JSON/`<Definition>`/`GOTO`-dangle, reused as-is). `ruff check` clean. Two independent regenerations byte-identical. The flagship well-formedness defect from the prior cycle (space-containing identifiers, invalid Robin syntax) is genuinely fixed corpus-wide. Held below full marks because the e2e suite operates at the XML/JSON/zip-envelope level and does not parse Robin script text for its own syntax validity, so it did not and could not catch the one residual illegal identifier this review found (`num_sleep-2s`, a hyphen inside a bare identifier) — a smaller-blast-radius instance of the exact same severity class (invalid Robin syntax, not a style nit) as the bug this cycle otherwise fixed. |

**Overall: ~60%**

## Most significant gaps

- **[New finding, corpus-wide] The naming pipeline produces camelCase; the real reference ground
  truth is PascalCase.** Confirmed against `docs/pad-reference/DF_PID_171_US_Loader.robin.txt` and
  `DF_PID_171_US_LIMS_Prelude_Main.robin.txt`: 159/159 unique prefixed identifiers use a
  capitalized first letter after the prefix. The freshly regenerated `PID_0171` output: 200/200
  sampled `SET` targets are lowercase-first. `_apply_type_prefix`'s camel-case step
  (`pad.py:1184-1185`, `parts[0].lower() + "".join(parts[1:])`) is the root cause — it needs to
  produce `parts[0].capitalize()` (or preserve the original first-letter casing) instead of always
  lowercasing it, to match §A4/the real reference convention. Not introduced by this fix pass and
  not part of what it claimed to fix, but it's the single biggest naming-convention gap now visible
  and sits directly inside the function this fix pass rewrote.
- **The same root cause produces an inconsistent-casing symptom**, directly answering this review's
  assigned question: `flg_iscompleted` is not an intentional simplification — it is what happens
  when a BP-author-prefixed, no-internal-delimiter name (`flg_IsCompleted`) passes through a
  camelCase algorithm that only preserves per-word casing when a delimiter is present. Compare
  `dt_loadedDateTime` (source had a space, casing survives) against
  `flg_completedwithoutoutcomeexactmatchlogic` (source had none, casing is fully lost) — same rule,
  wildly different outcomes depending on the BP author's original formatting habit.
- **One new illegal identifier found by a broader sweep than the implementer's own check**:
  `num_sleep-2s` (BP source name `Sleep-2s`) — a hyphen, not a space, passes straight through into
  an unquoted Robin identifier. Narrow in blast radius (1 unique variable, 2 lines) but the same
  severity class (invalid Robin syntax) as the space bug this cycle fixed, and undetectable by a
  "no spaces" regex — exactly the blind spot flagged as a risk going in.
- **No regression test accompanies this fix pass.** The one existing test that exercises
  fold/inline_block rendering end-to-end (`test_fold_and_inline_block_targets_are_never_silently_
  dropped`, from Task 5a) only checks that `BEGIN fold`/`END fold`/`BLOCK` markers exist — it does
  not assert anything about the identifiers rendered inside them, so it could not have caught the
  bug this fix pass fixed, and would not catch a regression of it either.
- **Do-step 2's `Trim`/`Lower` translation and do-step 3's VBO `method_actions` substitution remain
  fully unexercised / unimplemented against the real corpus** — unchanged standing gaps carried
  from every prior cycle of this task, not addressed by this fix pass (consistent with its stated,
  narrower scope).

## Verdict — honest assessment of Task 5b's Do-1/2/4 scope (excluding permanently-deferred Do-3)

**Needs another implementation pass — still not at a clean pass bar, but for different, smaller
reasons than every prior cycle.** This is real, verifiable progress: all three specifically claimed
fixes (fold/inline_block mapping threading, `bool_`→`flg_`, pre-existing-prefix stripping) are
genuinely correct, and the flagship defect that blocked the last review (26/227 illegal
space-containing identifiers) is corpus-wide fixed with zero regression on everything previously
verified clean (`Consecutive Exception`/`Retry` spellings, `FinalProduct_Collection`,
determinism, test/lint suites). But per this task's now-established pattern, an independent broad
sweep — this time specifically targeting the exact function this fix pass touched, rather than a
different code path — surfaced a real, corpus-wide naming-casing defect (camelCase vs. the real
reference package's PascalCase, affecting effectively 100% of processed identifiers) that no prior
review caught, plus one small residual illegal-identifier case. The next pass should: (1) fix
`_apply_type_prefix`'s casing step to capitalize the first letter instead of lowercasing it,
matching the real `docs/pad-reference/*.robin.txt` convention; (2) extend the existing sanitization
to strip/replace non-alphanumeric characters generally (not just spaces) so names like `Sleep-2s`
don't leak punctuation into the identifier; (3) add a regression test that asserts identifier
*legality* (not just marker presence) for at least one fold and one inline_block page, so this
class of defect can't silently reappear a third time.
