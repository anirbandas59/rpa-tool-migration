"""Process scoring — aggregation of stage confidence into summary statistics.

Transforms annotated BPProcess (with PAAnnotation on every stage) into
structured ProcessScore with per-stage, per-page, and process-level summaries.

These models are consumed by Phase 7 (reporter) for the HTML migration report.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from flowsmith.ast import BPPage, BPProcess, BPStage, ConfidenceBand
from flowsmith.exceptions import TransformError

# ── Summary models ─────────────────────────────────────────────────────────


class StageSummary(BaseModel):
    """Lightweight per-stage summary derived from PAAnnotation.

    Carries confidence score, band, and flag status for rendering in
    per-page sections of the HTML report.
    """

    model_config = ConfigDict(frozen=True)

    stage_id: str = Field(description="Unique stage identifier.")
    stage_type: str = Field(description="StageType.value string (e.g. 'ACTION', 'DECISION').")
    name: str = Field(description="Human-readable stage name.")
    confidence: float = Field(description="Migration confidence score (0.0–1.0).")
    band: ConfidenceBand = Field(description="Confidence band derived from score.")
    flag_count: int = Field(description="Number of ReviewFlags attached to this stage.")
    has_error: bool = Field(description="True if any flag has severity='error'.")
    has_warn: bool = Field(description="True if any flag has severity='warn'.")
    target_type: str = Field(description="PAD action type (e.g. 'Excel.LaunchExcel').")
    target_module: str = Field(description="PAD module name (e.g. 'Excel').")
    runtime: str = Field(description="Runtime.value string ('CLOUD' or 'DESKTOP').")


class PageScore(BaseModel):
    """Aggregate scoring for a single page.

    Tracks mean confidence, band distribution, flags by severity, and
    nested per-stage summaries.
    """

    model_config = ConfigDict(frozen=True)

    page_id: str = Field(description="Unique page identifier.")
    page_name: str = Field(description="Human-readable page name.")
    is_main: bool = Field(description="True if this is the entry-point page.")
    stage_count: int = Field(description="Total stages on this page.")
    mean_confidence: float = Field(description="Mean confidence score of all stages on this page.")
    band: ConfidenceBand = Field(description="Band derived from mean_confidence.")
    band_counts: dict[str, int] = Field(
        description="Distribution of stages by band (band.value -> count)."
    )
    flag_counts: dict[str, int] = Field(
        description="Distribution of flags by severity ('error', 'warn', 'info')."
    )
    stages: list[StageSummary] = Field(
        description="Per-stage summaries for all stages on this page."
    )

    @property
    def error_count(self) -> int:
        """Number of error flags on this page."""
        return self.flag_counts.get("error", 0)

    @property
    def warn_count(self) -> int:
        """Number of warn flags on this page."""
        return self.flag_counts.get("warn", 0)


class ProcessScore(BaseModel):
    """Aggregate scoring for the entire process.

    Tracks mean confidence, band distribution, flags, derived readiness
    metric, and nested per-page summaries.
    """

    model_config = ConfigDict(frozen=True)

    process_id: str = Field(description="Unique process identifier.")
    process_name: str = Field(description="Human-readable process name.")
    source_file: str = Field(description="Path to source .bprelease file.")
    page_count: int = Field(description="Total pages in the process.")
    stage_count: int = Field(description="Total stages across all pages.")
    mean_confidence: float = Field(description="Weighted mean confidence of all stages.")
    band: ConfidenceBand = Field(description="Band derived from mean_confidence.")
    band_counts: dict[str, int] = Field(
        description="Distribution of stages by band (band.value -> count)."
    )
    flag_counts: dict[str, int] = Field(
        description="Distribution of flags by severity ('error', 'warn', 'info')."
    )
    pages: list[PageScore] = Field(description="Per-page summaries for all pages in the process.")
    auto_count: int = Field(description="Stages in AUTO confidence band.")
    spot_check_count: int = Field(description="Stages in SPOT_CHECK band.")
    partial_count: int = Field(description="Stages in PARTIAL band.")
    manual_count: int = Field(description="Stages in MANUAL band.")
    error_flag_count: int = Field(description="Total error-severity flags.")
    warn_flag_count: int = Field(description="Total warn-severity flags.")

    @property
    def migration_readiness(self) -> str:
        """Human-readable assessment of migration readiness.

        Based on manual_count and mean_confidence:
          - No manual stages and mean ≥ 0.85 → "Ready"
          - ≤10 manual and mean ≥ 0.70 → "Minor review needed"
          - ≤50 manual and mean ≥ 0.50 → "Significant review needed"
          - Otherwise → "Major rework required"

        Returns:
            A readiness assessment string for the HTML report.
        """
        if self.manual_count == 0 and self.mean_confidence >= 0.85:
            return "Ready"
        if self.manual_count <= 10 and self.mean_confidence >= 0.70:
            return "Minor review needed"
        if self.manual_count <= 50 and self.mean_confidence >= 0.50:
            return "Significant review needed"
        return "Major rework required"

    @property
    def auto_pct(self) -> float:
        """Percentage of stages in AUTO band."""
        if self.stage_count == 0:
            return 0.0
        return self.auto_count / self.stage_count * 100

    @property
    def manual_pct(self) -> float:
        """Percentage of stages in MANUAL band."""
        if self.stage_count == 0:
            return 0.0
        return self.manual_count / self.stage_count * 100


# ── Scorer ─────────────────────────────────────────────────────────────────


class ProcessScorer:
    """Compute structured scores from an annotated BPProcess.

    All scores are derived from PAAnnotation objects already attached to
    stages by the StageAnnotator. If any stage lacks annotation, raises
    TransformError immediately.
    """

    def score_stage(self, stage: BPStage) -> StageSummary:
        """Produce a StageSummary for a single stage.

        Args:
            stage: An annotated BPStage (must have pa_annotation set).

        Returns:
            StageSummary for this stage.

        Raises:
            TransformError: If stage.pa_annotation is None.
        """
        if stage.pa_annotation is None:
            raise TransformError(
                f"Stage '{stage.stage_id}' has no PAAnnotation — "
                "run StageAnnotator.annotate_process() first"
            )

        ann = stage.pa_annotation
        return StageSummary(
            stage_id=stage.stage_id,
            stage_type=stage.stage_type.value,
            name=stage.name,
            confidence=ann.confidence,
            band=ann.band,
            flag_count=len(ann.flags),
            has_error=any(f.severity == "error" for f in ann.flags),
            has_warn=any(f.severity == "warn" for f in ann.flags),
            target_type=ann.target_type,
            target_module=ann.target_module,
            runtime=ann.runtime.value,
        )

    def score_page(self, page: BPPage) -> PageScore:
        """Compute a PageScore for a single page.

        Args:
            page: A BPPage with all stages annotated.

        Returns:
            PageScore for this page.

        Raises:
            TransformError: If any stage has pa_annotation=None.
        """
        summaries = [self.score_stage(s) for s in page.stages]

        # Compute mean confidence
        mean_conf = 0.0 if not summaries else sum(s.confidence for s in summaries) / len(summaries)

        # Count by band
        band_counts: dict[str, int] = {}
        for s in summaries:
            band_val = s.band.value
            band_counts[band_val] = band_counts.get(band_val, 0) + 1

        # Count by flag severity
        flag_counts: dict[str, int] = {}
        for stage in page.stages:
            if stage.pa_annotation is not None:
                for flag in stage.pa_annotation.flags:
                    flag_counts[flag.severity] = flag_counts.get(flag.severity, 0) + 1

        return PageScore(
            page_id=page.page_id,
            page_name=page.name,
            is_main=page.is_main,
            stage_count=len(page.stages),
            mean_confidence=mean_conf,
            band=ConfidenceBand.from_score(mean_conf),
            band_counts=band_counts,
            flag_counts=flag_counts,
            stages=summaries,
        )

    def score_process(self, process: BPProcess) -> ProcessScore:
        """Compute a full ProcessScore from an annotated BPProcess.

        The process must have been through StageAnnotator.annotate_process()
        — every stage must have pa_annotation set.

        Args:
            process: Fully annotated BPProcess.

        Returns:
            ProcessScore with all aggregations computed.

        Raises:
            TransformError: If any stage has pa_annotation=None.
        """
        # Validate all stages are annotated first
        for page in process.pages:
            for stage in page.stages:
                if stage.pa_annotation is None:
                    raise TransformError(
                        f"Stage '{stage.stage_id}' has no PAAnnotation — "
                        "run StageAnnotator.annotate_process() first"
                    )

        # Score all pages
        page_scores = [self.score_page(p) for p in process.pages]

        # Aggregate across all pages
        total_stage_count = sum(p.stage_count for p in page_scores)
        weighted_sum = sum(p.mean_confidence * p.stage_count for p in page_scores)
        weighted_mean = 0.0 if total_stage_count == 0 else weighted_sum / total_stage_count

        # Aggregate band counts
        band_counts: dict[str, int] = {}
        for p in page_scores:
            for band_val, count in p.band_counts.items():
                band_counts[band_val] = band_counts.get(band_val, 0) + count

        # Aggregate flag counts
        flag_counts: dict[str, int] = {}
        for p in page_scores:
            for severity, count in p.flag_counts.items():
                flag_counts[severity] = flag_counts.get(severity, 0) + count

        # Count by specific bands
        auto_count = band_counts.get("AUTO", 0)
        spot_check_count = band_counts.get("SPOT_CHECK", 0)
        partial_count = band_counts.get("PARTIAL", 0)
        manual_count = band_counts.get("MANUAL", 0)

        error_flag_count = flag_counts.get("error", 0)
        warn_flag_count = flag_counts.get("warn", 0)

        return ProcessScore(
            process_id=process.process_id,
            process_name=process.name,
            source_file=process.source_file,
            page_count=len(process.pages),
            stage_count=total_stage_count,
            mean_confidence=weighted_mean,
            band=ConfidenceBand.from_score(weighted_mean),
            band_counts=band_counts,
            flag_counts=flag_counts,
            pages=page_scores,
            auto_count=auto_count,
            spot_check_count=spot_check_count,
            partial_count=partial_count,
            manual_count=manual_count,
            error_flag_count=error_flag_count,
            warn_flag_count=warn_flag_count,
        )
