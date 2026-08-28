# PAD Generation Task Prompts — PID_171 Coding Phase

Each section below is one self-contained work order for the `pad-implementer` subagent, invoked via
`/pad-task <task-id>` (e.g. `/pad-task 3a`). Read only the task you were given plus its cited
"Required reading" — not this whole file, and not the full session history that produced it.

**Ground rules for every task** (also stated in `.claude/rules/pad-pipeline-workflow.md`, repeated
here so a task read in isolation is still complete):
- Stay inside "Files in scope." If you find you need to touch something else, stop and report that
  in your summary instead of doing it.
- Every change should be traceable to a cited section of `docs/bp-to-pad-architecture-PID171.md`,
  `docs/bp-to-pad-implementation-strategy-PID171.md`, or `docs/pad-reference/vbo-action-mapping.md`
  — no invented syntax, no plausible-looking guesses.
- Run the task's "Done when" command before reporting success.
- Never silently drop a BP stage/pattern you can't translate — leave a `# TODO` comment citing what
  BP construct it was and why it's out of scope (usually: needs a UI selector, per architecture doc
  §B9).
- Follow `CLAUDE.md`'s existing project rules (typed exceptions, no bare `None` returns, docstrings,
  type hints, YAML-not-hardcoded mappings) on top of whatever this task adds.
- End your summary with: files changed, test result (pass/fail + count), any deviation from this
  task's spec and why, and open questions for the reviewer.

Dependency order matches `docs/bp-to-pad-implementation-strategy-PID171.md` §3.2. Do not start a
task whose "Depends on" isn't already done.

---

## Task 1 — `mapper/config.py`: add per-method action field to `VBOEntry`

**Depends on:** none
**Files in scope:** `src/flowsmith/mapper/config.py`, `src/flowsmith/mapper/vbo_router.py`,
`tests/mapper/test_config.py`, `tests/mapper/test_vbo_router.py`
**Required reading:** `docs/bp-to-pad-implementation-strategy-PID171.md` §2.1 and the
`mapper/config.py` row of §1.1.

**Do:**
1. Open `src/flowsmith/mapper/config.py` and find the `VBOEntry` model. It currently has
   `method_patterns: list[str]` (BP-side method name substrings) and a single `pa_module: str` per
   VBO — there is no way to record "method X on this VBO maps to concrete PAD call Y, method Z
   maps to a different concrete PAD call W."
2. Add a new optional field, e.g. `method_actions: dict[str, str] = Field(default_factory=dict)`,
   mapping an **exact** BP method name (as it appears in `<resource action="...">`) to a literal
   PAD action-call template string. Keep `method_patterns` for fuzzy fallback matching — don't
   remove it.
3. Update YAML-loading validation so `method_actions` is optional (defaults to `{}`) and validated
   as `dict[str, str]`.
4. In `mapper/vbo_router.py`, update the routing logic: when resolving a stage's BP method name
   against a `VBOEntry`, first check `method_actions` for an **exact** key match — if found, that
   literal template is the resolved action (high confidence, e.g. `confidence_base` from the entry
   unmodified). Only fall back to the existing `method_patterns` fuzzy match (lower confidence) if
   no exact match exists. Fall back to the existing unknown-stub behavior if neither matches.
5. Update `test_config.py` (schema accepts `method_actions`, defaults to `{}` when absent) and
   `test_vbo_router.py` (an exact `method_actions` match takes precedence over and yields higher
   confidence than a `method_patterns` fuzzy match on the same VBO; a `VBOEntry` with no
   `method_actions` at all behaves exactly as before — no regression).

**Done when:** `uv run pytest tests/mapper/ -v` passes, including a new test asserting the
precedence behavior in step 4.

**Out of scope:** populating `vbo_catalogue.yaml`'s `method_actions` data (Tasks 2a/2b).

---

## Task 2a — `vbo_catalogue.yaml`: runtime/module corrections

