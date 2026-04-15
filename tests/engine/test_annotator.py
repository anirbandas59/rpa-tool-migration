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
    StageType,
)
from flowsmith.engine import StageAnnotator, create_annotator
from flowsmith.mapper import DataTypeMapper, MappingConfig, VBORouter, load_rules

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


# ── Integration tests ──────────────────────────────────────────────────────


class TestIntegration:
    """Integration tests with real sample."""

    @pytest.mark.skipif(
        not Path("samples/blueprism/PID_0127.bprelease").exists(), reason="Real sample unavailable"
    )
    def test_all_stages_annotated_real_sample(self, real_process) -> None:
        """All stages in real sample have PAAnnotation."""
        create_annotator().annotate_process(real_process)
        total = sum(len(p.stages) for p in real_process.pages)
        annotated = sum(
            1 for p in real_process.pages for s in p.stages if s.pa_annotation is not None
        )
        assert total == annotated == 6576

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
