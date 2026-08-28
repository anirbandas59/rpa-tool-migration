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