**Depends on:** none (pure data edit, independent of Task 1's schema)
**Files in scope:** `mapping/vbo_catalogue.yaml`
**Required reading:** `docs/bp-to-pad-implementation-strategy-PID171.md` §2.2 (first two bullets),
`docs/pad-reference/vbo-action-mapping.md`.

**Do:**
1. `Blueprism.Automate.clsWorkQueuesActions`: change `runtime: CLOUD` → `runtime: DESKTOP`. Real
   `WorkQueues.*` calls (`ProcessWorkQueueItem`, `GetWorkQueueItems`, `UpdateWorkQueueItem`,
   `UpdateProcessingNotes`, `EnqueueWorkQueueItem`) are Desktop Flow Robin actions, confirmed in
   `docs/pad-reference/DF_PID_171_US_LIMS_Prelude_Main.robin.txt`.
2. `Utility - JSON`: change `runtime: CLOUD` → `runtime: DESKTOP`. Real JSON conversion
   (`Variables.ConvertJsonToCustomObject`/`ConvertCustomObjectToJson`) happens inside the desktop
   flows.
3. `Utility_DataGateways-CustomFramework`: change `pa_module: "Database"` → `pa_module:
   "External"` and rewrite `notes` to describe the real pattern: `External.RunFlow` calling a
   sibling desktop flow (architecture doc §B13's DataGateways row), not a Database module call.
   Keep `runtime: DESKTOP`.
4. `Utility - Environment`: change `pa_module: "shared_sharepointonline"` → `pa_module: "System"`.
   Real usage is `System.GetEnvironmentVariable.GetEnvironmentVariable`, not SharePoint at all.
5. `Blueprism.Automate.clsCredentialsActions`: `pa_module: "shared_keyvault"` is already correct —
   leave it, but rewrite `notes` to flag that the real call happens *inside* a Desktop Flow via
   `External.InvokeCloudConnector` (a cloud connector called from a desktop flow) — the current
   binary `CLOUD`/`DESKTOP` `runtime` field can't express this combination cleanly. Do not invent a
   new schema field to fix this now (that's a future schema decision, out of scope for a data-only
   task) — just document the limitation in `notes` so it isn't lost.
6. Update the file's header comment to note it has been reviewed against
   `docs/pad-reference/vbo-action-mapping.md` as of this task.

**Done when:** the file still parses as valid YAML (`uv run python -c "import yaml;
yaml.safe_load(open('mapping/vbo_catalogue.yaml'))"` succeeds) and `uv run pytest
tests/mapper/test_config.py -v` passes unmodified (this task changes data only, not schema).

**Out of scope:** adding new VBO entries or fixing method patterns (Task 2b), `stage_rules.yaml`
(Task 2c).

---

## Task 2b — `vbo_catalogue.yaml`: add missing VBOs + method-pattern corrections

**Depends on:** Task 1 (needs the `method_actions` field to exist)
**Files in scope:** `mapping/vbo_catalogue.yaml`
**Required reading:** `docs/pad-reference/vbo-action-mapping.md` (the primary source — every
template you add must be copied from here, not invented), `docs/bp-to-pad-architecture-PID171.md`
§B9/§B_VBO (UI-selector out-of-scope rule).

**Do:**
1. Add `PID_0003_Object_US_SampleManager` and `PID_0005_Object_US_SampleResultsEntry` entries:
   `pa_module: "UIAutomation"`, `runtime: DESKTOP`, low `confidence_base` (e.g. `0.15`), `notes`
   explaining every method needs the `# TODO: UI selector required` stub per architecture doc §B9
   — leave `method_actions` empty (no real action template exists for these).
2. Add `MS Outlook Email VBO Extended` and `MS Outlook Extended VBO` entries with `method_actions`
   populated from `vbo-action-mapping.md`'s Outlook table (`Get Received Items` →
   `GetEmailsV3` call template, `Mark Email As Read` → `MarkAsRead_V3`, `Move Email` → `MoveV2` —
   copy the literal templates verbatim). `pa_module: "External"`, `runtime: DESKTOP` (same
   cloud-connector-from-desktop nuance as `clsCredentialsActions` — note it in `notes`).
3. Add `Utility_Object_Generic_ScreenShot` (`Take Screenshot` →
   `Workstation.TakeScreenshot.TakeScreenshotAndSaveToFile` template), `pa_module: "Workstation"`,
   `runtime: DESKTOP`. Do **not** assume the existing `"DWF Utility - Screenshot"` entry already
   covers this — it's a different name; add a new entry and leave the old one alone (it may serve
   other BP samples).
4. Add `Utility - Image Search`: if `vbo-action-mapping.md` has no confirmed PAD call for it, add
   the entry with low `confidence_base` and `notes: "no confirmed PAD equivalent found for PID_171
   usage — STOP, do not invent"` rather than skipping it.
