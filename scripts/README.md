# scripts/ — Blue Prism diagnostic toolkit

Standalone helper scripts for parsing `.bprelease` / `.bpprocess` / `.bpobject`
files and generating human-readable and machine-readable reports from them.

This directory is **not part of the `flowsmith` package** under `src/` — it
has no `pyproject.toml`-declared CLI entry point, isn't installed, and isn't
subject to `src/flowsmith`'s coverage/architecture rules in the root
`CLAUDE.md`. It's a set of directly-runnable Python files sharing the same
`uv`-managed virtual environment as the rest of the repo.

Every generated report is built to serve **two audiences from one run**: a
human reviewing the HTML in a browser, and a downstream tool or LLM ingesting
the accompanying `data/` exports. See [LLM data ingestion](#llm-data-ingestion)
below.

## Setup

Python dependencies (`lxml`, `rich`, `graphviz`) are already declared in the
repo's root `pyproject.toml` and installed with the rest of the project:

```bash
uv sync --extra dev
```

Graph rendering (`bp_graph_v3.py`, and the embedded page graphs in
`bp_html_report_v3.py`'s output) also needs the **Graphviz system binary** —
the `graphviz` *Python package* is just a wrapper around the `dot`
executable, which isn't installed by `uv sync`:

```bash
# Windows
choco install graphviz
# Linux
apt install graphviz
# macOS
brew install graphviz
```

Without it, `bp_html_report_v3.py` degrades gracefully — pages render with a
"graph module unavailable" badge instead of a PNG, rather than failing the
whole run.

All scripts are run directly with `uv run python`, from the repo root or
from inside `scripts/`:

```bash
uv run python scripts/bp_html_report_v3.py samples/blueprism/PID_0171.bprelease
```

## The primary tool: `bp_html_report_v3.py`

Takes any `.bprelease` (a release containing multiple processes/objects),
`.bpprocess`, or `.bpobject` file and produces an HTML diagnostic report —
file type is auto-detected from the XML root element, not the extension.

```bash
uv run python scripts/bp_html_report_v3.py PID_0171.bprelease --out-dir ./reports/
```

### Output — split mode (default)

Split mode is the default for every input type. It writes a folder, not a
single file:

```
{basename}_html_report_{YYYYMMDD}/
├── index.html            ← navigation shell: stat cards, sortable artefact
│                            table, env vars, VBO cross-reference, groups
├── styles.css             ← all structural CSS (no inline styles except
│                             genuinely per-item colours, e.g. badges)
├── images/
│   └── {artefact_slug}_{page_slug}.png   ← one Graphviz render per page
├── data/                  ← see LLM data ingestion, below
│   ├── release.json
│   ├── {artefact_slug}.json
│   ├── {artefact_slug}.md
│   ├── stages.jsonl
│   └── manifest.json
└── pages/
    └── {artefact_slug}.html   ← one full page per process/object
```

### CLI flags

| Flag | Effect |
|---|---|
| `--out-dir PATH` | Destination for the output folder/file. Defaults to the current directory. |
| `--single-file` | Produce the old monolithic single `.html` file instead (full backwards compatibility with the pre-split format — everything inlined and base64-embedded). Use for a quick one-off look at a small `.bpprocess`/`.bpobject`; not recommended for a `.bprelease` with many VBOs, since it reintroduces the original 40–70 MB file-size problem split mode exists to solve. |
| `--include-all` | Disable VBO reachability pruning — render every action page of every VBO, including ones no process in the release ever calls. Default is pruning **on**: only called actions (plus the VBO's own Initialize/Clean Up pages) are rendered; everything else is counted in a collapsed "N action pages omitted" footer per artefact. |
| `--no-graph` | Skip Graphviz rendering entirely (also the automatic fallback if the `dot` binary isn't installed). Much faster; pages show a badge instead of a diagram. |
| `--svg` | **Accepted but currently a no-op** — see [Known gaps](#known-gaps-and-deprecated-files). |

### Reading the output

- **Search** (`index.html` and every `pages/*.html`): tries `fetch(data/stages.jsonl)` first for a cross-page search reaching every artefact and stage from any page — but `fetch()` is blocked on `file://` origins in Chrome/Safari (how these reports are typically opened, by double-click), so it falls back automatically to a same-page filter (the artefact table on `index.html`; auto-expanding matching stage cards elsewhere). Both paths work; the cross-page one just needs the report served over HTTP (or opened in Firefox) to reach every stage from a single search box.
- **Sortable artefact table** (`index.html`): click a column header (Name / Type / Pages / Reachability) to sort, click again to reverse. Sorting by Reachability surfaces entirely-unused VBOs immediately.
- **Deep links**: every stage card has a permanent `#stage-{id}` anchor — copy the URL from the address bar (or a search result) to link directly to one stage; the target page and stage auto-expand on load.
- **Copy JSON / Copy MD** (inside each stage's expanded detail): copies that one stage's data to the clipboard for pasting into an LLM conversation, without needing to open `data/` at all.
- **Print / Save as PDF**: the browser's own print function renders a clean single-artefact page — screen-only UI (search, buttons, sort arrows) is hidden and every collapsed section force-expands for print, no separate export step needed.

## LLM data ingestion

Every split-mode run writes a `data/` folder alongside the HTML, purpose-built
for a downstream tool, script, or LLM to consume — this is not a byproduct of
the HTML report, it's an equally-first-class output.

| File | Contents | Best for |
|---|---|---|
| `data/release.json` | The full parsed `release_result` dict — every artefact, env var, group, and parse error, **unpruned**. | Programmatic analysis; the single source of truth if you need everything. |
| `data/{artefact_slug}.json` | Parsed pages + stages + edges for one process/object. | Per-artefact chunking — load only the artefact you need. |
| `data/{artefact_slug}.md` | A pruned Markdown rendering of one artefact (same reachability pruning as the HTML — unused VBO actions omitted). | Pasting into an LLM context window; readable diffs; `grep`-able. |
| `data/stages.jsonl` | One JSON object per line, one line per stage, flat (no page/artefact nesting) — see schema below. | RAG/embedding pipelines, semantic search over individual stages, quick `jq`/`grep` filtering. |
| `data/manifest.json` | An index of every file above with `type`, `size_bytes`, and a one-line `description` each. | Letting an agent decide which file to read first without guessing. |

### `stages.jsonl` record schema

```json
{
  "id": "d8c547cc-60d0-459b-876f-90bf696a5757",
  "artefact": "Utility - File Management",
  "artefact_type": "object",
  "page": "Delete File",
  "stage_type": "Action",
  "raw_type": "Action",
  "name": "Delete File 1",
  "vbo_object": "Utility - File Management",
  "vbo_action": "Delete File",
  "expression": null,
  "inputs": [{"name": "File Name", "type": "text", "expr": "[File Path]"}],
  "outputs": [{"name": "Success", "type": "flag"}],
  "next_stage": "End",
  "is_reachable": true
}
```

`id` is the stage's real Blue Prism GUID — it doubles as a deep-link target:
`pages/{artefact_slug}.html#stage-{id}` lands directly on that stage (once the
target page has been generated by the same run). `is_reachable` reflects
whether the stage is reachable via the happy-path/branch traversal from that
page's Start stage — orphaned stages (dead code) are still included, just
flagged `false`, rather than silently dropped.

### A minimal ingestion recipe

```python
import json

# Cheapest entry point — what files exist and what they're for
manifest = json.load(open("data/manifest.json"))

# Everything, unpruned — if you need the whole release
release = json.load(open("data/release.json"))

# Stage-level, streamable, one record at a time — no need to load it all
with open("data/stages.jsonl", encoding="utf-8") as f:
    stages = [json.loads(line) for line in f]

reachable_vbo_calls = [
    s for s in stages
    if s["is_reachable"] and s["vbo_object"]
]
```

## Other scripts

| Script | Role | Notes |
|---|---|---|
| `bp_parser_v2.py` | Parses one process/object element into the canonical dict shape (`meta`, `pages`, `stages`, `edges`, `stage_by_id`, `stats`). | Library, not typically run standalone. The active, maintained parser — richer than `bp_parser.py` (adds `timeout_seconds`/`group_id` for WaitStart/WaitEnd bracket matching). |
| `bp_release_parser.py` | Parses a `.bprelease` container — cross-references every process/object/env-var/group inside it via `bp_parser_v2.parse_element()`. | `uv run python scripts/bp_release_parser.py <file.bprelease>` for a standalone summary; otherwise imported as a library. |
| `bp_common.py` | Shared utilities: `_reachable_vbo_actions`, `_reachable_stage_ids`, `_full_traversal`, `_json_default`. | Single source of truth for logic used by more than one of the scripts below — never duplicate one of these into a script instead of importing it. |
| `bp_report_v3.py` | Same parsed data as `bp_html_report_v3.py`, rendered as Markdown instead of HTML. | `uv run python scripts/bp_report_v3.py <file> [output.md]`. No flags; prints to stdout if no output path given. |
| `bp_graph_v3.py` | Renders one process/object's Graphviz diagram (PNG + SVG) directly, without going through the HTML report. | `uv run python scripts/bp_graph_v3.py <file.xml> [output_stem] [--with-data]`. Also imported as a library by `bp_html_report_v3.py` for its per-page graphs. |
| `analyse_bp_samples.py` | One-off: statistical survey of the `.bprelease`/`.xml` samples under `samples/blueprism/` — stage-type frequency, schema quirks, etc. Writes `docs/bp_schema_analysis.md`. | `uv run python scripts/analyse_bp_samples.py`. Not part of the report pipeline. |
| `analyse_pad_samples.py` | One-off: same idea for the Power Automate Desktop samples under `samples/pad/` (manifests, connector definitions, Cloud Flow JSON, control repositories). | `uv run python scripts/analyse_pad_samples.py`. Not part of the report pipeline. |

## Known gaps and deprecated files

Documented here rather than silently glossed over, so this README doesn't
claim more than the code actually does:

- **`--svg` is currently a no-op.** `generate_split()` accepts an
  `include_svg` parameter and the CLI flag is parsed, but nothing in the
  function body actually writes an `.svg` file — `bp_graph_v3.py`'s own
  `render()` already produces one alongside the PNG, so wiring it up in
  `generate_split()` is a small, well-scoped task; it just hasn't been done
  yet.
- **`bp_graph.py` is broken, not just deprecated.** It imports
  `_full_traversal` from `bp_html_report` (no version suffix) — a file that
  no longer exists in `scripts/`; it was moved to `scripts/archived/` when
  the actively-maintained files were renamed to `_v3`. Importing this script
  raises `ImportError`. Use `bp_graph_v3.py` instead.
- **`bp_html_report_v2.py` is an older, unrelated lineage — not a newer
  version of anything.** Despite the `_v2` suffix, it predates the
  `bp_parser_v2.py` pipeline (it imports from `bp_parser.py`) and is a
  different, less-capable ancestor of `bp_html_report_v3.py`, not a version
  in between. Kept for reference only; not maintained.
- **`bp_parser.py`** is the original parser, superseded by `bp_parser_v2.py`.
  Still correct for what it does, just missing the newer fields
  (`timeout_seconds`, `group_id`) and not receiving further updates.
- **`bp_report.py`**'s own usage message and docstring still say it consumes
  `bp_parser.parse()` — its actual import is `bp_parser_v2`, so the parser it
  uses is current even though the text describing it is stale. Use
  `bp_report_v3.py`, not this file, for anything new.
- **`scripts/archived/`** holds the pristine, pre-rename originals of the
  three files that became `_v3` (`bp_html_report.py`, `bp_report_v2.py`,
  `bp_graph_v2.py`) — kept for history, not imported by anything.

## Tests

`scripts/tests/` is a self-contained pytest suite, deliberately isolated from
the root `flowsmith` package's test suite:

```bash
uv run pytest scripts/tests/ -v
```

It has its own `pytest.ini` (no `--cov=flowsmith`, no coverage threshold) so
it never runs as a side effect of `uv run pytest` or `uv run pytest tests/`
from the repo root — `pyproject.toml` scopes those to `testpaths = ["tests"]`,
and pytest's config discovery finds `scripts/tests/pytest.ini` before it ever
reaches the root config when you point it at this directory. Fixtures live in
`scripts/tests/conftest.py` as a factory (`make_release_result(...)`) that
builds a minimal synthetic parsed release in Python — no real `.bprelease`
sample file is needed to run these tests.
