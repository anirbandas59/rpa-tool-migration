# PID_0171 — PAD Fix Notes

Companion to [PID171_PAD_VALIDATION_REPORT.md](PID171_PAD_VALIDATION_REPORT.md).
Fixed code (originals untouched):

- `samples/pad/fixed/PID171_loader_fixed.txt` — full loader (all 4 functions)
- `samples/pad/fixed/PID171_performer_fixed.txt` — **changed functions only** (11 of 26); keep the originals for the rest

Every change is marked in-code with a `# FIX Fx:` comment. ControlRepository / connection JSON blocks are omitted from both files — paste the function bodies into the **existing** flows where the UI elements and connection references already exist.

---

## 1. Decision log (your feedback → what was implemented)

| Finding | Your decision | Implementation |
|---|---|---|
| F1 | Fix, keep `num_RowIndex` | Rows whose identity is already in `lst_MissingIdList` now get their four summary columns written (UnAuthorise / NULL / FAIL / `Err_ProductException`, same as the first failing row) and flow through the normal `Summary block`, which increments `num_RowIndex`. Alignment is preserved for all subsequent rows. |
| F2 | SUE for SampleManager launch/login and Outlook API failures, after 3 retries | `Launch Application` (start + login), loader `Fetch Emails from Mailbox`, and performer `Move Emails` now throw `System Unavailable Exception` after `num_MaxRetryLimit` / `num_MailRetryLimit` attempts. Typed `ON BLOCK ERROR 'System Unavailable Exception'` clauses were added to loader `Main_copy`, performer `Main_copy` (Launch + Main Work blocks) and `Process items block` so the classification survives `Get Error` (which defaults everything to System Exception). Both flows' terminal `ThrowCustomError` now uses `txt_ExceptionType` as the error code, so the parent cloud flow can distinguish SE / SUE / BE. |
| F3 + F10 | Try the item 3 times, then fail to the parent; no BP-style requeue (PAD cycles by status) | Implemented as an **in-place attempt loop**: each dequeued item runs up to `num_ConsecutiveExcLimit` (3) attempts. Between attempts the apps are closed and relaunched. Business Exceptions and SUE are never retried. After the 3rd System-Exception failure the item is marked `GenericException` with the BP-style message *"N consecutive incidents of TYPE: MESSAGE"*, the **Consecutive Exception Mail** is sent (its `{{Threshold}}` = `num_ConsecutiveExcLimit`, so the template text stays truthful), and the run rethrows the exception → `Main_copy` → parent cloud flow. The old cross-item `txt_PreviousExceptionMessage` / `num_ConsecutiveExcCount` bookkeeping became redundant and was removed from `Mark Exception` (the attempt loop *is* the consecutive counter — identical failures of one item are by definition consecutive). |
| F4 | Retry and continue 3 times, no logging, fail after that | Loader `Get Email block` handler no longer rethrows on first failure; it swallows attempts 1..N-1 (nothing appended to `txt_FailedItemsLog`) and throws SUE on the final attempt. |
| F5 | Fix | Backoff is now `WAIT num_MailRunCount * num_App_WaitTime` (the loop counter). The dead `num_ConnectionRetryCount` is no longer referenced (its init in `Load Config Data` is left as-is to keep that function unchanged). |
| F6 | Fix | Guard is now `IF flg_IsAppRunning = False` — the flag alone proves all retries failed; the old `num_AppRetryCount >= num_MaxRetryLimit` comparison could never be true (loop counter tops out at limit−1). Throws SUE per F2. |
| F7 | One final screenshot after retries; reuse existing variable; no duplicates | Screenshot capture was extracted from `Get Error` into a new global subflow `Capture Error Screenshot` (writes `txt_LastScreenshotPath`, disarms `flg_Screenshot`). During item attempts `flg_Screenshot` is kept **False**, so intermediate failures produce no screenshots. When an item is finally marked as exception, exactly one screenshot is taken (before apps are closed). It is attached to whichever mail fires: the Consecutive mail (`Mark Exception`) or the System Exception mail (`Main_copy` System Error path). `flg_SendExceptionEmail` (previously unused) now prevents double-mailing: `Mark Exception` disarms it after sending the consecutive mail. |
| F8 | Fix | `External.RunFlow` is now inside a `BLOCK 'Data gateway block'` whose handler swallows the error, and gated by **new config key `Ctrl_SendDataToGateway`** (`"True"` to enable). If the key is missing, the property access errors inside the guarded block and telemetry is skipped silently. |
| F9 | Fix | Two changes: (1) the performer now recomputes `txt_AttachmentFilepath` from its own `txt_EmailInputsPath + '\' + Name` instead of trusting the loader-resolved `CurrentItem.Filepath` (removes the username/machine coupling); (2) the loader rejects encrypted payloads over `num_MaxQueueValueLength` (1,000,000 chars) before enqueue — BE mail + move to exception folder + failed-items log, same treatment as a no-attachment mail. |
| F11 | Ignore (moving changes messageId; hash is built from the Inbox mail id; only invalid mails are moved) | No change. See counter-observation §2.1. |
| F12 | Fix | Duplicate-check failure handler now ends with `GOTO 'Next loop - Mail Items'` — the mail is skipped this run (it stays unread and is retried next run) instead of falling through to an IF that reads the previous mail's result. |
| F13 | Ignore (cloud flow owns desktop-failure notification, has a default-address env var) | No change. See §2.2. |
| F14 | Fix | `txt_DestinationPath` initialised to `''` before the empty-summary early exit. |
| F15 | Suggest a better approach | Root cause of your error: `Variables.IncreaseVariable` resolves its target variable in the **local** scope of the subflow, so pointing it at `GLOBAL.num_ItemsCompleted` from the non-global `Mark Complete`/`Mark Exception` fails. Fix: counting moved into `Process Work Queue Items` (a `GLOBAL` function) as plain `SET num_ItemsCompleted TO num_ItemsCompleted + 1` immediately after the mark calls. `txt_FailedItemsLog` is appended there too (`name: type - message | `), so `Main_copy` outputs (`out_num_CompletedCount`, `out_num_ExceptionCount`, `out_txt_ExceptionDetail`) now report real values to the cloud flow — symmetrical with the loader's `Out_num_MailItemCount`. |
| F16 | Keep (business requirement: all exception mail → `txt_MailExceptionFolder`) | No change. Finding withdrawn; requirement noted for the runbook. |
| F17 | Ignore for now | No change. Tracked as open backlog item. |
| F18 | Fix | `Set Results Entry` re-reads `Edit 'Analysis_Value'` **after** the populate + wait, so `Out_txt_OutputValue` reports the post-entry value. The re-read has an empty `ON ERROR` so a flaky read falls back to the previous value instead of failing an already-successful entry. |
| F19 | Intentional (dedup by mail id; subject can repeat legitimately) | No change. Agreed — subject-keyed dedup (BP) would silently skip legitimate re-sends; mail-id hashing is the better key. Documented. |
| F20 | Fix | In the `Set Results Entry` retry loop, each attempt first checks `IfWindow.IsNotOpen` on 'Result Entry Analysis' and re-navigates via `Get Results by Analysis and SampleId` (which itself falls back to `Open 'Entry By Test'`) before retrying — mirrors BP's recovery path. First attempt is unaffected (window is already open). |
| F21 | Ignore (cloud flow orchestrates loader/performer instances; runbook documents it) | No change. |
| F22 | Fix | Payload mapping corrected: `ItemCreatedOn` ← `obj_WorkQueueItem.CreatedOn`, `InputReceivedTime` ← `obj_QueueItemData['ReceivedOn']` (the mail's received timestamp, already in the decrypted payload), `ItemCompletedOn` ← `txt_ItemEndDateTime` captured at item end (correct for both completed and exception outcomes, matching BP's Completed/Exception DateTime split). |

