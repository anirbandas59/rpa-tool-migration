"""Report models — the presentation-ready shape of a coverage report.

These models carry only values already computed by ``engine.scorer`` (bands,
confidence, counts) and ``engine.flag_index`` (ReviewFlags + page/stage context),
plus the BP stage context a developer needs to act on a flag without opening the
BP source (narrative, typed inputs/outputs, VBO/method). Nothing here re-scores or
re-flags a stage — see ``reporter.coverage`` for how they are populated.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ParamDetail(BaseModel):
    """One BP data item attached to a stage, with direction, type and binding."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(description="BP parameter / data item name.")
    data_type: str = Field(description="Raw BP data type (e.g. 'text', 'number', 'collection').")
    direction: str = Field(description="'input', 'output', or 'declared' (Data/Collection item).")
    binding: str = Field(
        default="",
        description=(
            "What the parameter is bound to in BP: the input expression, the output "
            "target data item, or the initial value of a declared item. Empty if unbound."
        ),
    )


class StageDetail(BaseModel):
    """Hand-off-ready context for a single BP stage.

    Everything a developer (or a later curation pass) needs to act on a stage
    without re-reading the BP XML or the generated ``.robin``/JSON.
    """

    model_config = ConfigDict(frozen=True)

    stage_id: str = Field(description="BP stage ID.")
    stage_name: str = Field(description="BP stage name.")
    stage_type: str = Field(description="Canonical AST StageType value.")
    page_id: str = Field(description="ID of the BP page containing the stage.")
    page_name: str = Field(description="Name of the BP page containing the stage.")
    page_role: str = Field(description="Loader/Performer role of the page, '' if untagged.")
    is_main_page: bool = Field(description="True if the page is the process entry point.")
    narrative: str = Field(default="", description="BP stage narrative, '' if none.")
    params: list[ParamDetail] = Field(
        default_factory=list, description="Typed inputs/outputs/declared items of the stage."
    )
    vbo_object: str = Field(default="", description="BP VBO object name, '' if not a VBO call.")
    vbo_action: str = Field(default="", description="BP VBO action/method, '' if not a VBO call.")
    called_page: str = Field(
        default="",
        description="Name of the page a SubSheet/Process call targets, '' if not a call.",
    )
    expression: str = Field(
        default="",
        description="Decision expression or exception detail carried by the stage, if any.",
    )
    exception_type: str = Field(default="", description="Exception type for EXCEPTION stages.")
    code_text: str = Field(default="", description="Code body for CODE stages, '' otherwise.")
    fused_with: list[str] = Field(
        default_factory=list, description="Stage IDs fused with this stage (Task 1b)."
    )
    fusion_action: str = Field(default="", description="Fused PAD action name, '' if none.")
    is_vestigial: bool = Field(
        default=False, description="True if the stage emits nothing standalone (fusion)."
    )
    target_type: str = Field(description="PAD/Cloud action the engine mapped the stage to.")
    target_module: str = Field(description="PAD module / connector the engine mapped to.")
    runtime: str = Field(description="'CLOUD' or 'DESKTOP'.")
    confidence: float = Field(description="Engine confidence score (0.0-1.0).")
    band: str = Field(description="ConfidenceBand value derived by the engine.")
    flag_count: int = Field(description="Number of ReviewFlags the engine attached.")
    pending_flag_reasons: list[str] = Field(
        default_factory=list,
        description=(
            "Reasons of AST-build ReviewFlags still sitting in BPStage.pending_flags "
            "(never transferred onto pa_annotation.flags). Surfaced so they are not lost."
        ),
    )


class FlagDetail(BaseModel):
    """A single engine ReviewFlag joined with its full stage context."""

    model_config = ConfigDict(frozen=True)

    severity: str = Field(description="'error', 'warn', or 'info'.")
    reason: str = Field(description="Why the engine flagged the stage.")
    suggested_fix: str = Field(description="Engine's suggested fix, '' if none.")
    stage: StageDetail = Field(description="Hand-off context for the flagged stage.")


class BandSummary(BaseModel):
    """Count and share of stages in one confidence band."""

    model_config = ConfigDict(frozen=True)

    band: str = Field(description="ConfidenceBand value.")
    count: int = Field(description="Stages in this band.")
    percent: float = Field(description="Share of all stages, 0-100.")
    stages: list[StageDetail] = Field(
        default_factory=list, description="Every stage in this band, in page order."
    )


class PageSummary(BaseModel):
    """Per-page roll-up, taken from engine.scorer.PageScore."""

    model_config = ConfigDict(frozen=True)

    page_id: str = Field(description="BP page ID.")
    page_name: str = Field(description="BP page name.")
    role: str = Field(description="Loader/Performer role, '' if untagged.")
    is_main: bool = Field(description="True for the entry-point page.")
    reachable: bool = Field(description="False for orphan pages (Task 4a).")
    stage_count: int = Field(description="Stages on the page.")
    mean_confidence: float = Field(description="Mean stage confidence on the page.")
    band: str = Field(description="Band of the page's mean confidence.")
    band_counts: dict[str, int] = Field(description="Band value -> stage count.")
    flag_counts: dict[str, int] = Field(description="Severity -> flag count.")


class CoverageReport(BaseModel):
    """The complete developer-facing coverage report for one process."""

    model_config = ConfigDict(frozen=True)

    process_id: str = Field(description="BP process ID.")
    process_name: str = Field(description="BP process name.")
    source_file: str = Field(description="Source .bprelease path recorded in the AST.")
    input_path: str = Field(description="Artefact the report was built from.")
    page_count: int = Field(description="Pages in the process.")
    stage_count: int = Field(description="Stages across all pages.")
    mean_confidence: float = Field(description="Stage-weighted mean confidence.")
    overall_band: str = Field(description="Band of the mean confidence.")
    readiness: str = Field(description="ProcessScore.migration_readiness.")
    bands: list[BandSummary] = Field(description="One entry per band, AUTO..MANUAL order.")
    flag_counts: dict[str, int] = Field(description="Severity -> flag count (from the scorer).")
    flag_total: int = Field(description="Total ReviewFlags (from the flag index).")
    flags: list[FlagDetail] = Field(description="Every ReviewFlag in checklist order.")
    unflagged_attention: list[StageDetail] = Field(
        description=(
            "PARTIAL/MANUAL stages the engine attached no ReviewFlag to — still need a "
            "developer, so listed explicitly rather than hidden inside the band tables."
        )
    )
    pages: list[PageSummary] = Field(description="Per-page roll-ups in process order.")
