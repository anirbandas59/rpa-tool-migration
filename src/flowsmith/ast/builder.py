"""AST builder — converts a raw parsed dict into a validated BPProcess AST.

This is the single place where:
  - Stage type strings from XML are normalised to StageType enum values
  - Non-canonical types are collapsed (MultipleCalculation, SubSheet, Process, WaitStart/End, etc.)
  - Skip types are dropped (Anchor, Note, SubSheetInfo, ProcessInfo)
  - Paired bracket stages are matched and pair_id is assigned
  - Pydantic ValidationError is wrapped as ASTBuildError
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, TypedDict

from pydantic import ValidationError as PydanticValidationError

from flowsmith.ast.models import (
    BPDataItem,
    BPEnvironmentVariable,
    BPPage,
    BPProcess,
    BPStage,
    ReviewFlag,
    StageType,
)
from flowsmith.exceptions import ASTBuildError

if TYPE_CHECKING:
    from flowsmith.mapper.vbo_router import VBORouter


# Type alias for the multi-artefact release shape from Task 3a/3b
class MultiArtefactRelease(TypedDict, total=False):
    """Multi-artefact release parsing result — Task 3a/3b."""

    processes: list[RawProcess]
    objects: list[RawProcess]
    environment_variables: list[dict[str, str]]
    source_file: str
    validation: dict[str, int]


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
    onsuccess_target: str | None
    ontrue_target: str | None
    onfalse_target: str | None
    processid: str | None  # SubSheet/Process cross-reference ID (Task 4a)


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

_SKIP_TYPES: frozenset[str] = frozenset({"Anchor", "Note", "SubSheetInfo", "ProcessInfo"})

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
        "onsuccess_target": raw.get("onsuccess_target"),
        "ontrue_target": raw.get("ontrue_target"),
        "onfalse_target": raw.get("onfalse_target"),
        "processid": raw.get("processid"),  # SubSheet/Process cross-reference (Task 4a)
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

        if stage_type == "Process":
            # PROCESS stages are normalised to ACTION(is_process_call=True) per CLAUDE.md
            # "Normalised on parse" table: PROCESS → ACTION (is_process_call=True)
            stages.append(
                BPStage(
                    stage_id=stage_id,
                    stage_type=StageType.ACTION,
                    name=raw["name"],
                    data_items=data_items,
                    is_process_call=True,
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


def _detect_vbo_call_fusions(
    stages: list[BPStage],
    router: VBORouter | None = None,
    page_name: str = "",
) -> None:
    """Detect and resolve VBO call-fusion candidates.

    Scans for pairs of adjacent ACTION stages where stage N's numeric output
    feeds into stage N+1's numeric input (the generic structural signal for
    "acquire resource, then use it" fusion candidates per architecture doc
    §B_FUSION). For each candidate:
    - If router is provided: checks against vbo_catalogue.yaml's fusion_patterns
      - Matched patterns: marks the sequence as fused with fusion_action
      - Unmatched candidates: attaches a ReviewFlag for curation
    - If router is None: only flags structural candidates without resolution

    Modifies stages in-place:
    - Sets fused_with, fusion_action, is_vestigial fields on affected stages.
    - Creates ReviewFlag entries for unresolved candidates.

    Args:
        stages: Normalised stage list for one page (modified in-place).
        router: VBORouter instance for resolving patterns, or None.
        page_name: Page name used in error messages.
    """
    if not router:
        return  # No router → no fusion resolution possible

    # Iterate through adjacent pairs of ACTION stages
    for i in range(len(stages) - 1):
        stage_n = stages[i]
        stage_n_plus_1 = stages[i + 1]

        # Both must be ACTION stages
        if stage_n.stage_type != StageType.ACTION or stage_n_plus_1.stage_type != StageType.ACTION:
            continue

        # Check for numeric handle handoff: stage N has numeric output, stage N+1 has matching input
        # Find numeric outputs from stage N
        numeric_outputs = {
            item.name: item
            for item in stage_n.data_items
            if item.is_output and item.data_type == "number"
        }

        if not numeric_outputs:
            continue  # No numeric output from stage N → not a fusion candidate

        # Check if stage N+1 has a matching numeric input with same name
        numeric_inputs_by_name = {
            item.name: item
            for item in stage_n_plus_1.data_items
            if item.is_input and item.data_type == "number"
        }

        # Look for a match (same name, same type)
        fusion_candidates = []
        for output_name in numeric_outputs:
            if output_name in numeric_inputs_by_name:
                # Found a match: stage N outputs this, stage N+1 inputs it
                fusion_candidates.append(output_name)

        if not fusion_candidates:
            continue  # No numeric handoff → not a fusion candidate

        # At this point, we have detected a structural fusion candidate.
        # Now try to resolve it via router.resolve_fusion_pattern.

        # Extract VBO/method names from both stages
        vbo_n = stage_n.params_map.get("_vbo_object", "")
        method_n = stage_n.params_map.get("_vbo_action", "")
        vbo_n_plus_1 = stage_n_plus_1.params_map.get("_vbo_object", "")
        method_n_plus_1 = stage_n_plus_1.params_map.get("_vbo_action", "")

        # Both stages must be VBO calls to the same VBO
        if not (vbo_n and method_n and vbo_n_plus_1 and method_n_plus_1 and vbo_n == vbo_n_plus_1):
            # Not a VBO-call pair, or different VBOs → not a resolvable fusion
            # (but still structurally looks like one, so flag it)
            continue

        # Try to resolve against fusion patterns
        pattern, vestigial_methods = router.resolve_fusion_pattern(
            vbo_n, [method_n, method_n_plus_1]
        )

        if pattern:
            # Matched! Mark the sequence as fused.
            # Attach fusion info to the last stage in the sequence (stage N+1)
            stage_n_plus_1.fused_with = [stage_n.stage_id]
            stage_n_plus_1.fusion_action = pattern.fused_action

            # Mark vestigial stages
            for vestigial_method in vestigial_methods:
                if vestigial_method == method_n:
                    stage_n.is_vestigial = True
                elif vestigial_method == method_n_plus_1:
                    stage_n_plus_1.is_vestigial = True
        else:
            # Unresolved fusion candidate: create a ReviewFlag for curation
            handoff_var = fusion_candidates[0]  # Report the first matched handoff
            flag = ReviewFlag(
                stage_id=stage_n_plus_1.stage_id,
                reason=(
                    f"Detected numeric-handle handoff from '{stage_n.name}' "
                    f"(variable '{handoff_var}'). This looks like a VBO call-fusion "
                    f"candidate ({vbo_n}::{method_n} → {method_n_plus_1}), "
                    f"but no matching fusion pattern is defined in vbo_catalogue.yaml. "
                    f"Consider adding a fusion_patterns entry for this VBO pair."
                ),
                severity="warn",
                suggested_fix=(
                    f"Add fusion_patterns entry to vbo_catalogue.yaml for {vbo_n}: "
                    f"sequence=['{method_n}', '{method_n_plus_1}'], "
                    f"or confirm this is not a fusion candidate and close the flag."
                ),
            )
            # Store the flag in pending_flags for later transfer to pa_annotation
            stage_n_plus_1.pending_flags.append(flag)


def _build_multiple_calculation_map(raw_stages: list[RawStage]) -> dict[str, str]:
    """Build a map of MultipleCalculation stage IDs to their first fanned-out sub-stage ID.

    When a MultipleCalculation stage is normalised, it is split into N CALCULATION stages
    with IDs like {original_id}__calc_1, {original_id}__calc_2, etc. Any edge that
    pointed at the original MultipleCalculation ID should be redirected to the first
    fanned-out sub-stage.

    Args:
        raw_stages: List of RawStage dicts from one page (before normalization).

    Returns:
        Dict mapping original MultipleCalculation stage_id → first __calc_N sub-stage ID.
        Non-MultipleCalculation stages are not included.
    """
    mc_map: dict[str, str] = {}

    for raw_stage in raw_stages:
        if raw_stage["stage_type"] != "MultipleCalculation":
            continue

        original_id = raw_stage["stage_id"]
        # The first fanned-out sub-stage will have ID {original_id}__calc_1
        first_sub_id = f"{original_id}__calc_1"
        mc_map[original_id] = first_sub_id

    return mc_map


def _apply_multiple_calculation_redirects(
    stages: list[BPStage],
    mc_map: dict[str, str],
) -> None:
    """Update stage edges to redirect MultipleCalculation references to their first sub-stage.

    For any stage whose onsuccess/ontrue/onfalse target is a MultipleCalculation that's
    been fanned out, redirect it to the first sub-stage.

    Args:
        stages: Normalized stage list (modified in-place).
        mc_map: Map from original MC stage_id to first __calc_N sub-stage ID.
    """
    for stage in stages:
        if stage.onsuccess_target and stage.onsuccess_target in mc_map:
            stage.onsuccess_target = mc_map[stage.onsuccess_target]
        if stage.ontrue_target and stage.ontrue_target in mc_map:
            stage.ontrue_target = mc_map[stage.ontrue_target]
        if stage.onfalse_target and stage.onfalse_target in mc_map:
            stage.onfalse_target = mc_map[stage.onfalse_target]


def _build_skip_type_passthrough_map(raw_stages: list[RawStage]) -> dict[str, str]:
    """Build a map of skip-type stage IDs to their pass-through targets.

    Skip-type stages (Anchor, Note, SubSheetInfo, ProcessInfo) are pure routing artifacts
    with no semantic meaning. When a skip-type stage is encountered, edges that point to it
    should pass through to the skip-type's own onsuccess target. This function builds that
    mapping, handling chains of skip-types by recursively following onsuccess edges until
    a non-skip-type is found.

    Per CLAUDE.md's normalisation rules, all these stages are skipped (no AST node),
    but their pass-through edges must be preserved to maintain execution continuity.

    Args:
        raw_stages: List of RawStage dicts from one page (before normalization).

    Returns:
        Dict mapping skip-type stage_id → ultimate target stage_id (following the chain).
        Non-skip-type stages are not included in this map.
    """
    # Build stage_id → raw stage dict for quick lookup
    stage_map: dict[str, RawStage] = {s["stage_id"]: s for s in raw_stages}

    passthrough_map: dict[str, str] = {}

    # For each skip-type stage, find its ultimate pass-through target
    for raw_stage in raw_stages:
        # All four skip types per CLAUDE.md
        if raw_stage["stage_type"] not in _SKIP_TYPES:
            continue

        current_id = raw_stage["stage_id"]
        visited: set[str] = set()  # Track visited to detect cycles

        # Follow onsuccess edges until we hit a non-skip-type or a cycle
        while current_id and current_id not in visited:
            if current_id not in stage_map:
                break  # Target stage not found
            visited.add(current_id)
            current_stage = stage_map[current_id]

            # If this stage is not a skip-type, we've found our ultimate target
            if current_stage["stage_type"] not in _SKIP_TYPES:
                passthrough_map[raw_stage["stage_id"]] = current_id
                break

            # This is a skip-type, keep following
            current_id = current_stage.get("onsuccess_target")

    return passthrough_map


def _apply_anchor_passthroughs(
    stages: list[BPStage],
    anchor_passthrough_map: dict[str, str],
) -> None:
    """Update stage edges to bypass Anchors using the passthrough map.

    For any stage whose onsuccess/ontrue/onfalse target is an Anchor,
    redirect it to the Anchor's ultimate pass-through target.

    Args:
        stages: Normalized stage list (modified in-place).
        anchor_passthrough_map: Map from Anchor stage_id to ultimate target.
    """
    for stage in stages:
        if stage.onsuccess_target and stage.onsuccess_target in anchor_passthrough_map:
            stage.onsuccess_target = anchor_passthrough_map[stage.onsuccess_target]
        if stage.ontrue_target and stage.ontrue_target in anchor_passthrough_map:
            stage.ontrue_target = anchor_passthrough_map[stage.ontrue_target]
        if stage.onfalse_target and stage.onfalse_target in anchor_passthrough_map:
            stage.onfalse_target = anchor_passthrough_map[stage.onfalse_target]


def _build_page(raw_page: RawPage, router: VBORouter | None = None) -> BPPage:
    """Build a validated BPPage from a raw page dict.

    Args:
        raw_page: RawPage dict from the parser.
        router: Optional VBORouter for resolving fusion patterns. If provided,
            fusion candidates are checked against vbo_catalogue.yaml's fusion_patterns.

    Returns:
        Validated BPPage with all stages normalised and pairs assigned.
        Fusion-candidate stages have fused_with, fusion_action, and is_vestigial
        fields populated if a match is found; unresolved candidates get ReviewFlags
        in pending_flags. Skip-type stages are dropped, and edges pointing to them
        are redirected to their pass-through targets. MultipleCalculation stages
        are fanned out, and edges to the original MC ID are redirected to the first
        sub-stage (Task 4a).

    Raises:
        ASTBuildError: If normalisation or pair matching fails.
    """
    # Build skip-type pass-through map BEFORE normalizing (so we still have skip-type data)
    # This handles Anchor, Note, SubSheetInfo, ProcessInfo per CLAUDE.md's skip-type list
    skip_type_passthrough_map = _build_skip_type_passthrough_map(raw_page["stages"])

    # Build MultipleCalculation redirect map BEFORE normalizing (so we know which will fan out)
    mc_redirect_map = _build_multiple_calculation_map(raw_page["stages"])

    stages, bracket_roles = _normalise_stages(raw_page["stages"])

    # Apply skip-type redirects to normalized stages
    _apply_anchor_passthroughs(stages, skip_type_passthrough_map)

    # Apply MultipleCalculation redirects to normalized stages (Task 4a Fix 2)
    _apply_multiple_calculation_redirects(stages, mc_redirect_map)

    _assign_wait_loop_pairs(stages, bracket_roles, raw_page["name"])
    _assign_block_pairs(stages, raw_page["name"])
    _detect_vbo_call_fusions(stages, router, raw_page["name"])

    return BPPage(
        page_id=raw_page["page_id"],
        name=raw_page["name"],
        stages=stages,
        is_main=raw_page.get("is_main", False),
        published=raw_page.get("published", False),
    )


def _build_block_recover_map(pages: list[BPPage]) -> dict[str, str]:
    """Build a map of BLOCK stage IDs to their corresponding RECOVER stage IDs.

    Per CLAUDE.md rule 4 and the task's Do-step 2, the Block→Recover relationship
    is implicit in BP XML (never explicitly encoded as an edge). This function
    reconstructs it by scanning each page for Block/Recover pairs in document order.

    For each Block stage with an unmatched Recover in the same page, the first
    such Recover is paired with the Block. This handles the common case where
    a Block has zero independent incoming edges (it's a pure scope marker whose
    protected body is entered directly by the mainline flow) — we must construct
    this pairing structurally, not via BFS reachability.

    Args:
        pages: List of BPPage objects from the process.

    Returns:
        Dict mapping Block stage_id → Recover stage_id (its paired handler).
    """
    block_recover_map: dict[str, str] = {}

    for page in pages:
        # Find all Block and Recover stages in this page
        block_stages: dict[int, BPStage] = {}  # index → stage
        recover_stages: dict[int, BPStage] = {}  # index → stage

        for idx, stage in enumerate(page.stages):
            if stage.stage_type == StageType.BLOCK:
                block_stages[idx] = stage
            elif stage.stage_type == StageType.RECOVER:
                recover_stages[idx] = stage

        # Pair Blocks with Recovers: for each Block, find the first unmatched
        # Recover after it in document order
        used_recover_indices: set[int] = set()

        for block_idx, block_stage in sorted(block_stages.items()):
            # Find the first Recover after this Block that hasn't been used
            for recover_idx in sorted(recover_stages.keys()):
                if recover_idx > block_idx and recover_idx not in used_recover_indices:
                    recover_stage = recover_stages[recover_idx]
                    block_recover_map[block_stage.stage_id] = recover_stage.stage_id
                    used_recover_indices.add(recover_idx)
                    break

    return block_recover_map


def _compute_reachability(
    pages: list[BPPage],
) -> tuple[list[BPPage], dict[str, str]]:
    """Compute reachability for each page in a process (Task 4a).

    Returns a new list of pages with `reachable=True/False` annotations based
    on reachability from the Main Page via onsuccess/ontrue/onfalse edges,
    SubSheet cross-references, or implicit Block→Recover edges.

    The Block→Recover pairing is constructed structurally (per CLAUDE.md rule 4),
    independently of whether a Block has incoming edges in the BFS, since real
    Blocks can be pure scope markers with no independent incoming edges. Crucially,
    we consult a page's Block→Recover pairs whenever ANY stage on that page becomes
    reachable, not only when the Block stage itself is independently visited via
    BFS (Task 4a Fix A).

    SubSheet cross-references are matched first by processid (if available),
    then by page name as a fallback.

    Args:
        pages: List of BPPage objects from the process.

    Returns:
        Tuple of (new list of BPPage objects with updated reachable annotations,
        block_recover_map dict for Task 4b persistence).
    """
    # Build a stage ID → page mapping for quick lookup
    stage_to_page: dict[str, BPPage] = {}
    for page in pages:
        for stage in page.stages:
            stage_to_page[stage.stage_id] = page

    # Build Block→Recover pairing map structurally (Task 4a)
    # This must be done before BFS so we can follow implicit edges even for
    # Blocks with zero independent incoming edges
    block_recover_map = _build_block_recover_map(pages)

    # Identify the main page (entry point for reachability analysis)
    main_page: BPPage | None = None
    for page in pages:
        if page.is_main:
            main_page = page
            break

    visited_pages: set[str] = set()

    if not main_page:
        # No main page found — mark all as reachable (conservative default)
        for page in pages:
            visited_pages.add(page.page_id)
    else:
        # Perform a graph traversal starting from main_page's Start stage
        visited_stages: set[str] = set()
        to_visit_stages: list[str] = []

        # Find the Start stage on the main page to begin traversal
        start_stage: BPStage | None = None
        for stage in main_page.stages:
            if stage.stage_type == StageType.START:
                start_stage = stage
                break

        if start_stage:
            to_visit_stages.append(start_stage.stage_id)
            visited_pages.add(main_page.page_id)

        # BFS traversal of the execution graph
        # Track which pages we've checked for Block→Recover pairs to avoid duplicate processing
        pages_checked_for_blocks: set[str] = set()

        while to_visit_stages:
            stage_id = to_visit_stages.pop(0)
            if stage_id in visited_stages:
                continue
            visited_stages.add(stage_id)

            if stage_id not in stage_to_page:
                continue

            current_page = stage_to_page[stage_id]
            current_stage: BPStage | None = None

            for s in current_page.stages:
                if s.stage_id == stage_id:
                    current_stage = s
                    break

            if not current_stage:
                continue

            # Mark current page as visited
            if current_page.page_id not in visited_pages:
                visited_pages.add(current_page.page_id)

            # Task 4a Fix A: When a page becomes reachable, immediately consult its Block→Recover
            # pairs. This ensures exception handlers are traversed even when Block stages have
            # zero independent incoming edges.
            if current_page.page_id not in pages_checked_for_blocks:
                pages_checked_for_blocks.add(current_page.page_id)
                for block_id, recover_id in block_recover_map.items():
                    # Check if this block belongs to the current page
                    if (
                        block_id in stage_to_page
                        and stage_to_page[block_id].page_id == current_page.page_id
                        and recover_id not in visited_stages
                    ):
                        to_visit_stages.append(recover_id)

            # Follow onsuccess edge (standard flow)
            if current_stage.onsuccess_target:
                target_id = current_stage.onsuccess_target
                if target_id in stage_to_page:
                    target_page = stage_to_page[target_id]
                    visited_pages.add(target_page.page_id)
                    if target_id not in visited_stages:
                        to_visit_stages.append(target_id)
                elif target_id not in visited_stages:
                    # Unknown target stage — still mark as to visit to traverse it later
                    to_visit_stages.append(target_id)

            # Follow ontrue edge (DECISION true branch)
            if current_stage.ontrue_target:
                target_id = current_stage.ontrue_target
                if target_id in stage_to_page:
                    target_page = stage_to_page[target_id]
                    visited_pages.add(target_page.page_id)
                    if target_id not in visited_stages:
                        to_visit_stages.append(target_id)
                elif target_id not in visited_stages:
                    to_visit_stages.append(target_id)

            # Follow onfalse edge (DECISION false branch)
            if current_stage.onfalse_target:
                target_id = current_stage.onfalse_target
                if target_id in stage_to_page:
                    target_page = stage_to_page[target_id]
                    visited_pages.add(target_page.page_id)
                    if target_id not in visited_stages:
                        to_visit_stages.append(target_id)
                elif target_id not in visited_stages:
                    to_visit_stages.append(target_id)

            # For SubSheet calls, match by processid first (Task 4a),
            # then fall back to page name matching.
            # Per CLAUDE.md, processid is the designed matching mechanism.
            if current_stage.is_subsheet_call:
                target_page: BPPage | None = None

                # Try processid match first
                if current_stage.processid:
                    for page in pages:
                        if (
                            page.page_id == current_stage.processid
                            and page.page_id not in visited_pages
                        ):
                            target_page = page
                            break

                # Fall back to name matching if processid didn't match or isn't available
                if not target_page:
                    target_page_name = current_stage.name
                    for page in pages:
                        if page.name == target_page_name and page.page_id not in visited_pages:
                            target_page = page
                            break

                if target_page:
                    visited_pages.add(target_page.page_id)
                    # Add the page's Start stage to begin traversing it
                    for s in target_page.stages:
                        if s.stage_type == StageType.START:
                            if s.stage_id not in visited_stages:
                                to_visit_stages.append(s.stage_id)
                            break

    # Now build a new list of pages with updated reachable flags
    updated_pages: list[BPPage] = []
    for page in pages:
        is_reachable = page.page_id in visited_pages
        if page.reachable != is_reachable:
            # Create a new page object with updated reachable flag
            updated_pages.append(
                BPPage(
                    page_id=page.page_id,
                    name=page.name,
                    stages=page.stages,
                    is_main=page.is_main,
                    published=page.published,
                    reachable=is_reachable,
                )
            )
        else:
            updated_pages.append(page)

    # Task 4b: return block_recover_map for persistence onto BPStage
    return updated_pages, block_recover_map


def _tag_loader_performer_roles(
    pages: list[BPPage],
    block_recover_map: dict[str, str],
) -> list[BPPage]:
    """Tag pages with Loader/Performer roles based on the 'Get Next Item' split point (Task 4b).

    Hard split point: BP stage `85fbb578` (`Get Next Item`, Main Page) is the exact boundary.
    Pages reachable BEFORE this stage are tagged as "loader".
    Pages reachable FROM this stage onward are tagged as "performer".
    Unreachable pages get no role (remain None).

    Consults block_recover_map (Task 4a Fix A) to extend reachability through
    Block→Recover implicit edges, just like _compute_reachability() does.

    Args:
        pages: List of BPPage objects (already marked with reachability, per Task 4a).
        block_recover_map: Dict mapping Block stage_id → Recover stage_id (from Task 4a).

    Returns:
        New list of BPPage objects with role annotations.
    """
    # Stage ID of the hard split point (from architecture doc §B11)
    # Full UUID of the first "Get Next Item" on Main Page (short form: 85fbb578)
    GET_NEXT_ITEM_STAGE_ID = "85fbb578-f410-4f72-8ca9-58513939bc51"

    # Build a stage ID → page mapping for quick lookup
    stage_to_page: dict[str, BPPage] = {}
    for page in pages:
        for stage in page.stages:
            stage_to_page[stage.stage_id] = page

    # Find the Main Page
    main_page: BPPage | None = None
    get_next_item_stage: BPStage | None = None
    for page in pages:
        if page.is_main:
            main_page = page
            # Look for the Get Next Item stage on Main Page
            for stage in page.stages:
                if stage.stage_id == GET_NEXT_ITEM_STAGE_ID:
                    get_next_item_stage = stage
                    break
            break

    # If we can't find the split point, we can't do role tagging — return unchanged
    if not main_page or not get_next_item_stage:
        # Return pages unchanged if no split point found
        return pages

    # Phase 1: Find all pages reachable BEFORE Get Next Item (Loader pages)
    # Do a BFS from Main Page's Start, stopping AT the split stage (don't traverse beyond it)
    loader_pages: set[str] = set()
    before_visited_stages: set[str] = set()
    to_visit_stages: list[str] = []
    pages_checked_for_blocks_before: set[str] = set()

    # Find the Start stage on Main Page
    start_stage: BPStage | None = None
    for stage in main_page.stages:
        if stage.stage_type == StageType.START:
            start_stage = stage
            break

    if start_stage:
        to_visit_stages.append(start_stage.stage_id)
        loader_pages.add(main_page.page_id)

    while to_visit_stages:
        stage_id = to_visit_stages.pop(0)

        if stage_id in before_visited_stages:
            continue
        before_visited_stages.add(stage_id)

        # Stop traversing if we hit the split point (but still mark the main page as visited)
        if stage_id == GET_NEXT_ITEM_STAGE_ID:
            continue

        if stage_id not in stage_to_page:
            continue

        current_page = stage_to_page[stage_id]
        current_stage: BPStage | None = None

        for s in current_page.stages:
            if s.stage_id == stage_id:
                current_stage = s
                break

        if not current_stage:
            continue

        # Mark current page as loader
        loader_pages.add(current_page.page_id)

        # Task 4a Fix A: When a page becomes reachable, immediately consult its Block→Recover
        # pairs, just like _compute_reachability() does. This ensures exception handlers are
        # traversed even when Block stages have zero independent incoming edges.
        if current_page.page_id not in pages_checked_for_blocks_before:
            pages_checked_for_blocks_before.add(current_page.page_id)
            for block_id, recover_id in block_recover_map.items():
                # Check if this block belongs to the current page
                if (
                    block_id in stage_to_page
                    and stage_to_page[block_id].page_id == current_page.page_id
                    and recover_id not in before_visited_stages
                ):
                    to_visit_stages.append(recover_id)

        # Follow edges, but don't cross into Get Next Item stage
        if (
            current_stage.onsuccess_target
            and current_stage.onsuccess_target != GET_NEXT_ITEM_STAGE_ID
            and current_stage.onsuccess_target not in before_visited_stages
        ):
            to_visit_stages.append(current_stage.onsuccess_target)

        if (
            current_stage.ontrue_target
            and current_stage.ontrue_target != GET_NEXT_ITEM_STAGE_ID
            and current_stage.ontrue_target not in before_visited_stages
        ):
            to_visit_stages.append(current_stage.ontrue_target)

        if (
            current_stage.onfalse_target
            and current_stage.onfalse_target != GET_NEXT_ITEM_STAGE_ID
            and current_stage.onfalse_target not in before_visited_stages
        ):
            to_visit_stages.append(current_stage.onfalse_target)

        # For SubSheet calls, follow to target page
        if current_stage.is_subsheet_call:
            target_page: BPPage | None = None

            # Try processid match first
            if current_stage.processid:
                for page in pages:
                    if page.page_id == current_stage.processid:
                        target_page = page
                        break

            # Fall back to name matching
            if not target_page:
                target_page_name = current_stage.name
                for page in pages:
                    if page.name == target_page_name:
                        target_page = page
                        break

            if target_page:
                loader_pages.add(target_page.page_id)
                # Add the page's Start stage to traverse it
                for s in target_page.stages:
                    if s.stage_type == StageType.START:
                        if s.stage_id not in before_visited_stages:
                            to_visit_stages.append(s.stage_id)
                        break

    # Phase 2: Find all pages reachable FROM Get Next Item onward (Performer pages)
    # Do a BFS starting from Get Next Item and all edges FROM it
    performer_pages: set[str] = set()
    after_visited_stages: set[str] = set()
    to_visit_stages = [GET_NEXT_ITEM_STAGE_ID]
    pages_checked_for_blocks_after: set[str] = set()

    while to_visit_stages:
        stage_id = to_visit_stages.pop(0)

        if stage_id in after_visited_stages:
            continue
        after_visited_stages.add(stage_id)

        if stage_id not in stage_to_page:
            continue

        current_page = stage_to_page[stage_id]
        current_stage: BPStage | None = None

        for s in current_page.stages:
            if s.stage_id == stage_id:
                current_stage = s
                break

        if not current_stage:
            continue

        # Mark current page as performer (even if also in loader, performer takes precedence)
        performer_pages.add(current_page.page_id)

        # Task 4a Fix A: When a page becomes reachable, immediately consult its Block→Recover
        # pairs, just like _compute_reachability() does. This ensures exception handlers are
        # traversed even when Block stages have zero independent incoming edges.
        if current_page.page_id not in pages_checked_for_blocks_after:
            pages_checked_for_blocks_after.add(current_page.page_id)
            for block_id, recover_id in block_recover_map.items():
                # Check if this block belongs to the current page
                if (
                    block_id in stage_to_page
                    and stage_to_page[block_id].page_id == current_page.page_id
                    and recover_id not in after_visited_stages
                ):
                    to_visit_stages.append(recover_id)

        # Follow all edges forward
        if (
            current_stage.onsuccess_target
            and current_stage.onsuccess_target not in after_visited_stages
        ):
            to_visit_stages.append(current_stage.onsuccess_target)

        if current_stage.ontrue_target and current_stage.ontrue_target not in after_visited_stages:
            to_visit_stages.append(current_stage.ontrue_target)

        if (
            current_stage.onfalse_target
            and current_stage.onfalse_target not in after_visited_stages
        ):
            to_visit_stages.append(current_stage.onfalse_target)

        # For SubSheet calls, follow to target page
        if current_stage.is_subsheet_call:
            target_page: BPPage | None = None

            # Try processid match first
            if current_stage.processid:
                for page in pages:
                    if page.page_id == current_stage.processid:
                        target_page = page
                        break

            # Fall back to name matching
            if not target_page:
                target_page_name = current_stage.name
                for page in pages:
                    if page.name == target_page_name:
                        target_page = page
                        break

            if target_page:
                performer_pages.add(target_page.page_id)
                # Add the page's Start stage to traverse it
                for s in target_page.stages:
                    if s.stage_type == StageType.START:
                        if s.stage_id not in after_visited_stages:
                            to_visit_stages.append(s.stage_id)
                        break

    # Build updated pages with role annotations
    # Priority: performer > loader (if a page is reachable from both, it's performer)
    updated_pages: list[BPPage] = []
    for page in pages:
        if page.page_id in performer_pages:
            role = "performer"
        elif page.page_id in loader_pages:
            role = "loader"
        else:
            role = None  # Unreachable or orphaned

        # Create new page object with role (even if None, to be explicit)
        updated_pages.append(
            BPPage(
                page_id=page.page_id,
                name=page.name,
                stages=page.stages,
                is_main=page.is_main,
                published=page.published,
                reachable=page.reachable,
                role=role,
            )
        )

    return updated_pages


# ── Public API ──────────────────────────────────────────────────────────────


def build_ast(raw: RawProcess | MultiArtefactRelease, router: VBORouter | None = None) -> BPProcess:
    """Build a validated BPProcess AST from a raw parsed dict.

    Accepts either a single RawProcess or a MultiArtefactRelease (from Task 3a/3b).
    If a MultiArtefactRelease is provided, extracts the first (main) process.

    Args:
        raw: RawProcess dict from the parser, or MultiArtefactRelease from parse_process().
        router: Optional VBORouter for resolving VBO call-fusion patterns.
            If provided, fusion candidates are checked against vbo_catalogue.yaml.

    Returns:
        Fully validated BPProcess with all stages normalised and reachability
        annotations. Stages with fusion candidates have fused_with, fusion_action,
        and is_vestigial fields populated (if a match is found) or pending_flags
        (if unresolved). Each page is tagged with reachability status.

    Raises:
        ASTBuildError: If any normalisation or validation step
            fails — unmatched pairs, unknown stage types,
            orphan stage IDs, Pydantic validation errors.
    """
    # Handle MultiArtefactRelease from Task 3a/3b
    process_dict: RawProcess
    if isinstance(raw, dict) and "processes" in raw:
        # This is a MultiArtefactRelease
        release = raw  # type: ignore[assignment]
        if not release.get("processes"):
            raise ASTBuildError("MultiArtefactRelease has no processes")
        process_dict = release["processes"][0]
    else:
        # This is a single RawProcess
        process_dict = raw  # type: ignore[assignment]

    pages: list[BPPage] = []
    for raw_page in process_dict["pages"]:
        pages.append(_build_page(raw_page, router))

    # Compute reachability annotations (Task 4a) — must happen before creating BPProcess
    # because BPProcess is frozen. Also returns block_recover_map for Task 4b.
    pages, block_recover_map = _compute_reachability(pages)

    # Task 4b: Persist the Block→Recover pairing onto BLOCK-type stages
    # Since BPStage is mutable (not frozen), we can update in place
    for page in pages:
        for stage in page.stages:
            if stage.stage_type == StageType.BLOCK and stage.stage_id in block_recover_map:
                stage.recover_stage_id = block_recover_map[stage.stage_id]

    # Task 4b: Tag pages with Loader/Performer roles using the reachability graph
    # Pass block_recover_map so role tagging consults the same Block→Recover edges (Task 4a Fix A)
    pages = _tag_loader_performer_roles(pages, block_recover_map)

    # Extract environment variables from MultiArtefactRelease if present
    environment_variables: list[BPEnvironmentVariable] = []
    if isinstance(raw, dict) and "environment_variables" in raw:
        for env_var_dict in raw.get("environment_variables", []):  # type: ignore[union-attr]
            environment_variables.append(
                BPEnvironmentVariable(
                    name=env_var_dict.get("name", ""),
                    data_type=env_var_dict.get("data_type", ""),
                    value=env_var_dict.get("value"),
                )
            )

    try:
        return BPProcess(
            process_id=process_dict["process_id"],
            name=process_dict["name"],
            version=process_dict["version"],
            pages=pages,
            environment_variables=environment_variables,
            source_file=process_dict["source_file"],
        )
    except PydanticValidationError as exc:
        raise ASTBuildError(f"AST validation failed: {exc}") from exc
