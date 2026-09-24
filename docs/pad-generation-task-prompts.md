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
task whose "Depends on" isn't already done. **Task 0** has no dependency and touches no
`src/flowsmith` code — it can run first, in parallel with Task 1, or any time; doing it early
means Task 2b has a broader reference to pull from.

---

## Task 0 — Build the PAD action index: PDF descriptions + confirmed syntax from real source

**Why this task exists:** `docs/pad-reference/vbo-action-mapping.md` only covers the ~40 actions
PID_171 happens to use, each hand-confirmed against `docs/pad-reference/*.robin.txt`. The PDF
cheat sheet covers PAD's full action surface (~40 categories) with a name + one-line description
per action, but — confirmed earlier this session via `pdftotext -layout` extraction — **no calling
syntax at all**, only names and descriptions. This task builds one merged, reusable reference that
keeps those two kinds of information honestly separated, so a later curation pass (resolving
`ReviewFlag`s for BP VBOs with no existing catalogue entry) can search by *description/intent*
first, and know immediately whether a match has real, confirmed syntax or only a name — never
treating the two as equivalent.

**Depends on:** none
**Files in scope:** new `scripts/build_pad_action_index.py`, new
`docs/pad-reference/pad-action-index.yaml` (output). No changes to `src/flowsmith`,
`mapping/*.yaml`, or any existing `docs/pad-reference/` file.
**Required reading:** `C:\Users\AnirbanDas\Downloads\power-automate-desktop-actions.pdf` (the PDF
itself — user-local path, not in the repo; read it directly, same `pdftotext -layout` extraction
approach already proven to work on it this session — Git for Windows bundles `pdftotext.exe`),
`docs/pad-reference/vbo-action-mapping.md` (existing precedent for row format/citation discipline,
indexed by BP VBO rather than by PAD action — this task builds the complementary index, it doesn't
replace that file).

**Do:**
1. Extract PDF entries into `{friendly_name, category, description}` rows, covering every action
   listed across all ~40 categories (Variables, UI automation, Excel, Work queues, Office 365
   Outlook, etc.) — not just the categories PID_171 happens to use.
2. Extract confirmed syntax by scanning every real PAD source file already in the repo for actual
   action-call lines (the `<Module>.<SubModule...>.<Method> <params>` shape) — at minimum:
   `docs/pad-reference/DF_PID_171_US_Loader.robin.txt`,
   `docs/pad-reference/DF_PID_171_US_LIMS_Prelude_Main.robin.txt`,
   `docs/robin_Shell_PP_DesktopFlow_Template_Loader_Performer.robin`,
   `docs/robin_Shell_PP_Reusable_Subflows.robin`,
   `docs/robin_Shell_PP_SendEmail_Reusable_DesktopFlow.robin`,
   `samples/pad/fixed/PID171_loader_fixed.txt`, `samples/pad/fixed/PID171_performer_fixed.txt`,
   `samples/pad/PID171_loader.txt`, `samples/pad/PID171_performer.txt`,
   `samples/pad/Shell_PP_DesktopFlow_Template_Loader_Performer.txt` — plus glob for any other
   `.robin`/`.txt` PAD source under `samples/pad/` and `docs/` you find; don't treat this list as
   exhaustive, note in your summary what you actually scanned. For each call found, capture the
   dotted action name, full parameter list verbatim, and source file + line number.
3. Align each confirmed-syntax dotted name (e.g. `Excel.LaunchExcel.
   LaunchAndOpenUnderExistingProcess`) to its PDF friendly-name row (e.g. "Launch Excel," category
   "Excel"). **This is not a plain string match** — the PDF uses PAD Studio's UI labels, Robin
   script uses dotted internal paths. Align via category + keyword heuristics (match the PDF
   category to the dotted name's leading module, then fuzzy-match the friendly name's key terms
   against the method name). Any alignment you're not confident in gets marked
   `alignment: unconfirmed` rather than silently paired wrong.
4. Emit `docs/pad-reference/pad-action-index.yaml`: one entry per action — `dotted_name` (or
   absent if PDF-only with no confirmed syntax and no confident alignment), `friendly_name`,
   `category`, `description`, `confidence` (`confirmed` | `description-only`), `syntax` (only when
   `confirmed`), `syntax_source` (file + line, only when `confirmed`).
5. Add a header to the file (same convention as `vbo-action-mapping.md`) stating its purpose,
   its relationship to `vbo_catalogue.yaml` (this is a curation-time search index keyed by *PAD
   action*; `vbo_catalogue.yaml` stays the runtime lookup keyed by *BP VBO* — this file doesn't
   replace it), and the row-format rule for future additions (never mark `confirmed` without a
   real `syntax_source` citation).

**Done when:** `pad-action-index.yaml` exists and parses as valid YAML; every `confirmed` row's
`syntax_source` resolves to a real file and line (spot-check a handful); your summary reports the
total count of `confirmed` vs. `description-only` rows — that ratio is itself a useful number for
planning how much curation work remains before the tool's action coverage is broad.

**Out of scope:** using this index to resolve any specific `ReviewFlag`, or building the
curation-agent that would search it (a future task, once this index exists) — this task only
builds the reference artifact.

---

## Task 1 — `mapper/config.py`: add per-method action field + fusion-pattern schema to `VBOEntry`

**Depends on:** none
**Files in scope:** `src/flowsmith/mapper/config.py`, `src/flowsmith/mapper/vbo_router.py`,
`tests/mapper/test_config.py`, `tests/mapper/test_vbo_router.py`
**Required reading:** `docs/bp-to-pad-implementation-strategy-PID171.md` §2.1 and the
`mapper/config.py` row of §1.1; `docs/bp-to-pad-architecture-PID171.md` §B_FUSION (the fusion
concept this schema must be able to express — read this before designing the schema, not after).

**Do:**
1. Open `src/flowsmith/mapper/config.py` and find the `VBOEntry` model. It currently has
   `method_patterns: list[str]` (BP-side method name substrings) and a single `pa_module: str` per
   VBO — there is no way to record either (a) "method X on this VBO maps to concrete PAD call Y,
   method Z maps to a different concrete PAD call W" or (b) "methods X and Y, in sequence, fuse
   into one PAD call Z" (§B_FUSION — e.g. `MS Excel VBO`'s `Create Instance` + `Open Workbook`).
   This task's schema must support both, not just the first.
2. Add a new optional field, e.g. `method_actions: dict[str, str] = Field(default_factory=dict)`,
   mapping an **exact** BP method name (as it appears in `<resource action="...">`) to a literal
   PAD action-call template string, for the ordinary 1:1 case. Keep `method_patterns` for fuzzy
   fallback matching — don't remove it.
3. Add a second new optional field for the fusion case, e.g. `fusion_patterns:
   list[VBOFusionPattern] = Field(default_factory=list)`, where `VBOFusionPattern` is a small
   model with at least: `sequence: list[str]` (the ordered BP method names that must appear
   consecutively, e.g. `["Create Instance", "Open Workbook"]`), `fused_action: str` (the literal
   PAD template for the whole sequence), and `vestigial_stages: list[str]` (which method names in
   the sequence produce no PAD output of their own — e.g. `["Create Instance"]`).
4. Update YAML-loading validation so both new fields are optional (default to `{}`/`[]`) and
   validated per their types.
5. In `mapper/vbo_router.py`, update the routing logic in two parts:
   - **Per-stage resolution** (unchanged in spirit): when resolving a single stage's BP method
     name against a `VBOEntry`, first check `method_actions` for an exact key match (high
     confidence), then fall back to `method_patterns` fuzzy match (lower confidence), then the
     existing unknown-stub behavior.
   - **New: fusion-candidate check**, which must run *before* per-stage resolution for any stage
     that is the first element of some `VBOEntry.fusion_patterns[i].sequence` **and** the
     immediately-following stage (same page, `onsuccess`-linked, no branch in between) is a
     matching `ACTION` call to the *next* method name in that same sequence: resolve the **whole
     matched sequence** to the pattern's `fused_action` (attached to the *last* stage in the
     sequence, or wherever the AST fusion pass from Task 1b decides is the right attachment point
     — coordinate with that task), and mark every stage named in `vestigial_stages` as producing
     no independent output. Do not implement the *detection* of adjacent stages here — that's
     Task 1b's job in `ast/builder.py`; this router only needs to resolve a sequence **it's given**
     against the catalogue's fusion patterns.
6. Update `test_config.py` (schema accepts `method_actions` and `fusion_patterns`, both default to
   empty when absent) and `test_vbo_router.py` (exact `method_actions` match takes precedence over
   `method_patterns` fuzzy match; a `VBOEntry` with neither new field behaves exactly as before —
   no regression; a `fusion_patterns` entry resolves correctly when the router is given a matching
   method-name sequence).

**Done when:** `uv run pytest tests/mapper/ -v` passes, including new tests for both the per-method
precedence behavior (step 5's first bullet) and fusion-pattern resolution (step 5's second
bullet).

**Out of scope:** populating `vbo_catalogue.yaml`'s `method_actions`/`fusion_patterns` data
(Tasks 2a/2b); detecting *which* adjacent stages form a fusion candidate in the first place
(Task 1b).

---

## Task 1a — `parser/process.py`: capture ACTION output/input types and flow edges

**Why this task exists:** found by `pad-reviewer`'s Task 1b review (`docs/reviews/1b-2026-08-29.md`,
30%, "blocked pending a design decision"). Task 1b's fusion-detection logic is correct but cannot
see the real `PID_0171.bprelease` fusion pairs at all — confirmed by the reviewer independently
running the real `Read Excel As Collection` page — because two things it needs were never
extracted at the parser layer: (1) `parser/process.py` never parses `<outputs>` on `ACTION` stages
(confirmed by grep — no `<output` handling anywhere in the file), and `<input>` elements route
into `params_map`, not `data_items`, so the numeric-handle output→input signal §B_FUSION describes
never reaches `BPStage`; (2) neither `RawStage` nor `BPStage` carries `onsuccess`/`ontrue`/
`onfalse` edge targets anywhere (also confirmed by grep), so Task 1b's "sole `onsuccess` target is
the next stage" adjacency check was approximated by raw list position instead — works by
coincidence on the two Excel pairs (which happen to be document-adjacent), not a faithful
implementation, and could misfire wherever document order and execution order diverge.

**Depends on:** none
**Files in scope:** `src/flowsmith/parser/process.py` (primary — the actual XML extraction),
`src/flowsmith/ast/builder.py` and `src/flowsmith/ast/models.py` (only to carry the newly-parsed
fields through `RawStage`→`BPStage` mapping — do **not** touch `_detect_vbo_call_fusions` or any
other fusion-detection logic here, that's Task 1b's job in its redo pass), `tests/parser/
test_process.py`, `tests/ast/test_builder.py`, `tests/ast/test_models.py`.
**Required reading:** `docs/reviews/1b-2026-08-29.md` in full (the exact evidence — grep results,
raw XML dump confirming the real `Create Instance`/`Open Excel` stages do carry the
`<outputs><output type="number" name="handle" stage="handle"/></outputs>` /
`<input type="number" name="handle" expr="[handle]"/>` shape §B_FUSION's worked example
describes), `docs/bp-to-pad-architecture-PID171.md` §B_FUSION, `CLAUDE.md`'s "Parser critical
rules" section (rules 4-5 on `onsuccess`/implicit Block→Recover edges — this task's edge capture
is the general-purpose version of what those rules already assume exists).

