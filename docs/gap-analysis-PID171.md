# Gap Analysis — PID_171 generated solution vs hand-built managed reference

**Phase 1 baseline report.** This file is the fixed contract Phase 2 works from.

- **Source:** `samples/blueprism/PID_0171.bprelease`
  (2 processes, 22 objects, 11 environment variables, 5 object-groups, 2 process-groups — declared count 42)
- **Reference (expected output):** `samples/pad/Shell_PP_PID_US_171_US_PreludeLIMS_V12_1_0_0_2_managed/`
  (hand-built managed solution, version 1.0.0.2)
- **Generated:** `output/pid171_run/PID_171_US_Process_LIMS_Prelude_solution.zip`
  produced by `uv run flowsmith convert --input samples/blueprism/PID_0171.bprelease --output output/pid171_run`
  (pipeline exit 0; run 2026-07-17 on branch `dev` @ `1037539` + uncommitted parser/AST/packager edits)
- **Regression scope:** PID_0127 is the only other known PID exercising this pipeline. Every template listed
  below is shared by all PIDs (there are no per-PID templates), so **any template fix must be re-verified
  against PID_0127** (`tests/parser` integration suite + full convert run).

---

## 0. Headline architecture difference (context for every gap below)

| | Generated | Reference |
|---|---|---|
| Workflow count | 40 `<Workflow>` elements in customizations.xml (all Category 6 / desktop), 20 orphan cloud-flow JSONs in `Workflows/` | **4** workflows: `CF_PID_171_US_LIMS_Prelude_Cloud_Main`, `CF_PID_171_US_Read Config File` (Category 5), `DF_PID_171_US_LIMS_Prelude_Main`, `DF_PID_171_US_Loader` (Category 6, UIFlowType 2) |
| Mapping unit | **1 BP page → 1 workflow** (and all 382 pages of 2 processes + 22 VBOs flattened into one `BPProcess`) | **1 BP process → 1 CF + consolidated DFs**; BP pages and used VBO actions become `FUNCTION 'name' [GLOBAL]` subflows *inside* a single DF `<Definition>` |
| Loader/performer | Not represented | Main BP process split into DF_Loader (fetch mail → populate queue) + DF_Main (performer), orchestrated by CF_Cloud_Main via work-queue counting |
| 2nd BP process (`RPA_Sharepoint_API_ConfigFile_Download`) | Merged into the same flat page list | Its own cloud flow `CF_PID_171_US_Read Config File` |

The reference embodies deliberate redesign (loader/performer split, retry loops, e-mail bodies). Gaps that
require this human-level redesign are flagged `redesign` in the tables; everything else is mechanically
derivable from the `.bprelease`.

---

## 1. COVERAGE gaps — BP construct present in PID_171 with no template at all

