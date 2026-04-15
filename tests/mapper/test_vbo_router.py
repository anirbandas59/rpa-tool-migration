"""Tests for flowsmith.mapper.vbo_router — VBO method routing."""

from __future__ import annotations

from pathlib import Path

import pytest

from flowsmith.ast import BPStage, Runtime, StageType
from flowsmith.mapper import MappingConfig, RoutingDecision, VBORouter, load_rules

# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def config() -> MappingConfig:
    """Load the real mapping configuration."""
    return load_rules(force_reload=True)


@pytest.fixture
def router(config: MappingConfig) -> VBORouter:
    """Create a VBORouter with the real config."""
    return VBORouter(config)


@pytest.fixture
def make_action_stage():
    """Factory for creating ACTION BPStage objects."""

    def _make(
        vbo_object: str = "",
        vbo_action: str = "",
        is_subsheet_call: bool = False,
        stage_id: str = "s1",
        **kwargs,
    ) -> BPStage:
        params = {}
        if vbo_object:
            params["_vbo_object"] = vbo_object
        if vbo_action:
            params["_vbo_action"] = vbo_action

        return BPStage(
            stage_id=stage_id,
            stage_type=StageType.ACTION,
            name="VBO Call",
            data_items=[],
            exception_handler_id=None,
            exception_type=None,
            pair_id=None,
            is_subsheet_call=is_subsheet_call,
            params_map=params,
            pa_annotation=None,
            **kwargs,
        )

    return _make


# ── RoutingDecision model tests ────────────────────────────────────────────


class TestRoutingDecision:
    """Test RoutingDecision Pydantic model."""

    def test_routing_decision_is_frozen(self, router: VBORouter) -> None:
        """RoutingDecision is frozen — cannot modify fields."""
        from pydantic import ValidationError

        decision = router.route("MS Excel VBO", "Open Workbook")
        with pytest.raises((TypeError, ValidationError)):
            decision.pa_module = "NewModule"  # type: ignore

    def test_routing_decision_has_all_fields(self, router: VBORouter) -> None:
        """RoutingDecision has all expected fields."""
        decision = router.route("MS Excel VBO", "Open Workbook")
        assert hasattr(decision, "vbo_name")
        assert hasattr(decision, "method_name")
        assert hasattr(decision, "pa_module")
        assert hasattr(decision, "runtime")
        assert hasattr(decision, "confidence")
        assert hasattr(decision, "is_known")
        assert hasattr(decision, "review_flags")
        assert hasattr(decision, "notes")


# ── Known VBO routing tests ────────────────────────────────────────────────


