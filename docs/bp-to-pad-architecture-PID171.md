# BP → PAD Migration Architecture & Mapping Design — PID_171

**Process:** `PID_171_US_Process_LIMS_Prelude` (Blue Prism) → Shell_PP_PID_US_171_US_PreludeLIMS
(Power Platform managed solution).
**Ground-truth PAD target:** `samples/pad/Shell_PP_PID_US_171_US_PreludeLIMS_V12_1_0_0_11_managed/`
(the current, complete, deployed implementation — not the `_fixed.txt` patches, which only cover
a subset of functions and assume an existing flow to paste into).
**BP source:** `samples/blueprism/PID_0171.bprelease` (main process only; the sibling
`RPA_Sharepoint_API_ConfigFile_Download` process and all 22 VBO/object artefacts are call
targets, not separately translated).

**Implementation strategy:** see
[`docs/bp-to-pad-implementation-strategy-PID171.md`](bp-to-pad-implementation-strategy-PID171.md)
for the *how* — a codebase audit classifying every `src/flowsmith` module, the `mapping/*.yaml`
update guidance, and the coding-phase/reviewer-subagent plan built on top of this document. This
file stays the *what*/*why* reference; that one is the execution plan.

**How to use this document:** Part A is the reference ruleset — read it first, it defines the
naming/error/stop/consecutive-exception conventions every generated stage must follow. Part B is
the transformation procedure — for each BP page, look up its stage-type rule in §B12, its
VBO/action mapping in §B13, and its target `FUNCTION` in §B14, then emit PAD code following the
exact syntax templates given (not paraphrased). Anything marked **STOP** requires a human
decision before code is generated for it — do not guess.

**Project conventions:** `docs/` holds documents and session plans (this file, `docs/pad-reference/`
for extracted ground-truth source and the VBO mapping file). `scripts/` holds reusable parsing/
reporting utilities (`bp_parser_v2.py`, `bp_release_parser.py`, `bp_report_v2.py`,
`extract_definitions.py`, etc.) — general-purpose tools, not one-off/temporary output. Anything
that re-derives a fact cited in this document should go through those scripts rather than ad hoc
XML reads, both to stay consistent with what's already been verified and so the same tool can be
re-run if the source files change.

---

## PART A — PAD ARCHITECTURE REFERENCE

### A1. Package identification & provenance

| Source | What it is | Status |
|---|---|---|
| `samples/pad/Shell_PP_PID_US_171_US_PreludeLIMS_V12_1_0_0_11_managed/customizations.xml` | **Ground truth.** Full managed-solution export, 5 `<Workflow>` entries, complete Robin source inline for both desktop flows | Current |
| `samples/pad/Shell_PP_PID_US_171_US_PreludeLIMS_V12_1_0_0_2_managed/` | Earlier export of the same package | Superseded — not used below |
| `samples/pad/fixed/PID171_loader_fixed.txt`, `PID171_performer_fixed.txt` | Hand-authored **patch** — its own header states "paste these function bodies into the EXISTING flows... do not paste into a brand-new empty flow" | Partial/historical — used only where it disagrees with `_11_managed`, noted in §A8 |
| `samples/pad/PID171_loader.txt`, `PID171_performer.txt` | Pre-fix originals | Superseded |

**Extraction method** (reproducible — script at `scripts/extract_definitions.py`):
`customizations.xml`'s `<Workflow><Definition>` element for a Desktop Flow is XML-entity-escaped
around a **JSON-encoded string literal** (opening/closing `"`, `\r\n`/`\'`/`\"` escapes) — decode
with `html.unescape()` then `json.loads()`, not a naive `str.replace`. Cloud Flows (`Type=1`,
`Category=5`) store no inline `<Definition>`; instead `<JsonFileName>` points at
`Workflows/<Name>-<GUID>.json`, a plain Logic-App-schema JSON file.

The two decoded desktop-flow sources are saved for reference at:
- `docs/pad-reference/DF_PID_171_US_Loader.robin.txt` (313 lines, 4 `FUNCTION`s + main body)
- `docs/pad-reference/DF_PID_171_US_LIMS_Prelude_Main.robin.txt` (1655 lines, ~29 `FUNCTION`s + main body)

All line numbers cited in this document refer to these two files.

### A2. 5-flow orchestration architecture

| Workflow | Type | WorkflowId | Role |
|---|---|---|---|
| `CF_PID_171_US_LIMS_Prelude_Cloud_Schedule` | Cloud Flow | `7f249437-0497-f111-8075-000d3ab1199b` | Recurrence trigger (every 30 min, UTC) → calls Cloud_Main |
| `CF_PID_171_US_LIMS_Prelude_Cloud_Main` | Cloud Flow | `695d7a31-c74d-f111-bec7-000d3abe3bc4` | Orchestrator |
| `CF_PID_171_US_Read Config File` | Cloud Flow | `441406d4-9c6f-f111-ab0c-0022489b2a72` | Reads config from a SharePoint Excel table, returns JSON |
| `DF_PID_171_US_Loader` | Desktop Flow | `5231954c-98dc-4575-8b2f-7cbfc0e3c42f` | Loader |
| `DF_PID_171_US_LIMS_Prelude_Main` | Desktop Flow | `a08a518c-e955-4e3a-af5b-262e29bc6a9b` | Performer |

**Call chain, exactly as implemented:**

1. **Cloud_Schedule** (`Recurrence`, interval 30 Minute) → `Run_a_Child_Flow` (type `Workflow`,
   `host.workflowReferenceName` = Cloud_Main's GUID) with body `{boolean: true, boolean_1: true}`
   — every cycle always requests both phases. Checks the response's `out_txt_mainflow_status`;
   if not `"Success"` → `Terminate` (Failed, error message = that field).

2. **Cloud_Main** — trigger `manual` (`Request`, kind `Button`), 2 **required** boolean inputs:
   `boolean` (title `Loader_Flag`), `boolean_1` (title `Performer_Flag`) — this makes Cloud_Main
   independently callable with either phase toggled off (e.g. a manual performer-only re-run).
   Body, in order:
   - **`Try: Init`** → `Run: Load Config Data` (type `Workflow`, calls Read Config File's GUID)
     with `body.text` = the `EV_PID_171_US_LIMS_Prelude_SharePoint_URL` environment variable;
     result parsed as JSON into variable `var`; success is gated on a `Flow_Message == "success"`
     field in the response. **`Catch: Init`** on failure → email + `Terminate(Failed)` + `Respond`.
   - **`Try: Loader`** (runs after `Try: Init` succeeds):
     - `Assign_Work_Queue_ID`: `WorkQueue_ID` variable ← `var['Ctrl_WorkQueueId']`.
     - `IF triggerBody()['boolean'] = true THEN` (Loader_Flag):
       - `IF lower(var['Ctrl_LoaderType']) = 'cloud' THEN` — **body is empty** (`{}`) — a
         cloud-native loader is a config-selectable option with **no implementation yet**;
         **STOP** if a real BP process ever needs this path, it must be built from scratch.
       - `ELSE` (desktop — the only real path today):
         - `IF lower(var['Ctrl_LoaderUnattendedRun']) = 'yes' THEN` → `OpenApiConnection`
           (`shared_uiflow`, `RunUIFlow_V2`, `uiFlowId`=Loader GUID, `runMode: 'unattended'`,
           `item/In_txt_Config: string(var)`) **ELSE** the same call with `runMode: 'attended'`.
         - `SetVariable Flow_Status = true`.
     - `Catch: Loader` — same failure pattern as `Catch: Init`.
   - **`Try: Performer`** (runs after `Try: Loader` succeeds):
     - `IF triggerBody()['boolean_1'] = true THEN` (Performer_Flag):
       - `List_rows_-_Get_Queue_Item_count`: Dataverse `ListRecords` on `workqueueitems`,
         filter `_workqueueid_value eq '<WorkQueue_ID>' and statecode eq 0` (pending only).
       - `Total_Queue_Items = length(...)`.
       - `IF Total_Queue_Items > 0 THEN` — **this is the orchestrator-level gate that avoids
         launching a bot session for an empty queue**, mirroring what BP's `Get Next Item`
         loop does implicitly by simply returning nothing:
         - `IF lower(var['Ctrl_PerfomerType']) = 'desktop' THEN`
           (unattended/attended `RunUIFlow_V2` call, `uiFlowId`=Performer GUID, same shape as
           Loader) `SetVariable Flow_Status = true`.
           `ELSE` — **empty**, same not-yet-implemented placeholder pattern as the Loader.
     - `Respond_to_a_Power_App_or_flow_-_Success`: 200, `{out_txt_mainflow_status: "Success"}`.
     - `Catch: Performer` — same failure pattern.
   - **`Catch: Global_Error_Handler`** — top-level safety net wrapping the whole flow: filters
     the run's action outputs for an `error_description`, emails, responds failure.

3. Both desktop flows receive their entire configuration as **one parameter**:
   `item/In_txt_Config = string(var)` — the same JSON blob Cloud_Main used for its own routing
   decisions (`Ctrl_LoaderType`, `Ctrl_PerfomerType`, `Ctrl_*UnattendedRun`, `Ctrl_WorkQueueId`)
   is re-parsed independently inside each desktop flow via
   `Variables.ConvertJsonToCustomObject Json: In_txt_Config CustomObject=> obj_Config` and then
   `Load Config Data` derives everything else (folder paths, retry limits, mail settings) from
   `obj_Config`. **Rule for generation:** any new config key consumed only by a desktop flow
   needs no Cloud_Main change; a key that changes *routing* (attended/unattended, cloud/desktop)
   must be added to Cloud_Main's `If` conditions too.

4. `CF_PID_171_US_Read Config File` — trigger inputs `In_txt_SharePointURL`,
   `In_txt_SharePointFilePath`, `In_txt_Config_TableName` (+ more); resolves the SharePoint
   document library, reads the named Excel table, returns it as the `configuration` JSON body
   consumed by Cloud_Main's `Try: Init`. Not further decomposed here — treat as a fixed utility
   flow, out of scope for the BP crosswalk (BP has no equivalent stage; it's Cloud_Main's own
   config-bootstrap concern).

5. **Release-level environment variables** — the BP `.bprelease` container declares 11
   `<environment-variable>` entries (distinct from the 3 process-level `Data` items with
   `exposure=Environment` covered in §A4/§B12; parse with `scripts/bp_release_parser.py`, field
   `environment_variables`, not `bp_parser_v2.py`'s per-page `Data` stages). These are the source
   of the `parameters('EV_...')` references Cloud_Main's `Try: Init` reads:

   | Name | Type | Value / role |
   |---|---|---|
   | `PID_171_US_EV_LIMS_Prelude_ConfigFile` | text | Config file name (`PID_171_US_LIMS_Prelude_Config File.xlsx`) |
   | `RPA_Sharepoint_URL` | text | SharePoint site URL — feeds `CF_PID_171_US_Read Config File`'s `In_txt_SharePointURL` |
   | `RPA_Sharepoint_Credential_Name`, `RPA_Sharepoint_Bearer_Token` | text | SharePoint API auth |
   | `RPA_Sharepoint_Random_Wait` | number | Anti-throttling jitter (seconds) for the SharePoint API |
   | `Generic_RPA_Sharepoint_API_Config_File_Folder_Path` | text | Same role as the process-level Data item of the same name (§A4) — declared at both levels in BP |
   | `Generic_SupportTeam_EmailID` | text | Config-load-failure notification address |
   | `RPA_AzureBlob_Download` | flag | Gates a BP-side **Azure Blob Storage fallback** for config download |
   | `RPA_AzureBlob_Container_Name`, `RPA_AzureBlob_StorageAccount_Name`, `RPA_AzureBlob_Credential_Name` | text | Azure Blob fallback connection details |

   **Gap, add to §B16:** the 4 `RPA_AzureBlob_*` keys describe a complete alternate config-download
   path (Blob Storage instead of SharePoint) that BP supports via a flag. Nothing in `_11_managed`
   (Cloud_Main, Read Config File) implements or references this fallback anywhere — `Ctrl_*`
   config keys and the Cloud Flow actions inspected in §A2 are SharePoint-only. `ReviewFlag`: no
   PAD equivalent exists for the Azure Blob path; confirm it's intentionally dropped before
   building any new config-bootstrap logic that assumes it still needs to exist.

### A3. Desktop flow structure

**`DF_PID_171_US_Loader`** — `@INPUT In_txt_Config`; `@OUTPUT Out_num_MailItemCount`,
`Out_txt_ExceptionDetail`. Main body (lines 11–154):

```
Init (region "Initialise Values", L12-30): defaults + parse In_txt_Config → obj_Config
  (empty obj_Config → System Exception, thrown immediately)
CALL 'Load Config Data'                                              (L32)
BLOCK 'Get unprocessed emails'  (typed: Business Exc / Sys Unavail Exc / catch-all)  (L35-50)
  CALL 'Fetch Emails from Mailbox'
IF lst_MailItems.Count = 0 → Business Exception mail, GOTO 'End'     (L51-56)
BLOCK 'Add to Queue Block' (catch-all)                                (L58-145)
  LOOP FOREACH obj_CurrentMail IN lst_MailItems
    MarkAsRead_V3 (Outlook)                                          (L67)
    BLOCK 'Run Hash script' → SHA-256 hash of mail id, 40 chars       (L69-82)
    BLOCK 'Duplicate Item Check' → WorkQueues.GetWorkQueueItems by hash name  (L84-102)
      lst_WorkQueueItems.Count > 0 → NEXT LOOP (skip, already queued)
    build lst_Attachments from obj_CurrentMail.attachments (only if hasAttachments=True)  (L107-113)
    build obj_QueueInputs {Id, Subject, ReceivedOn, MailAttachments} → JSON               (L115-116)
    fetch AES key from Key Vault (GetSecret) → encrypt JSON (AES-256, UTF8, PKCS7)         (L117-121)
    IF encrypted length > num_MaxQueueValueLength (1,000,000) → Business Exception mail, skip  (L124-132)
    BLOCK 'Add to Work Queue' → WorkQueues.EnqueueWorkQueueItem.WithoutUniqueId             (L133-142)
    LABEL 'Next loop - Mail Items'
LABEL 'Error Block' → typed rethrow (SUE vs generic SE)               (L147-151)
LABEL 'End' → set outputs                                             (L152-154)
```

Helper `FUNCTION`s: `Get Error` (GLOBAL, L155), `Send Business Exception Mail` (L173),
`Load Config Data` (GLOBAL, L213), `Fetch Emails from Mailbox` (GLOBAL, L274 — retry loop
`num_MailRunCount FROM 1 TO num_MailRetryLimit`, per-attempt error captured into
`flg_OutlookError`, exhaustion check done **after** the `BLOCK`, not inside its handler; then
filters `lst_MailItems` down to senders in `lst_SenderMailList`, a case-insensitive, comma-split
allowlist built in `Load Config Data`).

**`DF_PID_171_US_LIMS_Prelude_Main`** (Performer) — `@INPUT In_txt_Config`; `@OUTPUT
out_num_CompletedCount`, `out_num_ExceptionCount`, `out_txt_ExceptionDetail`,
`out_txt_SummaryReportPath`, `out_txt_ScreenshotPath`. Main body (lines 14–117):

```
Init (region "Initialise Values", L15-45): defaults, parse config, 'Load Config Data', 'Close Application'
BLOCK 'Get unprocessed items' (Business Exc typed / catch-all)         (L46-65)
  WorkQueues.GetWorkQueueItems (statecode=0) → 0 items = Business Exception
BLOCK 'Launch block' (Sys Unavail Exc typed / catch-all)               (L66-80)
  CALL 'Launch Application'
BLOCK 'Main Work block' (Sys Unavail Exc typed / catch-all)            (L81-94)
  CALL 'Process Work Queue Items' → GOTO 'End'
LABEL 'System Error' (L95-110): Close Application, build screenshot attachment list,
  send System Exception mail, IF SUE → rethrow, ELSE EXIT Code: 0 (see §A5 — NOT a rethrow)
LABEL 'Business Error' → GOTO 'End'                                    (L111-112)
LABEL 'End': Close Application, set 3 outputs                          (L113-117)
```
**Correction (verified against source):** only 3 of the 5 `@OUTPUT`s declared at the top of the
file are ever assigned — `out_num_CompletedCount`, `out_num_ExceptionCount`,
`out_txt_ExceptionDetail` (L115-117). `out_txt_SummaryReportPath` and `out_txt_ScreenshotPath`
(declared L12-13) have **no `SET` anywhere in the flow** — confirmed by a full-text search of the
file. A caller invoking this Desktop Flow and reading those two outputs will always get an empty
string. Treat this as a real (if minor) gap, not a naming-convention issue like §A4's casing
note — the values are simply never populated, not populated-under-a-different-name.

`FUNCTION` inventory (name / GLOBAL / params — UI-automation-only bodies summarized, not
transcribed; every UI stage inside them is out of scope per §B9):

| FUNCTION | GLOBAL | Params | Purpose |
|---|---|---|---|
| `Load Config Data` | Y | — | Parses `obj_Config` into ~25 typed locals + folder bootstrap (L118) |
| `Get Error` | Y | — | Capture error + call `Capture Error Screenshot` (L219) |
| `Fetch Data from Excel file` | N | `in_txt_InputFilePath`, OUT `out_txt_SampleId`, OUT `out_dtb_DataCollection` | Excel read + C# script extracts Sample ID + pivots to a fixed 7-column table (L232) |
| `Launch Application` | Y | — | Start/attach SampleManager, retry loop, Key-Vault login (L402) |
| `Get Results by Analysis and SampleId` | N | `in_txt_Analysis`, `in_txt_SampleId` | UI nav (L447) |
| `Open - Entry By Test window` | N | — | UI nav (L498) |
| `Get Components List` | N | OUT `out_lst_ComponentNames` | UI clipboard scrape (L532) |
| `Close Results Entry Analysis` | N | — | UI (L582) |
| `Close Results Entry` | N | — | UI (L606) |
| `Set Results Entry` | N | `In_txt_ComponentName`, `In_lst_ComponentNamesList`, `In_txt_ComponentValue`, 4× OUT | UI data-entry + popup handling (L622) |
| `Enter Results in App` | N | `In_dtb_FinalProduct`, `txt_SampleId`, OUT `out_dtb_filteredTable` | Per-row driver loop calling the above (L768) |
| `Create Summary Report` | N | `SummaryData`, `In_txt_DestinationPath`, `In_txt_SampleId`, OUT `out_txt_DestinationPath` | Writes summary Excel from template (L949) |
| `Send Email` | N | `In_txt_To_Email`, `In_txt_Cc_Email`, `In_txt_Subject`, `In_lst_Attachments` | Business report mail (L993) |
| `Send System Exception Mail` | N | same shape + `In_txt_ErrorMessage` | (L1026) |
| `Send Business Exception Mail` | N | same shape | (L1061) |
| `Send Consecutive Exception Mail` | N | same shape | (L1096) |
| `Close Application` | N | `In_txt_AppProcessName` (comma-list) | Kill by name then PowerShell force-kill fallback (L1132) |
| `Create New Folder` | N | `In_txt_RootFolder`, `In_txt_FolderName`, OUT `Out_txt_NewFolder` | (L1155) |
| `Log In Application` | N | `In_txt_AppUsername`, `In_txt_AppPassword`, OUT `Out_flg_Success`, OUT `Out_txt_Message` | (L1167) |
| `Mark Complete` | N | `In_obj_WorkQueueItem`, OUT `Out_obj_WorkQueueItem` | WorkQueues update + reset consecutive-exception state (L1200) |
| `Mark Exception` | N | same shape | 3-way BE/SUE/SE dispatch + consecutive-exception breach (L1226) — see §A7 |
| `Delete files from Folder` | N | `In_txt_FolderName` | (L1323) |
| `Move Emails` | N | `In_txt_MessageId`, `In_txt_DestinationFolder` | MarkAsRead_V3 + MoveV2 (L1338) |
| `Capture Error Screenshot` | Y | — | Single-arm-site screenshot (L1356) |
| `Process Work Queue Items` | Y | — | The item loop — see below (L1368) |
| `Open Complete Sample Window` | N | — | UI (L1575) |
| `Move Sample Id to Completed` | N | `In_txt_SampleId` | UI (L1607) |

`Process Work Queue Items` outline (L1368–1574):

```
LOOP WHILE WorkQueues.ProcessWorkQueueItem.ProcessWorkQueueItem(...) → obj_WorkQueueItem
    reset per-item flags/vars                                         (L1372-1384)
    BLOCK 'Process items block' (BE typed / SUE typed / catch-all)     (L1385-1468)
        decrypt obj_WorkQueueItem.Value (Key Vault + AES)              (L1405-1416)
        parse → obj_QueueItemData; validate exactly 1 mail attachment  (L1417-1431)
        create per-item folders; LOOP FOREACH attachment:
            validate extension against obj_Config['Excel_PatternsCsv']
            save file, 'Fetch Data from Excel file', 'Enter Results in App',
            'Create Summary Report', 'Send Email', 'Delete files from Folder',
            'Move Emails' → completed folder
    IF flg_ErrorOccurred → GOTO 'Mark Item as Exception'
    LABEL 'Mark Item as Completed' → CALL 'Mark Complete', num_ItemsCompleted+=1, GOTO 'Reset All'
    LABEL 'Mark Item as Exception' → CALL 'Mark Exception', 'Move Emails'→exception,
        'Close Application', reset app-state flags
    LABEL 'Reset All':
        BLOCK 'Data gateway block' (swallow-all) → Key Vault DB secret,
            IF obj_Config['Ctrl_SendDataToGateway']='True' → External.RunFlow
            (telemetry payload built from obj_WorkQueueItem + obj_QueueItemData fields)
        IF txt_ExceptionType = 'System Unavailable Exception' → rethrow (halts run)
        IF flg_HaltRun = True → EXIT LOOP                              (§A7 breach)
        reset per-item vars
        BLOCK 'Launch block' → CALL 'Launch Application'
        IF (FlowControl.IfSafeStop ShouldStop: True) THEN EXIT FUNCTION END   (§A6)
END LOOP
```

### A4. Variable naming convention

| Prefix | Meaning | Example |
|---|---|---|
| `txt_` | String | `txt_ExceptionMessage` |
| `num_` | Number | `num_MaxRetryLimit` |
| `flg_` | Boolean | `flg_HaltRun` |
| `obj_` | Custom object (parsed JSON) | `obj_Config`, `obj_WorkQueueItem` |
| `lst_` | List | `lst_MailItems` |
| `dtb_` / `dtr_` | Datatable / Datatable row | `dtb_FinalProduct`, `dtr_CurrentItem` |
| `dt_` | DateTime value | `dt_CurrentDateTime` |
| `ins_` | Instance handle (Excel) | `ins_ExcelInstance` |
| `In_`/`Out_` (function param) | Function input/output parameter | `In_txt_Config`, `Out_flg_Success` |

**BP `Collection` → PAD `dtb_` (DataTable) or `obj_` (custom object) — pick by usage, not by
type alone.** A BP `Collection` is, by itself, ambiguous: it becomes a PAD **DataTable**
(`dtb_`/`dtr_`) when it is used as tabular/row-oriented data (e.g. the Excel-derived
`dtb_FinalProduct` in `Enter Results in App`), but a PAD **custom JSON object** (`obj_`) when it
is really a key/value bag being used for lookups (e.g. `obj_Config`, `obj_QueueItemData` —
both originate from BP `Collection`s carrying config/queue-item data, but are parsed as JSON
objects and indexed with `obj_Config['Key']`, never iterated as rows). **Rule:** if the BP page
indexes the collection by a field name to look up a single value → `obj_`; if it loops over rows
or writes tabular output → `dtb_`/`dtr_`. Don't default to DataTable just because the BP source
type is `collection`.

**`In_`/`Out_` casing — one canonical rule, not a per-function judgment call.** New/generated
`FUNCTION` parameters always use capitalized `In_`/`Out_` (`In_txt_Config`, `Out_flg_Success`),
matching the majority convention and the `@INPUT`/`@OUTPUT` directive style. The lowercase
`in_`/`out_` instances that exist in a few functions (`Fetch Data from Excel file`,
`Enter Results in App`) are legacy inconsistency in the current codebase, not a pattern to
replicate — generated code should not try to match whichever casing a neighboring function
happens to use; always emit the capitalized form.

**`GLOBAL.` qualification rule:** a non-`GLOBAL` `FUNCTION` must prefix `GLOBAL.` to read or
write a variable owned by the main body or a `GLOBAL FUNCTION` (e.g. `GLOBAL.obj_Config`,
`GLOBAL.num_ConsecutiveExcLimit`). Omitting it silently creates/reads a **local** shadow
variable instead of raising an error — this was the root cause of the historical
`Variables.IncreaseVariable`-on-`GLOBAL.var` bug documented in `PID171_PAD_FIX_NOTES.md` (fixed
here by using `SET GLOBAL.var TO GLOBAL.var + 1` instead of `Variables.IncreaseVariable`, which
cannot target a `GLOBAL.`-prefixed variable from a non-`GLOBAL` function at all).

**One remaining case-sensitivity rule that isn't a style choice:** the top-of-file `@OUTPUT`
directive name and the variable actually `SET` at the end of the flow **must match exactly**
(case-sensitive) — PAD does not normalize this. When adding a new `@OUTPUT`, verify by grep which
variable name is really assigned; don't assume it matches the prefix table's casing. (This is
also why §A3 flags `out_txt_SummaryReportPath`/`out_txt_ScreenshotPath` as dead outputs — nothing
`SET`s them at all, under any casing.)

### A5. Error-handling architecture

**3-tier exception taxonomy**, identical strings to BP's `<exception type="...">`:
`Business Exception`, `System Exception` (default/untyped), `System Unavailable Exception`.

**Dispatch template** (used at every `BLOCK` boundary that needs typed handling):
```
BLOCK '<name>'
ON BLOCK ERROR '<Exact BP Exception Type String>' IsUserDefinedErrorCode: True
    <handler statements — NO IF/branching allowed here, see below>
ON BLOCK ERROR
    <catch-all handler>
END
    <body>
END
```
**Hard constraint:** an `ON BLOCK ERROR` handler body is a **fixed action sequence** — it cannot
contain `IF`. Any "was this the last retry attempt" decision must be a plain `IF` placed **after**
the enclosing `LOOP`, checking a flag the handler set (e.g. `flg_QueueUpdateSuccess`,
`flg_FetchApiSuccess`) — never inside the handler. (This is the exact bug class the historical
fix notes call EB-2/F4 — already correctly applied throughout `_11_managed`.)

**Raise template:**
```
FlowControl.ThrowCustomError CustomErrorCode: $'''<Exact BP Exception Type String>''' CustomErrorMessage: <message expr>
```

**Single-arm-site screenshot pattern:** `Get Error` (GLOBAL) always calls `Capture Error
Screenshot` (GLOBAL), which only fires if `flg_Screenshot = True` and immediately sets it back to
`False` — so a screenshot is captured at most once per error chain, at the first handler that
armed `flg_Screenshot`, not re-triggered by every subsequent `Get Error` call up the stack.

**Asymmetric exit — confirmed, worth stating plainly:** in the Performer's top-level `LABEL
'System Error'` (L95–110), a plain `System Exception` (or `Business Exception`, which never
reaches this label) results in `EXIT Code: 0 ErrorMessage: txt_FailedItemsLog` — **a successful
process exit** — after the notification email is sent. Only `System Unavailable Exception`
actually re-throws (`FlowControl.ThrowCustomError`), which is what Cloud_Main's
`Desktop_Flow_-_Performer_-_*` connector call sees as a failure. **Practical effect:** Cloud_Main
(and therefore the Schedule flow's failure `Terminate`) only reacts to System-Unavailable-class
failures at the run level; an ordinary System Exception is handled entirely inside the desktop
flow (logged, emailed, exits clean) and never surfaces as a Cloud Flow failure. Confirm this is
the intended severity model before treating any generated code that does otherwise as a bug.

### A6. Graceful stop

Confirmed via full-text search of both desktop flows: **one** occurrence, in `Process Work Queue
Items`, immediately after the end-of-loop `'Launch block'` (L1570):
```
IF (FlowControl.IfSafeStop ShouldStop: True) THEN
    EXIT FUNCTION
END
```
This is PAD's actual equivalent of BP's Main-Page `Stop?` / `IsStopRequested()` decision. Effect:
exits `Process Work Queue Items` entirely (not just the current iteration), which returns control
to `Main_copy`'s `'Main Work block'`, which then falls through to the normal `LABEL 'End'` cleanup
— i.e. a **graceful** stop after the current item finishes, identical in intent to BP's check.
The Loader has **no** such check anywhere — this matches BP's Main Page, where
`IsStopRequested()` appears only in the performer-side loop, never in the mail-fetch/enqueue
pages. **Correction:** BP's Main Page is not the *only* place `IsStopRequested()` is used —
the orphaned `Mark leftout Items as Exception` page (§B11/§B14/§B16) has its own, independent
`Stop?`/`IsStopRequested()` decision guarding its own `Get Next Item` drain loop. Since that BP
page has no caller anywhere (confirmed in the Review Notes below) and no PAD counterpart exists,
this second occurrence has no bearing on the current PAD flows — but if that orphan page is ever
resurrected, it would need its own `FlowControl.IfSafeStop` check too, not just the one already
present in `Process Work Queue Items`.

**Generation rule:** any new per-work-item loop added to the Performer must include this exact
`FlowControl.IfSafeStop` check at the same position (end of loop body, after any per-item
relaunch); loops in the Loader do not need it unless a future BP page explicitly adds a stop
check there too.

### A7. Consecutive-exception handling

State: `GLOBAL.num_ConsecutiveExcCount` (starts 0), `GLOBAL.num_ConsecutiveExcLimit` (from config
`Ctrl_ConsecutiveExceptionLimit`, parsed in `Load Config Data`), `GLOBAL.txt_PreviousExceptionMessage`.

**BP ground truth** (traced directly from the `Mark Item As Exception` page in
`PID_0171.bprelease` via `bp_report_v2.py`, not from `_fixed.txt` or the fix notes — those turn
out to be themselves an approximation, see below): on a plain System Exception, the page's
`Previous Exception?` decision compares `[Previous Exception Detail] = [Exception Detail]`.
- **Match** → `Count`: `Consecutive Exception Count = [Consecutive Exception Count] + 1` →
  `Limit?` → breach if `>= [Consecutive Exception Limit]`, otherwise continue with the streak
  still counted.
- **No match** → `Reset Consecutive Exception Indicators`: `Previous Exception Detail =
  [Exception Detail]` (set to the *current* exception, not cleared), `Consecutive Exception Count
  = 0` — and this path is **terminal for the current item**: it does *not* also fall through to
  `Count`/`Limit?`. So a message change doesn't just reset the streak, it means *this* occurrence
  isn't counted at all — only seeds `Previous Exception Detail` for the *next* comparison. Net
  effect: breaching at `Consecutive Exception Limit = 3` requires **4** total consecutive
  identical-message System Exceptions (the 1st seeds the comparison, the 2nd/3rd/4th each match
  and increment to 1/2/3), not 3.

`_fixed.txt`'s documented design intent (`docs/PID171_PAD_FIX_NOTES.md` §2.1: "on a match it
increments the counter... otherwise resets it to 1 with the new message") is **already a
simplification of true BP behavior**, not an exact port — "reset to 1" treats the mismatching
exception as the first counted occurrence, whereas BP's "reset to 0, terminal" does not count it
at all, so `_fixed.txt`'s version breaches one item sooner than BP would (3 identical messages
instead of 4). `_11_managed` (§A8 D6 below) deviates further still, from *both* BP and
`_fixed.txt`, by never resetting at all.

- **Reset to 0** on any successful item completion (`Mark Complete`, L1222-1223) or on a
  **Business Exception** outcome (`Mark Exception`, L1256-1257). **Correction:** a System
  Unavailable Exception does **not** reset the counter — the SUE branch (L1258-1273) only updates
  the queue-item status to `ITException`; it never touches `GLOBAL.num_ConsecutiveExcCount` or
  `GLOBAL.txt_PreviousExceptionMessage` (confirmed: neither variable name appears anywhere in
  L1258-1273). In practice this rarely matters because SUE always re-throws and halts the run
  (§A5), but as written, only a successful item and a Business Exception reset the streak; only a
  **plain System Exception** advances it (see next bullet), and a SUE neither resets nor
  increments it.
- **Increment** in `Mark Exception`'s `ELSE` branch (L1274-1281): if
  `GLOBAL.txt_PreviousExceptionMessage = GLOBAL.txt_ExceptionDetail` (identical failure message
  to last time) or not, either way `num_ConsecutiveExcCount += 1` (both branches increment; the
  equality check only decides whether `txt_PreviousExceptionMessage` is refreshed) — read the
  code at L1276-1281 exactly, not from a shorthand summary, if reproducing this logic. **This is
  itself a real deviation, newly identified in this review — see §A8 D6:** the documented design
  intent for this exact logic (`docs/PID171_PAD_FIX_NOTES.md` §2.1: "on a match it increments the
  counter... otherwise resets it to 1 with the new message") and `_fixed.txt` (L899-903) both
  implement *reset-to-1-on-mismatch*, so the breach was meant to fire on N **identical**
  consecutive System Exceptions. `_11_managed` never resets to 1 — it always increments — so as
  actually implemented the breach fires on N consecutive plain System Exceptions of **any** kind,
  whether or not the message repeats.
- **Breach** (`num_ConsecutiveExcCount >= num_ConsecutiveExcLimit`, L1283-1302): update the queue
  item status via `WorkQueueItemStatus.ITException` with a message reporting the limit and last
  exception, `CALL 'Send Consecutive Exception Mail'` (a **dedicated** template, not the generic
  System Exception one — disarms `GLOBAL.flg_SendExceptionEmail` right after so the top-level
  `System Error` path doesn't send a duplicate), then `SET GLOBAL.flg_HaltRun TO True`.
- `flg_HaltRun` is checked once per item, **after** that item's Data Gateway telemetry block
  completes (L1552-1554: `IF flg_HaltRun = True THEN EXIT LOOP END`) — so a breach does not skip
  cleanup/telemetry for the item that tripped it, matching BP's `Mark Item As Exception` page
  `TERMINATE`-on-N-identical-failures circuit breaker exactly (BP default limit = 3, same config
  key family).

### A8. Deviations vs. BP source / vs. `_fixed.txt`

| # | Deviation | Direction | Confidence |
|---|---|---|---|
| D1 | **STOP — needs confirmation.** `_fixed.txt`'s Loader (and the BP source's `Populate Queue`/Main-Page logic) explicitly branches on `obj_CurrentMail.hasAttachments = False` to send a Business Exception mail and move the mail to the exception folder, skipping enqueue. `_11_managed`'s Loader (L108-113) only conditionally *builds* the attachment list (`IF hasAttachments = True THEN LOOP...END`) — if False, `lst_Attachments` stays empty and the mail is **still enqueued** with 0 attachments. The Performer's own `Process Work Queue Items` *does* separately reject 0-attachment items as a Business Exception (L1421-1425) — so the item is eventually caught, just one stage later (post-decrypt, in the Performer, instead of pre-encrypt in the Loader) and without the immediate move-to-exception-folder/notify step at Loader time. Confirm with the process owner whether this later-catch behavior is the intended simplification or an unintended regression before treating either as "correct" in generated code. | Loader lost a branch | Confirmed by direct comparison |
| D2 | AES key for the queue-item payload is fetched from Azure Key Vault at runtime (`GetSecret` on `obj_Config['Sec_EncDecSecret']`, then cleared from memory after use) rather than using the config value directly as the key. | Security improvement over `_fixed.txt` | Confirmed |
| D3 | Sender allow-list is a comma-split, lower-cased list (`lst_SenderMailList`, filtered via `Variables.FilterList`) instead of a single exact-match string comparison. | Enhancement over `_fixed.txt` | Confirmed |
| D4 | `Mark Exception` fully implements the BE/SUE/SE 3-way dispatch with a dedicated `Send Consecutive Exception Mail` — more complete than the `_fixed.txt` snapshot, which only documents the reasoning, not this exact final code. | Matches BP intent, more complete than `_fixed.txt` | Confirmed |
| D5 | Application login password and the Data Gateway DB password are both fetched from Key Vault per-use and cleared immediately after (`SET txt_...Password TO ''`) rather than held for the item's duration. | Security hardening, no BP equivalent (BP has no Key Vault concept) | Confirmed |
| D6 | `Mark Exception`'s plain-System-Exception branch (Performer L1274-1281) increments `num_ConsecutiveExcCount` unconditionally in both arms of its message-comparison `IF`, instead of resetting to 0 (BP ground truth, terminal-on-mismatch — §A7) or resetting to 1 (`_fixed.txt`'s already-approximate port, L899-903) when the message does *not* match the previous one. Effect: the circuit breaker fires on N consecutive plain System Exceptions of *any* kind, not N *identical* ones as BP actually implements (nor even the looser N-identical-with-one-fewer-required that `_fixed.txt` implements). This is the largest of the two deviations stacked on top of each other — confirm against BP ground truth (§A7), not `_fixed.txt`, when fixing it. | Behavior regression vs. both BP source and `_fixed.txt` | Confirmed by direct comparison against BP source (`Mark Item As Exception` page) and `_fixed.txt` L891-904 |

---

## PART B — BP → PAD MAPPING DESIGN

### B9. Scope & ground rules

- **Main process only**: `PID_171_US_Process_LIMS_Prelude`. The sibling process
  `RPA_Sharepoint_API_ConfigFile_Download` is a call target whose logic gets inlined as steps
  within the caller (per the user's own instruction — a *sub-process* call is not separately
  translated, its steps go inline). **VBOs are handled differently — corrected from an earlier
  draft of this rule, see §B_VBO below:** a VBO is structurally a Process (a `Start`→...→`End`
  page graph using the same 18 stage types, §B12 applies uniformly), just packaged as a reusable
  object with normal published methods instead of a runnable process. Each VBO **method** (one
  published page inside the VBO) becomes its own PAD `FUNCTION`, called via `CALL '<method
  name>' ...` exactly like a `SubSheet` call — not textually inlined — matching how `_11_managed`
  already structures `Get Results by Analysis and SampleId`, `Set Results Entry`, etc. as their
  own `FUNCTION`s (§A3), one per `PID_0005_Object_US_SampleResultsEntry` method.
- **UI-automation selectors are out of scope**, not "VBOs are out of scope" — see §B_VBO for the
  precise boundary (some VBO stage types translate fine; only selector-bearing ones don't). Any
  BP stage whose target action needs an `<appdef>`/ControlRepository selector gets:
  ```
  # TODO: UI selector required - <BP stage name>, <BP action name>
  ```
  instead of an invented `UIAutomation.*` call. Do **not** fabricate `appmask[...]` selector
  paths — every real one in `_11_managed` was captured by hand in Power Automate Desktop's
  recorder; a generator has no way to produce a working one from BP XML alone.
- **BP Credential Manager → PAD Azure Key Vault, as a general rule, not just for the AES key.**
  BP has its own credential store, accessed via `Blueprism.Automate.clsCredentialsActions ::
  Get`/`:: Set` (confirmed real — used in the sibling `RPA_Sharepoint_API_ConfigFile_Download`
  process for Azure/SharePoint credentials; not called anywhere in the main process itself, which
  is why it doesn't appear in §B13's table, but the mapping applies if it's ever encountered).
  PAD has no equivalent local credential store — `_11_managed` fetches every secret (AES
  encryption key, SampleManager login password, Data Gateway DB password — §A8 D2/D5) from Azure
  Key Vault at the point of use via `External.InvokeCloudConnector ... shared_keyvault ...
  OperationId: 'GetSecret'`, then clears the variable immediately after use. **Rule:** any BP
  `clsCredentialsActions :: Get` stage maps to this same Key Vault `GetSecret` pattern, keyed by
  a `Sec_*`-style config value naming the secret (as `obj_Config['Sec_EncDecSecret']`,
  `obj_Config['Sec_AppSecret']`, `obj_Config['Sec_DBSecret']` already do).

### B_VBO. VBO transformation approach

A VBO ("Business Object") is structurally the same thing as a Process — a `Start`→...→`End` page
graph built from the same 18 canonical stage types (§B12 applies to every one of them, no
separate rule set) — packaged as a reusable object with published methods instead of a runnable
top-level process. The one structural difference: a VBO's methods are far more likely to use the
5 stage types that model interacting with an external application: `NAVIGATE`, `READ`, `WRITE`,
`WAIT`, `CODE`.

**How to translate a VBO call:**
1. A Process-side `ACTION` stage that calls a VBO method (`<resource object="..." action="...">`)
   translates the same way as a `SubSheet` call: `CALL '<VBO method name>' <params>`.
2. The VBO method itself becomes its own `FUNCTION '<method name>'` — its `Start`/`End` map to
   `FUNCTION`/`END FUNCTION` exactly like a Process page (§B12's `START`/`END` row), and every
   other stage inside it follows the same §B12 rules as any Process page (`CALCULATION`,
   `DECISION`, `LOOP`, `CODE`, static `WAIT`, etc. — no special VBO variant of these rules).
3. Within that method, split by stage type:
   - **`CODE`** and **static `WAIT`** (a fixed-duration pause, e.g. BP `WaitStart` with only a
     `<timeout>` and no UI-element condition) — translate normally per §B12's `CODE`/`WAIT` rows.
   - **`NAVIGATE`, `READ`, `WRITE`, and dynamic `WAIT`** (a `WaitStart` whose condition targets a
     UI element/window — the PAD equivalent is `UIAutomation.WaitForWindowContent...`, which
     itself needs a selector) — these need an `<appdef>`/ControlRepository selector and are out
     of scope per §B9: emit the `# TODO: UI selector required` stub, not an invented call.
   - Everything else (`CALCULATION`, `MULTIPLECALCULATION`, `DECISION`, `LOOP`, `BLOCK`/`RECOVER`/
     `RESUME`, `EXCEPTION`, nested `ACTION`/`SubSheet` calls to other VBO methods) translates
     exactly as it would on a Process page.

This is exactly the shape already present in `_11_managed`'s Performer: `Get Results by Analysis
and SampleId`, `Open - Entry By Test window`, `Get Components List`, `Close Results Entry
Analysis`, `Close Results Entry`, and `Set Results Entry` are each one `FUNCTION` per
`PID_0005_Object_US_SampleResultsEntry` method (§A3), called via `CALL` from `Enter Results in
App` — not inlined as one giant flattened block. Building a new VBO-method `FUNCTION` should
follow that same one-`FUNCTION`-per-method pattern even when its body is mostly `# TODO` stubs
because every action inside happens to be UI-selector-bound.

### B_FUSION. VBO call-fusion patterns — not every BP stage maps 1:1 to a PAD action

Some BP VBO idioms span **two or more adjacent stages that must collapse into a single PAD
action**, not be translated stage-by-stage. Treating every `ACTION` stage as an independent
1:1 lookup (one BP method name → one PAD template) gets these wrong — it emits two PAD lines
where one is correct, and the intermediate BP-side variable often doesn't survive into PAD at
all.

**Worked example, confirmed against the real ground truth** (`docs/pad-reference/
DF_PID_171_US_LIMS_Prelude_Main.robin.txt` L249, and the `Read Excel As Collection` BP page,
subsheetid `eeeb6765-9d9f-4374-b7cd-d5ca8f3dfa61`):

```xml
<stage type="Action" name="Create Instance">
  <outputs><output type="number" name="handle" stage="handle" /></outputs>
  <resource object="MS Excel VBO" action="Create Instance" />
</stage>
<stage type="Action" name="Open Excel">
  <inputs><input type="number" name="handle" expr="[handle]" />
          <input type="text" name="File name" expr="[fileName]" /></inputs>
  <outputs><output type="text" name="Workbook Name" stage="Workbook Name" /></outputs>
  <resource object="MS Excel VBO" action="Open Workbook" />
</stage>
```

translates to **one** PAD line, not two:

```
Excel.LaunchExcel.LaunchAndOpenUnderExistingProcess Path: in_txt_InputFilePath Visible: False ReadOnly: False UseMachineLocale: False Instance=> ins_ExcelInstance
```

Note `handle` never appears in the PAD output at all — BP's "acquire a handle, then use it"
two-stage idiom is fully absorbed into `LaunchAndOpenUnderExistingProcess`'s single `Instance`
output. The mirror pattern exists on the close side: BP's `Close Workbook` + `Close Instance`
(same VBO, same handle-chaining shape) collapse into one `Excel.CloseExcel.Close Instance:
<ins>` call (confirmed at L253/L980 — `docs/pad-reference/vbo-action-mapping.md`'s Excel table
already records both fused pairs as single rows, not two).

**The general structural signal, independent of which VBO it is:** a numeric-typed output on
one `ACTION` stage feeding a same-named/same-typed numeric input on the very next `ACTION`
stage (no branching, no other stage in between) is BP's own convention for a resource-handle
handoff — "acquire a resource, then use it." This is detectable **without understanding what
either stage does** — it's a shape in the BP XML (`<output type="number" name="handle"
stage="handle">` on stage N, `<input type="number" name="handle" expr="[handle]">` on stage
N+1), not a semantic judgment. Any two adjacent same-VBO `ACTION` stages matching this shape
are a **fusion candidate**, whether or not a specific fusion template for that exact VBO pair
has been curated yet.

**How this must be represented and used (binding on Task 1's schema design and the AST
builder):**
1. A fusion candidate detected by the structural signal, but with **no matching entry** in
   `mapping/vbo_catalogue.yaml`'s fusion-pattern data, is **not** auto-fused — it gets a
   `ReviewFlag` naming both stages and the detected handoff, for curation (§B_FUSION is a
   detection mechanism, not a rule that invents new PAD syntax on its own — every fused
   template still needs the same real-call citation discipline as everything else in this
   document).
2. A fusion candidate that **does** match a curated pattern (like the two Excel pairs above)
   fuses per that pattern's literal template — the intermediate stage(s) it names as vestigial
   produce no PAD output of their own.
3. This is the same kind of bracket-pairing problem `ast/builder.py` already solves for
   `WaitStart`/`WaitEnd` and `LoopStart`/`LoopEnd` (§B12) — implement it as a comparable pass,
   not a special case bolted onto the generator.

**Known fused pairs so far** (from this document's ground-truth analysis; add more as they're
found during curation — see `mapping/vbo_catalogue.yaml`'s fusion-pattern rows for the current
complete list, this document doesn't duplicate that data):
- `MS Excel VBO :: Create Instance` + `:: Open Workbook` → `Excel.LaunchExcel.
  LaunchAndOpenUnderExistingProcess` (`Create Instance` vestigial)
- `MS Excel VBO :: Close Workbook` + `:: Close Instance` → `Excel.CloseExcel.Close`
  (`Close Workbook` vestigial)

### B10. Methodology

For each BP page: start at its `Start` stage → follow `onsuccess`/`ontrue`/`onfalse` links,
reconstructing the **implicit** Block→Recover edge (BP never encodes this edge in XML — it must
be inferred from spatial containment or, more reliably, by treating every `Recover` stage as the
error-continuation of the nearest enclosing `Block` in the same page) → for each stage in order:
1. Resolve stage type (§B12) and, for `ACTION` stages, the VBO/method called (§B13).
2. Resolve inputs/outputs: BP `<input>`/`<output>` (and legacy `<o>`, treat as `<output>`) map to
   PAD named parameters / `=>` output vars using the naming rules in §A4.
3. Translate BP expressions: `[Data Item]` → bare variable reference or `%var%` inside a `$'''...'''`
   string; string concatenation (`&`) → PAD `+`; `Trim(...)`/`Lower(...)` → `Text.Trim`/
   `Text.ChangeCase` action calls (BP has expression functions PAD does not — these become
   separate action lines, they cannot be inlined into a PAD expression).
4. Emit the PAD construct (§B12 template) and continue to the next linked stage until `End`.

Each BP **page** becomes one PAD `FUNCTION '<page name>'` (or the un-named main body, for Main
Page) — never a separate workflow file. This is the single largest correction versus the old
`src/flowsmith` generator (§A of the earlier gap-analysis docs): 1 BP process → 1 Desktop Flow
with pages as `FUNCTION`s, not 1 BP page → 1 workflow.

**Tooling note:** re-deriving BP-side facts (page/stage inventories, edges, exception strings,
environment variables, orphan-page checks) should go through this repo's existing parser —
`scripts/bp_parser_v2.py` (single artefact, `parse()`/`parse_element()`), `scripts/
bp_release_parser.py` (the whole `.bprelease` container — processes, objects, env vars in one
call), and `scripts/bp_report_v2.py` (renders either into a human-readable `.md`, all UUIDs
resolved to names) — rather than ad hoc `grep`/manual XML reads. One caveat when cross-checking
against this document's stage counts (§B14): those counts are **raw** `<stage>` element counts
per page (matching what a direct XML `<subsheetid>` tally gives, and what this document's Review
Notes independently re-verified 9/9 against). `bp_parser_v2.py`'s `stats.parsed`/per-page counts
are smaller because they exclude the 4 skip-types (`Anchor`, `Note`, `SubSheetInfo`,
`ProcessInfo`) — for the whole main process, parsed 706 + skipped 85 = 791 raw, matching this
document's totals; the same offset applies per-page. Don't treat a `bp_parser_v2.py` count that's
lower than this document's as a discrepancy — confirm which convention you're comparing first.

### B11. Loader/Performer split

**Hard boundary: BP stage `85fbb578` (`Get Next Item`, Main Page).**

| BP side | PAD side |
|---|---|
| Start → Get User Name → Download Config File (external process, inline its 2-3 steps) → ConvertConfigFile As Collection → Delete Config File → **Get Mails** page → **Populate Queue** page → `[85fbb578] Get Next Item` | `DF_PID_171_US_Loader`'s main body: Init → `Load Config Data` → `BLOCK 'Get unprocessed emails'` (= Get Mails) → `BLOCK 'Add to Queue Block'` (= Populate Queue) |
| `[85fbb578]`/`[7652dc4c] Get Next Item` (true branch) → Save Attachments → Read Input Data From Excel → Launch_Sample Manager → Result Entry → Summary_Report → Input File Management → Mark as read mail → Mark Item As Completed / Mark Item As Exception → DataGateway → Reset Global Data → loop back to `[7652dc4c]` | `DF_PID_171_US_LIMS_Prelude_Main`'s `Process Work Queue Items` `LOOP WHILE WorkQueues.ProcessWorkQueueItem...` — one iteration per BP loop-back |

**STOP — open question:** the BP page **"Mark leftout Items as Exception"** (own `Get Next Item`
at stageid `a5f6f46f`, an end-of-run drain loop) has no confirmed caller in the traced BP flow
(Block containers don't carry `onsuccess`, so this may be reachable via a path the trace missed)
**and no counterpart was found anywhere in `_11_managed`'s Performer** (`Grep` for a second
`ProcessWorkQueueItem`/`GetWorkQueueItems` drain-loop pattern found none). Confirm with the
process owner whether this page is (a) genuinely dead/orphaned in BP, (b) intentionally dropped
in the PAD rebuild, or (c) missing and needs to be added — do not silently port or silently drop
it.

### B12. BP stage-type → PAD construct rules

All templates below are literal syntax confirmed present in `_11_managed` (line-cited); fill in
`<...>` placeholders per-stage.

| BP stage type | PAD construct / template |
|---|---|
| `START` / `END` | No-op markers; drive the enclosing `FUNCTION`'s boundaries. Main Page's `Start`/`End` drive the flow's `@INPUT`/`@OUTPUT` directives (§A3 shows the real ones). |
| `ACTION` (VBO call) | See §B13 for the specific target; general shape: `<Module>.<Method> <Param>: <expr> ... <OutParam>=> <var>` (e.g. L1211 `WorkQueues.UpdateProcessingNotes.WithProcessingNotes WorkQueueItem: obj_WorkQueueItem ProcessingNotes: '...'`). |
| `ACTION` (SubSheet call, `is_subsheet_call=True`) | `CALL '<page name>' <Param>: <expr> ... <OutParam>=> <var>` (e.g. L1452 `CALL 'Fetch Data from Excel file' in_txt_InputFilePath: txt_AttachmentFilepath out_txt_SampleId=> txt_SampleId out_dtb_DataCollection=> dtb_FileData`). |
| `DECISION` | `IF <translated expr> THEN <true-branch> ELSE <false-branch> END` (e.g. L1421 `IF lst_MailAttachments.Count = 0 THEN ...`). |
| `CHOICE` | **Not present in PID_171 (0 occurrences)** — do not implement speculatively. |
| `CALCULATION` / `MULTIPLECALCULATION` | One `SET <var> TO <translated expr>` per assignment (a `MULTIPLECALCULATION` fans out to N `SET` lines). Sanitize BP identifiers with spaces into valid PAD variable names using the §A4 prefix scheme (e.g. BP `Exception Type` data item → PAD `txt_ExceptionType`). |
| `CODE` | `Scripting.RunDotNetScript Imports: '...' Language: System.DotNetActionLanguageType.CSharp Script: $'''...''' @'name:<param>': ... @<Output>=> <var>` — confirmed C#, not PowerShell, in real use (L268-388, L75-80). |
| `WAIT` (paired `WaitStart`/`WaitEnd` via `<groupid>`) | `WAIT <seconds expr>` — for a wait-on-a-value-with-timeout pattern (BP `WaitStart` with a condition + timeout), use PAD's `WAIT (<condition action>) FOR <seconds> ON ERROR ... END` shape (e.g. L404 `WAIT (UIAutomation.WaitForWindowContent.WindowToContainElement ...) FOR num_Delay_M ON ERROR ... END`). |
| `LOOP` (`LoopStart`/`LoopEnd` via shared `<subsheetid>`) | `LOOP FOREACH <item> IN <collection> ... END` for a collection loop, `LOOP <var> FROM <start> TO <end> STEP <n> ... END` for a counted loop (BP retry-count loops map here — e.g. L243 `LOOP num_RetryCount FROM 1 TO GLOBAL.num_MaxRetryLimit STEP 1`); `EXIT LOOP` / `NEXT LOOP` map directly. |
| `EXCEPTION` (throw) | `FlowControl.ThrowCustomError CustomErrorCode: $'''<exact BP exception type string>''' CustomErrorMessage: <expr>` — **preserve the BP type string verbatim**, it is matched later by a typed `ON BLOCK ERROR` handler (§A5). |
| `RECOVER` / `RESUME` | **No standalone PAD emission.** They are structural markers consumed by the enclosing `BLOCK`'s `ON BLOCK ERROR` handler (§A5 template) — a `Recover` stage's contents become the handler body; its paired `Resume` stage is simply where normal flow continues after the handler, i.e. the code immediately following the `END` of the `BLOCK`. |
| `BLOCK` | Emit `BLOCK '<name>' ON BLOCK ERROR ... END <body> END` **only** when a `Recover` exists in scope for this Block. BP also uses `Block` as a pure visual grouping container with no handler — those get no `BLOCK` wrapper (there's no error handling to translate), but the BP grouping intent is worth preserving as a PAD `**REGION <name>` / `**ENDREGION` around the contained stages, exactly as `_11_managed`'s `Load Config Data` groups its config-derived variables into named regions (`**REGION System Variables`, `**REGION Time Variables`, etc., §A3). This is a developer/generator **style choice**, not a mechanical 1:1 rule — use it where it keeps generated output readable, skip it for a trivial 1-2-stage grouping. |
| `COLLECTION` / `DATA` | Emit nothing at declaration time unless it has a BP `initial_value` (→ one `SET var TO <value>` in the enclosing `FUNCTION`'s init region) or is `exposure=Environment` (→ treat as a config-driven value read from `obj_Config['<Key>']` in `Load Config Data`, per §B13's config row, not a bare local `SET`). |
| `ANCHOR` | Pure routing artifact (a visual line-break for a long edge) — always skip, no AST node, no PAD output of any kind. |
| `NOTE`, `SUBSHEETINFO`, `PROCESSINFO` | No AST node (never a translatable stage), but **if the stage carries text** (a `Note`'s body, or a `SubSheetInfo`/`ProcessInfo`'s narrative) it may be emitted as a plain `# <text>` comment at the equivalent position in the generated `FUNCTION` — useful as a page-header comment or an inline annotation carried over from the BP diagram. Optional, not required; never skip a `Note` silently if the text conveys BP-author intent worth keeping visible in the PAD source. |

### B13. VBO / system-object → PAD action mapping

**Maintained as a separate, living file:** `docs/pad-reference/vbo-action-mapping.md`. Every
BP VBO method → PAD action row lives there, grouped by VBO (Work Queues, Excel, Outlook, Utility
VBOs, the UI-automation objects that are out of scope, and PAD-native constructs with no BP
origin), plus the row format to follow when a new VBO action is found during future work. Keeping
it out of this architecture document means it can grow without repeated edits to this file, and
without risking drift between two copies of the same table.

Two rules from that file worth restating here since they're binding, not just data: (1) never add
a row without a confirmed real call — a missing mapping is a `**STOP**` row citing "no confirmed
PAD equivalent found", not an invented plausible-looking action name; (2) the BP Credential
Manager (`clsCredentialsActions :: Get`/`:: Set`) → PAD Azure Key Vault `GetSecret` rule (§B9)
applies to any VBO credential fetch, not only the ones already in the table.

**When a BP VBO has no entry here at all** (not PID_171's VBOs — a future automation's), search
`docs/pad-reference/pad-action-index.yaml` (task-prompts doc Task 0) before concluding no PAD
equivalent exists. That file indexes PAD's *full* action surface (name + description, from the
official action-reference PDF) merged with confirmed syntax mined from every real PAD source file
in this repo — broader than this table, which only covers what PID_171 happens to use. Its
`confidence: confirmed` rows are usable the same way this table's rows are; its
`confidence: description-only` rows name a *candidate* action family with no verified syntax —
never promote one of those into this table without confirming the real call first (in a live PAD
sample, or PAD Studio itself).

### B14. Page-by-page crosswalk

All 24 BP pages (Main Page + 23 subsheets). "PAD target" cites the real `_11_managed` `FUNCTION`
where a direct counterpart exists; where a BP page's logic is spread across several `FUNCTION`s
or folded into the main body, all are listed.

| # | BP page | Stages | Loader/Performer | PAD target |
|---|---|---|---|---|
| — | **Main Page** | 119 | split page (§B11) | Loader main body (pre-`Get Next Item`) + Performer main body (post-`Get Next Item`) |
| 1 | Get Mails | 28 | Loader | `Fetch Emails from Mailbox` |
| 2 | Populate Queue | 37 | Loader | Loader main body `BLOCK 'Add to Queue Block'` |
| 3 | Save Attachments | 40 | Performer | Inlined into `Process Work Queue Items`' attachment loop (L1437-1467) — BP's separate delete-existing/save/get-files/exists-check sequence collapses to `File.ConvertFromBase64` since the PAD design decrypts the attachment bytes directly from the queue payload rather than re-fetching from Outlook |
| 4 | Read Input Data From Excel | 53 | Performer | `Fetch Data from Excel file` |
| 5 | Launch_Sample Manager | 30 | Performer | `Launch Application` |
| 6 | Result Entry | 159 | Performer | `Get Results by Analysis and SampleId`, `Open - Entry By Test window`, `Get Components List`, `Close Results Entry Analysis`, `Close Results Entry`, `Set Results Entry`, `Enter Results in App` (region-grouped, all UI — §B9 scope rule applies to any selector-level detail) |
| 7 | Sample Manager - Explorer | 14 | Performer | Folded into `Open - Entry By Test window` (the "Explorer block" UI navigation) |
| 8 | Summary_Report | 45 | Performer | `Create Summary Report` |
| 9 | Input File Management | 18 | Performer | Folded into `Process Work Queue Items`/`Delete files from Folder` (input-file existence + delete now happens per-item, not as a separate page) |
| 10 | Mark as read mail | 13 | Performer | `Move Emails` (completed-folder branch) |
| 11 | Mark as read and move to exception folder | 16 | Performer | `Move Emails` (exception-folder branch) — BP's two near-duplicate pages collapse to one parameterized `FUNCTION` (`In_txt_DestinationFolder`) |
| 12 | Mark Item As Completed | 7 | Performer | `Mark Complete` |
| 13 | Mark Item As Exception | 33 | Performer | `Mark Exception` (§A7 — the consecutive-breach logic lives here) |
| 14 | Completed No Outcome | 26 | Performer | **No counterpart found in `_11_managed`.** **STOP** — confirm whether the fuzzy-match "completed without outcome" rule engine was intentionally dropped or still needs building; `_11_managed`'s `Enter Results in App`/`Mark Complete` do not implement any equivalent rule matching. |
| 15 | DataGateway | 9 | Performer | `Process Work Queue Items`' `'Reset All'` → `BLOCK 'Data gateway block'` (§B13's DataGateways row) |
| 16 | Send Info to Data Gateways | 11 | — (unclear) | **STOP — second orphan page, corrected from an earlier draft of this row.** Takes 9 explicit inputs (`Work Queue Name`, `Item Id`, `Item Key`, timestamps, `Result Status`, `CustomMessage`) and calls `Blueprism.Automate.clsDataGatewaysActions :: Send Custom Data` — a **different** VBO from the `DataGateway` page's `Utility_DataGateways-CustomFramework :: Send Data to Data Gateways` (row 15). A caller search (same method as §B11's orphan check) finds **zero** callers for this page anywhere in the process. This looks like a legacy/alternate telemetry mechanism, superseded by the `DataGateway` page rather than "the same block" — confirm with the process owner whether it's dead code before deciding it needs no PAD counterpart. |
| 17 | Reset Global Data | 14 | Performer | `Process Work Queue Items`' per-item variable-reset section (L1555-1561), no separate `FUNCTION` |
| 18 | Close Down | 7 | Performer | `Close Application` |
| 19 | Send mail | 21 | Performer | `Send Email` (business report) — subject-line branching folded into the caller at L1463 |
| 20 | Send mail - No New Mail | 20 | Loader | `Send Business Exception Mail` (Loader's "no mail found" path, L53-55) |
| 21 | Mark leftout Items as Exception | 12 | — (unclear) | **STOP** — see §B11 open question; no confirmed PAD counterpart |
| 22 | Read Excel As Collection | 28 | Loader (config bootstrap) | Folded into `CF_PID_171_US_Read Config File` (Cloud Flow, §A2) — this BP page's "open Excel, read as collection, close" pattern for the *config* file is now a SharePoint-native read in the cloud tier, not a desktop Excel automation at all |
| 23 | Summary_Report (dup entry — see #8) | — | — | — |
| 24 | ConvertConfigFile As Collection - Copy | 31 | Loader (config bootstrap) | Same as #22 — superseded by `CF_PID_171_US_Read Config File`; the JSON-building-loop/escaping logic BP used to turn an Excel collection into JSON is unnecessary now that config is read as structured data directly from SharePoint |

*(Row 23 is a bookkeeping artifact of the 24-page BP inventory containing one exact duplicate
page name at different points in the original research pass — Summary_Report is a single page,
already covered at row 8.)*

### B15. Exception-handling pattern

The Block→Recover→circuit-breaker pipeline, confirmed identical in intent between BP and PAD:

- BP: `Block` (try) + `Recover` (catch, implicit edge) + `Resume` (continue-after) on a page,
  with the exception type classified via `ExceptionType()`/`ExceptionDetail()` BP functions.
- PAD: `BLOCK '<name>' ON BLOCK ERROR '<type>' ... ON BLOCK ERROR ... END <body> END` (§A5,
  §B12's `BLOCK`/`RECOVER`/`RESUME` rows) — the `Recover` stage's body becomes the handler; the
  `Resume` stage's target is simply the code after `END`.
- The consecutive-exception circuit breaker (BP: `Mark Item As Exception` page, `Consecutive
  Exception Limit` default 3, `TERMINATE`) maps exactly to §A7's PAD implementation in `Mark
  Exception` + `Process Work Queue Items`' post-item `flg_HaltRun` check.

### B16. Known gaps / explicit non-goals

- BP's `clsEnvironmentLockingBusinessObject` mutual-exclusion lock (`Populate Queue` page) —
  likely unnecessary given Dataverse-backed `ProcessWorkQueueItem`'s built-in concurrency safety;
  `ReviewFlag`, do not translate literally (§B13).
- BP's "Completed No Outcome" fuzzy-match rule engine (page #14) — no PAD counterpart found;
  `ReviewFlag`, needs a product decision, not a mechanical translation.
- BP's `Mark leftout Items as Exception` drain-loop page (page #21) — orphan status unresolved
  in both BP and PAD; `ReviewFlag`.
- BP's `Send Info to Data Gateways` page (page #16) — a second orphan page (no caller found
  anywhere in the process), implementing a distinct/legacy telemetry mechanism via
  `clsDataGatewaysActions :: Send Custom Data` rather than the `DataGateway` page's
  `Utility_DataGateways-CustomFramework`; `ReviewFlag`, likely dead code but not confirmed.
- BP's `RPA_AzureBlob_*` release-level environment variables (§A2 point 5) describe a complete
  Azure Blob Storage fallback for config download, gated by `RPA_AzureBlob_Download`, with no
  trace anywhere in the PAD config-bootstrap chain (Cloud_Main, Read Config File); `ReviewFlag`.
- Any BP stage requiring a `<appdef>`/ControlRepository UI selector — out of scope by design
  (§B9), always emit the `# TODO: UI selector required` stub, never a fabricated `appmask[...]`.

---

## REVIEW NOTES

Independent architect-review pass against the source files listed below. Every line citation in
Part A's §A3 outlines, §A6, §A7, and Part B's §B12/§B13 was spot-checked directly against
`DF_PID_171_US_Loader.robin.txt` and `DF_PID_171_US_LIMS_Prelude_Main.robin.txt` (well beyond the
requested 15-20 sample); §A2's orchestration claims were checked against the real Cloud Flow JSON
and `customizations.xml`; §A8's D1-D5 were re-verified by direct diff against
`samples/pad/fixed/*.txt`; §B11/§B14's BP-side claims (stageids, orphan-page status, stage
counts) were checked against `PID_0171.bprelease` by direct XML search, not re-parsed from
scratch.

**CONFIRMED**

- §A1 package-provenance claims, incl. the `<Definition>`-vs-`<JsonFileName>` split: verified
  directly in `customizations.xml` — the 3 Cloud Flows (Category 5) have `<JsonFileName>` only
  and no `<Definition>` element; the 2 Desktop Flows (Category 6) have both. All 5 WorkflowIds
  (GUIDs) match the actual `<Workflow WorkflowId=...>` entries and `Workflows/*.json` filenames
  exactly, including `CF_PID_171_US_Read Config File`'s space-containing `Name` attribute.
- §A2's entire orchestration description — trigger shapes, the `boolean`/`boolean_1` required
  inputs and their titles, the `Try:_Init → Try:_Loader → Try:_Performer → Catch:_*` scope chain,
  every cited action name (`Assign_Work_Queue_ID`, `List_rows_-_Get_Queue_Item_count`,
  `Total_Queue_Items`, `Respond_to_a_Power_App_or_flow_-_Success`, etc.), the two empty
  `"actions": {}` cloud-native placeholder branches (Loader and Performer), the Dataverse
  `_workqueueid_value eq '...' and statecode eq 0` filter, the `uiFlowId` GUIDs on both
  `RunUIFlow_V2` calls, and the `Flow_Message == 'success'` gate on `Try:_Init` — verified line
  by line against `CF_PID_171_US_LIMS_Prelude_Cloud_Main-*.json` and
  `CF_PID_171_US_LIMS_Prelude_Cloud_Schedule-*.json`. No discrepancies found.
- §A3's full Loader and Performer outlines, including every cited line number/range (`L12-30`,
  `L35-50`, `L58-145`, `L1372-1384`, `L1385-1468`, `L1405-1416`, `L1417-1431`, `L1469-1554`,
  `L1555-1561`, `L1562-1569`, `L1570-1572`, etc.) and every `FUNCTION` inventory line number in
  the Performer table (`L118` through `L1607`) — all checked directly and all correct.
- §A4's two worked examples: the `In_`/`in_` casing split between `Set Results Entry` and `Fetch
  Data from Excel file` is real (verified at their respective `FUNCTION` signatures), and the
  `SET GLOBAL.num_ConsecutiveExcCount TO GLOBAL.num_ConsecutiveExcCount + 1` pattern (not
  `Variables.IncreaseVariable`) is exactly what appears at L1277/L1280.
- §A5's asymmetric-exit claim: verified exactly at L95-110 — a plain System/Business Exception
  reaches `EXIT Code: 0 ErrorMessage: txt_FailedItemsLog` (L109) after the email; only System
  Unavailable Exception re-throws (L106-108). This claim had reportedly been corrected once
  already in this session; re-verification here confirms it is now right.
- §A6's graceful-stop claim: confirmed a single occurrence of `FlowControl.IfSafeStop` in the
  entire codebase (both files), at exactly L1570-1572, in the position described.
- §A7 (aside from the two corrections below): the increment code at L1276-1281, the breach block
  at L1283-1302 (message content, `ITException` status, `Send Consecutive Exception Mail`,
  `flg_SendExceptionEmail` disarm, `flg_HaltRun` set), and the post-telemetry `flg_HaltRun` check
  at L1552-1554 are all exactly as described.
- §A8 D1: independently re-verified by direct diff, not assumed. `_fixed.txt`'s Loader
  (`PID171_loader_fixed.txt` L73-80) explicitly checks `hasAttachments = False`, sends a Business
  Exception mail, moves the mail to the exception folder via `MoveV2`, and `NEXT LOOP`s past
  enqueue. `_11_managed`'s Loader (L108-113) has no such branch — it only conditionally *builds*
  the attachment list and always falls through to enqueue. The Performer's own L1421-1425 does
  independently reject 0-attachment items as a Business Exception, one stage later than in
  `_fixed.txt`. D1's "Confirmed by direct comparison" tag holds up.
- §A8 D2-D5: each independently re-verified against `_fixed.txt` (D2: Loader L134 uses
  `obj_Config['Sec_EncDecSecret']` directly as the AES key, no Key Vault call anywhere in the
  file; D3: Loader L319 uses a single `<>` exact-match against `Mail_SenderMailId`, no
  comma-split/`FilterList`; D5: no Key Vault / password-clearing code anywhere in
  `PID171_performer_fixed.txt`). All confirmed as stated.
- §B9-B11 scope/methodology claims, incl. the Loader/Performer split at BP stageid `85fbb578`
  (Main Page, no `<subsheetid>`) and the mirrored `Get Next Item` at `7652dc4c` — both confirmed
  present in `PID_0171.bprelease` with `name="Get Next Item" type="Action"`.
- The **"Mark leftout Items as Exception" orphan claim** (§B11/§B14/§B16): independently
  re-verified, not just re-asserted. Its `Get Next Item` (stageid `a5f6f46f`) sits on subsheet
  `12e3a570-3118-413d-aaf9-3ea7f3c16676`, named "Mark leftout Items as Exception" (12 stages —
  matches the page's own internal structure, not the "12" stage count cited in §B14's row 21,
  which is correct too). A full-text search of `PID_0171.bprelease` for
  `<processid>12e3a570-3118-413d-aaf9-3ea7f3c16676</processid>` (how a `SubSheet`-type call stage
  references a target page) returns **zero** matches — no stage anywhere in the process calls
  this page. The "no confirmed caller in the traced BP flow" claim is correct, and stronger than
  stated: there is no caller at all, by any path, not just none found by the trace.
- The **"Completed No Outcome" claim** (§B14 row 14): its subsheet (`3906e13c-...`) has exactly
  26 stages (matches the table) and **2** real callers elsewhere in the process (unlike page 21
  above) — so, correctly, this is a reachable BP page with a genuine missing PAD counterpart, not
  an orphan. The document's phrasing already reflects this distinction correctly.
- §B12: every template line citation (L1211, L1421, L1452, L404, L243, L268-388/L75-80) points
  exactly to the construct claimed.
- §B13: every VBO/action mapping row's cited line(s) were checked and are correct, including the
  multi-line-annotation-adjacent ones (L1211/L1403/L1450 for `UpdateProcessingNotes`, L975-980
  and L249-253 for the Excel rows, L775-778/L930-933/L939 for the DataTable-manipulation row,
  L238/L1449/L1159-1160/L1330-1331 for the File/Folder row, L1021/L1056/L1091/L1127 for the four
  `SendEmailV2` call sites) — one correction below (Key Vault row). The "`:: Tag Item`, `:: Defer`
  — no direct call observed" and "`clsEnvironmentLockingBusinessObject` — no PAD equivalent
  found" claims were independently re-checked with a case-insensitive full-text search of both
  `.robin.txt` files for "tag", "defer", and "lock" — no matches beyond the unrelated word
  "BLOCK". Both **STOP**/"no equivalent" claims hold up under independent search, not just
  uncritical copying.