| ID | Gap | Root cause | Template(s) implicated | Other PIDs affected |
|----|-----|-----------|------------------------|---------------------|
| **COV-1** | **Environment variables dropped entirely.** The release declares 11 `env:environment-variable` items; reference ships 6 `environmentvariabledefinitions/<prefix>_<name>/environmentvariabledefinition.xml` folders (schemaname `cr3ac_PID_171_*`, displayname, defaultvalue, type code e.g. `100000000` for text). Generated zip has none; the AST (`ast.json`) has no env-var field at all — the parser discards them. | Parser (`parse_process`) never extracts `env:` items; `BPProcess` model has no field; packager has no emitter. | **none exists** (new `environmentvariabledefinition.xml.j2` needed) + parser/AST/packager wiring | PID_0127 (also contains env vars) |
| **COV-2** | **Work queues not represented.** BP process uses internal work-queue actions (Get Next Item / Mark Completed / Mark Exception / Add To Queue pages exist). Reference ships `<workqueues><workqueue workqueueid=…>` in customizations.xml (name `WQ_PID_171_US_LIMS_Prelude`, workqueuekey GUID, itemmaxrequeuecount etc.) plus `workqueues.*` claims on DF workflows and a `MissingDependencies` entry for `workqueueitem` (MicrosoftFlowExtensionsCore). Generated: nothing — CF renders `Get_Next_Item` as a `Compose` stub. | No detection of work-queue usage → no `<workqueue>` emission. (Note: the `.bprelease` contains **no** work-queue definition items; the queue must be synthesised from usage + process name.) | **none exists** (customizations `<workqueues>` block) ; `templates/pad/actions/work_queues.robin.j2` exists but PAD output for queue stages still stubs | PID_0127 (uses work queues) |
| **COV-3** | **Multi-artefact release flattened.** 2 processes + 22 objects are merged into one `BPProcess` named after the first process, with 382 pages and a 242-stage "Stage1" main page. The reference keeps process #2 as its own cloud flow and does not ship VBO pages as standalone flows. | Parser/AST builder has no artefact boundary; generators receive one flat page list. | none exists (parser/`ast.builder` architecture — no template) | PID_0127 (single process + objects — same flattening, less visible) |
| **COV-4** | **No call-graph pruning / VBO inlining.** All 382 pages generate output — including `OBSOLETE`, `### TEST`, separator pages (`----…Extended Features----`). Reference ships only actions actually reachable from the two processes, inlined as `FUNCTION`s in the consuming DF. | No reachability analysis from process → subsheet/action call edges (edges only now being added in the uncommitted parser work). | none exists (engine-level) | PID_0127 |
| **COV-5** | **UI selectors / images (desktopflowbinaries) absent.** Reference has 59 GUID folders: ControlRepository ×2, ControlRepositoryImageFile ×44, ImageRepository ×2, ImageRepositoryImageFile ×2, ManifestFile ×2, DependenciesFile ×2, ConnectorDefinition ×5 — each with `desktopflowbinary.xml` wrapper linked to its DF's workflowid; DF definitions begin `IMPORT 'controlRepo.appmask' AS appmask` / `IMPORT 'imageRepo.imgrepo' AS imgrepo`. Generated zip: no folder; `Dependencies.requiredBinaries` filled with **random GUIDs that point at nothing**. BP `<appdef>` application models (UI element trees) are never parsed. | No appdef parser, no binary-wrapper template, no repo-file generators. | **none exists** (`desktopflowbinary.xml.j2` + data-file emitters) | PID_0127 |
| **COV-6** | **Loader/performer orchestration pattern.** Reference CF_Cloud_Main: Try/Catch per phase (Init / Loader / Performer), run-type switches (Cloud vs Desktop, Attended vs Unattended via `OpenApiConnection` uiflow calls), Dataverse `List_rows` on `workqueueitems`, child-workflow call to CF_ReadConfigFile with `ParseJson` of result, failure e-mails + `Terminate` per phase. Generated main CF: Try scope with two `Compose` stubs + generic Catch. | This is a **redesign** pattern, not mechanically derivable from BP XML. Needs an orchestration template driven by config. | `templates/cloudflow/flow_definition.json.j2` + a new orchestrator template (**none exists**) | PID_0127 (same main-CF template) |
| **COV-7** | **Connection references not derived.** Reference declares 6 `<connectionreference>` elements (keyvault, sharepointonline, uiflow, commondataserviceforapps, excelonlinebusiness, office365) with logical names (`cr3ac_…`/`new_…`) that CF JSONs bind via `connectionReferences`. Generated: `<connectionreferences>` section absent and every CF has `"connectionReferences": {}`. | VBO→connector knowledge partially exists in `mapping/vbo_catalogue.yaml`, but nothing aggregates per-solution connectors nor emits the XML section. | **none exists** (customizations `<connectionreferences>` block) | PID_0127 |

## 2. STRUCTURAL gaps — element missing/extra or wrong XML shape

