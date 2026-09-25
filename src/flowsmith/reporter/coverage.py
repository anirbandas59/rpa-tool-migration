"""Coverage report builder - present engine scores and flags as a CoverageReport.

Consumes, never recomputes:
  * ``engine.scorer.ProcessScorer`` - per-stage band/confidence, band counts,
    per-page roll-ups, flag counts by severity, migration readiness.
  * ``engine.flag_index.FlagIndexBuilder`` - every ReviewFlag with page/stage
    context, in ``FlagIndex.checklist()`` order.

The only thing added here is BP stage context read straight off the AST
(narrative, typed inputs/outputs, VBO object/action, called page) so each
flag entry is hand-off-ready (Task 8 "Do" step 2).
"""

from __future__ import annotations

from flowsmith.ast import BPPage, BPProcess, BPStage, ConfidenceBand
from flowsmith.engine import FlagIndex, FlagIndexBuilder, ProcessScore, ProcessScorer
from flowsmith.exceptions import TransformError
from flowsmith.reporter.models import (
    BandSummary,
    CoverageReport,
    FlagDetail,
    PageSummary,
    ParamDetail,
    StageDetail,
)

# Keys the parser stores in params_map for VBO metadata rather than BP parameters.
_VBO_OBJECT_KEY = "_vbo_object"
_VBO_ACTION_KEY = "_vbo_action"

# Bands that still need a developer (CLAUDE.md confidence-band table: PARTIAL is
# "Scaffold + TODO", MANUAL is "Stub only").
_ATTENTION_BANDS = frozenset({ConfidenceBand.PARTIAL.value, ConfidenceBand.MANUAL.value})


def _param(name: str, direction: str, binding: str | None, data_type: str) -> ParamDetail:
    """Build a ParamDetail, normalising a missing binding to ''.

    Args:
        name: Parameter name.
        direction: 'input', 'output' or 'declared'.
        binding: Bound expression / output target / initial value, or None.
        data_type: BP data type string.

    Returns:
        The ParamDetail.
    """
    return ParamDetail(name=name, data_type=data_type, direction=direction, binding=binding or "")


def _stage_params(stage: BPStage) -> list[ParamDetail]:
    """Collect a stage's typed inputs, outputs and declared data items.

    Args:
        stage: The BP stage.

    Returns:
        Data items first (with their BP types), then any bound parameter with
        no matching data item (its type reported as 'unknown').
    """
    params: list[ParamDetail] = []
    seen_inputs: set[str] = set()
    seen_outputs: set[str] = set()
    for item in stage.data_items:
        if item.is_input:
            seen_inputs.add(item.name)
            binding = stage.params_map.get(item.name, stage.inputs_stage_map.get(item.name))
            params.append(_param(item.name, "input", binding, item.data_type))
        elif item.is_output:
            seen_outputs.add(item.name)
            binding = stage.outputs_stage_map.get(item.name)
            params.append(_param(item.name, "output", binding, item.data_type))
        else:
            params.append(_param(item.name, "declared", item.initial_value, item.data_type))

    for name, expr in stage.params_map.items():
        if not name.startswith("_") and name not in seen_inputs:
            params.append(_param(name, "input", expr, "unknown"))
    for name, target in stage.outputs_stage_map.items():
        if name not in seen_outputs:
            params.append(_param(name, "output", target, "unknown"))
    return params


def _called_page(stage: BPStage, page_names: dict[str, str]) -> str:
    """Describe the target of a SubSheet/Process call stage.

    Args:
        stage: The BP stage.
        page_names: page_id -> page name for the process.

    Returns:
        Called page name, an external-process marker, or '' for non-call stages.
    """
    if not (stage.is_subsheet_call or stage.is_process_call):
        return ""
    if stage.processid and stage.processid in page_names:
        return page_names[stage.processid]
    if stage.is_process_call:
        return f"external BP process {stage.processid or '(no processid)'}"
    return f"unresolved page {stage.processid or '(no processid)'}"


