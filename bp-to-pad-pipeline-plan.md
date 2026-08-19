# BP-to-PAD Pipeline Implementation Plan
# For Claude Code to implement — do NOT execute these steps yourself

## Status legend
- `[ ] pending` — not started
- `[x] done` — completed and validated

---

## 1. Executive Summary

### Current State
Flowsmith has a working end-to-end skeleton pipeline:

```
.bprelease → parse_process() → build_ast() → annotate_process()
           → PADGenerator → CloudFlowGenerator → WorkflowBuilder → SolutionPackager → .zip
```

The pipeline produces a `.zip` with `solution.xml`, `customizations.xml`, and `.robin` content in
`<Definition>`. However, the output diverges from the real-world target
(`samples/pad/Shell_PP_PID_US_171_US_PreludeLIMS_V12_1_0_0_2_managed/`) in many ways.

### Target State
Running `flowsmith convert --input samples/blueprism/PID_0171.bprelease --output output/`
should produce files that structurally and semantically match the reference managed solution
under `samples/pad/Shell_PP_PID_US_171_US_PreludeLIMS_V12_1_0_0_2_managed/`, specifically:

1. `solution.xml` — with correct GUID-based RootComponents and managed=1 option
2. `customizations.xml` — with correct per-Workflow metadata, Metadata JSON flags,
   Inputs/Outputs schema, Claims, ConnectionReferences, and `<Definition>` content
3. `Workflows/CF_PID_171_US_LIMS_Prelude_Cloud_Main-*.json` — Cloud Flow orchestrator JSON

### Scope of Changes
Five layers require coordinated changes, in this order:
1. Parser (`process.py`) — 12 missing extraction fields
2. AST models (`models.py`, `builder.py`) — 10 new/updated fields
3. Annotator (`annotator.py`) — smarter dispatch for new fields
4. PAD generator (`pad.py` + templates) — structural Robin constructs missing
5. Packager/WorkflowBuilder (`packager.py`, `workflow_builder.py`, templates) — XML/JSON metadata gaps

---

## 2. Repository Map (Files Relevant to This Plan)

### Source files to modify
| File | Role |
|------|------|
| `src/flowsmith/parser/process.py` | XML → RawProcess dict |
| `src/flowsmith/ast/builder.py` | RawProcess → BPProcess (normalisation) |
| `src/flowsmith/ast/models.py` | Pydantic models — BPStage, BPPage, BPDataItem |
| `src/flowsmith/engine/annotator.py` | BPStage → PAAnnotation dispatch |
| `src/flowsmith/generator/pad.py` | BPProcess → .robin files |
| `src/flowsmith/generator/cloudflow.py` | BPProcess → Cloud Flow JSON |
| `src/flowsmith/generator/workflow_builder.py` | BPPage → Workflow XML element dict |
| `src/flowsmith/generator/packager.py` | Assemble .zip package |
| `mapping/stage_rules.yaml` | Stage type → PA target rules |

### Templates to update
| File | Produces |
|------|----------|
| `templates/report/customizations_workflows.xml.j2` | `customizations.xml` |
| `templates/report/solution_with_guids.xml.j2` | `solution.xml` |
| `templates/pad/flow_header.robin.j2` | .robin header (@@/IMPORT/@SENSITIVE) |
| `templates/pad/subflow.robin.j2` | FUNCTION ... END FUNCTION wrapper |
| `templates/pad/actions/work_queues.robin.j2` | WorkQueues.* PAD actions |

### Reference truth files
| File | Contains |
|------|----------|
| `samples/pad/Shell_PP_PID_US_171_US_PreludeLIMS_V12_1_0_0_2_managed/customizations.xml` | Exact expected XML with real Workflow elements |
| `samples/pad/Shell_PP_PID_US_171_US_PreludeLIMS_V12_1_0_0_2_managed/solution.xml` | Exact expected solution manifest |
| `samples/pad/Shell_PP_PID_US_171_US_PreludeLIMS_V12_1_0_0_2_managed/Workflows/CF_*.json` | Exact expected Cloud Flow JSON |
| `samples/pad/fixed/PID171_loader_fixed.txt` | Expected .robin for Loader desktop flow |
| `samples/pad/fixed/PID171_performer_fixed.txt` | Expected .robin for Performer desktop flow |

### Tests to run after each sub-task
```
uv run pytest tests/ -v
uv run pytest tests/parser/ -v
uv run pytest tests/ast/ -v
uv run pytest tests/generator/ -v
uv run ruff check src/ tests/
```

---

## 3. Current Transformation Pipeline

