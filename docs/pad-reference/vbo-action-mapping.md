# VBO / system-object → PAD action mapping (PID_171)

**Purpose:** the single, extensible source of truth for BP VBO/system-object method → PAD action
mappings. Referenced from `docs/bp-to-pad-architecture-PID171.md` §B13 — that document explains
*how* to use this table (the methodology in §B10/§B_VBO); this file only holds the mapping data,
so it can grow as new VBO actions are found without bloating the architecture document.

**Row format:** `| BP VBO :: Method | PAD target (literal syntax template) | Confirmed real call
(file + line, or "—" if not directly observed) |`. Every row should cite where the PAD syntax was
actually seen — don't add a row from memory/assumption; if you can't find a real call, mark it
`**STOP** — no confirmed PAD equivalent found` per the existing rows below, rather than guessing
a plausible-looking action name.

**Ground-truth PAD sources**, line numbers refer to these:
- `docs/pad-reference/DF_PID_171_US_Loader.robin.txt`
- `docs/pad-reference/DF_PID_171_US_LIMS_Prelude_Main.robin.txt`

---

## Work Queues (`Blueprism.Automate.clsWorkQueuesActions`)

| BP VBO / system object | PAD target | Confirmed real call (line) |
|---|---|---|
| `:: Get Next Item` | `WorkQueues.ProcessWorkQueueItem.ProcessWorkQueueItem WorkQueue: <id> WorkQueueItem=> <var>` (drives a `LOOP WHILE`) | L1371 |
| `:: Add To Queue` | `WorkQueues.EnqueueWorkQueueItem.WithoutUniqueId WorkQueue: <id> Status: WorkQueues.WorkQueueItemEnqueueStatus.Queued Priority: WorkQueues.WorkQueueItemPriority.Normal Name: <var> Value: <var> WorkQueueItem=> <var>` | Loader L140 |
| `:: Mark Completed` | `WorkQueues.UpdateWorkQueueItem.UpdateWithProcessingNotes WorkQueueItem: <obj> Status: WorkQueues.WorkQueueItemStatus.Processed` | L1212 |
| `:: Mark Exception` (Business type) | `... Status: WorkQueues.WorkQueueItemStatus.BusinessException ProcessingResult: <msg>` | L1246 |
| `:: Mark Exception` (System Unavailable / consecutive-breach type) | `... Status: WorkQueues.WorkQueueItemStatus.ITException ProcessingResult: <msg>` | L1265, L1290 |
| `:: Mark Exception` (plain System type) | `... Status: WorkQueues.WorkQueueItemStatus.GenericException ProcessingResult: <msg>` | L1309 |
| `:: Update Status` (progress note, no status change) | `WorkQueues.UpdateProcessingNotes.WithProcessingNotes WorkQueueItem: <obj> ProcessingNotes: <text>` | L1211, L1403, L1450 etc |
| `:: Is Item In Queue` / duplicate check | `WorkQueues.GetWorkQueueItems WorkQueue: <id> FilterRows: '<FetchXML>' RowsToReturn: 5000 WorkQueueItems=> <list>`, then `IF <list>.Count > 0` | Loader L90-102 |
| `:: Tag Item`, `:: Defer` | **STOP — no direct call observed in `_11_managed`.** Do not invent one; flag as `ReviewFlag` if a BP page needs it. | — |
| `BluePrism...clsEnvironmentLockingBusinessObject :: Acquire/Release Lock` | **STOP — no PAD equivalent found.** PAD's Dataverse-backed `ProcessWorkQueueItem` already provides safe concurrent dequeue, so this BP-side mutual-exclusion lock may simply be unnecessary in PAD rather than needing translation — confirm before adding a custom lock mechanism. | — |

## Excel (`MS Excel VBO`)

| BP VBO / system object | PAD target | Confirmed real call (line) |
|---|---|---|
| `:: Create Instance` / `Open Workbook` | `Excel.LaunchExcel.LaunchAndOpenUnderExistingProcess Path: <path> Visible: False ReadOnly: False UseMachineLocale: False Instance=> <var>` | L249, L976 |
| `:: Get Worksheet As Collection` / `Read` | `Excel.ReadFromExcel.ReadAllCells Instance: <ins> GetCellContentsMode: Excel.GetCellContentsMode.PlainText FirstLineIsHeader: True RangeValue=> <var>` | L252 |
| `:: Write to cell` | `Excel.WriteToExcel.WriteCell Instance: <ins> Value: <val> Column: <n> Row: <n>` | L978 |
| `:: Close Workbook` / `Close Instance` | `Excel.CloseExcel.Close Instance: <ins>` | L253, L980 |
| `:: Save As` | `Excel.SaveExcel.SaveAs Instance: <ins> DocumentFormat: Excel.ExcelFormat.FromExtension DocumentPath: <path>` | L979 |

## Outlook (`MS Outlook Email VBO` + Extended variants)

