"""Tests for flowsmith.engine.annotator — stage annotation."""

from __future__ import annotations

from pathlib import Path

import pytest

from flowsmith.ast import (
    BPDataItem,
    BPPage,
    BPProcess,
    BPStage,
    ConfidenceBand,
    ReviewFlag,
    StageType,
)
from flowsmith.engine import StageAnnotator, create_annotator
from flowsmith.mapper import (
    DataTypeMapper,
    MappingConfig,
    StageRule,
    VBOEntry,
    VBORouter,
    load_rules,
)

# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def config() -> MappingConfig:
    """Load real mapping configuration."""
    return load_rules(force_reload=True)


@pytest.fixture
def vbo_router(config: MappingConfig) -> VBORouter:
    """Create router with real config."""
    return VBORouter(config)


@pytest.fixture
def type_mapper() -> DataTypeMapper:
    """Create type mapper."""
    return DataTypeMapper()


@pytest.fixture
def annotator(
    config: MappingConfig, vbo_router: VBORouter, type_mapper: DataTypeMapper
) -> StageAnnotator:
    """Create annotator with all dependencies."""
    return StageAnnotator(config, vbo_router, type_mapper)


@pytest.fixture
def make_stage():
    """Factory for creating minimal BPStage objects."""

    def _make(
        stage_type: StageType = StageType.START,
        stage_id: str = "s1",
        name: str = "Test Stage",
        **kwargs,
    ) -> BPStage:
        # Build defaults dict, then merge with kwargs to allow overrides
        defaults = {
            "data_items": [],
            "exception_handler_id": None,
            "exception_type": None,
            "pair_id": None,
            "is_subsheet_call": False,
            "params_map": {},
            "pa_annotation": None,
        }
        defaults.update(kwargs)

        return BPStage(
            stage_id=stage_id,
            stage_type=stage_type,
            name=name,
            **defaults,
        )

    return _make


@pytest.fixture
def make_process():
    """Factory for creating BPProcess with stages."""

    def _make(stages: list[BPStage] | None = None) -> BPProcess:
        if stages is None:
            stages = []
        return BPProcess(
            process_id="test_process",
            name="Test Process",
            version="1.0",
            pages=[
                BPPage(
                    page_id="main",
                    name="Main",
                    stages=stages,
                    is_main=True,
                )
            ],
            source_file="/test/process.bprelease",
        )

    return _make


# ── Unit tests ─────────────────────────────────────────────────────────────


