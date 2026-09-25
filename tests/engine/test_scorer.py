"""Tests for flowsmith.engine.scorer — process scoring and aggregation."""

from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from flowsmith.ast import (
    BPPage,
    BPProcess,
    BPStage,
    ConfidenceBand,
    PAAnnotation,
    ReviewFlag,
    Runtime,
    StageType,
)
from flowsmith.engine import ProcessScorer, create_annotator
from flowsmith.exceptions import TransformError

# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def scorer() -> ProcessScorer:
    """Create a ProcessScorer instance."""
    return ProcessScorer()


@pytest.fixture
def annotated_process(real_process):
    """Return an annotated copy of the real sample process.

    Makes a deep copy of real_process and runs StageAnnotator on it
    to ensure we don't mutate the shared fixture.

    Args:
        real_process: The session-scoped real_process fixture.

    Returns:
        An annotated copy of real_process with PAAnnotation on all stages.

    Raises:
        pytest.skip: If real sample is not available.
    """
    process_copy = copy.deepcopy(real_process)
    create_annotator().annotate_process(process_copy)
    return process_copy


@pytest.fixture
def make_annotated_stage():
    """Factory for creating BPStage with PAAnnotation.

    Returns a callable that accepts stage_type, confidence, flags,
    and other optional parameters.
    """

    def _make(
        stage_type: StageType = StageType.ACTION,
        stage_id: str = "s1",
        name: str = "Test Stage",
        confidence: float = 0.85,
        flags: list[ReviewFlag] | None = None,
        **kwargs,
    ) -> BPStage:
        if flags is None:
            flags = []

        ann = PAAnnotation(
            target_type="Test.Action",
            target_module="Test",
            runtime=Runtime.DESKTOP,
            params_map={},
            confidence=confidence,
            band=ConfidenceBand.from_score(confidence),
            flags=flags,
        )

        stage = BPStage(
            stage_id=stage_id,
            stage_type=stage_type,
            name=name,
            pa_annotation=ann,
            **kwargs,
        )
        return stage

    return _make


@pytest.fixture
def make_annotated_page():
    """Factory for creating BPPage with annotated stages.

    Returns a callable that accepts a list of BPStage objects.
    """

    def _make(
        stages: list[BPStage] | None = None,
        page_id: str = "p1",
        name: str = "Test Page",
        is_main: bool = False,
    ) -> BPPage:
        if stages is None:
            stages = []
        return BPPage(
            page_id=page_id,
            name=name,
            is_main=is_main,
            stages=stages,
        )

    return _make


@pytest.fixture
def make_annotated_process():
    """Factory for creating BPProcess with annotated pages.

    Returns a callable that accepts a list of BPPage objects.
    """

    def _make(
        pages: list[BPPage] | None = None,
        process_id: str = "p1",
        name: str = "Test Process",
        version: str = "1.0",
        source_file: str = "test.bprelease",
    ) -> BPProcess:
        if pages is None:
            pages = []
        return BPProcess(
            process_id=process_id,
            name=name,
            version=version,
            pages=pages,
            source_file=source_file,
        )

    return _make


# ── Unit tests (synthetic stages) ──────────────────────────────────────────


