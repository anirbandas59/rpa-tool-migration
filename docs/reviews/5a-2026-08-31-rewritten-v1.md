# Review: Task 5a (rewritten, narrower version) — 2026-08-31

This is the sixth review cycle on this task's underlying work, and the first against the
rewritten (narrower) Task 5a text that split the coarse-`BLOCK`/`GOTO`/`LABEL` exception-dispatch
pattern out into its own Task 5c. Prior cycles: `5a-2026-08-30.md` (58%), `5a-2026-08-31-fixpass.md`
(52%), `5a-2026-08-31-secondfixpass.md` (42%), `5a-2026-08-31-thirdfixpass.md` (49%),
`5a-2026-08-31-fourthfixpass.md` (31%, against the pre-split, 7-Do-step version of this task).

**Overall: 31%**

The coordinator's pre-check is confirmed and, on exhaustive audit, materially *worse* than the
coordinator's spot-check suggested. This is not a minor gap: the task's single most explicit,
most-repeated instruction — "never silently drop [fold/inline_block content]... stub it clearly
with a `# TODO` naming what still needs to land there" — is violated for every one of 8
fold/inline_block-shaped pages, with **zero** exception, and for at least two of them
(`Populate Queue` → `Loader_Main_Body`, `Sample Manager - Explorer` → `Open - Entry By Test
window`) the target container is **already rendered, real content in this task's own output** —
meaning the fold was fully achievable within this task's own scope and simply was not attempted,
not deferred for a legitimate reason. Genuine, verifiable progress exists on three narrower fronts
(Do-step 1 rename wiring, the specific Do-step 5 pre-split routing defect, and process-scoping) —
credited in detail below — but it does not move the needle on the task's central, repeatedly-named
failure mode.

## Method

Regenerated fresh from `samples/blueprism/PID_0171.bprelease` into
`outputs/generated/PID_0171_review5a_v1/` and from `samples/blueprism/PID_0127.bprelease` into
`outputs/generated/PID_0127_review5a_v1/` (both untracked). Read `mapping/page_target_map.yaml`,
`src/flowsmith/generator/pad.py`, `templates/pad/subflow.robin.j2`,
`templates/pad/flow_header.robin.j2`, and `tests/generator/test_pad.py` directly (not the diff
summary). Cross-referenced every mapping-file `fold`/`inline_block`/`split` entry against
architecture doc §B14 and, where a real-reference line-cited target exists, against
`docs/pad-reference/DF_PID_171_US_Loader.robin.txt` /
`DF_PID_171_US_LIMS_Prelude_Main.robin.txt` directly (not just the architecture doc's summary of
them). Wrote small Python scripts to extract `ast.json` page role/reachability, and to extract
every unique `CALL '<x>'` / `FUNCTION '<x>'` pair from both generated `.robin` files and diff the
sets, per file. Ran `uv run pytest tests/generator/test_pad.py -v`, the full suite (`--no-cov`),
`tests/e2e/test_pid171_pipeline.py`, `ruff check` on the two changed Python files, and a direct
`yaml.safe_load` on the mapping file and on both a PID_171 and a PID_0127 regeneration.

## Verification detail, by review-instruction item

### 1–2. Exhaustive fold/inline_block audit — every one dangles with zero trace; at least 2 were achievable within this task's own scope