class TestUnitAnnotations:
    """Unit tests on synthetic stages."""

    def test_annotate_start_stage(self, annotator: StageAnnotator, make_stage) -> None:
        """START stage annotated with non-None PAAnnotation."""
        stage = make_stage(stage_type=StageType.START)
        annotation = annotator.annotate_stage(stage)
        assert annotation is not None
        assert annotation.confidence >= 0.0

    def test_annotate_end_stage(self, annotator: StageAnnotator, make_stage) -> None:
        """END stage annotated."""
        stage = make_stage(stage_type=StageType.END)
        annotation = annotator.annotate_stage(stage)
        assert annotation is not None

    def test_annotate_decision_stage(self, annotator: StageAnnotator, make_stage) -> None:
        """DECISION stage annotated with confidence > 0."""
        stage = make_stage(stage_type=StageType.DECISION)
        annotation = annotator.annotate_stage(stage)
        assert annotation.confidence > 0

    def test_annotate_calculation_stage(self, annotator: StageAnnotator, make_stage) -> None:
        """CALCULATION stage annotated."""
        stage = make_stage(stage_type=StageType.CALCULATION)
        annotation = annotator.annotate_stage(stage)
        assert annotation is not None

    def test_code_stage_is_manual_band(self, annotator: StageAnnotator, make_stage) -> None:
        """CODE stages always in MANUAL band."""
        stage = make_stage(stage_type=StageType.CODE)
        annotation = annotator.annotate_stage(stage)
        assert annotation.band == ConfidenceBand.MANUAL
        assert annotation.confidence == 0.30

    def test_code_stage_has_error_flag(self, annotator: StageAnnotator, make_stage) -> None:
        """CODE stages have error ReviewFlag."""
        stage = make_stage(stage_type=StageType.CODE)
        annotation = annotator.annotate_stage(stage)
        assert len(annotation.flags) > 0
        assert annotation.flags[0].severity == "error"

    def test_data_stage_target_is_set_variable(self, annotator: StageAnnotator, make_stage) -> None:
        """DATA stage target is SetVariable."""
        stage = make_stage(
            stage_type=StageType.DATA,
            data_items=[
                BPDataItem(
                    name="test_var",
                    data_type="text",
                    initial_value=None,
                    is_input=False,
                    is_output=False,
                )
            ],
        )
        annotation = annotator.annotate_stage(stage)
        assert annotation.target_type == "SetVariable"
        assert annotation.target_module == "Variables"

    def test_data_stage_with_known_type_confidence_085(
        self, annotator: StageAnnotator, make_stage
    ) -> None:
        """DATA stage with known type has confidence 0.85."""
        stage = make_stage(
            stage_type=StageType.DATA,
            data_items=[
                BPDataItem(
                    name="test_var",
                    data_type="text",
                    initial_value=None,
                    is_input=False,
                    is_output=False,
                )
            ],
        )
        annotation = annotator.annotate_stage(stage)
        assert annotation.confidence == 0.85

    def test_data_stage_password_type_has_warn_flag(
        self, annotator: StageAnnotator, make_stage
    ) -> None:
        """DATA stage with password type has warn flag."""
        stage = make_stage(
            stage_type=StageType.DATA,
            data_items=[
                BPDataItem(
                    name="pwd",
                    data_type="password",
                    initial_value=None,
                    is_input=False,
                    is_output=False,
                )
            ],
        )
        annotation = annotator.annotate_stage(stage)
        assert any(f.severity == "warn" for f in annotation.flags)

    def test_collection_stage_target_is_create_datatable(
        self, annotator: StageAnnotator, make_stage
    ) -> None:
        """COLLECTION stage target is CreateNewDataTable."""
        stage = make_stage(stage_type=StageType.COLLECTION)
        annotation = annotator.annotate_stage(stage)
        assert annotation.target_type == "CreateNewDataTable"
        assert annotation.target_module == "Variables"

    def test_collection_stage_confidence_is_075(
        self, annotator: StageAnnotator, make_stage
    ) -> None:
        """COLLECTION stage has confidence 0.75."""
        stage = make_stage(stage_type=StageType.COLLECTION)
        annotation = annotator.annotate_stage(stage)
        assert annotation.confidence == 0.75

    def test_action_subsheet_call_target_is_run_desktop_flow(
        self, annotator: StageAnnotator, make_stage
    ) -> None:
        """ACTION subsheet call target is RunDesktopFlow."""
        stage = make_stage(stage_type=StageType.ACTION, is_subsheet_call=True)
        annotation = annotator.annotate_stage(stage)
        assert annotation.target_type == "RunDesktopFlow"
        assert annotation.target_module == "SubFlow"

    def test_action_subsheet_call_confidence_is_085(
        self, annotator: StageAnnotator, make_stage
    ) -> None:
        """ACTION subsheet call has confidence 0.85."""
        stage = make_stage(stage_type=StageType.ACTION, is_subsheet_call=True)
        annotation = annotator.annotate_stage(stage)
        assert annotation.confidence == 0.85

    def test_action_vbo_call_routes_via_vbo_router(
        self, annotator: StageAnnotator, make_stage
    ) -> None:
        """ACTION VBO call routed via VBORouter."""
        stage = make_stage(
            stage_type=StageType.ACTION,
            params_map={"_vbo_object": "MS Excel VBO", "_vbo_action": "Open Workbook"},
        )
        annotation = annotator.annotate_stage(stage)
        assert annotation.target_type == "Open Workbook"  # Router resolved the VBO action
        assert annotation.confidence > 0  # Router returned a confidence score

    def test_action_unknown_vbo_is_manual_band(self, annotator: StageAnnotator, make_stage) -> None:
        """ACTION stage with unknown VBO is MANUAL band."""
        stage = make_stage(
            stage_type=StageType.ACTION,
            params_map={"_vbo_object": "Unknown VBO", "_vbo_action": "Unknown Method"},
        )
        annotation = annotator.annotate_stage(stage)
        assert annotation.band == ConfidenceBand.MANUAL

    def test_action_process_call_uses_process_rule(
        self, annotator: StageAnnotator, make_stage
    ) -> None:
        """ACTION Process call (is_process_call=True) uses Process stage rule.

        Process-type stages are normalised to ACTION(is_process_call=True) per CLAUDE.md.
        They should use the Process entry from stage_rules.yaml (confidence_base: 0.5)
        rather than falling through to VBO router, which would fail.
        """
        stage = make_stage(
            stage_type=StageType.ACTION,
            is_process_call=True,
            name="Download Config File from SharePoint",
        )
        annotation = annotator.annotate_stage(stage)
        # Should get Process rule: confidence 0.5, PARTIAL band (0.50 <= score < 0.70)
        assert annotation.confidence == 0.5
        assert annotation.band == ConfidenceBand.PARTIAL
        assert annotation.target_module == "External"

    def test_review_flag_stage_id_filled(self, annotator: StageAnnotator, make_stage) -> None:
        """All ReviewFlags have stage_id filled (not empty)."""
        stage = make_stage(stage_type=StageType.CODE, stage_id="s123")
        annotation = annotator.annotate_stage(stage)
        for flag in annotation.flags:
            assert flag.stage_id == "s123", f"Flag has stage_id='{flag.stage_id}', expected 's123'"

    def test_band_matches_confidence(self, annotator: StageAnnotator, make_stage) -> None:
        """Band always matches confidence via ConfidenceBand.from_score()."""
        for _ in [0.0, 0.30, 0.50, 0.75, 0.85, 0.99]:
            stage = make_stage(stage_type=StageType.START)
            # Test that band always matches confidence
            annotation = annotator.annotate_stage(stage)
            expected_band = ConfidenceBand.from_score(annotation.confidence)
            assert annotation.band == expected_band

    def test_annotate_process_mutates_in_place(
        self, annotator: StageAnnotator, make_stage, make_process
    ) -> None:
        """annotate_process() mutates BPProcess in place."""
        stage = make_stage(stage_type=StageType.START)
        process = make_process([stage])
        original_id = id(process)
        returned = annotator.annotate_process(process)
        assert id(returned) == original_id
        assert process.pages[0].stages[0].pa_annotation is not None

    def test_annotate_process_returns_same_object(
        self, annotator: StageAnnotator, make_stage, make_process
    ) -> None:
        """annotate_process() returns the same process object."""
        stage = make_stage(stage_type=StageType.START)
        process = make_process([stage])
        returned = annotator.annotate_process(process)
        assert returned is process

    def test_code_stage_suggested_fix_includes_code_text(
        self, annotator: StageAnnotator, make_stage
    ) -> None:
        """CODE stage suggested_fix embeds the original VBScript body."""
        stage = make_stage(stage_type=StageType.CODE, code_text="some code")
        annotation = annotator.annotate_stage(stage)
        assert "some code" in annotation.flags[0].suggested_fix

    def test_code_stage_suggested_fix_truncates_to_500_chars(
        self, annotator: StageAnnotator, make_stage
    ) -> None:
        """CODE stage suggested_fix only includes the first 500 chars of code_text."""
        long_code = "x" * 1000
        stage = make_stage(stage_type=StageType.CODE, code_text=long_code)
        annotation = annotator.annotate_stage(stage)
        assert ("x" * 500) in annotation.flags[0].suggested_fix
        assert ("x" * 501) not in annotation.flags[0].suggested_fix

    def test_code_stage_without_code_text_has_generic_suggested_fix(
        self, annotator: StageAnnotator, make_stage
    ) -> None:
        """CODE stage with no code_text falls back to the generic suggested_fix."""
        stage = make_stage(stage_type=StageType.CODE, code_text=None)
        annotation = annotator.annotate_stage(stage)
        assert "Original VBScript" not in annotation.flags[0].suggested_fix

    def test_exception_usecurrent_true_throws_error(
        self, annotator: StageAnnotator, make_stage
    ) -> None:
        """EXCEPTION stage with usecurrent=True re-raises via ThrowError/FlowControl."""
        stage = make_stage(stage_type=StageType.EXCEPTION, exception_usecurrent=True)
        annotation = annotator.annotate_stage(stage)
        assert annotation.target_type == "ThrowError"
        assert annotation.target_module == "FlowControl"
        assert annotation.params_map == {}

    def test_exception_usecurrent_false_throws_custom_error(
        self, annotator: StageAnnotator, make_stage
    ) -> None:
        """EXCEPTION stage with usecurrent=False throws a typed custom error."""
        stage = make_stage(
            stage_type=StageType.EXCEPTION,
            exception_usecurrent=False,
            exception_type="Business Exception",
            exception_detail="txt_ExceptionMessage",
        )
        annotation = annotator.annotate_stage(stage)
        assert annotation.target_type == "ThrowCustomError"
        assert annotation.target_module == "FlowControl"
        assert annotation.params_map["exception_type"] == "Business Exception"
        assert annotation.params_map["detail_expr"] == "txt_ExceptionMessage"

    def test_exception_without_type_or_detail_has_warn_flag(
        self, annotator: StageAnnotator, make_stage
    ) -> None:
        """EXCEPTION stage missing both type and detail gets a warn flag."""
        stage = make_stage(
            stage_type=StageType.EXCEPTION,
            exception_usecurrent=False,
            exception_type=None,
            exception_detail=None,
        )
        annotation = annotator.annotate_stage(stage)
        assert any(f.severity == "warn" for f in annotation.flags)