| ID | Gap | Root cause | Template(s) implicated | Other PIDs affected |
|----|-----|-----------|------------------------|---------------------|
| **STR-1** | **Cloud flows orphaned.** 20 `Workflows/*_cloudflow.json` files are in the zip but have **no `<Workflow>` element** in customizations.xml (all 40 entries are Category 6 desktop). Reference CF entries: `JsonFileName`, `Type=1`, `Category=5`, `Mode/Scope/StateCode=1/StatusCode=2/RunAs/IsTransacted/IntroducedVersion/IsCustomizable/BusinessProcessType/ModernFlowType/PrimaryEntity/LocalizedNames` — and *no* Definition/Metadata block. | Packager only builds Workflow entries from robin files; cloud flows never enter `builder.workflows`. | `templates/report/customizations_workflows.xml.j2` | PID_0127 |
| **STR-2** | **342 of 382 pages silently dropped from customizations.xml.** `SolutionPackager._sanitise_filename` keeps spaces while `PADGenerator._sanitise_filename` converts spaces→underscores, so `_find_robin_file("Mark Item As Completed")` never matches `Mark_Item_As_Completed.robin` → `continue` (silent skip). Only the 40 space-free page names survived. Also: loose substring matching (`target_stem in robin_file.stem`) can attach the **wrong** robin, and duplicate page names (`Attach` ×4, `Terminate` ×3, `Clean Up` ×12…) produce duplicate Workflow Names with no uniquification. | Two different sanitisers + fuzzy matching + no error on miss (violates "never silently skip"). | `src/flowsmith/generator/packager.py` (code, not template) | PID_0127 |
| **STR-3** | **`JsonFileName` references point at files that don't exist.** DF entries reference `/Workflows/<Page>.json`; the zip contains only `*_cloudflow.json`. Reference pattern: `/Workflows/<Name>-<WORKFLOWID-UPPERCASE>.json`, and **every DF has a companion stub JSON** (205 bytes: `{"properties":{"definition":{"package":""},…},"schemaversion":"ROBIN_202208_DVRS"}`). | Packager never writes DF stubs; filename scheme lacks the GUID suffix. | `templates/report/customizations_workflows.xml.j2` + packager; DF stub JSON template **none exists** | PID_0127 |
| **STR-4** | **customizations.xml sections missing/extra.** Missing: `<connectionreferences>` (COV-7), `<workqueues>` (COV-2), `<Languages><Language>1033</Language>`. Extra: `<SolutionPluginAssemblies/>` (absent in reference). Root attrs on `<ImportExportXml>` match in shape (OK). | Template written against the older PADPOC sample. | `templates/report/customizations_workflows.xml.j2` | PID_0127 |
| **STR-5** | **solution.xml manifest divergence.** Generated root attrs: 4 (`version=9.0.0.0`, `SolutionPackageVersion=9.0`, `languagecode`, `generatedBy=flowsmith`) vs reference 7 (adds `OrganizationVersion`, `OrganizationSchemaType`, `CRMServerServiceabilityVersion`; `generatedBy=CrmLive`, version `9.2.x`). Missing `<Descriptions>`; `<Managed>0</Managed>` vs `1`; Publisher has 1 child vs 8 (no `CustomizationPrefix` — reference `cr3ac` drives env-var/connref logical names); no `<MissingDependencies>` (reference declares the `workqueueitem` dependency). RootComponents: 40 random GUIDs regenerated per run vs 4 stable workflow ids. | Minimal stub template; GUIDs not persisted; publisher prefix not configurable. | `templates/report/solution_with_guids.xml.j2` | PID_0127 |
| **STR-6** | **`[Content_Types].xml` missing `png` default.** Reference has 3 `<Default>` entries (xml, json, **png** — needed for ControlRepositoryImageFile binaries); generated has 2. | Template predates image binaries. | `templates/report/content_types.xml.j2` | PID_0127 |
| **STR-7** | **Extra `Other/` folder.** Generated zip ships `Other/ManifestFile.json` (empty ModuleReferences) + `Other/DependenciesFile.json`. Reference has no `Other/` — manifest & dependencies live per-DF inside `desktopflowbinaries/` (COV-5). | Legacy of the pre-6.4 packager. | packager code (no template) | PID_0127 |
| **STR-8** | **Env-var definitions folder missing** (structural face of COV-1: `environmentvariabledefinitions/<schemaname>/environmentvariabledefinition.xml`, one folder per variable). | See COV-1. | **none exists** | PID_0127 |

## 3. LOGIC-LEVEL gaps — element exists but content/expression logic diverges