| Page | Shape | `container` | Container status in this task's own output | Result |
|---|---|---|---|---|
| `Populate Queue` | inline_block | `Loader_Main_Body` | **Real, already rendered** (Loader main body, lines 14–31) | 100% missing — only a misplaced dangling `CALL 'Populate Queue'` in the *Performer* file |
| `DataGateway` | inline_block | `Process Work Queue Items` | Does not exist (Task 5c synthesized construct) | 100% missing, **no `# TODO` stub** despite the task's explicit exemption still requiring one |
| `Save Attachments` | fold | `Process Work Queue Items` | Does not exist (Task 5c) | 100% missing, no stub |
| `Input File Management` | fold | `Process Work Queue Items` | Does not exist (Task 5c) | 100% missing, no stub |
| `Reset Global Data` | fold | `Process Work Queue Items` | Does not exist (Task 5c) | 100% missing, no stub |
| `Sample Manager - Explorer` | fold | `Open - Entry By Test window` | **Real, already rendered** (Performer file, `Result Entry`'s split output) | 100% missing — confirmed by reading the actual `FUNCTION 'Open - Entry By Test window'` body directly; zero trace of its 12 stages, no `# TODO` |
| `Read Excel As Collection` | fold | `CF_PID_171_US_Read Config File` | Cloud Flow, genuinely out of this task's Desktop-Flow-only scope | Not called anywhere in generated Desktop Flows — no dangling reference, acceptable |
| `ConvertConfigFile As Collection - Copy` | fold | `CF_PID_171_US_Read Config File` | Cloud Flow, same as above | **Called** (`CALL 'ConvertConfigFile As Collection - Copy'` at line 110 of the Performer file) with zero resolution and zero comment — the cross-tier nature of this fold target should have prompted at least a `# TODO: now a Cloud Flow config read, see CF_PID_171_US_Read Config File` comment at the call site, not silence |

Every single fold/inline_block page's content is either fully absent or, where the raw BP page is
still called from somewhere, produces a bare dangling `CALL` with **zero** adjacent comment of any
kind (confirmed by direct `grep -B1` around every one of the 9 dangling call sites — no `# TODO`
line precedes or follows any of them). This is the literal "worse than before" regression pattern
named by the fourth fix-pass review, recurring unchanged. Two of the eight (`Populate Queue`,
`Sample Manager - Explorer`) are demonstrably **not** covered by the task's own "container doesn't
exist yet" exemption — their containers are real, rendered content in this same task's own output
— so even the narrowest reading of the task's carve-out does not excuse them.

The implementer's summary characterization ("deferred entirely to Task 5c, matching the task's own
Out of scope section") is false. Task 5a's "Out of scope" line names only "the coarse-`BLOCK`/
`GOTO`/`LABEL` exception-dispatch **pattern**" — nothing about the basic act of folding a page's
stages into an existing container, and nothing that exempts a missing `# TODO` marker even for the
genuinely-not-yet-existing containers.

### 3. Do-step 4 (`split`) — names are right, boundaries are provably wrong, and a new dangling `CALL` was introduced

`Result Entry` (161 raw stages) is rendered as 7 correctly-named `FUNCTION`s
(`Get Results by Analysis and SampleId`, `Open - Entry By Test window`, `Get Components List`,
`Close Results Entry Analysis`, `Close Results Entry`, `Set Results Entry`,
`Enter Results in App`) — a real structural improvement over the prior cycle's single `FUNCTION`.
But `_split_page_into_functions` uses `max(1, len(stages) // num_targets)` — an equal-sized slice
per target (`161 // 7 ≈ 23` stages each) — exactly the "simple stage-count division" the
implementer's own summary admits to. Checked directly against the real reference file
(`docs/pad-reference/DF_PID_171_US_LIMS_Prelude_Main.robin.txt`), the true boundaries are wildly
uneven: `Get Results by Analysis and SampleId` (L447–497, ~50 lines), `Open - Entry By Test window`
(L498–531, ~33 lines), `Get Components List` (L532–581, ~49 lines),
`Close Results Entry Analysis` (L582–605, ~23 lines), `Close Results Entry` (L606–621, ~15 lines),
`Set Results Entry` (L622–767, **~145 lines**), `Enter Results in App` (L768–948, **~180 lines**).
An even 23-stage-per-function split cannot possibly match this distribution — `Set Results Entry`
and `Enter Results in App` alone account for the majority of real content. The task explicitly
anticipated this ("if the mapping schema doesn't yet specify... boundaries, add whatever field is
needed... cite §B14 row 6") — no such field was added to `page_target_map.yaml`, and no attempt was
made to derive real boundaries (e.g. from stage names/regions) before falling back to even
division. Given the actual generated bodies (spot-checked: `Get Components List`'s rendered content
opens with `Summary Report [4]`/`Store Old Data [1]` variable sets, which by content bears no
resemblance to a "get the component list" operation) it is very unlikely any of the 7 generated
bodies' *content* matches its real counterpart, even though the 7 *names* are correct.

**New regression found, not previously reported:** `_resolve_call_target` only reads `target_name`
from the mapping entry — a `split`-shaped entry has no `target_name` field (it has `targets`
instead), so the one real call site to `Result Entry` (from Main Page) falls through to
`target_page.name` = `"Result Entry"`, which matches none of the 7 rendered `FUNCTION` names.
`CALL 'Result Entry'` dangles in the Performer file — split-shape rendering and split-shape
`CALL`-resolution were never connected.

### 4. Do-step 5 (Main Page split-by-role) — the specifically-named defect is genuinely fixed; a related, unnamed defect remains

Traced all 5 pre-split (list-index-before-`Get Next Item`) SubSheet calls directly against
`ast.json`: `Get Mails` (loader role, index 3), `Read Input Data From Excel` (performer, index 5),
`Reset Global Data` (performer, index 6), `Mark Item As Exception` (performer, index 7),
`Mark Item As Completed` (performer, index 8). Confirmed in the regenerated output: the 4
performer-role targets (`Fetch Data from Excel file`, `Reset Global Data`, `Mark Exception`,
`Mark Complete`) now render exclusively in the Performer file's main body and are absent from the
Loader file — **the fourth-consecutive-cycle-named defect is fixed for exactly the case it names.**
`test_main_page_split_routes_calls_by_target_role` asserts this correctly and passes.

**However**, a related, broader defect was found that this narrow fix does not address: the raw BP
stage-list order for Main Page does **not** correlate with execution order at all (confirmed
directly — the SubSheet call to `Populate Queue`, index 18, and to `ConvertConfigFile As
Collection - Copy`, index 62, both sit *after* `Get Next Item`'s index (14) in the raw stage list,
even though both are logically pre-loop, Loader-role content per §B11's own table). Because
`_split_main_page_if_needed` only role-filters the *pre-split* bucket (per Do-step 5's literal
text) and appends the entire *post-split* bucket unconditionally, these two Loader-role calls leak
into the Performer file's main body verbatim (confirmed: `CALL 'Populate Queue'` at Performer line
28, `CALL 'ConvertConfigFile As Collection - Copy'` at line 110). Separately, `Send mail - No New
Mail` (§B14 row 20, confirmed Loader-role) is tagged `role: performer` in `ast.json` — an
upstream Task 4b role-tagging defect, not this task's own code — which causes its `FUNCTION 'Send
Business Exception Mail' GLOBAL` to render in the *Performer* file instead of the Loader file where
its own `Fetch Emails from Mailbox`/`Load Config Data` siblings live. Do-step 5's own literal ask
is met; the Main Page split as a whole is not functionally clean.

### 5. Do-step 1 (rename wiring) — genuinely works, both directions, for every page checked

Enumerated every `shape: function`/`inline_block` mapping entry with a `target_name` and confirmed
each renders under its mapped name, consistently, in both the `FUNCTION` declaration and every
`CALL` site: `Get Mails`→`Fetch Emails from Mailbox` (GLOBAL), `Read Input Data From Excel`→`Fetch
Data from Excel file`, `Launch_Sample Manager`→`Launch Application`, `Summary_Report`→`Create
Summary Report`, `Mark Item As Completed`→`Mark Complete`, `Mark Item As Exception`→`Mark
Exception`, `Send mail`→`Send Email`, `Send mail - No New Mail`→`Send Business Exception Mail`
(GLOBAL), and both `Mark as read mail`/`Mark as read and move to exception folder`→`Move Emails`.
This is real, verified progress — `_resolve_call_target` and `_render_page_as_function` both
correctly consult the mapping, and the `templates/pad/subflow.robin.j2` `GLOBAL` qualifier is now
conditional on the mapping's `global` field rather than unconditional (the fourth-fix-pass's named
defect for this specific point is fixed).

**Two citation-accuracy defects found independently in the mapping's `global` values**, not
previously flagged: `Launch_Sample Manager`'s mapping entry says `global: false`, but the real
reference file marks `FUNCTION 'Launch Application' GLOBAL` (L402,
`DF_PID_171_US_LIMS_Prelude_Main.robin.txt`) — should be `true`. `Send mail - No New Mail`'s entry
says `global: true`, but the real Loader reference marks `FUNCTION 'Send Business Exception Mail'`
with **no** `GLOBAL` keyword (L173, `DF_PID_171_US_Loader.robin.txt`) — should be `false`. The
`GLOBAL`-application *mechanism* is correct; two of its input values are wrong.

**New well-formedness defect found, not previously reported:** because `Mark as read mail` and
`Mark as read and move to exception folder` both map to the *same* `target_name` (`Move Emails`)
and each renders as its own independent `FUNCTION`, the Performer file contains **two** separate
`FUNCTION 'Move Emails'` declarations with the same name and different bodies (confirmed:
`grep -c "^FUNCTION 'Move Emails'"` → 2). The mapping file's own `notes` field on the second entry
correctly describes the real target as "Shares Move Emails FUNCTION with row 10 (parameterized by
`In_txt_DestinationFolder`)" — i.e. one shared, parameterized function — but nothing in the
generator implements parameter-based merging, so it silently produces a same-name duplicate
declaration instead, which is a real PAD compile risk (duplicate function names), not merely a
missed optimization.

