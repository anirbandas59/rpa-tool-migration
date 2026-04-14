"""AST builder — converts a raw parsed dict into a validated BPProcess AST.

This is the single place where:
  - Stage type strings from XML are normalised to StageType enum values
  - Non-canonical types are collapsed (MultipleCalculation, SubSheet, WaitStart/End, etc.)
  - Skip types are dropped (Anchor, Note, SubSheetInfo, ProcessInfo, Process)
  - Paired bracket stages are matched and pair_id is assigned
  - Pydantic ValidationError is wrapped as ASTBuildError
"""

from __future__ import annotations

from collections import defaultdict
from typing import TypedDict

from pydantic import ValidationError as PydanticValidationError

from flowsmith.ast.models import BPDataItem, BPPage, BPProcess, BPStage, StageType
from flowsmith.exceptions import ASTBuildError

# ── Input contract TypedDicts ───────────────────────────────────────────────


class RawDataItem(TypedDict):
    """A single data item from the raw parsed dict."""

    name: str
    data_type: str
    initial_value: str | None
    is_input: bool
    is_output: bool


class RawStage(TypedDict):
    """A single stage from the raw parsed dict."""

    stage_id: str
    stage_type: str  # raw XML string e.g. "SubSheetInfo"
    name: str
    data_items: list[RawDataItem]
    exception_handler_id: str | None
    exception_type: str | None
    params_map: dict[str, str]


class RawPage(TypedDict):
    """A single page from the raw parsed dict."""

    page_id: str
    name: str
    stages: list[RawStage]
    is_main: bool


class RawProcess(TypedDict):
    """The root raw parsed dict produced by the XML parser."""

    process_id: str
    name: str
    version: str
    pages: list[RawPage]
    source_file: str


# ── Normalisation constants ─────────────────────────────────────────────────

_SKIP_TYPES: frozenset[str] = frozenset(
    {"Anchor", "Note", "SubSheetInfo", "ProcessInfo", "Process"}
)

_DIRECT_MAP: dict[str, StageType] = {
    "Start": StageType.START,
    "End": StageType.END,
    "Action": StageType.ACTION,
    "Decision": StageType.DECISION,
    "Calculation": StageType.CALCULATION,
    "Code": StageType.CODE,
    "Navigate": StageType.NAVIGATE,
    "Read": StageType.READ,
    "Write": StageType.WRITE,
    "Exception": StageType.EXCEPTION,
    "Recover": StageType.RECOVER,
    "Resume": StageType.RESUME,
    "Block": StageType.BLOCK,
    "Collection": StageType.COLLECTION,
    "Data": StageType.DATA,
}

# ── Private helpers ─────────────────────────────────────────────────────────


def _build_data_items(raw_items: list[RawDataItem]) -> list[BPDataItem]:
    """Convert raw data item dicts to BPDataItem models.

    Args:
        raw_items: List of RawDataItem dicts.

    Returns:
        List of validated BPDataItem instances.
    """
    return [
        BPDataItem(
            name=item["name"],
            data_type=item["data_type"],
            initial_value=item.get("initial_value"),
            is_input=item.get("is_input", False),
            is_output=item.get("is_output", False),
        )
        for item in raw_items
    ]


def _normalise_stages(
    raw_stages: list[RawStage],
) -> tuple[list[BPStage], dict[str, str]]:
    """Normalise raw stage dicts into BPStage objects.

    Applies skip, collapse, and direct-map rules in order.
    Returns both the stage list and a bracket-role map for pair assignment.

    Args:
        raw_stages: List of RawStage dicts from one page.

    Returns:
        A tuple of:
          - List of BPStage instances (skip types removed, collapse rules applied).
          - Dict mapping stage_id → raw bracket role string
            (e.g. "WaitStart", "LoopEnd") for stages that need pairing.

    Raises:
        ASTBuildError: If an unknown stage type is encountered.
    """
    stages: list[BPStage] = []
    bracket_roles: dict[str, str] = {}  # stage_id → bracket role

    for raw in raw_stages:
        stage_type = raw["stage_type"]
        stage_id = raw["stage_id"]

        # 1. Skip types — drop entirely
        if stage_type in _SKIP_TYPES:
            continue

        data_items = _build_data_items(raw["data_items"])

        # 2. Collapse rules

        if stage_type == "MultipleCalculation":
            params = raw["params_map"]
            for i, (bp_param, pa_param) in enumerate(params.items(), start=1):
                sub_id = f"{stage_id}__calc_{i}"
                stages.append(
                    BPStage(
                        stage_id=sub_id,
                        stage_type=StageType.CALCULATION,
                        name=f"{raw['name']} [{i}]",
                        data_items=data_items,
                        exception_handler_id=raw["exception_handler_id"],
                        exception_type=raw["exception_type"],
                        params_map={bp_param: pa_param},
                    )
                )
            continue

        if stage_type == "SubSheet":
            stages.append(
                BPStage(
                    stage_id=stage_id,
                    stage_type=StageType.ACTION,
                    name=raw["name"],
                    data_items=data_items,
                    exception_handler_id=raw["exception_handler_id"],
                    exception_type=raw["exception_type"],
                    params_map=raw["params_map"],
                    is_subsheet_call=True,
                )
            )
            continue

        if stage_type in ("WaitStart", "WaitEnd"):
            stage = BPStage(
                stage_id=stage_id,
                stage_type=StageType.WAIT,
                name=raw["name"],
                data_items=data_items,
                exception_handler_id=raw["exception_handler_id"],
                exception_type=raw["exception_type"],
                params_map=raw["params_map"],
            )
            stages.append(stage)
            bracket_roles[stage_id] = stage_type
            continue

        if stage_type in ("LoopStart", "LoopEnd"):
            stage = BPStage(
                stage_id=stage_id,
                stage_type=StageType.LOOP,
                name=raw["name"],
                data_items=data_items,
                exception_handler_id=raw["exception_handler_id"],
                exception_type=raw["exception_type"],
                params_map=raw["params_map"],
            )
            stages.append(stage)
            bracket_roles[stage_id] = stage_type
            continue

        # 3. Direct map
        if stage_type in _DIRECT_MAP:
            stages.append(
                BPStage(
                    stage_id=stage_id,
                    stage_type=_DIRECT_MAP[stage_type],
                    name=raw["name"],
                    data_items=data_items,
                    exception_handler_id=raw["exception_handler_id"],
                    exception_type=raw["exception_type"],
                    params_map=raw["params_map"],
                )
            )
            continue

        raise ASTBuildError(f"Unknown stage type '{stage_type}' on stage '{stage_id}'")

    return stages, bracket_roles