| ID | Gap | Root cause | Template(s) implicated | Other PIDs affected |
|----|-----|-----------|------------------------|---------------------|
| **LOG-1** | **DF `<Definition>` header wrong.** Reference robin starts `@@ConnectionString: ''` / `@@Type: 'Local'` / `@@DesktopType: 'local'` / `@@DisplayName: 'Local computer'`, then `IMPORT` repo lines, `@SENSITIVE: […]`, and `@INPUT`/`@OUTPUT` declarations built from the flow's parameters. Generated robin starts with `# Generated by Flowsmith` comment banner, no `@@` header, no `@INPUT/@OUTPUT`, no imports. | Header template emits comments instead of the ROBIN preamble contract. | `templates/pad/flow_header.robin.j2` | PID_0127 |
| **LOG-2** | **Robin bodies are mostly comments/stubs.** Sampled `Launch.robin` (20 stages): every ACTION renders as `# System.` / `# UIAutomation. # TODO`, WAIT stages fail with *"No mapping rule for stage type 'WAIT'"* stubs, `SET` lines emit placeholder `%SomeVar%`, and variable names keep spaces (`SET num_Try Count TO …` — syntactically invalid Robin). Reference uses concrete actions (`Variables.ConvertJsonToCustomObject`, `FlowControl.ThrowCustomError`, `WorkQueues.GetWorkQueueItems`, `Excel.*`, `Email.*`), `**REGION` markers, `LOOP`/`LABEL`/`GOTO`. | Mapping rules incomplete (WAIT missing entirely); expression translator emits placeholders; identifier sanitisation missing. | `templates/pad/actions/*.robin.j2` (esp. `stub`, `set_variable`, `work_queues`) + `mapping/stage_rules.yaml` | PID_0127 |
| **LOG-3** | **Exception handling shape.** Reference wraps phases in `BLOCK 'name'` with typed `ON BLOCK ERROR 'Business Exception' IsUserDefinedErrorCode: True` handlers routing via `GOTO 'Error Block'`, preserving BP exception-type strings. Generated robin shows no BLOCK/ON BLOCK ERROR structure for BP Block/Recover/Resume stages. | `error_block.robin.j2` exists but BP BLOCK→Recover mapping isn't driving it (implicit Block→Recover edge only added in uncommitted parser work). | `templates/pad/actions/error_block.robin.j2` | PID_0127 |
| **LOG-4** | **CF JSON envelope wrong.** Generated CF: trigger `kind: "PowerApp"` with empty schema, no `parameters` block, no `templateName`, no root `schemaVersion`, `connectionReferences: {}`. Reference: trigger `kind: "Button"` with typed input schema (titles = BP input params, `x-ms-content-hint`), `parameters` incl. `$authentication`/`$connections`, root `"schemaVersion"`, populated `connectionReferences` keyed by connector with `connectionReferenceLogicalName`. | Envelope template built from an older, simpler sample. | `templates/cloudflow/flow_definition.json.j2` | PID_0127 |
| **LOG-5** | **CF action logic stubs.** Connector calls render as `Compose` "STUB:" actions (e.g. `Get_Bearer_Token` for `shared_keyvault.Get`); reference uses `OpenApiConnection` actions with `host.connectionName/operationId` + typed parameters, `Query`/`ParseJson`/`Workflow` child-flow calls, and per-action `metadata.operationMetadataId`. `runAfter` chains in generated scopes are flat/empty. | `stub.json.j2` used wherever no concrete action template matched; no OpenApiConnection template. | `templates/cloudflow/actions/*` (`stub.json.j2`; OpenApiConnection template **none exists**) | PID_0127 |
| **LOG-6** | **Workflow metadata JSON fields.** Generated DF entries: `Inputs/Outputs = {"schema":null}` (reference: schemas derived from flow params); `Dependencies.childFlows` always empty (reference DF_Main lists its child flow GUID); `Dependencies.environmentVariables/workQueues` empty; `ConnectionReferences = []` (reference: populated with api name, displayName, padInternalId); `Claims` always `[{"name": "selfheal"}]` (reference: `workqueues.items.get`, `connectors.execution.*` per flow); `Metadata.clientversion` "2.63.163.25342" (reference "2.69.217.26166"). | `workflow_builder.py` fills placeholders; page-level params (now parsed in uncommitted work) not used. | `templates/report/customizations_workflows.xml.j2` + `src/flowsmith/generator/workflow_builder.py` | PID_0127 |
| **LOG-7** | **Naming conventions.** Reference: `CF_`/`DF_` prefixes + `PID_171_US_` stem; env vars `cr3ac_PID_171_*` (publisher prefix); work queue `WQ_PID_171_US_LIMS_Prelude`; solution UniqueName `Shell_PP_PID_US_171_US_PreludeLIMS_V12`. Generated: raw BP page names, no prefixes, duplicate names uncontrolled. | No naming policy layer. | packager + `workflow_builder` (code); all report templates consume the names | PID_0127 |

---

## 4. Verification matrix (updated during Phase 2)

Order of work: coverage → structural → logic, per Phase 2 protocol.
"Verified" means: pipeline re-run on PID_0171, targeted re-diff confirms the gap closed, and PID_0127
regression run (convert + pytest) passes.

| ID | Status | Fix applied | Verification | PID_0127 regression |
|----|--------|-------------|--------------|---------------------|
| COV-1 | pending | — | — | — |
| COV-2 | pending | — | — | — |
| COV-3 | pending | — | — | — |
| COV-4 | pending | — | — | — |
| COV-5 | pending | — | — | — |
| COV-6 | pending | — | — | — |
| COV-7 | pending | — | — | — |
| STR-1 | pending | — | — | — |
| STR-2 | pending | — | — | — |
| STR-3 | pending | — | — | — |
| STR-4 | pending | — | — | — |
| STR-5 | pending | — | — | — |
| STR-6 | pending | — | — | — |
| STR-7 | pending | — | — | — |
| STR-8 | pending | — | — | — |
| LOG-1 | pending | — | — | — |
| LOG-2 | pending | — | — | — |
| LOG-3 | pending | — | — | — |
| LOG-4 | pending | — | — | — |
| LOG-5 | pending | — | — | — |
| LOG-6 | pending | — | — | — |
| LOG-7 | pending | — | — | — |

### Scope notes for Phase 2

- **Redesign-scale gaps** (COV-3 flow consolidation, COV-4 pruning, COV-6 loader/performer orchestration,
  and the full concrete-action translation in LOG-2/LOG-5) cannot be closed to byte-parity with a
  hand-built solution by template edits alone; they need engine/parser architecture work and, for COV-6,
  a human-approved orchestration pattern. Phase 2 will close what is mechanically derivable and record
  the residual explicitly per gap — nothing gets silently folded in.
- Random GUID regeneration per run (STR-5) means diffs must compare *structure*, not GUID values.
