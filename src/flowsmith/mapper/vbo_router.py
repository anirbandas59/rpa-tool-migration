"""VBO method routing — maps Blue Prism VBO calls to Power Automate modules.

Given a VBO name and method name, the router returns a RoutingDecision
that tells the engine which PAD module to target, runtime, confidence,
and any mandatory review flags from the catalogue.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from flowsmith.ast.models import ReviewFlag, Runtime, StageType
from flowsmith.mapper.config import MappingConfig, VBOFusionPattern

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
    resolved_action_template: str = Field(
        default="",
        description="Resolved PAD action template if method_actions had an exact match, empty otherwise.",
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

        # Known VBO — resolve method and apply routing logic
        confidence = entry.confidence_base
        resolved_template = ""

        # Check if method_actions is populated (new feature)
        has_method_actions = bool(entry.method_actions)

        if has_method_actions:
            # New logic: check method_actions first for exact match
            if method_name in entry.method_actions:
                resolved_template = entry.method_actions[method_name]
                # Exact match uses full confidence
                confidence = entry.confidence_base
            else:
                # method_actions exists but does not have this method
                # Fall back to method_patterns (fuzzy match) with same base confidence
                # TODO: Confidence differentiation between exact and fuzzy method matches
                # is an open design question — currently both yield entry.confidence_base.
                # This will be addressed during Task 2b when real method_actions data is
                # populated and a decision is made on whether to apply confidence penalties
                # for fuzzy matches. For now, both paths conservatively use base confidence.
                if method_name:
                    method_lower = method_name.lower()
                    for pattern in entry.method_patterns:
                        if method_lower == pattern.lower():
                            # Fuzzy pattern match found, but uses same confidence
                            break

                # Whether a fuzzy pattern matched or not, keep base confidence for known VBO
                confidence = entry.confidence_base
        else:
            # Old logic: method_actions is empty (backward compatibility)
            # Return full confidence unconditionally for known VBO
            # (pre-Task-1 behavior: no method-level checking)
            confidence = entry.confidence_base

        # Inject mandatory flags if present
        flags: list[ReviewFlag] = []
        if entry.review_severity is not None:
            # Carry the full catalogue note, whitespace-normalised (YAML folded
            # scalars end in a newline). Task 8a item 5: the former `notes[:120]`
            # cut the reason mid-word ("...via SharePoin"), unreadable for hand-off.
            note = " ".join(entry.notes.split())
            flag = ReviewFlag(
                stage_id="",
                reason=f"VBO '{vbo_name}' requires mandatory review: {note}",
                severity=entry.review_severity,
                suggested_fix="Review and replace with Power Platform equivalent",
            )
            flags.append(flag)

        return RoutingDecision(
            vbo_name=vbo_name,
            method_name=method_name,
            pa_module=entry.pa_module,
            runtime=entry.runtime,
            confidence=confidence,
            is_known=True,
            review_flags=flags,
            notes=entry.notes,
            resolved_action_template=resolved_template,
        )

    def resolve_fusion_pattern(
        self,
        vbo_name: str,
        method_sequence: list[str],
    ) -> tuple[VBOFusionPattern | None, list[str]]:
        """Resolve a sequence of BP method names against fusion patterns.

        Checks whether the given sequence of method names (in order) matches any
        fusion pattern defined for the VBO in the catalogue. This is called when
        adjacent stages have been detected as a fusion candidate (by Task 1b's
        structural detection in ast/builder.py), and the router's job is to
        resolve that candidate against curated patterns.

        Args:
            vbo_name: The VBO name (should match all stages in the sequence).
            method_sequence: List of BP method names in order, e.g.
                ["Create Instance", "Open Workbook"].

        Returns:
            A tuple (pattern, vestigial_methods) where:
            - pattern: The matching VBOFusionPattern if found, None otherwise.
            - vestigial_methods: List of method names from the sequence that are
              marked as vestigial in the pattern (empty if no match or no vestigial
              stages). These stages produce no independent PAD output.

            Never raises. Unknown VBOs return (None, []).
        """
        # Look up the VBO entry
        entry = self._config.get_vbo_entry(vbo_name)
        if entry is None:
            entry = self._config.get_vbo_entry_fuzzy(vbo_name)

        # Unknown VBO or no fusion patterns
        if entry is None or not entry.fusion_patterns:
            return None, []

        # Search for a matching fusion pattern
        for pattern in entry.fusion_patterns:
            if pattern.sequence == method_sequence:
                # Exact match found
                return pattern, pattern.vestigial_stages

        # No matching pattern
        return None, []

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