```
samples/blueprism/PID_0171.bprelease
        │
        ▼ parse_process(path)                   [src/flowsmith/parser/process.py:364]
        │  - etree.parse() with lxml
        │  - Handles <bpr:release><bpr:contents><process> wrapper
        │  - Iterates root.iter() for all <stage> elements
        │  - Calls _parse_stage() per stage → RawStage TypedDict
        │  - Calls _parse_page() per <subsheet> → RawPage TypedDict
        │  - Calls _parse_environment_variables() → list[dict]
        │
        ▼ RawProcess TypedDict                  [src/flowsmith/ast/builder.py:76-84]
        │  {process_id, name, version, pages: [RawPage], environment_variables, source_file}
        │
        ▼ build_ast(raw)                        [src/flowsmith/ast/builder.py:480]
        │  - _normalise_stages() — SKIP/NORMALISE/DIRECT_MAP dispatch
        │  - _assign_wait_loop_pairs() — bracket matching by shared subsheetid
        │  - _assign_block_pairs() — Block pairing by name encounter order
        │  - _build_page() — wraps normalised stages into BPPage
        │  - Returns BPProcess (Pydantic, frozen except BPStage.pa_annotation)
        │
        ▼ BPProcess                             [src/flowsmith/ast/models.py:357]
        │
        ▼ create_annotator().annotate_process() [src/flowsmith/engine/annotator.py:53]
        │  - Loads mapping/stage_rules.yaml + mapping/vbo_catalogue.yaml
        │  - Per stage: dispatch on stage_type → PAAnnotation
        │    ACTION → VBORouter.route_stage() → catalogue lookup
        │    DATA/COLLECTION/CODE → hardcoded annotators
        │    others → stage_rules.yaml lookup
        │
        ▼ BPProcess (all stages have pa_annotation)
        │
        ├── PADGenerator().generate_process()   [src/flowsmith/generator/pad.py:48]
        │     Per page → generate_page() → Jinja2 render of subflow.robin.j2
        │     Per stage → _render_stage() → dispatch on band + target_type
        │     Output: output/robin/{page_name}.robin files
        │
        ├── CloudFlowGenerator().generate_process() [src/flowsmith/generator/cloudflow.py:50]
        │     Per page → generate_page() → try/catch scope dict
        │     Output: output/cloudflow/{page_name}.json files
        │
        ▼ SolutionPackager().package()          [src/flowsmith/generator/packager.py:55]
          - WorkflowBuilder.build_workflow() per page
              → reads .robin file → escape → "definition" field
              → _build_inputs_schema(), _build_outputs_schema()
              → _build_dependencies(), _build_connection_references()
              → _build_metadata(), _build_claims()
              → returns workflow dict
          - Renders templates:
              solution_with_guids.xml.j2 → solution.xml
              customizations_workflows.xml.j2 → customizations.xml
              content_types.xml.j2 → [Content_Types].xml
              environmentvariabledefinition.xml.j2 → per env var
          - Writes .zip:
              solution.xml, customizations.xml, [Content_Types].xml
              Workflows/*.json, Other/*.json
              environmentvariabledefinitions/*/*.xml
```

---

## 4. Source-to-Target Mapping

### Confirmed mappings (directly evidenced)

| Blue Prism Source | Existing Transformation | PAD Target |
|---|---|---|
| `<bpr:release><bpr:contents><process @id @name>` | `parse_process()` extracts process_id, name | `Workflow.WorkflowId`, `Workflow.Name` |
| `<process @version>` | `parse_process()` stores version | `Workflow.IntroducedVersion` |
| `<subsheet @subsheetid @name>` | `_parse_page()` → BPPage | One Workflow element per page in customizations.xml |
| `<stage @stageid @type @name>` | `_parse_stage()` → RawStage | .robin FUNCTION body actions |
| `<resource @object @action>` | Stored as params_map["_vbo_object"], params_map["_vbo_action"] | PAD module action call |
| `<inputs><input @name @type @expr>` | `_parse_stage()` → input_params list | .robin action parameters |
| `<outputs><output @name @type @stage>` | `_parse_stage()` → output_params list | .robin `=>` capture variables |
| `<onsuccess>`, `<ontrue>`, `<onfalse>` | `_extract_edges()` → BPEdge list | Control flow (CALL, IF, GOTO) |
| `<environment-variable @name @type @value>` | `_parse_environment_variables()` | `environmentvariabledefinitions/*/environmentvariabledefinition.xml` |
| `<datatype>` text child of Data stage | `_parse_stage()` RawDataItem.data_type | @INPUT / @OUTPUT type annotation |
| BP process Start inputs | `build_ast()` data_items with is_input=True | `<Inputs>` JSON schema in customizations.xml |
| BP process End outputs | `build_ast()` data_items with is_output=True | `<Outputs>` JSON schema in customizations.xml |
| BPPage name | `WorkflowBuilder._escape_definition()` | `<Definition>` embedded .robin content |
| Annotated stage target_module | `_build_dependencies()` | `<Dependencies>.requiredBinaries[]` |

### Gaps (evidenced differences between current output and reference)

