"""Review flag index — flat, queryable structure for all ReviewFlags in a process.

After annotation, the process tree contains 538+ ReviewFlags scattered across
6,576 stages. The reporter needs to surface these in a structured, filterable way.

FlagIndex builds a single flat structure that collects all flags, enriches them
with context (page name, stage type, VBO name), and exposes query methods.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from flowsmith.exceptions import TransformError

if TYPE_CHECKING:
    from flowsmith.ast import BPProcess


class FlagEntry(BaseModel):
    """A single enriched ReviewFlag with full context.

    Combines the ReviewFlag data with page and stage context that helps
    the reporter understand where the flag came from and what it affects.
    """

    model_config = ConfigDict(frozen=True)

    stage_id: str = Field(description="ID of the BPStage this flag is attached to.")
    stage_type: str = Field(description="StageType.value (e.g., 'CODE', 'ACTION').")
    stage_name: str = Field(description="Human-readable name of the stage.")
    page_id: str = Field(description="ID of the page containing the stage.")
    page_name: str = Field(description="Human-readable name of the page.")
    is_main_page: bool = Field(description="True if this is the Main entry-point page.")
    severity: str = Field(description="Severity level: 'info', 'warn', or 'error'.")
    reason: str = Field(description="Human-readable explanation of the concern.")
    suggested_fix: str = Field(description="Recommended action for the reviewer.")
    vbo_name: str = Field(
        description="VBO object name from params_map._vbo_object, empty string if not a VBO call."
    )
    target_module: str = Field(description="PA module name (e.g., 'Excel', 'File').")
    confidence: float = Field(description="Migration confidence score in range 0.0–1.0.")


class FlagIndex(BaseModel):
    """Flat, queryable index of all ReviewFlags in a process.

    Provides fast lookups and filtering by severity, page, stage type, VBO name.
    All query methods return new lists — FlagIndex is immutable.
    """

    model_config = ConfigDict(frozen=True)

    process_id: str = Field(description="ID of the process.")
    process_name: str = Field(description="Human-readable name of the process.")
    entries: list[FlagEntry] = Field(description="All enriched flag entries.")

    def by_severity(self, severity: str) -> list[FlagEntry]:
        """Return all entries with the given severity.

        Args:
            severity: One of 'info', 'warn', 'error'.

        Returns:
            List of matching FlagEntry objects, in original order.
        """
        return [e for e in self.entries if e.severity == severity]

    def by_page(self, page_id: str) -> list[FlagEntry]:
        """Return all entries for the given page_id.

        Args:
            page_id: The page_id to filter by.

        Returns:
            List of matching FlagEntry objects, in original order.
        """
        return [e for e in self.entries if e.page_id == page_id]

    def by_stage_type(self, stage_type: str) -> list[FlagEntry]:
        """Return all entries for the given stage_type string.

        Args:
            stage_type: StageType value string (e.g., 'CODE', 'ACTION').

        Returns:
            List of matching FlagEntry objects, in original order.
        """
        return [e for e in self.entries if e.stage_type == stage_type]

    def by_vbo(self, vbo_name: str) -> list[FlagEntry]:
        """Return all entries where vbo_name matches exactly.

        Args:
            vbo_name: The VBO name to filter by.

        Returns:
            List of matching FlagEntry objects, in original order.
        """
        return [e for e in self.entries if e.vbo_name == vbo_name]

    def errors(self) -> list[FlagEntry]:
        """Shorthand for by_severity('error').

        Returns:
            List of all error severity FlagEntry objects.
        """
        return self.by_severity("error")

    def warnings(self) -> list[FlagEntry]:
        """Shorthand for by_severity('warn').

        Returns:
            List of all warn severity FlagEntry objects.
        """
        return self.by_severity("warn")

    def summary_by_page(self) -> dict[str, int]:
        """Return dict of page_name → flag count, sorted by count descending.

        Returns:
            Dict mapping page names to flag counts, sorted descending by count.
        """
        counts: dict[str, int] = {}
        for entry in self.entries:
            counts[entry.page_name] = counts.get(entry.page_name, 0) + 1
        return dict(sorted(counts.items(), key=lambda x: x[1], reverse=True))

    def summary_by_stage_type(self) -> dict[str, int]:
        """Return dict of stage_type → flag count, sorted by count descending.

        Returns:
            Dict mapping stage types to flag counts, sorted descending by count.
        """
        counts: dict[str, int] = {}
        for entry in self.entries:
            counts[entry.stage_type] = counts.get(entry.stage_type, 0) + 1
        return dict(sorted(counts.items(), key=lambda x: x[1], reverse=True))

    def summary_by_severity(self) -> dict[str, int]:
        """Return dict of severity → flag count.

        Returns:
            Dict mapping severity levels to flag counts.
        """
        counts: dict[str, int] = {}
        for entry in self.entries:
            counts[entry.severity] = counts.get(entry.severity, 0) + 1
        return counts

    def summary_by_vbo(self) -> dict[str, int]:
        """Return dict of vbo_name → flag count for entries where vbo_name is not empty.

        Returns VBOs sorted by flag count descending.

        Returns:
            Dict mapping VBO names to flag counts, sorted descending by count.
        """
        counts: dict[str, int] = {}
        for entry in self.entries:
            if entry.vbo_name:  # Only non-empty VBO names
                counts[entry.vbo_name] = counts.get(entry.vbo_name, 0) + 1
        return dict(sorted(counts.items(), key=lambda x: x[1], reverse=True))

    def checklist(self) -> list[FlagEntry]:
        """Return all entries sorted for rendering a review checklist.

        Sorted by:
          1. severity (error first, then warn, then info)
          2. page_name alphabetically
          3. stage_name alphabetically

        Returns:
            List of FlagEntry objects in checklist sort order.
        """
        severity_order = {"error": 0, "warn": 1, "info": 2}
        return sorted(
            self.entries,
            key=lambda e: (
                severity_order.get(e.severity, 999),
                e.page_name,
                e.stage_name,
            ),
        )


class FlagIndexBuilder:
    """Builder for FlagIndex from a fully annotated BPProcess."""

    def __init__(self) -> None:
        """Initialize the builder (no dependencies)."""

    def build(self, process: BPProcess) -> FlagIndex:
        """Build a FlagIndex from a fully annotated BPProcess.

        Walks all pages and stages, collects every ReviewFlag from every
        pa_annotation, and enriches each with page/stage context.

        Args:
            process: Fully annotated BPProcess — every stage must have
                     pa_annotation set.

        Returns:
            FlagIndex with all flags enriched and indexed.

        Raises:
            TransformError: If any stage has pa_annotation=None.
        """
        entries: list[FlagEntry] = []

        for page in process.pages:
            for stage in page.stages:
                if stage.pa_annotation is None:
                    raise TransformError(f"Stage '{stage.stage_id}' has no PAAnnotation")

                ann = stage.pa_annotation
                vbo_name = stage.params_map.get("_vbo_object", "")

                for flag in ann.flags:
                    entries.append(
                        FlagEntry(
                            stage_id=flag.stage_id,
                            stage_type=stage.stage_type.value,
                            stage_name=stage.name,
                            page_id=page.page_id,
                            page_name=page.name,
                            is_main_page=page.is_main,
                            severity=flag.severity,
                            reason=flag.reason,
                            suggested_fix=flag.suggested_fix,
                            vbo_name=vbo_name,
                            target_module=ann.target_module,
                            confidence=ann.confidence,
                        )
                    )

        return FlagIndex(
            process_id=process.process_id,
            process_name=process.name,
            entries=entries,
        )