class TestKnownVBORouting:
    """Test routing of known VBOs from the catalogue."""

    def test_known_vbo_is_known_true(self, router: VBORouter) -> None:
        """Known VBO has is_known=True."""
        decision = router.route("MS Excel VBO", "Open Workbook")
        assert decision.is_known is True

    def test_known_vbo_confidence_matches_catalogue(self, router: VBORouter) -> None:
        """Known VBO confidence matches catalogue entry."""
        decision = router.route("MS Excel VBO", "Open Workbook")
        assert decision.confidence == 0.80

    def test_known_vbo_runtime_matches_catalogue(self, router: VBORouter) -> None:
        """Known VBO runtime matches catalogue entry."""
        decision = router.route("MS Excel VBO", "Open Workbook")
        assert decision.runtime == Runtime.DESKTOP

    def test_known_vbo_no_flags_for_normal_entry(self, router: VBORouter) -> None:
        """Known VBO without review_severity has 0 flags."""
        decision = router.route("MS Excel VBO", "Open Workbook")
        assert len(decision.review_flags) == 0

    def test_known_vbo_vbo_name_in_decision(self, router: VBORouter) -> None:
        """Known VBO decision contains the VBO name."""
        decision = router.route("MS Excel VBO", "Open Workbook")
        assert decision.vbo_name == "MS Excel VBO"

    def test_known_vbo_method_name_in_decision(self, router: VBORouter) -> None:
        """Known VBO decision contains the method name."""
        decision = router.route("MS Excel VBO", "Open Workbook")
        assert decision.method_name == "Open Workbook"

    def test_notes_populated_from_catalogue(self, router: VBORouter) -> None:
        """Known VBO decision contains notes from catalogue."""
        decision = router.route("MS Excel VBO", "Open Workbook")
        assert decision.notes != ""
        assert len(decision.notes) > 0

    def test_work_queues_vbo_is_cloud_runtime(self, router: VBORouter) -> None:
        """Work Queue VBO has CLOUD runtime."""
        decision = router.route("Blueprism.Automate.clsWorkQueuesActions", "Get Next Item")
        assert decision.is_known is True
        assert decision.runtime == Runtime.CLOUD

    def test_sharepoint_api_vbo_is_cloud_runtime(self, router: VBORouter) -> None:
        """SharePoint API VBO has CLOUD runtime."""
        decision = router.route(
            "Utility_Object_Generic_SharePoint_API_Common_Actions",
            "Download File From SharePoint",
        )
        assert decision.is_known is True
        assert decision.runtime == Runtime.CLOUD

    def test_file_management_vbo_is_desktop_runtime(self, router: VBORouter) -> None:
        """File Management VBO has DESKTOP runtime."""
        decision = router.route("Utility - File Management", "File Exists")
        assert decision.is_known is True
        assert decision.runtime == Runtime.DESKTOP


# ── Mandatory flag injection tests ─────────────────────────────────────────


class TestMandatoryFlagInjection:
    """Test mandatory flag injection for VBOs with review_severity."""

    def test_acs_vbo_injects_error_flag(self, router: VBORouter) -> None:
        """ACS VBO injects an error-level review flag."""
        decision = router.route("RPA Sharepoint ACS Authentication", "Authenticate")
        assert decision.is_known is True
        assert len(decision.review_flags) == 1
        assert decision.review_flags[0].severity == "error"

    def test_acs_flag_severity_is_error(self, router: VBORouter) -> None:
        """ACS VBO flag has severity='error'."""
        decision = router.route("RPA Sharepoint ACS Authentication", "Authenticate")
        flag = decision.review_flags[0]
        assert flag.severity == "error"

    def test_acs_flag_stage_id_is_empty(self, router: VBORouter) -> None:
        """ACS VBO flag has stage_id='' (filled by engine later)."""
        decision = router.route("RPA Sharepoint ACS Authentication", "Authenticate")
        flag = decision.review_flags[0]
        assert flag.stage_id == ""

    def test_acs_flag_reason_mentions_vbo(self, router: VBORouter) -> None:
        """ACS VBO flag reason mentions the VBO name."""
        decision = router.route("RPA Sharepoint ACS Authentication", "Authenticate")
        flag = decision.review_flags[0]
        assert "RPA Sharepoint ACS Authentication" in flag.reason

    def test_locking_vbo_injects_warn_flag(self, router: VBORouter) -> None:
        """Locking VBO injects a warn-level review flag."""
        decision = router.route(
            "BluePrism.AutomateAppCore.clsEnvironmentLockingBusinessObject",
            "Acquire Lock",
        )
        assert decision.is_known is True
        assert len(decision.review_flags) == 1
        assert decision.review_flags[0].severity == "warn"

    def test_locking_flag_severity_is_warn(self, router: VBORouter) -> None:
        """Locking VBO flag has severity='warn'."""
        decision = router.route(
            "BluePrism.AutomateAppCore.clsEnvironmentLockingBusinessObject",
            "Acquire Lock",
        )
        flag = decision.review_flags[0]
        assert flag.severity == "warn"

    def test_flag_has_suggested_fix(self, router: VBORouter) -> None:
        """Injected flags have suggested_fix field."""
        decision = router.route("RPA Sharepoint ACS Authentication", "Authenticate")
        flag = decision.review_flags[0]
        assert flag.suggested_fix != ""
        assert len(flag.suggested_fix) > 0


