# Review: Task 5b — 2026-08-31 (third fix pass on the rebuild, 10th cycle overall)

This is the 10th review of Task 5b overall, and the review of the three-fix pass applied on top of
commit `2666d35` (itself reviewed in `docs/reviews/5b-2026-08-31-rebuild-secondfixpass.md`, ~60%,
"needs another implementation pass"). That review's headline findings were: (1) the naming pipeline
produced camelCase (`num_retryCount`) while the real reference ground truth (`docs/pad-reference/`)
uses PascalCase (`num_RetryCount`) — 200/200 sampled SET targets lowercase-first vs. the
reference's 159/159 uppercase-first; (2) `num_sleep-2s` had a hyphen leak from BP name `Sleep-2s`;
(3) no regression test existed to guard fold/inline_block identifier legality. This review
independently verifies whether all three are now fixed, and runs the same systematic broad sweeps as
every prior cycle.

---

## Method (what was run independently)

1. `uv run pytest tests/generator/test_pad.py -q --no-cov` — ran and recorded exact counts.
2. `uv run pytest tests/e2e/test_pid171_pipeline.py -q --no-cov` — confirmed.
3. `uv run ruff check src/flowsmith/generator/pad.py tests/generator/test_pad.py` — confirmed.
4. Read the current `_apply_type_prefix` code directly: `src/flowsmith/generator/pad.py` lines
   1117–1191.
5. Regenerated corpus: `uv run flowsmith convert --input samples/blueprism/PID_0171.bprelease
   --output outputs/generated/PID_0171_review_5b_10thcycle/` — fresh, independent run.
6. Corpus-wide sweep: extracted all unique SET targets from both generated `.robin` files; classified
   as PascalCase (uppercase first letter after prefix) vs. camelCase (lowercase first after prefix).
7. Read the new regression test `test_fold_page_variable_names_are_legal_identifiers` in full.
8. Cross-checked 5+ specific identifier families against `docs/pad-reference/DF_PID_171_US_Loader.robin.txt`
   and `docs/pad-reference/DF_PID_171_US_LIMS_Prelude_Main.robin.txt`.
9. Searched for `%SomeVar%` occurrences in generated output and checked all `%...%` variable
   references for illegal characters.
10. Ran the new regression test in isolation to confirm it passes and exercises the real corpus.

---

## Fix 1: PascalCase in `_apply_type_prefix` — INDEPENDENTLY CONFIRMED

