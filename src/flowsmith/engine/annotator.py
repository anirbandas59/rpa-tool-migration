"""Stage annotator — transforms BPStage into PAAnnotation.

Walks every stage in a BPProcess and attaches a PAAnnotation
describing the target Power Automate artifact. Coordinates with
mapper modules (VBORouter, DataTypeMapper, MappingConfig) to
produce confidence scores, runtime targets, and review flags.

After annotation, every BPStage has pa_annotation set. The
generator (Phase 6) reads pa_annotation only — never stage_type.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from flowsmith.ast.models import ConfidenceBand, PAAnnotation, ReviewFlag, Runtime, StageType
from flowsmith.exceptions import TransformError
from flowsmith.mapper import DataTypeMapper, MappingConfig, VBORouter, load_rules

if TYPE_CHECKING:
    from pathlib import Path

    from flowsmith.ast.models import BPProcess, BPStage


class StageAnnotator:
    """Annotates every BPStage with a complete PAAnnotation.

    Accepts injected mapper dependencies (MappingConfig,
    VBORouter, DataTypeMapper) and produces PAAnnotation
    objects that fully describe each stage's Power Automate
    target module, action, runtime, and confidence.
    """

    def __init__(
        self,
        config: MappingConfig,
        vbo_router: VBORouter,
        type_mapper: DataTypeMapper,
    ) -> None:
        """Initialise with injected mapper dependencies.

        Args:
            config: Loaded MappingConfig from load_rules().
            vbo_router: Initialised VBORouter instance.
            type_mapper: Initialised DataTypeMapper instance.

        """
        self._config = config
        self._vbo_router = vbo_router
        self._type_mapper = type_mapper

    def annotate_process(self, process: BPProcess) -> BPProcess:
        """Annotate every stage in the process with a PAAnnotation.

        Walks all pages and stages in order. Mutates each
        BPStage in place (BPStage is mutable by design).
        Returns the same BPProcess object for chaining.

        Args:
            process: A BPProcess produced by build_ast().

        Returns:
            The same BPProcess with all stages annotated.

        Raises:
            TransformError: If a stage cannot be annotated and
                the failure is unrecoverable. In practice this
                should never happen — unknown stages fall back
                to MANUAL band with a ReviewFlag.

        """
        for page in process.pages:
            for stage in page.stages:
                try:
                    stage.pa_annotation = self.annotate_stage(stage)
                except Exception as exc:
                    msg = f"Failed to annotate stage {stage.stage_id} ({stage.name}): {exc}"
                    raise TransformError(msg) from exc

        return process

    def annotate_stage(self, stage: BPStage) -> PAAnnotation:
        """Produce a PAAnnotation for a single BPStage.

        Dispatch order:
          1. StageType.ACTION  → _annotate_action()
          2. StageType.DATA    → _annotate_data()
          3. StageType.COLLECTION → _annotate_collection()
          4. StageType.CODE    → _annotate_code()
          5. All others        → _annotate_from_rules()

        Args:
            stage: A BPStage from the AST.

        Returns:
            PAAnnotation with all fields populated.

        """
        if stage.stage_type == StageType.ACTION:
            return self._annotate_action(stage)
        if stage.stage_type == StageType.DATA:
            return self._annotate_data(stage)
        if stage.stage_type == StageType.COLLECTION:
            return self._annotate_collection(stage)
        if stage.stage_type == StageType.CODE:
            return self._annotate_code(stage)
        return self._annotate_from_rules(stage)

    def _annotate_action(self, stage: BPStage) -> PAAnnotation:
        """Annotate ACTION stage (VBO call or subsheet call)."""
        if stage.is_subsheet_call:
            # Subsheet call
            confidence = 0.85
            return PAAnnotation(
                target_type="RunDesktopFlow",
                target_module="SubFlow",
                runtime=Runtime.DESKTOP,
                confidence=confidence,
                band=ConfidenceBand.from_score(confidence),
                params_map=stage.params_map,
                flags=[],
            )

        # VBO call
        decision = self._vbo_router.route_stage(stage)
        if decision is None:
            # Non-VBO ACTION stage (shouldn't happen if parser is correct)
            confidence = 0.0
            return PAAnnotation(
                target_type="",
                target_module="",
                runtime=Runtime.DESKTOP,
                confidence=confidence,
                band=ConfidenceBand.from_score(confidence),
                params_map={},
                flags=[
                    ReviewFlag(
                        stage_id=stage.stage_id,
                        reason="ACTION stage has no VBO metadata and is not a subsheet call",
                        severity="error",
                        suggested_fix="Check XML parsing — ACTION must have _vbo_object or be flagged as subsheet",
                    )
                ],
            )

        # Fill in stage_id on flags (they come with stage_id="")
        flags = [
            ReviewFlag(
                stage_id=stage.stage_id,
                reason=f.reason,
                severity=f.severity,
                suggested_fix=f.suggested_fix,
            )
            for f in decision.review_flags
        ]

        return PAAnnotation(
            target_type=decision.method_name,
            target_module=decision.pa_module,
            runtime=decision.runtime,
            confidence=decision.confidence,
            band=ConfidenceBand.from_score(decision.confidence),
            params_map=stage.params_map,
            flags=flags,
        )

    def _annotate_data(self, stage: BPStage) -> PAAnnotation:
        """Annotate DATA stage (variable declaration)."""
        data_item = stage.data_items[0] if stage.data_items else None
        type_mapping = (
            self._type_mapper.map_data_item(data_item, stage.stage_id) if data_item else None
        )

        confidence = 0.85 if type_mapping and type_mapping.is_known else 0.60

        flags = []
        if type_mapping and type_mapping.review_flag:
            flags.append(
                ReviewFlag(
                    stage_id=stage.stage_id,
                    reason=type_mapping.review_flag.reason,
                    severity=type_mapping.review_flag.severity,
                    suggested_fix=type_mapping.review_flag.suggested_fix,
                )
            )

        params_map = {
            "variable_name": stage.name,
            "variable_type": type_mapping.pad_type if type_mapping else "Text",
            "initial_value": (data_item.initial_value or "" if data_item else ""),
        }

        return PAAnnotation(
            target_type="SetVariable",
            target_module="Variables",
            runtime=Runtime.DESKTOP,
            confidence=confidence,
            band=ConfidenceBand.from_score(confidence),
            params_map=params_map,
            flags=flags,
        )

    def _annotate_collection(self, stage: BPStage) -> PAAnnotation:
        """Annotate COLLECTION stage (data table declaration)."""
        confidence = 0.75
        return PAAnnotation(
            target_type="CreateNewDataTable",
            target_module="Variables",
            runtime=Runtime.DESKTOP,
            confidence=confidence,
            band=ConfidenceBand.from_score(confidence),
            params_map={
                "table_name": stage.name,
                "variable_type": "DataTable",
            },
            flags=[],
        )

    def _annotate_code(self, stage: BPStage) -> PAAnnotation:
        """Annotate CODE stage (always MANUAL band)."""
        confidence = 0.30  # Always MANUAL band
        return PAAnnotation(
            target_type="RunPowershellScript",
            target_module="Scripting",
            runtime=Runtime.DESKTOP,
            confidence=confidence,
            band=ConfidenceBand.from_score(confidence),
            params_map={},
            flags=[
                ReviewFlag(
                    stage_id=stage.stage_id,
                    reason="Code stage contains inline VBScript/VB.NET — "
                    "must be rewritten as PowerShell or PAD script action",
                    severity="error",
                    suggested_fix="Extract code logic and rewrite as "
                    "System.RunPowershellScript action",
                )
            ],
        )

    def _annotate_from_rules(self, stage: BPStage) -> PAAnnotation:
        """Annotate stage using stage_rules.yaml."""
        rule = self._config.get_stage_rule(stage.stage_type.value)

        if rule is None:
            # No rule found
            confidence = 0.0
            return PAAnnotation(
                target_type="",
                target_module="",
                runtime=Runtime.DESKTOP,
                confidence=confidence,
                band=ConfidenceBand.from_score(confidence),
                params_map={},
                flags=[
                    ReviewFlag(
                        stage_id=stage.stage_id,
                        reason=f"No mapping rule for stage type '{stage.stage_type.value}'",
                        severity="error",
                        suggested_fix="Add rule to mapping/stage_rules.yaml",
                    )
                ],
            )

        # Rule found
        flags = []
        if rule.confidence_base < 0.50:
            flags.append(
                ReviewFlag(
                    stage_id=stage.stage_id,
                    reason=f"{stage.stage_type.value} stage has low confidence "
                    f"({rule.confidence_base}) — {rule.notes[:100]}",
                    severity="error",
                    suggested_fix="Review and complete manually",
                )
            )

        return PAAnnotation(
            target_type=rule.pa_target_action,
            target_module=rule.pa_module,
            runtime=rule.runtime,
            confidence=rule.confidence_base,
            band=ConfidenceBand.from_score(rule.confidence_base),
            params_map={},
            flags=flags,
        )


def create_annotator(mapping_dir: Path | None = None) -> StageAnnotator:
    """Create a fully wired StageAnnotator from YAML files.

    Args:
        mapping_dir: Optional override for mapping directory.
                     Defaults to mapping/ relative to cwd.

    Returns:
        StageAnnotator ready to call annotate_process().

    Raises:
        ConfigError: If YAML files cannot be loaded.

    """
    config = load_rules(mapping_dir=mapping_dir)
    vbo_router = VBORouter(config)
    type_mapper = DataTypeMapper()
    return StageAnnotator(config, vbo_router, type_mapper)