# ── Unknown VBO tests ──────────────────────────────────────────────────────


class TestUnknownVBORouting:
    """Test routing of unknown VBOs not in the catalogue."""

    def test_unknown_vbo_is_known_false(self, router: VBORouter) -> None:
        """Unknown VBO has is_known=False."""
        decision = router.route("Totally Unknown VBO", "Some Method")
        assert decision.is_known is False

    def test_unknown_vbo_confidence_is_zero(self, router: VBORouter) -> None:
        """Unknown VBO has confidence=0.0."""
        decision = router.route("Totally Unknown VBO", "Some Method")
        assert decision.confidence == 0.0

    def test_unknown_vbo_runtime_is_desktop(self, router: VBORouter) -> None:
        """Unknown VBO has runtime=DESKTOP (safe default)."""
        decision = router.route("Totally Unknown VBO", "Some Method")
        assert decision.runtime == Runtime.DESKTOP

    def test_unknown_vbo_pa_module_is_empty(self, router: VBORouter) -> None:
        """Unknown VBO has pa_module=''."""
        decision = router.route("Totally Unknown VBO", "Some Method")
        assert decision.pa_module == ""

    def test_unknown_vbo_injects_error_flag(self, router: VBORouter) -> None:
        """Unknown VBO injects an error-level review flag."""
        decision = router.route("Totally Unknown VBO", "Some Method")
        assert len(decision.review_flags) == 1
        assert decision.review_flags[0].severity == "error"

    def test_unknown_vbo_flag_reason_mentions_vbo(self, router: VBORouter) -> None:
        """Unknown VBO flag reason mentions the VBO name."""
        decision = router.route("Totally Unknown VBO", "Some Method")
        flag = decision.review_flags[0]
        assert "Totally Unknown VBO" in flag.reason

    def test_unknown_vbo_notes_empty(self, router: VBORouter) -> None:
        """Unknown VBO has notes=''."""
        decision = router.route("Totally Unknown VBO", "Some Method")
        assert decision.notes == ""


# ── Fuzzy matching tests ───────────────────────────────────────────────────


class TestFuzzyMatching:
    """Test case-insensitive fuzzy matching."""

    def test_fuzzy_match_case_insensitive_lower(self, router: VBORouter) -> None:
        """Fuzzy match finds VBO with lowercase input."""
        decision = router.route("ms excel vbo", "Open Workbook")
        assert decision.is_known is True
        assert decision.confidence == 0.80

    def test_fuzzy_match_case_insensitive_mixed(self, router: VBORouter) -> None:
        """Fuzzy match finds VBO with mixed-case input."""
        decision = router.route("Ms Excel VbO", "Open Workbook")
        assert decision.is_known is True

    def test_fuzzy_match_preserves_original_vbo_name(self, router: VBORouter) -> None:
        """Fuzzy match preserves the original input VBO name in decision."""
        decision = router.route("ms excel vbo", "Open Workbook")
        assert decision.vbo_name == "ms excel vbo"  # Not normalized


# ── route_stage() convenience method tests ─────────────────────────────────