# ── Integration tests ──────────────────────────────────────────────────────


class TestIntegration:
    """Integration tests with real sample."""

    @pytest.mark.skipif(
        not Path("samples/blueprism/PID_0127.bprelease").exists(), reason="Real sample unavailable"
    )
    def test_all_stages_annotated_real_sample(self, real_process) -> None:
        """All stages in real sample have PAAnnotation.

        Count shifted from 6576 to 724 by Task 3a's artefact-isolation fix:
        parse_element() previously walked the whole release document for every
        artefact, so this fixture (which unwraps to processes[0]) was
        accidentally counting all 22 VBO objects' stages too, not just the
        main process's own 18 pages (docs/reviews/3a-2026-08-30-isolation-fixpass.md).
        Shifted from 724 to 725 by Task 4a (prior pass): one Process-type stage
        normalized to ACTION(is_process_call=True) per CLAUDE.md, previously
        had been skipped, now preserved per prior fix.
        Shifted from 725 to 796 by Task 4a (this pass): MultipleCalculation fix
        correctly populates 66 fanned-out sub-stages (from 1 collapsed MC element),
        adding 71 stages net. Prior assertion of 725 was against intermediate build
        state before all fixes applied together.
        """
        create_annotator().annotate_process(real_process)
        total = sum(len(p.stages) for p in real_process.pages)
        annotated = sum(
            1 for p in real_process.pages for s in p.stages if s.pa_annotation is not None
        )
        assert total == annotated == 796

    @pytest.mark.skipif(
        not Path("samples/blueprism/PID_0127.bprelease").exists(), reason="Real sample unavailable"
    )
    def test_no_unannotated_stages_real_sample(self, real_process) -> None:
        """No unannotated stages after annotation."""
        create_annotator().annotate_process(real_process)
        unannotated = [s for p in real_process.pages for s in p.stages if s.pa_annotation is None]
        assert len(unannotated) == 0

    @pytest.mark.skipif(
        not Path("samples/blueprism/PID_0127.bprelease").exists(), reason="Real sample unavailable"
    )
    def test_code_stages_all_manual_real_sample(self, real_process) -> None:
        """All CODE stages in real sample are MANUAL band."""
        create_annotator().annotate_process(real_process)
        code_stages = [
            s for p in real_process.pages for s in p.stages if s.stage_type == StageType.CODE
        ]
        assert all(s.pa_annotation.band == ConfidenceBand.MANUAL for s in code_stages)

    @pytest.mark.skipif(
        not Path("samples/blueprism/PID_0127.bprelease").exists(), reason="Real sample unavailable"
    )
    def test_flag_stage_ids_all_populated_real_sample(self, real_process) -> None:
        """No ReviewFlag has empty stage_id in real sample."""
        create_annotator().annotate_process(real_process)
        for p in real_process.pages:
            for s in p.stages:
                for flag in s.pa_annotation.flags:
                    assert flag.stage_id != "", f"Stage {s.stage_id} has flag with empty stage_id"