class TestScoreStage:
    """Tests for ProcessScorer.score_stage()."""

    def test_score_stage_returns_stage_summary(self, scorer, make_annotated_stage):
        """score_stage returns a StageSummary."""
        stage = make_annotated_stage(stage_id="s1", name="Test")
        summary = scorer.score_stage(stage)

        assert summary.stage_id == "s1"
        assert summary.name == "Test"
        assert summary.stage_type == "ACTION"

    def test_score_stage_confidence_matches_annotation(self, scorer, make_annotated_stage):
        """score_stage preserves confidence from PAAnnotation."""
        stage = make_annotated_stage(confidence=0.75)
        summary = scorer.score_stage(stage)

        assert summary.confidence == 0.75

    def test_score_stage_band_matches_confidence(self, scorer, make_annotated_stage):
        """score_stage band matches ConfidenceBand.from_score(confidence)."""
        stage = make_annotated_stage(confidence=0.95)
        summary = scorer.score_stage(stage)

        assert summary.band == ConfidenceBand.AUTO

    def test_score_stage_has_error_true_when_error_flag(self, scorer, make_annotated_stage):
        """score_stage.has_error=True when any flag has severity='error'."""
        error_flag = ReviewFlag(
            stage_id="s1",
            reason="Test error",
            severity="error",
            suggested_fix="Fix it",
        )
        stage = make_annotated_stage(flags=[error_flag])
        summary = scorer.score_stage(stage)

        assert summary.has_error is True

    def test_score_stage_has_warn_true_when_warn_flag(self, scorer, make_annotated_stage):
        """score_stage.has_warn=True when any flag has severity='warn'."""
        warn_flag = ReviewFlag(
            stage_id="s1",
            reason="Test warning",
            severity="warn",
            suggested_fix="Check it",
        )
        stage = make_annotated_stage(flags=[warn_flag])
        summary = scorer.score_stage(stage)

        assert summary.has_warn is True

    def test_score_stage_flag_count_correct(self, scorer, make_annotated_stage):
        """score_stage.flag_count matches number of flags."""
        flags = [
            ReviewFlag(
                stage_id="s1",
                reason="Flag 1",
                severity="warn",
                suggested_fix="Fix",
            ),
            ReviewFlag(
                stage_id="s1",
                reason="Flag 2",
                severity="error",
                suggested_fix="Fix",
            ),
        ]
        stage = make_annotated_stage(flags=flags)
        summary = scorer.score_stage(stage)

        assert summary.flag_count == 2

    def test_score_stage_raises_transform_error_if_unannotated(self, scorer):
        """score_stage raises TransformError if pa_annotation is None."""
        stage = BPStage(
            stage_id="s1",
            stage_type=StageType.ACTION,
            name="Unannotated",
            pa_annotation=None,
        )

        with pytest.raises(TransformError, match="has no PAAnnotation"):
            scorer.score_stage(stage)


class TestScorePage:
    """Tests for ProcessScorer.score_page()."""

    def test_score_page_returns_page_score(self, scorer, make_annotated_stage, make_annotated_page):
        """score_page returns a PageScore."""
        stage = make_annotated_stage()
        page = make_annotated_page(stages=[stage])
        page_score = scorer.score_page(page)

        assert page_score.page_id == "p1"
        assert page_score.page_name == "Test Page"
        assert len(page_score.stages) == 1

    def test_score_page_stage_count_correct(
        self, scorer, make_annotated_stage, make_annotated_page
    ):
        """score_page.stage_count matches number of stages."""
        stages = [make_annotated_stage(stage_id=f"s{i}", name=f"Stage {i}") for i in range(3)]
        page = make_annotated_page(stages=stages)
        page_score = scorer.score_page(page)

        assert page_score.stage_count == 3

    def test_score_page_mean_confidence_correct(
        self, scorer, make_annotated_stage, make_annotated_page
    ):
        """score_page.mean_confidence is mean of stage confidences."""
        stages = [
            make_annotated_stage(stage_id="s1", confidence=0.8),
            make_annotated_stage(stage_id="s2", confidence=0.6),
        ]
        page = make_annotated_page(stages=stages)
        page_score = scorer.score_page(page)

        assert page_score.mean_confidence == pytest.approx(0.7)

    def test_score_page_band_from_mean_confidence(
        self, scorer, make_annotated_stage, make_annotated_page
    ):
        """score_page.band is derived from mean_confidence."""
        stages = [
            make_annotated_stage(stage_id="s1", confidence=0.8),
            make_annotated_stage(stage_id="s2", confidence=0.6),
        ]
        page = make_annotated_page(stages=stages)
        page_score = scorer.score_page(page)

        assert page_score.band == ConfidenceBand.SPOT_CHECK

    def test_score_page_band_counts_correct(
        self, scorer, make_annotated_stage, make_annotated_page
    ):
        """score_page.band_counts aggregates correctly."""
        stages = [
            make_annotated_stage(stage_id="s1", confidence=0.95),
            make_annotated_stage(stage_id="s2", confidence=0.95),
            make_annotated_stage(stage_id="s3", confidence=0.3),
        ]
        page = make_annotated_page(stages=stages)
        page_score = scorer.score_page(page)

        assert page_score.band_counts.get("AUTO") == 2
        assert page_score.band_counts.get("MANUAL") == 1

    def test_score_page_flag_counts_by_severity(
        self, scorer, make_annotated_stage, make_annotated_page
    ):
        """score_page.flag_counts breaks down flags by severity."""
        error_flag = ReviewFlag(
            stage_id="s1",
            reason="Error",
            severity="error",
            suggested_fix="Fix",
        )
        warn_flag = ReviewFlag(
            stage_id="s2",
            reason="Warning",
            severity="warn",
            suggested_fix="Check",
        )
        stages = [
            make_annotated_stage(stage_id="s1", flags=[error_flag]),
            make_annotated_stage(stage_id="s2", flags=[warn_flag]),
        ]
        page = make_annotated_page(stages=stages)
        page_score = scorer.score_page(page)

        assert page_score.flag_counts.get("error") == 1
        assert page_score.flag_counts.get("warn") == 1

    def test_score_page_empty_page_returns_zero_confidence(self, scorer, make_annotated_page):
        """score_page with no stages returns mean_confidence=0.0."""
        page = make_annotated_page(stages=[])
        page_score = scorer.score_page(page)

        assert page_score.mean_confidence == 0.0
        assert page_score.stage_count == 0