### 6. Do-step 6 (test correction) — the allowlist variables are gone, but the replacement test also does not assert the thing the task requires

`cross_role_loader_calls`/`cross_role_performer_calls`/`folded_pages` allowlist variables are
confirmed absent from `test_call_function_correspondence_in_generated_files` (grep for
`allowlist` in the test file: zero hits). But the rewritten test's own docstring concedes: "Full
CALL/FUNCTION correspondence currently has known limitations for pages marked as 'fold' or
'inline_block'... This test focuses on ensuring target_name resolution works correctly" — and its
actual assertion body only checks, conditionally, that specific known-good mapped calls appear
*when their `FUNCTION` already exists* (`if call_name in functions: assert call_name in calls`). It
never asserts "every unique `CALL` has a matching `FUNCTION`," and it structurally cannot fail on
any of the 12 real dangling references found above, because none of their target names are in its
`expected_resolved_calls` sets. This is a materially different test than the one the task's own
"Done when" text requires ("a test asserts every unique `CALL '<x>'`... has a matching `FUNCTION
'<x>'`... with zero allowlist exceptions") — the literal named `allowlist` variables are gone, but
the effect (silently not catching the exact defects this task exists to fix) is unchanged.
`test_five_critical_calls_appear_in_loader_for_pid171` was renamed to
`test_main_page_split_routes_calls_by_target_role` and its assertions were genuinely corrected (see
§4 above) — that part of Do-step 6 is real.

### 7. Full CALL/FUNCTION dangling-reference audit (both files, exhaustive)

| File | Unique `CALL` targets | Unique `FUNCTION` decls | Dangling | Any with a visible `# TODO`? |
|---|---|---|---|---|
| Loader | 2 | 1 | 1 (`Get Error`, ×5 occurrences) | No |
| Performer | 19 | 15 | 11 (`Get Error` ×77, `Completed No Outcome` ×2, `ConvertConfigFile As Collection - Copy` ×1, `DataGateway` ×1, `Input File Management` ×1, `Populate Queue` ×1, `Reset Global Data` ×1, `Result Entry` ×1, `Sample Manager - Explorer` ×3, `Save Attachments` ×1, `<page/subprocess>` ×1 comment placeholder) | No — confirmed via `grep -B1` around every occurrence |

**Total: 12 unique dangling `CALL` targets, 0 with any visible marker.** The largest single bucket
by raw occurrence count, `Get Error` (82 occurrences across both files), is not a page-shape
mapping issue at all — `Get Error` is a boilerplate helper `FUNCTION` (confirmed present, `GLOBAL`,
in *both* real reference files) that every `BLOCK`'s `ON BLOCK ERROR` handler and every `RECOVER`
stage calls, and it is emitted by pre-existing `_render_block_open`/`_render_structural_stage` logic
this task did not touch. It is outside Task 5a's own Do-steps (none of them mention it), but it is
squarely inside the task's own literal "Done when" bar (a zero-allowlist-exception `CALL`/
`FUNCTION` correspondence test) — no such test could pass today without also addressing this. This
is a legitimate, actionable finding for whoever owns that bar next (likely Task 5c, since `Get
Error` is part of the same error-handling boilerplate `Get Error`/`ON BLOCK ERROR` machinery), not
something to lay at this implementer's feet, but it does mean the task's stated Done-when criterion
was unattainable without touching files outside this task's declared scope.