- §B14: the full 24-page inventory was spot-checked far beyond the requested sample — stage
  counts for Main Page (119), Get Mails (28), Populate Queue (37), Send mail - No New Mail (20),
  Mark as read and move to exception folder (16), Read Excel As Collection (28),
  ConvertConfigFile As Collection - Copy (31), Completed No Outcome (26), and Mark Item As
  Exception (33) were all recomputed independently from the BP XML by counting stages per
  `<subsheetid>` — every one matches the table exactly (9/9). The 23-subsheet + Main Page = 24
  total is confirmed against the process's own `<subsheet>` list.
- §B15/§B16 are consistent with everything verified above; no changes needed.

**CORRECTED**

1. **§A7 — a System Unavailable Exception does *not* reset the consecutive-exception counter.**
   The original text said reset-to-0 happens "on a Business Exception / System Unavailable
   Exception outcome," citing L1256-1257. Those lines are inside the *Business Exception* branch
   only (L1239-1257); the SUE branch (L1258-1273) never references
   `GLOBAL.num_ConsecutiveExcCount` or `GLOBAL.txt_PreviousExceptionMessage` at all — verified by
   reading the full branch body. This is exactly the kind of claim the task asked for extra
   scrutiny on (having reportedly been corrected once already this session), and on
   re-verification it still needed a fix. **Fixed in §A7** (reset bullet rewritten to name only
   item-success and Business Exception as resetting the streak, with the SUE-branch line range
   cited as evidence).
