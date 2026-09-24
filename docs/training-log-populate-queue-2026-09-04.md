# Training exercise log — BP subsheets → PAD `FUNCTION`s

**Date:** 2026-09-04
**Scope:** hand-translate individual BP subsheets end-to-end into standalone PAD
`FUNCTION ... END FUNCTION` blocks, one page at a time, as a step-by-step learning
exercise — **not** a change to the flowsmith generator, the mapping YAML, or any
pipeline output. This single log file covers every page done in this exercise;
each gets its own top-level part below, in the order it was done.

**Part 1 — "Populate Queue"**
Output: [`outputs/training/populate_queue/FUNCTION_Populate_Queue.txt`](../outputs/training/populate_queue/FUNCTION_Populate_Queue.txt)

**Part 2 — "Mark Item As Completed"**
Output: [`outputs/training/mark_item_as_completed/FUNCTION_Mark_Item_As_Completed.txt`](../outputs/training/mark_item_as_completed/FUNCTION_Mark_Item_As_Completed.txt)

**Rule followed throughout:** nothing under `src/flowsmith`, `mapping/`, `docs/` (except
this log file), or any existing sample/report file was modified. Throwaway diagnostic
scripts were created under `scripts/temp/` (allowed per the task instructions) and nothing
else was written outside `outputs/` and this log.

---

## Part 1 — "Populate Queue"

## Step 0 — What was already on the table when I started

The conversation had already, in prior turns, pulled up:
- `scripts/README.md` (full) — confirms `data/manifest.json` and the per-artefact
  `data/{artefact}.json` / `.md` files are the intended ingestion path, and that
  `stages.jsonl` carries a real BP GUID per stage plus an `is_reachable` flag.
- `mapping/` directory listing (`page_target_map.yaml`, `stage_rules.yaml`,
  `vbo_catalogue.yaml`).
- `samples/pad/fixed/PID171_loader_fixed.txt` (full, 342 lines) — the Loader's fixed
  reference implementation, including `Main_copy`'s `BLOCK 'Add to Queue Block'`
  (lines 65-159), which is the *actual, already-shipped* translation target for
  everything this BP page does, fused into a bigger per-email loop. This became the
  single most important cross-check document for VBO-action syntax.
- `docs/` directory listing.

**Why this matters for the log:** several of the citations below reference exact line
numbers in this file as I first read it, before I separately opened the canonical
`docs/pad-reference/DF_PID_171_US_Loader.robin.txt` copy later (Step 5) to get citeable
line numbers against the *canonical* reference rather than the `_fixed.txt` convenience
copy. Both files contain the same real PAD syntax; only the file used for citation differs
between early and late steps below.

---

## Step 1 — Locate "Populate Queue" in the generated report

Ran (via `Bash`, read-only):
```
ls outputs/report/PID_0171_html_report_20260904/data
cat outputs/report/PID_0171_html_report_20260904/data/manifest.json
```
`manifest.json` confirmed `pid-171-us-process-lims-prelude.{json,md}` is the parsed export
for the process artefact that contains "Populate Queue" (the process is
`PID_171_US_Process_LIMS_Prelude`).

**Grep** for `"Populate Queue"` inside the `.md` export located the page section at line 1185
and — separately — every edge involving it (lines 2598-2992), including a first hint of a
parser artefact I'd need to resolve later: `on_exception` edges listing **five** Block-type
stages against **both** Recover stages on the page (a 5×2 cross-join), which cannot by itself
tell me which Block a given Recover really guards.

**Read** the full page section of the `.md` (`Read` tool, lines 1185-1306) — this gave me
the human-readable stage list, narratives, VBO citations, and the scope-block / data-item
tables, but not enough to resolve the Block↔Recover ambiguity or get exact stage IDs/edges.

## Step 2 — Get the machine-readable stage graph for this one page

The `.md` is pruned/rendered for humans; I needed the raw parsed structure to get exact
`onsuccess`/`ontrue`/`onfalse` stage IDs. Ran a one-off `uv run python -c "..."` (no file
written) against `data/pid-171-us-process-lims-prelude.json`:
- Confirmed top-level shape: `{meta, pages, stages, edges, stage_by_id, stats, release_id}`.
- `pages` is a dict keyed by page GUID; found `"Populate Queue"` → page id
  `b749d60a-bded-4d36-b099-3627ed699606`.
- Filtered `stages` to that `page_id` → **33 stages** (dumped to a temp file under the
  session scratchpad, not the repo, and read back) — the page's actual stage inventory:
  `Start`, `End`, `End5`, `Aquire Lock`, `Got Lock?`, `Mail Items` (LoopStart+LoopEnd),
  `Read EmailSubject`, `Is Item In Queue`, `Item Already added in Queue?`, `Remove Row`,
  `Count Rows`, `No New Emails?`, `Add to Queue`, `Recover`, `Release Lock` (×2, distinct
  stage IDs), `Throw`, `Recover13`, `SE: Aquire Lock`, plus 5 `Block`-type stages
  (`Populate Queue Settings`, `Load Work Block`, `Block13`, `Input`, `Output`) and several
  `Data`/`Collection` stages (`Lock Token`, `Lock Name`, `QueueName`, `Item IDs`,
  `Mail Items`, `Result`, `MailItems_Count`, `Email_Subject`).