| Blue Prism Source | Current State | Required PAD Target | Evidence |
|---|---|---|---|
| `<decision @expression>` | NOT extracted | Used in condition robin output | Real .robin has `IF expr THEN` |
| `<code>` text content | NOT extracted | MANUAL stub should include original VBScript | PID171 performer has Code stages |
| `<narrative>` per stage | NOT extracted | Stage comments in .robin | Reference .robin has `# ` comments from narratives |
| `<initialvalue>` for Data stages | NOT extracted (always None) | SET var TO initial_value | Real .robin: `SET txt_Var TO $'''%''%'''` |
| `<timeout>` for WaitStart | NOT extracted | WAIT … FOR num | Real .robin: `WAIT (…) FOR num_Delay_M` |
| `<groupid>` for loop/wait brackets | NOT extracted | Correct bracket pairing | builder uses subsheetid; group_id is the correct matcher |
| `<exception @detail>` | NOT extracted (only @type) | `FlowControl.ThrowCustomError … CustomErrorMessage: expr` | Real .robin has detail expression |
| `<exception @usecurrent>` | NOT extracted | `THROW ERROR` vs explicit throw | PID171 has usecurrent="yes" stages |
| `<input @friendlyname>` | NOT extracted | @INPUT FriendlyName parameter | customizations.xml Inputs schema has "FriendlyName" |
| `<steps><calculation>` fan-out | Parser gets them but builder doesn't produce N stages | N `SET` statements in .robin | builder.py _normalise_stages() MultipleCalculation handling is incomplete |
| `<subsheet @published>` | NOT extracted | Determines which pages become Workflows | customizations.xml only has published pages |
| BLOCK/ON BLOCK ERROR pattern | NOT generated | `BLOCK … ON BLOCK ERROR … END` in .robin | PID171_loader_fixed.txt lines 40–57 |
| FUNCTION/END FUNCTION | Generated as FUNCTION via subflow.robin.j2 | Correct — but body structure wrong | subflow.robin.j2 produces basic wrapper |
| LABEL / GOTO | NOT generated | `LABEL 'name'` / `GOTO 'name'` | PID171_loader_fixed.txt lines 161–165 |
| `<Metadata>` JSON flags | All flags hardcoded False | `containsActiveWorkQueuesActions: true` | customizations.xml line 53 |
| `<Claims>` | Only `[{"name":"selfheal"}]` | Claims derived from process stage types | customizations.xml line 60 |
| `<UIFlowType>` | Always 2 (desktop) | 2 for desktop, absent for cloud | CF workflows in customizations.xml have no UIFlowType |
| `<Category>` | Always 6 (desktop) | 6=desktop, 5=cloud | CF workflow: Category=5, DF workflow: Category=6 |
| solution.xml `<Managed>` | 0 (unmanaged) | 1 (managed) for PID_0171 reference | solution.xml line 9 |
| solution.xml `<Publisher>` | Only UniqueName | Full Publisher block with CustomizationPrefix, addresses | solution.xml lines 10–78 |
| solution.xml `<MissingDependencies>` | NOT generated | workqueueitem dependency declaration | solution.xml lines 85–92 |
| .robin Definition header | Missing IMPORT statements | `IMPORT 'controlRepo.appmask' AS appmask` | customizations.xml line 58 Definition content |
| .robin @SENSITIVE | NOT generated | `@SENSITIVE: [var1, var2, ...]` | customizations.xml Definition |

---

## 5. Sub-Tasks

---

### Sub-Task 1 — Parser: Extract 9 Missing Fields from `_parse_stage()`
**Status:** `[ ] pending`

**Intent:**
The parser currently misses decision expressions, code body text, stage narratives,
initial values, timeout/groupid for wait/loop brackets, exception detail/usecurrent,
and friendlyname attributes. These are all needed by later pipeline stages.

**Expected Outcomes:**
- `_parse_stage()` returns all 9 additional fields in the RawStage TypedDict
- `_parse_page()` captures the `published` flag from subsheet elements
- No existing tests break

**Todo List:**
1. In `src/flowsmith/ast/builder.py`, extend the `RawStage` TypedDict (lines 44–56) with:
   - `decision_expression: str | None`
   - `code_text: str | None`
   - `narrative: str | None`
   - `initial_value: str | None`
   - `timeout_seconds: int | None`
   - `group_id: str | None`
   - `exception_detail: str | None`
   - `exception_usecurrent: bool`
   - `friendlyname_inputs: list[dict]` (or add friendlyname to existing input dict structure)

2. In `src/flowsmith/ast/builder.py`, extend `RawPage` TypedDict with `published: bool`.

3. In `src/flowsmith/parser/process.py:_parse_stage()` (lines 125–289):
   - After existing `dec_el` check at line 153 (in `_parse_stage`): add `<decision>` expression extraction
     `dec_el = stage_elem.find(_ns("decision")); if dec_el: decision_expression = dec_el.get("expression")`
   - After existing exception_type extraction (line 188–194): add `exception_detail` and `exception_usecurrent`
   - Add narrative extraction: `narrative = _txt_child(stage_elem, "narrative")` or use `findtext`
   - For Data stages: extract `<initialvalue>` text (already has `<datatype>` extraction pattern)
   - Add `<timeout>` extraction: `timeout_el = stage_elem.find(_ns("timeout"))` → int or None
   - Add `<groupid>` extraction: `groupid_el = stage_elem.find(_ns("groupid"))` → str or None
   - Add `<code>` extraction: `code_el = stage_elem.find(_ns("code"))` → str or None
   - Add `friendlyname` to the existing input_params parsing loop (lines 205–220): `inp.get("friendlyname", "")`

4. In `src/flowsmith/parser/process.py:_parse_page()` (lines 323–361):
   - Extract `published` from subsheet_elem attribute: `published = subsheet_elem.get("published", "false").lower() == "true"`
   - Include in returned `RawPage`

5. Also add pre-pass anchor chain resolution (from `scripts/bp_parser_v2._build_anchor_map()`):
   - Before `_parse_stage()` calls, collect all Anchor stages and build `anchor_map`
   - In `_extract_edges()`, resolve targets through `anchor_map` before adding to edges list
   - This prevents dead edges pointing to Anchor nodes

**Relevant Context:**
- Pattern for namespace-aware child extraction: `stage_elem.find(_ns("decision"))` or `stage_elem.find("decision")`
- The `_txt_child` helper equivalent in process.py uses `stage_elem.findtext(_ns("tag")) or ""`
- Reference: `scripts/bp_parser_v2.py:113–249` has the complete extraction already implemented
- Target TypedDict is in `src/flowsmith/ast/builder.py:34–84`

**Validation:**
- Run `uv run pytest tests/parser/ -v`
- Add test: parse `samples/blueprism/PID_0171.bprelease` and assert that RawStage for a
  Decision stage has non-None `decision_expression`
- Assert a Data stage has non-None `initial_value` where `<initialvalue>` is non-empty
- Assert WaitStart/LoopStart stages have non-None `group_id`

---

### Sub-Task 2 — AST Models: Add New Fields to BPStage, BPPage, BPDataItem
**Status:** `[ ] pending`

**Intent:**
Propagate the newly-parsed fields into the canonical Pydantic models so the engine
and generator can access them.