class TestScoreProcess:
    """Tests for ProcessScorer.score_process()."""

    def test_score_process_returns_process_score(
        self, scorer, make_annotated_stage, make_annotated_page, make_annotated_process
    ):
        """score_process returns a ProcessScore."""
        stage = make_annotated_stage()
        page = make_annotated_page(stages=[stage])
        process = make_annotated_process(pages=[page])

        score = scorer.score_process(process)

        assert score.process_id == "p1"
        assert score.process_name == "Test Process"
        assert score.page_count == 1

    def test_score_process_stage_count_correct(
        self, scorer, make_annotated_stage, make_annotated_page, make_annotated_process
    ):
        """score_process.stage_count is total across all pages."""
        page1 = make_annotated_page(
            stages=[
                make_annotated_stage(stage_id="s1"),
                make_annotated_stage(stage_id="s2"),
            ],
            page_id="p1",
        )
        page2 = make_annotated_page(
            stages=[
                make_annotated_stage(stage_id="s3"),
            ],
            page_id="p2",
        )
        process = make_annotated_process(pages=[page1, page2])

        score = scorer.score_process(process)

        assert score.stage_count == 3

    def test_score_process_page_count_correct(
        self, scorer, make_annotated_page, make_annotated_process
    ):
        """score_process.page_count matches number of pages."""
        pages = [make_annotated_page(page_id=f"p{i}", stages=[]) for i in range(3)]
        process = make_annotated_process(pages=pages)

        score = scorer.score_process(process)

        assert score.page_count == 3

    def test_score_process_mean_is_weighted_not_page_mean(
        self, scorer, make_annotated_stage, make_annotated_page, make_annotated_process
    ):
        """score_process.mean_confidence is weighted by stage count, not page mean."""
        # Page 1: 100 stages at confidence 0.9
        page1_stages = [make_annotated_stage(stage_id=f"s{i}", confidence=0.9) for i in range(100)]
        page1 = make_annotated_page(stages=page1_stages, page_id="p1")

        # Page 2: 1 stage at confidence 0.1
        page2 = make_annotated_page(
            stages=[make_annotated_stage(stage_id="s101", confidence=0.1)],
            page_id="p2",
        )

        process = make_annotated_process(pages=[page1, page2])
        score = scorer.score_process(process)

        # Weighted mean: (100*0.9 + 1*0.1) / 101 ≈ 0.893
        expected_mean = (100 * 0.9 + 1 * 0.1) / 101
        assert score.mean_confidence == pytest.approx(expected_mean)

    def test_score_process_band_counts_aggregate_correctly(
        self, scorer, make_annotated_stage, make_annotated_page, make_annotated_process
    ):
        """score_process.band_counts aggregates across all pages."""
        page1 = make_annotated_page(
            stages=[
                make_annotated_stage(stage_id="s1", confidence=0.95),
                make_annotated_stage(stage_id="s2", confidence=0.95),
            ],
            page_id="p1",
        )
        page2 = make_annotated_page(
            stages=[
                make_annotated_stage(stage_id="s3", confidence=0.3),
            ],
            page_id="p2",
        )
        process = make_annotated_process(pages=[page1, page2])

        score = scorer.score_process(process)

        assert score.band_counts.get("AUTO") == 2
        assert score.band_counts.get("MANUAL") == 1

    def test_score_process_auto_count_property(
        self, scorer, make_annotated_stage, make_annotated_page, make_annotated_process
    ):
        """score_process.auto_count matches AUTO band count."""
        page = make_annotated_page(
            stages=[
                make_annotated_stage(stage_id="s1", confidence=0.95),
                make_annotated_stage(stage_id="s2", confidence=0.3),
            ]
        )
        process = make_annotated_process(pages=[page])

        score = scorer.score_process(process)

        assert score.auto_count == 1

    def test_score_process_manual_count_property(
        self, scorer, make_annotated_stage, make_annotated_page, make_annotated_process
    ):
        """score_process.manual_count matches MANUAL band count."""
        page = make_annotated_page(
            stages=[
                make_annotated_stage(stage_id="s1", confidence=0.95),
                make_annotated_stage(stage_id="s2", confidence=0.3),
            ]
        )
        process = make_annotated_process(pages=[page])

        score = scorer.score_process(process)

        assert score.manual_count == 1

    def test_score_process_error_flag_count_property(
        self, scorer, make_annotated_stage, make_annotated_page, make_annotated_process
    ):
        """score_process.error_flag_count sums error flags."""
        error1 = ReviewFlag(
            stage_id="s1",
            reason="Error 1",
            severity="error",
            suggested_fix="Fix",
        )
        error2 = ReviewFlag(
            stage_id="s2",
            reason="Error 2",
            severity="error",
            suggested_fix="Fix",
        )
        page = make_annotated_page(
            stages=[
                make_annotated_stage(stage_id="s1", flags=[error1]),
                make_annotated_stage(stage_id="s2", flags=[error2]),
            ]
        )
        process = make_annotated_process(pages=[page])

        score = scorer.score_process(process)

        assert score.error_flag_count == 2

    def test_score_process_warn_flag_count_property(
        self, scorer, make_annotated_stage, make_annotated_page, make_annotated_process
    ):
        """score_process.warn_flag_count sums warn flags."""
        warn1 = ReviewFlag(
            stage_id="s1",
            reason="Warn 1",
            severity="warn",
            suggested_fix="Check",
        )
        warn2 = ReviewFlag(
            stage_id="s2",
            reason="Warn 2",
            severity="warn",
            suggested_fix="Check",
        )
        page = make_annotated_page(
            stages=[
                make_annotated_stage(stage_id="s1", flags=[warn1]),
                make_annotated_stage(stage_id="s2", flags=[warn2]),
            ]
        )
        process = make_annotated_process(pages=[page])

        score = scorer.score_process(process)

        assert score.warn_flag_count == 2

    def test_score_process_raises_if_unannotated_stage(
        self, scorer, make_annotated_page, make_annotated_process
    ):
        """score_process raises TransformError if any stage lacks annotation."""
        unannotated = BPStage(
            stage_id="s1",
            stage_type=StageType.ACTION,
            name="Unannotated",
            pa_annotation=None,
        )
        page = BPPage(page_id="p1", name="Test", stages=[unannotated])
        process = make_annotated_process(pages=[page])

        with pytest.raises(TransformError, match="has no PAAnnotation"):
            scorer.score_process(process)