**Do:**
1. Add `<outputs>` parsing for `ACTION` stages in `parser/process.py`, populating `RawStage`
   (and, via the existing mapping logic, `BPStage.data_items`) with each output's `name`, `type`,
   and target (`stage` attribute) — the same shape `<inputs>` parsing already handles for other
   stage types, just currently missing for `ACTION`.
2. Additionally route `ACTION` `<input>` elements into `data_items` (not instead of
   `params_map` — VBO-call parameter substitution for Task 1/2b's `method_actions`/
   `fusion_patterns` templates still needs `params_map`; this is an additional exposure of the
   same input data in the shape structural/type-based scanning — like Task 1b's fusion
   pre-filter — needs to read).
3. Add `onsuccess`/`ontrue`/`onfalse` target-stage-ID capture on `RawStage`, populated from the
   BP XML's own `<onsuccess>`/`<ontrue>`/`<onfalse>` elements, and carry it through to `BPStage`
   in `ast/builder.py`. This is deliberately just the plain edge target(s) — not a full graph
   traversal, not the `WaitStart`/`WaitEnd`/`LoopStart`/`LoopEnd` bracket-pairing (that's a
   separate, already-existing mechanism via `<groupid>`/`<subsheetid>`, per `CLAUDE.md`, and is
   not in scope here) and not the implicit Block→Recover edge construction (`CLAUDE.md` rule 4 —
   also not in scope here, needed later but not by Task 1b).
4. Update `tests/parser/test_process.py` and `tests/ast/test_builder.py`/`test_models.py` to
   assert the new fields are populated correctly against real stages, not just synthetic fixtures
   — use the module-scoped `pid_0171_process`-style fixture already present in `tests/ast/
   test_builder.py` (the review noted this fixture already exists and is already used by 3 other
   tests, but wasn't used for the fusion tests) rather than adding a new one.

**Done when:** `uv run pytest tests/parser/ tests/ast/ -v` passes, including a new test asserting
that parsing `samples/blueprism/PID_0171.bprelease`'s `Read Excel As Collection` page produces a
`Create Instance` stage with a numeric `handle` output in `data_items` and an `Open Excel` (`Open
Workbook`) stage with a matching numeric `handle` input in `data_items` and an `onsuccess` edge
from `Create Instance` to `Open Excel`.

**Out of scope:** re-running or fixing Task 1b's `_detect_vbo_call_fusions` logic itself (a
follow-up implementation pass on Task 1b, after this task lands — Task 1b's own file scope and
detection logic don't need to change, only the data it now has available to read).

---

## Task 1b — `ast/builder.py`: VBO call-fusion detection pass

**Depends on:** Task 1, Task 1a
**Files in scope:** `src/flowsmith/ast/builder.py`, `src/flowsmith/ast/models.py`,
`tests/ast/test_builder.py`
**Required reading:** `docs/bp-to-pad-architecture-PID171.md` §B_FUSION in full (both the
worked Excel example and the generic structural-signal rule); `docs/reviews/1b-2026-08-29.md`
(the prior review — this is a re-implementation pass, know what was found wrong before starting).

**Do:**
1. Implement the **generic structural pre-filter** from §B_FUSION: for every pair of stages on the
   same page where stage N's `onsuccess` edge (now available on `BPStage`, per Task 1a — use it,
   not document/list order) targets stage N+1 with no other stage sharing that edge (i.e. a sole,
   unbranched target), and stage N has a numeric-typed `<output>` and stage N+1 has a same-named,
   same-typed numeric `<input>` whose `expr` references stage N's output (BP's `[handle]`-style
   reference, now available in `data_items` per Task 1a) — flag this pair as a **fusion
   candidate**, regardless of which VBO is involved and regardless of whether a curated pattern
   exists for it yet. This step needs no VBO-specific knowledge — it's a shape in the XML (see
   §B_FUSION's exact `<output>`/`<input>` example).
2. For each fusion candidate, check whether the two stages' VBO/method names match an entry in
   `mapping/vbo_catalogue.yaml`'s `fusion_patterns` for that VBO (via `mapper/vbo_router.py`'s new
   lookup from Task 1). If they match: mark the sequence as resolved-by-fusion on the AST (e.g. a
   `fused_with: list[stage_id]` / `fusion_action: str | None` field on `BPStage` in
   `ast/models.py`), attached to whichever stage the fused action should render at (the second/last
   stage in the sequence is the natural choice, matching where the real PAD call actually appears
   in `docs/pad-reference/DF_PID_171_US_LIMS_Prelude_Main.robin.txt`), and mark the vestigial
   stage(s) so the generator emits nothing standalone for them.
3. If a fusion candidate does **not** match any curated pattern: do not fuse it and do not
   translate the two stages independently as if the candidate signal didn't exist — attach a
   `ReviewFlag` naming both stage IDs, both method names, and the detected numeric-handoff variable
   name, so it surfaces as a concrete, curatable gap (per the earlier "rich flag, not a bare stub"
   discussion) rather than either a wrong guess or a silent miss.
4. This is structurally the same kind of problem `_assign_wait_loop_pairs`/`_assign_block_pairs`
   (or whatever this codebase's existing `WaitStart`/`WaitEnd` and `LoopStart`/`LoopEnd` pairing
   functions are actually named — check `ast/builder.py` directly rather than assuming) already
   solve — reuse that pass's general shape (a pre-pass over the page's stages before/alongside
   normalisation) rather than inventing a parallel mechanism.

**Done when:** `uv run pytest tests/ast/ -v` passes, including tests asserting: (a) the two known
Excel fusion pairs from `PID_0171.bprelease`'s `Read Excel As Collection` page — parsed via
`build_ast(parse_process(...))` against the **real sample file**, not hand-built `RawStage`
fixtures — are correctly detected and resolved to their fused actions; (b) a synthetic
numeric-handle-chaining pair with **no** matching `fusion_patterns` entry produces a `ReviewFlag`
naming both stages, not a silent per-stage translation. State explicitly in your summary whether
(a) was run against the real file or a fixture — do not omit this; the prior implementation pass
was marked down specifically for using only synthetic fixtures and not disclosing it.

**Out of scope:** generating the actual PAD output for a fused sequence (Task 5a/5b consume this
AST annotation, they don't need to re-detect fusion themselves).

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
   lists different, non-matching names). For the standalone methods (`Get Worksheet As
   Collection`, `Write to cell`, `Save As`), populate `method_actions` with their literal
   templates. For `Create Instance`/`Open Workbook` and `Close Workbook`/`Close Instance` — **do
   not** add these as two separate `method_actions` entries; per architecture doc §B_FUSION these
   are fusion pairs. Add two `fusion_patterns` entries instead:
   - `sequence: ["Create Instance", "Open Workbook"]`, `fused_action:` the
     `LaunchAndOpenUnderExistingProcess` template from `vbo-action-mapping.md`'s Excel table,
     `vestigial_stages: ["Create Instance"]`.
   - `sequence: ["Close Workbook", "Close Instance"]`, `fused_action:` the `Excel.CloseExcel.Close`
     template, `vestigial_stages: ["Close Workbook"]`.
7. For every entry you touch in this task, populate `method_actions`/`fusion_patterns` with
   literal PAD call templates copied verbatim from `docs/pad-reference/vbo-action-mapping.md` —
   never invent one. If you notice another BP method pair in this task's scope that looks like the
   same numeric-handle-chaining shape §B_FUSION describes (check any VBO you're adding/fixing, not
   just Excel), add it as a `fusion_patterns` entry too rather than two independent
   `method_actions` entries — note it in your summary either way so the reviewer can confirm.

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

**Depends on:** Task 1a, Task 3a, Task 3b
**Files in scope:** `src/flowsmith/ast/builder.py`, `src/flowsmith/ast/models.py`,
`tests/ast/test_builder.py`, `tests/ast/test_models.py`
**Required reading:** `docs/bp-to-pad-architecture-PID171.md` §B11 (the confirmed orphan-page
findings — `Mark leftout Items as Exception` and `Send Info to Data Gateways`, both have zero
callers, confirmed by a `<processid>` search against the BP XML) and §B16 (known-gaps list);
`docs/reviews/1b-2026-08-29.md` (why this task now depends on Task 1a — see below).

