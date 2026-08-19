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
    decision_expression: str | None
    code_text: str | None
    narrative: str | None
    initial_value: str | None
    timeout_seconds: int | None
    group_id: str | None
    exception_detail: str | None
    exception_usecurrent: bool
    input_friendlynames: dict[str, str]


class RawPage(TypedDict):
    """A single page from the raw parsed dict."""

    page_id: str
    name: str
    stages: list[RawStage]
    is_main: bool
    published: bool


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


def _extract_common_stage_fields(raw: RawStage) -> dict[str, object]:
    """Extract the fields shared by every BPStage construction path.

    Uses `.get()` (not direct indexing) for every field introduced after the
    original RawStage contract so that older/minimal RawStage fixtures
    (e.g. hand-built test dicts that only set the original keys) keep
    working — missing keys fall back to None/empty defaults.

    Args:
        raw: RawStage dict from the parser.

    Returns:
        Dict of keyword arguments ready to spread into a BPStage(...) call.
    """
    return {
        "exception_handler_id": raw.get("exception_handler_id"),
        "exception_type": raw.get("exception_type"),
        "params_map": raw.get("params_map") or {},
        "decision_expression": raw.get("decision_expression"),
        "code_text": raw.get("code_text"),
        "narrative": raw.get("narrative"),
        "timeout_seconds": raw.get("timeout_seconds"),
        "group_id": raw.get("group_id"),
        "exception_detail": raw.get("exception_detail"),
        "exception_usecurrent": raw.get("exception_usecurrent") or False,
    }


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
        common_fields = _extract_common_stage_fields(raw)

        # 2. Collapse rules

        if stage_type == "MultipleCalculation":
            params = raw["params_map"]
            for i, (bp_param, pa_param) in enumerate(params.items(), start=1):
                sub_id = f"{stage_id}__calc_{i}"
                sub_fields = {**common_fields, "params_map": {bp_param: pa_param}}
                stages.append(
                    BPStage(
                        stage_id=sub_id,
                        stage_type=StageType.CALCULATION,
                        name=f"{raw['name']} [{i}]",
                        data_items=data_items,
                        **sub_fields,
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
                    is_subsheet_call=True,
                    **common_fields,
                )
            )
            continue

        if stage_type in ("WaitStart", "WaitEnd"):
            stage = BPStage(
                stage_id=stage_id,
                stage_type=StageType.WAIT,
                name=raw["name"],
                data_items=data_items,
                **common_fields,
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
                **common_fields,
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
                    **common_fields,
                )
            )
            continue

        raise ASTBuildError(f"Unknown stage type '{stage_type}' on stage '{stage_id}'")

    return stages, bracket_roles


def _stack_pair_brackets(
    ordered_stages: list[BPStage],
    bracket_roles: dict[str, str],
    bracket_start: str,
    bracket_end: str,
) -> tuple[list[BPStage], list[BPStage]]:
    """Stack-match Start/End bracket stages, in the given order, setting pair_id.

    Also handles End appearing before its Start (out-of-order brackets).
    pair_id is always the Start stage_id, assigned to both partners.

    Args:
        ordered_stages: Bracket stages of one kind (Wait or Loop), in
            page-encounter order, already filtered to a single pairing scope
            (either one group_id's stages, or the no-group_id fallback set).
        bracket_roles: Dict mapping stage_id → raw bracket role string.
        bracket_start: The Start role string (e.g. "WaitStart").
        bracket_end: The End role string (e.g. "WaitEnd").

    Returns:
        A tuple of (unmatched Start stages, unmatched End stages) — both
        empty when every stage found a partner.
    """
    start_stack: list[BPStage] = []
    end_queue: list[BPStage] = []  # unpaired End stages

    for stage in ordered_stages:
        role = bracket_roles[stage.stage_id]
        if role == bracket_start:
            # If we have unpaired End stages, pair with the oldest one
            if end_queue:
                end_stage = end_queue.pop(0)
                pair_id = stage.stage_id
                end_stage.pair_id = pair_id
                stage.pair_id = pair_id
            else:
                start_stack.append(stage)
        elif role == bracket_end:
            # If we have unpaired Start stages, pair with the most recent one
            if start_stack:
                partner = start_stack.pop()
                pair_id = partner.stage_id
                partner.pair_id = pair_id
                stage.pair_id = pair_id
            else:
                # No Start available yet, queue this End for later pairing
                end_queue.append(stage)

    return start_stack, end_queue