class TestMigrationReadiness:
    """Tests for ProcessScore.migration_readiness property."""

    def test_migration_readiness_ready(
        self, scorer, make_annotated_stage, make_annotated_page, make_annotated_process
    ):
        """readiness='Ready' when manual_count=0 and mean>=0.85."""
        page = make_annotated_page(
            stages=[
                make_annotated_stage(stage_id="s1", confidence=0.90),
            ]
        )
        process = make_annotated_process(pages=[page])
        score = scorer.score_process(process)

        assert score.migration_readiness == "Ready"

    def test_migration_readiness_minor(
        self, scorer, make_annotated_stage, make_annotated_page, make_annotated_process
    ):
        """readiness='Minor review needed' when manual<=10 and mean>=0.70."""
        # 18 stages at 0.80 (SPOT_CHECK) + 2 at 0.3 (MANUAL) = mean 0.75
        stages = [make_annotated_stage(stage_id=f"s{i}", confidence=0.80) for i in range(18)] + [
            make_annotated_stage(stage_id=f"s{i}", confidence=0.3) for i in range(18, 20)
        ]
        page = make_annotated_page(stages=stages)
        process = make_annotated_process(pages=[page])
        score = scorer.score_process(process)

        assert score.manual_count <= 10
        assert score.mean_confidence >= 0.70
        assert score.migration_readiness == "Minor review needed"

    def test_migration_readiness_significant(
        self, scorer, make_annotated_stage, make_annotated_page, make_annotated_process
    ):
        """readiness='Significant review needed' when manual<=50 and mean>=0.50."""
        # 40 stages at 0.55 (PARTIAL) + 10 at 0.3 (MANUAL) = mean 0.50
        stages = [make_annotated_stage(stage_id=f"s{i}", confidence=0.55) for i in range(40)] + [
            make_annotated_stage(stage_id=f"s{i}", confidence=0.3) for i in range(40, 50)
        ]
        page = make_annotated_page(stages=stages)
        process = make_annotated_process(pages=[page])
        score = scorer.score_process(process)

        assert score.manual_count <= 50
        assert score.mean_confidence >= 0.50
        assert score.migration_readiness == "Significant review needed"

    def test_migration_readiness_major(
        self, scorer, make_annotated_stage, make_annotated_page, make_annotated_process
    ):
        """readiness='Major rework required' otherwise."""
        stages = [make_annotated_stage(stage_id=f"s{i}", confidence=0.3) for i in range(100)]
        page = make_annotated_page(stages=stages)
        process = make_annotated_process(pages=[page])
        score = scorer.score_process(process)

        assert score.migration_readiness == "Major rework required"


