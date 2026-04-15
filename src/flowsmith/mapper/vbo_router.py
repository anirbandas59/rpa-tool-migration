"""VBO method routing — maps Blue Prism VBO calls to Power Automate modules.

Given a VBO name and method name, the router returns a RoutingDecision
that tells the engine which PAD module to target, runtime, confidence,
and any mandatory review flags from the catalogue.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from flowsmith.ast.models import ReviewFlag, Runtime, StageType
from flowsmith.mapper.config import MappingConfig

# ── RoutingDecision model ──────────────────────────────────────────────────


class RoutingDecision(BaseModel):
    """The routing decision for a single VBO method call.

    Immutable (frozen) once created. Contains all information the
    engine needs to annotate a VBO ACTION stage.
    """

    model_config = ConfigDict(frozen=True)

    vbo_name: str = Field(description="The VBO name from the BP ACTION stage.")
    method_name: str = Field(description="The VBO method name from the BP ACTION stage.")
    pa_module: str = Field(description="Target PAD module name, or '' if unknown.")
    runtime: Runtime = Field(description="CLOUD or DESKTOP runtime target.")
    confidence: float = Field(description="Migration confidence score [0.0, 1.0].")
    is_known: bool = Field(description="True if VBO is in the catalogue, False if unknown.")
    review_flags: list[ReviewFlag] = Field(
        default_factory=list,
        description="Mandatory review flags from the catalogue (injected by router).",
    )
    notes: str = Field(
        default="",
        description="Notes from the catalogue entry, or '' if unknown VBO.",
    )


# ── VBO Router ─────────────────────────────────────────────────────────────


class VBORouter:
    """Routes VBO method calls to their Power Automate equivalents.

    Accepts a MappingConfig (injected, not loaded). All lookups are
    case-insensitive with fuzzy fallback. Unknown VBOs return a stub
    RoutingDecision with is_known=False, never raise exceptions.
    """

    def __init__(self, config: MappingConfig) -> None:
        """Initialize the router with a MappingConfig.

        Args:
            config: Loaded MappingConfig with stage_rules and vbo_catalogue.
        """
        self._config = config

    def route(
        self,
        vbo_name: str,
        method_name: str,
    ) -> RoutingDecision:
        """Route a VBO method call to its Power Automate equivalent.

        Lookup order:
          1. Exact match by vbo_name in catalogue
          2. Fuzzy (case-insensitive) match
          3. Unknown VBO — return low-confidence stub

        Mandatory flags:
          - If VBOEntry.review_severity == "error": inject error flag
          - If VBOEntry.review_severity == "warn": inject warn flag
          - If unknown VBO: inject error flag

        The stage_id on injected flags is left as "" — the engine
        fills it with the real stage_id in Phase 5.

        Args:
            vbo_name: The _vbo_object value from params_map.
            method_name: The _vbo_action value from params_map.

        Returns:
            RoutingDecision with all fields populated. Never raises.
        """
        # Look up the VBO entry
        entry = self._config.get_vbo_entry(vbo_name)
        if entry is None:
            entry = self._config.get_vbo_entry_fuzzy(vbo_name)

        # Handle unknown VBO
        if entry is None:
            flag = ReviewFlag(
                stage_id="",
                reason=f"Unknown VBO '{vbo_name}' — not in catalogue",
                severity="error",
                suggested_fix="Add VBO to mapping/vbo_catalogue.yaml and re-run",
            )
            return RoutingDecision(
                vbo_name=vbo_name,
                method_name=method_name,
                pa_module="",
                runtime=Runtime.DESKTOP,
                confidence=0.0,
                is_known=False,
                review_flags=[flag],
                notes="",
            )

        # Known VBO — inject mandatory flags if present
        flags: list[ReviewFlag] = []
        if entry.review_severity is not None:
            flag = ReviewFlag(
                stage_id="",
                reason=f"VBO '{vbo_name}' requires mandatory review: {entry.notes[:120]}",
                severity=entry.review_severity,
                suggested_fix="Review and replace with Power Platform equivalent",
            )
            flags.append(flag)

        return RoutingDecision(
            vbo_name=vbo_name,
            method_name=method_name,
            pa_module=entry.pa_module,
            runtime=entry.runtime,
            confidence=entry.confidence_base,
            is_known=True,
            review_flags=flags,
            notes=entry.notes,
        )

    def route_stage(self, stage) -> RoutingDecision | None:
        """Convenience method — route directly from a BPStage.

        Returns None if the stage is not a VBO call (i.e., it's not an
        ACTION stage, or it's a subsheet call, or it has no _vbo_object
        in params_map).

        Args:
            stage: A BPStage from the AST.

        Returns:
            RoutingDecision or None if stage is not a VBO call.
        """
        # Only route ACTION stages
        if stage.stage_type != StageType.ACTION:
            return None

        # Skip subsheet calls
        if stage.is_subsheet_call:
            return None

        # Check for _vbo_object in params_map
        vbo_object = stage.params_map.get("_vbo_object")
        if not vbo_object:
            return None

        # Get the method name, defaulting to "" if missing
        vbo_action = stage.params_map.get("_vbo_action", "")

        # Route and return
        return self.route(vbo_object, vbo_action)
