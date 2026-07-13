# PID_0171 — PAD Fix Notes

Companion to [PID171_PAD_VALIDATION_REPORT.md](PID171_PAD_VALIDATION_REPORT.md).
Fixed code (originals untouched):

- `samples/pad/fixed/PID171_loader_fixed.txt` — full loader (all 4 functions)
- `samples/pad/fixed/PID171_performer_fixed.txt` — **changed functions only** (16 of 26, see the file header for the exact list — this grew from 11 during the item-retry/screenshot design review, §2 below); keep the originals for the rest

Every change is marked in-code with a `# FIX Fx:` comment. ControlRepository / connection JSON blocks are omitted from both files — paste the function bodies into the **existing** flows where the UI elements and connection references already exist.

---

## 1. Decision log (your feedback → what was implemented)

| Finding | Your decision | Implementation |
|---|---|---|
| F1 | Fix, keep `num_RowIndex` | Rows whose identity is already in `lst_MissingIdList` now get their four summary columns written (UnAuthorise / NULL / FAIL / `Err_ProductException`, same as the first failing row) and flow through the normal `Summary block`, which increments `num_RowIndex`. Alignment is preserved for all subsequent rows. |
| F2 | SUE for SampleManager launch/login and Outlook API failures, after 3 retries | `Launch Application` (start + login), loader `Fetch Emails from Mailbox`, and performer `Move Emails` now throw `System Unavailable Exception` after `num_MaxRetryLimit` / `num_MailRetryLimit` attempts. Typed `ON BLOCK ERROR 'System Unavailable Exception'` clauses were added to loader `Main_copy`, performer `Main_copy` (Launch + Main Work blocks) and `Process items block` so the classification survives `Get Error` (which defaults everything to System Exception). Both flows' terminal `ThrowCustomError` now uses `txt_ExceptionType` as the error code, so the parent cloud flow can distinguish SE / SUE / BE. |
| F3 + F10 | **Superseded, see §2.** Originally implemented as an in-place 3× attempt loop; withdrawn after design review in favour of BP-faithful single-attempt processing + a cross-item consecutive-failure circuit breaker. | An item is now attempted **once** (BP parity). Any escalated exception routes straight to `Mark Exception`. The run halts only for System Unavailable Exception, or when `num_ConsecutiveExcLimit` **different** items in a row fail with the identical message (`GLOBAL.flg_HaltRun`, set in `Mark Exception`'s System Exception branch, checked in `Process Work Queue Items` after cleanup/telemetry). `txt_PreviousExceptionMessage` / `num_ConsecutiveExcCount` are back — reset on success (`Mark Complete`) and on Business Exception, incremented only when the same message repeats on the *next* item. |
| F4 | Retry and continue 3 times, no logging, fail after that | Loader `Get Email block` handler no longer rethrows on first failure; it swallows attempts 1..N-1 (nothing appended to `txt_FailedItemsLog`) and throws SUE on the final attempt. |
| F5 | Fix | Backoff is now `WAIT num_MailRunCount * num_App_WaitTime` (the loop counter). The dead `num_ConnectionRetryCount` is no longer referenced (its init in `Load Config Data` is left as-is to keep that function unchanged). |
| F6 | Fix | Guard is now `IF flg_IsAppRunning = False` — the flag alone proves all retries failed; the old `num_AppRetryCount >= num_MaxRetryLimit` comparison could never be true (loop counter tops out at limit−1). Throws SUE per F2. |
| F7 | One screenshot per real error; reuse existing variable; no duplicates; **not overwritten by a parent handler** | **Revised, see §2.** Screenshot capture was extracted from `Get Error` into a new global subflow `Capture Error Screenshot` (writes `txt_LastScreenshotPath`, disarms `flg_Screenshot`). Exactly one arm+capture site exists per item failure: `Process items block` in `Process Work Queue Items` (mirrors BP's single `Capture Error Screenshot` call on Main Page). Every sub-flow nested under that block no longer arms `flg_Screenshot` itself, so there is nothing left for an outer handler to overwrite. It is attached to whichever mail fires: the Consecutive mail (`Mark Exception`) or the System Exception mail (`Main_copy` System Error path). `flg_SendExceptionEmail` (previously unused) now prevents double-mailing: `Mark Exception` disarms it after sending the consecutive mail. |
| F8 | Fix | `External.RunFlow` is now inside a `BLOCK 'Data gateway block'` whose handler swallows the error, and gated by **new config key `Ctrl_SendDataToGateway`** (`"True"` to enable). If the key is missing, the property access errors inside the guarded block and telemetry is skipped silently. |
| F9 | Fix | Two changes: (1) the performer now recomputes `txt_AttachmentFilepath` from its own `txt_EmailInputsPath + '\' + Name` instead of trusting the loader-resolved `CurrentItem.Filepath` (removes the username/machine coupling); (2) the loader rejects encrypted payloads over `num_MaxQueueValueLength` (1,000,000 chars) before enqueue — BE mail + move to exception folder + failed-items log, same treatment as a no-attachment mail. |
| F11 | Ignore (moving changes messageId; hash is built from the Inbox mail id; only invalid mails are moved) | No change. See counter-observation §3.1. |
| F12 | Fix | Duplicate-check failure handler now ends with `GOTO 'Next loop - Mail Items'` — the mail is skipped this run (it stays unread and is retried next run) instead of falling through to an IF that reads the previous mail's result. |
| F13 | Ignore (cloud flow owns desktop-failure notification, has a default-address env var) | No change. See §3.2. |
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

## 2. Design revision: item-level retry and screenshot semantics

After the F3/F7 fixes above shipped, you challenged the item-retry design directly, and separately asked me to re-derive the screenshot behaviour from the BP report and the *original* PAD code rather than keep patching. Both investigations changed the design materially — recorded here in full since they reverse earlier decisions in §1.

### 2.1 Item-level retry: why the in-place attempt loop was wrong

Your critique, verified against the code:

- `Enter Results in App` (the SampleManager entry loop) throws **only** `System Exception` — every business condition it encounters (empty Sample ID, empty Results, missing Identity, component not found, parameter not matched) is absorbed into the `EntryStatus`/`EntryError` columns and the loop moves on. Nothing else in the reachable item pipeline realistically produces a retryable failure except this one function.
- `Set Results Entry`, `Get Components List`, and `Get Results by Analysis and SampleId` already have their own `LOOP num_RetryCount FROM 1 TO GLOBAL.num_MaxRetryLimit` loops around the specific UI action that can flake — retry responsibility already lives at the point of failure.
- Consequently, the item-level attempt loop's practical effect was almost entirely "re-run `Enter Results in App` from row zero." A prior partial pass may have already clicked Authorize on some rows in SampleManager; re-entering those rows hits `Set Results Entry`'s `GOTO Authorize` path, finds the button disabled ("already authorised"), and logs `EntryStatus = FAIL` for rows that had in fact already succeeded — corrupting the summary report the process exists to produce. (This was flagged as a "parity quirk" in §2.3 of an earlier revision of this doc; it is not a quirk, it is disqualifying.)
- BP itself never retries an item in-session either: `Mark Exception ... Retry: True` clones the item back onto the queue for a **later** pickup, governed by the queue's own attempt tracking — not a synchronous re-run. PAD's equivalent primitive is `Requeue Work Queue Item` (with delay), which returns the item to Pending/Deferred for a fresh iteration of the `WHILE (ProcessWorkQueueItem...)` loop, with a naturally reset app state — not a manual loop that never lets go of the item.

Decision (confirmed): **single attempt per item** (recommended option). `Requeue Work Queue Item` was considered and rejected for now — sub-flow-level retries plus immediate escalation to `Mark Exception` already cover the realistic failure modes, and native requeue adds queue-state complexity (delay, attempts-tracking, multi-machine interaction) without a concrete failure mode it's needed for yet. Revisit if a specific transient-but-not-sub-flow-retryable failure shows up in practice.

`num_ConsecutiveExcLimit` reverts to BP's actual semantics (confirmed): a **cross-item** circuit breaker — N *different* items in a row failing with the identical message halts the run, independent of any per-item retry count. Implementation:

- `Mark Complete` and the Business Exception branch of `Mark Exception` both reset `GLOBAL.txt_PreviousExceptionMessage` / `num_ConsecutiveExcCount` — a success or an unrelated business condition breaks the streak.
- The System Exception branch of `Mark Exception` compares this item's message to the previous one; on a match it increments the counter (plain `SET`, not `Variables.IncreaseVariable` — same scope issue as F15), otherwise resets it to 1 with the new message.
- On breach: status `ITException` with the BP-style "N consecutive incidents of TYPE: MESSAGE", Consecutive Exception Mail sent, `GLOBAL.flg_HaltRun` set. `Process Work Queue Items` checks `flg_HaltRun` (and, separately, `txt_ExceptionType = 'System Unavailable Exception'`) only **after** the failing item's own cleanup and telemetry complete — the halt never skips that item's routing.

`Process Work Queue Items`'s tail-of-item halt check was also corrected: it previously threw on *any* non-Business exception (a leftover from when reaching that point meant "3 attempts already exhausted"), which under single-attempt would have halted the run on one isolated System Exception. It now throws only for System Unavailable Exception or `flg_HaltRun`.

### 2.2 Screenshot semantics: exactly one, taken nearest the real error

BP's own report settles this precisely: the `Capture Error Screenshot` VBO action is called from **exactly one** Recover path across the entire Main Page — `Recover20 → Exception Data → Capture Error Screenshot → Send mail`, tied to the outermost `Work` block that wraps the whole per-item pipeline. Every other Recover on that page (Recover2, Recover21, Recover22, Recover23, and every sub-page's own retry loop) skips straight to its own routing without re-screenshotting. BP has no per-item "was a screenshot already taken" flag at all, because nothing deeper in the process ever takes one — there's only one call site in the whole design, so there's nothing to protect against being overwritten.

The original PAD `Get Error` had a real bug in this area, independent of anything I introduced: it unconditionally ran `SET txt_LastScreenshotPath TO ''` at the top, on **every** call — so any outer handler re-calling `Get Error` (extremely common in this codebase) erased a deeper handler's screenshot path even when it took no new screenshot itself. The F7 split into `Capture Error Screenshot` incidentally fixed that specific bug (the reset now only happens inside the `flg_Screenshot = True` branch). But the F7/F3 rounds then introduced a *worse* version of the same class of problem: an unconditional forced re-capture in `Process Work Queue Items`'s `Mark Item as Exception` label, plus several sub-flows (`Get Results by Analysis and SampleId`, `Open 'Entry By Test'`, `Get Components List`, `Close Results Entry Analysis`, `Close Results Entry`) that each independently armed and captured their own screenshot *while nested under* that same per-item catch — exactly the "parent overwrites the real error's screenshot" failure mode you flagged.

Fix, matching BP's model exactly: **one arm+capture site** for the whole item pipeline, in `Process items block` (`Process Work Queue Items`), covering the System Unavailable and plain (System Exception) clauses — Business Exception still never screenshots, matching the original convention. All five sub-flows above (now included in the fixed file — see the header for the full function list) had their independent `SET GLOBAL.flg_Screenshot TO True` line removed; they still call `Get Error` for the error **message**, just not for a screenshot. The forced re-capture at `Mark Item as Exception` was deleted outright — the screenshot (if any) was already taken at the true point of catching, before the block even exits.

Functions that keep their *own* independent screenshot arming are the ones genuinely **not** nested under the per-item catch, so there's no overwrite risk: `Main_copy`'s pre-loop `Launch block`, `Launch Application`, `Log In Application` (unchanged original), and `Process Work Queue Items`'s tail `Launch block` (post-item relaunch, its own distinct failure scope).

---

## 3. Counter-observations (recorded, no code change)

### 3.1 F11 — accepted, one residual cost to watch
Your rationale is correct: Graph/Outlook `messageId` changes when a mail is moved, which would invalidate the stored id and the hash lineage. Residual cost of leaving processed-but-unqueued mails unread in the fetch folder: the loader re-fetches, re-hashes and re-dup-checks the whole backlog every run, and `@top: num_MailFetchLimit` is consumed by old mail first. If the queue ever backs up beyond `App_MailFetchLimit` unread mails, **new** mail stops being seen. Worth a line in the runbook: keep `App_MailFetchLimit` comfortably above the expected in-flight backlog.

### 3.2 F13 — accepted, one prerequisite on the cloud side
With `Load Config Data` failures surfacing as raw flow errors, the cloud flow's failure branch is the only notification path. Two things for the cloud-flow owner to confirm: (a) the failure branch triggers on **desktop flow error** (not just timeout), and (b) it surfaces `LastError`/error details from the desktop flow run into the notification, otherwise the mail will say only "flow failed".

### 3.3 F3 — superseded
The original note here ("retries re-visit already-authorised rows") described a consequence of the in-place attempt loop. That loop no longer exists (§2.1) — an item is attempted once, so this consequence cannot occur. Left here only as a pointer for anyone reading an older version of this doc or the git history.

### 3.4 F2 — scope of the SUE classification
Per your note, SUE is raised by: SampleManager launch, SampleManager login, loader mail fetch (`GetEmailsV3`), and performer mail move (`MarkAsRead_V3`/`MoveV2`). I deliberately did **not** convert the SendEmail functions (`Send Email`, `Send * Exception Mail`) to SUE-after-retries: they are the notification mechanism itself, and making them halt-the-run errors risks masking the original failure. They keep their current behaviour (error propagates as System Exception). Say the word if you want them retried too.

---

## 4. New/changed contract items (action required)

| Item | Where | Action |
|---|---|---|
| **New config key** `Ctrl_SendDataToGateway` | performer, Data gateway block | Add to the config JSON with `"True"`/`"False"`. Absent key = telemetry skipped. |
| `num_MaxQueueValueLength` (1,000,000 chars) | loader `Main_copy` init | Hardcoded guard for the Dataverse work-queue-item Value capacity. Verify the actual column limit in your environment and consider promoting to a config key (`Ctrl_MaxQueueValueLength`). |
| Flow outputs now populated | performer `Main_copy` | `out_num_CompletedCount` / `out_num_ExceptionCount` / `out_txt_ExceptionDetail` now carry real values — wire them into the cloud flow's run summary if not already. |
| Error codes surfaced to parent | both flows | Terminal throws now use `txt_ExceptionType` as the error code (`System Exception` / `System Unavailable Exception` / `Business Exception`). If the cloud flow branches on error text, update it to branch on these codes. |

## 5. Verify in the designer before first run

These are the syntax points that cannot be validated outside PAD — check them when pasting:

1. **`obj_WorkQueueItem.CreatedOn`** (F22): confirm the work-queue-item object exposes `CreatedOn` in IntelliSense (the original code already used `ProcessingStartTime`, `ProcessingDuration`, `CompletedOn`, `StatusCode`, so the property family exists). If the name differs, substitute the created-timestamp property.
2. **`UIAutomation.IfWindow.IsNotOpen`** (F20): the designer's "If window" action offers *Is open* / *Is not open*; confirm the generated Robin token matches (`IsNotOpen`). If not, invert with the `IsOpen` variant and an `ELSE` branch.

Suggested smoke tests (in order):
1. Loader with Outlook connection deliberately broken → expect 3 spaced attempts, then flow fails with code `System Unavailable Exception`, no BE mail.
2. Loader happy path → items enqueued, oversized-attachment mail (if testable) moved to exception folder with BE mail.
3. Performer with an input file whose identity is missing in SampleManager and ≥2 rows sharing that identity → summary report rows must stay aligned and all carry `Err_ProductException`.
4. Performer with a single item hitting a genuine UI failure in `Enter Results in App` (e.g. force `Get Results by Analysis and SampleId` to exhaust its retries) → item is attempted **once**, marked `GenericException`, mail moved, run **continues to the next item** (no halt) — confirms the single-attempt design and that the run doesn't stop on an isolated failure.
5. Performer with **three consecutive items** forced to fail with the identical injected error message → 1st and 2nd marked `GenericException` (no mail, run continues), 3rd marked `ITException` with the "3 consecutive incidents…" message, Consecutive Exception Mail sent, run halts with code `System Exception`. Interleave a success or a different error between failures to confirm the streak resets instead.
6. Same scenario as #4/#5 but with a genuine screen-visible failure (e.g. block the Result Entry Analysis window from opening) → confirm exactly **one** screenshot file is written per failed item, and it visibly matches the true failure state (not a later/different screen).
7. Performer happy path → outputs report correct completed/exception counts; data gateway fires only when `Ctrl_SendDataToGateway = "True"`.

## 6. Exception-bubbling audit hardening (EB-2)

Added after auditing the fixed code against the four-rule exception-bubbling model
(child throws → item-level routing at `Process Work Queue Items` → global handler
in `Main_copy`).

**EB-1 is superseded.** It patched a gap in the in-place item-retry loop's inter-attempt recovery section (a relaunch failure between attempts bubbled straight to the global handler, orphaning the item in "Processing"). That whole loop was removed in §2.1 — there is no more inter-attempt recovery section, so there is nothing left for EB-1 to guard. Kept here for history only.

**EB-2** stands: `UpdateWorkQueueItem` in `Mark Complete` / `Mark Exception` had no protection. Valid assumption in BP (in-process `clsWorkQueuesActions`, session holds the lock — though even BP routed these through the Work block's recovery and its "Internal" exception type), but PAD queue actions are **Dataverse Web API calls**: service-protection 429s, token refresh, and network are real transient failure modes — amplified by multiple performer machines sharing one Dataverse throttling scope (F21 topology). Fix: all four status updates (`Mark Complete`, and the BE / SUE / SE branches of `Mark Exception`), plus `Move Emails`, are wrapped in a `num_MaxRetryLimit` retry loop with incremental back-off (`num_Delay_S * attempt`). Transient blips self-heal; a persistent failure raises `System Unavailable Exception` — by then it is a genuine environment problem. Mails are sent only after the status update succeeds, so no duplicate notifications on retry.

Design notes:
- The retried scope in `Mark Complete` includes the `UpdateProcessingNotes` call; a retry can append a duplicate "Processing completed at…" note — harmless (notes are append-only) and preferable to splitting the block.
- Per-item `UpdateProcessingNotes` calls *inside* `'Process items block'` are intentionally not retried — a transient failure there fails the item outright now (single attempt, §2.1), which is the correct behaviour.

### 6.1 Correction: `ON BLOCK ERROR` cannot carry conditional logic

The first EB-2 draft put an `IF num_QueueUpdateRetryCount >= GLOBAL.num_MaxRetryLimit THEN … END` **inside** the `ON BLOCK ERROR` handler of each retry block (and the same anti-pattern was already present, unnoticed, in the F2/F4 loader and `Move Emails` fixes). This is invalid: a PAD block's error handler runs as a fixed action sequence, not a branch — it cannot host conditional flow control. The tell is in the *original* BP-generated code itself: every retry loop there (`Launch Application`'s `flg_IsAppRunning`, `Log In Application`'s `flg_IsLoggedIn`) sets a plain flag unconditionally inside the handler and makes the retries-exhausted decision in an `IF` placed **after the `LOOP` ends** — never inside the handler. All six retry blocks below were rewritten to that pattern:

| Location | Success flag | Where the exhausted-check now lives |
|---|---|---|
| Loader `Fetch Emails from Mailbox` | `flg_FetchApiSuccess` (attempt-scoped; distinct from `flg_Success`, which still means "mail found") | After the `LOOP`, combined with the attempt-scoped flag so a call that succeeded but found 0 mails does **not** raise SUE — only a failed *connector call* on the final attempt does |
| Performer `Move Emails` | `flg_MoveSuccess` | After the `LOOP` |
| Performer `Mark Complete` | `flg_QueueUpdateSuccess` | After the `LOOP` |
| Performer `Mark Exception` (BE / SUE / SE branches) | `flg_QueueUpdateSuccess` (reset per branch — branches are mutually exclusive) | After each branch's `LOOP` |

A second, related bug surfaced while fixing this: the original handlers called `CALL 'Get Error'`, which unconditionally overwrites `GLOBAL.txt_ExceptionType` / `txt_ExceptionMessage`. Inside `Mark Exception`'s nested retry loops that would have **clobbered the item's original exception classification and message** — the same variables the `ProcessingResult` text and the exception mail body read right after the loop. The equivalent bug existed in `Move Emails`: `Process Work Queue Items`'s `'Reset All'` region reads `txt_ExceptionMessage` to build the Data Gateway telemetry `FinalOutcome` field *after* the `Move Emails` call on the exception path, so a transient mail-move retry could have overwritten the real failure reason in the telemetry payload. Fix: these five handlers (`Mark Complete`, `Mark Exception` ×3, `Move Emails`) no longer call `Get Error` at all — they are pure empty swallow-and-retry handlers (an empty `ON BLOCK ERROR … END` is valid Robin syntax, proven by the original `Get Error` function's own screenshot handler and `Create New Folder`'s `Folder.Create` handler). The retries-exhausted throw messages for these five are correspondingly generic (attempt count only, no captured connector error text) — loader's `Fetch Emails from Mailbox` is the one exception, since it has no downstream variable to protect and still captures `obj_LastError.Message` for diagnostics.

## 7. Still open

### 7.1 New question raised by EB-2: `Mark Complete` retry-exhausted path isn't routed through `Mark Exception`

`Mark Complete` can now throw `System Unavailable Exception` if `UpdateWorkQueueItem` fails `num_MaxRetryLimit` times. That call site (`Process Work Queue Items`, `LABEL 'Mark Item as Completed'`) sits outside any block, so the throw bubbles straight to `Main_copy`'s global handler with the item **never explicitly marked** (it was mid-completion, so it's not "orphaned in Processing" the way the old EB-1 case was, but its terminal Dataverse status is whatever `UpdateWorkQueueItem` left it at after N failed attempts — normally still the pre-call state). Two options, not yet applied pending your call:
- **Wrap and route**: on failure, `GOTO 'Mark Item as Exception'` instead of throwing directly, so the item at least gets tagged before the run fails to the parent. Downside: the item completed successfully in SampleManager but ends up marked as an exception, which may be more confusing than an unmarked item for someone reconciling the queue afterward.
- **Leave as-is**: accept it as a rare, environment-level failure (Dataverse itself is unreachable after 3 retries) and handle it operationally — the parent cloud flow's failure path already fires, and a stuck-status item is discoverable via a queue-age alert. Document in the runbook.

### 7.2 Deferred (agreed)

- F17 — "Completed No Outcome" rule engine (backlog).
- Low findings L1–L7 from the validation report (dead code, copy-paste texts, `flg_ConfigError`) — untouched per scope; cheap to sweep later. Note L2 (`Log In Application` backoff uses the foreign `num_AppRetryCount`) still exists since that function was intentionally left unchanged.
- Native `Requeue Work Queue Item` for item-level retry (§2.1) — considered and deferred, not rejected outright. Revisit if a real transient failure mode emerges that sub-flow-level retries don't already cover.