class TestPercentageProperties:
    """Tests for percentage properties on ProcessScore."""

    def test_auto_pct_property(
        self, scorer, make_annotated_stage, make_annotated_page, make_annotated_process
    ):
        """auto_pct returns percentage of stages in AUTO band."""
        stages = [
            make_annotated_stage(stage_id="s1", confidence=0.95),
            make_annotated_stage(stage_id="s2", confidence=0.95),
            make_annotated_stage(stage_id="s3", confidence=0.3),
        ]
        page = make_annotated_page(stages=stages)
        process = make_annotated_process(pages=[page])
        score = scorer.score_process(process)

        assert score.auto_pct == pytest.approx(66.66, abs=0.1)

    def test_manual_pct_property(
        self, scorer, make_annotated_stage, make_annotated_page, make_annotated_process
    ):
        """manual_pct returns percentage of stages in MANUAL band."""
        stages = [
            make_annotated_stage(stage_id="s1", confidence=0.95),
            make_annotated_stage(stage_id="s2", confidence=0.95),
            make_annotated_stage(stage_id="s3", confidence=0.3),
        ]
        page = make_annotated_page(stages=stages)
        process = make_annotated_process(pages=[page])
        score = scorer.score_process(process)

        assert score.manual_pct == pytest.approx(33.33, abs=0.1)


class TestPageProperties:
    """Tests for properties on PageScore."""

    def test_page_error_count_property(self, scorer, make_annotated_stage, make_annotated_page):
        """PageScore.error_count returns error flag count."""
        error_flag = ReviewFlag(
            stage_id="s1",
            reason="Error",
            severity="error",
            suggested_fix="Fix",
        )
        page = make_annotated_page(stages=[make_annotated_stage(stage_id="s1", flags=[error_flag])])
        page_score = scorer.score_page(page)

        assert page_score.error_count == 1

    def test_page_warn_count_property(self, scorer, make_annotated_stage, make_annotated_page):
        """PageScore.warn_count returns warn flag count."""
        warn_flag = ReviewFlag(
            stage_id="s1",
            reason="Warning",
            severity="warn",
            suggested_fix="Check",
        )
        page = make_annotated_page(stages=[make_annotated_stage(stage_id="s1", flags=[warn_flag])])
        page_score = scorer.score_page(page)

        assert page_score.warn_count == 1