2. **§A7/§A8 — newly identified deviation: the SE-branch increment never resets to 1 on a
   non-matching message.** While re-verifying the (correctly stated) "both branches increment"
   claim at L1276-1281, cross-referencing `docs/PID171_PAD_FIX_NOTES.md` §2.1 (the project's own
   design-intent notes for this exact code path) and `_fixed.txt` L891-904 showed both specify
   "increment on identical-message match, **reset to 1** on a different message." `_11_managed`
   implements only the increment half — the non-match arm (L1279-1280) sets
   `txt_PreviousExceptionMessage` but still does `+ 1`, never `= 1`. Net effect: the circuit
   breaker as built fires on N consecutive plain System Exceptions of *any* kind, not N
   *identical* ones as the config key `Ctrl_ConsecutiveExceptionLimit` and every other design
   document imply. **Fixed:** added as new deviation **D6** in §A8's table, and flagged inline in
   §A7's increment bullet.
3. **§A3 — the Performer's `LABEL 'End'` sets 3 outputs, not 4, and 2 of the 5 declared
   `@OUTPUT`s are dead.** `out_txt_SummaryReportPath` and `out_txt_ScreenshotPath` are declared at
   the top of `DF_PID_171_US_LIMS_Prelude_Main.robin.txt` (L12-13) but a full-text search of the
   file shows no `SET` statement for either, anywhere. Only `out_num_CompletedCount`,
   `out_num_ExceptionCount`, and `out_txt_ExceptionDetail` are actually populated (L115-117).
   **Fixed:** §A3's outline now says "set 3 outputs" with a note explaining the 2 unpopulated
   ones — worth flagging to whoever owns this flow, since a caller reading those two fields
   always gets an empty string.