---

## 2. Counter-observations (recorded, no code change)

### 2.1 F11 — accepted, one residual cost to watch
Your rationale is correct: Graph/Outlook `messageId` changes when a mail is moved, which would invalidate the stored id and the hash lineage. Residual cost of leaving processed-but-unqueued mails unread in the fetch folder: the loader re-fetches, re-hashes and re-dup-checks the whole backlog every run, and `@top: num_MailFetchLimit` is consumed by old mail first. If the queue ever backs up beyond `App_MailFetchLimit` unread mails, **new** mail stops being seen. Worth a line in the runbook: keep `App_MailFetchLimit` comfortably above the expected in-flight backlog.

### 2.2 F13 — accepted, one prerequisite on the cloud side
With `Load Config Data` failures surfacing as raw flow errors, the cloud flow's failure branch is the only notification path. Two things for the cloud-flow owner to confirm: (a) the failure branch triggers on **desktop flow error** (not just timeout), and (b) it surfaces `LastError`/error details from the desktop flow run into the notification, otherwise the mail will say only "flow failed".

### 2.3 F3 — one behavioural consequence to be aware of
Because attempts re-run the full item pipeline, a retry of a **partially completed** item will re-visit rows already authorised in SampleManager. Those rows re-enter through the `GOTO Authorize` path (value already matches) and typically land in "Authorise button disabled or Already authorised" → `EntryStatus = FAIL` in the summary for rows that in fact succeeded on attempt 1. BP had the same behaviour on its `Retry=True` clones, so this is parity, not a regression — but if the business reads the summary strictly, consider persisting per-row progress across attempts as a future enhancement.

### 2.4 F2 — scope of the SUE classification
Per your note, SUE is raised by: SampleManager launch, SampleManager login, loader mail fetch (`GetEmailsV3`), and performer mail move (`MarkAsRead_V3`/`MoveV2`). I deliberately did **not** convert the SendEmail functions (`Send Email`, `Send * Exception Mail`) to SUE-after-retries: they are the notification mechanism itself, and making them halt-the-run errors risks masking the original failure. They keep their current behaviour (error propagates as System Exception). Say the word if you want them retried too.

---

## 3. New/changed contract items (action required)

