"""Canonical intermediate representation (AST) for a Blue Prism process.

These Pydantic v2 models are the single source of truth shared across all
Flowsmith phases:
  - Phase 2 (parser)  — populates BPProcess / BPPage / BPStage
  - Phase 5 (engine)  — attaches PAAnnotation to each BPStage
  - Phase 6 (generator) — reads the annotated tree to emit .robin / JSON

Immutability: all models are frozen EXCEPT BPStage, which must remain
mutable so the engine can attach pa_annotation after construction.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from flowsmith.exceptions import ASTBuildError

# ── Enums ──────────────────────────────────────────────────────────────────


class StageType(StrEnum):
    """The 17 canonical stage types used in the Flowsmith AST.

    BLOCK and EXCEPTION are distinct:
      BLOCK     = scope boundary (try/catch wrapper)
      EXCEPTION = throw stage
    """

    START = "START"
    END = "END"
    ACTION = "ACTION"
    DECISION = "DECISION"
    CALCULATION = "CALCULATION"
    CODE = "CODE"
    WAIT = "WAIT"
    NAVIGATE = "NAVIGATE"
    READ = "READ"
    WRITE = "WRITE"
    LOOP = "LOOP"
    EXCEPTION = "EXCEPTION"
    RECOVER = "RECOVER"
    RESUME = "RESUME"
    BLOCK = "BLOCK"
    COLLECTION = "COLLECTION"
    DATA = "DATA"


class Runtime(StrEnum):
    """Target Power Automate runtime for a generated action."""

    CLOUD = "CLOUD"
    DESKTOP = "DESKTOP"


class ConfidenceBand(StrEnum):
    """Migration confidence bands as defined in CLAUDE.md.

    Maps a 0.0–1.0 confidence score to a named band that controls the
    verbosity and annotation style of generated output.
    """

    AUTO = "AUTO"
    SPOT_CHECK = "SPOT_CHECK"
    PARTIAL = "PARTIAL"
    MANUAL = "MANUAL"

    @classmethod
    def from_score(cls, score: float) -> ConfidenceBand:
        """Derive a confidence band from a numeric score.

        Args:
            score: Float in range 0.0–1.0.

        Returns:
            ConfidenceBand matching the score threshold.
        """
        if score >= 0.90:
            return cls.AUTO
        if score >= 0.70:
            return cls.SPOT_CHECK
        if score >= 0.50:
            return cls.PARTIAL
        return cls.MANUAL


# ── Leaf models (no cross-references) ─────────────────────────────────────


class ReviewFlag(BaseModel):
    """A single reviewer note attached to a migration decision.

    Flags are collected on PAAnnotation and surfaced in the HTML report.
    """

    model_config = ConfigDict(frozen=True)

    stage_id: str = Field(description="ID of the BPStage this flag is attached to.")
    reason: str = Field(description="Human-readable explanation of the concern.")
    severity: Literal["info", "warn", "error"] = Field(
        description="How urgently this flag needs human attention."
    )
    suggested_fix: str = Field(description="Recommended action for the reviewer.")


class PAAnnotation(BaseModel):
    """The Power Automate mapping annotation for a single BPStage.

    Produced by the transformation engine (Phase 5) and consumed by the
    code generator (Phase 6).  band is always derived from confidence —
    they must never be out of sync.
    """

    model_config = ConfigDict(frozen=True)

    target_type: str = Field(
        description="PAD action or Cloud Flow action type (e.g. 'Excel.LaunchExcel')."
    )
    target_module: str = Field(description="PAD module name (e.g. 'Excel', 'File', 'Web').")
    runtime: Runtime = Field(description="Whether to emit CLOUD or DESKTOP output.")
    params_map: dict[str, str] = Field(
        description="BP parameter name -> PA parameter name mapping."
    )
    confidence: float = Field(description="Migration confidence score in range 0.0–1.0.")
    band: ConfidenceBand = Field(
        description="Confidence band derived from the score — must match from_score(confidence)."
    )
    flags: list[ReviewFlag] = Field(
        default_factory=list,
        description="Reviewer flags attached to this annotation.",
    )

    @field_validator("confidence")
    @classmethod
    def confidence_in_range(cls, v: float) -> float:
        """Validate confidence is within [0.0, 1.0].

        Args:
            v: The confidence value to validate.

        Returns:
            The validated confidence value.

        Raises:
            ValueError: If confidence is outside [0.0, 1.0].
        """
        if not (0.0 <= v <= 1.0):
            raise ValueError(f"confidence must be in [0.0, 1.0], got {v}")
        return v

    @model_validator(mode="after")
    def band_matches_confidence(self) -> PAAnnotation:
        """Enforce that band always equals ConfidenceBand.from_score(confidence).

        Returns:
            Self, unchanged if valid.

        Raises:
            ValueError: If band is inconsistent with confidence.
        """
        expected = ConfidenceBand.from_score(self.confidence)
        if self.band != expected:
            raise ValueError(
                f"band {self.band!r} is inconsistent with confidence {self.confidence}: "
                f"expected {expected!r}"
            )
        return self


# ── Stage-level models ─────────────────────────────────────────────────────


class BPDataItem(BaseModel):
    """A single data item (variable) declared on or associated with a stage."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(description="Variable name as it appears in the BP XML.")
    data_type: str = Field(
        description="Raw BP type string (e.g. 'text', 'number', 'flag', 'collection')."
    )
    initial_value: str | None = Field(
        default=None,
        description="Initial value expression, or None if not set.",
    )
    is_input: bool = Field(
        default=False,
        description="True if this data item is a stage input parameter.",
    )
    is_output: bool = Field(
        default=False,
        description="True if this data item is a stage output parameter.",
    )


