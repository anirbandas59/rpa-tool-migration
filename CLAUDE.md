# CLAUDE.md — Flowsmith project intelligence file

## READ THIS COMPLETELY BEFORE WRITING ANY CODE

## What this project does

Flowsmith is a Python CLI tool that migrates Blue Prism automation processes (.bprelease files)
to Power Automate Cloud Flows + Desktop (PAD) flows.

Pipeline: .bprelease → XML parser → Canonical AST → Transformation engine → Code generator → .zip solution

## Project layout

src/flowsmith/
  cli/         — typer CLI commands only. No logic here.
  parser/      — lxml XML parsing of .bprelease files
  ast/         — Pydantic models for the canonical intermediate representation
  mapper/      — YAML rule loading + data type mapping
  engine/      — transformation + confidence scoring
  generator/   — Jinja2-based .robin and Cloud Flow JSON generation
  reporter/    — Rich terminal + HTML report generation
  exceptions.py — ALL custom exceptions live here

tests/          — mirrors src/flowsmith structure exactly
  mapping/        — stage_rules.yaml, vbo_catalogue.yaml (YAML only, no code)
  templates/      — Jinja2 templates for .robin, Cloud Flow JSON, HTML report
  docs/           — markdown documentation
  output/         — generated files (gitignored — never commit)

## Non-negotiable rules

### Structure

- ONE responsibility per file. Parser parses. Engine transforms. Generator generates.
- CLI files (src/flowsmith/cli/) contain ZERO business logic — only typer command wiring.
- Prompts and templates live in templates/ — never inline them in Python code.
- YAML mapping config lives in mapping/ — never hardcode mappings in Python.

### Exceptions

- NEVER return None to signal failure. ALWAYS raise a typed exception from exceptions.py.
- Every function that can fail must raise the appropriate typed exception with a clear message.

### Testing

- Every module must have a corresponding test file in tests/<module>/
- Test files are named test_<module_name>.py
- Coverage threshold is 85% — check with: uv run pytest --cov
- DO NOT move to the next task until the test for the current task passes.

### Code quality

- Type hints on ALL function signatures — parameters and return types.
- Docstrings on every public function: purpose, params (Args:), returns (Returns:), raises (Raises:).
- Run ruff before every commit: uv run ruff check src/ tests/

### Git discipline

- Commit after each individual task — not after each phase.
- Commit message format: type(scope): description
  Types: feat, fix, test, refactor, docs, chore
  Example: feat(parser): add VBO method parser with param extraction
- Stage specific files only — never: git add .
- Do not mention author name

### Dependencies

- ALL new packages go into pyproject.toml under [project.dependencies] or [project.dependency-groups].dev
- Install with: uv sync --extra dev
- NEVER pip install anything directly.

### Output files

- All generated .robin, .json, .zip, .html files go to output/ only.
- output/ is gitignored — never commit generated artifacts.

## Running the tool

uv run flowsmith --help
uv run flowsmith convert --input path/to/process.bprelease --output output/

## Running tests

uv run pytest tests/ -v                          # full suite
uv run pytest tests/parser/ -v                   # single module
uv run pytest --cov --cov-report=term-missing    # with coverage

## Import verification pattern

uv run python -c "from flowsmith.<module> import <Class>; print('OK')"

## Confidence band reference

| Score    | Band       | Generated output behaviour             |
|----------|------------|----------------------------------------|
| >= 0.90  | AUTO       | Full code, no TODO markers             |
| 0.70-0.89| SPOT-CHECK | Full code + inline comment to verify   |
| 0.50-0.69| PARTIAL    | Scaffold + TODO: complete this block   |
| < 0.50   | MANUAL     | Stub only + ReviewFlag(severity=error) |

## XML namespace contract

Three namespaces appear in `.bprelease` files. Every parser must register or strip
them before any XPath or `find()` call — failure returns empty results silently.

| Prefix | URI | Used on |
|--------|-----|---------|
| (none) | `http://www.blueprism.co.uk/product/process` | All `<process>`, `<object>`, and every stage element |
| `bpr:` | `http://www.blueprism.co.uk/product/release` | Release root and metadata (`<bpr:name>`, `<bpr:contents>`, etc.) |
| `env:` | `http://www.blueprism.co.uk/product/environment-variable` | `<environment-variable>` items |

```python
NS  = "http://www.blueprism.co.uk/product/process"
BP  = f"{{{NS}}}"          # prepend: f"{BP}stage"
BPR = "http://www.blueprism.co.uk/product/release"
ENV = "http://www.blueprism.co.uk/product/environment-variable"
```

## .bprelease container structure