class TestRouteStageMethods:
    """Test the route_stage() convenience method."""

    def test_route_stage_returns_none_for_subsheet_call(
        self, router: VBORouter, make_action_stage
    ) -> None:
        """route_stage() returns None for subsheet calls."""
        stage = make_action_stage(vbo_object="Subsheet", vbo_action="", is_subsheet_call=True)
        assert router.route_stage(stage) is None

    def test_route_stage_returns_none_for_non_action(self, router: VBORouter) -> None:
        """route_stage() returns None for non-ACTION stages."""
        stage = BPStage(
            stage_id="s1",
            stage_type=StageType.DECISION,
            name="Check Status",
            data_items=[],
            exception_handler_id=None,
            exception_type=None,
            pair_id=None,
            is_subsheet_call=False,
            params_map={},
            pa_annotation=None,
        )
        assert router.route_stage(stage) is None

    def test_route_stage_returns_none_for_action_without_vbo_key(
        self, router: VBORouter, make_action_stage
    ) -> None:
        """route_stage() returns None for ACTION without _vbo_object."""
        stage = make_action_stage(vbo_object="", vbo_action="")
        assert router.route_stage(stage) is None

    def test_route_stage_returns_decision_for_vbo_action(
        self, router: VBORouter, make_action_stage
    ) -> None:
        """route_stage() returns RoutingDecision for VBO ACTION."""
        stage = make_action_stage(vbo_object="MS Excel VBO", vbo_action="Open Workbook")
        decision = router.route_stage(stage)
        assert decision is not None
        assert isinstance(decision, RoutingDecision)

    def test_route_stage_vbo_name_matches_params_map(
        self, router: VBORouter, make_action_stage
    ) -> None:
        """route_stage() extracts VBO name from _vbo_object in params_map."""
        stage = make_action_stage(vbo_object="MS Excel VBO", vbo_action="Open Workbook")
        decision = router.route_stage(stage)
        assert decision is not None
        assert decision.vbo_name == "MS Excel VBO"

    def test_route_stage_method_name_matches_params_map(
        self, router: VBORouter, make_action_stage
    ) -> None:
        """route_stage() extracts method name from _vbo_action in params_map."""
        stage = make_action_stage(vbo_object="MS Excel VBO", vbo_action="Open Workbook")
        decision = router.route_stage(stage)
        assert decision is not None
        assert decision.method_name == "Open Workbook"

    def test_route_stage_handles_missing_vbo_action(
        self, router: VBORouter, make_action_stage
    ) -> None:
        """route_stage() handles missing _vbo_action (defaults to '')."""
        stage = make_action_stage(vbo_object="MS Excel VBO", vbo_action="")
        decision = router.route_stage(stage)
        assert decision is not None
        assert decision.method_name == ""


# ── Integration tests ──────────────────────────────────────────────────────


class TestIntegration:
    """Integration tests with real sample data."""

    def test_all_vbos_in_sample_are_known(self, router: VBORouter) -> None:
        """Real sample uses only VBOs in the catalogue."""
        from collections import Counter

        from flowsmith.ast import build_ast
        from flowsmith.parser import VBO_OBJECT_KEY, parse_process

        raw = parse_process(Path("samples/blueprism/PID_0127.bprelease"))
        process = build_ast(raw)

        results = Counter()
        unknown_vbos = set()

        for page in process.pages:
            for stage in page.stages:
                decision = router.route_stage(stage)
                if decision is None:
                    continue
                results["routed"] += 1
                if decision.is_known:
                    results["known"] += 1
                else:
                    results["unknown"] += 1
                    unknown_vbos.add(stage.params_map.get(VBO_OBJECT_KEY, ""))

        # All VBO calls must be known
        assert results["unknown"] == 0, f"Found unknown VBOs: {unknown_vbos}"

    def test_sample_routed_count_is_correct(self, router: VBORouter) -> None:
        """Real sample routes exactly 489 VBO calls."""
        from flowsmith.ast import build_ast
        from flowsmith.parser import parse_process

        raw = parse_process(Path("samples/blueprism/PID_0127.bprelease"))
        process = build_ast(raw)

        routed = 0
        for page in process.pages:
            for stage in page.stages:
                if router.route_stage(stage) is not None:
                    routed += 1

        assert routed == 489

    def test_sample_mandatory_flags_count(self, router: VBORouter) -> None:
        """Real sample has exactly 4 mandatory review flags."""
        from flowsmith.ast import build_ast
        from flowsmith.parser import parse_process

        raw = parse_process(Path("samples/blueprism/PID_0127.bprelease"))
        process = build_ast(raw)

        flag_count = 0
        for page in process.pages:
            for stage in page.stages:
                decision = router.route_stage(stage)
                if decision is not None:
                    flag_count += len(decision.review_flags)

        assert flag_count == 4