class BPStage(BaseModel):
    """A single executable stage within a Blue Prism page.

    Intentionally NOT frozen — the engine (Phase 5) must be able to set
    pa_annotation after the parser constructs the object.
    """

    model_config = ConfigDict(frozen=False)

    stage_id: str = Field(description="Unique stage identifier from the BP XML.")
    stage_type: StageType = Field(description="Canonical AST stage type.")
    name: str = Field(description="Human-readable stage name from the BP XML.")
    data_items: list[BPDataItem] = Field(
        default_factory=list,
        description="Variables declared on or associated with this stage.",
    )
    exception_handler_id: str | None = Field(
        default=None,
        description="Stage ID of the Recover stage that handles exceptions from this stage.",
    )
    exception_type: str | None = Field(
        default=None,
        description=(
            "Exception type string, only populated for EXCEPTION stages "
            "(e.g. 'Business Exception', 'System Exception')."
        ),
    )
    pair_id: str | None = Field(
        default=None,
        description=(
            "For paired stages (WAIT start/end, LOOP start/end, BLOCK open/close): "
            "the stage_id of the partner node."
        ),
    )
    is_subsheet_call: bool = Field(
        default=False,
        description="True when a SUBSHEET BP stage has been normalised to ACTION.",
    )
    params_map: dict[str, str] = Field(
        default_factory=dict,
        description="Stage-level BP parameter name -> PA parameter name mapping.",
    )
    pa_annotation: PAAnnotation | None = Field(
        default=None,
        description="Power Automate annotation set by the engine in Phase 5.",
    )


# ── Page and process models ────────────────────────────────────────────────


class BPPage(BaseModel):
    """A single page (sub-sheet) within a Blue Prism process."""

    model_config = ConfigDict(frozen=True)

    page_id: str = Field(description="Unique page identifier from the BP XML.")
    name: str = Field(description="Page name (e.g. 'Main Page', 'Initialise').")
    stages: list[BPStage] = Field(
        default_factory=list,
        description="Ordered list of stages on this page.",
    )
    is_main: bool = Field(
        default=False,
        description="True if this is the process entry-point (Main) page.",
    )


class BPProcess(BaseModel):
    """The root node of the Flowsmith AST, representing one Blue Prism process."""

    model_config = ConfigDict(frozen=True)

    process_id: str = Field(description="Unique process identifier from the BP XML.")
    name: str = Field(description="Process name as it appears in Blue Prism.")
    version: str = Field(description="Process version string from the BP XML.")
    pages: list[BPPage] = Field(
        default_factory=list,
        description="All pages (sub-sheets) in the process.",
    )
    source_file: str = Field(description="Absolute or relative path to the source .bprelease file.")

    def get_stage(self, stage_id: str) -> BPStage:
        """Find a stage by its ID, searching all pages.

        Args:
            stage_id: The stage_id to search for.

        Returns:
            The matching BPStage.

        Raises:
            ASTBuildError: If no stage with the given ID exists in any page.
        """
        for page in self.pages:
            for stage in page.stages:
                if stage.stage_id == stage_id:
                    return stage
        raise ASTBuildError(
            f"Stage '{stage_id}' not found in process '{self.name}' "
            f"(searched {sum(len(p.stages) for p in self.pages)} stages across "
            f"{len(self.pages)} page(s))"
        )