- Filtered `edges` to those touching this page's stage IDs — this confirmed the exact
  `onsuccess`/`ontrue`/`onfalse` wiring (reproduced in the mapping table below) and, more
  importantly, reproduced the same 5×2 Block→Recover cross-join already seen in the `.md`.

**Decision point:** I could not resolve real Block/Recover pairing (i.e. which Block a given
Recover actually guards) from `stages`/`edges` alone — the parser emits a full cross-join
of every Block-type stage against every Recover-type stage on a page, not a real nesting
relationship, and `.claude/rules/mapping-yaml-conventions.md`-adjacent context (the
CLAUDE.md rule "*Block → Recover edge is always implicit — it is never in the XML. The
parser must construct this edge (`on_exception` label) for every Block/Recover pair on the
same page*") confirms this is deliberate, documented parser behaviour, not a bug — but it
means the report data alone under-determines the real structure. I needed the raw XML.

## Step 3 — Also found the calling site (Main Page), to get real parameter wiring

Before touching the raw XML, I searched `stages` for a `SubSheet`-type call stage named
"Populate Queue" (`is_subsheet_call: true`) to see how the page is actually invoked from
Main Page. Found it (`page_id: IMPLICIT_MAIN`, `processid` pointing at the Populate Queue
subsheet id) with:
- `QueueName` ← `[ConfigFileData.Queue Name]`
- `Lock Name` ← `[ConfigFileData.Environment Lock]`
- `Mail Items` ← `[Mail Items]` (the same collection populated earlier by the "Get Mails"
  page)
- **no outputs consumed** by the caller — confirms this subsheet is fire-and-forget (its
  purpose is entirely the side effect of populating the work queue; nothing it returns is
  read downstream).

This told me the FUNCTION's three parameters map straight onto BP's own `Start` stage
inputs (`QueueName`, `Lock Name`, `Mail Items`) with no surprises, and that the FUNCTION
should have **no meaningful output parameters** in the translation.

## Step 4 — Wrote a throwaway diagnostic script to resolve Block/Recover geometry

Per the task's own instruction ("if you want to run scripts, create them in
`scripts/temp/`"), wrote `scripts/temp/inspect_populate_queue.py` — parses
`samples/blueprism/PID_0171.bprelease` directly with `lxml`, finds the
`PID_171_US_Process_LIMS_Prelude` `<process>` element (name lives as an **attribute** on
`<process>`, not a child `<name>` element — first thing that tripped the script up), finds
the `Populate Queue` `<subsheet>` id inside `<subsheets>`, then dumps every `<stage>` whose
`<subsheetid>` matches, printing name/type/id and (crucially) its `<display x= y= w= h=>`
geometry.

Two bugs fixed while getting this to run (both visible in the script's own history if
diffed against its current state): an unused, wrong import (`parse_release_file`, which
doesn't exist in `bp_release_parser.py`) — removed since raw `lxml` parsing was all that
was actually needed; and the wrong assumption about where a process's `name` lives.

Ran it (`uv run python scripts/temp/inspect_populate_queue.py`), and separately ran a
follow-up inline Python snippet to sort all 37 raw `<stage>` elements (33 "real" AST stages
+ the `SubSheetInfo` marker, 2× `Anchor`, `Note6` = 37 total XML `<stage>` elements for this
subsheet) by their `x` coordinate and print `(name, type, id, x, y, w, h)` for each.

**This is the step that actually resolved the ambiguity.** Reading the coordinates:

| Block (x range, y range) | Stages whose (x,y) falls inside |
|---|---|
| `Populate Queue Settings` (-390..-240, -75..135) | `Lock Token` (-315,15), `Lock Name` (-315,-30), `QueueName` (-315,105) — all `Data` stages, no flow stages |
| `Input` (-390..-240, 150..210) | `Mail Items` collection var (-345,180), `Email_Subject` (-285,180) — again `Data`/`Collection` stages only |
| `Output` (-390..-240, 225..300) | `Result` (-345,270), `MailItems_Count` (-285,270) — `Data` stages only |
| `Block13` (-75..210, -135..-75) | `Aquire Lock` (15,-105) **and** `Recover13` (150,-105) |
| `Load Work Block` (-75..210, -15..465) | `Mail Items` LoopStart/LoopEnd, `Read EmailSubject`, `Is Item In Queue`, `Item Already added in Queue?`, `Remove Row`, `Count Rows`, `No New Emails?`, `Add to Queue`, and `Recover` (150,15) |

**Conclusion:** three of the five "Block" stages (`Populate Queue Settings`, `Input`,
`Output`) are pure visual groupings around the page's **data-item panel**, not real
try/catch scopes — they contain zero flow stages and zero Recover stages, which is exactly
why the report's cross-join wrongly paired them with both Recovers (a documented parser
limitation, not a real relationship). Only `Block13` (guards `Aquire Lock`, caught by
`Recover13` → throws "Issue on Aquire Lock") and `Load Work Block` (guards the entire
loop/count/enqueue sequence, caught by `Recover` → release-lock-then-rethrow) are real
error-handling scopes. This resolved the only structurally ambiguous part of the page.

## Step 5 — Pulled exact stage XML for every stage whose semantics needed verifying, not assuming

Rather than trust the `.md` summary's paraphrasing for anything I'd actually put in the
generated code, I re-ran targeted `lxml` lookups against specific `stageid`s (all still via
disposable inline Python, no new files) to get the **exact** raw fields for:
- `Read EmailSubject` → confirmed `<calculation expression="[Mail Items.Subject]"
  stage="Email_Subject"/>` — i.e. it assigns to the `Email_Subject` data item (the `.md`'s
  narrative didn't spell out the assignment target explicitly).
- `Got Lock?`, `Item Already added in Queue?`, `No New Emails?` — confirmed exact
  `<decision expression>` text and exact `ontrue`/`onfalse` target stage IDs.
- `Aquire Lock`, `Add to Queue`, `Release Lock` (both occurrences), `Count Rows` — full
  `<inputs>`/`<outputs>`/`<resource object= action=>` blocks, confirming VBO object/action
  names precisely (`BluePrism.AutomateAppCore.clsEnvironmentLockingBusinessObject` for the
  lock actions, `Blueprism.Automate.clsWorkQueuesActions` for queue actions,
  `Blueprism.AutomateProcessCore.clsCollectionActions` for `Count Rows`/`Remove Row`).
- The two `Anchor` stages (`Anchor32`, `Anchor33`) — confirmed they're pure routing
  pass-throughs (`onsuccess` only, no other fields), consistent with
  `docs/bp-to-pad-architecture-PID171.md` §B12's rule to always skip them transparently.
  Specifically: `No New Emails?`'s `ontrue` actually points at `Anchor33`, which points at
  `Release Lock` — the `.md`'s simplified edge table had already resolved this for me
  (`No New Emails? true → Release Lock`), but I verified it against raw XML rather than
  trusting the simplification blindly, since I was about to hand-write code from it.
- **`Note6`** (the stage `Got Lock?`'s false branch actually points at) — this was the one
  genuine surprise. I expected a `Note`-type stage to be a dead end (Notes have no
  processing significance per CLAUDE.md's skip-type list), but its raw XML has a real
  `<onsuccess>949d4522...</onsuccess>` pointing at `End5`, **and** a `<narrative>` reading
  *"Another session is loading work"* — i.e. Blue Prism does allow a Note to sit inline on a
  branch as a documented pass-through, and this Note is the only place in the whole page
  that explains *why* the "lock not acquired" branch just quietly ends. I kept that text as
  a comment in the generated code specifically because of this — dropping it would have
  silently discarded the only explanation for that branch's behaviour, which
  `docs/bp-to-pad-architecture-PID171.md` §B12 explicitly says not to do ("never skip a
  Note silently if the text conveys BP-author intent worth keeping visible").

## Step 6 — Established every VBO-action → PAD-syntax mapping from cited sources, not memory

Read in full:
- `docs/pad-reference/vbo-action-mapping.md` — the project's single source of truth for
  VBO→PAD action syntax. Found:
  - **Work Queues → `:: Add To Queue`**: `WorkQueues.EnqueueWorkQueueItem.WithoutUniqueId
    ...` (cites Loader L140).
  - **Work Queues → `:: Is Item In Queue` / duplicate check**: `WorkQueues.GetWorkQueueItems
    WorkQueue: <id> FilterRows: '<FetchXML>' RowsToReturn: 5000 WorkQueueItems=> <list>`,
    then `IF <list>.Count > 0` (cites Loader L90-102).
  - **`clsEnvironmentLockingBusinessObject :: Acquire/Release Lock`**: explicitly
    `**STOP** — no PAD equivalent found`, with the exact reasoning ("PAD's Dataverse-backed
    `ProcessWorkQueueItem` already provides safe concurrent dequeue, so this BP-side
    mutual-exclusion lock may simply be unnecessary in PAD rather than needing translation
    — confirm before adding a custom lock mechanism").
- `.claude/rules/mapping-yaml-conventions.md` (surfaced automatically as project context) —
  this is what made me go back and **check, then discard**, `mapping/vbo_catalogue.yaml`'s
  own `clsEnvironmentLockingBusinessObject` row (which proposes a `shared_sharepointonline`
  / Azure-Service-Bus mutex, `confidence_base: 0.45`). The rule file explicitly warns that
  several `vbo_catalogue.yaml` rows were generated against a *different* BP sample
  (`PID_0127`) and contradict now-confirmed PID_171 behaviour. Since
  `vbo-action-mapping.md` is the PID_171-specific, curated ground truth and directly
  contradicts the YAML row (STOP vs. a proposed mechanism), I treated the YAML row as
  exactly the kind of stale entry the rule warns about and did **not** use it — Acquire/
  Release Lock became `# TODO` / `ReviewFlag`-style comments instead of a fabricated
  SharePoint call. This is the single most consequential judgement call in the whole
  exercise and is why it gets its own paragraph here rather than a table row.
- `docs/bp-to-pad-architecture-PID171.md` §A4 (variable naming convention table — `txt_`,
  `num_`, `flg_`, `obj_`, `lst_`, `dtb_`/`dtr_`, `dt_`, `ins_`, `In_`/`Out_`), §A5
  (BLOCK/ON BLOCK ERROR dispatch template + `FlowControl.ThrowCustomError` raise template +
  the "no IF inside a handler" hard constraint), §B12 (the full BP-stage-type → PAD-construct
  table — this is where `RECOVER`/`RESUME` "no standalone emission, handler body becomes the
  block's ON BLOCK ERROR" and `BLOCK` "only emit the wrapper when a Recover exists in scope"
  come from), and §B14 (the page-by-page crosswalk — row 2 confirms "Populate Queue" 37
  stages maps, in the real shipped solution, to the Loader's `BLOCK 'Add to Queue Block'`,
  **not** a standalone FUNCTION — see the explicit note in the generated file's header about
  why I built a standalone FUNCTION anyway for this exercise).
- `docs/pad-reference/DF_PID_171_US_Loader.robin.txt` (the **canonical** reference copy, as
  opposed to the `_fixed.txt` convenience copy read in Step 0) — re-grepped specifically for
  citeable line numbers:
  - `L51`: `IF lst_MailItems.Count = 0 THEN` — confirms `.Count` is read as a plain property,
    never a discrete "Count Rows" action, anywhere in the real reference code. This is what
    justified translating BP's `Count Rows` action as `SET num_MailItemsCount TO
    In_lst_MailItems.Count` rather than inventing a PAD action for it.
  - `L91-98`: the exact `WorkQueues.GetWorkQueueItems ... FilterRows: '<FetchXML>' ...`
    call and FetchXML shape, which I reused verbatim (with the filter's key value swapped
    from the Loader's `%txt_MailIdHash%` to this page's own `%txt_EmailSubject%`, since this
    BP page keys its own dedup check on Subject, not on a hash — a deliberate,
    logged-in-the-code decision **not** to silently borrow the Loader's more elaborate,
    hash-based key for a page that doesn't use one).
  - `L100-102`: `IF lst_WorkQueueItems.Count > 0 THEN ... END` confirming the boolean-from-
    count-check idiom.
  - `L140`: `WorkQueues.EnqueueWorkQueueItem.WithoutUniqueId ...` — confirmed the exact
    param list and casing.
  - `L298-302`: `LOOP num_ItemIndex FROM lst_MailItems.Count - 1 TO 0 STEP -1 ... IF
    lst_FilteredList.Count = 0 THEN Variables.RemoveItemFromList.RemoveItemFromListByIndex
    ItemIndex: num_ItemIndex List: lst_MailItems END` — **this is the exact precedent** I
    needed to translate BP's forward `LoopStart`/`Decision`/`Remove Row`/`LoopEnd` pattern
    (removing rows from a collection while nominally iterating it) into something PAD-safe.
    PAD's `LOOP FOREACH` cannot safely remove the current item mid-iteration; rather than
    invent a workaround, I copied this exact already-proven idiom (reverse-indexed counted
    loop + `RemoveItemFromListByIndex`), just applied to this page's own condition (already-
    queued, via the Subject-keyed `GetWorkQueueItems` check) instead of the Loader's
    (sender not in the allow-list).
  - `L219`: `THROW ERROR` — confirmed this is PAD's real re-raise keyword (matches BP's
    `exception_usecurrent: true` semantics on the page's `Throw` stage), also cross-checked
    against `docs/bp-to-pad-pipeline-plan.md:370` ("Real PAD for exception re-raise: `THROW
    ERROR`") and `docs/SUBTASK8_VALIDATION_REPORT.md:130` (a validation report scoring this
    exact mapping a "MATCH" across 17 real occurrences).
- `samples/pad/fixed/PID171_loader_fixed.txt:193` — cited as the precedent for a **plain
  (non-`GLOBAL`) `FUNCTION` with `In_`-prefixed parameters and no return value**
  (`FUNCTION 'Send Business Exception Mail' In_txt_To_Email, In_txt_Cc_Email, ...`), which is
  the shape I used for `FUNCTION 'Populate Queue'` — justified because, unlike the Loader's
  `Main_copy` (which is `GLOBAL` because it owns/mutates the shared state every other
  function reads), this page never reads or writes a variable outside its own three
  parameters and its own local working variables, so §A4's `GLOBAL.` qualification rule
  doesn't apply and the plain form is correct.

## Step 7 — Stage-by-stage mapping table actually used in the generated code

| BP stage(s) | Type | PAD translation | Citation |
|---|---|---|---|
| `Start` (inputs: QueueName, Lock Name, Mail Items) | Start | `FUNCTION 'Populate Queue' In_txt_QueueName, In_txt_LockName, In_lst_MailItems` | §A4 naming table; `_fixed.txt:193` for the plain-`FUNCTION` shape |
| `MailItems_Count` data item, `initial_value=5` | Data | `SET num_MailItemsCount TO 5` at top of body | §B12 COLLECTION/DATA row |
| `Aquire Lock` (wrapped in `Block13`) | Action, `clsEnvironmentLockingBusinessObject :: Acquire Lock` | `# TODO` / `ReviewFlag` stub; placeholder non-empty token assigned to `txt_LockToken` so downstream logic stays reachable | vbo-action-mapping.md STOP row; `.claude/rules/mapping-yaml-conventions.md` (why the stale YAML row was rejected) |
| `Recover13` → `SE: Aquire Lock` | Recover → Exception (`System Exception`, `"Issue on Aquire Lock"`) | `ON BLOCK ERROR` handler body: `FlowControl.ThrowCustomError CustomErrorCode: $'''System Exception''' CustomErrorMessage: $'''Issue on Aquire Lock'''` | §A5 dispatch + raise templates |
| `Got Lock?` (`[Lock Token]<>""`) | Decision | `IF txt_LockToken <> $'''%''%''' THEN ... ELSE ... END` | §B12 DECISION row |
| `Note6` ("Another session is loading work") → `End5` | Note → End | `# comment` + `EXIT FUNCTION` in the `ELSE` branch | §B12 NOTE row |
| `Mail Items` LoopStart/LoopEnd + `Read EmailSubject` + `Is Item In Queue` + `Item Already added in Queue?` + `Remove Row` (wrapped in `Load Work Block`) | Loop/Calculation/Action/Decision/Action | One reverse-indexed `LOOP num_ItemIndex FROM In_lst_MailItems.Count - 1 TO 0 STEP -1` doing the subject lookup, `WorkQueues.GetWorkQueueItems` dedup check, and conditional `Variables.RemoveItemFromList.RemoveItemFromListByIndex` | `DF_PID_171_US_Loader.robin.txt` L91-102 (dedup call) + L298-302 (safe-removal idiom); vbo-action-mapping.md Work Queues section |
| `Recover` → `Release Lock` → `Throw` | Recover → Action → Exception (re-raise) | `ON BLOCK ERROR` handler body: `# TODO` (Release Lock stub) + `THROW ERROR` | §A5 templates; `DF_PID_171_US_Loader.robin.txt:219` for `THROW ERROR` |
| `Count Rows` (on "Mail Items") | Action, `clsCollectionActions :: Count Rows` | `SET num_MailItemsCount TO In_lst_MailItems.Count` (property access, no discrete action) | `DF_PID_171_US_Loader.robin.txt:51` |
| `No New Emails?` (`[MailItems_Count]=0`) + `Add to Queue` | Decision + Action, `clsWorkQueuesActions :: Add To Queue` | `IF num_MailItemsCount > 0 THEN LOOP FOREACH obj_CurrentMailItem IN In_lst_MailItems ... WorkQueues.EnqueueWorkQueueItem.WithoutUniqueId ... END END` (bulk call decomposed into one confirmed per-row call, since no bulk PAD action is confirmed) | vbo-action-mapping.md Work Queues section (`:: Add To Queue` row, cites canonical ref L140) |
| `Release Lock` (success path) | Action | `# TODO` stub, same gap as `Aquire Lock` | same as above |
| `End` | End | implicit (falls through to `END FUNCTION`, no outputs — call site consumes none) | Step 3 finding |

## Step 8 — What I deliberately did *not* do, and why

- **Did not use `mapping/vbo_catalogue.yaml`'s lock-VBO row.** Covered above (Step 6) — it's
  the one stale, pre-PID_171 entry the project's own rules flag, and it directly contradicts
  the curated `vbo-action-mapping.md` STOP row.
- **Did not silently drop `Acquire Lock`/`Release Lock`.** Left as `# TODO` comments with a
  `ReviewFlag`-shaped explanation each, per CLAUDE.md's "never silently drop a BP construct
  that can't be translated" rule and the MANUAL confidence band's "stub only +
  ReviewFlag(severity=error)" contract. The one deliberate departure from a pure "stub only"
  reading: I gave `txt_LockToken` a **non-empty placeholder value** rather than leaving it
  genuinely empty, specifically so the `Got Lock?` branch and everything downstream of it
  remains reachable and demonstrable for this training exercise — a real generator run would
  arguably leave it empty (and therefore dead-code the happy path) until a human resolves
  the `ReviewFlag`, and I've said so explicitly in the code comment so this choice is visible
  and challengeable, not hidden.
- **Did not fuse in logic from other BP pages** (the mail-hashing, attachment-JSON-building,
  AES-encryption, and Key-Vault steps that the *real* Loader's `BLOCK 'Add to Queue Block'`
  also does). Those all belong to *other* BP pages/stages (`Get Mails`'s hash generation,
  etc.) that are out of scope for a translation of *this one subsheet*. Mentioned explicitly
  in the generated file's header comment so this isn't mistaken for an oversight.
- **Did not implement `CHOICE`.** Not present on this page (no `Choice`-type stages were
  found), consistent with CLAUDE.md's explicit "do not implement until a real sample is
  obtained" rule and the project rule file's reminder to leave `CHOICE` out of
  `stage_rules.yaml` regardless.
- **Did not touch any file under `mapping/`, `src/flowsmith/`, `docs/pad-reference/`, or any
  existing `docs/*.md`.** Only new files were created: this log, the generated `.txt` output,
  and the throwaway `scripts/temp/inspect_populate_queue.py` diagnostic.

## Step 9 — Verification performed

- Confirmed every VBO object/action name, every `onsuccess`/`ontrue`/`onfalse` edge, and
  every Block's geometry directly against the raw `.bprelease` XML (Steps 4-5) rather than
  relying on the `.md`/`.json` report's paraphrasing anywhere it mattered for generated code.
- Confirmed every PAD syntax fragment used (`WorkQueues.GetWorkQueueItems`,
  `WorkQueues.EnqueueWorkQueueItem.WithoutUniqueId`,
  `Variables.RemoveItemFromList.RemoveItemFromListByIndex`, `Variables.ConvertCustomObjectToJson`,
  `THROW ERROR`, `FlowControl.ThrowCustomError`, the `BLOCK ... ON BLOCK ERROR ... END`
  shape, the `$'''...'''` string-literal form, the `@@'InputSummaryValue:WORKQUEUE'`
  annotation line preceding a `WorkQueues` call) against at least one real, cited line number
  in `docs/pad-reference/DF_PID_171_US_Loader.robin.txt` — nothing was written from memory or
  "this looks plausible" reasoning.
- Did **not** run the generated PAD code through any PAD runtime (none is available in this
  environment) — this is a syntax-and-mapping-fidelity exercise, not an executed test. This
  limitation is stated here rather than left implicit.

## Step 10 — Revision: comment length

User feedback after the first pass: the generated `.txt` had too many long, multi-line
comment blocks. Rewrote every comment in
`outputs/training/populate_queue/FUNCTION_Populate_Queue.txt` down to at most 3 consecutive
lines (verified programmatically — max consecutive `#`-line run is now 3), trimming prose
and moving anything not essential to reading the code (the full BP-geometry evidence,
the stale-YAML-row discussion, the open questions) into this log instead, where it already
lived in full. No structural or semantic change to the translation itself — same stages,
same mappings, same citations, just condensed inline commentary with pointers back here for
the full reasoning.

## Known open questions for the user's review

1. Whether the `Aquire Lock`/`Release Lock` stub approach (placeholder non-empty token
   rather than a true no-op) is acceptable for this exercise, or whether a genuinely empty
   stub (forcing the `Got Lock?` false/"another session" branch) would better represent an
   honest MANUAL-confidence translation.
2. Whether decomposing BP's bulk `Add to Queue` collection call into a per-row
   `EnqueueWorkQueueItem.WithoutUniqueId` loop is the right adaptation, versus flagging the
   whole "Add to Queue" stage as a gap since no bulk PAD action is confirmed.
3. Whether keying the dedup check on `Email_Subject` (this page's literal, if arguably
   fragile, own logic) rather than silently upgrading it to the Loader's later hash-based key
   was the right call for a *literal* page translation — flagged explicitly in-code either
   way.

---

## Part 2 — "Mark Item As Completed"

**Output artefact:** [`outputs/training/mark_item_as_completed/FUNCTION_Mark_Item_As_Completed.txt`](../outputs/training/mark_item_as_completed/FUNCTION_Mark_Item_As_Completed.txt)

### Step 1 — Locate the page

Grepped `"Mark Item As Completed"` in `data/pid-171-us-process-lims-prelude.md` — page
section at line 907, **6 stages**, `Start → Set Status → Mark Completed → Reset Consecutive
Exception Indicators → Is Completed → End3`. No `Scope blocks` table and no `Data items`
table rendered for this page (unlike "Populate Queue") — first sign this page declares no
local Data items of its own at all.

### Step 2 — Machine-readable stage graph + calling site

Same `uv run python -c "..."` approach as Part 1, against
`data/pid-171-us-process-lims-prelude.json`: found the page id
(`d31d1c11-61ad-4c49-91a4-44bbf0bf0725`, matching the `<subsheet>` list from Part 1's Step 4
script output), filtered `stages` to it — **exactly 6 stages**, confirming the `.md`'s count,
none of type `Block`, `Recover`, `Data`, or `Collection`. No Block/Recover ambiguity to
resolve this time (unlike Part 1) — the page is a flat, linear sequence.

Found the Main-Page `SubSheet`-call stage (`is_subsheet_call: true`, `processid` matching
this page's id) — its `inputs` and `outputs` are both **empty**. Combined with Step 1's
"no local Data items" finding, this means every data item this page's stages reference
(`[Item ID]`, `[Previous Exception Detail]`, `[Consecutive Exception Count]`) must be
Main-Page-scoped globals read implicitly, not page parameters or local Data items — a
different BP authoring style from "Populate Queue" (which declared 3 explicit `Start`
inputs). Noted as a real, evidence-based difference between the two pages, not an
inconsistency in method.

### Step 3 — Raw XML for every stage (no ambiguity, but no guessing either)

Re-ran the same `lxml`-direct-parse approach as Part 1 against
`samples/blueprism/PID_0171.bprelease`, filtered to this subsheet id — **7** raw `<stage>`
elements (6 AST stages + 1 `SubSheetInfo` marker, itself confirming the page's own
narrative: *"Marks the current work queue item as complete"*). Confirmed exact assignment
targets that the `.md`'s narrative-only rendering doesn't spell out:
- `Set Status` → `Blueprism.Automate.clsWorkQueuesActions :: Update Status`, inputs
  `Item ID=[Item ID]`, `Status="COMPLETED"`.
- `Mark Completed` → `Blueprism.Automate.clsWorkQueuesActions :: Mark Completed`, input
  `Item ID=[Item ID]`.
- `Reset Consecutive Exception Indicators` (`MultipleCalculation`) → two `<calculation>`
  steps: `"" → stage="Previous Exception Detail"`, `0 → stage="Consecutive Exception Count"`.
- `Is Completed` (`Calculation`) → `<calculation expression="True" stage="flg_IsCompleted"/>`
  — this is the one genuine surprise: the stage is *named* "Is Completed" but writes to a
  data item named `flg_IsCompleted`, not "Is Completed". Cross-checked against Part 1's own
  earlier finding (while reading the "Reset Global Data" page for an unrelated reason) that
  `flg_IsCompleted` is declared there with `initial_value=True` — confirms `flg_IsCompleted`
  is a genuine Main-Page-scoped global reset at the start of every run and re-armed to
  `True` here at item completion, not a page-local variable invented for this stage.

### Step 4 — Cross-checked against the real, shipped reference *before* writing any PAD code

Read `samples/pad/fixed/PID171_performer_fixed.txt`'s `FUNCTION 'Mark Complete'`
(lines 784-826) — the actual, already-shipped PAD counterpart for this BP page (confirmed
by `docs/bp-to-pad-architecture-PID171.md` §B14's page-crosswalk, which lists "Mark Item As
Completed" → Performer's `Mark Complete`). Three load-bearing findings from it, used
directly in the translation below:
- It takes `In_obj_WorkQueueItem` (an **object**), not a bare ID — and its very first line
  is `SET obj_WorkQueueItem TO In_obj_WorkQueueItem`. This exists because both of the
  *confirmed* PAD actions for BP's `Update Status`/`Mark Completed`
  (`WorkQueues.UpdateProcessingNotes.WithProcessingNotes` /
  `WorkQueues.UpdateWorkQueueItem.UpdateWithProcessingNotes`, both cited in
  `docs/pad-reference/vbo-action-mapping.md`'s Work Queues section) take a `WorkQueueItem:
  <obj>` parameter, not a scalar ID — there is no confirmed PAD action taking a bare ID for
  either BP method. So even though BP's own page signature has no input at all (Step 2), the
  literal-BP-Item-ID reading has to become an explicit object parameter on the PAD side,
  because that's the only shape any confirmed target action accepts. This is *not* a
  stylistic choice — it's forced by which actions are actually confirmed to exist — and it's
  taken directly from a real, cited, already-shipped function rather than invented.
- Lines 819-820 — `SET GLOBAL.txt_PreviousExceptionMessage TO $'''%''%'''` /
  `SET GLOBAL.num_ConsecutiveExcCount TO 0` — is a **direct, literal, already-confirmed
  match** for BP's `Reset Consecutive Exception Indicators` MultipleCalculation. This is the
  cleanest citation of the whole exercise so far: the real reference resets the exact same
  two fields, for the documented exact same reason ("a success breaks the cross-item
  consecutive-failure streak"), which also independently confirms BP's `Previous Exception
  Detail` → PAD `txt_PreviousExceptionMessage` and BP's `Consecutive Exception Count` → PAD
  `num_ConsecutiveExcCount`, matching `docs/bp-to-pad-architecture-PID171.md`'s own §A7
  circuit-breaker state description (`GLOBAL.num_ConsecutiveExcCount`,
  `GLOBAL.txt_PreviousExceptionMessage`), read earlier during Part 1.
- The real reference wraps both WorkQueues calls in a `LOOP ... BLOCK 'Queue update block -
  Complete' ON BLOCK ERROR (swallow) ... END ... END` retry loop (EB-2 hardening, per the
  file's own header) and captures a `DateTime`/`txt_FormattedDateTime` for a richer
  `ProcessingNotes` message. **Neither of these has any counterpart stage anywhere on the BP
  page** (no `Block`, no `Recover`, no DateTime action — confirmed in Step 3's stage list).
  They are pure PAD-side hardening added when the real solution was built, not a translation
  of anything BP does. Per the same literal-translation-fidelity method used in Part 1 (never
  silently adopt the reference's enhancements as if they were in the BP source), I did **not**
  add a retry loop or a timestamp to the generated code — flagged explicitly instead (see the
  generated file's comments and the feedback delivered in chat for this task's step 3).

### Step 5 — Mapping table used in the generated code

| BP stage | Type | PAD translation | Citation |
|---|---|---|---|
| `Start` (no inputs declared) | Start | `FUNCTION 'Mark Item As Completed' In_obj_WorkQueueItem` + `SET obj_WorkQueueItem TO In_obj_WorkQueueItem` | Step 4 — forced by the confirmed action signatures, matches the real `Mark Complete`'s own opening line |
| `Set Status` (`Update Status`, `Status="COMPLETED"`) | Action | `WorkQueues.UpdateProcessingNotes.WithProcessingNotes WorkQueueItem: obj_WorkQueueItem ProcessingNotes: $'''COMPLETED'''` | vbo-action-mapping.md Work Queues section, `:: Update Status` row |
| `Mark Completed` | Action | `WorkQueues.UpdateWorkQueueItem.UpdateWithProcessingNotes WorkQueueItem: obj_WorkQueueItem Status: WorkQueues.WorkQueueItemStatus.Processed` | vbo-action-mapping.md Work Queues section, `:: Mark Completed` row (cites canonical Performer ref L1212) |
| `Reset Consecutive Exception Indicators` (`""`→Previous Exception Detail, `0`→Consecutive Exception Count) | MultipleCalculation | `SET GLOBAL.txt_PreviousExceptionMessage TO $'''%''%'''` + `SET GLOBAL.num_ConsecutiveExcCount TO 0` | Direct literal match, real `Mark Complete` L819-820 |
| `Is Completed` (`True`→flg_IsCompleted) | Calculation | `SET GLOBAL.flg_IsCompleted TO True` | §B12 CALCULATION row; global-ness confirmed via "Reset Global Data" page's own declaration of the same name |
| `End3` | End | implicit (falls through to `END FUNCTION`, no outputs — call site consumes none) | Step 2 finding |

### Step 6 — What I deliberately did not do, and why

- **Did not add a retry loop or `BLOCK`/`ON BLOCK ERROR` wrapper.** BP's page has zero
  `Block`/`Recover` stages — a literal translation of *this page* has none either. The real
  reference's EB-2 retry hardening is a PAD-side design addition with no BP-side stage to
  translate from; noted in the generated file and in this log rather than silently copied in
  or silently ignored.
- **Did not add a `DateTime`/timestamped `ProcessingNotes` message.** Same reasoning — no
  DateTime-capture stage exists on this BP page. Kept BP's own literal `"COMPLETED"` string
  as the note text instead of the reference's richer message.
- **Did not invent a bare-ID-taking PAD call.** Confirmed both target actions require the
  item object, not a scalar ID (Step 4) — used the object parameter shape instead of
  guessing a scalar-ID overload might exist.

### Step 7 — Verification performed

Same standard as Part 1: every VBO object/action name and every stage's exact assignment
target was confirmed against the raw `.bprelease` XML (Step 3), not the `.md`'s paraphrasing.
Every PAD syntax fragment used (`WorkQueues.UpdateProcessingNotes.WithProcessingNotes`,
`WorkQueues.UpdateWorkQueueItem.UpdateWithProcessingNotes`, the `GLOBAL.` variable names) is
either directly cited in `docs/pad-reference/vbo-action-mapping.md` or copied verbatim from
the real, already-shipped `Mark Complete` FUNCTION. No PAD runtime was available to execute
the generated code — stated here rather than left implicit, same as Part 1.

The formal side-by-side comparison against `samples/pad/fixed/PID171_loader_fixed.txt`
(Populate Queue) and `samples/pad/fixed/PID171_performer_fixed.txt` (Mark Item As Completed)
requested as a separate task was delivered in the chat response, not duplicated into this
log file.