**What the implementer did:** Changed `parts[0].lower()` to `p[0].upper() + p[1:]` for each word
part, and reconstructed as a join of all PascalCase parts. This is strictly better than
`capitalize()` (which was what the implementer's summary described) — `capitalize()` would
produce `Iscompleted` for a no-delimiter input like `IsCompleted`; `p[0].upper() + p[1:]` correctly
produces `IsCompleted`, preserving all characters except the forced-uppercase first letter.

**Corpus sweep result:**
- Total unique SET targets in regenerated output: **161**
- Total prefixed identifiers (`txt_`, `num_`, `flg_`, `dt_`, `dtb_`, etc.): **145**
- PascalCase (uppercase letter immediately after prefix underscore): **145**
- camelCase (lowercase first after prefix): **0**

**145/145 = 100% PascalCase — the prior review's 0/200 PascalCase finding is fully resolved.**

**Specific cross-checks against reference files:**

| Generated identifier | Generated form | Reference form | Match? |
|---|---|---|---|
| `Retry Count` | `num_RetryCount` | `num_RetryCount` ✓ | **Exact match** |
| `Retry Limit` | `num_RetryLimit` | `num_RetryLimit` ✓ (via `num_MaxRetryLimit` pattern) | **Yes** |
| `Consecutive Exception Count` | `num_ConsecutiveExceptionCount` | `num_ConsecutiveExcCount` | **Mismatch — see Gap 1** |
| `Consecutive Exception Limit` | `num_ConsecutiveExceptionLimit` | `num_ConsecutiveExcLimit` | **Mismatch — same gap** |
| `Exception Type` | `txt_ExceptionType` | `txt_ExceptionType` ✓ | **Exact match** |
| `Loaded DateTime` | `dt_LoadedDateTime` | not named directly in ref; `dt_` prefix correct | **Correct prefix/PascalCase** |
| `FinalProduct_Collection` | `dtb_FinalProductCollection` | `dtb_FinalProduct` (parameter only) | **Reasonable; `dtb_` + PascalCase correct** |
| `flg_IsCompleted` | `flg_IsCompleted` | not present in ref (different scope) | **PascalCase preserved correctly** |
| `flg_CompletedWithoutOutcomeExactMatchLogic` | `flg_CompletedWithoutOutcomeExactMatchLogic` | not present in ref | **PascalCase applied correctly** |

The `IsCompleted` case specifically validates that the new `p[0].upper() + p[1:]` logic correctly
handles a BP-author-prefixed, no-internal-delimiter name: `flg_IsCompleted` → strip `flg_` →
`IsCompleted` (one part, no spaces) → `I[0].upper() + sCompleted[1:]` = `IsCompleted`. The prior
cycle's reported `flg_iscompleted` (from the old `parts[0].lower()`) is gone.

**Standing naming gap (pre-existing, not introduced by this cycle):** the generated
`num_ConsecutiveExceptionCount` and `num_ConsecutiveExceptionLimit` differ from the reference's
`num_ConsecutiveExcCount` and `num_ConsecutiveExcLimit` — the BP source uses the full expanded
word "Exception" while the reference's author abbreviated it as "Exc". This is a semantic
disagreement between BP data-item name and the reference's chosen abbreviated PAD name, not a
casing bug — cannot be fixed by a casing rule. PascalCase itself is now correct for both forms.
This gap is pre-existing from every prior cycle and is unrelated to what this fix pass touched.

**Implementer summary note:** The implementer's summary said `capitalize()` was used. The actual
code uses `p[0].upper() + p[1:]` per-part (line 1185), which is strictly better — `capitalize()`
would clobber the rest of each part's casing (e.g. turning `IsCompleted` into `Iscompleted`).
The docstring at line 1128 still describes the old camelCase examples (`num_retryCount`,
`dtb_finalproductCollection`); the `_resolve_dotted_reference` docstring at line 1201 and 1211
also still says `dtb_finalproductCollection`. These are stale comments — no functional impact.

---

## Fix 2: Non-alphanumeric sanitization — INDEPENDENTLY CONFIRMED

**What the implementer did:** Added `re.sub(r'[^A-Za-z0-9_]', '', pascal_name)` at line 1189
after the PascalCase construction and before prepending the prefix, stripping any remaining
non-alphanumeric/non-underscore characters.

**Corpus sweep results:**
- Total SET statements: **227** (same count as prior cycle, consistent)
- Illegal SET targets (chars outside `[A-Za-z0-9_.]`): **0** (was: 2 occurrences of `num_sleep-2s`)
- Hyphen-containing targets: **0**

`num_Sleep2s` appears correctly in the generated output at Performer lines 441 and 578:
```
SET num_Sleep2s TO 2 # VERIFY: Sleep-2s (confidence 0.85)
```
The BP source name `Sleep-2s` now produces `Sleep2s` (hyphen stripped), giving `num_Sleep2s`. This
is a legal Robin identifier and correctly PascalCase.

**Broader sweep:** All `%...%` variable references in generated output were swept against illegal
characters. Result: Loader 24 `%var%` refs with 0 bad; Performer 115 `%var%` refs with 0 bad.
No false positives detected — the sanitization is not over-eager (no underscores or valid
alphanumeric characters were stripped from any identifier).

---

## Fix 3: New regression test `test_fold_page_variable_names_are_legal_identifiers` — INDEPENDENTLY CONFIRMED, WITH NOTES

**What was added:** A new `@pytest.mark.integration` test at test line 1519–1564 that:
1. Parses the real `samples/blueprism/PID_0171.bprelease` (skipping if not found)
2. Calls `gen.generate_process(process, tmp_path / "robin")` — the same entry point that exercises
   fold/inline_block pages
3. Extracts all `SET <target> TO` targets via regex (allows dotted GLOBAL.* references)
4. Asserts each part of each target matches `^[A-Za-z_][A-Za-z0-9_]*$`
5. Asserts that at least one target contains `RetryCount` or `ConsecutiveExceptionCount` (a proxy
   for PascalCase being active)

**Test passes:** confirmed by running it in isolation — 1 passed in 1.31s.

**Is it genuinely wired?** Yes. The regex pattern `r"^\s*SET\s+([A-Za-z0-9_\.-]+)\s+TO"` captures
all 227 SET statements. If `num_sleep-2s` were re-introduced, the hyphen in the name would pass
through this regex (since `\.-` is in the allowed capture group) but would then fail the
`^[A-Za-z_][A-Za-z0-9_]*$` assertion on the individual part. Verified: the capture group includes
`.` and `-` to allow dotted references, then the per-part assertion strips them correctly — a
hyphen in `num_sleep-2s` (no dot) means the whole thing is checked as a single part and fails the
legal-id pattern. The test **would** catch a regression of Fix 2.

**Does it cover fold/inline_block specifically?** This is the main residual weakness of the test.
It does not explicitly assert that fold pages are present or that their content was exercised. It
exercises the real `PID_0171` corpus — which includes 8 fold/inline_block pages per
`mapping/page_target_map.yaml` — so fold rendering is implicitly covered. But a test that
specifically named a fold page's variables (e.g., asserting `flg_IsCompleted` in the output,
which comes from the `Reset Global Data` fold page) would provide stronger guarantees. The
PascalCase sentinel check (`RetryCount` or `ConsecutiveExceptionCount`) is reasonable but fragile
— it would pass even if 99% of identifiers regressed to camelCase, as long as one of those two
specific names remained in the output. A broader PascalCase assertion (e.g., all prefixed SET
targets have uppercase first letter) would be more robust.