### 8. Process-scoping fix — genuinely correct, independently re-verified

Regenerated fresh from `PID_0127.bprelease` (process name `PID_0127_Process_US_BulkUnlock`,
confirmed via `ast.json`) and confirmed directly: `Reset Global Data`, `DataGateway`, `Mark Item As
Completed`, `Mark Item As Exception`, `Completed No Outcome` all render as full `FUNCTION`
declarations with real content (not skipped, not folded) — because `_get_page_shape` only consults
`self.page_target_map[process_name]` and `PID_0127_Process_US_BulkUnlock` has no key in
`page_target_map.yaml`, so every page falls to the `{"shape": "function"}` default. This is a real,
verified fix — `test_real_sample_stub_count`'s updated expected count (18, up from the prior
fold-affected baseline) is consistent with this and passes.

### 9. Test suite

`uv run pytest tests/generator/test_pad.py -v` → **59 passed** (matches implementer's claim
exactly; coverage-gate failure at 69% is an artifact of running one file in isolation against the
project's whole-suite 85% gate, not a real regression). `uv run pytest tests/ -q --no-cov` → **762
passed, 10 failed** — identical failure set to every prior review cycle
(`tests/engine/test_flag_index.py` ×8, `tests/mapper/test_vbo_router.py` ×2), confirmed
pre-existing and unrelated. `tests/e2e/test_pid171_pipeline.py` → **16 passed**, unaffected (checks
outer package/XML/JSON well-formedness only, not `CALL`/`FUNCTION` correspondence).

### 10. Ruff

`uv run ruff check src/flowsmith/generator/pad.py tests/generator/test_pad.py` → clean. (`ruff
check` on the `.yaml` mapping file is a tool-misuse false alarm — ruff only lints Python; a direct
`yaml.safe_load` confirms the file parses correctly.)

## Score breakdown

| Dimension | Score | Evidence |
|---|---|---|
| Structural | 30% | The 2-file Loader/Performer skeleton and Do-step 5's specifically-named routing defect are genuinely fixed. But the task's central structural ask — 4-way shape differentiation actually producing the right *shape* of output — still only fully works for 1 of 4 (`function`, including rename+conditional-`GLOBAL`); `split` produces the right names with provably wrong boundaries and a newly-broken `CALL` resolution; `inline_block`/`fold` remain complete no-ops with silent drops, including 2 cases where the target container already exists in this task's own output and folding was fully achievable. |
| FUNCTION functional fidelity | 20% | Per-stage rendering inside existing `FUNCTION`s is unregressed. But cross-page assembly is severely compromised: 8 fold/inline_block pages' business logic (Populate Queue's "Add to Queue Block" loop, DataGateway, Save Attachments, Reset Global Data, Input File Management, Sample Manager - Explorer — several hundred BP stages combined) is entirely unrepresented anywhere in the output; Main Page's Performer body is polluted with misplaced Loader-role content (`Populate Queue`, `ConvertConfigFile As Collection - Copy` calls) that don't belong in the per-item loop; `Result Entry`'s 7-way split almost certainly misassigns real content to the wrong named function given the confirmed-uneven real boundaries. |
| VBO/action fidelity | 55% | The `CALL '<name>'` / `FUNCTION '<name>' [GLOBAL]' ... END FUNCTION` skeleton syntax matches architecture doc §B12's literal template correctly wherever it renders, and `GLOBAL` is now correctly conditional on mapping data (fixing the prior cycle's unconditional-`GLOBAL` defect) rather than a blanket default. Two of the mapping's own `global` values are miscited against the real reference (`Launch Application` should be `true`, `Send Business Exception Mail` should be `false`), and the duplicate `FUNCTION 'Move Emails'` declaration is a real syntax-uniqueness risk this dimension is the right place to flag. |
| Naming convention | 65% | All 9–10 real BP-page→renamed-`FUNCTION` pairs from §B14 render correctly, consistently, on both the declaration and every call site — a genuine, verified fix of the fourth-fix-pass's named 15% defect. Docked for the 2 `global`-value citation errors above and for `Move Emails`'s unimplemented parameter-based merge producing a duplicate name instead of one shared, parameterized `FUNCTION` as the mapping's own `notes` field correctly describes. |
| Error-handling/stop/consecutive-exception | N/A for this task's scope | The coarse-`BLOCK`/`GOTO`/`LABEL` dispatch pattern is explicitly out of scope (Task 5c). Noted in passing: the `Get Error` boilerplate helper (82 dangling occurrences) and the silent `Completed No Outcome` STOP-page dangling `CALL` sit adjacent to this dimension and will need addressing before Task 5c's own Done-when bar is reachable, but neither is this task's Do-step to fix. |
| Well-formedness | 15% | This is the dimension the task exists to fix, and its own literal "Done when" bar — a test asserting zero-allowlist-exception `CALL`/`FUNCTION` correspondence — is not met: no such test exists (the rewritten regression test structurally cannot catch any of the 12 real dangling references found by direct extraction), and the underlying dangling-reference count is unchanged in kind from the fourth-fix-pass finding (silent, zero-trace content loss) despite the task's explicit instruction that this must never recur. YAML parses; outer package/XML/JSON well-formedness (e2e suite) is unaffected since dangling references live inside embedded Robin script text, not the outer package structure. |