5. Add `Utility_Sharepoint_API_Config` under its **exact** real name (distinct from the existing
   `Utility_PnP_Auth`/`RPA Sharepoint Conifgfile Download` entries — do not assume either covers
   it). If `vbo-action-mapping.md` doesn't cover it directly, mark low confidence and note that this
   VBO's role is superseded by the `CF_PID_171_US_Read Config File` cloud flow per architecture doc
   §A2 and §B14 rows 22/24.
6. Fix `MS Excel VBO`'s `method_patterns` to the real PID_171 method names from
   `vbo-action-mapping.md`'s Excel table (`Create Instance`, `Open Workbook`, `Get Worksheet As
   Collection`, `Close Workbook`, `Close Instance`, `Write to cell`, `Save As` — the current file
   lists different, non-matching names) and populate `method_actions` with the literal templates
   from that table.
7. For every entry you touch in this task, populate `method_actions` with literal PAD call
   templates copied verbatim from `docs/pad-reference/vbo-action-mapping.md` — never invent one.

**Done when:** the file still parses as valid YAML; `uv run pytest tests/mapper/ -v` passes; in
your summary, list every `method_actions` value you added alongside the exact
`vbo-action-mapping.md` row it was copied from.

**Out of scope:** `stage_rules.yaml` (Task 2c).

---

## Task 2c — `stage_rules.yaml`: 18-type fix, Process/Alert/Skill rows, fill `pa_target_action`

**Depends on:** none
**Files in scope:** `mapping/stage_rules.yaml`
**Required reading:** `docs/bp-to-pad-architecture-PID171.md` §B12 (stage-type → PAD construct
templates), `CLAUDE.md`'s "Stage type enum reference" section, `docs/bp-to-pad-implementation-strategy-PID171.md`
§2.3.

**Do:**
1. Update the header comment from "14 canonical types" to **18**, listing them per `CLAUDE.md`'s
   reference (`START, END, ACTION, DECISION, CHOICE, CALCULATION, CODE, WAIT, NAVIGATE, READ,
   WRITE, LOOP, EXCEPTION, RECOVER, RESUME, BLOCK, COLLECTION, DATA`).
2. Add 3 missing normalisation rows, none present today:
   - `Process` → canonical_type `ACTION`, notes: normally a `CALL '<page/subprocess>'` like
     `SubSheet`, **except** the one process-level call that maps to a Cloud Flow child-workflow
     (architecture doc §B13's "Process-call special case" / strategy doc §2.3's bullet — cite
     both) — flag `confidence_base: 0.5` and a note that routing (desktop `CALL` vs. cloud
     `Workflow` action) needs a human/reviewer decision, don't hardcode one.
   - `Alert` → canonical_type `ACTION`, `is_alert` flag, no confirmed PAD equivalent researched
     yet — `confidence_base: 0.2`, `notes: "STOP - not yet mapped, review before use"`.
   - `Skill` → canonical_type `ACTION`, `is_skill` flag, confidence forced to MANUAL band per
     `CLAUDE.md` — `confidence_base: 0.0`.
3. For every existing canonical-type row (`Start`, `End`, `Action`, `Decision`, `Calculation`,
   `Code`, `WaitStart`/`WaitEnd`, `Navigate`, `Read`, `Write`, `LoopStart`/`LoopEnd`, `Exception`,
   `Recover`, `Resume`, `MultipleCalculation`, `Block`, `Collection`, `Data`, `Note`,
   `SubSheetInfo`, `ProcessInfo`, `SubSheet`, `Anchor`), fill in `pa_target_action` with the
   literal syntax template from architecture doc §B12's table:
   - `Calculation`/`MultipleCalculation` → `SET <var> TO <expr>`
   - `Decision` → `IF <expr> THEN <true-branch> ELSE <false-branch> END`
   - `LoopStart`/`LoopEnd` → `LOOP FOREACH <item> IN <collection> ... END` (collection loop) or
     `LOOP <var> FROM <start> TO <end> STEP <n> ... END` (counted loop) — note both forms exist,
     dispatch is by the BP loop's own child elements, not a fixed choice.
   - `Exception` → `FlowControl.ThrowCustomError CustomErrorCode: $'''<exact BP type string>'''
     CustomErrorMessage: <expr>`
   - `Block` → the `BLOCK '<name>' ON BLOCK ERROR ... END <body> END` template (§A5/§B12)
   - `Recover`/`Resume` → **leave `pa_target_action` empty**, add `notes: "consumed by the
     enclosing BLOCK's handler, no standalone PAD emission — see §B12"` (per architecture doc, do
     not give these a template of their own).
   - `Note`/`SubSheetInfo`/`ProcessInfo` → `# <text>` (optional comment, only when the stage
     carries text — see §B12's refined rule).
   - `Anchor` → stays empty/skip, no change needed (pure routing artifact, never emitted).
   - `WaitStart`/`WaitEnd` → `WAIT <seconds expr>` for a static/fixed-duration wait; note in
     `notes` that a UI-element-condition wait is a different (dynamic) case handled at the VBO
     level (§B_VBO), not by this row.
   - `Navigate`/`Read`/`Write` → `pa_target_action` stays a placeholder
     (`# TODO: UI selector required`), these are UI-automation stage types out of scope per §B9 —
     don't invent a `UIAutomation.*` call here.
4. Do **not** add a `CHOICE` row — confirm it stays absent, matching `CLAUDE.md`'s explicit
   caveat ("do not implement until a real sample is obtained").

**Done when:** the file parses as valid YAML; `uv run pytest tests/mapper/test_config.py -v`
passes; every canonical-type row that architecture doc §B12 specifies a literal template for now
has a non-empty `pa_target_action` matching that template (spot-checkable by grep).

**Out of scope:** `vbo_catalogue.yaml` (Tasks 2a/2b).

---

## Task 3a — `parser/process.py`: multi-artefact release parsing

**Depends on:** none
**Files in scope:** `src/flowsmith/parser/process.py`, `tests/parser/test_process.py`,
`tests/parser/test_integration.py`
**Required reading:** `docs/bp-to-pad-architecture-PID171.md` §A1's ".bprelease container
structure" cross-reference (or `CLAUDE.md`'s own copy of the same section — they agree), the
`parser/process.py` row of `docs/bp-to-pad-implementation-strategy-PID171.md` §1.1.

**Do:**
1. The current parser only ever resolves the **first** `<process>` inside
   `<bpr:release><bpr:contents>` — confirmed the second `<process>` (`RPA_Sharepoint_API_ConfigFile_Download`
   in PID_171's release) and all `<object>` (VBO) artefacts are never parsed. Extend the entry
   point so it iterates every `<process>` and `<object>` child of `<bpr:contents>`, calling the
   existing per-artefact `parse_element(root_el, release_id)` (already the correct primitive per
   `CLAUDE.md` — reuse it, don't reimplement) for each one.
2. Return a structure that distinguishes the artefacts — e.g. `{"processes": [...], "objects":
   [...], ...}` rather than a single flattened `BPProcess`-shaped dict — so downstream code
   (Task 4a/4b) can tell the main process apart from the sibling process and from VBOs. Check
   `scripts/bp_release_parser.py` (already in this repo, read-only reference — do not import it
   into `src/`, it's a standalone diagnostic tool) for a precedent shape if useful, but the
   production return type should fit `src/flowsmith/ast/builder.py`'s existing consumption
   pattern — check how `build_ast()` currently calls this parser before deciding the exact shape.
3. Validate `process_count + object_count + env_var_count + group_count == declared_count`
   (from `<bpr:contents count="N">`) — raise `ConfigError` (see `exceptions.py`) on mismatch,
   per `CLAUDE.md`'s validation rule.

**Done when:** `uv run pytest tests/parser/ -v` passes, including a new test asserting that
parsing `samples/blueprism/PID_0171.bprelease` returns **2** processes (not 1) and the VBO/object
artefacts are present in the result (even if not yet consumed downstream — that's later tasks).

**Out of scope:** environment-variable extraction (Task 3b); anything in `ast/builder.py` that
consumes this new multi-artefact shape (Task 4a) — this task only needs to return the data, not
wire it through the whole pipeline yet. If `ast/builder.py` breaks because it expects the old
single-artefact shape, that's expected and will be fixed in Task 4a — note it in your summary
rather than trying to fix `ast/builder.py` yourself.

---

## Task 3b — `parser/process.py`: environment-variable extraction

**Depends on:** Task 3a (shares the release-level parsing entry point)
**Files in scope:** `src/flowsmith/parser/process.py`, `tests/parser/test_process.py`
**Required reading:** `CLAUDE.md`'s ".bprelease container structure" section (the
`<environment-variable>` element), `docs/bp-to-pad-architecture-PID171.md` §A2 point 5 (the 11
real PID_171 environment variables, for a concrete example to test against).

**Do:**
1. Extract every `<environment-variable>` element from `<bpr:contents>` (namespace
   `http://www.blueprism.co.uk/product/environment-variable`) — `id`, `name`, `type`, `value`,
   and `description` (child element, may be missing the namespace prefix on some BP export
   versions — check for both `env:description` and bare `description`, per
   `scripts/bp_release_parser.py`'s existing handling of this quirk if you want a working
   reference, read-only).
2. Add these to the same return structure Task 3a introduced (e.g. an
   `environment_variables: list[dict]` key alongside `processes`/`objects`).
3. Ensure `ast/models.py`'s existing `BPEnvironmentVariable`/`BPProcess.environment_variables`
   field (already defined — its own docstring says "not yet parser-populated," confirmed in the
   codebase audit) is the target shape you're feeding, even if wiring it through `ast/builder.py`
   is a separate task — check the field definition so your parser output's keys match what that
   model expects.

**Done when:** `uv run pytest tests/parser/ -v` passes, including a new test asserting that
parsing `samples/blueprism/PID_0171.bprelease` returns exactly **11** environment variables with
names matching the ones listed in architecture doc §A2 point 5 (e.g.
`PID_171_US_EV_LIMS_Prelude_ConfigFile`, `RPA_Sharepoint_URL`).

**Out of scope:** wiring the extracted data through `ast/builder.py` into `BPProcess` (that's
implied by Task 4a's scope, since it already needs to consume Task 3a's multi-artefact shape —
note any coupling you find in your summary).

---

## Task 4a — `ast/builder.py`: call-graph/reachability model

**Depends on:** Task 3a, Task 3b
**Files in scope:** `src/flowsmith/ast/builder.py`, `src/flowsmith/ast/models.py`,
`tests/ast/test_builder.py`, `tests/ast/test_models.py`
**Required reading:** `docs/bp-to-pad-architecture-PID171.md` §B11 (the confirmed orphan-page
findings — `Mark leftout Items as Exception` and `Send Info to Data Gateways`, both have zero
callers, confirmed by a `<processid>` search against the BP XML) and §B16 (known-gaps list).

**Do:**
1. `ast/builder.py` currently builds one `BPProcess` per artefact with no cross-page edge/call
   graph at all. Add a reachability pass: starting from each page's `Start` stage, follow
   `onsuccess`/`ontrue`/`onfalse` edges (already resolved by the existing anchor-chain logic — see
   `_build_anchor_map`/`_resolve_edge` if present, reuse rather than reimplement) plus `SubSheet`/
   `Process`-type `ACTION` stages' `processid` cross-references to other pages, to determine which
   pages are actually reachable from the process's `Main Page`/entry point.
2. Also reconstruct the **implicit** Block→Recover edge (BP never encodes it in the XML — it's
   the nearest enclosing `Block` in the same page for each `Recover` stage) as part of this same
   graph-building pass, since it affects reachability too (a `Recover`'s continuation matters for
   completeness, not just for `BLOCK`/`ON BLOCK ERROR` rendering later).
3. Tag each `BPPage` with a `reachable: bool` (or equivalent) field on the model in
   `ast/models.py`, computed by this pass — do not delete unreachable pages from the AST outright
   (a future consumer, or a human, may still want to see them); just mark them.
4. Add a test using `samples/blueprism/PID_0171.bprelease` asserting `Mark leftout Items as
   Exception` and `Send Info to Data Gateways` are both marked unreachable, and that ordinary
   called pages (e.g. `Get Mails`, `Populate Queue`) are marked reachable.

**Done when:** `uv run pytest tests/ast/ -v` passes, including the new reachability test from
step 4.

**Out of scope:** actually pruning unreachable pages from generator output (a later task, if the
strategy doc's COV-4 gap is addressed downstream — not this task); Loader/Performer role tagging
(Task 4b, though it will likely reuse this same graph).

---

## Task 4b — `ast/builder.py`: Loader/Performer role tagging

**Depends on:** Task 4a
**Files in scope:** `src/flowsmith/ast/builder.py`, `src/flowsmith/ast/models.py`,
`tests/ast/test_builder.py`
**Required reading:** `docs/bp-to-pad-architecture-PID171.md` §B11 (the hard boundary at BP
stage `85fbb578`, `Get Next Item` on Main Page) and §A3 (what a Loader vs. Performer body actually
looks like in the real PAD output, for context on what this tagging is ultimately feeding).

**Do:**
1. Using the reachability/call graph from Task 4a, walk Main Page's stages in order and find the
   `Get Next Item` `ACTION` stage (VBO `clsWorkQueuesActions`, method `Get Next Item`) — this is
   the hard split point, not a heuristic (don't guess by page name, as the current
   `generator/cloudflow.py`'s `_resolve_role_ids` does per the codebase audit — that's exactly the
   fragile approach this task should replace with something structural).
2. Tag every page reachable **before** that stage (transitively, from Main Page's `Start`) as
   `role: "loader"`, and every page reachable **from** that stage onward (including the loop-back
   target) as `role: "performer"`, on the `BPPage` model (add a field in `ast/models.py` if one
   doesn't exist).
3. Pages unreachable from either path (Task 4a's orphans) get no role (or `role: None`) — don't
   force-assign one.
4. Add a test against `samples/blueprism/PID_0171.bprelease` asserting `Get Mails` and `Populate
   Queue` are tagged `loader`, and `Save Attachments`, `Result Entry`, `Mark Item As Exception`
   are tagged `performer`.

**Done when:** `uv run pytest tests/ast/ -v` passes, including the new role-tagging test.

**Out of scope:** anything in `generator/` that consumes this tagging (Tasks 5a/6a) — this task
only adds the field and computes it correctly.

---

## Task 5a — `generator/pad.py`: consolidate pages into `FUNCTION`s in one Desktop Flow body

**Depends on:** Task 4b
**Files in scope:** `src/flowsmith/generator/pad.py`, `templates/pad/subflow.robin.j2`,
`tests/generator/test_pad.py`
**Required reading:** `docs/bp-to-pad-architecture-PID171.md` §A3 (the exact real Loader/Performer
`FUNCTION` structure to match — main body + helper `FUNCTION`s), §B10 (the page→`FUNCTION`
methodology), §B11 (Loader/Performer split).

**Do:**
1. `generator/pad.py:generate_process()` currently does `for page in process.pages: ...` and
   writes **one `.robin` file per page** (confirmed at line ~96) — this is the core architectural
   gap (strategy doc COV-3/U1). Replace this with: **two** `.robin` outputs per process run — one
   for the `role: "loader"` pages, one for the `role: "performer"` pages (Task 4b's tagging) —
   each a single file containing a main body (the entry-point page's stages, inlined) followed by
   one `FUNCTION '<page name>' ... END FUNCTION` block per other reachable page with that role,
   matching the shape in `docs/pad-reference/DF_PID_171_US_Loader.robin.txt` and
   `DF_PID_171_US_LIMS_Prelude_Main.robin.txt`.
2. A `SubSheet`/`Process`-type `ACTION` stage that calls another page in the same role becomes a
   `CALL '<page name>' <params>` (already partially supported per `templates/pad/actions/
   call_subflow.robin.j2` — check it still fires correctly once pages are consolidated into one
   file rather than separate ones).
3. Update `templates/pad/subflow.robin.j2` if its current per-file assumption (one `FUNCTION` = one
   whole file) needs to change to "one `FUNCTION` block within a larger file."
4. Pages tagged unreachable (Task 4a) should be skipped entirely — not emitted as dead
   `FUNCTION`s — unless you find a reason not to (note it in your summary if so, don't decide
   silently).
5. Keep the existing `@@`/`@INPUT`/`@OUTPUT`/`IMPORT`/`@SENSITIVE` header logic (already correct
   per the codebase audit, commit `760fb47`) — just move it to fire once per output file (Loader,
   Performer), not once per page.

**Done when:** `uv run pytest tests/generator/test_pad.py -v` passes (existing tests will need
updating for the new 2-file-not-N-file output shape — update them, don't just delete coverage),
and a new test asserts that generating from `PID_0171.bprelease`'s AST produces exactly 2 `.robin`
outputs, each containing multiple `FUNCTION ... END FUNCTION` blocks.

**Out of scope:** real BP-expression translation inside the stage bodies (Task 5b — this task is
purely about the *file/FUNCTION* structure, the body content can still be placeholder for now);
Cloud Flow consolidation (Task 6a).

---

## Task 5b — `generator/pad.py`: real BP-expression translation

**Depends on:** Task 5a
**Files in scope:** `src/flowsmith/generator/pad.py`, `templates/pad/actions/*.robin.j2`,
`tests/generator/test_pad.py`
**Required reading:** `docs/bp-to-pad-architecture-PID171.md` §B10 point 3 (expression
translation rules), §B12 (stage-type → template table, now filled in by Task 2c), §B13 /
`docs/pad-reference/vbo-action-mapping.md` (VBO action templates, now filled in by Task 2b).

**Do:**
1. Confirmed placeholders to replace (codebase audit, current line refs approximate — verify
   before editing): `SetVariable` rendering renders `value="%SomeVar%"` unconditionally
   (`pad.py:288`) instead of the stage's actual BP expression; Excel/File/Folder/DateTime/
   Text/WorkQueues template partials render literal placeholder values (`'C:\\path\\to\\file.txt'`,
   `'Sheet1'`, `'QueueName'`) regardless of the real BP stage's actual parameters.
2. For each of these, wire the real stage data through: a `Calculation` stage's BP `expression`
   attribute → translated into the PAD `SET <var> TO <expr>` template (Task 2c's
   `stage_rules.yaml` entry) with BP operators/functions converted per architecture doc §B10 point
   3 (`[Data Item]` → variable reference, string concat `&` → `+`, `Trim(...)`/`Lower(...)` →
   separate `Text.Trim`/`Text.ChangeCase` action lines since PAD can't inline them into an
   expression).
3. For `ACTION` stages calling a VBO method, use `mapper/vbo_router.py`'s (Task 1) resolved
   `method_actions` template, substituting the stage's real `<input>`/`<output>` values into the
   template's placeholders — not a hardcoded example value.
4. Where no real value/template can be resolved (e.g. a VBO method with no `method_actions` entry,
   or a UI-automation stage per §B9), emit the `# TODO` stub — this is the "never silently drop"
   rule; don't emit a placeholder that *looks* like real code when it isn't.

**Done when:** `uv run pytest tests/generator/test_pad.py -v` passes, and a new test asserts that
generating a `Calculation` stage with a known BP expression (e.g. `[Exception Type]` assignment)
produces the exact expected `SET txt_ExceptionType TO ...` line, not a placeholder.

**Out of scope:** Cloud Flow generation (Task 6a).

---

## Task 6a — `generator/cloudflow.py` + `workflow_builder.py`: 4-flow consolidation, orchestrator registration

**Depends on:** Task 4b, Task 5a
**Files in scope:** `src/flowsmith/generator/cloudflow.py`, `src/flowsmith/generator/workflow_builder.py`,
`tests/generator/test_cloudflow.py`, `tests/generator/test_workflow_builder.py` (if it exists —
check)
**Required reading:** `docs/bp-to-pad-architecture-PID171.md` §A2 (the exact real 4-flow topology
and orchestrator `Try:_Init`/`Try:_Loader`/`Try:_Performer`/`Catch:_*` shape to match).

**Do:**
1. `workflow_builder.py:build_workflow()` is currently called once per page (one `<Workflow>`
   element per page) — replace with exactly 2 Desktop Flow `<Workflow>` elements (one per Task
   5a's Loader/Performer `.robin` output), plus the Cloud Flow orchestrator as a 3rd `<Workflow>`
   element (currently, per the codebase audit and `SUBTASK8_VALIDATION_REPORT.md` §8.2, the
   orchestrator JSON exists via `generate_orchestrator()` but is **never registered** as a
   `<Workflow>`/`RootComponent` — this task fixes that registration gap, it's not building the
   orchestrator content from scratch).
2. `generate_orchestrator()`'s existing `Try:_Init`/`Try:_Loader`/`Try:_Performer`/`Catch:_*`
   scope shape is a reasonable approximation already — check it against architecture doc §A2's
   exact structure (trigger inputs `boolean`/`boolean_1`, the `uiFlowId`/`RunUIFlow_V2` desktop
   flow invocation pattern, the Dataverse queue-count gate before invoking the Performer) and
   correct any structural mismatch rather than rewriting it wholesale.
3. Remove the heuristic `_resolve_role_ids` page-name-guessing logic in `cloudflow.py` if Task
   4b's structural `role` tagging now makes it redundant — use the AST's `role` field instead.
4. A 4th Cloud Flow (the Read-Config-File child flow, or a Schedule trigger flow) is **not**
   required by this task if it's out of scope for what the AST/generator can currently produce
   (BP has no direct stage-level equivalent to generate it from) — note this gap explicitly in
   your summary rather than fabricating a Cloud Flow with no BP-derived content.

**Done when:** `uv run pytest tests/generator/test_cloudflow.py -v` (and
`test_workflow_builder.py` if present) pass, and a new test asserts the generated
`customizations.xml`-equivalent structure has exactly 2 Desktop Flow `<Workflow>` elements + 1
registered orchestrator Cloud Flow `<Workflow>` element for `PID_0171.bprelease`, not N-per-page.

**Out of scope:** `packager.py`'s `.zip` assembly (Task 6b).

---

## Task 6b — `generator/packager.py`: wire consolidated output into the `.zip`

**Depends on:** Task 6a, Task 3b
**Files in scope:** `src/flowsmith/generator/packager.py`, `tests/generator/test_packager.py`
**Required reading:** the `generator/packager.py` row of `docs/bp-to-pad-implementation-strategy-PID171.md`
§1.1.

**Do:**
1. `packager.py` currently assembles one `<Workflow>` per page (dependent on
   `workflow_builder.py`'s old per-page behavior — should now follow Task 6a's consolidated output
   automatically once that's fixed; verify it does, don't re-implement the loop).
2. The env-var-definition emission code path already exists (`for env_var in
   process.environment_variables: ...`) but never executes on real input because the parser never
   populated that field (confirmed in the codebase audit) — Task 3b fixed the parser side; verify
   this loop now actually produces `environmentvariabledefinitions/*/*.xml` entries for
   `PID_0171.bprelease`'s 11 environment variables when you run the full pipeline.
3. Delete `templates/report/solution.xml.j2` — confirmed dead code (unreferenced anywhere in
   `src/`, superseded by `solution_with_guids.xml.j2`) per the codebase audit. Grep for any
   reference before deleting, to be sure.
4. `naming.py`'s duplicate-page-name collision (two BP pages sanitising to the same `.robin`
   stem overwrite each other — documented as U2 in `SUBTASK8_VALIDATION_REPORT.md`) — check
   whether Task 5a's consolidation (pages become `FUNCTION`s inside 2 files, not N separate files)
   makes this moot; if page **names** can still collide as `FUNCTION` names within one file, add a
   disambiguation suffix (e.g. append a short id) rather than leaving a silent overwrite.

**Done when:** `uv run pytest tests/generator/test_packager.py -v` passes, and running the full
CLI (`uv run flowsmith convert --input samples/blueprism/PID_0171.bprelease --output
outputs/generated/PID_0171/ --managed`) produces a `.zip` with exactly the file counts implied by
Task 6a's 2 DF + 1 orchestrator CF (not ~380 workflows), populated environment-variable-definition
XML files, and no `solution.xml.j2` remnants.

**Out of scope:** the actual end-to-end acceptance run/validation (Task 7 — this task's "Done
when" runs the CLI as a smoke check, Task 7 is the full formal pass).

---

## Task 7 — End-to-end run against `PID_0171.bprelease` → `outputs/generated/PID_0171/`

**Depends on:** all previous tasks
**Files in scope:** none (no code changes — this is a run + report task)
**Required reading:** `docs/bp-to-pad-implementation-strategy-PID171.md` §4 (the reviewer's
6-dimension scoring methodology — this task's own "done" check should mirror it at a basic level,
full scoring is `pad-reviewer`'s job via `/pad-review 7`, not this task's).

**Do:**
1. Run `uv run flowsmith convert --input samples/blueprism/PID_0171.bprelease --output
   outputs/generated/PID_0171/ --managed`.
2. Run the existing `tests/e2e/test_pid171_pipeline.py` suite against the new output path if it's
   parameterized to accept one, or adapt it if needed — confirm well-formedness (XML/JSON parse,
   `<Definition>` JSON-decodes, no dangling `JsonFileName`/RootComponent references) matching the
   checks already proven in that suite and in `SUBTASK8_VALIDATION_REPORT.md`.
3. Run the full test suite once more (`uv run pytest tests/ -v --cov` and `uv run ruff check src/
   tests/`) to confirm no regression across all the preceding tasks' combined changes.
4. Do **not** attempt the full reference-package comparison scoring here — that's `pad-reviewer`'s
   job (`/pad-review 7` or the auto-triggered post-hook review). This task's job is just: does the
   pipeline run clean end-to-end and produce well-formed output at the new output path.

**Done when:** the CLI run in step 1 exits 0, the well-formedness checks in step 2 pass, and the
full test suite + linter in step 3 are clean.

**Out of scope:** grading similarity to `samples/pad/Shell_PP_PID_US_171_US_PreludeLIMS_V12_1_0_0_11_managed/`
— that's `pad-reviewer`'s dedicated job, not this task's.
