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
from flowsmith.exceptions import ConfigError, TransformError
from flowsmith.mapper import DataTypeMapper, MappingConfig, VBORouter, load_rules

if TYPE_CHECKING:
    from pathlib import Path

    from flowsmith.ast.models import BPProcess, BPStage

# PAD module name that marks a mapping as UI interaction needing an element selector.
# Data-driven, not a hardcoded stage list: it is the `pa_module` value both YAML files
# already use for selector-bearing targets — mapping/stage_rules.yaml's Navigate/Read/
# Write rows ("Out of scope per architecture doc §B9. Requires appdef/ControlRepository
# UI selector") and mapping/vbo_catalogue.yaml's UI-automation VBO entries
# (PID_0003_Object_US_SampleManager, PID_0005_Object_US_ SampleResultsEntry: "Per
# architecture doc §B9, all methods require UI selectors"). Task 8a items 2-3.
_UI_SELECTOR_MODULE = "UIAutomation"

# Stage types whose score is fixed in this module rather than read from a
# stage_rules.yaml row (see _annotate_data/_annotate_collection/_annotate_code/
# _annotate_exception); a rule row's note would not describe their score.
_SELF_SCORED_TYPES = frozenset(
    {StageType.DATA, StageType.COLLECTION, StageType.CODE, StageType.EXCEPTION}
)


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
          5. StageType.EXCEPTION → _annotate_exception()
          6. All others        → _annotate_from_rules()

        Args:
            stage: A BPStage from the AST.

        Returns:
            PAAnnotation with all fields populated.

        """
        annotation = self._dispatch(stage)
        annotation = self._transfer_pending_flags(stage, annotation)
        return self._enforce_band_flags(stage, annotation)

    def _dispatch(self, stage: BPStage) -> PAAnnotation:
        """Route a stage to its per-type annotation method.

        Args:
            stage: A BPStage from the AST.

        Returns:
            The PAAnnotation produced by the per-type method, before the
            post-confidence steps in annotate_stage().

        """
        if stage.stage_type == StageType.ACTION:
            return self._annotate_action(stage)
        if stage.stage_type == StageType.DATA:
            return self._annotate_data(stage)
        if stage.stage_type == StageType.COLLECTION:
            return self._annotate_collection(stage)
        if stage.stage_type == StageType.CODE:
            return self._annotate_code(stage)
        if stage.stage_type == StageType.EXCEPTION:
            return self._annotate_exception(stage)
        return self._annotate_from_rules(stage)

    def _transfer_pending_flags(self, stage: BPStage, annotation: PAAnnotation) -> PAAnnotation:
        """Merge the stage's AST-build ``pending_flags`` into the annotation (Task 8a item 4).

        Task 1b's fusion detection (``ast/builder.py``, unresolved call-fusion
        candidates) stores ReviewFlags in ``BPStage.pending_flags`` because no
        PAAnnotation exists yet; the field's docstring (``ast/models.py``) says the
        engine merges them into ``pa_annotation.flags``. ``pending_flags`` is left
        untouched so annotate_stage() has no side effect on the stage:
        re-annotating the same stage builds a fresh annotation and transfers the
        same flags again, and a flag already present on the annotation (same
        severity and reason) is never added twice.

        Args:
            stage: The stage being annotated.
            annotation: The annotation produced for it by _dispatch().

        Returns:
            The annotation, with any not-yet-present pending flags appended.

        """
        if not stage.pending_flags:
            return annotation
        flags = list(annotation.flags)
        seen = {(f.severity, f.reason) for f in flags}
        for pending in stage.pending_flags:
            key = (pending.severity, pending.reason)
            if key in seen:
                continue
            seen.add(key)
            flags.append(
                ReviewFlag(
                    stage_id=stage.stage_id,
                    reason=pending.reason,
                    severity=pending.severity,
                    suggested_fix=pending.suggested_fix,
                )
            )
        return annotation.model_copy(update={"flags": flags})

    def _enforce_band_flags(self, stage: BPStage, annotation: PAAnnotation) -> PAAnnotation:
        """Apply CLAUDE.md's band-table flag contract once confidence is final (Task 8a 2-3).

        CLAUDE.md's confidence-band table: MANUAL (< 0.50) = "Stub only +
        ReviewFlag(severity=error)"; PARTIAL (0.50-0.69) = "Scaffold + TODO:
        complete this block". Enforced here, after every annotation path, so no
        path can skip it:

        - MANUAL with no ``error`` flag → append one ``error`` flag.
        - PARTIAL with no flag at all → append one ``warn`` flag.

        Existing flags are kept, in order, ahead of the added one. The added
        flag's reason is the specific cause from _low_confidence_cause().

        Args:
            stage: The stage being annotated.
            annotation: Its annotation with final confidence and band.

        Returns:
            The annotation, with the band-mandated flag appended if missing.

        """
        flags = annotation.flags
        if annotation.band == ConfidenceBand.MANUAL:
            if any(f.severity == "error" for f in flags):
                return annotation
            severity = "error"
        elif annotation.band == ConfidenceBand.PARTIAL:
            if flags:
                return annotation
            severity = "warn"
        else:
            return annotation

        reason, suggested_fix = self._low_confidence_cause(stage, annotation)
        added = ReviewFlag(
            stage_id=stage.stage_id,
            reason=reason,
            severity=severity,
            suggested_fix=suggested_fix,
        )
        return annotation.model_copy(update={"flags": [*flags, added]})

    def _low_confidence_cause(self, stage: BPStage, annotation: PAAnnotation) -> tuple[str, str]:
        """Derive why a stage's confidence is low, from the mapping data that produced it.

        Uses only what the stage and the mapping YAML actually carry — never a
        generic "low confidence". In order:

        1. UI interaction: the mapping's module is ``UIAutomation`` → needs a UI
           selector, out of scope per architecture doc §B9.
        2. VBO call: the ``vbo_catalogue.yaml`` entry it routed to — whether the
           called method has a ``method_actions`` template (no catalogue mapping
           if not) and the entry's own note.
        3. Process call / rule-driven stage: the ``stage_rules.yaml`` row and its note.
        4. DATA stage with no data item: its PAD type defaulted to Text.
        5. Otherwise: the score's source plus "no specific cause recorded".

        Args:
            stage: The stage being annotated.
            annotation: Its annotation with final confidence.

        Returns:
            A ``(reason, suggested_fix)`` pair for the band-mandated ReviewFlag.

        """
        score = f"confidence {annotation.confidence:.2f}"
        if stage.stage_type == StageType.ACTION and not stage.is_subsheet_call:
            if stage.is_process_call:
                rule = self._config.get_stage_rule("Process")
                if rule is not None:
                    return _rule_cause(rule.bp_stage_type, rule.notes, rule.pa_module, score)
            else:
                vbo_name = stage.params_map.get("_vbo_object", "")
                method = stage.params_map.get("_vbo_action", "")
                entry = self._config.get_vbo_entry_fuzzy(vbo_name) if vbo_name else None
                if entry is not None:
                    return _vbo_cause(
                        entry.vbo_name,
                        method,
                        entry.pa_module,
                        method in entry.method_actions,
                        entry.notes,
                        score,
                    )
        elif stage.stage_type == StageType.DATA and not stage.data_items:
            return (
                f"DATA stage '{stage.name}' has no data item recorded, so its PAD variable "
                f"type defaulted to Text ({score}, the annotator's fixed score for an "
                "unresolved data type)",
                "Check the BP Data stage was parsed with its data type",
            )
        elif stage.stage_type not in _SELF_SCORED_TYPES:
            try:
                rule = self._config.get_stage_rule_for_canonical_type(stage.stage_type.value)
            except ConfigError:
                rule = None
            if rule is not None:
                return _rule_cause(rule.bp_stage_type, rule.notes, rule.pa_module, score)

        return (
            f"{score} from the annotator's fixed score for {stage.stage_type.value} stages; "
            "no specific cause recorded",
            "Review the generated block against the BP stage and complete it by hand",
        )

    def _annotate_action(self, stage: BPStage) -> PAAnnotation:
        """Annotate ACTION stage (VBO call, subsheet call, or process call)."""
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

        if stage.is_process_call:
            # Process call — use the Process stage rule from stage_rules.yaml
            # Per architecture doc §B13 and CLAUDE.md normalisation table: PROCESS → ACTION
            # Look up by "Process" bp_stage_type, not by stage.stage_type (which is ACTION)
            rule = self._config.get_stage_rule("Process")

            if rule is None:
                # No Process rule found — this shouldn't happen if stage_rules.yaml is correct
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
                            reason="No Process rule found in stage_rules.yaml",
                            severity="error",
                            suggested_fix="Add Process entry to mapping/stage_rules.yaml",
                        )
                    ],
                )

            # Rule found. Any band-mandated flag is added by _enforce_band_flags()
            # (Task 8a) with the rule's full note, not a truncated copy here.
            return PAAnnotation(
                target_type=rule.pa_target_action,
                target_module=rule.pa_module,
                runtime=rule.runtime,
                confidence=rule.confidence_base,
                band=ConfidenceBand.from_score(rule.confidence_base),
                params_map={},
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
                        reason="ACTION stage has no VBO metadata and is not a subsheet or process call",
                        severity="error",
                        suggested_fix="Check XML parsing — ACTION must have _vbo_object or be flagged as subsheet/process call",
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
        code_preview = (stage.code_text or "")[:500]
        suggested_fix = "Extract code logic and rewrite as System.RunPowershellScript action"
        if code_preview:
            suggested_fix = f"Rewrite as PowerShell/C# script.\nOriginal VBScript:\n{code_preview}"
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
                    suggested_fix=suggested_fix,
                )
            ],
        )

    def _annotate_exception(self, stage: BPStage) -> PAAnnotation:
        """Annotate EXCEPTION stage (throw or re-raise).

        A BP <exception usecurrent="yes"> stage re-raises whatever exception
        is currently active — this maps to a plain `THROW ERROR` in PAD, so
        no custom message parameters are needed. Otherwise, the stage throws
        a new typed exception and must carry its type/detail forward so the
        generator can emit `FlowControl.ThrowCustomError`.

        Args:
            stage: A BPStage with stage_type == StageType.EXCEPTION.

        Returns:
            PAAnnotation targeting FlowControl.ThrowError or
            FlowControl.ThrowCustomError.

        """
        if stage.exception_usecurrent:
            confidence = 0.90
            return PAAnnotation(
                target_type="ThrowError",
                target_module="FlowControl",
                runtime=Runtime.DESKTOP,
                confidence=confidence,
                band=ConfidenceBand.from_score(confidence),
                params_map={},
                flags=[],
            )

        confidence = 0.80
        params_map: dict[str, str] = {}
        if stage.exception_type:
            params_map["exception_type"] = stage.exception_type
        if stage.exception_detail:
            params_map["detail_expr"] = stage.exception_detail

        flags = []
        if not stage.exception_type and not stage.exception_detail:
            flags.append(
                ReviewFlag(
                    stage_id=stage.stage_id,
                    reason="Exception stage has neither a type nor a detail expression",
                    severity="warn",
                    suggested_fix="Verify the original BP <exception> element was parsed correctly",
                )
            )

        return PAAnnotation(
            target_type="ThrowCustomError",
            target_module="FlowControl",
            runtime=Runtime.DESKTOP,
            confidence=confidence,
            band=ConfidenceBand.from_score(confidence),
            params_map=params_map,
            flags=flags,
        )

    def _annotate_from_rules(self, stage: BPStage) -> PAAnnotation:
        """Annotate stage using stage_rules.yaml.

        The rule is looked up by the stage's *canonical* type against the
        ``canonical_type`` column (Task 8a item 1), because the AST does not keep
        the raw BP type of normalised stages (LOOP ← LoopStart/LoopEnd, WAIT ←
        WaitStart/WaitEnd). See MappingConfig.get_stage_rule_for_canonical_type()
        for which row is chosen when several share a canonical type.

        Args:
            stage: A BPStage whose type has no dedicated annotation method.

        Returns:
            PAAnnotation from the matching rule, or a MANUAL annotation with an
            error flag if stage_rules.yaml has no row for the canonical type.

        """
        try:
            rule = self._config.get_stage_rule_for_canonical_type(stage.stage_type.value)
        except ConfigError:
            rule = None

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

        # Rule found. Any band-mandated flag is added by _enforce_band_flags()
        # (Task 8a) with the rule's full note, not a truncated copy here.
        return PAAnnotation(
            target_type=rule.pa_target_action,
            target_module=rule.pa_module,
            runtime=rule.runtime,
            confidence=rule.confidence_base,
            band=ConfidenceBand.from_score(rule.confidence_base),
            params_map={},
            flags=[],
        )


def _one_line(text: str) -> str:
    """Collapse a YAML note (folded scalars end in a newline) onto one line.

    Args:
        text: Raw ``notes`` text from a mapping YAML row.

    Returns:
        The text with every whitespace run collapsed to one space, stripped.

    """
    return " ".join(text.split())


def _rule_cause(bp_stage_type: str, notes: str, pa_module: str, score: str) -> tuple[str, str]:
    """Build the low-confidence cause for a stage scored by a stage_rules.yaml row.

    Args:
        bp_stage_type: The rule's ``bp_stage_type`` (identifies the YAML row).
        notes: The rule's ``notes`` text.
        pa_module: The rule's ``pa_module``.
        score: Pre-formatted "confidence X.XX" text.

    Returns:
        A ``(reason, suggested_fix)`` pair.

    """
    source = f"{score} from stage_rules.yaml '{bp_stage_type}' rule"
    note = _one_line(notes)
    if pa_module == _UI_SELECTOR_MODULE:
        reason = f"UI interaction needs a UI selector (architecture doc §B9); {source}"
        return (
            reason + (f": {note}" if note else ""),
            "Build the UI element selector in PAD's UI element repository and implement "
            "this step by hand (architecture doc §B9 — never a fabricated selector)",
        )
    if note:
        return (
            f"{source}: {note}",
            f"Resolve the point raised in the stage_rules.yaml '{bp_stage_type}' note "
            "and complete this block by hand",
        )
    return (
        f"{source}; no specific cause recorded",
        "Review the generated block against the BP stage and complete it by hand",
    )


def _vbo_cause(
    vbo_name: str,
    method: str,
    pa_module: str,
    has_template: bool,
    notes: str,
    score: str,
) -> tuple[str, str]:
    """Build the low-confidence cause for a VBO-call stage.

    Args:
        vbo_name: The matched ``vbo_catalogue.yaml`` entry's ``vbo_name``.
        method: The BP VBO method (action) name the stage calls.
        pa_module: The entry's ``pa_module``.
        has_template: True if the entry's ``method_actions`` has this method.
        notes: The entry's ``notes`` text.
        score: Pre-formatted "confidence X.XX" text.

    Returns:
        A ``(reason, suggested_fix)`` pair.

    """
    source = f"{score} from vbo_catalogue.yaml entry '{vbo_name}'"
    note = _one_line(notes)
    if pa_module == _UI_SELECTOR_MODULE:
        return (
            f"UI interaction needs a UI selector (architecture doc §B9): '{vbo_name}' "
            f"action '{method}'; {source}",
            "Build the UI element selector in PAD's UI element repository and implement "
            "this action by hand (architecture doc §B9 — never a fabricated selector)",
        )
    if not has_template:
        reason = f"No catalogue mapping: no method_actions template for '{method}'; {source}"
        return (
            reason + (f". Catalogue note: {note}" if note else ""),
            f"Add a confirmed PAD template for '{method}' to the '{vbo_name}' entry's "
            "method_actions (docs/pad-reference/vbo-action-mapping.md), or implement "
            "this action by hand",
        )
    if note:
        return (
            f"{source}: {note}",
            f"Resolve the point raised in the '{vbo_name}' catalogue note and complete "
            "this action by hand",
        )
    return (
        f"{source}; no specific cause recorded",
        "Review the generated action against the BP stage and complete it by hand",
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