4. **§B13 — off-by-one line citation on the Key Vault row.** The DB-secret `GetSecret` call cited
   as `L1538` is actually on `L1539`; `L1538` is the `@@connectionDisplayName` annotation line
   immediately before it (the same one-line offset the other three citations in that row — L119,
   L436, L1407 — correctly avoid). **Fixed:** citation changed to `L1539`.

**OPEN QUESTION**

- **A real exception-type-string typo exists in the BP source and is directly relevant to §B12's
  "preserve the BP type string verbatim" rule.** `PID_0171.bprelease` contains a stage named `SE:
  ReslutsEntry` (itself a typo of "Results Entry"), type `Exception`, on the `Result Entry` page,
  with `<exception type="System Exceprion" ...>` — "Exceprion" misspelled, confirmed by grepping
  all distinct `exception type="..."` values used in the file (`System Exceprion` appears exactly
  once, alongside the 8 canonical strings from CLAUDE.md's reference list, all correctly
  spelled). §B12's `EXCEPTION` rule says to preserve the BP string verbatim so it matches a typed
  `ON BLOCK ERROR` handler downstream — but this specific string, preserved verbatim, would never
  match any handler (typed for `'System Exception'`) and would silently fall through to a
  catch-all instead. Because `Result Entry` is already out of scope per §B9 (pure UI-automation,
  `# TODO: UI selector required` stub), this has no impact on the current document's generated
  output, but it's worth a decision before anyone builds that page for real: should the generator
  preserve exception-type strings verbatim even when they don't match the 11-string canonical
  list (CLAUDE.md), or validate/warn on a near-match instead? Not resolved here either way.