def build_stage_detail(stage: BPStage, page: BPPage, page_names: dict[str, str]) -> StageDetail:
    """Build hand-off-ready context for one annotated stage.

    Args:
        stage: An annotated BP stage (``pa_annotation`` set).
        page: The page containing the stage.
        page_names: page_id -> page name, to resolve SubSheet call targets.

    Returns:
        StageDetail for the stage.

    Raises:
        TransformError: If the stage has no PAAnnotation.
    """
    ann = stage.pa_annotation
    if ann is None:
        raise TransformError(
            f"Stage '{stage.stage_id}' has no PAAnnotation - "
            "run StageAnnotator.annotate_process() first"
        )
    return StageDetail(
        stage_id=stage.stage_id,
        stage_name=stage.name,
        stage_type=stage.stage_type.value,
        page_id=page.page_id,
        page_name=page.name,
        page_role=page.role or "",
        is_main_page=page.is_main,
        narrative=stage.narrative or "",
        params=_stage_params(stage),
        vbo_object=stage.params_map.get(_VBO_OBJECT_KEY, ""),
        vbo_action=stage.params_map.get(_VBO_ACTION_KEY, ""),
        called_page=_called_page(stage, page_names),
        expression=stage.decision_expression or stage.exception_detail or "",
        exception_type=stage.exception_type or "",
        code_text=stage.code_text or "",
        fused_with=list(stage.fused_with),
        fusion_action=stage.fusion_action or "",
        is_vestigial=stage.is_vestigial,
        target_type=ann.target_type,
        target_module=ann.target_module,
        runtime=ann.runtime.value,
        confidence=ann.confidence,
        band=ann.band.value,
        flag_count=len(ann.flags),
        pending_flag_reasons=[f.reason for f in stage.pending_flags],
    )


def _check_consistency(score: ProcessScore, index: FlagIndex) -> None:
    """Verify the scorer's and flag index's totals agree before presenting them.

    Args:
        score: ProcessScore from ProcessScorer.
        index: FlagIndex from FlagIndexBuilder.

    Raises:
        TransformError: If band counts do not sum to the stage total, or the
            scorer's flag counts disagree with the flag index.
    """
    band_total = sum(score.band_counts.values())
    if band_total != score.stage_count:
        raise TransformError(
            f"Band counts sum to {band_total} but the process has {score.stage_count} stages"
        )
    index_counts = index.summary_by_severity()
    if index_counts != score.flag_counts:
        raise TransformError(
            f"Scorer flag counts {score.flag_counts} disagree with flag index {index_counts}"
        )


def build_coverage_report(process: BPProcess, input_path: str = "") -> CoverageReport:
    """Build the developer-facing coverage report for an annotated process.

    Args:
        process: BPProcess after ``engine.annotate_process()``.
        input_path: Artefact the process was loaded from, shown in the report.

    Returns:
        CoverageReport with band breakdown, every ReviewFlag with full stage
        context, unflagged PARTIAL/MANUAL stages, and per-page roll-ups.

    Raises:
        TransformError: If any stage is unannotated, or the engine's scorer and
            flag index disagree.
    """
    score = ProcessScorer().score_process(process)
    index = FlagIndexBuilder().build(process)
    _check_consistency(score, index)

    page_names = {page.page_id: page.name for page in process.pages}
    details: dict[tuple[str, str], StageDetail] = {}
    ordered: list[StageDetail] = []
    for page in process.pages:
        for stage in page.stages:
            detail = build_stage_detail(stage, page, page_names)
            details[(page.page_id, stage.stage_id)] = detail
            ordered.append(detail)

    bands = [
        BandSummary(
            band=band.value,
            count=score.band_counts.get(band.value, 0),
            percent=(
                score.band_counts.get(band.value, 0) / score.stage_count * 100
                if score.stage_count
                else 0.0
            ),
            stages=[d for d in ordered if d.band == band.value],
        )
        for band in ConfidenceBand
    ]

    flags: list[FlagDetail] = []
    for entry in index.checklist():
        stage_detail = details.get((entry.page_id, entry.stage_id))
        if stage_detail is None:
            raise TransformError(
                f"ReviewFlag on page '{entry.page_name}' names stage '{entry.stage_id}', "
                "which is not on that page"
            )
        flags.append(
            FlagDetail(
                severity=entry.severity,
                reason=entry.reason,
                suggested_fix=entry.suggested_fix,
                stage=stage_detail,
            )
        )

    unflagged = [d for d in ordered if d.band in _ATTENTION_BANDS and d.flag_count == 0]

    pages_by_id = {page.page_id: page for page in process.pages}
    pages = [
        PageSummary(
            page_id=ps.page_id,
            page_name=ps.page_name,
            role=pages_by_id[ps.page_id].role or "",
            is_main=ps.is_main,
            reachable=pages_by_id[ps.page_id].reachable,
            stage_count=ps.stage_count,
            mean_confidence=ps.mean_confidence,
            band=ps.band.value,
            band_counts=ps.band_counts,
            flag_counts=ps.flag_counts,
        )
        for ps in score.pages
    ]

    return CoverageReport(
        process_id=score.process_id,
        process_name=score.process_name,
        source_file=score.source_file,
        input_path=input_path,
        page_count=score.page_count,
        stage_count=score.stage_count,
        mean_confidence=score.mean_confidence,
        overall_band=score.band.value,
        readiness=score.migration_readiness,
        bands=bands,
        flag_counts=score.flag_counts,
        flag_total=len(index.entries),
        flags=flags,
        unflagged_attention=unflagged,
        pages=pages,
    )