| Item | Where | Action |
|---|---|---|
| **New config key** `Ctrl_SendDataToGateway` | performer, Data gateway block | Add to the config JSON with `"True"`/`"False"`. Absent key = telemetry skipped. |
| `num_MaxQueueValueLength` (1,000,000 chars) | loader `Main_copy` init | Hardcoded guard for the Dataverse work-queue-item Value capacity. Verify the actual column limit in your environment and consider promoting to a config key (`Ctrl_MaxQueueValueLength`). |
| Flow outputs now populated | performer `Main_copy` | `out_num_CompletedCount` / `out_num_ExceptionCount` / `out_txt_ExceptionDetail` now carry real values — wire them into the cloud flow's run summary if not already. |
| Error codes surfaced to parent | both flows | Terminal throws now use `txt_ExceptionType` as the error code (`System Exception` / `System Unavailable Exception` / `Business Exception`). If the cloud flow branches on error text, update it to branch on these codes. |

## 4. Verify in the designer before first run

These are the two syntax points that cannot be validated outside PAD — check them when pasting:

1. **`obj_WorkQueueItem.CreatedOn`** (F22): confirm the work-queue-item object exposes `CreatedOn` in IntelliSense (the original code already used `ProcessingStartTime`, `ProcessingDuration`, `CompletedOn`, `StatusCode`, so the property family exists). If the name differs, substitute the created-timestamp property.
2. **`UIAutomation.IfWindow.IsNotOpen`** (F20): the designer's "If window" action offers *Is open* / *Is not open*; confirm the generated Robin token matches (`IsNotOpen`). If not, invert with the `IsOpen` variant and an `ELSE` branch.

Suggested smoke tests (in order):
1. Loader with Outlook connection deliberately broken → expect 3 spaced attempts, then flow fails with code `System Unavailable Exception`, no BE mail.
2. Loader happy path → items enqueued, oversized-attachment mail (if testable) moved to exception folder with BE mail.
3. Performer with an input file whose identity is missing in SampleManager and ≥2 rows sharing that identity → summary report rows must stay aligned and all carry `Err_ProductException`.
4. Performer with SampleManager killed mid-item → attempt notes 1..3 on the item, one screenshot, one Consecutive mail, item `GenericException`, flow fails with code `System Exception`, cloud flow notified.
5. Performer happy path → outputs report correct completed/exception counts; data gateway fires only when `Ctrl_SendDataToGateway = "True"`.
6. (EB-1) Kill SampleManager and block its exe path mid-run so the inter-attempt relaunch fails → the in-flight item must end `ITException` (not stuck in "Processing"), then the run fails with code `System Unavailable Exception`.

## 5. Exception-bubbling audit hardening (EB-1, EB-2)

Added after auditing the fixed code against the four-rule exception-bubbling model
(child throws → item-level routing at `Process Work Queue Items` → global handler
in `Main_copy`). The audit confirmed the model holds, with two gaps now closed:

| ID | Gap | Fix |
|---|---|---|
| **EB-1** | The inter-attempt recovery section (`Close Application` → `Launch Application` between item retries) runs *outside* `'Process items block'`. A relaunch failure bubbled straight to the global handler, leaving the in-flight item orphaned in "Processing" status — it escaped rule-3 routing. | Recovery section wrapped in `BLOCK 'Attempt recovery block'`; its handler classifies the failure as `System Unavailable Exception`, sets the item status to Failed, and `GOTO 'Mark Item as Exception'` — the item is marked `ITException`, mail moved, apps closed, telemetry sent, and only then does the terminal rethrow fail the run to the parent. Note: the item's `ProcessingResult` carries the *relaunch* error; the original per-attempt error is preserved in the processing notes. |
| **EB-2** | `UpdateWorkQueueItem` in `Mark Complete` / `Mark Exception` had no protection. Valid assumption in BP (in-process `clsWorkQueuesActions`, session holds the lock — though even BP routed these through the Work block's recovery and its "Internal" exception type), but PAD queue actions are **Dataverse Web API calls**: service-protection 429s, token refresh, and network are real transient failure modes — amplified by multiple performer machines sharing one Dataverse throttling scope (F21 topology). | All four status updates (`Mark Complete`, and the BE / SUE / SE branches of `Mark Exception`) are wrapped in a `num_MaxRetryLimit` retry loop with incremental back-off (`num_Delay_S * attempt`), same pattern as `Move Emails`. Transient blips self-heal; a persistent failure still `THROW ERROR`s to the global handler — by then it is a genuine environment problem. Mails are sent only after the status update succeeds, so no duplicate notifications on retry. |

Design notes:
- The retried scope in `Mark Complete` includes the `UpdateProcessingNotes` call; a retry can append a duplicate "Processing completed at…" note — harmless (notes are append-only) and preferable to splitting the block.
- Per-item `UpdateProcessingNotes` calls *inside* `'Process items block'` are intentionally not retried — a transient failure there is absorbed by the item attempt loop (F3).

## 6. Still open (agreed deferrals)

- F17 — "Completed No Outcome" rule engine (backlog).
- Low findings L1–L7 from the validation report (dead code, copy-paste texts, `flg_ConfigError`) — untouched per scope; cheap to sweep later. Note L2 (`Log In Application` backoff uses the foreign `num_AppRetryCount`) still exists since that function was intentionally left unchanged.