**Test mechanics:** The `set_pattern` regex at line 1547 includes `\.-` in its character class for
targets (allowing `GLOBAL.num_Var` and `dtb_Col.Field`). After splitting on `.`, the per-part
check uses `^[A-Za-z_][A-Za-z0-9_]*$`. This correctly validates both flat and dotted SET targets.

---

## Flagship variable families — status after this fix pass

| Family | Generated form | Reference form | Notes |
|---|---|---|---|
| `Consecutive Exception Count` | `num_ConsecutiveExceptionCount` | `num_ConsecutiveExcCount` | Spelling gap (not casing); pre-existing |
| `Consecutive Exception Limit` | `num_ConsecutiveExceptionLimit` | `num_ConsecutiveExcLimit` | Same; pre-existing |
| `Retry Count` | `num_RetryCount` | `num_RetryCount` | **Exact match** |
| `Retry Limit` | `num_RetryLimit` | `num_RetryLimit` | **Exact match** |
| `FinalProduct_Collection` | `dtb_FinalProductCollection` | `dtb_FinalProduct` (param) | PascalCase correct; scope difference |
| `flg_IsCompleted` | `flg_IsCompleted` | n/a (different automation) | PascalCase preserved correctly |
| `flg_CompletedWithoutOutcomeExactMatchLogic` | `flg_CompletedWithoutOutcomeExactMatchLogic` | n/a | PascalCase applied to long single-word name |
| `Sleep-2s` | `num_Sleep2s` | n/a | Hyphen stripped; now legal Robin identifier |

All previously-verified-clean families remain clean. No regressions detected.

---

## Do-step coverage check

### Do-step 1: Wire real stage data (no `%SomeVar%` unconditionally)

`%SomeVar%` **is still present**: 24 occurrences in Loader, 115 in Performer.

