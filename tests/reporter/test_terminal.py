"""Tests for flowsmith.reporter.terminal - Rich console summary."""

from __future__ import annotations

from rich.console import Console

from flowsmith.ast import BPProcess
from flowsmith.reporter.coverage import build_coverage_report
from flowsmith.reporter.terminal import render_terminal_summary


def test_summary_prints_bands_and_flags(process: BPProcess) -> None:
    console = Console(record=True, width=120)
    render_terminal_summary(build_coverage_report(process), console)
    text = console.export_text()
    assert "Test Process" in text
    for band in ("AUTO", "SPOT_CHECK", "PARTIAL", "MANUAL", "Total"):
        assert band in text
    assert "ReviewFlags: 2 (error: 1, warn: 1, info: 0)" in text
    assert "PARTIAL/MANUAL stages without a ReviewFlag: 2" in text