**Expected Outcomes:**
- `BPStage` has 9 new optional fields
- `BPPage` has `published: bool` field
- `BPDataItem` has `initial_value: str | None` field (already exists — verify it's populated)
- `build_ast()` correctly populates all new fields
- `_assign_wait_loop_pairs()` uses `group_id` for Wait bracket matching instead of positional order

**Todo List:**
1. In `src/flowsmith/ast/models.py:BPStage` (around line 250):
   Add these optional fields (all with `default=None` or `default=False`):
   - `decision_expression: str | None` with Field(default=None)
   - `code_text: str | None` with Field(default=None)
   - `code_length: int` with Field(default=0) — derived from code_text
   - `narrative: str | None` with Field(default=None)
   - `timeout_seconds: int | None` with Field(default=None)
   - `group_id: str | None` with Field(default=None)
   - `exception_detail: str | None` with Field(default=None)
   - `exception_usecurrent: bool` with Field(default=False)

2. In `src/flowsmith/ast/models.py:BPPage` (around line 325):
   Add `published: bool = Field(default=False, ...)`

3. In `src/flowsmith/ast/models.py:BPDataItem` (around line 227):
   Verify `initial_value: str | None` field exists (it does — line 236).
   Confirm `_build_data_items()` in builder.py is actually populating it from the raw dict.

4. In `src/flowsmith/ast/builder.py:_build_data_items()` (line 114):
   Ensure `initial_value=raw_item.get("initial_value")` is included in BPDataItem construction.

5. In `src/flowsmith/ast/builder.py:_extract_common_stage_fields()` (line 192):
   Include all 9 new fields in the common_fields dict passed to BPStage constructors.

6. In `src/flowsmith/ast/builder.py:_assign_wait_loop_pairs()` (line 362):
   Change matching logic: instead of positional stack-based matching by subsheetid,
   match by `group_id`. Stages with same `group_id` are partners (one WaitStart, one WaitEnd).
   If `group_id` is None (older BP versions), fall back to existing stack-based matching.

7. In `src/flowsmith/ast/builder.py:_build_page()` (line 453):
   Pass `published=raw_page.get("published", False)` to `BPPage(...)` constructor.

**Relevant Context:**
- `src/flowsmith/ast/models.py:BPStage` currently has ~15 fields (lines 250–319)
- `src/flowsmith/ast/builder.py:_extract_common_stage_fields()` (line 192) is the shared field extractor
- `_assign_wait_loop_pairs()` at line 362 currently uses positional matching
- Reference implementation: `scripts/bp_parser_v2._parse_stage()` lines 198–208

**Validation:**
- Run `uv run pytest tests/ast/ -v`
- Add test: build AST from PID_0171.bprelease and assert BPStage from a Decision stage
  has non-None `decision_expression`
- Assert BPPage has `published` field
- Assert WaitStart/WaitEnd stages have matching `pair_id` when `group_id` is present

---

### Sub-Task 3 — Annotator: Use New Stage Fields for Better Annotation
**Status:** `[ ] pending`

**Intent:**
The annotator should now use the newly available fields to produce richer annotations:
- Code stages should embed `code_text` in the review flag's `suggested_fix` so reviewers see the original script
- Exception stages with `exception_usecurrent=True` should get `target_type="ThrowError"` (re-raise)
- Exception stages with `exception_detail` should populate `params_map` with the detail expression

**Expected Outcomes:**
- CODE stage annotation includes original VBScript in `flags[0].suggested_fix` (truncated to 500 chars)
- EXCEPTION stage with `usecurrent=True` has `target_type="ThrowError"` and `target_module="FlowControl"`
- EXCEPTION stage with `exception_detail` has `params_map["detail_expr"] = stage.exception_detail`

**Todo List:**
1. In `src/flowsmith/engine/annotator.py:_annotate_code()` (line 220):
   Modify the `suggested_fix` to include the code body:
   ```
   code_preview = (stage.code_text or "")[:500]
   suggested_fix = f"Rewrite as PowerShell/C# script.\nOriginal VBScript:\n{code_preview}"
   ```

2. Add a new `_annotate_exception()` method or extend `_annotate_from_rules()`:
   - If `stage.exception_usecurrent == True`: set `target_type="ThrowError"`, no custom message
   - Otherwise: set `target_type="ThrowCustomError"`, populate `params_map` with exception_type and detail_expr
   - The dispatch in `annotate_stage()` for `StageType.EXCEPTION` currently falls through to `_annotate_from_rules()`
     which reads from `stage_rules.yaml`. Check if stage_rules.yaml has an EXCEPTION entry.

3. Ensure `_annotate_action()` handles the `is_alert=True` flag:
   Currently it falls through to VBO routing which returns None (no `_vbo_object` on Alert stages).
   Add explicit check: if `stage.is_alert`, return SPOT_CHECK annotation mapping to `System.ShowMessage`.

4. Ensure `is_skill=True` stages always produce MANUAL band (currently: they fall through to VBO routing).

**Relevant Context:**
- `src/flowsmith/engine/annotator.py:annotate_stage()` dispatch at lines 100–108
- `mapping/stage_rules.yaml` has an EXCEPTION entry — check its pa_target_action
- Real PAD for exception re-raise: `THROW ERROR` (PID171_performer_fixed.txt line 241)
- Real PAD for custom throw: `FlowControl.ThrowCustomError CustomErrorCode: $'''System Exception''' CustomErrorMessage: txt_ExceptionMessage`

**Validation:**
- Run `uv run pytest tests/ -v`
- Add test: BPStage with stage_type=EXCEPTION and exception_usecurrent=True → target_type="ThrowError"
- Add test: BPStage with stage_type=CODE and code_text="some code" → flags[0].suggested_fix contains "some code"

---

### Sub-Task 4 — PAD Generator: Structural Robin Constructs
**Status:** `[ ] pending`

**Intent:**
The current PAD generator cannot produce BLOCK/ON BLOCK ERROR, LABEL/GOTO,
or the correct .robin header with IMPORT statements and @SENSITIVE.
These are required for the `<Definition>` content to be valid PAD script.

**Expected Outcomes:**
- Generated .robin files include `IMPORT 'controlRepo.appmask' AS appmask` header line
- BLOCK stages produce `BLOCK 'name'\nON BLOCK ERROR all\n...\nEND` structure
- EXCEPTION stages (throw) produce `FlowControl.ThrowCustomError CustomErrorCode: … CustomErrorMessage: …`
- RECOVER stages produce `ERROR => obj_LastError` capture followed by GOTO
- `@SENSITIVE` line generated when there are password/binary type data items

**Todo List:**
1. Update `templates/pad/flow_header.robin.j2`:
   - Add `IMPORT 'controlRepo.appmask' AS appmask` and `IMPORT 'imageRepo.imgrepo' AS imgrepo`
     as hardcoded lines after the `@@DesktopType` block (before @INPUT declarations)
   - These are always present in real flows (confirmed from customizations.xml Definition content)

2. In `src/flowsmith/generator/pad.py:_render_stage()`:
   - Add case for `StageType.BLOCK`: Render `BLOCK '{stage.name}'\nON BLOCK ERROR all\n    CALL 'Get Error'\nEND`
     Use `templates/pad/actions/error_block.robin.j2` (already exists)
   - Add case for `StageType.RECOVER`: Render `ERROR => obj_LastError\nCALL 'Get Error'\nGOTO 'Error Block'`
   - Add case for `StageType.EXCEPTION`:
     - If `pa_annotation.target_type == "ThrowError"`: emit `THROW ERROR`
     - Else: emit `FlowControl.ThrowCustomError CustomErrorCode: $'''%txt_ExceptionType%''' CustomErrorMessage: txt_ExceptionMessage`
   - Add case for GOTO generation: RESUME stages should emit `GOTO 'End'`
   - Note: Current generator reads `band` and `target_type` from pa_annotation — NEVER reads stage_type directly
     This is by design (see comment in pad.py). The pa_annotation for BLOCK/RECOVER/EXCEPTION stages
     comes from stage_rules.yaml. Check those entries and update target_type values if needed.

3. In `src/flowsmith/generator/pad.py:generate_page()`:
   - Detect `@SENSITIVE` variables: any DATA stage whose data_type is "password" or "binary",
     or whose name contains "pass", "key", "secret", "pwd"
   - Pass `sensitive_vars` to flow_header template (already supported by template)

4. Update `templates/pad/actions/error_block.robin.j2` to use named exception handlers:
   Currently: `ON BLOCK ERROR all`. Real output uses:
   `ON BLOCK ERROR 'Business Exception' IsUserDefinedErrorCode: True` for typed handlers.
   Add conditional branches for typed vs catch-all.

**Relevant Context:**
- Real BLOCK structure (PID171_loader_fixed.txt lines 40–57):
  ```
  BLOCK 'Get unprocessed emails'
  ON BLOCK ERROR 'Business Exception' IsUserDefinedErrorCode: True
      SET txt_ExceptionType TO $'''Business Exception'''
      GOTO 'End'
  ON BLOCK ERROR all
      CALL 'Get Error'
      GOTO 'Error Block'
  END
      CALL 'Fetch Emails from Mailbox'
  END
  ```
- customizations.xml Definition starts with `@@ConnectionString: ''\r\n@@Type: 'Local'\r\n...`
  followed immediately by `IMPORT 'controlRepo.appmask' AS appmask\r\nIMPORT 'imageRepo.imgrepo' AS imgrepo`
- `templates/pad/actions/error_block.robin.j2` already exists — check current content

**Validation:**
- Run `uv run pytest tests/generator/ -v`
- Generate .robin for PID_0171 and check that the output file contains `IMPORT 'controlRepo.appmask'`
- Check that BLOCK stages produce `BLOCK … END` structure
- Check that `@SENSITIVE` is generated when password-type data items exist

---

### Sub-Task 5 — WorkflowBuilder: Fix Metadata JSON Flags and Claims
**Status:** `[ ] pending`

**Intent:**
The `<Metadata>` JSON in `customizations.xml` currently hardcodes all feature flags to `false`.
The `<Claims>` currently only contains `[{"name":"selfheal"}]`.
Both need to be computed from the annotated process stages only (no VBO catalogue lookup).

**Expected Outcomes:**
- `containsActiveWorkQueuesActions: true` when any stage has `stage_type == WAIT` or
  annotation `target_module == "WorkQueues"`
- `clientversion` updated to "2.69.217.26166"
- Claims array derived from `stage_rules.yaml`-driven stage types present in the process
- `flowGeneratedBy` is "Flowsmith" (already correct)

**Todo List:**
1. In `src/flowsmith/generator/workflow_builder.py:_build_metadata()` (line 251):
   - Change from returning static dict to computing from page stages:
   - `containsActiveWorkQueuesActions`: True if any stage annotation has `target_module == "WorkQueues"`
   - `clientversion`: update to "2.69.217.26166" (matching real output, not "2.63.163.25342")
   - Keep all other flags as False for now

2. In `src/flowsmith/generator/workflow_builder.py:_build_claims()` (line 283):
   - Build claims list from `stage_type` values present on the page:
     - Any WAIT/ACTION stage with WorkQueues annotation → `selfheal` (already included), `workqueues.items.get`
     - Always include: `selfheal`
   - Deduplicate claims (use a set then convert to list)

3. In `src/flowsmith/generator/workflow_builder.py:build_workflow()` (line 35):
   - Check `page.is_main` or use `BPPage.published` to set `category`:
     - Desktop flow pages: `category = 6`
     - Cloud flow pages: `category = 5` (currently always 6)
   - For cloud flows, omit `ui_flow_type` or set to 0 (not 2)

**Relevant Context:**
- Real Metadata JSON (customizations.xml line 53): clientversion "2.69.217.26166",
  `containsActiveWorkQueuesActions: true`
- Real Claims (customizations.xml line 60): includes `selfheal` and stage-type-driven claims

**Validation:**
- Run `uv run pytest tests/generator/ -v`
- Generate customizations.xml for PID_0171 and verify:
  - `<Metadata>` contains `"containsActiveWorkQueuesActions":true` when process has WAIT stages
  - `<Claims>` contains at least `{"name":"selfheal"}`

---

### Sub-Task 6 — Packager: Fix solution.xml and Category Dispatch
**Status:** `[ ] pending`

**Intent:**
The current `solution.xml` output differs from the reference in several ways:
- `<Managed>0</Managed>` vs required `<Managed>1</Managed>`
- Missing full `<Publisher>` block with `<CustomizationPrefix>` and `<Addresses>`
- Missing `<MissingDependencies>` section
- Template uses `solution_with_guids.xml.j2` (correct — uses GUIDs not schema names)

Also, the packager needs to distinguish desktop flow pages (Category=6) from cloud flow
pages (Category=5) when building Workflow elements.

**Expected Outcomes:**
- Generated `solution.xml` has `<Managed>1</Managed>` when `managed=True` is requested
- Publisher block includes `<CustomizationPrefix>` field
- `<MissingDependencies>` block present if any WorkQueue stages exist
- Desktop flow Workflow elements have Category=6, cloud flow elements have Category=5
- `<UIFlowType>2</UIFlowType>` present only for desktop flow workflows

**Todo List:**
1. Update `templates/report/solution_with_guids.xml.j2`:
   - Add `managed` Jinja2 variable: `<Managed>{{ managed | default(0) }}</Managed>`
   - Expand Publisher block:
     ```xml
     <Publisher>
       <UniqueName>{{ publisher_prefix }}</UniqueName>
       <CustomizationPrefix>{{ publisher_prefix }}</CustomizationPrefix>
     </Publisher>
     ```
   - Optionally add `<MissingDependencies>` section controlled by a `has_workqueues` variable:
     ```xml
     {% if has_workqueues %}
     <MissingDependencies>
       <MissingDependency>
         <Required type="1" schemaName="workqueueitem" displayName="Work Queue Item"
                   solution="MicrosoftFlowExtensionsCore (1.10.9.0)">
           <package appName="MicrosoftFlowExtensionsCore" version="1.10.9.0">
             MicrosoftFlowExtensionsAnchor (1.10.9.0)
           </package>
         </Required>
       </MissingDependency>
     </MissingDependencies>
     {% endif %}
     ```

2. In `src/flowsmith/generator/packager.py:package()` (line 55):
   - Add `managed: bool = False` parameter
   - Detect if any stage uses WorkQueues module: `has_workqueues = any(...)`
   - Pass `managed=managed` and `has_workqueues=has_workqueues` to solution template render

3. In `src/flowsmith/generator/workflow_builder.py:build_workflow()`:
   - Add logic to detect if page should be Cloud Flow category:
     - If any stage on the page has `pa_annotation.runtime == Runtime.CLOUD` → `category=5`, omit UIFlowType
     - Otherwise → `category=6`, `ui_flow_type=2`
   - This requires access to `page.stages` (already available)

4. Update `templates/report/customizations_workflows.xml.j2` line 25:
   - Only emit `<UIFlowType>` element when `workflow.ui_flow_type` is not None/0:
     ```
     {% if workflow.ui_flow_type %}
       <UIFlowType>{{ workflow.ui_flow_type }}</UIFlowType>
     {% endif %}
     ```

**Relevant Context:**
- Real solution.xml: `<Managed>1</Managed>` (line 9), full Publisher block (lines 10–78)
- Reference MissingDependencies (lines 85–92): workqueueitem dependency
- CF Workflow in customizations.xml: Category=5, no UIFlowType element
- DF Workflow: Category=6, UIFlowType=2
- `src/flowsmith/generator/packager.py:package()` signature at line 55

**Validation:**
- Run `uv run pytest tests/generator/ -v`
- Generate solution.xml and check `<Managed>` value
- Check that CF workflow elements don't have `<UIFlowType>`
- Check DF workflows have `<UIFlowType>2</UIFlowType>` and `<Category>6</Category>`

---

### Sub-Task 7 — Cloud Flow Generator: Produce Real CF JSON Structure
**Status:** `[ ] pending`

**Intent:**
The current Cloud Flow JSON output is a minimal try/catch scope with placeholder actions.
The reference CF JSON (`CF_PID_171_US_LIMS_Prelude_Cloud_Main-*.json`) is a sophisticated
orchestrator that initialises variables, invokes desktop flows, and handles errors.
The gap is large — the current generator produces skeletal output that needs major restructuring.

This sub-task focuses on producing the correct top-level structure and environment parameters.
Full action-level fidelity is tracked separately.

**Expected Outcomes:**
- CF JSON has correct `connectionReferences` section with three connections
- CF JSON has `parameters` section with 5 environment variable entries
- CF JSON trigger is `{"manual": {"type": "Request", "kind": "Button"}}` with Loader_Flag and Performer_Flag inputs
- Top-level action structure matches: Try:_Init, Try:_Loader, Try:_Performer, Catch:_Global_Error_Handler, plus Init_* variable initializations

**Todo List:**
1. In `src/flowsmith/generator/cloudflow.py:generate_page()` (line 114):
   - Add `connectionReferences` generation from annotated stage modules:
     Same connection references as WorkflowBuilder._build_connection_references()
   - Add `parameters` section: iterate `process.environment_variables` and generate
     environment parameter entries with defaultValue and metadata.schemaName
   - Change trigger from `"kind": "PowerApp"` to `"kind": "Button"` with trigger inputs schema:
     `{"boolean": {"type": "boolean", "title": "Loader_Flag", ...}, "boolean_1": {...}}`

2. Restructure the top-level actions to match the reference:
   - Create `Try:_Init` scope: variable initializations + call to CF_Read_Config child flow
   - Create `Try:_Loader` scope: check Loader_Flag trigger input, invoke desktop flow
   - Create `Try:_Performer` scope: check Performer_Flag, query work queue, invoke desktop flow
   - Create `Catch:_Global_Error_Handler` scope: filter failed actions, extract error, send email

3. The desktop flow invocation action uses `OpenApiConnection` type:
   ```json
   {
     "type": "OpenApiConnection",
     "inputs": {
       "parameters": {
         "uiFlowId": "<desktop_flow_workflow_id>",
         "runMode": "attended",
         "item/In_txt_Config": "@string(variables('var'))"
       },
       "host": {
         "apiId": "/providers/Microsoft.PowerApps/apis/shared_uiflow",
         "operationId": "RunUIFlow_V2",
         "connectionName": "shared_uiflow"
       }
     }
   }
   ```
   The `uiFlowId` must reference the WorkflowId of the corresponding desktop flow.

4. For this sub-task, it is acceptable to template the CF JSON largely as a static
   structure with dynamic substitution of:
   - Desktop flow IDs (from WorkflowBuilder.workflows list)
   - Environment variable parameters (from process.environment_variables)
   - Connection reference logical names

**Relevant Context:**
- Reference CF JSON: `samples/pad/Shell_PP_PID_US_171_US_PreludeLIMS_V12_1_0_0_2_managed/Workflows/CF_PID_171_US_LIMS_Prelude_Cloud_Main-695D7A31-C74D-F111-BEC7-000D3ABE3BC4.json`
- `templates/cloudflow/flow_definition.json.j2` — current template
- Desktop flow IDs are generated by WorkflowBuilder at package time (uuid.uuid4())
- Sub-task 7 must complete first so desktop flow GUIDs are available

**Validation:**
- Run `uv run pytest tests/generator/ -v`
- Parse generated CF JSON and verify:
  - `connectionReferences` has at least `shared_uiflow` and `shared_office365-1`
  - `parameters` section exists with at least one environment variable entry
  - `triggers.manual.kind == "Button"`
  - `actions` contains `Try:_Loader` scope with desktop flow invocation

---

### Sub-Task 8 — Integration Test: End-to-End PID_0171 Generation
**Status:** `[ ] pending`

**Intent:**
Run the full pipeline against `samples/blueprism/PID_0171.bprelease` and validate the
output against the reference managed solution. This is the acceptance test for all sub-tasks.

**Expected Outcomes:**
- `output/PID_171_US_Process_LIMS_Prelude_solution.zip` is generated without errors
- Unzipped output contains `solution.xml`, `customizations.xml`, `[Content_Types].xml`,
  `Workflows/*.json`, `environmentvariabledefinitions/**/*.xml`
- `customizations.xml` has 2+ Workflow elements
- `solution.xml` has matching RootComponent GUIDs
- No 0.0-confidence ERROR flags for any process ACTION stages
- `<Definition>` in customizations.xml is non-empty and starts with `@@ConnectionString`

**Todo List:**
1. Run the pipeline: `uv run flowsmith convert --input samples/blueprism/PID_0171.bprelease --output output/`
2. Inspect `output/ast.json` — verify all stages are annotated and confidence > 0.0 for process ACTION stages
3. Extract the generated .zip and inspect each file
4. Compare `customizations.xml` against reference:
   - Check Workflow element count
   - Check `<Category>` values (5 vs 6)
   - Check `<Metadata>` for `containsActiveWorkQueuesActions`
   - Check `<Claims>` for workqueues claims
   - Check `<Definition>` starts with correct header
5. Compare `solution.xml` against reference:
   - Check `<Managed>` value
   - Check RootComponent count and type=29
6. Compare generated .robin files against `samples/pad/fixed/PID171_loader_fixed.txt`
   - Check IMPORT statements present
   - Check WorkQueues.* actions generated (not stubs)
   - Check BLOCK structure present for BLOCK stages
7. Run all tests: `uv run pytest tests/ -v --cov`
8. Run linter: `uv run ruff check src/ tests/`

**Relevant Context:**
- CLI entry point: `src/flowsmith/cli/app.py:convert()`
- Output directory: `output/` (gitignored)
- Reference solution: `samples/pad/Shell_PP_PID_US_171_US_PreludeLIMS_V12_1_0_0_2_managed/`

**Validation:**
Pass condition: all items in step 4–6 above match the reference without critical divergences.
Critical divergences (must fix): missing Definition content, wrong Category values, missing Claims.
Acceptable divergences for initial pass: GUIDs will differ (generated fresh), binary dependency
GUIDs will differ, connection reference padInternalId values will differ.

---

## 6. Generation Sequence

Claude Code must execute sub-tasks in this exact order (each depends on the previous):

```
Sub-Task 1 (Parser fields)
    ↓
Sub-Task 2 (AST models)
    ↓
Sub-Task 3 (Annotator smarter dispatch)
    ↓
Sub-Task 4 (PAD generator Robin constructs)
    ↓
Sub-Task 5 (WorkflowBuilder metadata + claims)
    ↓
Sub-Task 6 (Packager solution.xml + category dispatch)
    ↓
Sub-Task 7 (Cloud Flow JSON structure)
    ↓
Sub-Task 8 (Integration test)
```

---

## 7. GUID and ID Handling

### Confirmed rules (from evidence)

| ID Type | Source | Rule |
|---|---|---|
| WorkflowId in customizations.xml | Generated fresh | `uuid.uuid4().upper()` in `workflow_builder.py:78` |
| RootComponent id in solution.xml | Same GUIDs as WorkflowId | Passed as `workflow_ids` list from packager |
| Desktop flow `uiFlowId` in CF JSON | WorkflowId of the corresponding DF Workflow | Must cross-reference — built at package time |
| Binary dependency GUIDs | Generated fresh | `uuid.uuid4().upper()` per module |
| Connection reference `padInternalId` | Generated fresh or hardcoded | Can hardcode safe defaults for now |
| Process ID from bprelease | Preserved from XML (`@id` on process element) | `parse_process()` already extracts it |
| Subsheet IDs from bprelease | Preserved from XML (`@subsheetid`) | Used as page_id in BPPage |

### Unknown (unresolved questions)

1. **Desktop flow uiFlowId cross-reference**: The CF JSON references the Loader DF workflow by
   its WorkflowId. But WorkflowIds are generated at package time. The packager must:
   - First generate all desktop flow WorkflowIds (run WorkflowBuilder for all pages)
   - Then pass those IDs to the CF JSON generator
   - Current code doesn't do this — the packager calls `build_workflow()` sequentially
   - Claude Code should investigate whether to: (a) pre-generate all IDs then render,
     or (b) pass the ID map as a parameter to CloudFlowGenerator

2. **Managed vs unmanaged**: Real output has `<Managed>1</Managed>`. This should be a
   parameter to `package()`. When converting for production, pass `managed=True`.

---

## 8. Validation Strategy

### File existence check
```python
required_files = [
    "solution.xml",
    "customizations.xml",
    "[Content_Types].xml",
    "Other/ManifestFile.json",
]
# Plus at least one Workflow JSON
```

### JSON validation
```python
import json
with open("output/cloudflow/xxx.json") as f:
    data = json.load(f)  # Parse succeeds = valid JSON
assert "properties" in data
assert "definition" in data["properties"]
assert "actions" in data["properties"]["definition"]
```

### XML validation
```python
from lxml import etree
tree = etree.parse("customizations.xml")
workflows = tree.findall(".//Workflow")
assert len(workflows) >= 2  # At least one desktop + one cloud
for wf in workflows:
    assert wf.find("Definition") is not None
    assert wf.find("Definition").text is not None
    assert wf.find("Definition").text.startswith('"@@Connection')
```

### Cross-file consistency
```python
# Get all WorkflowId values from customizations.xml
workflow_ids = {wf.get("WorkflowId").strip("{}").lower()
                for wf in tree.findall(".//Workflow")}
# Get all RootComponent ids from solution.xml
root_ids = {rc.get("id").strip("{}").lower()
            for rc in sol_tree.findall(".//RootComponent")}
# Every root component must have a corresponding workflow
assert root_ids.issubset(workflow_ids)
```

### Definition content check
```python
for wf in workflows:
    defn = wf.find("Definition")
    assert defn is not None
    # Definition must be a JSON-escaped string starting with @@ConnectionString
    import json
    content = json.loads(defn.text)  # Should parse as JSON string
    assert content.startswith("@@ConnectionString:")
    assert "IMPORT 'controlRepo.appmask'" in content
```

---

## 9. Risks and Ambiguities

### High risk
1. **Desktop flow uiFlowId forward reference**: The Cloud Flow JSON must reference the desktop
   flow's WorkflowId, but that ID is generated at package time. Claude Code must restructure
   `packager.package()` to pre-generate all workflow IDs before rendering CF JSON.
   Investigate: can `WorkflowBuilder.build_workflow()` be called in a two-pass manner?

2. **Robin BLOCK structure**: Real PAD BLOCK/ON BLOCK ERROR is complex (multiple typed handlers,
   nested content, GOTO targets). The simple `error_block.robin.j2` template may be insufficient.
   Claude Code should study PID171_loader_fixed.txt lines 40–57 carefully before implementing.

3. **Anchor resolution breaking existing tests**: Adding anchor chain resolution changes
   how edges are computed. Existing test fixtures may need updating.

### Medium risk
4. **group_id-based Wait/Loop pairing**: Some older BP processes may not have `<groupid>` elements.
   The fallback to stack-based matching must remain for backward compatibility.

5. **customizations.xml `<UIFlowType>` conditional**: The template must conditionally omit this
   element for cloud flows. Current template always emits it.

### Low risk
6. **Managed vs unmanaged solution**: The reference has `<Managed>1</Managed>`. The generator
   currently always emits `<Managed>0</Managed>`. Adding a `managed=True` parameter is straightforward.

7. **OrganizationVersion in customizations.xml**: Current template hardcodes `9.2.26031.175`,
   reference has `9.2.26063.162`. This is a minor cosmetic difference and won't affect importability.

---

## 10. Questions Requiring Confirmation

None at this time. All design decisions above are grounded in direct evidence from the reference
files. Claude Code should proceed with implementation and raise issues only if a specific file
or structure cannot be located during implementation.