# ── Task 8a: ReviewFlag correctness and completeness ──────────────────────

_PID_0171 = Path("samples/blueprism/PID_0171.bprelease")
_ENV_LOCK_VBO = "BluePrism.AutomateAppCore.clsEnvironmentLockingBusinessObject"
_RESULTS_ENTRY_VBO = "PID_0005_Object_US_ SampleResultsEntry"


def _stage_rule(
    bp_stage_type: str, canonical_type: str, confidence: float, notes: str = "", module: str = ""
) -> StageRule:
    """Build a StageRule for a synthetic MappingConfig."""
    return StageRule(
        bp_stage_type=bp_stage_type,
        canonical_type=canonical_type,
        pa_module=module,
        runtime="DESKTOP",
        confidence_base=confidence,
        notes=notes,
    )


def _annotator_for(config: MappingConfig) -> StageAnnotator:
    """Wire a StageAnnotator around a synthetic MappingConfig."""
    return StageAnnotator(config, VBORouter(config), DataTypeMapper())


class TestNormalisedTypeRuleLookup:
    """Item 1: canonical LOOP/WAIT stages resolve to their stage_rules.yaml rows."""

    @pytest.mark.parametrize(
        ("stage_type", "confidence", "band"),
        [
            # LOOP <- LoopStart/LoopEnd: stage_rules.yaml L156/L171, both 0.80
            (StageType.LOOP, 0.80, ConfidenceBand.SPOT_CHECK),
            # WAIT <- WaitStart/WaitEnd: stage_rules.yaml L98/L112, both 0.70
            (StageType.WAIT, 0.70, ConfidenceBand.SPOT_CHECK),
            # CALCULATION <- Calculation (and MultipleCalculation fan-out): 'Calculation' row
            (StageType.CALCULATION, 0.80, ConfidenceBand.SPOT_CHECK),
        ],
    )
    def test_normalised_type_gets_its_rule_not_no_mapping_error(
        self,
        annotator: StageAnnotator,
        make_stage,
        stage_type: StageType,
        confidence: float,
        band: ConfidenceBand,
    ) -> None:
        """No false "No mapping rule" error; confidence comes from the matching row."""
        annotation = annotator.annotate_stage(make_stage(stage_type=stage_type))
        assert not any("No mapping rule" in f.reason for f in annotation.flags)
        assert annotation.flags == []
        assert annotation.confidence == confidence
        assert annotation.band == band

    def test_loop_end_stage_resolves_like_loop_start(
        self, annotator: StageAnnotator, make_stage
    ) -> None:
        """Both brackets of a LOOP pair (pair_id = the Start id) get the same rule."""
        start = make_stage(stage_type=StageType.LOOP, stage_id="ls", pair_id="ls")
        end = make_stage(stage_type=StageType.LOOP, stage_id="le", pair_id="ls")
        a_start, a_end = annotator.annotate_stage(start), annotator.annotate_stage(end)
        assert a_start.confidence == a_end.confidence == 0.80
        assert a_start.target_type == a_end.target_type

    def test_multiple_calculation_fan_out_uses_calculation_row(
        self, annotator: StageAnnotator, make_stage
    ) -> None:
        """A MultipleCalculation sub-stage ('<id>__calc_1') is a plain CALCULATION."""
        stage = make_stage(stage_type=StageType.CALCULATION, stage_id="mc__calc_1")
        annotation = annotator.annotate_stage(stage)
        assert annotation.target_type == "SET <var> TO <expr>"
        assert annotation.confidence == 0.80

    def test_type_with_no_rule_row_still_gets_error(self, make_stage) -> None:
        """A canonical type with no row at all keeps the explicit 'No mapping rule' error."""
        config = MappingConfig(stage_rules=[_stage_rule("Start", "START", 0.95)], vbo_catalogue=[])
        annotation = _annotator_for(config).annotate_stage(make_stage(stage_type=StageType.LOOP))
        assert annotation.band == ConfidenceBand.MANUAL
        assert [f.severity for f in annotation.flags] == ["error"]
        assert "No mapping rule for stage type 'LOOP'" in annotation.flags[0].reason


