# Blue Prism XML Schema — Ground Truth
> Derived from empirical analysis of `sample-process.xml` (2174 lines),
> `sample-object.xml` (217 lines), and `sample-release.xml`,
> cross-referenced against the official Blue Prism 6.10 documentation stage-type list.
> This document is the authoritative parser contract for Flowsmith.
>
> **Revision notes:**
> - `Choice` promoted to its own canonical AST type (`CHOICE`, #18). See §5b and §6.4a.
> - `Alert` and `Skill` confirmed as `ACTION` normalisations. See §5b, §6.16, §6.17.
> - `.bprelease` file format documented: release namespace, content types, env vars, groups. See §2b–§2d.
> - `WaitStart`/`WaitEnd` child elements (`<timeout>`, `<groupid>`, `<choices>`) documented. See §6.14.
> - `parse_element()` API documented (§10 note #9).
> - Section numbering in §10 corrected.

---

## 1. Namespace Contract

**Every element** in a `.bprelease` / `.bpprocess` / `.bpobject` file lives under:

```
http://www.blueprism.co.uk/product/process
```

The parser **must** register or strip this namespace before any XPath or
`find()` call. Failing to do so returns empty results silently.

```python
NS = "http://www.blueprism.co.uk/product/process"
BP = f"{{{NS}}}"          # use as: f"{BP}stage"
strip_ns = lambda tag: tag.replace(BP, "")
```

---

## 2. Root Discriminator — Process vs Object

The file root tag determines the artefact type.

| Root tag     | Artefact type | `published` attr present? |
|--------------|---------------|--------------------------|
| `<process>`  | Process       | Yes (`"true"` / `"false"`) |
| `<object>`   | VBO / Object  | No                        |

The root element has one mandatory child: `<process>` (same tag, different
level). This inner `<process>` carries the metadata.

### Root attributes

| Attribute | Required | Notes |
|-----------|----------|-------|
| `id`      | Yes      | UUID, unique process/object identifier |
| `name`    | Yes      | Display name |
| `published` | Process only | `"true"` / `"false"` (lowercase) |

### Inner `<process>` metadata attributes

| Attribute | Required | Notes |
|-----------|----------|-------|
| `name`    | Yes      | Same as root name |
| `version` | Yes      | e.g. `"1.0"` |
| `bpversion` | Yes   | e.g. `"7.3.1.15031"` |
| `narrative` | No    | Description text |
| `type`    | Object only | `"object"` |
| `runmode` | Object only | `"Background"` / `"Exclusive"` / `"Foreground"` |
| `byrefcollection` | No | `"true"` / `"false"` |
| `disableversioning` | No | `"true"` / `"false"` |

### Inner `<process>` children to **ignore** for migration

`<appdef>`, `<view>`, `<preconditions>`, `<endpoint>`

---

## 2b. `.bprelease` File Format

A `.bprelease` file is an export container. It holds one or more processes,
objects, environment variables, and group definitions in a single XML file.

### Release namespace

The release root and its metadata children use a **separate namespace** from
the process/object content:

```
http://www.blueprism.co.uk/product/release   (bpr:)
```

The `<process>` and `<object>` content items inside the release use the
**standard BP process namespace** (`http://www.blueprism.co.uk/product/process`).
Environment variables use their own namespace:
```
http://www.blueprism.co.uk/product/environment-variable   (env:)
```

### Root structure

```xml
<bpr:release xmlns:bpr="http://www.blueprism.co.uk/product/release">
  <bpr:name>PID_0127_Process_US_BulkUnlock_23March2026_Export</bpr:name>
  <bpr:release-notes/>
  <bpr:created>2026-03-23 07:35:34Z</bpr:created>
  <bpr:package-id>890</bpr:package-id>
  <bpr:package-name>PID_0127_Process_US_BulkUnlock_23March2026_Export</bpr:package-name>
  <bpr:user-created-by>user@domain.com</bpr:user-created-by>
  <bpr:contents count="47">
    <!-- N items: process | object | environment-variable | process-group | object-group -->
  </bpr:contents>
</bpr:release>
```

### Release metadata fields

| Element | Type | Notes |
|---------|------|-------|
| `<bpr:name>` | string | Release display name |
| `<bpr:created>` | datetime | ISO format with Z suffix |
| `<bpr:package-id>` | integer | Numeric package identifier |
| `<bpr:package-name>` | string | Usually same as name |
| `<bpr:user-created-by>` | email | Creator's BP login |
| `<bpr:contents count="N">` | container | N = declared total item count |

> **`count` attribute:** The declared count includes ALL item types (processes,
> objects, env vars, groups). Validate that `process_count + object_count +
> env_var_count + group_count + error_count` equals this `declared_count` —
> any gap means an unrecognised content type was silently skipped.

### Content item types

| XML tag | Namespace | Parser disposition |
|---------|-----------|-------------------|
| `<process>` | BP process NS | Parse via `parse_element()` — full artefact |
| `<object>` | BP process NS | Parse via `parse_element()` — full artefact |
| `<environment-variable>` | env: NS | Parse directly — see §2c |
| `<process-group>` | own NS | Parse for cross-reference only — not migrated |
| `<object-group>` | own NS | Parse for cross-reference only — not migrated |

### `<process>` and `<object>` in a release

The `<process>` and `<object>` elements inside a release are structurally
identical to their standalone file counterparts — same namespace, same inner
`<process>` child, same stage structure. The only additions are release-level
wrapper attributes:

```xml
<process xmlns="http://www.blueprism.co.uk/product/process"
         id="21fbccd0-f313-4ed2-adf7-39625af1ed85"
         name="PID_0127_Process_US_BulkUnlock"
         published="true">
  <process name="..." version="1.0" bpversion="7.3.1.15031" ...>
    <!-- full process content -->
  </process>
</process>
```

**Additional wrapper attributes (not present in standalone files):**

| Attribute | Present on | Notes |
|-----------|-----------|-------|
| `id` | process, object | UUID — unique within the BP environment |
| `published` | process only | `"true"` / `"false"` (lowercase) |

---

## 2c. Environment Variable Schema

Environment variables are key-value configuration pairs exported as part of a
release. They are referenced by processes at runtime via the BP credential/env
store. They have their own namespace: `http://www.blueprism.co.uk/product/environment-variable`.

```xml
<environment-variable
    xmlns="http://www.blueprism.co.uk/product/environment-variable"
    id="Generic_RPA_Sharepoint_API_Config_File_Folder_Path"
    name="Generic_RPA_Sharepoint_API_Config_File_Folder_Path"
    type="text"
    value="/sites/AAFAA5234/RPA Config File/Prod Config File API/">
  <description>SharePoint Config file Path</description>
</environment-variable>
```

**Attributes:**

| Attribute | Required | Notes |
|-----------|----------|-------|
| `id` | Yes | Typically same as `name`; used as the env var key |
| `name` | Yes | Display name |
| `type` | Yes | BP data type — same enum as stage data types (§9) |
| `value` | Yes | Current value as plain text |

**Children:**

| Child | Required | Notes |
|-------|----------|-------|
| `<description>` | No | Human-readable description of what the variable is used for |

> **Namespace note:** the `<description>` child uses the same env-var namespace.
> Some BP versions may omit the namespace on the description element — parsers
> must try both `{NS}description` and bare `description`.

---

## 2d. Group Schema (process-group / object-group)

Groups organise processes and objects into folder-like structures in the BP
Studio tree view. They are reference metadata only — not migrated to Power
Automate. Useful for understanding deployment structure.

```xml
<process-group id="19a73585-..." name="PROJECTS/GF-IT/Upstream/PID_0127"
               isDefaultGroup="False"
               xmlns="http://www.blueprism.co.uk/product/process-group">
  <members>
    <member id="21fbccd0-f313-4ed2-adf7-39625af1ed85" />
  </members>
</process-group>
```

**Attributes:**

| Attribute | Notes |
|-----------|-------|
| `id` | UUID of the group |
| `name` | Full path name (slash-delimited hierarchy) |
| `isDefaultGroup` | `"True"` for the "Default" group that catches ungrouped items |

**`<members>`:** list of `<member id="..."/>` elements referencing process/object
UUIDs. Use these to build a group membership cross-reference — which processes
and objects belong to which group path.

Each `<subsheet>` represents one **page** of the process/object.

### Attributes

| Attribute    | Type   | Required | Notes |
|-------------|--------|----------|-------|
| `subsheetid` | UUID  | Yes      | Primary key; stages reference this |
| `type`       | Enum  | Yes      | See table below |
| `published`  | Bool  | Yes      | ⚠️ casing varies — normalise to Python `bool` |

**`published` casing gotcha:**
- Process files use `"False"` / `"True"` (titlecase)
- Object files use `"True"` (titlecase)
- Always do: `published = attrib["published"].lower() == "true"`

### Subsheet `type` enum

| Value       | Meaning |
|-------------|---------|
| `Normal`    | Standard page |
| `CleanUp`   | Clean-up page (object only) |
| `Main`      | Main page (implicit, may not appear as explicit subsheet in all versions) |

### Children

| Child tag | Required | Capture? | Notes |
|-----------|----------|----------|-------|
| `<name>`  | Yes      | **Yes**  | Text content = page display name |
| `<view>`  | No       | No       | Layout coordinates, ignore |

### Capture target
```python
{
  "subsheetid": str,   # UUID
  "name": str,         # from <name> child text
  "published": bool,   # normalised
  "type": str,         # "Normal" | "CleanUp" | ...
}
```

---

## 4. Stage Base Schema

Every `<stage>` has these three mandatory attributes regardless of type:

| Attribute  | Type | Notes |
|-----------|------|-------|
| `stageid`  | UUID | Primary key |
| `name`     | str  | Display name |
| `type`     | Enum | See §5 |

### Universal optional children (present on most types)

| Child tag     | Capture? | Content |
|--------------|----------|---------|
| `<subsheetid>` | **Yes** | Text = UUID of the page this stage belongs to. **Absence is meaningful — see page identity rule below.** |
| `<onsuccess>` | **Yes** | Text = `stageid` of the next stage (flow edge) |
| `<narrative>` | Yes     | Text = stage description/comment |
| `<loginhibit>` | No     | Logging config, ignore |
| `<display>`   | No      | Visual coordinates, ignore |
| `<font>`      | No      | Visual styling, ignore |

### Page identity rule (ground truth)

The presence or absence of `<subsheetid>`, combined with the artefact root tag,
determines which page a stage belongs to. This is the **only** reliable way to
group stages into pages — do not infer page membership from stage order in the XML.

| Stage has `<subsheetid>`? | Artefact root tag | Page assignment |
|--------------------------|-------------------|-----------------|
| Yes                      | Either            | The subsheet whose `subsheetid` attribute matches the text value |
| No                       | `<process>`       | **Main page** (implicit — no UUID, never appears as a `<subsheet>` element) |
| No                       | `<object>`        | **Initialize page** (implicit — same rule, different name by convention) |

The `ProcessInfo` stage always lives on the implicit page (no `<subsheetid>`).
It is the reliable marker that the implicit page exists — every process and
object has exactly one `ProcessInfo` stage.

---

## 5. Complete Stage Type Inventory

30 XML type strings total. Grouped by parser disposition.

### 5a. SKIP — No AST node produced

| XML `type` string | Reason |
|-------------------|--------|
| `Anchor`          | Visual navigation aid only |
| `Note`            | Comment/documentation stage |
| `SubSheetInfo`    | Header marker for a **named subsheet** — has `<subsheetid>`, not executable |
| `ProcessInfo`     | Header marker for the **implicit Main/Initialize page** — no `<subsheetid>`, not executable |

> **`SubSheetInfo` and `ProcessInfo` are structurally parallel skip types.**
> Both serve as page header anchors on the canvas. Neither is executable.
> The difference is which page they mark:
>
> | Type | Marks | Has `<subsheetid>`? |
> |------|-------|---------------------|
> | `SubSheetInfo` | A named subsheet (Normal, CleanUp, etc.) | Yes — contains the page UUID |
> | `ProcessInfo`  | The implicit Main page (process) or Initialize page (object) | No — this page has no UUID |
>
> Do not confuse `SubSheetInfo` (skip) with `SubSheet` (a callable stage that
> calls another page). They share a naming prefix but are completely different.

### 5b. NORMALISE — Collapsed into canonical AST type on parse

| XML `type` string | → Canonical AST type | Rule |
|-------------------|---------------------|------|
| `MultipleCalculation` | `CALCULATION` | Fan-out: emit N `CALCULATION` nodes, one per `<steps><calculation>` |
| `SubSheet`        | `ACTION`            | Set `is_subsheet_call=True`; target page UUID from `<processid>` |
| `WaitStart`       | `WAIT`              | Paired bracket — match with WaitEnd by subsheetid |
| `WaitEnd`         | `WAIT`              | Paired bracket — match with WaitStart |
| `LoopStart`       | `LOOP`              | Paired bracket — match with LoopEnd |
| `LoopEnd`         | `LOOP`              | Paired bracket — match with LoopStart |
| `Alert`           | `ACTION`            | Fire-and-forget notification (email/message). No branching, no flow-relevant outputs. Set `is_alert=True`. |
| `Skill`           | `ACTION`            | Decipher/SDD AI skill call. Structurally identical to Action (inputs/outputs). Target environment won't have Decipher — emit STUB at MANUAL confidence. Set `is_skill=True`. |

> **`Choice` is NOT in this table.** It cannot safely normalise to `DECISION`
> because it has N named branches — collapsing to binary loses branch labels
> and all edges beyond the first two. `Choice` maps to its own canonical AST
> type: `CHOICE`. See §5c and §6.16.

### 5c. PARSE — Direct 1:1 to canonical AST type

| XML `type` string | Canonical AST | Category |
|-------------------|--------------|----------|
| `Start`           | `START`      | Control |
| `End`             | `END`        | Control |
| `Action`          | `ACTION`     | Flow |
| `Decision`        | `DECISION`   | Flow — binary gate, exactly 2 edges: `ontrue` / `onfalse` |
| `Choice`          | `CHOICE`     | Flow — N-way ordered branch; first-true-wins semantics |
| `Calculation`     | `CALCULATION`| Flow |
| `Code`            | `CODE`       | Flow |
| `Navigate`        | `NAVIGATE`   | UI Automation (object-only) |
| `Read`            | `READ`       | UI Automation (object-only) |
| `Write`           | `WRITE`      | UI Automation (object-only) |
| `Wait`            | `WAIT`       | UI Automation (object-only) |
| `Exception`       | `EXCEPTION`  | Control |
| `Recover`         | `RECOVER`    | Control |
| `Resume`          | `RESUME`     | Control |
| `Block`           | `BLOCK`      | Scope |
| `Collection`      | `COLLECTION` | Data |
| `Data`            | `DATA`       | Data |
| `Process`         | `ACTION`     | Flow — calls a sub-process; set `is_process_call=True` |

> **`BLOCK` ≠ `EXCEPTION`:** `BLOCK` is a scope boundary (try/catch wrapper).
> `EXCEPTION` is an explicit throw stage. They are structurally and
> semantically different.

---

## 6. Per-Type Child Elements

### 6.1 `Action` (and `SubSheet` normalised to ACTION)

```
<stage stageid="..." name="..." type="Action">
  <subsheetid>  {page UUID}  </subsheetid>
  <resource object="VBO Name" action="Method Name" />   ← VBO call target
  <inputs>
    <input type="text|number|flag|..." name="ParamName"
           expr="[DataItem]" friendlyname="..." narrative="..." />
  </inputs>
  <outputs>
    <output type="text|..." name="ParamName" stage="TargetDataItem"
            friendlyname="..." narrative="..." />
  </outputs>
  <onsuccess>  {next stageid}  </onsuccess>
  <narrative>  {description}  </narrative>
</stage>
```

For `SubSheet` (page call): replace `<resource>` with `<processid>{target page UUID}</processid>`.

**Capture:**
- `resource.object` → VBO name (used for VBO catalogue lookup)
- `resource.action` → method name
- `inputs[].{type, name, expr}` → parameter mapping
- `outputs[].{type, name, stage}` → output data item targets

---

### 6.2 `Calculation`

```
<stage type="Calculation">
  <calculation expression="[A] & [B]" stage="TargetDataItem" />
  <onsuccess> ... </onsuccess>
</stage>
```

**Capture:** `expression` (VBScript/BP expression), `stage` (target data item name)

---

### 6.3 `MultipleCalculation` → normalised to N × CALCULATION

```
<stage type="MultipleCalculation">
  <steps>
    <calculation expression="..." stage="Target1" />
    <calculation expression="..." stage="Target2" />
  </steps>
  <onsuccess> ... </onsuccess>
</stage>
```

**Capture:** Iterate `<steps><calculation>` → emit one CALCULATION node per row.

---

### 6.4 `Decision`

```
<stage type="Decision">
  <decision expression="[X] > 0" />
  <ontrue>  {stageid}  </ontrue>
  <onfalse> {stageid}  </onfalse>
</stage>
```

**Capture:** `expression`, `ontrue` (stageid), `onfalse` (stageid)

---

### 6.4a `Choice` → canonical `CHOICE` (18th AST type)

> ⚠️ **XML structure NOT empirically verified** — neither sample file contained
> a Choice stage. The structure below is inferred from Blue Prism 6.9/7.0
> official documentation describing its behaviour. **Before the parser handles
> this type, a real sample must be obtained and the XML verified.**
> Tag names marked `[INFERRED]` are not confirmed.

**Semantics:** Ordered N-way branch. Each criterion is a boolean expression.
Evaluation stops at the first truthy branch. An implicit else/default branch
catches all-false cases. This is fundamentally different from `Decision` — it
has N named outbound edges, not 2 anonymous ones.

**Why it cannot normalise to `DECISION`:** `DECISION` has exactly 2 edges
(`ontrue`/`onfalse`) with no labels. `Choice` has N edges each with a
`friendlyname`. Collapsing loses the branch names and every edge beyond the
first two — silent data loss in the process map.

**PAD migration target:** Chained `if / else if / else` block in `.robin`.

```xml
<!-- [INFERRED] structure — verify against real sample before coding -->
<stage type="Choice">
  <subsheetid> ... </subsheetid>
  <choices>
    <choice>
      <name>Branch Label 1</name>              <!-- friendlyname -->
      <condition expression="[X] = 1" />       <!-- boolean expression -->
      <onsuccess>{stageid}</onsuccess>          <!-- edge target -->
    </choice>
    <choice>
      <name>Branch Label 2</name>
      <condition expression="[X] = 2" />
      <onsuccess>{stageid}</onsuccess>
    </choice>
    <!-- ... N more ... -->
    <!-- implicit else branch — structure unknown, may be a bare <onsuccess> on the stage -->
  </choices>
</stage>
```

**Capture (once verified):**
- `branches: list[{name: str, expression: str, next_stage_id: str}]`
- `default_next_stage_id: str | None` — the else/fall-through target

---

### 6.5 `Data` (data item)

```
<stage type="Data">
  <subsheetid> ... </subsheetid>
  <datatype>  text|number|flag|binary|password|date|datetime|time|timespan  </datatype>
  <initialvalue>  {literal value}  </initialvalue>
  <initialvalueenc>  {encrypted value}  </initialvalueenc>  <!-- for password -->
  <exposure>  Session|Environment  </exposure>              <!-- optional -->
  <private />                                               <!-- optional -->
  <narrative> ... </narrative>
</stage>
```

**`datatype` enum:** `text`, `number`, `flag`, `binary`, `password`, `date`, `datetime`, `time`, `timespan`

**Capture:** `datatype`, `initialvalue` (plain text), `exposure` (if present), `private` (bool, presence = true)

---

### 6.6 `Collection`

```
<stage type="Collection">
  <subsheetid> ... </subsheetid>
  <datatype> collection </datatype>
  <collectioninfo>
    <field name="ColumnName" type="text|number|flag|..." value="" />
    ...
  </collectioninfo>
  <initialvalue>
    <row> ... </row>   <!-- optional pre-populated rows -->
  </initialvalue>
</stage>
```

**Capture:** `collectioninfo.field[].{name, type}` → column schema

---

### 6.7 `Code`

```
<stage type="Code">
  <subsheetid> ... </subsheetid>
  <code>  {VBScript source code text}  </code>
  <inputs>
    <input type="text" name="ParamName" expr="[DataItem]" />
  </inputs>
  <outputs>
    <output type="flag" name="ParamName" stage="TargetDataItem" />
  </outputs>
  <onsuccess> ... </onsuccess>
</stage>
```

**Capture:** `code` text (full VBScript), inputs, outputs (same schema as Action)

---

### 6.8 `Exception`

```
<stage type="Exception">
  <subsheetid> ... </subsheetid>
  <exception
    type="System Exception|Business Exception|System Unavailable Exception|..."
    detail="{expression or literal}"
    usecurrent="yes"       <!-- rethrow current exception -->
    localized="yes"        <!-- optional -->
  />
</stage>
```

Two modes: `usecurrent="yes"` (rethrow, `type`/`detail` empty) vs explicit (`type` + `detail` set).

**`exception.type` known values:**
`Business Exception`, `System Exception`, `System Unavailable Exception`,
`Action Failed`, `Bad Handle`, `File Not Found`,
`Invalid Direction Parameter`, `Invalid Input Parameter`,
`UtilityException`, `Workbook Not Found`, `Worksheet Not Found`

**Capture:** `exception.type`, `exception.detail`, `exception.usecurrent` (bool)

---

### 6.9 `Recover`

```
<stage type="Recover">
  <onsuccess> {stageid} </onsuccess>
</stage>
```

**Capture:** `onsuccess` only. Marks the start of an error-handling path.

---

### 6.10 `Resume`

```
<stage type="Resume">
  <onsuccess> {stageid} </onsuccess>
</stage>
```

**Capture:** `onsuccess` only. Exits error-handling path back to normal flow.

---

### 6.11 `Block`

```
<stage type="Block">
  <subsheetid> ... </subsheetid>
  <!-- No expression children. Scope boundary only. -->
</stage>
```

**Capture:** `stageid`, `name`, `subsheetid`. No expression data.

---

### 6.12 `Start`

```
<stage type="Start">
  <subsheetid> ... </subsheetid>
  <inputs>
    <input type="text" name="ParamName" expr="" friendlyname="..." />
  </inputs>
  <onsuccess> {stageid} </onsuccess>
  <preconditions> <condition narrative="..." /> </preconditions>
  <postconditions> <condition narrative="..." /> </postconditions>
</stage>
```

**Capture:** `inputs` (page input parameters), `onsuccess`

---

### 6.13 `End`

```
<stage type="End">
  <subsheetid> ... </subsheetid>
  <outputs>
    <output type="text" name="ParamName" stage="SourceDataItem" />
  </outputs>
</stage>
```

**Capture:** `outputs` (page output parameters). No `onsuccess` — terminal.

---

### 6.14 `WaitStart` / `WaitEnd` → normalised to `WAIT` (bracket pair, object-only)

`WaitStart` and `WaitEnd` are a matched bracket pair used in VBO pages to pause
execution and wait for a UI condition. They always appear together on the same
page and share a `<groupid>` that pairs them.

```xml
<stage stageid="..." name="Wait1" type="WaitStart">
  <subsheetid> ... </subsheetid>
  <groupid>  {same UUID as paired WaitEnd}  </groupid>
  <choices />                               <!-- always present, may be empty -->
  <timeout>  10  </timeout>                 <!-- timeout in seconds (integer) -->
</stage>

<stage stageid="..." name="Time Out1" type="WaitEnd">
  <subsheetid> ... </subsheetid>
  <groupid>  {same UUID as paired WaitStart}  </groupid>
  <onsuccess>  {next stageid}  </onsuccess>
</stage>
```

**`WaitStart`-only children:**
- `<timeout>` — integer seconds before timeout; only on `WaitStart`
- `<choices>` — UI condition definitions (empty element if no conditions set)

**Shared children:**
- `<groupid>` — UUID that pairs `WaitStart` with its matching `WaitEnd`;
  analogous to how `LoopStart`/`LoopEnd` are paired

**Capture:** `timeout_seconds` (int|None from `<timeout>`), `group_id` (str from `<groupid>`).
`WaitEnd` has `<onsuccess>` only; `WaitStart` has no `<onsuccess>` (flow continues from `WaitEnd`).

---

### 6.14b `Navigate` / `Read` / `Write` / `Wait` (UI Automation stages — object-only)

These share similar structure with `<steps>` containing UI element actions.
Exact child schema is application-model-dependent and **not required for
process migration** — capture as opaque blobs with `runtime=DESKTOP` flag.

```
<stage type="Navigate|Read|Write|Wait">
  <subsheetid> ... </subsheetid>
  <steps> ... </steps>            <!-- UI element actions -->
  <onsuccess> ... </onsuccess>
</stage>
```

**Capture:** Mark as `runtime=DESKTOP`, preserve `<steps>` as raw XML string
for STUB generation. Set confidence band = MANUAL.

> **Note:** `Wait` (without Start/End suffix) is a UI Automation stage that
> waits for an element condition. It is structurally different from the
> `WaitStart`/`WaitEnd` bracket pair. Both normalise to the `WAIT` canonical
> type, but with different child schemas.

---

### 6.15 `Process` (sub-process call)

```
<stage type="Process">
  <processid> {process UUID} </processid>
  <inputs> ... </inputs>
  <outputs> ... </outputs>
  <onsuccess> ... </onsuccess>
</stage>
```

Same structure as `SubSheet` but calls a full **process** rather than a page.
Normalise to `ACTION` with `is_process_call=True`.

---

### 6.16 `Alert` → normalised to `ACTION` (is_alert=True)

Alert is a notification stage — it sends an email or message and continues.
No branching. No outputs that affect process flow. Structurally identical to
an Action stage in the XML (inputs only, single `<onsuccess>` edge).

**Why `ACTION` is safe here:** The migration target has no equivalent notification
primitive in PAD — the stage becomes a STUB regardless. Keeping the `is_alert=True`
flag on the AST node gives the generator enough information to emit the right
stub comment and set confidence = MANUAL.

```xml
<stage type="Alert">
  <subsheetid> ... </subsheetid>
  <inputs>
    <input type="text" name="To" expr="[EmailAddress]" />
    <input type="text" name="Subject" expr="..." />
    <input type="text" name="Message" expr="..." />
  </inputs>
  <onsuccess>{stageid}</onsuccess>
</stage>
```

**Capture:** Same as Action. Set `is_alert=True`, `resource=None`.

---

### 6.17 `Skill` → normalised to `ACTION` (is_skill=True)

Skill calls a Blue Prism Decipher / SDD AI service. Structurally identical to
an Action stage — it has a named skill target, inputs, and outputs. The target
environment will not have Decipher, so this is always a STUB at MANUAL confidence.

```xml
<stage type="Skill">
  <subsheetid> ... </subsheetid>
  <resource object="Skill Name" action="Method" />
  <inputs> ... </inputs>
  <outputs> ... </outputs>
  <onsuccess>{stageid}</onsuccess>
</stage>
```

**Capture:** Same as Action. Set `is_skill=True`. Force confidence = MANUAL.

---

## 7. Flow Edge Extraction

The process map is a directed graph. Edges come from:

| Source element     | Stage type(s)            | Edge semantics |
|-------------------|--------------------------|----------------|
| `<onsuccess>`     | Most types               | Default next stage |
| `<ontrue>`        | `Decision`               | True branch (binary only) |
| `<onfalse>`       | `Decision`               | False branch (binary only) |
| `<choices>` branches | `Choice`             | N named edges; each branch has its own `<onsuccess>` (see §6.16) |
| `<processid>`     | `SubSheet`, `Process`    | Call target (page/process UUID) |
| Bracket pairing   | `WaitStart`↔`WaitEnd`, `LoopStart`↔`LoopEnd` | Scope edges |

All edge values are **stage UUIDs** (`stageid`), except `<processid>` which is
a **subsheet/process UUID**.

### Page membership

Apply the page identity rule from §4 to assign every stage to a page. Use
`<subsheetid>` presence/absence + artefact root tag. `ProcessInfo` is the
reliable signal that the implicit Main/Initialize page exists.

### Recover/Resume — error path edge semantics (ground truth)

`Recover` and `Resume` are **not** disconnected orphans. They are part of the
flow graph on an error path, connected through an implicit trigger rather than
an explicit XML edge.

The correct model:

```
[Block scope]
    │  happy path (onsuccess edges, explicit in XML)
    │
    │  ← on any unhandled exception thrown inside the Block scope →
    │
[Recover]  ← NO explicit inbound edge in XML; trigger is implicit
    │  onsuccess (explicit in XML)
    ▼
[Retry? Decision]
    │ true                    │ false
    ▼                         ▼
[Count Calculation]      [Exception stage]
    │ onsuccess               (terminates)
    ▼
[Resume]  ← re-enters the happy path
    │  onsuccess (explicit in XML) — points back into the Block
    ▼
[next happy-path stage]
```

**Parser rules for Recover/Resume:**
1. Assign them to the same page as the `Block` they guard (use `<subsheetid>`
   if present; if absent, infer from adjacent stages on the same page).
2. Do NOT treat missing inbound edges as a parsing error — the inbound edge
   to `Recover` is always implicit.
3. Emit an implicit edge `Block → Recover` (labelled `on_exception`) when
   building the process map. Without this, the map shows only the happy path
   and hides every retry loop.
4. `Resume`'s `<onsuccess>` is a normal explicit edge — capture it as usual.

**Important:** Retry loops are *not* independent of the actual flow. They
are the error path of the `Block` they belong to. A process map that omits
them is incomplete.

### Process map construction algorithm
1. Assign all stages to pages using the page identity rule (§4).
2. For each stage, collect outbound edges from `onsuccess` / `ontrue` / `onfalse`.
3. `SubSheet`/`Process` stages add a cross-page call edge via `processid`.
4. Bracket pairs (`WaitStart`/`WaitEnd`, `LoopStart`/`LoopEnd`) are matched
   by shared `subsheetid` — there is exactly one pair per scope on a page.
5. For each `Block` stage, infer an implicit `on_exception` edge to the
   `Recover` stage on the same page. This edge is not in the XML — it must
   be constructed by the parser.

---

## 8. `input` / `output` Parameter Schema

Used in `Start`, `End`, `Action`, `Code`, `SubSheet`, `Process` stages.

### `<input>` attributes

| Attribute      | Required | Notes |
|---------------|----------|-------|
| `name`        | Yes      | Parameter name as defined in VBO/page |
| `type`        | Yes      | BP data type: `text`, `number`, `flag`, `binary`, `password`, `date`, `datetime`, `time`, `timespan`, `collection` |
| `expr`        | Yes      | BP expression e.g. `[DataItem]`, `"literal"`, `""` (empty = not mapped) |
| `stage`       | No       | Source data item name (alternative to `expr` in some contexts) |
| `friendlyname`| No       | UI display label |
| `narrative`   | No       | Parameter description |

### `<output>` attributes

| Attribute      | Required | Notes |
|---------------|----------|-------|
| `name`        | Yes      | Parameter name |
| `type`        | Yes      | BP data type (same enum as input) |
| `stage`       | Yes      | **Target** data item name to write result into |
| `friendlyname`| No       | UI display label |
| `narrative`   | No       | Parameter description |

---

## 9. BP Data Type Enum

```
text | number | flag | binary | password | date | datetime | time | timespan | collection
```

`flag` = boolean. `binary` = byte array (file content, screenshots).

---

## 10. Parser Correction Notes for Flowsmith

These are confirmed bugs / gaps to fix before using this schema:

1. **Namespace stripping is mandatory** — all `find()` / `findall()` calls
   must use `f"{BP}tagname"` pattern. Bare tag names return nothing.

2. **`published` must be case-normalised** — do not compare directly to
   `"true"` or `"True"`. Always `.lower() == "true"`.

3. **`SubSheetInfo` ≠ `SubSheet`** — `SubSheetInfo` is a skip/meta type;
   `SubSheet` is a callable that must normalise to `ACTION`. Current
   CLAUDE.md correctly lists both, but parser code must handle them
   as structurally different: `SubSheetInfo` has `<subsheetid>` (page UUID),
   `SubSheet` has `<processid>` (target page UUID).

4. **Three stage types missing from CLAUDE.md** — `Alert` and `Skill`
   normalise to `ACTION` (set `is_alert=True` / `is_skill=True`). `Choice`
   is **not** a normalisation of `DECISION` — it requires its own canonical
   AST type `CHOICE` (18th type). CLAUDE.md currently says "17 total"; that
   count is wrong and must be updated. All three will cause `UnknownStageType`
   errors on real enterprise processes if unhandled.

   `Choice` XML structure is **not yet empirically verified** (§6.4a). Do not
   implement the Choice parser until a real sample with a Choice stage has been
   obtained and the XML child structure confirmed.

5. **`Recover`/`Resume` missing `<subsheetid>` is not a bug** — it is
   confirmed behaviour in at least some BP versions. The parser must not
   raise an error on missing `<subsheetid>` for these types. Fallback rule:
   assign them to the same page as the nearest `Block` stage sharing the same
   XML document position (i.e. the Block they guard). Never treat their missing
   inbound edge as a parser gap — the `Block → Recover` edge is always implicit
   and must be constructed, not read from XML (see §7 process map algorithm).

6. **`WaitStart`/`WaitEnd` — note the exact XML strings** — the official
   docs UI shows "Wait start" / "Wait end" but the XML `type` attribute is
   `WaitStart` and `WaitEnd` (no space, PascalCase). Same for `LoopStart`
   / `LoopEnd`. Both normalise to `WAIT` / `LOOP` canonical types. Capture
   `<timeout>` (WaitStart only) and `<groupid>` (both) — see §6.14.

7. **`<o>` tag exists** — empirically observed in output elements (probable
   abbreviation artefact in some BP versions). Parser must handle both
   `<output>` and `<o>` as equivalent.

8. **`ProcessInfo` is the implicit page marker** — every process and object
   has exactly one `ProcessInfo` stage, and it always lives on the implicit
   Main/Initialize page (no `<subsheetid>`). Use its presence as the signal
   to create the implicit page node in the process map. Stages without
   `<subsheetid>` that are NOT `ProcessInfo` (e.g. a bare `Start`/`End` pair,
   `Note` stages) also belong to this implicit page.

9. **`parse_element()` is the canonical entry point** — the parser exposes
   both `parse(filepath)` (file-based) and `parse_element(root_el, release_id)`
   (element-based). `parse(filepath)` is a thin wrapper around `parse_element`.
   Use `parse_element` directly when extracting artefacts from a release file
   to avoid writing temp files. The `release_id` parameter tags the result with
   the UUID from the release `<contents>` wrapper.
