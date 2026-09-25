"""Reporter module — developer-facing AUTO/SPOT-CHECK/PARTIAL/MANUAL coverage report (Task 8)."""

from flowsmith.reporter.coverage import build_coverage_report, build_stage_detail
from flowsmith.reporter.html_report import CoverageHtmlRenderer, resolve_output_path
from flowsmith.reporter.loader import load_annotated_process, resolve_ast_path
from flowsmith.reporter.models import (
    BandSummary,
    CoverageReport,
    FlagDetail,
    PageSummary,
    ParamDetail,
    StageDetail,
)
from flowsmith.reporter.report import generate_report, load_report
from flowsmith.reporter.terminal import render_terminal_summary

__all__ = [
    "BandSummary",
    "CoverageHtmlRenderer",
    "CoverageReport",
    "FlagDetail",
    "PageSummary",
    "ParamDetail",
    "StageDetail",
    "build_coverage_report",
    "build_stage_detail",
    "generate_report",
    "load_annotated_process",
    "load_report",
    "render_terminal_summary",
    "resolve_ast_path",
    "resolve_output_path",
]