class TestManualBandErrorFlag:
    """Item 2: every MANUAL annotation carries at least one specific error flag."""

    def test_ui_vbo_call_gets_ui_selector_error(
        self, annotator: StageAnnotator, make_stage
    ) -> None:
        """A SampleResultsEntry UI call (catalogue 0.15, UIAutomation) cites §B9."""
        stage = make_stage(
            stage_type=StageType.ACTION,
            stage_id="ui1",
            params_map={"_vbo_object": _RESULTS_ENTRY_VBO, "_vbo_action": "Enter Values"},
        )
        annotation = annotator.annotate_stage(stage)
        assert annotation.band == ConfidenceBand.MANUAL
        errors = [f for f in annotation.flags if f.severity == "error"]
        assert len(errors) == 1
        assert "needs a UI selector (architecture doc §B9)" in errors[0].reason
        assert "'Enter Values'" in errors[0].reason
        assert errors[0].stage_id == "ui1"
        assert "low confidence" not in errors[0].reason.lower()

    def test_warn_only_env_lock_gets_error_added_after_warn(
        self, annotator: StageAnnotator, make_stage
    ) -> None:
        """Env-lock (0.45, catalogue warn): the warn is kept first, one error appended."""
        stage = make_stage(
            stage_type=StageType.ACTION,
            params_map={"_vbo_object": _ENV_LOCK_VBO, "_vbo_action": "Acquire Lock"},
        )
        annotation = annotator.annotate_stage(stage)
        assert annotation.band == ConfidenceBand.MANUAL
        assert [f.severity for f in annotation.flags] == ["warn", "error"]
        reason = annotation.flags[1].reason
        assert reason.startswith("No catalogue mapping: no method_actions template")
        assert "confidence 0.45" in reason
        assert reason.endswith("Low confidence; needs design review.")

    def test_existing_error_flag_is_not_duplicated(
        self, annotator: StageAnnotator, make_stage
    ) -> None:
        """Unknown VBO and CODE already carry an error; no second one is added."""
        unknown = make_stage(
            stage_type=StageType.ACTION,
            params_map={"_vbo_object": "Unknown VBO", "_vbo_action": "X"},
        )
        code = make_stage(stage_type=StageType.CODE)
        for stage in (unknown, code):
            annotation = annotator.annotate_stage(stage)
            assert annotation.band == ConfidenceBand.MANUAL
            assert [f.severity for f in annotation.flags] == ["error"]

    def test_low_confidence_rule_gets_error_with_full_note(self, make_stage) -> None:
        """Rule path below 0.50 -> one error flag carrying the rule's whole note."""
        note = "Word " * 40 + "ending."
        config = MappingConfig(
            stage_rules=[_stage_rule("Decision", "DECISION", 0.30, notes=note)],
            vbo_catalogue=[],
        )
        stage = make_stage(stage_type=StageType.DECISION)
        annotation = _annotator_for(config).annotate_stage(stage)
        assert [f.severity for f in annotation.flags] == ["error"]
        assert annotation.flags[0].reason.endswith("Word ending.")
        assert "stage_rules.yaml 'Decision' rule" in annotation.flags[0].reason

    def test_low_confidence_process_call_gets_error(self, make_stage) -> None:
        """Process-call path below 0.50 -> one error flag from the 'Process' row's note."""
        config = MappingConfig(
            stage_rules=[_stage_rule("Process", "ACTION", 0.20, notes="Needs routing.")],
            vbo_catalogue=[],
        )
        stage = make_stage(stage_type=StageType.ACTION, is_process_call=True)
        annotation = _annotator_for(config).annotate_stage(stage)
        assert [f.severity for f in annotation.flags] == ["error"]
        assert annotation.flags[0].reason == (
            "confidence 0.20 from stage_rules.yaml 'Process' rule: Needs routing."
        )

    def test_no_derivable_cause_is_stated_honestly(self, make_stage) -> None:
        """A low score with no note and a method template says 'no specific cause recorded'."""
        entry = VBOEntry(
            vbo_name="Bare VBO",
            runtime="DESKTOP",
            confidence_base=0.40,
            method_actions={"Do": "System.Do"},
        )
        config = MappingConfig(stage_rules=[], vbo_catalogue=[entry])
        stage = make_stage(
            stage_type=StageType.ACTION,
            params_map={"_vbo_object": "Bare VBO", "_vbo_action": "Do"},
        )
        annotation = _annotator_for(config).annotate_stage(stage)
        assert annotation.flags[-1].reason == (
            "confidence 0.40 from vbo_catalogue.yaml entry 'Bare VBO'; no specific cause recorded"
        )