**Correction from an earlier draft of this task:** this task's step 1 used to say
`onsuccess`/`ontrue`/`onfalse` edges are "already resolved by the existing anchor-chain logic —
see `_build_anchor_map`/`_resolve_edge` if present" in `ast/builder.py`. That was wrong — those
functions exist in `scripts/bp_parser_v2.py` (a standalone diagnostic tool, not part of
`src/flowsmith`), and Task 1b's review confirmed by direct grep that `src/flowsmith/parser/
process.py`/`ast/builder.py` never captured `onsuccess` edges at all before Task 1a. Task 1a adds
this capture generally (not `SubSheet`/`Process`-type `processid` cross-references specifically —
that part of step 1 below is still this task's own job).

**Do:**
1. `ast/builder.py` currently builds one `BPProcess` per artefact with no cross-page edge/call
   graph at all. Add a reachability pass: starting from each page's `Start` stage, follow
   `onsuccess`/`ontrue`/`onfalse` edges (now available on `BPStage` per Task 1a — use them, do not
   re-derive edge data from document order) plus `SubSheet`/`Process`-type `ACTION` stages'
   `processid` cross-references to other pages, to determine which pages are actually reachable
   from the process's `Main Page`/entry point.
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

## Task 4b — `ast/builder.py`: Loader/Performer role tagging + Task 4a follow-up cleanup

**Depends on:** Task 4a
**Files in scope:** `src/flowsmith/ast/builder.py`, `src/flowsmith/ast/models.py`,
`src/flowsmith/parser/process.py`, `tests/ast/test_builder.py`, `tests/parser/test_process.py`,
`tests/parser/test_integration.py`, `tests/engine/test_flag_index.py`,
`tests/mapper/test_vbo_router.py`, `tests/generator/test_pad.py`,
`docs/bp-to-pad-architecture-PID171.md` (§B14 row 18 annotation only — see step 6)
**Required reading:** `docs/bp-to-pad-architecture-PID171.md` §B11 (the hard boundary at BP
stage `85fbb578`, `Get Next Item` on Main Page), §A3 (what a Loader vs. Performer body actually
looks like in the real PAD output), and §B14 (page-by-page crosswalk, row 18 `Close Down`);
`docs/reviews/4a-2026-08-30-final-fixpass.md` (the 6th and passing Task 4a review — its four
"most significant gaps"/recommendations are what steps 5-8 below close out).

**Do:**

*Role tagging (the task's original scope):*
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

*Task 4a follow-up cleanup (added after the 6th review cycle passed Task 4a at 95% — see
`docs/reviews/4a-2026-08-30-final-fixpass.md`'s "Most significant gaps"/recommendations):*

5. **Persist the Block→Recover pairing.** Task 4a's `_build_block_recover_map` in
   `ast/builder.py` is computed and discarded inside `_compute_reachability` — it's never attached
   to the AST, so this task (which already walks the same graph for role tagging) is the first
   natural consumer. Store the pairing on the model (e.g. a `recover_stage_id: str | None` field
   on the `BLOCK`-type `BPStage`, or an equivalent `BPPage`-level side-map in `ast/models.py`) so a
   later rendering task (`BLOCK`/`ON BLOCK ERROR` generation) can reuse it instead of
   re-deriving it from scratch. Raised in three of Task 4a's six review cycles — this is the last
   point in the pipeline before that reconstruction cost gets paid again downstream.
6. **`Close Down` orphan-status conflict — resolve, don't just re-flag.** Task 4a's reachability
   pass independently confirmed (via a `<processid>` search matching §B11/§B14's own methodology)
   that `Close Down` has zero callers anywhere in `PID_0171.bprelease` — but architecture doc §B14
   row 18 lists it as a normal, unflagged Performer page mapped to `Close Application`, with no
   **STOP** annotation like rows 16/21 carry. Update `docs/bp-to-pad-architecture-PID171.md` §B14
   row 18 to add a **STOP** annotation matching rows 16/21's format (cite the same
   `<processid>`-search method, and Task 4a's own reachability output as corroboration), so the doc
   and the code agree pending a process-owner decision on whether `Close Down` is genuinely dead
   code. Do not silently change the row's PAD-target mapping — only add the flag.
7. **Fix the `password`-typed data-item parser gap.** `parser/process.py` never maps an ACTION
   stage's `<inputs><input type="password" ...>` parameter type onto `BPDataItem.data_type` —
   confirmed via `tests/generator/test_pad.py::test_pid_0171_page_with_password_item_emits_sensitive`
   failing because zero password-typed `data_items` exist anywhere in the built AST, even though the
   string appears 33 times in `PID_0171.bprelease`'s raw XML as an input-parameter type. Add the
   capture (this is a genuine parser fix, not a stale test count — the `Sensitive` PAD directive
   this feeds is a real B-side requirement per CLAUDE.md's confidence/annotation model, not
   cosmetic).
8. **Reconcile stale hardcoded test counts.** Task 4a's fixes (main-page detection, `Process`-type
   normalisation, `MultipleCalculation` fan-out) shifted several real-sample totals that tests
   outside Task 4a's own file scope still assert the old values for. Update, against a single final
   full-suite run (not per-file, since Fix 2's MC-fanout ripple was previously under-reconciled by
   exactly this kind of partial update):
   - `tests/parser/test_integration.py`: `test_raw_page_count` (→19), `test_normalised_stage_count`
     (→796), `test_stage_type_counts[ACTION-174]` (→175), `test_stage_type_counts[CALCULATION-42]`
     (→113) — all against `PID_0127.bprelease` via `tests/conftest.py`'s `real_process` fixture.
   - `tests/engine/test_flag_index.py`'s 8 `test_real_*` assertions and
     `tests/mapper/test_vbo_router.py::TestIntegration::test_sample_routed_count_is_correct` — do
     **not** blindly update these to whatever the current run produces; the `vbo_router` one in
     particular traces back to Task 2b's `vbo_catalogue.yaml` rekey (commit `cd12585`), not this
     task's changes. Recompute each expected value from a fresh run and confirm by inspection it's
     explained by an already-understood cause before updating — don't paper over a real regression
     as a "stale count."
   - `tests/generator/test_pad.py::test_real_sample_generates_399_files` /
     `::test_real_sample_stub_count` — update the page/file-count baseline for the post-Task-3a
     artefact-isolation shrink (already documented in `docs/reviews/3a-2026-08-30-isolation-fixpass.md`).
     Leave `test_pid_0171_page_with_password_item_emits_sensitive` for step 7's actual fix, not a
     count update.

**Done when:** `uv run pytest tests/ast/ tests/parser/ -v` passes, including the new role-tagging
test (step 4) and the Block→Recover persistence being exercised by a test (step 5); `uv run pytest
tests/ -q` run once at the end shows no failures traceable to this task's own changes (pre-existing,
independently-explained failures outside this task's scope may remain — cite which, per step 8);
`docs/bp-to-pad-architecture-PID171.md` §B14 row 18 carries the new **STOP** annotation.

**Out of scope:** anything in `generator/` that consumes role tagging or the persisted Block→Recover
pairing (Tasks 5a/6a); resolving whether `Close Down` is actually dead code (a process-owner
decision — this task only makes the doc and the code stop disagreeing); any VBO/mapping fix beyond
reconciling the one `vbo_router` test count if it turns out to genuinely be stale (a deeper
`vbo_catalogue.yaml` audit is not this task's job).

---

## Task 5a — `generator/pad.py`: wire page-shape mapping into generation (rename/inline/fold/split)

**Depends on:** Task 4b
**Files in scope:** `src/flowsmith/generator/pad.py`, `templates/pad/subflow.robin.j2`,
`mapping/page_target_map.yaml` (already exists, uncommitted in the working tree — extend it, do
not rebuild it), `tests/generator/test_pad.py`
**Required reading:** `docs/bp-to-pad-architecture-PID171.md` §A3 (real Loader/Performer
`FUNCTION` structure), **§B10 (the "1 page → 1 `FUNCTION` is not the rule" correction)**, §B11
(Loader/Performer split, Main Page's mid-page split point), §B14 (page-by-page crosswalk — the
authoritative, cited source for every page's real PAD shape). Also read, in order, all five prior
review cycles on this exact task — `docs/reviews/5a-2026-08-30.md`, `5a-2026-08-31-fixpass.md`,
`5a-2026-08-31-secondfixpass.md`, `5a-2026-08-31-thirdfixpass.md`,
`5a-2026-08-31-fourthfixpass.md` (this last one graded the previous, single 7-Do-step version of
this task at 31%, *worse* than the 49% before it, precisely because that version was too large for
one implementer pass — see below).

**Why this task is being split, not just re-attempted a sixth time as one task:** the fourth
fix-pass review found `mapping/page_target_map.yaml` (built by that pass) genuinely good —
well-cited against §B14, correct on `Result Entry`'s 7-way split and every fold target checked.
But `generator/pad.py` never actually consumed most of it: `target_name`, `block_name`,
`container`, and `targets` are read nowhere in the generator (confirmed by grep), `inline_block`/
`split` are no-op stubs that fall through to plain `FUNCTION` rendering, `fold`-shaped pages'
content is dropped with **zero** trace (worse than before — previously every page at least
rendered as *some* `FUNCTION`), the exact Main-Page-split-by-role defect the task explicitly said
"must not recur" recurred byte-for-byte, and the coarse-`BLOCK`/`GOTO`/`LABEL` exception-dispatch
requirement (the single most heavily-specified new ask) was not attempted at all. Net result: 11
dangling `CALL`/`FUNCTION` references, worse than the 6 the immediately preceding cycle left. This
is the project's own "one small, scoped task at a time" rule being violated by the task prompt
itself, not an implementer failure to follow clear instructions — asking for mapping-file wiring,
4-way shape dispatch, `CALL` renaming, Main-Page-split-by-role, *and* a novel exception-dispatch
pattern in one pass gave a single Haiku implementer room to do the cheapest part well and skip the
rest. This task now covers only the mapping-consumption wiring; the exception-dispatch pattern is
its own task, Task 5c, below.

**Do not rebuild `mapping/page_target_map.yaml` from scratch** — it exists, uncommitted, in the
working tree, and the fourth fix-pass review confirmed its citations are sound. Only:
- Add the one missing entry it's missing (`Save Attachments`, §B14 row 3).
- Add process-scoping: the mapping is currently keyed by bare page name with no process
  qualifier, and independently confirmed to silently cross-apply to `PID_0127.bprelease` (which
  has same-named pages never curated for these shapes) via this task's own test fixtures. Scope
  every lookup to the specific process being generated (e.g. nest entries under a
  `PID_171_US_Process_LIMS_Prelude:` key, or check `process.name` before consulting the mapping at
  all) — do not let PID_171-specific curation silently apply to any other automation.
- Implement the `ReviewFlag`-on-uncited-page fallback Do-step 1 already specified in the original
  version of this task but that was never built (confirmed zero `ReviewFlag` usage in the prior
  pass's diff) — a reachable page with no mapping entry gets `function` shape named after the page,
  plus a flag, not a silent default.

**Do:**
1. Wire `target_name` into both `FUNCTION` declaration rendering (`_render_page_as_function`) and
   `CALL` resolution (`_resolve_call_target`) for every `shape: function` entry that has one — the
   9 real BP-page→renamed-`FUNCTION` pairs in §B14 (`Get Mails`→`Fetch Emails from Mailbox`,
   `Mark Item As Exception`→`Mark Exception`, etc.) must render/be called under the mapped name,
   not the raw BP page name. Also fix `templates/pad/subflow.robin.j2`'s unconditional `GLOBAL`
   qualifier — confirmed by the fourth fix-pass review that most Performer `FUNCTION`s in the real
   reference are *not* `GLOBAL`; only mark `GLOBAL` where the mapping entry (or the reference file)
   says so.
2. Implement `inline_block`: render the target page's stages into a `BLOCK '<block_name>'` inside
   the named `container` (the Loader/Performer main body, or another named `FUNCTION`) — not a
   separate `FUNCTION`. `Get Mails`/`Populate Queue` are the two concrete cases to verify against.
3. Implement `fold`: render the target page's stages directly into the named `container` with **no
   wrapper at all** — never silently drop them (the exact regression the fourth fix-pass review
   found: `DataGateway`/`Reset Global Data`/`Save Attachments` vanished with zero trace). If a
   `container` FUNCTION doesn't exist yet as a synthesized construct (e.g. `Process Work Queue
   Items` has no BP-page equivalent — see Task 5c), stub it clearly with a `# TODO` naming what
   still needs to land there, rather than silently dropping the fold target's content.