A `.bprelease` is a multi-artefact export container, not a single process file.
The parser entry point is `parse_element(root_el, release_id)` — use it directly
when extracting artefacts from a release to avoid writing temp files.
`parse(filepath)` is a thin wrapper around `parse_element`.

```xml
<bpr:release>
  <bpr:contents count="N">   ← N = total item count across ALL types
    <process>  … </process>          ← parse via parse_element()
    <object>   … </object>           ← parse via parse_element()
    <environment-variable … />       ← parse directly
    <process-group … />              ← cross-reference only, not migrated
    <object-group  … />              ← cross-reference only, not migrated
  </bpr:contents>
</bpr:release>
```

Validate: `process_count + object_count + env_var_count + group_count == declared_count`.
Any gap means an unrecognised content type was silently skipped — raise ConfigError.

Root discriminator: `<process>` root = Process artefact; `<object>` root = VBO.

## Stage type enum reference

Canonical AST types (18 total):
START, END, ACTION, DECISION, CHOICE, CALCULATION, CODE, WAIT,
NAVIGATE, READ, WRITE, LOOP, EXCEPTION, RECOVER, RESUME,
BLOCK, COLLECTION, DATA

⚠️ CHOICE is the 18th type. It is NOT a normalisation of DECISION. It maps N
named branches to chained if/else-if/else in .robin. Do not collapse it.
⚠️ CHOICE XML structure is NOT yet empirically verified against a real sample —
do not implement the Choice parser until a real sample is obtained (see bp_xml_schema §6.4a).

Skip types (no AST node, no generated output):
ANCHOR, NOTE, SUBSHEETINFO, PROCESSINFO

Note: SubSheetInfo ≠ SubSheet. SubSheetInfo is a skip/page-header marker.
SubSheet is a callable stage that normalises to ACTION (is_subsheet_call=True).

Normalised on parse (collapsed into existing types):
MULTIPLECALCULATION → CALCULATION  (fan-out as N nodes)
SUBSHEET            → ACTION       (is_subsheet_call=True)
PROCESS             → ACTION       (is_process_call=True)
ALERT               → ACTION       (is_alert=True)
SKILL               → ACTION       (is_skill=True, confidence forced to MANUAL)
WAITSTART/WAITEND   → WAIT         (paired bracket, matched by <groupid>)
LOOPSTART/LOOPEND   → LOOP         (paired bracket, matched by shared subsheetid)

BLOCK ≠ EXCEPTION:
  BLOCK     = scope boundary (try/catch wrapper)
  EXCEPTION = throw stage

Exception type strings (preserve in AST on every EXCEPTION stage):
  Business Exception, System Exception, Action Failed, Bad Handle,
  File Not Found, Invalid Direction Parameter, Invalid Input Parameter,
  System Unavailable Exception, UtilityException,
  Workbook Not Found, Worksheet Not Found

## Parser critical rules

1. `published` must be case-normalised — always `.lower() == "true"`. Never compare
   directly to `"true"` or `"True"` — casing varies between process and object files.

2. Page identity is determined by `<subsheetid>` presence, not stage order:
   - Stage has `<subsheetid>` → belongs to that named subsheet
   - Stage has no `<subsheetid>` + root is `<process>` → Main page (implicit)
   - Stage has no `<subsheetid>` + root is `<object>` → Initialize page (implicit)
   - ProcessInfo is the reliable marker that the implicit page exists.

3. `Recover`/`Resume` missing `<subsheetid>` is NOT a bug — confirmed BP behaviour.
   Assign them to the same page as the Block they guard. Do NOT raise on missing
   subsheetid for these types.

4. Block → Recover edge is always implicit — it is never in the XML. The parser
   must construct this edge (`on_exception` label) for every Block/Recover pair
   on the same page. Omitting it produces an incomplete process map.

5. `Resume`'s `<onsuccess>` is a normal explicit edge — capture it as usual.

6. `<o>` tag is equivalent to `<output>` — empirically observed in some BP versions.
   Parser must handle both.

7. WaitStart/WaitEnd XML type strings are `WaitStart`/`WaitEnd` (PascalCase, no space).
   Same for `LoopStart`/`LoopEnd`. Match by `<groupid>` for Wait pairs.

## Key Pydantic models (Phase 3 reference)

BPProcess → BPPage[] → BPStage[]
Each BPStage has: id, type (StageType), name, data_items, exception_handler_id, pa_annotation (optional)
PAAnnotation: target_type, target_module, runtime (CLOUD|DESKTOP), params_map, confidence, flags[]
ReviewFlag: stage_id, reason, severity (info|warn|error), suggested_fix