## Most significant gaps

- **Every fold/inline_block-shaped page (8 of 8) still has zero rendered trace, and zero `# TODO`
  marker, in the generated output** — the exact "never silently drop" violation this task exists to
  prevent, recurring unchanged from the fourth fix-pass finding.
- **At least 2 of those 8 (`Populate Queue`→`Loader_Main_Body`, `Sample Manager - Explorer`→`Open -
  Entry By Test window`) point at containers that already exist as real, rendered content in this
  task's own output** — meaning the fold was fully achievable within this task's declared scope and
  simply was not attempted, not legitimately deferred pending Task 5c.
- **The regression test rewritten to satisfy Do-step 6 does not assert the thing the task's own
  "Done when" text requires** — no `allowlist` variable exists, but the test's conditional structure
  means it cannot fail on any of the 12 real dangling references found by direct extraction.
- **`Result Entry`'s 7-way split uses even stage-count division, provably wrong against the real
  reference file's line ranges** (boundaries range from ~15 to ~180 lines per function, not ~23
  each) — and the split's own `CALL`-resolution was never wired, so the one real call site to
  `Result Entry` dangles despite all 7 target `FUNCTION`s existing.
- **New, previously-unreported defects found in this pass:** a duplicate `FUNCTION 'Move Emails'`
  declaration (same name, two different bodies, in the same file); 2 miscited `global` values in the
  mapping file (`Launch Application` should be `true`, `Send Business Exception Mail` should be
  `false`); Loader-role content (`Populate Queue`, `ConvertConfigFile As Collection - Copy`) leaking
  into the Performer file's main body because only the pre-split bucket is role-filtered, not the
  post-split bucket.