def _assign_wait_loop_pairs(
    stages: list[BPStage],
    bracket_roles: dict[str, str],
    page_name: str,
) -> None:
    """Match WaitStart/WaitEnd and LoopStart/LoopEnd pairs, setting pair_id in-place.

    Uses a stack so nested pairs are matched correctly. pair_id is always
    the WaitStart (or LoopStart) stage_id, assigned to both partners.

    Args:
        stages: Normalised stage list for one page (modified in-place).
        bracket_roles: Dict mapping stage_id → raw bracket role string.
        page_name: Page name used in error messages.

    Raises:
        ASTBuildError: If any bracket stage has no matching partner.
    """
    for bracket_start, bracket_end, _type_label in (
        ("WaitStart", "WaitEnd", "Wait"),
        ("LoopStart", "LoopEnd", "Loop"),
    ):
        stack: list[BPStage] = []
        for stage in stages:
            role = bracket_roles.get(stage.stage_id)
            if role == bracket_start:
                stack.append(stage)
            elif role == bracket_end:
                if not stack:
                    raise ASTBuildError(
                        f"Unmatched {bracket_end} stage '{stage.stage_id}' "
                        f"(no preceding {bracket_start}) on page '{page_name}'"
                    )
                partner = stack.pop()
                pair_id = partner.stage_id
                partner.pair_id = pair_id
                stage.pair_id = pair_id
        if stack:
            unmatched = ", ".join(s.stage_id for s in stack)
            raise ASTBuildError(
                f"Unmatched {bracket_start} stage(s) [{unmatched}] "
                f"with no {bracket_end} on page '{page_name}'"
            )


def _assign_block_pairs(stages: list[BPStage], page_name: str) -> None:
    """Match Block open/close pairs by name, setting pair_id in-place.

    Groups Block stages by name. Within each group, pairs are assigned
    in encounter order: first with second, third with fourth, etc.
    pair_id is the first stage's stage_id for each pair.

    Args:
        stages: Normalised stage list for one page (modified in-place).
        page_name: Page name used in error messages.

    Raises:
        ASTBuildError: If any Block name group has an odd count.
    """
    blocks_by_name: dict[str, list[BPStage]] = defaultdict(list)
    for stage in stages:
        if stage.stage_type == StageType.BLOCK:
            blocks_by_name[stage.name].append(stage)

    for name, block_stages in blocks_by_name.items():
        if len(block_stages) % 2 != 0:
            raise ASTBuildError(
                f"Unmatched Block stage with name '{name}' on page '{page_name}' "
                f"(found {len(block_stages)} block(s), expected an even count)"
            )
        for i in range(0, len(block_stages), 2):
            first = block_stages[i]
            second = block_stages[i + 1]
            pair_id = first.stage_id
            first.pair_id = pair_id
            second.pair_id = pair_id


def _build_page(raw_page: RawPage) -> BPPage:
    """Build a validated BPPage from a raw page dict.

    Args:
        raw_page: RawPage dict from the parser.

    Returns:
        Validated BPPage with all stages normalised and pairs assigned.

    Raises:
        ASTBuildError: If normalisation or pair matching fails.
    """
    stages, bracket_roles = _normalise_stages(raw_page["stages"])
    _assign_wait_loop_pairs(stages, bracket_roles, raw_page["name"])
    _assign_block_pairs(stages, raw_page["name"])

    return BPPage(
        page_id=raw_page["page_id"],
        name=raw_page["name"],
        stages=stages,
        is_main=raw_page.get("is_main", False),
    )


# ── Public API ──────────────────────────────────────────────────────────────


def build_ast(raw: RawProcess) -> BPProcess:
    """Build a validated BPProcess AST from a raw parsed dict.

    Args:
        raw: RawProcess dict produced by the XML parser.

    Returns:
        Fully validated BPProcess with all stages normalised.

    Raises:
        ASTBuildError: If any normalisation or validation step
            fails — unmatched pairs, unknown stage types,
            orphan stage IDs, Pydantic validation errors.
    """
    pages: list[BPPage] = []
    for raw_page in raw["pages"]:
        pages.append(_build_page(raw_page))

    try:
        return BPProcess(
            process_id=raw["process_id"],
            name=raw["name"],
            version=raw["version"],
            pages=pages,
            source_file=raw["source_file"],
        )
    except PydanticValidationError as exc:
        raise ASTBuildError(f"AST validation failed: {exc}") from exc