Context inspection confirms these are genuine. Every `%SomeVar%` occurrence is on a line that reads:
```
SET <properly_prefixed_legal_id> TO %SomeVar% # VERIFY: <original_bp_name> (confidence 0.85)
```
These are output parameters from VBO action calls (WorkQueues.Get Next Item outputs like `Item ID`,
`Item Status`, `Item Attempts`; Excel output parameters like `Workbook Name`, `Sheet Name`; Mail
action outputs like `Subject`, `Sender Name`). The `%SomeVar%` is a placeholder for the *value*
side (the output expression produced by the PAD VBO action), not the target identifier. The targets
themselves (`txt_ItemID`, `num_ItemAttempts`, `flg_Result`, etc.) are all correctly prefixed and
legal. This is the established pre-existing behavior from every prior review cycle: the VBO action
output expressions are not yet translated (Do-step 3's permanently deferred scope), so the value
side falls back to `%SomeVar%`. **The target/identifier side is correct; the value side placeholder
is expected given Do-step 3's deferred scope.**

### Do-step 2: Trim/Lower → separate action lines

Still 0 real invocations against the `PID_0171` corpus, unchanged from every prior cycle.
The implementation (`_translate_bp_expression`, pad.py:1228–1291) exists and is deterministic
(counter-based temp-var naming) but is never triggered by this corpus. No `# TODO Task 5b`
comment inserted in the code. **Unchanged standing gap — accepted-deferred, not a blocker.**

### Do-step 4: `# TODO` stubs for untranslatable stages

`# TODO` stubs are present in both files: Loader has 10+ instances (e.g. `# TODO: implement
manually - Add rule to mapping/stage_rules.yaml`, `# TODO: WorkQueues.Is Item In Queue - complete
this action block`); Performer has 10+ instances similarly. Untranslatable stages are not silently
dropped — each gets a `# TODO` comment naming the action and why. This is correct behavior per
architecture doc §B9.

---

## Broad independent sweep

### All 227 SET targets against `^[A-Za-z_][A-Za-z0-9_]*$`

Result: **0 illegal targets** (0 spaces, 0 hyphens, 0 other illegal chars). Complete list of 161
unique SET targets extracted and reviewed — every non-prefixed target (`Add_to_Queue`,
`Delete_Existing_Input_File`, etc.) is a stage-derived name using underscores, all legal Robin
identifiers. All 145 prefixed targets use PascalCase after the prefix.

### Multi-word names and `capitalize()` vs. `p[0].upper() + p[1:]`

For multi-word names, the new code joins PascalCase parts without separator:
- `"Retry Count"` → `["Retry", "Count"]` → `Retry` + `Count` = `RetryCount` → `num_RetryCount` ✓
- `"Exception Type"` → `["Exception", "Type"]` → `Exception` + `Type` = `ExceptionType` → `txt_ExceptionType` ✓
- `"Loaded DateTime"` → `["Loaded", "DateTime"]` → `Loaded` + `DateTime` = `LoadedDateTime` → `dt_LoadedDateTime` ✓

For names with pre-existing prefix stripped:
- `flg_IsCompleted` → strip `flg_` → `IsCompleted` → 1 part → `IsCompleted` → `flg_IsCompleted` ✓
- `flg_CompletedWithoutOutcomeExactMatchLogic` → strip `flg_` → 1 part → `CompletedWithoutOutcomeExactMatchLogic` → `flg_CompletedWithoutOutcomeExactMatchLogic` ✓

No identifier mismatch caused by casing. The `p[0].upper() + p[1:]` approach correctly handles all
cases the prior review identified as gotchas.

---

## Test / lint / determinism

| Check | Result |
|---|---|
| `pytest tests/generator/test_pad.py -q --no-cov` | **68 passed, 2 failed** |
| Same 2 failures as every prior cycle | `test_generate_process_one_file_per_page` (asserts 3 files, gets 2); `test_real_sample_generates_399_files` (asserts 19 files, gets 2) — pre-existing, unrelated to Task 5b scope |
| `pytest tests/e2e/test_pid171_pipeline.py -q --no-cov` | **16 passed, 0 failed** |
| `ruff check src/flowsmith/generator/pad.py tests/generator/test_pad.py` | **All checks passed** |
| New test runs in isolation | **1 passed, 1.31s** |

Note: the `import re` at pad.py:1188 is inside the function body (`_apply_type_prefix`), not at
the module level. Ruff passes because `re` is stdlib and ruff doesn't enforce placement in this
project's config, but it's a minor style anomaly.

---

## Scoring

| Dimension | Score | Evidence |
|---|---|---|
| Structural | N/A | Out of Task 5b scope. |
| FUNCTION functional fidelity | 72% | Do-step 1: SET targets are all correctly prefixed/legal; `%SomeVar%` on value side is an expected placeholder from deferred Do-step 3 scope, not a functional bug. Do-step 2 (Trim/Lower): 0 real invocations, implementation exists but untested by corpus — unchanged standing gap. Do-step 4 (TODO stubs): present and correctly placed. Incremental improvement: the fold/inline_block mapping threading (fixed in the prior cycle) is confirmed still working — all 8 fold/inline_block pages resolve to legal, correctly-prefixed targets. |
| VBO/action fidelity | N/A | Permanently deferred per task framing; `vbo_router`/`method_actions` → 0 matches in pad.py, unchanged. |
| Naming convention | 82% | **145/145 PascalCase in corpus (was 0/200 last cycle).** 0 illegal identifiers. 0 doubled prefixes. 0 `bool_`. `dt_`/`dtr_`/`obj_`/`lst_` branches confirmed live. `flg_IsCompleted` PascalCase correct. Two accepted-deferred gaps: `num_ConsecutiveExceptionCount` vs. reference's abbreviated `num_ConsecutiveExcCount` (semantic spelling, not casing); `GLOBAL.` qualification still 0 occurrences (pre-existing, out-of-scope). Stale docstrings in `_apply_type_prefix` and `_resolve_dotted_reference` still show old camelCase examples — minor, no functional impact. |
| Well-formedness | 92% | 68/70 tests (2 pre-existing failures). 16/16 e2e. Ruff clean. The new regression test passes and is genuinely wired to catch illegal identifier regressions. Held below full marks: PascalCase sentinel in the new test is fragile (1-of-2 name check, not a coverage-% assertion); `import re` inside function body (style gap, not a lint failure); stale docstrings. |

**Overall: ~78%**

---

## Most significant gaps (after this fix pass)

### Resolved since the prior review

- **Corpus-wide camelCase → PascalCase**: **fully resolved**. 145/145 prefixed SET targets now
  PascalCase. The root cause (`parts[0].lower()`) is fixed. `flg_iscompleted` is gone; `flg_IsCompleted` is correct.
- **`num_sleep-2s` hyphen leak**: **fully resolved**. `num_Sleep2s` is a legal Robin identifier.
- **No regression test for fold/inline_block identifier legality**: **addressed**. The new test
  covers illegal-char leakage across the full corpus including fold/inline_block output.

### Remaining / accepted-deferred

1. **`num_ConsecutiveExceptionCount` vs. reference `num_ConsecutiveExcCount`** — a pre-existing
   semantic spelling mismatch (BP data item uses the full word; reference used an abbreviated form).
   Not fixable by the naming pipeline — would require an explicit BP-name→PAD-name override map
   entry. Pre-existing from every cycle; accepted-deferred.

2. **`%SomeVar%` on value side of SET statements** — expected placeholder from Do-step 3's
   permanently-deferred VBO action output mapping. Every SET target is correctly named; the value
   side is the gap. Accepted-deferred per task framing.

3. **Do-step 2 (Trim/Lower) — 0 real invocations** — implementation exists, untested by corpus.
   Unchanged standing gap from every prior cycle. Accepted-deferred.

4. **`GLOBAL.` qualification — 0 occurrences** — pre-existing, out-of-this-task's scope (Task 5c
   territory). Accepted-deferred.

