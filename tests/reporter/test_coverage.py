"""Tests for flowsmith.reporter.coverage - presenting engine scores and flags."""

from __future__ import annotations

from pathlib import Path

import pytest

from flowsmith.ast import BPProcess, ConfidenceBand, ReviewFlag
from flowsmith.engine import FlagIndexBuilder, ProcessScorer
from flowsmith.exceptions import TransformError
from flowsmith.reporter.coverage import build_coverage_report
from flowsmith.reporter.loader import load_annotated_process
from tests.reporter.conftest import make_process


class TestBands:
    """Band breakdown mirrors ProcessScorer exactly."""

    def test_all_four_bands_in_enum_order(self, process: BPProcess) -> None:
        report = build_coverage_report(process)
        assert [b.band for b in report.bands] == [b.value for b in ConfidenceBand]

    def test_counts_match_scorer_and_sum_to_total(self, process: BPProcess) -> None:
        report = build_coverage_report(process)
        score = ProcessScorer().score_process(process)
        assert {b.band: b.count for b in report.bands if b.count} == score.band_counts
        assert sum(b.count for b in report.bands) == report.stage_count == 7
        assert sum(b.percent for b in report.bands) == pytest.approx(100.0)

    def test_band_stage_lists(self, process: BPProcess) -> None:
        report = build_coverage_report(process)
        by_band = {b.band: [s.stage_id for s in b.stages] for b in report.bands}
        assert by_band["AUTO"] == ["s-start", "s-end"]
        assert by_band["SPOT_CHECK"] == ["s-call", "s-data"]
        assert by_band["PARTIAL"] == ["s-partial"]
        assert by_band["MANUAL"] == ["s-vbo", "s-code"]

    def test_empty_process_has_zero_percent(self) -> None:
        empty = BPProcess(process_id="e", name="E", version="1", source_file="x")
        report = build_coverage_report(empty)
        assert all(b.count == 0 and b.percent == 0.0 for b in report.bands)


class TestFlags:
    """Every ReviewFlag is present, ordered, and hand-off-ready."""

    def test_flag_totals_match_flag_index(self, process: BPProcess) -> None:
        report = build_coverage_report(process)
        index = FlagIndexBuilder().build(process)
        assert report.flag_total == len(index.entries) == 2
        assert report.flag_counts == index.summary_by_severity()

    def test_checklist_order_errors_first(self, process: BPProcess) -> None:
        report = build_coverage_report(process)
        assert [f.severity for f in report.flags] == ["error", "warn"]

    def test_flag_entry_is_hand_off_ready(self, process: BPProcess) -> None:
        flag = build_coverage_report(process).flags[0]
        assert flag.reason == "UI automation - needs a PAD UI selector"
        assert flag.suggested_fix == "Capture the Login button selector in PAD"
        s = flag.stage
        assert (s.page_name, s.stage_name, s.page_role) == (
            "Main Page",
            "Click <Login> Button",
            "loader",
        )
        assert s.narrative.startswith("Clicks the login button")
        assert s.vbo_object == "PID_0005_Object_US_ SampleResultsEntry"
        assert s.vbo_action == "Click Login"
        params = {(p.direction, p.name): (p.data_type, p.binding) for p in s.params}
        assert params[("input", "Window Title")] == ("text", '"SampleManager"')
        assert params[("output", "Success")] == ("flag", "Login OK")
        # A bound parameter with no data item is kept, its type reported as unknown.
        assert params[("input", "Timeout")] == ("unknown", "5")
        # VBO metadata keys are not reported as parameters.
        assert not any(p.name.startswith("_") for p in s.params)

    def test_declared_data_item_and_empty_fix(self, process: BPProcess) -> None:
        flag = build_coverage_report(process).flags[1]
        assert flag.suggested_fix == ""
        assert [(p.direction, p.data_type, p.binding) for p in flag.stage.params] == [
            ("declared", "timespan", "00:00:05")
        ]

    def test_flag_on_unknown_stage_raises(self, process: BPProcess) -> None:
        stage = process.pages[0].stages[0]
        assert stage.pa_annotation is not None
        stage.pa_annotation = stage.pa_annotation.model_copy(
            update={
                "flags": [
                    ReviewFlag(stage_id="ghost", reason="r", severity="info", suggested_fix="")
                ]
            }
        )
        with pytest.raises(TransformError, match="ghost"):
            build_coverage_report(process)


class TestStageContext:
    """Stage context beyond flags: calls, code, pending flags, unflagged list."""

    def test_subsheet_call_resolves_page_name(self, process: BPProcess) -> None:
        report = build_coverage_report(process)
        call = next(s for b in report.bands for s in b.stages if s.stage_id == "s-call")
        assert call.called_page == "Helper"

    def test_process_call_described(self, process: BPProcess) -> None:
        stage = process.pages[0].stages[2]
        stage.processid = "elsewhere"
        stage.is_subsheet_call = False
        stage.is_process_call = True
        report = build_coverage_report(process)
        call = next(s for b in report.bands for s in b.stages if s.stage_id == "s-call")
        assert call.called_page == "external BP process elsewhere"

    def test_unresolved_subsheet_call_described(self, process: BPProcess) -> None:
        process.pages[0].stages[2].processid = "missing-page"
        report = build_coverage_report(process)
        call = next(s for b in report.bands for s in b.stages if s.stage_id == "s-call")
        assert call.called_page == "unresolved page missing-page"

    def test_unflagged_partial_and_manual_listed(self, process: BPProcess) -> None:
        report = build_coverage_report(process)
        assert [s.stage_id for s in report.unflagged_attention] == ["s-partial", "s-code"]
        assert report.unflagged_attention[1].code_text == "If x < 1 Then y = 2"

    def test_pending_flags_surfaced(self, process: BPProcess) -> None:
        process.pages[1].stages[1].pending_flags.append(
            ReviewFlag(
                stage_id="s-partial", reason="fusion candidate", severity="info", suggested_fix=""
            )
        )
        report = build_coverage_report(process)
        assert report.unflagged_attention[0].pending_flag_reasons == ["fusion candidate"]

    def test_pages_roll_up(self, process: BPProcess) -> None:
        report = build_coverage_report(process)
        main, helper = report.pages
        assert (main.page_name, main.role, main.is_main, main.stage_count) == (
            "Main Page",
            "loader",
            True,
            4,
        )
        assert helper.flag_counts == {"warn": 1}
        assert report.readiness == ProcessScorer().score_process(process).migration_readiness

    def test_unannotated_process_raises(self) -> None:
        with pytest.raises(TransformError):
            build_coverage_report(make_process(annotated=False))


class TestRealPid0171:
    """Integration against the Task 7 output in outputs/generated/PID_0171/."""

    def test_real_report_consistent_with_engine(self, real_ast: Path) -> None:
        process = load_annotated_process(real_ast)
        report = build_coverage_report(process, input_path=str(real_ast))
        index = FlagIndexBuilder().build(process)
        total = sum(len(p.stages) for p in process.pages)
        assert sum(b.count for b in report.bands) == report.stage_count == total
        assert report.flag_total == len(index.entries) == len(report.flags)
        assert report.flag_counts == index.summary_by_severity()
        for flag in report.flags:
            assert flag.stage.page_name and flag.stage.stage_name and flag.reason