def _assign_wait_loop_pairs(
    stages: list[BPStage],
    bracket_roles: dict[str, str],
    page_name: str,
) -> None:
    """Match WaitStart/WaitEnd and LoopStart/LoopEnd pairs, setting pair_id in-place.

    Bracket stages that carry a `group_id` (from the BP <groupid> element) are
    scoped to that group before stack-matching: real BP exports can fan a
    single logical Wait/Loop construct out into several WaitStart/WaitEnd (or
    LoopStart/LoopEnd) pairs that all share one groupid (e.g. multiple wait
    conditions on one Wait stage), so group_id is a pairing *scope*, not a
    guarantee of exactly one Start and one End. Within each scope (and within
    the no-group_id fallback set), pairing is stack-based so nested/out-of-
    order pairs are still matched correctly — this is the same algorithm used
    when group_id is absent entirely (older BP exports).
    pair_id is always the Start stage_id, assigned to both partners.

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
        grouped: dict[str, list[BPStage]] = defaultdict(list)
        positional: list[BPStage] = []

        for stage in stages:
            role = bracket_roles.get(stage.stage_id)
            if role not in (bracket_start, bracket_end):
                continue
            if stage.group_id is not None:
                grouped[stage.group_id].append(stage)
            else:
                positional.append(stage)

        unmatched_starts: list[BPStage] = []
        unmatched_ends: list[BPStage] = []

        # 1. group_id-scoped stack matching (reliable — pairs only within
        #    stages that share the same logical Wait/Loop construct)
        for group_stages in grouped.values():
            s, e = _stack_pair_brackets(group_stages, bracket_roles, bracket_start, bracket_end)
            unmatched_starts.extend(s)
            unmatched_ends.extend(e)

        # 2. Fallback: stack-based positional matching for stages with no group_id
        s, e = _stack_pair_brackets(positional, bracket_roles, bracket_start, bracket_end)
        unmatched_starts.extend(s)
        unmatched_ends.extend(e)

        # Check for unmatched brackets
        if unmatched_starts:
            unmatched = ", ".join(s.stage_id for s in unmatched_starts)
            raise ASTBuildError(
                f"Unmatched {bracket_start} stage(s) [{unmatched}] "
                f"with no {bracket_end} on page '{page_name}'"
            )
        if unmatched_ends:
            unmatched = ", ".join(s.stage_id for s in unmatched_ends)
            raise ASTBuildError(
                f"Unmatched {bracket_end} stage(s) [{unmatched}] "
                f"with no {bracket_start} on page '{page_name}'"
            )


def _assign_block_pairs(stages: list[BPStage], page_name: str) -> None:
    """Match Block open/close pairs by name, setting pair_id in-place.

    Groups Block stages by name. Within each group, pairs are assigned
    in encounter order: first with second, third with fourth, etc.
    pair_id is the first stage's stage_id for each pair.
    Singleton Blocks (unpaired) are left without a pair_id.

    Args:
        stages: Normalised stage list for one page (modified in-place).
        page_name: Page name used in error messages.
    """
    blocks_by_name: dict[str, list[BPStage]] = defaultdict(list)
    for stage in stages:
        if stage.stage_type == StageType.BLOCK:
            blocks_by_name[stage.name].append(stage)

    for _name, block_stages in blocks_by_name.items():
        # Pair blocks in groups: first with second, third with fourth, etc.
        # If there's an odd count, the last block remains unpaired (singleton).
        for i in range(0, len(block_stages) - 1, 2):
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
        published=raw_page.get("published", False),
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
