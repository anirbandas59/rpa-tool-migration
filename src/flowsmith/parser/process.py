"""Blue Prism XML process parser — .bprelease → RawProcess dict.

Parses Blue Prism .bprelease XML files into a RawProcess TypedDict,
ready for AST building. Handles namespace stripping, stage type
preservation, data item extraction, and parameter mapping.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lxml import etree

from flowsmith.ast.builder import RawDataItem, RawPage, RawProcess, RawStage
from flowsmith.exceptions import ParseError


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

        # Extract initial value from <value> child element
        initial_value: str | None = None
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

        # Parse data items
        data_items: list[RawDataItem] = []
        for di_elem in stage_elem.findall("dataitem"):
            data_items.append(_parse_data_item(di_elem))

        # Parse exception handler id from <onexception> child
        exception_handler_id: str | None = None
        onexc_elem = stage_elem.find("onexception")
        if onexc_elem is not None:
            exception_handler_id = onexc_elem.get("stage", None)
            if exception_handler_id:
                exception_handler_id = exception_handler_id.strip()

        # Parse exception type from <exception> child
        exception_type: str | None = None
        exc_elem = stage_elem.find("exception")
        if exc_elem is not None:
            exc_type = exc_elem.get("type", None)
            if exc_type:
                exception_type = exc_type.strip()

        # Parse params_map
        params_map: dict[str, str] = {}

        # For Action stages: extract inputs
        inputs_elem = stage_elem.find("inputs")
        if inputs_elem is not None:
            for input_elem in inputs_elem.findall("input"):
                input_name = input_elem.get("name", "").strip()
                input_expr = input_elem.get("expr", "").strip()
                if input_name:
                    params_map[input_name] = input_expr

        # For Calculation stages: extract calculation expressions
        calc_elem = stage_elem.find("calculation")
        if calc_elem is not None:
            calc_expr = calc_elem.get("expression", "").strip()
            calc_stage = calc_elem.get("stage", "").strip()
            if calc_stage and calc_expr:
                params_map[calc_stage] = calc_expr

        return RawStage(
            stage_id=stage_id,
            stage_type=stage_type,
            name=name,
            data_items=data_items,
            exception_handler_id=exception_handler_id,
            exception_type=exception_type,
            params_map=params_map,
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
        )
    except (ValueError, AttributeError) as exc:
        raise ParseError(f"Failed to parse page: {exc}") from exc


def parse_process(path: Path) -> RawProcess:
    """Parse a Blue Prism .bprelease or .xml file into a RawProcess dict.

    Reads the XML, extracts process metadata, pages, and stages,
    and returns a RawProcess dict matching the TypedDict contract.

    Args:
        path: Path to the .bprelease or .xml file.

    Returns:
        RawProcess dict ready to pass to build_ast().

    Raises:
        ParseError: If the file does not exist, cannot be read,
            or is not valid Blue Prism XML.
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
        process_elem = None
        metadata_elem = None

        if root_tag == "process":
            process_elem = root
            metadata_elem = root
        elif root_tag == "release":
            # Look for <process> inside <contents>
            # Try with namespace first, then without
            namespace = root.nsmap.get(None) or (
                list(root.nsmap.values())[0] if root.nsmap else None
            )

            contents = None
            if namespace:
                contents = root.find(f"{{{namespace}}}contents")
            if contents is None:
                contents = root.find("contents")

            if contents is not None:
                # Find the first <process> in contents (outer process wrapper with id)
                outer_process = None
                for child in contents:
                    if _strip_ns(child.tag) == "process":
                        outer_process = child
                        break

                metadata_elem = outer_process

                # Then find the inner <process> inside the outer one
                # (the actual process with stages and subsheets)
                if outer_process is not None:
                    for child in outer_process:
                        if _strip_ns(child.tag) == "process":
                            process_elem = child
                            break

                    # If no inner process, use the outer one
                    if process_elem is None:
                        process_elem = outer_process

        if process_elem is None or metadata_elem is None:
            raise ParseError(
                f"Expected root element <process> or <release><contents><process>, got <{root_tag}> in {path}"
            )

        # Extract process metadata (use metadata_elem for id, process_elem for other fields)
        process_id = metadata_elem.get("id", "").strip()
        if not process_id:
            raise ParseError("process element missing required 'id' attribute")

        process_name = (process_elem.get("name", "") or metadata_elem.get("name", "")).strip()
        if not process_name:
            raise ParseError("process element missing required 'name' attribute")

        process_version = (
            process_elem.get("version", "") or metadata_elem.get("version", "")
        ).strip()

        # Parse all pages (subsheets) and stages
        # Support two formats:
        # 1. Test format: stages nested within <subsheet> elements
        # 2. Real format: stages flat with <subsheetid> children
        subsheets_by_id: dict[str, Any] = {}
        paged_stages: dict[str, list[RawStage]] = {}
        extracted_stage_ids: set[str] = set()

        for subsheet_elem in process_elem.iter():
            if _strip_ns(subsheet_elem.tag) != "subsheet":
                continue

            page_id = subsheet_elem.get("subsheetid", "").strip()
            if not page_id:
                raise ParseError("subsheet missing required 'subsheetid' attribute")

            page_name = subsheet_elem.get("name", "").strip()
            if not page_name:
                page_name = page_id
            subsheets_by_id[page_id] = {"name": page_name, "elem": subsheet_elem}

            # Extract stages nested within this subsheet (test format)
            for elem in subsheet_elem.iter():
                if _strip_ns(elem.tag) == "stage":
                    stage = _parse_stage(elem)
                    extracted_stage_ids.add(stage["stage_id"])
                    if page_id:
                        if page_id not in paged_stages:
                            paged_stages[page_id] = []
                        paged_stages[page_id].append(stage)

        # Also collect flat stages with <subsheetid> children (real export format)
        main_stages: list[RawStage] = []
        namespace = "http://www.blueprism.co.uk/product/process"

        for stage_elem in process_elem.iter():
            if _strip_ns(stage_elem.tag) != "stage":
                continue

            # Skip if already extracted as nested stage
            stage_id = stage_elem.get("stageid", "").strip()
            if stage_id in extracted_stage_ids:
                continue

            # Parse the stage
            stage = _parse_stage(stage_elem)

            # Determine which page this stage belongs to by checking subsheetid child
            subsheetid = (
                stage_elem.findtext(f"{{{namespace}}}subsheetid")
                or stage_elem.findtext("subsheetid")
                or ""
            ).strip()

            if subsheetid:
                # Stage belongs to a subsheet
                if subsheetid not in paged_stages:
                    paged_stages[subsheetid] = []
                paged_stages[subsheetid].append(stage)
            else:
                # Stage has no subsheetid → belongs to main page
                main_stages.append(stage)

        # Build pages: main page first, then sub-pages
        pages: list[RawPage] = []

        # Find the main page (matches process name, or first subsheet)
        main_page_id = None
        main_page_name = None
        for page_id, info in subsheets_by_id.items():
            if info["name"] == process_name:
                main_page_id = page_id
                main_page_name = info["name"]
                break

        # Fallback: use first subsheet as main
        if main_page_id is None and subsheets_by_id:
            main_page_id = next(iter(subsheets_by_id.keys()))
            main_page_name = subsheets_by_id[main_page_id]["name"]

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
            )
        )

        # Add remaining sub-pages
        for page_id, stages in paged_stages.items():
            page_name = subsheets_by_id[page_id]["name"] if page_id in subsheets_by_id else page_id
            pages.append(
                RawPage(
                    page_id=page_id,
                    name=page_name,
                    stages=stages,
                    is_main=False,
                )
            )

        return RawProcess(
            process_id=process_id,
            name=process_name,
            version=process_version,
            pages=pages,
            source_file=str(path.absolute()),
        )

    except ParseError:
        raise
    except (etree.XMLSyntaxError, AttributeError, ValueError) as exc:
        raise ParseError(f"Failed to parse {path}: {exc}") from exc
