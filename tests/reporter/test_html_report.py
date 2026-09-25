"""Tests for flowsmith.reporter.html_report - rendering the HTML report."""

from __future__ import annotations

from pathlib import Path

import pytest

from flowsmith.ast import BPProcess
from flowsmith.exceptions import GenerationError
from flowsmith.reporter.coverage import build_coverage_report
from flowsmith.reporter.html_report import (
    DEFAULT_REPORT_FILENAME,
    CoverageHtmlRenderer,
    resolve_output_path,
)


@pytest.fixture
def html(process: BPProcess) -> str:
    """The synthetic process rendered to HTML."""
    return CoverageHtmlRenderer().render(build_coverage_report(process, "in/ast.json"))


class TestRender:
    """Rendered HTML carries every section a developer needs."""

    def test_band_table_with_claude_md_meanings(self, html: str) -> None:
        assert "Coverage by confidence band" in html
        assert "Stub only + ReviewFlag(severity=error)" in html
        assert "Full code + inline comment to verify" in html
        assert "SPOT-CHECK" in html

    def test_flag_entry_context(self, html: str) -> None:
        assert "UI automation - needs a PAD UI selector" in html
        assert "Capture the Login button selector in PAD" in html
        assert "Clicks the login button on the SampleManager window" in html
        assert "PID_0005_Object_US_ SampleResultsEntry" in html
        assert "Window Title" in html and "Login OK" in html

    def test_missing_fix_is_explicit(self, html: str) -> None:
        assert "(none given by the engine)" in html

    def test_unflagged_section_lists_stages(self, html: str) -> None:
        assert "PARTIAL / MANUAL stages with no ReviewFlag" in html
        assert "Delete Input File" in html

    def test_html_is_escaped(self, html: str) -> None:
        assert "Click &lt;Login&gt; Button" in html
        assert "If x &lt; 1 Then" in html
        assert "<Login>" not in html


class TestWrite:
    """Writing to a file or a directory, and error handling."""

    def test_write_to_html_file(self, process: BPProcess, tmp_path: Path) -> None:
        out = tmp_path / "sub" / "report.html"
        written = CoverageHtmlRenderer().write(build_coverage_report(process), out)
        assert written == out
        assert out.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")

    def test_write_to_directory(self, process: BPProcess, tmp_path: Path) -> None:
        written = CoverageHtmlRenderer().write(build_coverage_report(process), tmp_path)
        assert written == tmp_path / DEFAULT_REPORT_FILENAME
        assert written.is_file()

    def test_resolve_output_path_suffixless(self, tmp_path: Path) -> None:
        expected = tmp_path / "new" / DEFAULT_REPORT_FILENAME
        assert resolve_output_path(tmp_path / "new") == expected

    def test_missing_template_dir_raises(self, tmp_path: Path) -> None:
        with pytest.raises(GenerationError, match="Template directory"):
            CoverageHtmlRenderer(tmp_path / "missing")

    def test_missing_template_raises(self, process: BPProcess, tmp_path: Path) -> None:
        with pytest.raises(GenerationError, match="Failed to render"):
            CoverageHtmlRenderer(tmp_path).render(build_coverage_report(process))

    def test_unwritable_target_raises(self, process: BPProcess, tmp_path: Path) -> None:
        blocker = tmp_path / "file.txt"
        blocker.write_text("x", encoding="utf-8")
        with pytest.raises(GenerationError, match="Failed to write"):
            CoverageHtmlRenderer().write(build_coverage_report(process), blocker / "r.html")