4. Implement `split`: divide the target page's stages across the `targets` list into that many
   separate `FUNCTION`s. If `page_target_map.yaml`'s current schema doesn't yet specify *where*
   each split boundary falls, add whatever field is needed (e.g. per-target stage-ID ranges or
   region markers) and cite §B14 row 6 (`Result Entry`'s 7-way split) for the ground truth.
5. Fix `_split_main_page_if_needed` to route each pre-split SubSheet call by *its own target's*
   role (via the mapping file/AST), not the caller's raw stage-list index. This is the fourth
   consecutive review to name this exact defect — 4 of Main Page's 5 pre-split SubSheet calls
   target performer-role pages and belong in the Performer file regardless of list position.
6. Correct, don't extend, the two existing regression tests. `test_call_function_correspondence_
   in_generated_files`'s `cross_role_loader_calls`/`folded_pages` allowlists and
   `test_five_critical_calls_appear_in_loader_for_pid171`'s Loader-placement assertions both encode
   defects from before this task's fixes as accepted baseline — **delete the allowlists and assert
   the actually-correct file/shape/target-name for each call**, per the mapping file. If something
   still dangles once steps 1-5 land, that is a real, reportable finding for your summary — not
   grounds for adding a new allowlist to keep these two tests green.
7. Pages tagged unreachable (Task 4a) are skipped entirely — not emitted as dead `FUNCTION`s.
8. Keep the existing `@@`/`@INPUT`/`@OUTPUT`/`IMPORT`/`@SENSITIVE` header logic, firing once per
   output file, `@INPUT`/`@OUTPUT` left empty with the existing `# TODO` marker when not derivable.

**Done when:** `uv run pytest tests/generator/test_pad.py -v` passes; a test asserts every unique
`CALL '<x>'` in each generated file has a matching `FUNCTION '<x>'` in that same file, with **zero
allowlist exceptions**; a test confirms Main Page's pre-split stages land in the file matching
their own target's role; generating from `PID_0171.bprelease`'s AST matches the reference shape
for at minimum: `Get Mails`/`Populate Queue` as inline `BLOCK`s (no `FUNCTION`), `DataGateway`/
`Reset Global Data`/`Save Attachments` present with no wrapper (not dropped), `Result Entry` as 7
named `FUNCTION`s, and the 9 renamed pages under their mapped names; a test confirms the mapping
lookup is scoped to PID_171 and does not alter output for `PID_0127.bprelease`.

**Out of scope:** the coarse-`BLOCK`/`GOTO`/`LABEL` exception-dispatch pattern (Task 5c — the
`container` FUNCTION a `fold` target points at may not exist as real rendered content until Task 5c
lands; stub it per step 3 above rather than block on it); real BP-expression translation inside
stage bodies (Task 5b); Cloud Flow consolidation (Task 6a); populating
`mapping/page_target_map.yaml` for any automation other than PID_171.

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

## Task 5c — `generator/pad.py`: coarse `BLOCK`/`ON BLOCK ERROR` exception-dispatch pattern

**Depends on:** Task 5a, Task 4b (persisted Block→Recover pairing)
**Files in scope:** `src/flowsmith/generator/pad.py`, templates involved in `BLOCK`/`RECOVER`
rendering, `tests/generator/test_pad.py`
**Required reading:** `docs/bp-to-pad-architecture-PID171.md` §A5 (the `BLOCK`/`ON BLOCK ERROR`
dispatch template and its hard constraint — **no `IF` inside a handler body**), §B15 (exception
bubbling across a call boundary and the worked `Mark Item As Exception` example — read this
section in full, it was written specifically for this task).

**Why this is its own task:** split out of the original Task 5a per the fourth fix-pass review —
it was that version's single most heavily-specified requirement (citing §A5, §B15, and a full
worked example) and the one thing not attempted at all across five review cycles so far. It's a
genuinely different kind of work from Task 5a's mapping/shape wiring (restructuring how exception
control-flow is rendered, not deciding which pages become which PAD construct) and deserves its
own focused implementation and review pass rather than competing for attention inside a larger
task.

**Do:**
1. For each page, use Task 4b's persisted Block→Recover pairing to place **one `BLOCK '<name>'`
   per real BP `Block` stage** — coarse-grained, covering every stage/`CALL` that `Block`'s scope
   actually covers in the source page. Never render a separate `BLOCK` around each individual
   `CALL` inside it.
2. Each `BLOCK`'s `ON BLOCK ERROR` handler must be a flat action sequence (status-flag `SET`s plus
   a `GOTO`) — per §A5's hard constraint, no `IF` inside the handler body. Any branching on what
   happened belongs in a plain `IF` placed after the enclosing scope.
3. Implement `GOTO`/`LABEL` dispatch to named continuation points, mirroring the source page's own
   `Recover`→`Resume` target — this is how control reaches `Mark Item As Exception`/
   `Mark Item As Completed`-equivalent sections after a handled error, not further BLOCK nesting.
4. Match the worked example exactly: `Process Work Queue Items` (the `container` Task 5a's `fold`
   entries for `Reset Global Data`/`DataGateway`/`Save Attachments`/etc. point at) wraps its entire
   per-item sequence in one coarse `BLOCK`; its handler sets `txt_ItemStatus` and falls through to
   `GOTO 'Mark Item as Exception'` / `LABEL 'Mark Item as Exception'`; `CALL 'Mark Exception'` lives
   under that `LABEL`, outside any `BLOCK`.
5. A call site with no enclosing `Block` on the source BP page gets no wrapping `BLOCK` — do not
   invent wrapping the source page doesn't have.

**Done when:** `uv run pytest tests/generator/test_pad.py -v` passes; a new test builds a small
synthetic page with a `Block`/`Recover`/`Resume` sequence and asserts the generated output has one
coarse `BLOCK`, a flat handler, and a `GOTO`/`LABEL` pair matching the source's Recover target —
not nested per-call `BLOCK`s; a test against the real `PID_0171.bprelease` sample confirms
`Process Work Queue Items`'s generated structure matches the worked example above (one outer
`BLOCK`, `GOTO 'Mark Item as Exception'` present, `CALL 'Mark Exception'` outside any `BLOCK`).

**Out of scope:** the page-shape/mapping-file wiring (Task 5a); real BP-expression translation
(Task 5b); anything about which pages get which PAD construct — this task only changes how
exception control-flow renders around content Task 5a already places correctly.

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

## Task 6a2 — `templates/cloudflow/orchestrator.json.j2`: close the §A2 structural gaps

**Depends on:** Task 6a
**Files in scope:** `templates/cloudflow/orchestrator.json.j2`, `src/flowsmith/generator/cloudflow.py`,
`tests/generator/test_cloudflow.py`
**Required reading:**
- `docs/bp-to-pad-architecture-PID171.md` §A2 (lines 59-152) — the narrative description of the
  4-catch-scope, `Respond`, and attended/unattended/cloud-desktop branching shape.
- `samples/pad/Shell_PP_PID_US_171_US_PreludeLIMS_V12_1_0_0_11_managed/Workflows/CF_PID_171_US_LIMS_Prelude_Cloud_Main-695D7A31-C74D-F111-BEC7-000D3ABE3BC4.json`
  — the **ground-truth JSON** for every structure named below. Every action name, `type`, and
  `runAfter` wiring below is copied directly from this file (verified 2026-09-01) — treat it as
  the literal source of truth over the narrative doc if the two ever seem to disagree on a detail.
- `docs/reviews/6a-2026-09-01-rereview-2.md` — the review that identified this gap (VBO/action
  fidelity 55%, "Do step 2 was never actually performed" across all 3 passes of Task 6a).

**Why this task exists:** Task 6a wired the orchestrator into the registration path but left the
orchestrator's own internal JSON structure as it was — a single generic `Catch:_Global_Error_Handler`
scope, no `Respond` action, and hardcoded `"runMode": "attended"` with no branching. The real
reference package's orchestrator has 4 separate catch scopes, a success `Respond`, and real
attended/unattended + cloud/desktop routing logic. This task closes that gap in the template only —
Task 6a's registration/consolidation logic is not touched here.

**Do:**

1. **Split the single `Catch:_Global_Error_Handler` into 4 scopes**, matching the reference file
   exactly:
   - `Catch:_Init` — `runAfter: {"Try:_Init": ["Failed", "TimedOut"]}`. Actions (in order): a
     `Compose` of the current datetime (`@formatDateTime(utcNow(), 'MM/dd/yyyy hh:mm:ss tt')`), a
     `SetVariable` on `Exception_Message` (coalesce the error message from `Try:_Init`'s own inner
     action outputs — reference uses
     `@coalesce(outputs('Run:_Load_Config_Data')?['body']?['error']?['message'], outputs('Parse_Run:_Load_Config_result_as_JSON')?['body']?['error']?['message'])`;
     adapt the referenced action names to whatever this template's own `Try:_Init` actions are
     named — `Compose:_Config`/`Set_Config_value` today), a `Compose` of `@workflow()`, a
     `Send_an_email_(V2)` (`shared_office365`/`SendEmailV2`), a `Terminate` action
     (`runStatus: "Failed"`, `runError: {"code": "Run a flow built with Power Automate for desktop Failed", "message": "@variables('Exception_Message')"}`),
     and a `Respond` action (`type: "Response"`, `kind: "PowerApp"`, `statusCode: 200`,
     `body: {"out_txt_mainflow_status": "@{variables('Exception_Message')}"}`,
     `operationOptions: "Asynchronous"`). For the email recipient: see step 4 below — do not
     hardcode a PID_171-specific parameter name.
   - `Catch:_Loader` — same shape, `runAfter: {"Try:_Loader": ["TimedOut", "Failed"]}`, action
     names suffixed `_Loader`/`Loader_Flow_Failure` per the reference file, email recipient
     `@variables('var')?['Mail_SystemExceptionTo']` (this one **is** already available in `var` by
     this point, unlike `Catch:_Init`).
   - `Catch:_Performer` — same shape, `runAfter: {"Try:_Performer": ["TimedOut", "Failed"]}`,
     action names suffixed `_Performer`/`Performer_Flow_Failure`, same email recipient pattern as
     `Catch:_Loader`.
   - `Catch:_Global_Error_Handler` — keep this scope, but it becomes the **outer safety net**,
     `runAfter: {"Catch:_Performer": ["Succeeded", "Failed", "TimedOut"], "Catch:_Init": ["Succeeded", "TimedOut", "Failed"], "Catch:_Loader": ["Succeeded", "TimedOut", "Failed"]}`
     (i.e. it always runs after the other three, regardless of their outcome — it's the final
     unconditional wrap, not itself gated on `Try:*` directly). Keep its existing
     `Filter_array`/`Set_Exception_Message`/`Get_workflow_details`/`Send_an_email_(V2)` actions as
     they are today (the reference adds a `Respond_to_a_Power_App_or_flow_-_Global_fail` here too
     — add one for parity, same `Response`/`kind: PowerApp` shape as the others).

2. **Add the success `Respond`**: inside `Try:_Performer`, after the existing
   `If_Performer_flag_=_yes`/`If_Work_Queue_Items_present` structure, add
   `Respond_to_a_Power_App_or_flow_-_Success` — `type: "Response"`, `kind: "PowerApp"`,
   `statusCode: 200`, `body: {"out_txt_mainflow_status": "Success"}`,
   `runAfter: {"If_Performer_flag_=_yes": ["Succeeded"]}` (adjust the referenced action name to
   whatever this template names its top-level Performer-flag `If` today), `operationOptions:
   "Asynchronous"`.