- **Genuine, verified progress, credited above:** Do-step 1's rename wiring (9–10 pages, both
  `FUNCTION` and `CALL` sites, consistently correct); Do-step 5's specifically-named pre-split
  routing defect (fixed, with a real passing test); process-scoping (fixed, independently
  re-verified against a fresh `PID_0127.bprelease` regeneration); Do-step 7 (unreachable pages
  cleanly skipped, zero trace); Do-step 8 (header logic unaffected, fires once per file).
- **A large (82-occurrence) dangling-`CALL 'Get Error'` bucket exists that is not this task's own
  Do-step to fix** (it's pre-existing boilerplate-helper machinery, not a page-shape mapping
  concern) but makes the task's own literal "zero-exception" Done-when bar unreachable without also
  touching that machinery — worth surfacing to whoever scopes the next task in this area.

## Verdict

needs another implementation pass. Real, narrow progress exists (rename wiring, the specific
Do-step 5 defect, process-scoping) and should be kept. But the task's central ask — implement
`fold`/`inline_block` so content is never silently dropped — remains almost entirely unimplemented,
including for cases demonstrably achievable within this task's own scope, and the regression test
meant to guard against exactly this was rewritten in a way that cannot catch it. A seventh pass
should, in order of impact: (1) implement `inline_block`/`fold` for the two cases whose containers
already exist in this task's own output (`Populate Queue`→`Loader_Main_Body` BLOCK,
`Sample Manager - Explorer`→ fold into `Open - Entry By Test window`'s body) before touching
anything Task-5c-dependent; (2) for the remaining fold targets pointing at `Process Work Queue
Items` (not yet synthesized), add the literal `# TODO` stub the task's own text requires at minimum,
naming the missing container; (3) wire `_resolve_call_target` to handle `split`-shaped targets (even
routing to the first/most-plausible sub-function beats a dangling reference); (4) add real
stage-ID-range or region-marker boundaries to `Result Entry`'s mapping entry per the reference
file's actual (uneven) line ranges rather than even division; (5) fix the two miscited `global`
values and implement `Move Emails`'s parameter-based merge instead of a duplicate-named `FUNCTION`;
(6) write the actual "every unique `CALL` has a matching `FUNCTION`, zero exceptions" test the
task's own text specifies, and treat any resulting failures (including the pre-existing `Get Error`
bucket) as real findings to report rather than reasons to weaken the assertion further.