class TestPartialBandFlag:
    """Item 3: every PARTIAL annotation carries at least one specific flag."""

    def test_vbo_call_without_template_gets_warn(
        self, annotator: StageAnnotator, make_stage
    ) -> None:
        """File Management_Extended 'File Exists' (0.60, no method_actions) -> one warn."""
        stage = make_stage(
            stage_type=StageType.ACTION,
            params_map={
                "_vbo_object": "Utility - File Management_Extended",
                "_vbo_action": "File Exists",
            },
        )
        annotation = annotator.annotate_stage(stage)
        assert annotation.band == ConfidenceBand.PARTIAL
        assert [f.severity for f in annotation.flags] == ["warn"]
        assert annotation.flags[0].reason.startswith(
            "No catalogue mapping: no method_actions template for 'File Exists'; "
            "confidence 0.60 from vbo_catalogue.yaml entry 'Utility - File Management_Extended'"
        )

    def test_process_call_gets_warn_from_process_rule(
        self, annotator: StageAnnotator, make_stage
    ) -> None:
        """Process call (stage_rules.yaml 'Process', 0.5) -> warn citing that rule's note."""
        stage = make_stage(stage_type=StageType.ACTION, is_process_call=True)
        annotation = annotator.annotate_stage(stage)
        assert annotation.band == ConfidenceBand.PARTIAL
        assert [f.severity for f in annotation.flags] == ["warn"]
        assert annotation.flags[0].reason.startswith(
            "confidence 0.50 from stage_rules.yaml 'Process' rule: Normalises to ACTION."
        )

    @pytest.mark.parametrize("stage_type", [StageType.NAVIGATE, StageType.READ, StageType.WRITE])
    def test_ui_stage_types_get_ui_selector_warn(
        self, annotator: StageAnnotator, make_stage, stage_type: StageType
    ) -> None:
        """NAVIGATE/READ/WRITE (0.65, UIAutomation rows) -> warn citing §B9."""
        annotation = annotator.annotate_stage(make_stage(stage_type=stage_type))
        assert annotation.band == ConfidenceBand.PARTIAL
        assert [f.severity for f in annotation.flags] == ["warn"]
        assert "needs a UI selector (architecture doc §B9)" in annotation.flags[0].reason

    def test_data_stage_without_data_item_gets_warn(
        self, annotator: StageAnnotator, make_stage
    ) -> None:
        """DATA with no data item (0.60 fixed score) -> warn naming the Text default."""
        annotation = annotator.annotate_stage(make_stage(stage_type=StageType.DATA, name="X"))
        assert annotation.band == ConfidenceBand.PARTIAL
        assert [f.severity for f in annotation.flags] == ["warn"]
        assert "has no data item recorded" in annotation.flags[0].reason

    def test_partial_with_existing_flag_gets_nothing_added(
        self, annotator: StageAnnotator, make_stage
    ) -> None:
        """PARTIAL DATA stage with an unknown type keeps only the mapper's warn."""
        stage = make_stage(
            stage_type=StageType.DATA,
            data_items=[BPDataItem(name="v", data_type="weird")],
        )
        annotation = annotator.annotate_stage(stage)
        assert annotation.band == ConfidenceBand.PARTIAL
        assert len(annotation.flags) == 1
        assert "Unknown BP type" in annotation.flags[0].reason

    def test_spot_check_gets_no_flag(self, annotator: StageAnnotator, make_stage) -> None:
        """Band enforcement never touches SPOT-CHECK/AUTO stages."""
        annotation = annotator.annotate_stage(make_stage(stage_type=StageType.DECISION))
        assert annotation.band == ConfidenceBand.SPOT_CHECK
        assert annotation.flags == []