5. **New regression test's PascalCase sentinel is fragile** — checks for `RetryCount` or
   `ConsecutiveExceptionCount` specifically; would not catch a mass regression if these two names
   happened to survive. A stricter assertion (e.g., `all(re.match(r'^[a-z]+_[A-Z]', t) for t in
   prefixed_targets)`) would be more robust. Minor — the illegal-id assertion is the more important
   half and it is correctly wired.

6. **Stale docstrings** — `_apply_type_prefix` (line 1128) and `_resolve_dotted_reference` (line
   1201, 1211) still show old camelCase examples. No functional impact.

7. **`import re` inside function body** — `src/flowsmith/generator/pad.py` line 1188. Passes ruff,
   but is unconventional; should be at module level.

---

## Verdict

**Pass — with accepted-deferred standing gaps.**

This is genuine, verifiable progress on all three claimed fixes. The prior review's headline defects
(100% camelCase output, `num_sleep-2s` illegal identifier, absent regression test) are all
independently confirmed as fixed. The corpus-wide naming sweep finds 0 illegal identifiers and 145/145
PascalCase across both generated files. All pre-existing test/lint/e2e baselines hold unchanged.

The remaining gaps are all either: (a) pre-existing/carried-from-prior-cycles and explicitly
accepted-deferred (Trim/Lower, GLOBAL. qualification, ConsecutiveExc spelling, `%SomeVar%` value
side); or (b) minor quality-of-implementation issues in the new test and docstrings that do not
affect correctness of the generated output. None constitute a blocking reason to demand another
implementation pass.

**Accepted-deferred standing gaps (not blocking):**
- `num_ConsecutiveExceptionCount` vs. ref `num_ConsecutiveExcCount` (semantic spelling, not naming
  convention)
- `%SomeVar%` value-side placeholders (Do-step 3, permanently deferred)
- Trim/Lower 0 invocations (Do-step 2, no corpus data)
- `GLOBAL.` qualification (Task 5c scope)
- PascalCase regression-test sentinel fragility (minor)
- Stale docstrings (minor)
- `import re` inside function body (style)