3. **Add attended/unattended and cloud/desktop branching**, replacing the current hardcoded
   `"runMode": "attended"` calls:
   - In `Try:_Loader`'s `If_Loader_flag_=_yes` true branch, nest an `If_Loader_type_=_Cloud`
     (`toLower(variables('var')?['Ctrl_LoaderType']) == 'cloud'`) — **true branch stays empty**
     (`"actions": {}`) with a comment explaining this is a config-selectable path with no PAD
     implementation yet (per architecture doc line 88-89 — "STOP if a real BP process ever needs
     this path"); **else branch** nests `If_Desktop_run_=_Unattended`
     (`toLower(variables('var')?['Ctrl_LoaderUnattendedRun']) == 'yes'`) → true branch calls
     `RunUIFlow_V2` with `runMode: "unattended"`, else branch calls it with `runMode: "attended"` —
     both branches otherwise identical to today's single hardcoded call (`uiFlowId`,
     `item/In_txt_Config`). Keep the existing `SetVariable Flow_Status = true` after the nested
     `If`s resolve.
   - In `Try:_Performer`'s `If_Work_Queue_Items_present` true branch, nest an
     `If_Performer_type_=_desktop` (`toLower(variables('var')?['Ctrl_PerfomerType']) == 'desktop'`)
     — true branch nests `If_performer_run_=_Unattended`
     (`toLower(variables('var')?['Ctrl_PerfomerUnattendedRun']) == 'yes'`) with the same
     unattended/attended `RunUIFlow_V2` split as the Loader; **else branch stays empty** with a
     comment (per architecture doc line 107 — non-desktop performer type has no PAD implementation
     yet, same placeholder pattern as the Loader's cloud path). Note: `Ctrl_PerfomerType` and
     `Ctrl_PerfomerUnattendedRun` are spelled exactly this way (missing the second "r" in
     "Performer") in the real reference JSON — preserve that spelling exactly, it is not a typo to
     fix.

4. **`Catch:_Init`'s email recipient**: the reference JSON hardcodes a PID_171-specific parameter
   (`parameters('EV_PID_171_US_LIMS_Prelude_Exception_Email (...)')`). Since this generator must
   stay generic across ~200 automations (not just PID_171), do not hardcode that literal name.
   Instead, in `cloudflow.py`, add logic that looks for an environment variable named
   `Generic_SupportTeam_EmailID` in `process.environment_variables` (this is exactly the variable
   architecture doc §A2 point 5's table describes as "Config-load-failure notification address" —
   the right semantic match for `Catch:_Init`, which fires before `var` is populated so
   `variables('var')?['Mail_SystemExceptionTo']` isn't available yet). If found, pass its resolved
   `parameters('<schema_name>')` expression to the template as a new render variable (e.g.
   `init_failure_email_expr`); if not found, fall back to a hardcoded placeholder string with a
   `# TODO` noting the automation has no config-load-failure notification env var and someone must
   supply a recipient before this flow is usable — do not silently emit an empty/broken `To` field.

5. Leave `Try:_Init`, the connection references, `parameters`, and `config_compose` sections
   unchanged — this task only touches catch/respond/branching structure.

**Done when:** `uv run pytest tests/generator/test_cloudflow.py -v` passes, and new tests assert,
against the rendered orchestrator JSON:
- exactly 4 top-level `Catch:*` `Scope` actions exist, each with the `runAfter` wiring specified
  above (in particular: `Catch:_Global_Error_Handler` depends on all 3 other catches, not on
  `Try:*` directly);
- `Try:_Performer` contains a `Response`-type action with `body.out_txt_mainflow_status ==
  "Success"`;
- `Try:_Loader` contains a nested `If` referencing `Ctrl_LoaderType` and another referencing
  `Ctrl_LoaderUnattendedRun`, with both an `unattended` and an `attended` `RunUIFlow_V2` call
  present;
- `Try:_Performer` contains a nested `If` referencing `Ctrl_PerfomerType` and another referencing
  `Ctrl_PerfomerUnattendedRun`, with both `unattended` and `attended` `RunUIFlow_V2` calls present;
- each of `Catch:_Init`/`Catch:_Loader`/`Catch:_Performer` contains one `Terminate`-type action and
  one `Response`-type action.

**Out of scope:** Task 6a's registration/consolidation wiring (already done); `packager.py` (Task
6b); replicating the reference file's exact branded email HTML bodies verbatim (structural
correctness — action types, names, wiring, and the dynamic expressions named above — is what's
graded; keep email bodies simple and non-branded, referencing `variables('Exception_Message')` and
`workflow()?['tags']['flowDisplayName']` as the reference does, but no HTML/CSS polish required).

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

## Task 6b2 — `generator/pad.py` disambiguation + `tests/e2e/test_pid171_pipeline.py` Category filter

**Depends on:** Task 6b
**Files in scope:** `src/flowsmith/generator/pad.py`, `tests/e2e/test_pid171_pipeline.py`
**Required reading:**
- `docs/reviews/6b-2026-09-01.md` and `docs/reviews/6b-2026-09-01-rereview.md` — the two gaps this
  task exists to close were identified and root-caused there; read both before starting.
- `mapping/page_target_map.yaml` lines ~123-134 — the real `target_name: "Move Emails"` entries
  that both "Mark as read mail" and "Mark as read and move to exception folder" carry, confirming
  that case is an *intentional*, mapping-declared fold, not a collision to disambiguate.

**Why this task exists:** Task 6b's own declared file scope (`packager.py`/`test_packager.py`)
could not reach either gap below — both live in files outside that scope. Same pattern as Task
6a → 6a2.

**Do:**

1. **`pad.py`'s duplicate-`FUNCTION`-name handling (lines 380-409)**: `seen_function_names` is a
   single flat set that silently `continue`s past *any* second page whose resolved `target_name`
   already appears — with no distinction between two different reasons a collision can happen:
   - **Intentional, mapping-declared fold** — `page_target_map.yaml` explicitly gives two (or
     more) BP pages the *same* `target_name` (e.g. the "Move Emails" case at lines 123-134,
     parameterized by `In_txt_DestinationFolder` per its own `notes:` field). This is correct,
     desired behavior — keep skipping the duplicate here, no suffix, no flag. Do not change this
     path.
   - **Accidental/undeclared collision** — `shape_info.get("target_name", page.name)` falls back
     to the raw (or `naming.py`-sanitised) page name because no `page_target_map.yaml` entry set
     `target_name` for that page, and it happens to coincide with another page's resolved name.
     This is the case documented as U2 in `SUBTASK8_VALIDATION_REPORT.md`, and the case Task 6b's
     Do-step 4 asked to fix: **do not silently skip** — append a disambiguation suffix (e.g.
     `'<name>_2'`, `'<name>_3'`, ...) so both pages' content is rendered as distinct `FUNCTION`s,
     and update any `CALL` sites that referenced the now-suffixed page's original name so they
     still resolve. Distinguish the two cases by checking whether the collision's `target_name`
     came from an explicit `page_target_map.yaml` entry (intentional fold — skip) or from the
     `page.name` fallback (accidental — disambiguate); do not use the "does it have a `notes:`
     field" heuristic, use the actual source of the `target_name` value.
   - Add a test (real PID_0171 data if it naturally reproduces an accidental collision after
     `naming.py` sanitisation; a small synthetic AST fixture otherwise) confirming: (a) the
     intentional "Move Emails" fold still renders exactly once with no suffix, and (b) an
     accidental collision renders both `FUNCTION`s with distinct suffixed names, not a silent
     drop.