class TestPendingFlagTransfer:
    """Item 4: Task 1b's BPStage.pending_flags reach pa_annotation.flags."""

    @staticmethod
    def _fusion_candidate(make_stage) -> BPStage:
        """A synthetic unresolved fusion-candidate stage, shaped as ast/builder.py builds it."""
        flag = ReviewFlag(
            stage_id="f2",
            reason="Detected numeric-handle handoff from 'Create' (variable 'Handle').",
            severity="warn",
            suggested_fix="Add fusion_patterns entry to vbo_catalogue.yaml",
        )
        return make_stage(
            stage_type=StageType.ACTION,
            stage_id="f2",
            params_map={"_vbo_object": "MS Excel VBO", "_vbo_action": "Open Workbook"},
            pending_flags=[flag],
        )

    def test_pending_flag_transferred(self, annotator: StageAnnotator, make_stage) -> None:
        """The pending flag appears on the annotation with the stage's id."""
        stage = self._fusion_candidate(make_stage)
        annotation = annotator.annotate_stage(stage)
        reasons = [f.reason for f in annotation.flags]
        assert stage.pending_flags[0].reason in reasons
        assert all(f.stage_id == "f2" for f in annotation.flags)

    def test_annotating_twice_does_not_duplicate(
        self, annotator: StageAnnotator, make_stage, make_process
    ) -> None:
        """Running annotate_process twice leaves exactly one copy of the pending flag."""
        stage = self._fusion_candidate(make_stage)
        process = make_process([stage])
        annotator.annotate_process(process)
        annotator.annotate_process(process)
        reason = stage.pending_flags[0].reason
        assert [f.reason for f in stage.pa_annotation.flags].count(reason) == 1

    def test_pending_flag_already_on_annotation_not_duplicated(
        self, annotator: StageAnnotator, make_stage
    ) -> None:
        """A pending flag equal to one the path already produced is not added twice."""
        dup = ReviewFlag(
            stage_id="c1",
            reason=(
                "Code stage contains inline VBScript/VB.NET — "
                "must be rewritten as PowerShell or PAD script action"
            ),
            severity="error",
            suggested_fix="x",
        )
        stage = make_stage(stage_type=StageType.CODE, stage_id="c1", pending_flags=[dup])
        annotation = annotator.annotate_stage(stage)
        assert len(annotation.flags) == 1