---

## FOLLOW-UP FINDINGS — `bp_parser_v2.py` / `bp_release_parser.py` toolchain cross-check

A second, independent pass using this repo's actual BP parsing tools (`scripts/bp_parser_v2.py`,
`scripts/bp_release_parser.py`, `scripts/bp_report_v2.py` — see §B10's new tooling note) rather
than manual XML reads. Findings folded directly into the sections above; summarized here:

- **11 release-level environment variables** found via `bp_release_parser.py` (not visible from a
  single-artefact `bp_parser_v2.py` parse) — added to §A2 point 5, including a real gap: 4
  `RPA_AzureBlob_*` keys describing an Azure Blob Storage config-download fallback with no trace
  anywhere in the PAD side. Added to §B16.
- **A second orphan page**: `Send Info to Data Gateways` (page #16) has zero callers, same method
  as the already-documented `Mark leftout Items as Exception` check (`bp_report_v2.py`'s "Called
  by" column, cross-checked with a `<processid>` search) — the original document had folded it
  into the `DataGateway` page's telemetry block, which is wrong: it calls a different VBO
  (`clsDataGatewaysActions`, not `Utility_DataGateways-CustomFramework`) and is structurally a
  separate, uncalled page. Corrected in §B14 row 16 and added to §B16.
- **`IsStopRequested()` appears on two BP pages, not one**: Main Page (already documented, §A6)
  and the orphaned `Mark leftout Items as Exception` page. Corrected in §A6 — does not change any
  PAD-side conclusion since the second occurrence is on an uncalled page, but the original "only
  appears on Main Page" claim was incomplete.
- **Stage-count convention clarified, not corrected**: this document's §B14 counts are raw
  `<stage>`-element counts per page (confirmed exactly by the architect-review subagent's
  independent 9/9 recount above). `bp_parser_v2.py`'s parsed counts are lower because they exclude
  4 skip-types; whole-process total reconciles exactly (706 parsed + 85 skipped = 791 raw). No
  table values changed — a tooling note was added to §B10 so this isn't mistaken for a
  discrepancy by whoever uses the parser toolchain next.
