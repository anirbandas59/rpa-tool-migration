"""Blue Prism XML process parser — .bprelease → multi-artefact RawProcess dict.

Parses Blue Prism .bprelease XML files into a multi-artefact structure containing
processes, objects (VBOs), and environment variables. Handles namespace-aware
element discovery, stage type preservation, data item extraction, and parameter
mapping for each artefact independently.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict

from lxml import etree

from flowsmith.ast.builder import RawDataItem, RawPage, RawProcess, RawStage
from flowsmith.exceptions import ConfigError, ParseError

# Blue Prism XML namespaces
NS = "http://www.blueprism.co.uk/product/process"
BPR = "http://www.blueprism.co.uk/product/release"
ENV = "http://www.blueprism.co.uk/product/environment-variable"


class RawEnvironmentVariable(TypedDict):
    """A single environment variable from the release.

    Matches the shape expected by BPEnvironmentVariable model in ast/models.py,
    plus additional fields (id, description) for audit/tracing purposes.
    """

    id: str
    name: str
    data_type: str
    value: str
    description: str


class MultiArtefactRelease(TypedDict):
    """Multi-artefact release parsing result from parse_process().

    Contains processes, objects (VBOs), environment variables, and validation stats.
    This is the new return type for parse_process() — Task 3a.
    """

    processes: list[RawProcess]
    objects: list[RawProcess]
    environment_variables: list[RawEnvironmentVariable]
    source_file: str
    validation: dict[
        str, int
    ]  # declared_count, process_count, object_count, env_var_count, group_count


def _ns(tag: str) -> str:
    """Return a namespace-qualified tag name.

    Args:
        tag: Local tag name (e.g. "stage", "subsheet").

    Returns:
        Fully qualified tag with namespace (e.g. "{http://...}stage").
    """
    return f"{{{NS}}}{tag}"


def _strip_ns(tag: str) -> str:
    """Strip XML namespace prefix from a tag name.

    Args:
        tag: Raw lxml tag string, possibly with namespace prefix.

    Returns:
        Tag name without namespace prefix.
    """
    return tag.split("}")[-1] if "}" in tag else tag


def _parse_data_item(di_elem: Any) -> RawDataItem:
    """Extract a RawDataItem dict from a <dataitem> lxml element.

    Args:
        di_elem: An lxml Element representing a <dataitem> tag.

    Returns:
        RawDataItem dict with name, data_type, initial_value, is_input, is_output.

    Raises:
        ParseError: If required attributes are missing.
    """
    try:
        name = di_elem.get("name", "").strip()
        if not name:
            raise ValueError("dataitem missing required 'name' attribute")

        data_type = di_elem.get("type", "").strip()
        if not data_type:
            raise ValueError("dataitem missing required 'type' attribute")

        usage = di_elem.get("usage", "local").strip().lower()

        # Extract initial value from <value> child element (namespace-aware)
        initial_value: str | None = None
        value_elem = di_elem.find(_ns("value"))
        if value_elem is None:
            value_elem = di_elem.find("value")
        if value_elem is not None and value_elem.text:
            initial_value = value_elem.text.strip()

        # Derive is_input and is_output from usage attribute
        is_input = usage in ("input", "in-out")
        is_output = usage in ("output", "in-out")

        return RawDataItem(
            name=name,
            data_type=data_type,
            initial_value=initial_value,
            is_input=is_input,
            is_output=is_output,
        )
    except (ValueError, AttributeError) as exc:
        raise ParseError(f"Failed to parse dataitem: {exc}") from exc


def _parse_stage(stage_elem: Any) -> RawStage:
    """Extract a RawStage dict from a <stage> lxml element.

    Args:
        stage_elem: An lxml Element representing a <stage> tag.

    Returns:
        RawStage dict with all required fields.

    Raises:
        ParseError: If required attributes are missing.
    """
    try:
        stage_id = stage_elem.get("stageid", "").strip()
        if not stage_id:
            raise ValueError("stage missing required 'stageid' attribute")

        stage_type = stage_elem.get("type", "").strip()
        if not stage_type:
            raise ValueError("stage missing required 'type' attribute")

        name = stage_elem.get("name", "").strip()

        # Parse data items (namespace-aware)
        data_items: list[RawDataItem] = []
        for di_elem in stage_elem.findall(_ns("dataitem")):
            data_items.append(_parse_data_item(di_elem))
        # Also try without namespace for compatibility
        if not data_items:
            for di_elem in stage_elem.findall("dataitem"):
                data_items.append(_parse_data_item(di_elem))

        # Extract <initialvalue> text for Data/Collection stages (namespace-aware).
        # A self-closing <initialvalue /> element has no text — that is a
        # genuinely-absent initial value, not a parse failure, so it stays None.
        initial_value: str | None = None
        initialvalue_elem = stage_elem.find(_ns("initialvalue"))
        if initialvalue_elem is None:
            initialvalue_elem = stage_elem.find("initialvalue")
        if initialvalue_elem is not None and initialvalue_elem.text:
            initial_value = initialvalue_elem.text.strip()

        # Synthesise BPDataItem for DATA and COLLECTION stages
        # These stage types store their type in a <datatype> child element
        # rather than <dataitem> children.
        if stage_type in ("Data", "Collection"):
            dt_elem = stage_elem.find(_ns("datatype"))
            if dt_elem is None:
                dt_elem = stage_elem.find("datatype")
            if dt_elem is not None and dt_elem.text:
                raw_type = dt_elem.text.strip().lower()
            else:
                # Collection stages may have no datatype element —
                # default to "collection" which the type mapper handles
                raw_type = "collection" if stage_type == "Collection" else "text"

            data_items.append(
                RawDataItem(
                    name=name,  # variable name = stage name
                    data_type=raw_type,
                    initial_value=initial_value,
                    is_input=False,
                    is_output=False,
                )
            )

        # Parse exception handler id from <onexception> child (namespace-aware)
        exception_handler_id: str | None = None
        onexc_elem = stage_elem.find(_ns("onexception"))
        if onexc_elem is None:
            onexc_elem = stage_elem.find("onexception")
        if onexc_elem is not None:
            exception_handler_id = onexc_elem.get("stage", None)
            if exception_handler_id:
                exception_handler_id = exception_handler_id.strip()

        # Parse exception type/detail/usecurrent from <exception> child (namespace-aware)
        exception_type: str | None = None
        exception_detail: str | None = None
        exception_usecurrent: bool = False
        exc_elem = stage_elem.find(_ns("exception"))
        if exc_elem is None:
            exc_elem = stage_elem.find("exception")
        if exc_elem is not None:
            exc_type = exc_elem.get("type", None)
            if exc_type:
                exception_type = exc_type.strip()
            exc_detail = exc_elem.get("detail", None)
            if exc_detail:
                exception_detail = exc_detail.strip()
            exception_usecurrent = exc_elem.get("usecurrent", "no").strip().lower() == "yes"

        # Parse <decision> expression (namespace-aware) — DECISION and CHOICE stages
        decision_expression: str | None = None
        dec_el = stage_elem.find(_ns("decision"))
        if dec_el is None:
            dec_el = stage_elem.find("decision")
        if dec_el is not None:
            dec_expr = dec_el.get("expression", None)
            if dec_expr:
                decision_expression = dec_expr

        # Parse <narrative> text (namespace-aware) — stage-level comment
        narrative: str | None = None
        narrative_elem = stage_elem.find(_ns("narrative"))
        if narrative_elem is None:
            narrative_elem = stage_elem.find("narrative")
        if narrative_elem is not None and narrative_elem.text:
            narrative = narrative_elem.text.strip()

        # Parse <timeout> for WaitStart stages (namespace-aware)
        timeout_seconds: int | None = None
        timeout_elem = stage_elem.find(_ns("timeout"))
        if timeout_elem is None:
            timeout_elem = stage_elem.find("timeout")
        if timeout_elem is not None and timeout_elem.text and timeout_elem.text.strip().isdigit():
            timeout_seconds = int(timeout_elem.text.strip())

        # Parse <groupid> for WaitStart/WaitEnd/LoopStart/LoopEnd bracket matching
        # (namespace-aware) — the correct matcher, more reliable than positional order.
        group_id: str | None = None
        groupid_elem = stage_elem.find(_ns("groupid"))
        if groupid_elem is None:
            groupid_elem = stage_elem.find("groupid")
        if groupid_elem is not None and groupid_elem.text:
            group_id = groupid_elem.text.strip()

        # Parse <code> text content for Code stages (namespace-aware, CDATA)
        code_text: str | None = None
        code_elem = stage_elem.find(_ns("code"))
        if code_elem is None:
            code_elem = stage_elem.find("code")
        if code_elem is not None and code_elem.text:
            code_text = code_elem.text

        # Parse params_map and extract inputs into data_items (namespace-aware)
        params_map: dict[str, str] = {}
        input_friendlynames: dict[str, str] = {}
        inputs_elem = stage_elem.find(_ns("inputs"))
        if inputs_elem is None:
            inputs_elem = stage_elem.find("inputs")
        if inputs_elem is not None:
            for input_elem in inputs_elem.findall(_ns("input")):
                input_name = input_elem.get("name", "").strip()
                input_expr = input_elem.get("expr", "").strip()
                input_type = input_elem.get("type", "text").strip()
                if input_name:
                    params_map[input_name] = input_expr
                    friendlyname = input_elem.get("friendlyname", "").strip()
                    if friendlyname:
                        input_friendlynames[input_name] = friendlyname
                    # Also add to data_items for structural/type-based scanning (Task 1a)
                    data_items.append(
                        RawDataItem(
                            name=input_name,
                            data_type=input_type,
                            initial_value=None,
                            is_input=True,
                            is_output=False,
                        )
                    )
            # Also try without namespace
            if not params_map:
                for input_elem in inputs_elem.findall("input"):
                    input_name = input_elem.get("name", "").strip()
                    input_expr = input_elem.get("expr", "").strip()
                    input_type = input_elem.get("type", "text").strip()
                    if input_name:
                        params_map[input_name] = input_expr
                        friendlyname = input_elem.get("friendlyname", "").strip()
                        if friendlyname:
                            input_friendlynames[input_name] = friendlyname
                        # Also add to data_items for structural/type-based scanning
                        data_items.append(
                            RawDataItem(
                                name=input_name,
                                data_type=input_type,
                                initial_value=None,
                                is_input=True,
                                is_output=False,
                            )
                        )

        # Parse outputs for ACTION stages (namespace-aware) — Task 1a
        outputs_elem = stage_elem.find(_ns("outputs"))
        if outputs_elem is None:
            outputs_elem = stage_elem.find("outputs")
        if outputs_elem is not None:
            # Try with namespace first
            ns_outputs = list(outputs_elem.findall(_ns("output")))
            if ns_outputs:
                for output_elem in ns_outputs:
                    output_name = output_elem.get("name", "").strip()
                    output_type = output_elem.get("type", "text").strip()
                    if output_name:
                        # Add to data_items with is_output=True for fusion detection
                        data_items.append(
                            RawDataItem(
                                name=output_name,
                                data_type=output_type,
                                initial_value=None,
                                is_input=False,
                                is_output=True,
                            )
                        )
            else:
                # Try without namespace
                for output_elem in outputs_elem.findall("output"):
                    output_name = output_elem.get("name", "").strip()
                    output_type = output_elem.get("type", "text").strip()
                    if output_name:
                        data_items.append(
                            RawDataItem(
                                name=output_name,
                                data_type=output_type,
                                initial_value=None,
                                is_input=False,
                                is_output=True,
                            )
                        )

        # For Calculation stages: extract calculation expressions (namespace-aware)
        calc_elem = stage_elem.find(_ns("calculation"))
        if calc_elem is None:
            calc_elem = stage_elem.find("calculation")
        if calc_elem is not None:
            calc_expr = calc_elem.get("expression", "").strip()
            calc_stage = calc_elem.get("stage", "").strip()
            if calc_stage and calc_expr:
                params_map[calc_stage] = calc_expr

        # For Action stages: extract VBO object and action from <resource> child (namespace-aware)
        resource_elem = stage_elem.find(_ns("resource"))
        if resource_elem is None:
            resource_elem = stage_elem.find("resource")
        if resource_elem is not None:
            vbo_object = resource_elem.get("object", "").strip()
            vbo_action = resource_elem.get("action", "").strip()
            if vbo_object:
                params_map["_vbo_object"] = vbo_object
            if vbo_action:
                params_map["_vbo_action"] = vbo_action

        # Parse edge targets (onsuccess/ontrue/onfalse) — Task 1a
        onsuccess_target: str | None = None
        ontrue_target: str | None = None
        onfalse_target: str | None = None

        onsuccess_elem = stage_elem.find(_ns("onsuccess"))
        if onsuccess_elem is None:
            onsuccess_elem = stage_elem.find("onsuccess")
        if onsuccess_elem is not None and onsuccess_elem.text:
            onsuccess_target = onsuccess_elem.text.strip()

        ontrue_elem = stage_elem.find(_ns("ontrue"))
        if ontrue_elem is None:
            ontrue_elem = stage_elem.find("ontrue")
        if ontrue_elem is not None and ontrue_elem.text:
            ontrue_target = ontrue_elem.text.strip()

        onfalse_elem = stage_elem.find(_ns("onfalse"))
        if onfalse_elem is None:
            onfalse_elem = stage_elem.find("onfalse")
        if onfalse_elem is not None and onfalse_elem.text:
            onfalse_target = onfalse_elem.text.strip()

        return RawStage(
            stage_id=stage_id,
            stage_type=stage_type,
            name=name,
            data_items=data_items,
            exception_handler_id=exception_handler_id,
            exception_type=exception_type,
            params_map=params_map,
            decision_expression=decision_expression,
            code_text=code_text,
            narrative=narrative,
            initial_value=initial_value,
            timeout_seconds=timeout_seconds,
            group_id=group_id,
            exception_detail=exception_detail,
            exception_usecurrent=exception_usecurrent,
            input_friendlynames=input_friendlynames,
            onsuccess_target=onsuccess_target,
            ontrue_target=ontrue_target,
            onfalse_target=onfalse_target,
        )
    except (ValueError, AttributeError) as exc:
        raise ParseError(f"Failed to parse stage: {exc}") from exc


def _parse_page(subsheet_elem: Any) -> RawPage:
    """Extract a RawPage dict from a <subsheet> lxml element.

    Args:
        subsheet_elem: An lxml Element representing a <subsheet> tag.

    Returns:
        RawPage dict with page_id, name, stages, is_main.

    Raises:
        ParseError: If required attributes are missing.
    """
    try:
        page_id = subsheet_elem.get("subsheetid", "").strip()
        if not page_id:
            raise ValueError("subsheet missing required 'subsheetid' attribute")

        name = subsheet_elem.get("name", "").strip()
        if not name:
            # Fallback to id if name is missing
            name = page_id

        # Extract published flag — determines which pages become PAD Workflows
        published = subsheet_elem.get("published", "false").strip().lower() == "true"

        # In Blue Prism XML, stages are children of <subsheet>
        # They may be nested under other elements (like <view>), so we search recursively
        stages: list[RawStage] = []
        for stage_elem in subsheet_elem.iter():
            if _strip_ns(stage_elem.tag) == "stage":
                stages.append(_parse_stage(stage_elem))

        is_main = False

        return RawPage(
            page_id=page_id,
            name=name,
            stages=stages,
            is_main=is_main,
            published=published,
        )
    except (ValueError, AttributeError) as exc:
        raise ParseError(f"Failed to parse page: {exc}") from exc


def parse_element(artefact_elem: Any, release_id: str, root: Any) -> RawProcess:
    """Parse a single process or object artefact element into a RawProcess.

    This is the core per-artefact parsing function used by parse_process().
    It handles extracting metadata, pages, and stages from a single <process>
    or <object> element, returning a RawProcess dict that matches the existing
    AST builder's expectations.

    Args:
        artefact_elem: An lxml Element representing <process> or <object> root.
        release_id: The id attribute from the release-level <process>/<object> wrapper.
        root: The root element of the full XML tree (used for full-document stage collection).

    Returns:
        RawProcess dict ready to pass to build_ast().

    Raises:
        ParseError: If required metadata or structure is missing.
    """
    try:
        # Find the inner <process> element if this is an outer wrapper
        # (real .bprelease structure has wrapper → process → stages)
        process_elem = artefact_elem
        metadata_elem = artefact_elem

        # If artefact_elem has a child <process>, use it as the actual element
        for child in artefact_elem:
            if _strip_ns(child.tag) == "process":
                process_elem = child
                break

        # Extract process metadata (use release_id and outer element for id, process_elem for other fields)
        process_id = release_id.strip()
        if not process_id:
            process_id = metadata_elem.get("id", "").strip()
        if not process_id:
            raise ValueError("artefact element missing required 'id' attribute")

        process_name = (process_elem.get("name", "") or metadata_elem.get("name", "")).strip()
        if not process_name:
            raise ValueError("artefact element missing required 'name' attribute")

        process_version = (
            process_elem.get("version", "") or metadata_elem.get("version", "")
        ).strip()

        # ── ARTEFACT-SCOPED STAGE COLLECTION (namespace-aware) ─────────────────────

        # Step 1: Collect subsheets from this artefact only
        # Try namespace-aware first, then fall back to non-namespaced for test fixtures
        subsheets_by_id: dict[str, Any] = {}
        subsheets_published: dict[str, bool] = {}
        all_subsheet_elems = list(artefact_elem.iter(_ns("subsheet")))
        if not all_subsheet_elems:
            all_subsheet_elems = list(artefact_elem.iter("subsheet"))

        for subsheet_elem in all_subsheet_elems:
            page_id = subsheet_elem.get("subsheetid", "").strip()
            if not page_id:
                raise ValueError("subsheet missing required 'subsheetid' attribute")

            # Extract name from child element (namespace-aware)
            name_elem = subsheet_elem.find(_ns("name"))
            if name_elem is None:
                name_elem = subsheet_elem.find("name")
            page_name = (name_elem.text or "").strip() if name_elem is not None else ""

            # Fall back to name attribute if child element not found
            if not page_name:
                page_name = subsheet_elem.get("name", "").strip()

            # Fall back to page_id if still empty
            if not page_name:
                page_name = page_id

            subsheets_by_id[page_id] = page_name
            subsheets_published[page_id] = (
                subsheet_elem.get("published", "false").strip().lower() == "true"
            )

        # Step 2: Collect stages — supports two formats:
        # Format A (test): stages nested inside subsheet elements
        # Format B (real): flat stages at root with <subsheetid> children
        paged_stages: dict[str, list[RawStage]] = {}
        main_stages: list[RawStage] = []
        extracted_stage_ids: set[str] = set()

        # Format A: Collect nested stages from each subsheet (test format)
        for subsheet_elem in all_subsheet_elems:
            page_id = subsheet_elem.get("subsheetid", "").strip()
            if not page_id:
                continue

            # Find stages nested directly or indirectly within this subsheet
            for stage_elem in subsheet_elem.iter(_ns("stage")):
                stage = _parse_stage(stage_elem)
                extracted_stage_ids.add(stage["stage_id"])
                if page_id not in paged_stages:
                    paged_stages[page_id] = []
                paged_stages[page_id].append(stage)

            # Also try without namespace for test fixtures
            if page_id not in paged_stages:
                for stage_elem in subsheet_elem.iter("stage"):
                    stage = _parse_stage(stage_elem)
                    extracted_stage_ids.add(stage["stage_id"])
                    if page_id not in paged_stages:
                        paged_stages[page_id] = []
                    paged_stages[page_id].append(stage)

        # Format B: Collect flat stages from artefact with <subsheetid> children (real format)
        # This extracts all stages from this artefact only
        all_stage_elems = list(artefact_elem.iter(_ns("stage")))
        if not all_stage_elems:
            all_stage_elems = list(artefact_elem.iter("stage"))

        for stage_elem in all_stage_elems:
            stage_id = stage_elem.get("stageid", "").strip()

            # Skip if already extracted as nested stage
            if stage_id in extracted_stage_ids:
                continue

            stage = _parse_stage(stage_elem)

            # Determine which page this stage belongs to by checking <subsheetid> child
            subsheetid = (
                stage_elem.findtext(_ns("subsheetid")) or stage_elem.findtext("subsheetid") or ""
            ).strip()

            if subsheetid:
                # Stage belongs to a subsheet page
                if subsheetid not in paged_stages:
                    paged_stages[subsheetid] = []
                paged_stages[subsheetid].append(stage)
            else:
                # Stage has no subsheetid → belongs to main page
                main_stages.append(stage)

        # ── BUILD PAGES ──────────────────────────────────────────────────────────

        pages: list[RawPage] = []

        # Find the main page (matches process name, or first subsheet)
        main_page_id = None
        main_page_name = None
        for page_id, name in subsheets_by_id.items():
            if name == process_name:
                main_page_id = page_id
                main_page_name = name
                break

        # Fallback: use first subsheet as main
        if main_page_id is None and subsheets_by_id:
            main_page_id = next(iter(subsheets_by_id.keys()))
            main_page_name = subsheets_by_id[main_page_id]

        # If no subsheets exist, create a default main page
        if not main_page_id:
            main_page_id = "main"
            main_page_name = process_name

        # Add main page with stages that have no subsheetid
        main_page_stages = main_stages + paged_stages.pop(main_page_id, [])
        pages.append(
            RawPage(
                page_id=main_page_id,
                name=main_page_name,
                stages=main_page_stages,
                is_main=True,
                published=subsheets_published.get(main_page_id, False),
            )
        )

        # Add remaining sub-pages
        for page_id, stages in paged_stages.items():
            page_name = subsheets_by_id.get(page_id, page_id)
            pages.append(
                RawPage(
                    page_id=page_id,
                    name=page_name,
                    stages=stages,
                    is_main=False,
                    published=subsheets_published.get(page_id, False),
                )
            )

        return RawProcess(
            process_id=process_id,
            name=process_name,
            version=process_version,
            pages=pages,
            source_file="",  # Will be set by parse_process
        )

    except ParseError:
        raise
    except (ValueError, AttributeError) as exc:
        raise ParseError(f"Failed to parse artefact: {exc}") from exc


def parse_process(path: Path) -> MultiArtefactRelease:
    """Parse a Blue Prism .bprelease file into a multi-artefact structure.

    Reads the XML, extracts all processes, objects (VBOs), and environment variables
    from the release container. Returns a structured dict that distinguishes the
    different artefact types, allowing downstream consumers (Task 4a+) to handle
    each independently.

    **Return type change (Task 3a):** This function now returns `MultiArtefactRelease`
    (a dict with `processes`, `objects`, `environment_variables`, and validation stats)
    instead of a single `RawProcess`. The old single-process return type is **not**
    backward compatible — see Task 4a for how downstream consumers adapt.

    Args:
        path: Path to the .bprelease file.

    Returns:
        MultiArtefactRelease dict with parsed processes, objects, env vars, and stats.

    Raises:
        ParseError: If the file does not exist, cannot be read, or is not valid XML.
        ConfigError: If the declared item count doesn't match the actual count.
    """
    if not path.exists():
        raise ParseError(f"File does not exist: {path}")

    try:
        tree = etree.parse(str(path))
    except OSError as exc:
        raise ParseError(f"Failed to read file {path}: {exc}") from exc
    except etree.XMLSyntaxError as exc:
        raise ParseError(f"Invalid XML in {path}: {exc}") from exc

    try:
        root = tree.getroot()
        root_tag = _strip_ns(root.tag)

        # Handle both direct <process> root and wrapped <release><contents><process> structure
        if root_tag == "process":
            # Single process file (not a release container)
            # For backward compatibility, wrap it in a MultiArtefactRelease
            raw_process = parse_element(root, root.get("id", ""), root)
            raw_process["source_file"] = str(path.absolute())
            return MultiArtefactRelease(
                processes=[raw_process],
                objects=[],
                environment_variables=[],
                source_file=str(path.absolute()),
                validation={
                    "declared_count": 1,
                    "process_count": 1,
                    "object_count": 0,
                    "env_var_count": 0,
                    "group_count": 0,
                },
            )

        elif root_tag == "release":
            # Multi-artefact release container
            # Locate the <bpr:contents> element (in the release namespace)
            contents = None
            # Try with explicit release namespace first
            contents = root.find(f"{{{BPR}}}contents")
            if contents is None:
                # Try without namespace for compatibility
                contents = root.find("contents")

            if contents is None:
                raise ParseError("No <bpr:contents> element found in release file")

            # Validate declared count (per CLAUDE.md and task requirement)
            declared_count = int(contents.get("count", 0))

            # ── Iterate and parse all artefacts ──────────────────────────────────

            processes: list[RawProcess] = []
            objects: list[RawProcess] = []
            env_vars: list[RawEnvironmentVariable] = []
            groups: list[dict] = []

            for child in contents:
                tag = _strip_ns(child.tag)
                release_id = child.get("id", "").strip()

                if tag == "process":
                    try:
                        raw_proc = parse_element(child, release_id, root)
                        raw_proc["source_file"] = str(path.absolute())
                        processes.append(raw_proc)
                    except ParseError as exc:
                        raise ParseError(f"Failed to parse process {release_id}: {exc}") from exc

                elif tag == "object":
                    try:
                        raw_obj = parse_element(child, release_id, root)
                        raw_obj["source_file"] = str(path.absolute())
                        objects.append(raw_obj)
                    except ParseError as exc:
                        raise ParseError(f"Failed to parse object {release_id}: {exc}") from exc

                elif tag == "environment-variable":
                    # Parse environment variable (Task 3b)
                    try:
                        desc_elem = child.find(f"{{{ENV}}}description")
                        if desc_elem is None:
                            desc_elem = child.find("description")
                        env_var = RawEnvironmentVariable(
                            id=child.get("id", "").strip(),
                            name=child.get("name", "").strip(),
                            data_type=child.get("type", "text").strip(),
                            value=child.get("value", "").strip(),
                            description=(
                                desc_elem.text.strip()
                                if desc_elem is not None and desc_elem.text
                                else ""
                            ),
                        )
                        env_vars.append(env_var)
                    except (ValueError, AttributeError) as exc:
                        raise ParseError(f"Failed to parse environment variable: {exc}") from exc

                elif tag in ("process-group", "object-group"):
                    # Note groups but don't process them further — they're reference metadata only
                    groups.append({"id": child.get("id", ""), "name": child.get("name", "")})

                # All other tags are silently skipped

            # ── Validation: verify declared count matches actual count ──────────────

            total_count = len(processes) + len(objects) + len(env_vars) + len(groups)
            if total_count != declared_count:
                raise ConfigError(
                    f"Content count mismatch: declared={declared_count}, "
                    f"actual={total_count} (processes={len(processes)}, objects={len(objects)}, "
                    f"env_vars={len(env_vars)}, groups={len(groups)})"
                )

            return MultiArtefactRelease(
                processes=processes,
                objects=objects,
                environment_variables=env_vars,
                source_file=str(path.absolute()),
                validation={
                    "declared_count": declared_count,
                    "process_count": len(processes),
                    "object_count": len(objects),
                    "env_var_count": len(env_vars),
                    "group_count": len(groups),
                },
            )

        else:
            raise ParseError(
                f"Expected root element <process> or <release>, got <{root_tag}> in {path}"
            )

    except ParseError:
        raise
    except ConfigError:
        raise
    except (etree.XMLSyntaxError, AttributeError, ValueError) as exc:
        raise ParseError(f"Failed to parse {path}: {exc}") from exc
