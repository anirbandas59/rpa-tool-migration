# BP → PAD Implementation Strategy — PID_171

**Companion document to** [`docs/bp-to-pad-architecture-PID171.md`](bp-to-pad-architecture-PID171.md)
(the *what*/*why* — the real 4-flow architecture, stage/VBO mapping rules, naming/error/stop
conventions, grounded in the actual deployed `_11_managed` package). This document is the *how*:
guidelines and instructions only — **no code, no YAML content, no `.py` changes are made in this
document**. It exists to be handed to a future implementation phase (controller + small,
Haiku-model implementation subagents, one focused reviewer subagent) so that work can start from a
verified understanding of the codebase rather than rediscovering it.

Two research passes back this document, both completed by direct code/git reading (not inference):
a file-by-file audit of `src/flowsmith/*` cross-referenced against `git log`/`git show` on the
branch's last 9 commits and per-module `tests/` coverage, and a line-by-line audit of
`mapping/stage_rules.yaml` + `mapping/vbo_catalogue.yaml` against the architecture doc and
`docs/pad-reference/vbo-action-mapping.md`. Every claim below cites its evidence.

---

## 1. Codebase classification

**Headline finding:** the pipeline runs end-to-end without crashing — 709/709 tests pass, 93.82%
coverage, and `tests/e2e/test_pid171_pipeline.py` (16 tests) plus
`docs/SUBTASK8_VALIDATION_REPORT.md` independently confirm the output is well-formed and
importable-*shaped*. But it still implements the **old flattened "1 BP page = 1 workflow" design**
— confirmed directly at `src/flowsmith/generator/pad.py:96` (`for page in process.pages:`, one
`.robin` per page) and in `src/flowsmith/generator/packager.py:141-143` (`build_workflow()` called
once per matched page) — not the consolidated 2-Cloud-Flow / 2-Desktop-Flow-with-pages-as-`FUNCTION`s
architecture the reference package actually uses. Against PID_0171's 381 BP pages this produces
~380 Desktop Flow `<Workflow>` elements instead of 4 total. The last 6 commits on this branch
(`0fc18a9` → `7a35549`) fixed real well-formedness defects (XML/JSON escaping, header ordering,
dangling manifest references, filename-collision-drop bug, dangling GOTOs) — all independently
re-verified in current source below, not just trusted from commit messages — but none of them
touch the architectural gap.

### 1.1 Classification table

| Module | LOC | Classification | Evidence |
|---|---|---|---|
| `parser/process.py` | 589 | **Needs Update** | Solid namespace-aware per-page/stage extraction, but only ever resolves the *first* `<process>` inside `<release><contents>` — no multi-artefact handling for the sibling process or 22 VBO objects. Never extracts release-level `<environment-variable>` elements despite `BPEnvironmentVariable` already existing in the AST model. |
| `parser/__init__.py` | 9 | Needed | Trivial re-export. |
| `ast/models.py` | 379 | **Needs Update** | Well-designed, validated Pydantic v2 models. `environment_variables` field is explicitly documented in its own docstring as "not yet parser-populated" — a self-acknowledged gap. |
| `ast/builder.py` | 464 | **Needs Update** | Robust normalisation/pairing logic (skip-types, SubSheet→ACTION collapse, WaitStart/End & LoopStart/End bracket matching via `group_id`, Block-pair-by-name) — but no call-graph/reachability model at all. This is the natural home for page-pruning (drop unreachable/orphan pages, §B11/§B16 of the architecture doc) and Loader/Performer role tagging (§B11), neither of which exists yet. |
| `ast/serialiser.py` | 94 | Needed | Complete, simple JSON round-trip, correctly typed exceptions. |
| `ast/__init__.py` | 46 | Needed | Re-exports only. |
| `engine/annotator.py` | 370 | **Needs Update** | Correct per-stage dispatch and confidence scoring, never raises on unknown input. Annotates every stage unconditionally — no reachability filter, so orphan/dead BP pages (confirmed real: "Mark leftout Items as Exception", "Send Info to Data Gateways" — see architecture doc §B14/§B16) and every VBO utility page still get full annotation and downstream generation. Needs to consume `ast/builder.py`'s future reachability model once it exists. |
| `engine/scorer.py` | 299 | **Needed (currently unwired)** | Complete, heavily tested (2.5× more test code than module code). Nothing in `cli/app.py` calls it — the `report` command is an unimplemented stub. Keep as-is; out of scope to wire up for the PID_171 goal itself. |
| `engine/flag_index.py` | 243 | **Needed (currently unwired)** | Same situation as `scorer.py` — complete, tested, orphaned pending `reporter/`. |
| `engine/__init__.py` | 26 | Needed | Wires `create_annotator()`. |
| `mapper/config.py` | 227 | **Needs Update** | YAML loading/validation is correct and fails fast. But `VBOEntry`'s schema has **no per-method PAD action field** — only `method_patterns: list[str]` (BP-side method names) and a single `pa_module` per VBO. This is the confirmed root cause of the WorkQueues-stub defect (§2.1 below) — a schema gap, not just missing data. |
| `mapper/vbo_router.py` | 165 | Needed | Routing logic (exact→fuzzy→unknown-stub lookup, mandatory review-flag injection) is correct and fully covered; the gap is upstream data/schema, not this code. |
| `mapper/type_mapper.py` | 154 | Needed | Complete, pure-function type mapping with correct lossy-type review flags. |
| `mapper/__init__.py` | 27 | Needed | Re-exports. |
| `generator/pad.py` | 571 | **Needs Update** | Structural work is solid: typed `ON BLOCK ERROR` handlers, `GOTO`/`LABEL` epilogues (commits `a0f3b200`, `7a35549`) so nothing dangles, `@SENSITIVE` detection. But concrete action renderers emit **hardcoded placeholders**, not translated BP expressions — confirmed directly: `SetVariable` renders `value="%SomeVar%"` (pad.py:288); Excel/File/Folder/DateTime/Text/WorkQueues templates render literal placeholder paths/values regardless of the real BP stage's actual parameters. |
| `generator/workflow_builder.py` | 493 | **Needs Update** | Solid metadata/claims/category derivation (commit `a3ab601`) and correct JSON-escaping of `<Definition>` (commit `af0e634`). Still fundamentally one-`Workflow`-per-page (`build_workflow()` per page, `_page_workflow_ids` keyed by `page.page_id`). `dependencies.childFlows` is always `[]`. |
| `generator/cloudflow.py` | 711 | **Needs Update** | Largest generator file. Still per-page Cloud Flow generation rather than one consolidated Cloud_Main. `generate_orchestrator()` (commit `34d5a9c`) is a reasonable first approximation of the Try:_Init/Try:_Loader/Try:_Performer pattern (architecture doc §A2) but works by heuristically picking "loader"/"performer"-named pages out of the flattened output (`_resolve_role_ids`), not a true 2-desktop-flow consolidation — and per `SUBTASK8_VALIDATION_REPORT.md` §8.2, the orchestrator JSON is never registered as a `<Workflow>` element in `customizations.xml` (inert payload today). Per-page CF action bodies (`_render_action`) mostly `Compose "STUB: ..."` for anything outside a handful of recognized `target_type`s. |
| `generator/connections.py` | 161 | Needed | Complete, deterministic (md5-derived logical names), correctly shared between CF JSON and customizations.xml shapes. |
| `generator/naming.py` | 72 | **Needs Update** | Fixed the stem-derivation-mismatch bug well (commit `42dd686`), but by design still doesn't solve the duplicate-page-name collision (two BP pages sanitising to the same stem will still overwrite each other's `.robin` file — documented as U2 in `SUBTASK8_VALIDATION_REPORT.md`). |
| `generator/xml_escape.py` | 62 | Needed | Small, complete, correctly closes the well-formedness defects (commit `0fc18a9`). |
| `generator/packager.py` | 399 | **Needs Update** | Escaping filters, manifest JSON writing, env-var-definition emission code path are all correctly wired — but the env-var loop never executes on real input because the parser never populates `environment_variables` (see `parser/process.py` row). Still assembles one `<Workflow>` per page. `templates/report/solution.xml.j2` is dead code — only `solution_with_guids.xml.j2` is ever rendered (confirmed via grep, nothing references the former). |
| `generator/__init__.py` | 7 | Needed | Re-exports. |
| `exceptions.py` | 41 | Needed | Complete, simple typed-exception hierarchy, correctly used everywhere else. |
| `reporter/` | 0 (empty) | **Needed — reclassified, see below** | Never started, but `engine/scorer.py`/`engine/flag_index.py` already produce everything a reporter would need — presentation/wiring, not new logic. **Originally scoped as "later nice-to-have"**; reclassified after the ~200-automation/9-month rollout context made clear that a developer-facing AUTO/SPOT-CHECK/MANUAL breakdown is required infrastructure, not optional — without it, a developer has no fast way to know what to trust per automation, which defeats the tool's whole value proposition. Now Task 8. |
| `cli/app.py` | 149 | **Needs Update** | `convert` is fully wired and runs the real pipeline end-to-end. `report` and `deploy` are explicit `"Not yet implemented"` stubs. No flags yet for the things a redesign needs (multi-artefact input, page-pruning, Loader/Performer role assignment). |
| `templates/report/solution.xml.j2` | — | **Not Useful (dead code)** | Confirmed unreferenced anywhere in `src/` via grep; superseded by `solution_with_guids.xml.j2`. Candidate for deletion during implementation. |
| `templates/pad/actions/work_queues.robin.j2` | — | **Needs Update** | Its `{% elif target_type == ... %}` branches check for names ("Create Queue", "Add Queue Item", "Get Queue Item", "Remove Queue Item", "Update Queue Item", "Get Queue Items") that **do not match** any real BP method name or any name in `vbo_catalogue.yaml`'s `method_patterns` for `clsWorkQueuesActions` — root cause of every WorkQueues call falling through to the `# TODO` else-branch, independently reproduced (§2.1). |

### 1.2 Test coverage signal (how safe each area is to change)

| Area | Test file(s) | Ratio to module size | Signal |
|---|---|---|---|
| `parser/`, `ast/` | `test_process.py`+`test_integration.py` (1445 LOC/89 tests), `test_builder.py` (609/40), `test_models.py` (415/42), `test_serialiser.py` (326/15) | 1.5–4× | Heavily tested — safe to extend with confidence; regressions will be caught. |
| `engine/` | `test_annotator.py` (411/29), `test_scorer.py` (762/46), `test_flag_index.py` (485/36) | 1.4–2.5× | Heavily tested. |
| `mapper/` | `test_config.py` (643/37), `test_vbo_router.py` (415/39), `test_type_mapper.py` (355/36) | 2.3–2.8× | Heavily tested — a `VBOEntry` schema change (§2.2) will need real test updates, not just new fixtures. |
| `generator/packager.py` | `test_packager.py` (1857/65) | **4.7×** | Largest test file in the repo by far — reflects how much regression churn this file has already absorbed. Safe to touch, expect a large existing suite to react. |
| `generator/pad.py` | `test_pad.py` (926/52) | 1.6× | Heavily tested. |
| `generator/cloudflow.py` | `test_cloudflow.py` (709/42) | ~1× | Well tested for "doesn't crash / produces valid JSON," but given how many action branches are still placeholder stubs, coverage of *architectural correctness* is likely thinner than the ratio suggests. |
| `cli/app.py` | `test_app.py` (65/6) | 0.4× | Thin — smoke-level only. |
| `reporter/` | none | — | N/A, module is empty. |
| e2e | `tests/e2e/test_pid171_pipeline.py` (210/16) | — | The one true end-to-end acceptance suite; run this after any cross-module change. |

### 1.3 mapping/ and templates/ inventory

- `mapping/` contains exactly 2 files: `stage_rules.yaml`, `vbo_catalogue.yaml` (confirmed, no
  others).
- `templates/pad/` — 2 top-level (`flow_header.robin.j2`, `subflow.robin.j2`) + 20 action partials
  (`actions/*.robin.j2` — call_subflow, condition, datetime, error_block, excel_read, file, folder,
  get_variable, goto, goto_epilogue, loop, recover, scripting, set_variable, stub, text,
  throw_error, work_queues).
- `templates/cloudflow/` — 2 top-level (`flow_definition.json.j2`, `orchestrator.json.j2`) + 12
  action partials (condition, foreach, http, initialize_variable, parse_json, query, response,
  scope, select, send_email, set_variable, sharepoint, stub, workflow — all `.json.j2`).
- `templates/report/` — 5 files: `content_types.xml.j2` (missing a `png` default — relevant if
  UI-binary support, §B_VBO out-of-scope items, is ever added), `customizations_workflows.xml.j2`
  (used), `environmentvariabledefinition.xml.j2` (built, never exercised — see `parser/process.py`
  row), `solution.xml.j2` (dead code), `solution_with_guids.xml.j2` (used).

---

## 2. Mapping dependency update guidance

This section is **instructions for a future implementation subagent** — it specifies what must
change and why, sourced from `docs/pad-reference/vbo-action-mapping.md` (canonical VBO mapping
data) and `docs/bp-to-pad-architecture-PID171.md` §A4-A7/§B12/§B13. It does not rewrite the YAML
itself.

### 2.1 Prerequisite: `mapper/config.py` schema change

`VBOEntry` currently holds `method_patterns: list[str]` (BP-side method names only) and a single
`pa_module: str` per VBO — there is nowhere to record "method X on this VBO maps to concrete PAD
call Y, method Z maps to concrete PAD call W." This is why `templates/pad/actions/work_queues.robin.j2`
has to guess at BP method names in its own `{% elif %}` branches (and guesses wrong — see §1.1).
**Before** `vbo_catalogue.yaml`'s content can be fixed usefully, `VBOEntry` needs a field that maps
each BP method name to its own PAD action template (e.g. `method_actions: dict[str, str]`, or a
small list of `{bp_method, pa_action_template}` objects) — a schema change in `mapper/config.py`,
with a corresponding update to `mapper/vbo_router.py`'s lookup logic and `test_config.py`/
`test_vbo_router.py`. This is step 1 of the coding-phase sequencing in §3, and everything else in
this section depends on it landing first.

### 2.2 `vbo_catalogue.yaml` — corrections and additions needed

Once the schema exists, populate/correct entries using `docs/pad-reference/vbo-action-mapping.md`
as the source (every row there already cites a real, confirmed PAD call — do not add a
`vbo_catalogue.yaml` entry without an equivalent citation):

- **Runtime corrections** (currently wrong, contradicts confirmed real PAD behavior):
  - `Blueprism.Automate.clsWorkQueuesActions`: `runtime: CLOUD` → **`DESKTOP`**. Real
    `WorkQueues.*` calls (`ProcessWorkQueueItem`, `GetWorkQueueItems`, `UpdateWorkQueueItem`,
    `UpdateProcessingNotes`, `EnqueueWorkQueueItem`) are Desktop Flow Robin actions.
  - `Utility - JSON`: `runtime: CLOUD` → **`DESKTOP`**. Real JSON conversion
    (`Variables.ConvertJsonToCustomObject`/`ConvertCustomObjectToJson`) happens inside the desktop
    flows.
  - `Utility_DataGateways-CustomFramework`: `runtime: DESKTOP` stays, but `pa_module: "Database"`
    → **the real pattern is `External.RunFlow` calling a sibling desktop flow** (architecture doc
    §B13's DataGateways row), not a Database module call at all.
- **`pa_module` corrections**:
  - `Utility - Environment`: `pa_module: "shared_sharepointonline"` → **`System`** (real usage:
    `System.GetEnvironmentVariable.GetEnvironmentVariable`). The current value is simply wrong for
    how this VBO is actually used in PID_171.
  - `Blueprism.Automate.clsCredentialsActions`: `pa_module: "shared_keyvault"` is already correct
    — but note the runtime model gap this exposes: the call happens *inside* a Desktop Flow, via
    `External.InvokeCloudConnector`, calling a *cloud* connector. The current `CLOUD`/`DESKTOP`
    binary `runtime` field cannot express "desktop flow, cloud connector" — flag this as a schema
    limitation for whoever does §2.1's schema work to consider (a third value or a separate
    `connector_from_desktop: bool` flag), not something to paper over with an incorrect single
    value.
- **Missing VBOs to add** (real, confirmed usage in PID_171, absent from the catalogue today):
  `PID_0003_Object_US_SampleManager` and `PID_0005_Object_US_SampleResultsEntry` (the two
  UI-heavy custom VBOs driving ~200+ stages — map every method to the `# TODO: UI selector
  required` stub per architecture doc §B9/§B_VBO, `confidence_base` low, not a real action), `MS
  Outlook Email VBO Extended`, `MS Outlook Extended VBO`, `Utility_Object_Generic_ScreenShot`
  (the catalogue's current `"DWF Utility - Screenshot"` entry is a different, non-matching name —
  do not assume it covers this), `Utility - Image Search`, `Utility_Sharepoint_API_Config` (the
  catalogue's `Utility_PnP_Auth`/`RPA Sharepoint Conifgfile Download` entries don't match this
  exact real name either).
- **Method-pattern corrections** for VBOs that already exist in the catalogue but list the wrong
  method names for PID_171 (e.g. `MS Excel VBO`'s current patterns — "Get Cell Value", "Set Cell
  Value", "Save Workbook", "Get Last Row Number", "Create Worksheet" — don't match PID_171's real
  methods: "Create Instance", "Open Workbook", "Get Worksheet As Collection", "Close Workbook",
  "Close Instance", "Write to cell", "Save As"). Cross-check every existing entry's
  `method_patterns` against `docs/pad-reference/vbo-action-mapping.md` rather than assuming an
  existing row is already correct just because the VBO name matches.

### 2.3 `stage_rules.yaml` — corrections and additions needed

- Header comment says "14 canonical types" — stale; update to **18** (CLAUDE.md's authoritative
  reference list, which also fixed an earlier miscount).
- Missing normalisation rows entirely: `Process` → `ACTION` (`is_process_call=True`), `Alert` →
  `ACTION` (`is_alert=True`), `Skill` → `ACTION` (`is_skill=True`, confidence forced to MANUAL) —
  all defined in CLAUDE.md, none present in the current file.
- **New special-case rule discovered this session, not yet documented anywhere in the mapping
  layer**: BP's single `Process`-type stage in the main process (Main Page's "Download Config File
  from SharePoint," calling the sibling `RPA_Sharepoint_API_ConfigFile_Download` process) maps to
  Cloud_Main's `Try: Init` scope → a `Workflow`-type action calling `CF_PID_171_US_Read Config
  File` — a **cloud-tier** mapping, unlike every other `SubSheet`/`Action` stage which stays
  desktop-tier. `stage_rules.yaml`'s `Process` row needs a note (or a dedicated flag) capturing
  that a BP `Process` call is a candidate for cloud-tier translation, not a blanket
  `pa_module: "System"` skip.
- Every `pa_target_action` field in the file is currently an empty string — the file's own header
  comment says this is "filled in Phase 4," which never happened. Filling these in is real work,
  not a formality: each canonical stage type's `pa_target_action` should be the literal syntax
  template from architecture doc §B12 (e.g. `CALCULATION` → `SET <var> TO <expr>`,
  `LOOP`(foreach) → `LOOP FOREACH <item> IN <collection> ... END`), not left blank for the
  generator to guess at via hardcoded Python.
- `CHOICE` stays absent, correctly — CLAUDE.md itself says not to implement it until a real BP
  sample with `Choice` stages is obtained; PID_171 has zero occurrences (confirmed). Don't add a
  speculative row.

### 2.4 Discipline for whoever does this work

Never add a `pa_target_action`/`method_actions` entry without a citation to
`docs/pad-reference/vbo-action-mapping.md` or `docs/bp-to-pad-architecture-PID171.md`. A row with
no confirmed real call gets a `**STOP**`/low-`confidence_base` placeholder, not an invented
plausible-looking action — this is the same rule the architecture doc already enforces on itself.

---

## 3. Execution strategy for the (future) coding phase

This section describes how the coding phase — not started by this document — should be organized
once it begins.

### 3.1 Roles

- **Controller** (the orchestrating Claude session): owns design decisions, task breakdown, file
  scoping, and integration between subagent outputs. Does not write implementation code directly
  except where a task is too small/interdependent to delegate usefully.
- **Implementation subagents** (Haiku model): each gets one small, fully self-contained task —
  explicit file(s) to touch, the specific architecture-doc/VBO-mapping section it implements, and
  a clear done-condition (a test file to pass, a specific output shape to produce). Implementation
  only — no design decisions delegated to them.
- **Reviewer subagent** (§4): a separate, later pass — grades the finished output, does not
  participate in building it.

### 3.2 Sequencing

Respects the pipeline's real dependency order (parser → AST → mapper → engine → generator →
packager — the same ordering `docs/bp-to-pad-pipeline-plan.md`'s already-executed 8-sub-task plan
used), scoped specifically to the consolidated-architecture gaps identified in §1:

0. Build the PAD action index (`docs/pad-reference/pad-action-index.yaml`) — merges the PDF's
   full action-name/description surface with confirmed syntax mined from every real PAD source
   file already in the repo, kept honestly separated (`confirmed` vs `description-only`). No
   dependency on anything else; can run first or in parallel with step 1. Complements, doesn't
   replace, `vbo-action-mapping.md` — this is a curation-time search index keyed by PAD action,
   not the runtime lookup keyed by BP VBO.
1. `mapper/config.py` schema extension (§2.1) — per-method actions **and** multi-stage
   fusion-pattern support (architecture doc §B_FUSION — a BP idiom like `MS Excel VBO`'s
   `Create Instance`+`Open Workbook` collapses into one PAD call, which a flat 1:1 method→action
   table can't express; found via a worked example during this planning session, not from the
   original codebase audit). Prerequisite for step 1b and step 2.
1b. `ast/builder.py`: VBO call-fusion detection pass (architecture doc §B_FUSION) — a generic
   structural pre-filter (numeric-handle-output-feeds-numeric-handle-input, independent of which
   VBO) flags fusion candidates; those matching a curated `fusion_patterns` entry (step 1's schema)
   resolve to the fused action, everything else gets a `ReviewFlag` rather than a wrong per-stage
   guess. Same shape as the existing `WaitStart`/`WaitEnd` bracket-pairing pass.
2. `mapping/vbo_catalogue.yaml` + `mapping/stage_rules.yaml` content fixes (§2.2-2.3), now also
   populating `fusion_patterns` for the known Excel pairs (and any others found during this task).
3. `parser/process.py`: multi-artefact (release-level) parsing + `<environment-variable>`
   extraction.
4. `ast/builder.py`: call-graph/reachability model (drop orphan pages, confirmed real ones exist —
   architecture doc §B14/§B16) + Loader/Performer role tagging (architecture doc §B11's hard
   boundary at BP stage `85fbb578`).
5. `generator/pad.py`: consolidate pages into `FUNCTION`s inside one Desktop Flow body (per role —
   Loader vs. Performer) + replace hardcoded action-renderer placeholders with real BP-expression
   translation (consuming step 1b's fusion annotations where present).
6. `generator/cloudflow.py` / `workflow_builder.py` / `packager.py`: consolidate to the real 4-flow
   shape (2 CF + 2 DF per architecture doc §A2), fix the orchestrator-registration gap (§8.2 of
   `SUBTASK8_VALIDATION_REPORT.md`).
7. End-to-end run against `samples/blueprism/PID_0171.bprelease`, output to
   `outputs/generated/PID_0171/`.
8. `reporter/`: developer-facing AUTO/SPOT-CHECK/MANUAL coverage report (§1.1's reclassified
   `reporter/` row) — required infrastructure for the ~200-automation rollout (§5), not a
   PID_171-specific nicety.
9. Calibration checkpoint: run the finished pipeline against `samples/blueprism/PID_0127.bprelease`
   (already in this repo — the original source `mapping/*.yaml` was generated from) and measure
   whether AUTO-band coverage holds on a second, different automation before treating the tool as
   ready for team-wide rollout. See §5.

Each numbered step becomes one or more Haiku subagent tasks, sized to a single file or a tightly
related pair of files. Each task's required reading is the architecture doc section(s) and/or the
VBO mapping file rows it implements — not this document's full audit, and not the session history
that produced it.

### 3.3 Guardrails for every implementation task

- Cite which section of `docs/bp-to-pad-architecture-PID171.md` or
  `docs/pad-reference/vbo-action-mapping.md` the task implements.
- Run the existing relevant test file after the change (per-module tests are already heavy — §1.2
  — so regressions surface immediately); do not consider a task done until its test file passes.
- Do not touch files outside the assigned scope.
- **When generating a page's `FUNCTION` body specifically**: the BP page's actual business logic
  (branches, data flow, call order) must be preserved, not approximated. A stage that genuinely
  can't be translated (UI selectors, per architecture doc §B9) must still get an explicit
  `# TODO`/comment marking exactly what's missing at that point — never a silent drop. This is the
  same standard §4's reviewer grades against, stated here as a build-time requirement, not only a
  post-hoc review finding.

---

## 4. Reviewer subagent specification

Defines the review methodology precisely enough that a subagent can execute it without further
design input, once the coding phase produces output.

- **Inputs**: `outputs/generated/PID_0171/` (the generated output) vs.
  `samples/pad/Shell_PP_PID_US_171_US_PreludeLIMS_V12_1_0_0_11_managed/` (the reference — both
  already-established ground truth this session; the reference's `<Definition>` extraction method
  is in `scripts/extract_definitions.py`).
- **Dimensions to score** (each as a coverage fraction + a short evidence note — never collapse
  straight to one aggregate number without the breakdown):
  1. **Structural** — does the output have 2 Desktop Flows + 2 Cloud Flows (or an explicitly agreed
     subset) with the right roles, not N per-page workflows.
  2. **`FUNCTION` functional fidelity** — for each BP page that should map to a named `FUNCTION`
     per architecture doc §B14, does the `FUNCTION` actually preserve that page's BP business logic
     (same branches, same data flow, same calls in the same order) — not merely "a `FUNCTION`
     exists with a plausible-looking body." Where a stage genuinely can't be translated (UI
     selectors, per §B9), confirm it carries the required `# TODO`/comment rather than a silent
     drop; when scoring, judge the *translatable* portion of such a page on its own merits (correct
     comment coverage for the untranslatable rest counts as a pass, not a penalty) rather than
     marking the whole page "incomplete" for content that's legitimately out of scope.
  3. **VBO/action fidelity** — for a sample of `CALL`/module-action lines, do they match the real
     syntax templates in architecture doc §B12/§B13 rather than placeholders. Includes checking
     that §B_FUSION's known multi-stage patterns (e.g. Excel's `Create Instance`+`Open Workbook`)
     render as one fused action, not two independent per-stage translations — a page containing a
     fusion pair that was translated stage-by-stage instead of fused is a fidelity defect here,
     not a structural or naming issue.
  4. **Naming-convention compliance** (§A4).
  5. **Error-handling/stop/consecutive-exception pattern presence** (§A5-A7).
  6. **Well-formedness** — XML/JSON parses, `<Definition>` JSON-decodes, no dangling references —
     reuse the exact checks already proven in `tests/e2e/test_pid171_pipeline.py` and
     `SUBTASK8_VALIDATION_REPORT.md` rather than inventing new ones.
- **Output**: a single `%` overall figure plus the per-dimension breakdown above and a list of the
  most significant gaps, written as its own dated report under `docs/` — never silently overwriting
  a prior review report; if one already exists, write a new dated file and note what changed since
  the last one.

---

## 5. Rollout scope: PID_171 is the pilot, not the destination

This tool exists to support a ~200-automation migration program (9 months, ~20/month target
throughput) — PID_171 is the first, most-deeply-analyzed automation, used to build the tool's
core capability against real, verified ground truth. It is not a one-off. Two consequences worth
stating explicitly, since they change what "done" means for this coding phase:

**The economics only work if `flowsmith convert` stays fully offline and deterministic.**
Developers converting the other ~199 automations must never need to prompt a chat AI, review
logic they didn't write to judge if it's safe, or wait on live model access — their loop is:
run the CLI, read the report (§1.1/Task 8), build only what's flagged (predominantly UI
selectors, matching what developers already expect to hand-build). Every design decision in this
document (agent-assisted curation happening *before* or *alongside* the coding phase, never
inside `convert` itself; the fusion-pattern catalogue in §B_FUSION being a static, checked-in
data source rather than a runtime lookup to an LLM) exists to protect that property. Any future
change to this pipeline that would make a real conversion run depend on live agent/LLM access
should be treated as a regression against this rule, not a feature, unless explicitly re-decided.

**Curated coverage transfers unevenly, and that's expected, not a flaw.** Shared/common BP VBOs
(`MS Excel VBO`, `MS Outlook Email VBO`, `clsWorkQueuesActions`, the `Utility - *` family) are
present across most real BP estates — curation done for PID_171 pays off on every future
automation that uses them, which is most of them. Process-specific custom VBOs (PID_171's
`PID_0003_Object_US_SampleManager`/`PID_0005_Object_US_SampleResultsEntry`) will **never**
generalize — every automation will have some irreducible bespoke-UI surface no catalogue can
close, and that surface is exactly where developers already expect to spend their time. Task 9's
calibration checkpoint exists to measure the actual split between these two categories on a
second, different automation before anyone commits to a coverage number for the other ~198.

---

## Next step

This document, once reviewed, gates the coding phase described in §3 — Haiku-subagent
implementation orchestrated by the controller, `mapping/*.yaml` edits, `src/flowsmith` changes, the
run against `PID_0171.bprelease` into `outputs/generated/PID_0171/`, the developer-facing report
(Task 8), and the PID_0127 calibration checkpoint (Task 9, §5) — none of which has started yet.