2. **`tests/e2e/test_pid171_pipeline.py`'s `TestDefinitionContent._definitions()` (lines 168-173)**:
   decodes every registered `<Workflow>`'s `<Definition>` and hands it to assertions that are
   PAD-`.robin`-script-specific (`test_definitions_start_with_connection_string` line 183 —
   `@@ConnectionString:` prefix; `test_definitions_carry_import_statements` lines 185-189 —
   `IMPORT` lines; `test_definitions_wrap_body_in_a_function` lines 191-195 — `FUNCTION`/`END
   FUNCTION`). Since Task 6a2 the orchestrator is correctly registered as a `<Workflow>` too, but
   its `<Definition>` is Cloud Flow JSON, not PAD script, so these assertions fail against it.
   `workflow_builder.py` already sets `Category` to `6` for Desktop Flows (PAD script) and `5` for
   Cloud Flows (JSON) (confirmed at `workflow_builder.py` lines 182/196/293/919) — use that
   discriminator. Fix `_definitions()` (or add a parallel PAD-script-only variant, whichever reads
   more clearly given the rest of the test file's structure) to filter to `Category == "6"` before
   running these three PAD-specific assertions. Do not weaken or remove the assertions themselves
   — the goal is to stop applying them to the wrong workflow type, not to reduce what they check.
   Consider whether an equivalent Cloud-Flow-specific well-formedness check (e.g. the orchestrator's
   `<Definition>` JSON-decodes and contains a `"definition"` key) belongs alongside these, since the
   orchestrator's own well-formedness is currently unchecked by this test class.

**Done when:** `uv run pytest tests/generator/test_pad.py -v` and `uv run pytest
tests/e2e/test_pid171_pipeline.py -v` both pass with zero failures (the 3 previously-failing
`TestDefinitionContent` tests included), and a new `pad.py` test demonstrates both the
intentional-fold and accidental-collision paths behave differently as described above.

**Out of scope:** any other gap `tests/e2e/test_pid171_pipeline.py` surfaces beyond the 3 named
here (report it, don't fix it, if you find something new); Task 7's full formal acceptance pass.

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

---

**Task 7's own review** (`docs/reviews/7-2026-09-01.md`, 45%, "needs another implementation pass")
was the *first* full generated-solution-vs-full-reference-package comparison this session —
every prior review scored one task's own scoped diff. It found 8 concrete, cited gaps that no
per-task review could have caught individually. Independently re-confirmed against a fresh
regeneration on 2026-09-03 (after several more 5b/5c/6a/6b fix-passes had already landed) that all
8 are still present — this is not a stale finding. Gaps 1-4 are architecture-layer (they'll affect
every future automation in the ~200-program rollout, not just PID_171-specific content) and are
split into their own tasks below, each independently scoped per the lesson from Task 5a's history
(don't bundle reasoning-heavy work with mechanical work in one pass). Gaps 5-8 are smaller and
largely independent of each other's difficulty, bundled into one cleanup task.

## Task 7a — `mapping/vbo_catalogue.yaml`: wire WorkQueues `method_actions` templates

**Depends on:** Task 6b
**Files in scope:** `mapping/vbo_catalogue.yaml`, `src/flowsmith/generator/pad.py` (the
`WorkQueues` dispatch branch only), `tests/generator/test_pad.py`, `tests/mapper/test_vbo_router.py`
**Required reading:** `docs/pad-reference/vbo-action-mapping.md`'s Work Queues table (already has
real, cited PAD call templates for `Get Next Item`, `Mark Completed`, `Mark Exception` — 3 status
variants, `Update Status`); `mapping/vbo_catalogue.yaml`'s existing `clsWorkQueuesActions` entry
(cites this exact table in its own `notes` field already, per `docs/reviews/7-2026-09-01.md`'s
VBO/action fidelity finding).

**Do:**
1. Populate `method_actions` on `clsWorkQueuesActions`'s catalogue entry for `Get Next Item`,
   `Mark Completed`, `Mark Exception`, `Update Status` — the real syntax already exists in
   `vbo-action-mapping.md`, this is transcription with citation, not new research.
2. `Tag Item`/`Defer` correctly stay `# TODO` (the mapping doc's own row already says
   **STOP** — no direct call observed, `ReviewFlag`) — do not invent syntax for these two.
3. Wire `generator/pad.py`'s `WorkQueues` dispatch branch to actually consume `method_actions`
   (confirmed by the Task 7 review the catalogue entry has module/confidence/citation wired but no
   per-method template, so today's codegen has nothing to render even where the catalogue is
   otherwise correct).

**Done when:** regenerating `PID_0171.bprelease` shows zero `# TODO: WorkQueues.<action>` stubs for
the 4 documented actions (Tag Item/Defer TODOs remain, expected); a test asserts the real syntax
renders for at least `Get Next Item`.

**Out of scope:** any VBO other than `clsWorkQueuesActions`; the `GLOBAL.` qualification these
generated calls' output variables will need (Task 7b).

---

## Task 7b0 — every `FUNCTION` `GLOBAL`, with BP page inputs/outputs as `FUNCTION` parameters

**Depends on:** Task 6b
**Files in scope** (widened by the user on 2026-09-24 to include the parser/AST):
`src/flowsmith/parser/process.py`, `src/flowsmith/ast/models.py`, `src/flowsmith/ast/builder.py`,
`src/flowsmith/generator/pad.py` (`FUNCTION` header emission, `_render_call_or_inline` and the
page-call path, per-`FUNCTION` variable naming), `templates/pad/subflow.robin.j2`,
`mapping/page_target_map.yaml` (removing the `global:` field and stale parameter notes only),
`tests/parser/test_process.py`, `tests/ast/test_models.py`, `tests/ast/test_builder.py`,
`tests/generator/test_pad.py`
**Required reading:** `docs/bp-to-pad-architecture-PID171.md` §A3/§A4 (the `In_`/`Out_` parameter
convention: always capitalised `In_`/`Out_` plus the type-prefixed name); the reference headers and
calls cited below; `docs/reviews/7b0-2026-09-24.md` (first pass, `59fe817`, 45%: its gap list is
the work order for what carries over); `docs/reviews/7b-2026-09-24.md`.

**Decisions (user, 2026-09-24):**
- A `FUNCTION`'s PAD scope is a developer's choice with no Blue Prism equivalent. **Every generated
  `FUNCTION` is emitted as `GLOBAL`**, and the generator never works out scope. No variable gets a
  `GLOBAL.`/`global.` prefix. The per-page `global:` flag is gone (done in `59fe817`; keep it that
  way).
- **Keep the BP page pattern.** A BP page receives its inputs when called and returns its outputs,
  and the generated `FUNCTION` does the same through PAD `FUNCTION` parameters, which a `GLOBAL`
  `FUNCTION` can take. This **replaces** the first pass's shared-variable `SET` bindings around
  bare `CALL`s; remove those.
  - Header: `FUNCTION '<name>' GLOBAL In_<a>, In_<b>, OUTPUT Out_<c>`. The parameter list form is
    cited from reference L1226 (`FUNCTION 'Mark Exception' In_obj_WorkQueueItem, OUTPUT
    Out_obj_WorkQueueItem`) and `GLOBAL` placement from L219 (`FUNCTION 'Get Error' GLOBAL`). The
    user confirmed on 2026-09-24 that `GLOBAL` combined with parameters is valid PAD. A page with no
    inputs/outputs stays `FUNCTION '<name>' GLOBAL`.
  - Call: `CALL '<name>' In_<a>: <expr> Out_<c>=> <caller variable>`, cited from reference L438 and
    L1483. A call to a page with no inputs/outputs stays bare, `CALL '<name>'`.

**Where the data comes from.** Per `docs/reviews/7b0-2026-09-24.md` gap 3, the BP XML records, via
a `stage=` attribute, which data item each page Start/End parameter reads or writes, and which
caller data item each call-stage output feeds. Examples where the parameter name differs from the
data item: `ScreenShot path`→`File Path`, `Mail Items`→`Items`, `sheetName`→`SheetName`,
`Parameter_WorkSheet_Name`→`Config_Parameter_WorkSheet_Name`. `parser/process.py` (~L260-343)
currently drops it. Cite the exact XML shape from `samples/blueprism/PID_0171.bprelease` (quote a
line range); do not assume it.

**Do:**
1. **Parser/AST:** capture the `stage=` attribute on page Start/End parameters and on call-stage
   inputs/outputs, and carry it through the AST models/builder. Call-stage outputs must be stored
   separately from inputs; today `params_map` holds inputs only, and the review found an output
   lookup there could put an input's expression on the wrong side.
2. **Parameter naming:** a parameter is named from the data item it binds to (its `stage=`
   target), under the existing naming convention, prefixed `In_`/`Out_` (e.g. data item
   `File Path` → `In_txt_FilePath`). Use the same name in the header, in the `FUNCTION` body and at
   every call site.
3. **`FUNCTION` body:** inside the `FUNCTION`, references to a data item bound to a parameter render
   as the parameter name (as the reference does, e.g. `In_txt_ErrorMessage` in its bodies). Do
   **not** emit the initialising `SET` for those data items; this fixes the review's gap-5
   finding that bodies reset their inputs to `%SomeVar%` on entry. Other data items keep their
   initialisation. A data item that is only an output renders as its `Out_` name in the body (and
   is not re-initialised). If a data item is both an input and an output, the body uses the `In_`
   name and `SET Out_<x> TO In_<x>` is emitted before `END FUNCTION`.
   **Header syntax for multiple outputs:** repeat `OUTPUT` before each output parameter
   (`..., OUTPUT Out_a, OUTPUT Out_b`), as reference L232, L622, L1167.
   **Split pages (user decision, 2026-09-24):** only the entry `FUNCTION` of a `split` page carries
   the page's `In_`/`Out_` parameter list; the other sub-`FUNCTION`s are bare
   `FUNCTION '<name>' GLOBAL`. Because the page's End stage lands in the last sub-`FUNCTION` and the
   split call chain doesn't exist yet (Task 5a gap), the entry `FUNCTION` gets a `# TODO` stating
   that its `Out_` parameter(s) are not yet assigned, naming them. It must not be left silently
   unassigned.
4. **Call sites:** emit `CALL '<name>' In_<a>: <expr> ... Out_<c>=> <caller var>` for
   `function`- **and** `split`-shaped targets. `split` resolves to its entry `FUNCTION`; the review
   found `Result Entry`'s 7 inputs + 1 output dropped silently. Rules:
   - Unpack `_translate_bp_expression`'s `(expr, helper_actions)` result and emit helper actions
     before the `CALL`, following the Calculation path's pattern (the review found 36 tuple reprs
     at `pad.py` L1228-1231).
   - A BP input with no value is omitted from the `CALL`.
   - An unresolvable name or expression gets a `# TODO` naming the BP input/output and page; never
     a raw BP name with spaces, never a silent drop.
   - `inline_block`/`fold`/`stop` keep their current behaviour.
5. **Cleanup from the first pass:** remove the shared-variable binding `SET`s and
   `_render_page_call_bindings()`. Remove the leftover `is_global=False` at `pad.py` ~L276 (the
   legacy `generate_page` path must also emit `GLOBAL`), the dead `is_global` line (~L865), and the
   `is_global` conditional in `subflow.robin.j2`. Fix the stale `In_txt_DestinationFolder` note at
   `page_target_map.yaml` L126. BLOCK renders are unaffected.
6. **Clobber-risk report (report only, don't rename):** use Task 4a's call graph to list variables
   that are assigned in more than one `FUNCTION` where one calls the other (e.g. `txt_SampleID` at
   3 sites, `dtb_FinalProductCollection` re-created twice, per the review).
7. **Tests:**
   - parser test for `stage=` on Start/End params and call outputs;
   - builder/model tests that it reaches the AST;
   - generator tests on a synthetic process with non-PID_171 names, a 2-input/1-output page whose
     parameter names differ from their `stage=` data items, checking:
     - the header `FUNCTION 'X' GLOBAL In_..., In_..., OUTPUT Out_...`;
     - the body uses parameter names and has no input re-initialisation;
     - the call site `In_...: <expr> Out_...=> <var>` with no tuple repr;
     - helper actions come before the `CALL`;
     - a `split` target binds;
     - an unresolvable input yields a `# TODO`;
     - no `GLOBAL.` prefix appears.
8. **Data initialisation at the top of each body** (user decision, 2026-09-24, from
   `docs/reviews/7b0-2026-09-24-fixpass2.md` gap 2). BP Data/Collection stages are not part of a
   page's flow: their initial values apply when the page starts. So every initialising `SET` /
   `DataTable.Create()` for a page's (non-parameter-bound) data items is emitted at the **top** of
   that `FUNCTION` body (after the header, before any other action), and likewise at the top of the
   main body for the Main page. It is never emitted at the stage's position in the flow. This
   stops a caller's own initialisation from wiping a collection a `CALL` just returned (review
   examples: P143→P286 `dtb_FinalProductCollection`, P291→P292 `dtb_SammaryCollection`, Loader
   L109→L154 `dtb_MailItems`). Apply the same rule per sub-`FUNCTION` for `split` pages.
   **Inlined pages (`inline_block`/`fold`), option A (user decision, 2026-09-24, superseding the
   earlier "top of host body" wording that fix pass 3 implemented):** BP resets a page's data items
   every time that page runs, and an inlined page runs every time it's called. So each inlined copy
   of a page gets its own data initialisations at the **start of that inlined copy** (e.g. right
   after `# BEGIN fold` / at the top of the inlined `BLOCK` content), before any of its other
   actions, and never at the stage's flow position. Consequences:
   - a page inlined twice is initialised twice, once per copy;
   - `Reset Global Data` keeps its per-run resets (`docs/reviews/7b0-2026-09-24-fixpass3.md` gap 3).
   Only a data-item name declared by **both** the host page and the inlined page is initialised
   once, at the host body's top, and not repeated in the inlined copy. Scope rules:
   - hoisting only ever collects stages the current flow role actually renders (respect the
     Loader/Performer role filter);
   - never re-initialise a data item that is a flow `@INPUT` or one of the body's own
     `In_`/`Out_` parameters;
   - deduplicate identical initialisation lines within one body.
   **Clarifications (user decisions, 2026-09-24, from `docs/reviews/7b0-2026-09-24-fixpass4.md`):**
   - "Declared by both" is checked against **every** data item the host BP page declares, not only
     the subset/slice the current role or sub-`FUNCTION` renders. Such a shared name is initialised
     once at the host body's top (if the host body renders it at all) and **never** inside the
     inlined copy. When the host's own declaration isn't rendered in this body (e.g. it's on the
     other role's side), the inlined copy still doesn't re-initialise it.
   - An inlined page's own **Start-stage input** data items are never re-initialised in the
     inlined copy: BP applies the caller's input over the initial value.
   - Where "declared by both" suppresses a per-copy reset the inlined page relied on (e.g.
     `Retry Count` in both `Result Entry` and `Sample Manager - Explorer` → one PAD
     `num_RetryCount`), emit a `# TODO` at the start of that inlined copy naming the variable and
     that its per-run reset was suppressed because of a cross-page name collision (see Task 7b1).
9. **Split sub-`FUNCTION` input TODO** (user decision, 2026-09-24): where a non-entry split
   sub-`FUNCTION` would otherwise reference or re-initialise a data item that is one of the entry
   `FUNCTION`'s `In_` parameters, emit a `# TODO` naming the parameter(s) and that the split call
   chain doesn't yet pass them (Task 5a gap). Don't re-initialise them silently. This is the input
   twin of the entry `FUNCTION`'s `Out_` TODO.
10. **Unassigned `Out_` TODO** (user decision, 2026-09-24): in any `FUNCTION` (not just `split`
    entries), if a declared `Out_` parameter is never assigned in the rendered body, emit a
    `# TODO` before `END FUNCTION` naming it.
11. **Tests must fail on regression.** The fix-pass-2 suppression test (`test_pad.py` ~L3179) is
    vacuous: it asserts `SET txt_...` is absent, but a regression renders `SET In_txt_...`.
    Assert that no `SET In_<x> TO` / `SET Out_<x> TO %SomeVar%` / `DataTable.Create()` targets a
    bound name. Add tests for:
    - output-only `Out_` naming in the body;
    - collection (`DataTable.Create`) suppression;
    - init-at-top ordering: a collection returned by a `CALL` isn't re-created later in the caller;
    - the item-9 and item-10 TODOs.
    Mutation-check each: disable the behaviour and confirm the test fails, then restore.

**Done when:** regenerating `PID_0171.bprelease` shows:
- every `FUNCTION` in both `.robin` files is `GLOBAL`, with a parameter list matching its BP page's
  Start/End parameters;
- every call to a parameterised page passes `In_...:`/`Out_...=>` arguments, including `Send mail`'s
  6 inputs and `Result Entry`'s 7 inputs + 1 output;
- no `TO ('` tuple reprs, no shared-variable binding `SET`s, no input re-initialisation inside
  bodies, no `GLOBAL.` prefix, and no `is_global=False` in `src/`;
- the clobber-risk report is in the implementer's summary;
- `uv run pytest tests/parser tests/ast tests/generator -q` is green, and the full suite has no new
  failures beyond the 10 known PID_0127 ones.

**Out of scope:** `Mark Exception`'s consecutive-exception logic (Task 7b); renaming shared
variables (report only); the flow-level `@INPUT`/`@OUTPUT` contract (Task 7c).

---

## Task 7b1 — `generator/pad.py`: disambiguate cross-page data-item name collisions

**Depends on:** Task 7b0
**Files in scope:** `src/flowsmith/generator/pad.py` (variable naming / `variable_name_mapping`
construction only), `tests/generator/test_pad.py`
**Required reading:** `docs/bp-to-pad-architecture-PID171.md` §A4 (naming convention);
`docs/reviews/7b0-2026-09-24-fixpass4.md` (gap 2 and the decisions it prompted); the Task 7b0
section's item 8 clarifications.

**Why:** in BP every page has its own data-item namespace. After Task 7b0 every generated
`FUNCTION` is `GLOBAL`, and inlined (`inline_block`/`fold`) pages share their host's body, so two
BP data items with the same name on different pages collapse into one PAD variable. Example:
`Retry Count` is declared on both `Result Entry` and `Sample Manager - Explorer` and becomes one
`num_RetryCount`. As a stop-gap, Task 7b0 initialises such a name once at the host top and
`# TODO`-flags the lost per-copy reset. This task removes the collision.

**Do:**
1. Detect collisions from the AST, not from a name list: a data item name declared on more than
   one BP page whose generated code ends up in the same flow namespace (always, under all-`GLOBAL`),
   where the pages' declarations differ in role (e.g. one page is inlined into the other, or both
   independently initialise it).
   Exclude:
   - names that are deliberately shared: a caller's argument bound to the callee's `In_`/`Out_`
     parameter;
   - identical declarations that BP itself uses as a single shared value. **Stop and report** if
     you can't decide which case applies; don't guess.
2. Give the colliding inlined/secondary page's item a deterministic, page-qualified PAD name, e.g.
   a suffix derived from the page name under the §A4 convention. Report the exact scheme, justify
   it against §A4, and apply it consistently in initialisation, body references and TODOs.
3. With the collision removed, restore the inlined copy's own per-run reset (Task 7b0 item 8,
   option A) and drop the corresponding 7b0 collision `# TODO`.
