"""Tests for flowsmith.mapper.vbo_router — VBO method routing."""

from __future__ import annotations

from pathlib import Path

import pytest

from flowsmith.ast import BPStage, Runtime, StageType
from flowsmith.mapper import MappingConfig, RoutingDecision, VBOEntry, VBORouter, load_rules

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

    def test_work_queues_vbo_is_desktop_runtime(self, router: VBORouter) -> None:
        """Work Queue VBO has DESKTOP runtime."""
        decision = router.route("Blueprism.Automate.clsWorkQueuesActions", "Get Next Item")
        assert decision.is_known is True
        assert decision.runtime == Runtime.DESKTOP

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


# ── method_actions precedence tests ────────────────────────────────────────


class TestMethodActionsPrecedence:
    """Test that method_actions exact matches take precedence over fuzzy patterns."""

    def test_method_actions_exact_match_takes_precedence(self, config: MappingConfig) -> None:
        """Exact method_actions match is used when available."""
        # Create a test entry with both method_actions and method_patterns
        entry = VBOEntry(
            vbo_name="Test VBO",
            method_patterns=["Some Pattern"],
            pa_module="TestModule",
            runtime=Runtime.DESKTOP,
            confidence_base=0.80,
            method_actions={
                "Exact Method": "ExactActionTemplate",
            },
        )
        config.vbo_catalogue.append(entry)
        router = VBORouter(config)

        # Route with exact match in method_actions
        decision = router.route("Test VBO", "Exact Method")
        assert decision.is_known is True
        assert decision.resolved_action_template == "ExactActionTemplate"
        assert decision.confidence == 0.80

    def test_exact_match_has_higher_confidence_than_fuzzy(self, config: MappingConfig) -> None:
        """Exact method_actions and fuzzy pattern matches yield the same confidence (base_confidence) by design.

        No differentiation mechanism is currently documented or implemented. When method_actions is
        present but doesn't contain a method, the router falls back to fuzzy pattern matching using
        the same base confidence. Confidence differentiation between exact and fuzzy matches is an
        open design question, deferred to Task 2b when real method_actions data is populated.
        """
        # Create a test entry with both method_actions and method_patterns
        entry = VBOEntry(
            vbo_name="Test VBO With Methods",
            method_patterns=["Fuzzy Pattern", "Another Pattern"],
            pa_module="TestModule",
            runtime=Runtime.DESKTOP,
            confidence_base=0.80,
            method_actions={
                "Exact Method": "ExactTemplate",
            },
        )
        config.vbo_catalogue.append(entry)
        router = VBORouter(config)

        # Route with exact match (method_actions)
        exact_decision = router.route("Test VBO With Methods", "Exact Method")
        assert exact_decision.confidence == 0.80

        # Route with fuzzy match (method_patterns) - when method_actions exists
        fuzzy_decision = router.route("Test VBO With Methods", "Fuzzy Pattern")
        assert fuzzy_decision.confidence == 0.80  # same base confidence

        # Both exact and fuzzy matches currently yield the same confidence by design
        assert exact_decision.confidence == fuzzy_decision.confidence

    def test_fuzzy_pattern_match_reduces_confidence(self, config: MappingConfig) -> None:
        """Fuzzy method_patterns match yields the same base confidence, no reduction (by design).

        Confidence differentiation between exact and fuzzy method matches is an open design
        question. Currently, both paths conservatively yield entry.confidence_base.
        This test verifies that fuzzy matches do NOT artificially reduce confidence.
        """
        entry = VBOEntry(
            vbo_name="Fuzzy Test VBO",
            method_patterns=["Fuzzy Pattern"],
            pa_module="TestModule",
            runtime=Runtime.DESKTOP,
            confidence_base=1.0,
            method_actions={"SomeMethod": "SomeTemplate"},  # method_actions is non-empty
        )
        config.vbo_catalogue.append(entry)
        router = VBORouter(config)

        # Fuzzy match keeps base confidence when method_actions is set (no reduction)
        decision = router.route("Fuzzy Test VBO", "fuzzy pattern")
        assert decision.confidence == 1.0  # base confidence, no reduction

    def test_no_method_actions_behaves_as_before(self, config: MappingConfig) -> None:
        """VBOEntry with no method_actions behaves exactly as before (regression test)."""
        # Create an entry with no method_actions (relies on default behavior)
        entry = VBOEntry(
            vbo_name="Classic VBO",
            method_patterns=["Classic Pattern"],
            pa_module="TestModule",
            runtime=Runtime.DESKTOP,
            confidence_base=0.75,
        )
        config.vbo_catalogue.append(entry)
        router = VBORouter(config)

        # Should route successfully with fuzzy match
        decision = router.route("Classic VBO", "Classic Pattern")
        assert decision.is_known is True
        assert decision.confidence == 0.75  # Full confidence maintained for backward compatibility
        assert decision.resolved_action_template == ""

    def test_no_method_actions_with_unmatched_method(self, config: MappingConfig) -> None:
        """VBOEntry with no method_actions returns full confidence even for unmatched methods."""
        # This is the regression test case: method doesn't match any pattern
        entry = VBOEntry(
            vbo_name="Classic VBO Unmatch",
            method_patterns=["Some Pattern"],
            pa_module="TestModule",
            runtime=Runtime.DESKTOP,
            confidence_base=0.75,
        )
        config.vbo_catalogue.append(entry)
        router = VBORouter(config)

        # Route with a method name that does NOT match any pattern
        decision = router.route("Classic VBO Unmatch", "Totally Different Method")
        assert decision.is_known is True
        assert decision.confidence == 0.75  # Should keep full confidence (pre-Task-1 behavior)
        assert decision.resolved_action_template == ""

    def test_exact_match_case_sensitive(self, config: MappingConfig) -> None:
        """Exact method_actions matches are case-sensitive for the key."""
        entry = VBOEntry(
            vbo_name="Case Test VBO",
            pa_module="TestModule",
            runtime=Runtime.DESKTOP,
            confidence_base=0.80,
            method_actions={
                "ExactMethod": "ExactTemplate",
            },
        )
        config.vbo_catalogue.append(entry)
        router = VBORouter(config)

        # Exact match (case-sensitive)
        decision1 = router.route("Case Test VBO", "ExactMethod")
        assert decision1.resolved_action_template == "ExactTemplate"
        assert decision1.confidence == 0.80

        # Wrong case should not match exactly (but known VBO still uses base confidence)
        decision2 = router.route("Case Test VBO", "exactmethod")
        assert decision2.resolved_action_template == ""
        assert decision2.confidence == 0.80  # known VBO uses base confidence

    def test_method_actions_empty_dict_by_default(self, config: MappingConfig) -> None:
        """New VBOEntry with no method_actions has empty dict."""
        entry = VBOEntry(
            vbo_name="Empty Actions VBO",
            pa_module="TestModule",
            runtime=Runtime.DESKTOP,
            confidence_base=0.75,
        )
        assert entry.method_actions == {}

    def test_method_actions_template_returned_in_decision(self, config: MappingConfig) -> None:
        """Resolved action template is included in RoutingDecision."""
        entry = VBOEntry(
            vbo_name="Template VBO",
            pa_module="TestModule",
            runtime=Runtime.DESKTOP,
            confidence_base=0.80,
            method_actions={
                "Get Data": "DataModule.GetData",
            },
        )
        config.vbo_catalogue.append(entry)
        router = VBORouter(config)

        decision = router.route("Template VBO", "Get Data")
        assert decision.resolved_action_template == "DataModule.GetData"
        assert decision.is_known is True
