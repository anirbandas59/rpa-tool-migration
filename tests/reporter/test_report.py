"""Tests for flowsmith.reporter.report - input artefact to written report."""

from __future__ import annotations

from pathlib import Path

import pytest

from flowsmith.exceptions import ParseError
from flowsmith.reporter.report import generate_report, load_report


def test_load_report_from_directory(ast_file: Path) -> None:
    report = load_report(ast_file.parent)
    assert report.process_name == "Test Process"
    assert report.input_path == str(ast_file.parent)


def test_generate_report_writes_html(ast_file: Path, tmp_path: Path) -> None:
    report, written = generate_report(ast_file, tmp_path / "report.html")
    assert written.is_file()
    assert report.stage_count == 7
    assert "Test Process" in written.read_text(encoding="utf-8")


def test_generate_report_rejects_zip(tmp_path: Path) -> None:
    zip_path = tmp_path / "x.zip"
    zip_path.write_bytes(b"PK")
    with pytest.raises(ParseError):
        generate_report(zip_path, tmp_path / "r.html")


def test_real_pid0171_report(real_ast: Path, tmp_path: Path) -> None:
    report, written = generate_report(real_ast, tmp_path / "report.html")
    assert written.is_file()
    assert sum(b.count for b in report.bands) == report.stage_count