4. Tests on a synthetic process (non-PID_171 names): two pages declaring the same data item, one
   inlined into the other; after renaming, the host's counter isn't reset by the inlined copy and
   the inlined copy resets its own. Mutation-check each test.

**Done when:** regenerating `PID_0171.bprelease` shows `Result Entry`'s and
`Sample Manager - Explorer`'s `Retry Count` as two distinct PAD variables, each inlined copy of
`Sample Manager - Explorer` resetting its own, and no 7b0 collision `# TODO` left for resolved
cases. Any remaining collisions are reported with a `# TODO`. No hardcoded names in `src/`. Tests
green, and no new full-suite failures beyond the 10 known PID_0127 ones.

**Out of scope:** renaming variables for style; the flow-level `@INPUT` contract (Task 7c).

---

## Task 7b — `generator/pad.py`: consecutive-exception dispatch completion (BP behaviour)

**Depends on:** Task 7b0
**Files in scope:** `src/flowsmith/generator/pad.py`, `tests/generator/test_pad.py`
**Required reading:** `docs/bp-to-pad-architecture-PID171.md` §A7 (BP ground truth for the
`Mark Item As Exception` page, traced from `PID_0171.bprelease`), §A5 (SUE re-throws and halts the
run), §A8 D4/D6 (how the deployed reference differs); the BP page itself as rendered in
`outputs/report/PID_0171_html_report_20260904/data/pid-171-us-process-lims-prelude.md`
(`## Page: Mark Item As Exception`, ~L940-1043); `docs/reviews/7b-2026-09-24.md` (why the first
attempt, `2701fc8`, was reverted in `8960ef8`).

**Decisions (user, 2026-09-24):**
- **Follow BP behaviour, not the deployed reference's.** Reproducing the reference's
  always-increment (§A8 D6) or its extra machinery is a defect, not fidelity.
- **Every generated `FUNCTION` is `GLOBAL`, with BP page inputs/outputs as parameters (Task 7b0),** so all variables below are referenced by
  bare name: no `GLOBAL.` prefix.
- **No dedicated exception-mail `FUNCTION`s (option A).** `Send Consecutive Exception Mail` and
  `Send System Exception Mail` are reference-only redesigns (reference L1096, L1026) with no BP page.
  In BP, a breach hits the `TERMINATE` exception stage, which throws `System Unavailable Exception`
  (message: `[Consecutive Exception Limit] & " consecutive incidents of " & [Exception Type] & ...`).
  That propagates to the Main page's error path, which sends the one generic system-exception mail
  (`Mail on System exception` → `MS Outlook Email VBO` `Send Email`) and halts (§A5). The generated
  flow does the same: the breach throws via the existing error path (Task 5c's `ON BLOCK ERROR`),
  with no `CALL` to a dedicated mail `FUNCTION`, no `flg_SendExceptionEmail` duplicate-mail
  disarm, and no `flg_HaltRun` flag (all three are reference-only mechanisms).

**BP semantics to reproduce (§A7):** `Mark Exception` (the VBO call) runs **before** the
consecutive check. On a plain System Exception, `Previous Exception?`
(`[Previous Exception Detail]=[Exception Detail]`) → *match*: `Count` (+1), then `Limit?` (`>=`
limit) → breach throws as above. *Mismatch*: `Reset Consecutive Exception Indicators` (previous
detail := current detail, count := 0), terminal for the item, with no fall-through to `Limit?`. The
count is reset to 0 on item completion (`Mark Item As Completed`) and on a Business Exception; SUE
neither resets nor increments. With limit 3, a breach needs 4 identical consecutive messages.

**Hard constraints (from the reverted attempt):**
- `Mark Exception`'s body is **translated from the BP page's actual stages** through the normal
  page→`FUNCTION` pipeline. No Python string body, no `if target_name == "Mark Exception"`
  special case. Stages not otherwise translatable get a `# TODO` naming them; none vanish (incl.
  `Release Item`/Defer, `Tag Item`, `Not Completed`, `Completed No Outcome`, both `TERMINATE`s).
- The queue-item status comes from the catalogue (`mapping/vbo_catalogue.yaml`
  `clsWorkQueuesActions.method_actions`), chosen from the BP exception-type branch the
  `Mark Exception` stage sits in: Business Exception branch → default `"Mark Exception"`
  (`BusinessException`); System Exception branch → `"Mark Exception :: GenericException"`
  (`vbo-action-mapping.md` L29, reference L1309). BP marks the item once, before the breach check,
  so there is **no** second status update to `ITException` on breach (that is reference-only,
  L1290). Leave `"Mark Exception :: ITException"` unused unless a BP branch genuinely maps to it,
  and report it if so. Never select a variant by stage-name or `Tag` heuristics (rejected in
  `docs/reviews/7a-2026-09-04-thirdpass.md`). Remove the
  `# VERIFY: Mark Exception status variant deferred to Task 7b` marker wherever the variant is now
  selected from real branch context; keep it wherever context isn't determinable.
- No PAD syntax without a line citation to the reference or architecture doc.

**Do:**
1. Render the BP page's `Previous Exception?` / `Count` / `Reset Consecutive Exception Indicators`
   / `Limit?` / `TERMINATE` stages to the BP semantics above. The `Limit?` `IF` contains the real
   breach condition, not `# VERIFY`. The breach throws `System Unavailable Exception` with the BP
   message expression, using the existing `ThrowCustomError` rendering.
2. Wire the counter's lifecycle: reset to 0 on item completion (the `Mark Complete` placeholder
   today) and in the Business Exception path. Flag (`# TODO`/`# VERIFY` with citation) the
   counter's initialisation and the limit's load from config if they belong to
   `Load Config Data` (not yet generated, Task 7d item 3).
3. Status variant selection per the hard constraint above (the Task 7a hand-off).
4. Tests that exercise behaviour, not string presence: simulate a sequence of System Exceptions
   (e.g. same/same/different/same/same/same messages) through the rendered logic's semantics and
   assert the count and the breach point per BP (limit 3 → breach on the 4th identical); assert that
   the breach renders a `System Unavailable Exception` throw and no dedicated-mail `CALL`; assert
   `BusinessException`/`GenericException` are each selected from the BP branch structure; replace
   `test_mark_exception_variant_selection_is_deferred_to_task_7b`.

**Done when:** regenerating `PID_0171.bprelease` shows the `Mark Exception` `FUNCTION` translated
from the BP page with reset-to-0/terminal-on-mismatch semantics and a `System Unavailable
Exception` throw on breach; no `Send Consecutive Exception Mail`/`Send System Exception Mail`
`FUNCTION` or `CALL`; no dropped stages without a `# TODO`; the sequence and variant-selection tests
pass; `Mark Exception` is a `GLOBAL` `FUNCTION` whose parameters and call sites follow Task 7b0; no hardcoded `Mark Exception` body in
`src/`.