class TestModelImmutability:
    """Tests for frozen state on all summary models."""

    def test_stage_summary_is_frozen(self, scorer, make_annotated_stage):
        """StageSummary is frozen and cannot be modified."""
        stage = make_annotated_stage()
        summary = scorer.score_stage(stage)

        with pytest.raises(ValidationError):
            summary.confidence = 0.5

    def test_page_score_is_frozen(self, scorer, make_annotated_stage, make_annotated_page):
        """PageScore is frozen and cannot be modified."""
        page = make_annotated_page(stages=[make_annotated_stage()])
        page_score = scorer.score_page(page)

        with pytest.raises(ValidationError):
            page_score.mean_confidence = 0.5

    def test_process_score_is_frozen(
        self, scorer, make_annotated_stage, make_annotated_page, make_annotated_process
    ):
        """ProcessScore is frozen and cannot be modified."""
        page = make_annotated_page(stages=[make_annotated_stage()])
        process = make_annotated_process(pages=[page])
        score = scorer.score_process(process)

        with pytest.raises(ValidationError):
            score.mean_confidence = 0.5


# ── Integration tests (real sample) ────────────────────────────────────────


class TestRealSampleScoring:
    """Integration tests using the real sample process."""

    def test_real_sample_stage_count_724(self, scorer, annotated_process):
        """Real sample has exactly 796 stages.

        Shifted from 6576 by Task 3a's artefact-isolation fix: parse_element()
        previously walked the whole release document (root.iter(...)) for every
        artefact, so the "real sample" fixture (which unwraps to processes[0])
        was accidentally scored against all 22 VBO objects' stages too, not just
        the main process's own 18 pages. Now correctly scoped to the main
        process alone (docs/reviews/3a-2026-08-30-isolation-fixpass.md).
        Shifted from 724 to 725 by Task 4a (prior pass): one Process-type stage
        normalized to ACTION(is_process_call=True) per CLAUDE.md, previously
        had been skipped, now preserved per prior fix.
        Shifted from 725 to 796 by Task 4a (this pass): MultipleCalculation fix
        (Task 4a's own Fix 2) now correctly populates and fans out 66 sub-stages
        from 1 collapsed calculation element, adding 71 stages net (66 sub-stages
        - 1 original = +65 from MC fix, plus new reachability/stage type corrections
        from Block→Recover fix). Prior test assertion of 725 was against intermediate
        build state before all fixes fully applied together.
        """
        score = scorer.score_process(annotated_process)
        assert score.stage_count == 796

    def test_real_sample_auto_count_51(self, scorer, annotated_process):
        """Real sample has 51 AUTO stages.

        Shifted from 1125 by Task 3a's artefact-isolation fix (see
        test_real_sample_stage_count_724) — the real_process fixture now
        reflects only the main process's own stages.
        """
        score = scorer.score_process(annotated_process)
        assert score.auto_count == 51

    def test_real_sample_spot_check_count_623(self, scorer, annotated_process):
        """Real sample has 694 SPOT_CHECK stages.

        Shifted from 4808 by Task 3a's artefact-isolation fix (see
        test_real_sample_stage_count_724).
        Shifted from 623 to 694 by Task 4a (this pass): MultipleCalculation fix
        adds 71 calculation stages, most classified as SPOT_CHECK confidence band,
        increasing overall SPOT_CHECK count. Reflects stage_count change from 725→796.
        Shifted from 694 to 710 by Task 8a item 1: the 16 LOOP stages of
        PID_0127_Process_US_BulkUnlock now resolve to stage_rules.yaml's LoopStart row
        (confidence 0.80 → SPOT_CHECK) instead of the false "No mapping rule"
        (0.0 → MANUAL); 694 + 16 = 710. The "623" in the name is historical.
        """
        score = scorer.score_process(annotated_process)
        assert score.spot_check_count == 710

    def test_real_sample_partial_count_30(self, scorer, annotated_process):
        """Real sample has 31 PARTIAL stages.

        Shifted from 152 by Task 3a's artefact-isolation fix (see
        test_real_sample_stage_count_724); the prior 154->152 shift from
        Task 2b's catalogue corrections (Excel method_patterns rewrite, 6 new
        VBO entries including the fixed PID_0005 space key, SharePoint
        confidence change 0.65->0.45) still applies within the correctly
        scoped main-process-only stage set.
        Shifted from 30 to 31 by Task 4a (this pass): one Process-type stage
        now preserved with confidence 0.5 (PARTIAL band).
        """
        score = scorer.score_process(annotated_process)
        assert score.partial_count == 31

    def test_real_sample_manual_count_20(self, scorer, annotated_process):
        """Real sample has 20 MANUAL stages.

        Shifted from 491 by Task 3a's artefact-isolation fix (see
        test_real_sample_stage_count_724); the prior 489->491 shift from
        Task 2b's catalogue corrections still applies within the correctly
        scoped main-process-only stage set.
        Shifted from 20 to 4 by Task 8a item 1: the 16 LOOP stages leave MANUAL
        (now SPOT_CHECK, see test_real_sample_spot_check_count_623). The 4 left are
        VBO calls at catalogue confidence 0.45: 3 clsEnvironmentLockingBusinessObject
        calls (1 'Acquire Lock', 2 'Release Lock') and 'FormatReport'
        (Utility_Object_Format_Queue_Report 'Format Excel(Standard)').
        The "20" in the name is historical.
        """
        score = scorer.score_process(annotated_process)
        assert score.manual_count == 4

    def test_real_sample_error_flag_count_16(self, scorer, annotated_process):
        """Real sample has 16 error flags.

        Shifted from 485 by Task 3a's artefact-isolation fix (see
        test_real_sample_stage_count_724).
        Shifted from 16 to 4 by Task 8a: the 16 were the false "No mapping rule for
        stage type 'LOOP'" errors (removed by item 1); the 4 now are one
        band-mandated error per MANUAL stage (item 2) — the 4 stages listed in
        test_real_sample_manual_count_20. The "16" in the name is historical.
        """
        score = scorer.score_process(annotated_process)
        assert score.error_flag_count == 4

    def test_real_sample_warn_flag_count_4(self, scorer, annotated_process):
        """Real sample has 4 warn flags.

        Shifted from 53 by Task 3a's artefact-isolation fix (see
        test_real_sample_stage_count_724).
        Shifted from 4 to 35 by Task 8a item 3: the 4 existing warns (3 env-lock
        catalogue review_severity=warn flags + 1 DataTypeMapper TimeSpan flag on DATA
        'tmspan_Worktime') plus one band-mandated warn on each of the 31 PARTIAL
        stages (30 VBO calls + 1 Process call), none of which had a flag before;
        4 + 31 = 35. The "4" in the name is historical.
        """
        score = scorer.score_process(annotated_process)
        assert score.warn_flag_count == 35

    def test_real_sample_page_count_18(self, scorer, annotated_process):
        """Real sample has 19 pages.

        Shifted from 399 by Task 3a's artefact-isolation fix (see
        test_real_sample_stage_count_724) — 399 was the whole release
        document's page count (main process + 21 other artefacts), not the
        main process's own 18 pages.
        Shifted from 18 to 19 by Task 4a (prior pass): the main page was
        incorrectly identified; the fix creates a new separate main page for
        implicit main-flow stages, leaving previously-mis-picked subsheet as
        its own separate page (docs/reviews/4a-2026-08-30-fixpass.md).
        """
        score = scorer.score_process(annotated_process)
        assert score.page_count == 19

    def test_real_sample_migration_readiness_not_empty(self, scorer, annotated_process):
        """Real sample migration_readiness is a non-empty string."""
        score = scorer.score_process(annotated_process)
        assert isinstance(score.migration_readiness, str)
        assert len(score.migration_readiness) > 0

    def test_real_sample_mean_confidence_in_range(self, scorer, annotated_process):
        """Real sample mean_confidence is in [0.0, 1.0]."""
        score = scorer.score_process(annotated_process)
        assert 0.0 <= score.mean_confidence <= 1.0

    def test_real_sample_no_unannotated_in_score(self, scorer, annotated_process):
        """Sum of band_counts equals stage_count for real sample."""
        score = scorer.score_process(annotated_process)
        total_bands = sum(score.band_counts.values())
        assert total_bands == score.stage_count