@pytest.mark.skipif(not _PID_0171.exists(), reason="PID_0171 sample unavailable")
class TestPid0171FlagContract:
    """Items 1-3 on the real PID_0171 sample (Task 8 report's regression check).

    parse_process + build_ast (processes[0], 'PID_171_US_Process_LIMS_Prelude', 749
    stages) + annotate_process: the same AST `flowsmith convert` writes to ast.json.
    Before Task 8a: AUTO 60 / SPOT_CHECK 640 / PARTIAL 19 / MANUAL 30, flags
    error 14 / warn 5 (docs/reviews/8-2026-09-25.md).
    """

    @pytest.fixture(scope="class")
    def pid171(self) -> BPProcess:
        """Build and annotate PID_0171 once."""
        from flowsmith.ast import build_ast
        from flowsmith.parser import parse_process

        process = build_ast(parse_process(_PID_0171))
        return create_annotator().annotate_process(process)

    @staticmethod
    def _stages(process: BPProcess) -> list[BPStage]:
        """All stages of the process."""
        return [s for p in process.pages for s in p.stages]

    def test_no_false_no_mapping_rule_flags(self, pid171: BPProcess) -> None:
        """0 "No mapping rule" flags; the 14 LOOP stages are SPOT_CHECK at 0.80."""
        stages = self._stages(pid171)
        assert not any("No mapping rule" in f.reason for s in stages for f in s.pa_annotation.flags)
        loops = [s for s in stages if s.stage_type == StageType.LOOP]
        assert len(loops) == 14
        assert all(s.pa_annotation.band == ConfidenceBand.SPOT_CHECK for s in loops)

    def test_every_manual_stage_has_error_flag(self, pid171: BPProcess) -> None:
        """All 16 MANUAL stages (13 with no flag + 3 env-lock warn-only) now have an error."""
        manual = [s for s in self._stages(pid171) if s.pa_annotation.band == ConfidenceBand.MANUAL]
        assert len(manual) == 16
        assert all(any(f.severity == "error" for f in s.pa_annotation.flags) for s in manual)

    def test_every_partial_stage_has_flag(self, pid171: BPProcess) -> None:
        """All 19 PARTIAL stages (none flagged before Task 8a) now carry a flag."""
        partial = [
            s for s in self._stages(pid171) if s.pa_annotation.band == ConfidenceBand.PARTIAL
        ]
        assert len(partial) == 19
        assert all(s.pa_annotation.flags for s in partial)

    def test_band_and_flag_totals(self, pid171: BPProcess) -> None:
        """Totals: the 14 LOOP stages move MANUAL -> SPOT_CHECK; 16 errors / 24 warns.

        error 16 = one per MANUAL stage (12 UI-selector VBO calls, 'Save Attachments',
        3 env-lock calls). warn 24 = 19 PARTIAL band flags + 3 env-lock catalogue
        warns + 2 DATA TimeSpan lossy-type warns.
        """
        from collections import Counter

        stages = self._stages(pid171)
        bands = Counter(s.pa_annotation.band for s in stages)
        assert bands == {
            ConfidenceBand.AUTO: 60,
            ConfidenceBand.SPOT_CHECK: 654,
            ConfidenceBand.PARTIAL: 19,
            ConfidenceBand.MANUAL: 16,
        }
        severities = Counter(f.severity for s in stages for f in s.pa_annotation.flags)
        assert severities == {"error": 16, "warn": 24}