**Out of scope:** making every `FUNCTION` `GLOBAL` (Task 7b0); Task 5c's `BLOCK`/`ON BLOCK ERROR`
structure (already done); generating `Load Config Data` (Task 7d item 3); translating `Tag Item`/
`Defer` (STOP per `vbo-action-mapping.md` L32, stays `# TODO`).

---

## Task 7c — `generator/pad.py`: match the reference's single-parameter `@INPUT` contract

**Depends on:** Task 6b
**Files in scope:** `src/flowsmith/generator/pad.py` (flow-header generation),
`templates/pad/flow_header.robin.j2`, `tests/generator/test_pad.py`
**Required reading:** `docs/bp-to-pad-architecture-PID171.md` §A4 (the `In_`/`Out_`-prefixed
single-JSON-blob interface); `docs/reviews/7-2026-09-01.md`'s Naming-convention finding (the real
orchestrator's `RunUIFlow_V2` call was decoded directly and confirmed to only ever send
`In_txt_Config` — the generated Desktop Flows' declared input surface doesn't match what will
actually be supplied at call time, not just a style mismatch).

**Do:** replace the current per-stage-VBO-parameter-union `@INPUT` collection (92 raw,
space-containing, unprefixed names in Loader; 111 in Performer — e.g. `Sender Mail ID`, `Queue
Name`, and one that carries a source typo through verbatim, `SystemException_Maiil ID`) with the
single `In_txt_Config` contract both reference files actually use.

**Done when:** regenerating `PID_0171.bprelease` shows exactly 1 `@INPUT` (`In_txt_Config`) per
generated file, matching the reference and the orchestrator's real call signature.

**Out of scope:** `@OUTPUT` (already correctly left empty with a `# TODO`, per Task 5a's Fix C);
the orchestrator's own Cloud Flow JSON (Task 7d).

---

## Task 7d — packaging/mapping/fallback cleanup (4 independent, small fixes)

**Depends on:** Task 6b
**Files in scope:** `src/flowsmith/cli/app.py`, `src/flowsmith/generator/packager.py`,
`mapping/page_target_map.yaml`, `src/flowsmith/generator/pad.py` (fallback-rendering paths only)
**Required reading:** `docs/bp-to-pad-architecture-PID171.md` §A1 (Cloud Flow content-storage
convention); `CLAUDE.md`'s "never silently drop a BP construct... leave a `# TODO` comment naming
what it was and why" rule; `docs/reviews/7-2026-09-01.md` gaps 5, 6, 7, 8.

**Do (4 independent items, no shared logic — implement and test each separately):**
1. **Orphan `Populate_Queue_cloudflow.json`** — `cli/app.py:58` still invokes the old per-page
   `CloudFlowGenerator.generate_process()` path alongside the new consolidated packaging path;
   `packager.py:222-225` blindly copies its output into the `.zip` wholesale, unreferenced by
   anything. Remove the old invocation — violates Task 6b's own "exactly the file counts" done
   condition.
2. **Orchestrator Cloud Flow content storage is inverted from the reference's documented
   convention** — real Logic-App JSON currently sits inline in `<Definition>`, while the
   `<JsonFileName>`-referenced companion file is a hollow `{"package": ""}` stub. Per §A1, Cloud
   Flows should carry no inline `<Definition>`, only a real `<JsonFileName>` payload — the reverse
   of the current output. Fix `packager.py`'s storage direction for Cloud Flow workflow entries
   specifically (Desktop Flow entries' inline `<Definition>` storage is correct and unaffected).
3. **Missing `Load Config Data` mapping entry** — present in the reference Loader (L213), has no
   entry anywhere in `mapping/page_target_map.yaml` and is silently missing from generated output,
   unlike the four legitimately-`stop`-shaped orphan pages (which are cited with reasons). Add the
   entry, citing the reference line.
4. **Fallback honesty for untranslated expressions** — when Task 5b's translator returns empty for
   a BP expression, `pad.py:1636`/`:1690`'s fallback currently emits either a commented-out unfilled
   template skeleton or a bare `%SomeVar%` placeholder, with only a confidence-band comment naming
   the *stage* — not a `# TODO` naming *why* it failed or *what BP expression* needs manual
   completion, per CLAUDE.md's rule. Change the fallback to emit
   `# TODO: could not translate BP expression '<raw expression>' on stage '<stage name>' — needs
   manual completion` instead of a placeholder that looks like it might already be real.

**Done when:** regenerating `PID_0171.bprelease`'s `.zip` contains no unreferenced Cloud Flow JSON
file; the orchestrator CF's `<Definition>`/`<JsonFileName>` storage matches the reference's
convention; `Load Config Data` `FUNCTION` is present; every remaining untranslated-expression
fallback line is a `# TODO` naming the source expression, not a bare placeholder value or an
unfilled template skeleton.

**Out of scope:** the underlying reasons expressions fail to translate in the first place (that's
Task 5b's/7a's/7b's job depending on which construct) — this task only fixes how the *failure* is
reported when it does happen.

---

## Task 8 — `reporter/`: developer-facing AUTO/SPOT-CHECK/MANUAL coverage report

**Why this task exists (context, not part of the PID_171 output itself):** PID_171 is the pilot
that builds this tool's core capability, but the tool's actual purpose is a ~200-automation
migration program where each developer needs a fast, trustworthy answer to "what can I trust,
what needs a quick check, what do I need to actually build (usually UI selectors)" — without
reading the whole generated flow. `engine/scorer.py` and `engine/flag_index.py` already compute
everything this needs; they're just never wired to output. This task closes that gap. Elevated
from the strategy doc's original "Not Useful (empty) — later nice-to-have" classification once
the ~200-automation throughput context made it clear a report is required infrastructure, not an
optional extra.

**Depends on:** Task 7 (needs a real generated output to report on)
**Files in scope:** `src/flowsmith/reporter/` (currently empty), `src/flowsmith/cli/app.py`
(wire the `report` command, currently a stub), `templates/report/` (a new report template, not
to be confused with the existing `customizations.xml`/`solution.xml` packaging templates in the
same directory — use a subfolder or distinct naming to avoid confusion), `tests/reporter/` (new).
**Required reading:** `CLAUDE.md`'s confidence-band table, `src/flowsmith/engine/scorer.py` and
`engine/flag_index.py` (read both fully — this task consumes their existing output, it doesn't
recompute anything), the "rich `ReviewFlag`, not a bare stub" discussion (this session's
conversation — no doc citation exists yet for this specific point, use your own judgment on
format, guided by the goal: a developer or an agent doing later curation should be able to act on
a flag without re-deriving context).

**Do:**
1. Build a report generator (`reporter/generate_report()` or similar) that takes an annotated
   `BPProcess` (post-`engine.annotate_process()`) and produces a per-stage breakdown grouped by
   confidence band (AUTO / SPOT-CHECK / PARTIAL / MANUAL, per `CLAUDE.md`'s table), with counts and
   percentages per band, and a list of every `ReviewFlag` with severity.
2. For each `ReviewFlag`, the report entry must be **hand-off-ready**: the BP stage's page, name,
   narrative, inputs/outputs (with types), the VBO/method involved if any, and the reason it was
   flagged (UI-selector-required, no confident mapping, fusion-candidate-with-no-curated-pattern
   per Task 1b, etc.) — enough that a human or a later curation pass can act on it without opening
   the BP source themselves.
3. Emit at least one human-readable format (HTML or Markdown — `CLAUDE.md` says "Rich terminal +
   HTML report generation" was the original intent for this module, keep that unless you find a
   reason not to) and wire it to `uv run flowsmith report --input <ast-or-zip> --output <path>` in
   `cli/app.py`, replacing the current stub.
4. Do not touch `engine/scorer.py`/`engine/flag_index.py`'s own logic unless you find them
   genuinely wrong for this purpose — they're already built and tested; this task's job is
   presentation/wiring, not recomputation.

**Done when:** `uv run pytest tests/reporter/ -v` passes, and running `uv run flowsmith report`
against `outputs/generated/PID_0171/`'s AST produces a report a developer could act on without
reading the raw generated `.robin`/JSON files.

**Out of scope:** changing what gets flagged or how confidence is scored (that's `engine/`'s job,
already done); this task only presents what's already computed.

---

## Task 9 — Calibration checkpoint: validate against a second automation before team rollout

**Why this task exists:** every task above proves the tool works for PID_171 specifically. Before
committing a team to a 20-automations/month cadence across all ~200, the coverage claim needs to
be checked against at least one *different* automation — otherwise "60-80% coverage" is an
assumption carried over from a single pilot, not a measured number. `samples/blueprism/
PID_0127.bprelease` is already in this repo (it's what `mapping/stage_rules.yaml` and
`mapping/vbo_catalogue.yaml` were originally generated from, before this session's PID_171-specific
corrections) — no new sample-gathering is needed to run this checkpoint once.

**Depends on:** Task 8
**Files in scope:** none required (this is a run + measure + report task, like Task 7) — but
expect it to *produce* new findings that become follow-up tasks (new `ReviewFlag`s needing
curation, possibly new fusion patterns per §B_FUSION) rather than being a clean pass on the first
try. That's the point of running it now rather than discovering the gap mid-rollout.
**Required reading:** `docs/bp-to-pad-implementation-strategy-PID171.md` §4 (same scoring
methodology as PID_171's own review), `docs/bp-to-pad-architecture-PID171.md` §B_FUSION.

**Do:**
1. Run `uv run flowsmith convert --input samples/blueprism/PID_0127.bprelease --output
   outputs/generated/PID_0127/ --managed`, then `uv run flowsmith report` (Task 8) against it.
2. Compare the AUTO-band coverage percentage against PID_171's. Note which VBOs/patterns PID_0127
   shares with PID_171 (where curated coverage should transfer directly) versus which are novel to
   PID_0127 (where it won't — this is expected, not a failure, per the "custom VBOs never
   generalize" point from the business-context discussion).
3. For every new `ReviewFlag` PID_0127 surfaces that represents a **shared/common BP VBO** (not a
   process-specific custom one), treat it as a real gap in the pilot's coverage claim — file it as
   a follow-up curation task (extend `vbo_catalogue.yaml`/`stage_rules.yaml`/`fusion_patterns`
   the same way Tasks 2a-2c did) rather than accepting a lower number for PID_0127 alone.
4. Write a short comparison note (where — `docs/reviews/` fits, or a dedicated
   `docs/calibration/PID_0127-<date>.md`, your call, but don't lose it) covering: PID_171's AUTO %
   vs. PID_0127's, which gaps are shared-VBO (actionable) vs. process-specific (expected, not
   actionable), and a revised coverage estimate for the general tool now backed by two data points
   instead of one.

**Done when:** the comparison note exists and states plainly whether the tool is ready for
team-wide rollout at the claimed coverage level, or what specifically needs curating first — not a
vague "looks fine."

**Out of scope:** fixing every gap PID_0127 surfaces within this task itself — file them as
follow-up tasks per step 3, don't silently scope-creep this checkpoint into another full
implementation pass.