| BP VBO / system object | PAD target | Confirmed real call (line) |
|---|---|---|
| `:: Get Received Items` | `External.InvokeCloudConnector ... OperationId: 'GetEmailsV3' @folderPath: ... @fetchOnlyUnread: True @includeAttachments: True @top: <n> @GetEmailsV3Response=> <var>` | Loader L287 |
| `:: Mark Email As Read` | `... OperationId: 'MarkAsRead_V3' @messageId: ... @mailboxAddress: ... @'body/isRead': 'True'` | Loader L67, Performer L1347 |
| `:: Move Email` | `... OperationId: 'MoveV2' @messageId: ... @folderPath: ... @mailboxAddress: ... @MoveV2Response=> <var>` | Performer L1350 |
| `:: Send Email` | `... OperationId: 'SendEmailV2' @'emailMessage/To': ... @'emailMessage/Subject': ... @'emailMessage/Body': ... @'emailMessage/From': ... @'emailMessage/Cc': ... @'emailMessage/Attachments': <list> @'emailMessage/Importance': 'Normal'` | L1021, L1056, L1091, L1127 |

## Utility VBOs

| BP VBO / system object | PAD target | Confirmed real call (line) |
|---|---|---|
| `Utility - Strings :: Split Text` | `Text.SplitText.SplitWithDelimiter Text: <t> CustomDelimiter: '<d>' IsRegEx: False Result=> <list>` (or `.Split` with `StandardDelimiter` for newline/tab) | Loader L241, Performer L564 |
| `Utility - Collection Manipulation :: Remove Null Rows` / row ops | `Variables.FilterDataTable` / `Variables.ModifyDataTableItem` / `Variables.AddColumnToDataTable.AppendColumnToDataTable` — pick per BP method, no single 1:1 (inspect the specific BP action name before mapping) | L775-778, L930-933, L939 |
| `Utility - File Management(_Extended) :: File Exists` / `Delete File` / `Get Files` | `File.IfFile.Exists`/`.DoesNotExist`, `File.ConvertToBase64`/`ConvertFromBase64`, `Folder.IfFolderExists.*`, `Folder.Create`, `Folder.Delete` | L238, L1449, L1159-1160, L1330-1331 |
| `Utility - General :: Sleep` | `WAIT <seconds>` | Loader L293/311, Performer L257/428 |
| `Utility - Environment :: Get User Name` / `Kill Process` | `System.GetEnvironmentVariable.GetEnvironmentVariable Name: 'USERNAME'/'COMPUTERNAME' Value=> <var>`; `System.TerminateProcess.TerminateProcessByName ProcessName: <name>` (+ PowerShell force-kill fallback, L1149) | L128/130, L1142-1149 |
| `Utility - JSON :: Convert` | `Variables.ConvertJsonToCustomObject Json: <t> CustomObject=> <var>` / `Variables.ConvertCustomObjectToJson CustomObject: <o> Json=> <var>` | Loader L24/116 |
| `Utility_DataGateways-CustomFramework :: Send Custom Data` | `External.RunFlow FlowId: '<guid>' WaitToComplete: True @In_<param>: <val> @Out_<param>=> <var>` — gated behind `obj_Config['Ctrl_SendDataToGateway'] = 'True'`, wrapped in a swallow-all `BLOCK` | L1533-1546 |
| `Blueprism.Automate.clsCredentialsActions :: Get`/`:: Set` | `External.InvokeCloudConnector ... shared_keyvault ... OperationId: 'GetSecret' @secretName: <config key naming the secret> @GetSecretResponse=> <var>`, then clear the variable after use. Not called in the main process (confirmed absent — only used in the sibling `RPA_Sharepoint_API_ConfigFile_Download` process), but this is the general BP-Credential-Manager → PAD-Key-Vault rule if it's ever needed. | — (rule stated generally; see Azure Key Vault row below for a real call site) |

## UI-automation objects (out of scope, §B9/§B_VBO)

| BP VBO / system object | PAD target | Confirmed real call (line) |
|---|---|---|
| `PID_0003_Object_US_SampleManager`, `PID_0005_Object_US_SampleResultsEntry` (any `NAVIGATE`/`READ`/`WRITE`/dynamic-`WAIT` method) | Out of scope — `# TODO: UI selector required` comment stub. The real `appmask[...]` selectors exist in `_11_managed`'s `ControlRepository_*.json` binaries for the methods already built (`Get Results by Analysis and SampleId`, `Set Results Entry`, etc., main doc §A3) — reuse those, do not re-record. Static `CODE`/`WAIT` stages inside these VBOs still translate normally per §B12/§B_VBO. | — |

## PAD-native constructs with no BP origin

| Construct | PAD target | Confirmed real call (line) |
|---|---|---|
| Azure Key Vault secret fetch | `External.InvokeCloudConnector ... shared_keyvault ... OperationId: 'GetSecret' @secretName: <config key> @GetSecretResponse=> <var>`, then clear the variable after use | L119 (Loader), L436, L1407, L1539 |
| AES encrypt/decrypt | `Cryptography.EncryptText.EncryptTextWithAES` / `Cryptography.DecryptText.DecryptTextWithAES Encoding: Cryptography.EncryptionEncoding.UTF8 ... EncryptionKey/DecryptionKey: <key> PaddingMode: Cryptography.PaddingMode.PKCS7 KeySize: Cryptography.AESKeySize.Bits256` | Loader L121, Performer L1409 |
