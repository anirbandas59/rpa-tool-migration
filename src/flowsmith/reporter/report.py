"""Report orchestration — input artefact to written coverage report.

Kept out of ``cli/app.py`` so the CLI stays pure typer wiring.
"""

from __future__ import annotations

from pathlib import Path

from flowsmith.reporter.coverage import build_coverage_report
from flowsmith.reporter.html_report import CoverageHtmlRenderer
from flowsmith.reporter.loader import load_annotated_process
from flowsmith.reporter.models import CoverageReport


def load_report(input_path: Path) -> CoverageReport:
    """Load an annotated AST and build its coverage report (no file written).

    Args:
        input_path: ``ast.json`` written by ``flowsmith convert``, or its output directory.

    Returns:
        The built CoverageReport.

    Raises:
        ParseError: If the input cannot be resolved or read.
        ASTBuildError: If the AST JSON is invalid.
        TransformError: If annotation/scoring fails or engine totals disagree.
    """
    process = load_annotated_process(input_path)
    return build_coverage_report(process, input_path=str(input_path))


def generate_report(
    input_path: Path, output: Path, template_dir: Path | None = None
) -> tuple[CoverageReport, Path]:
    """Load an annotated AST, build the coverage report and write it as HTML.

    Args:
        input_path: ``ast.json`` written by ``flowsmith convert``, or its output directory.
        output: Target ``.html`` file, or a directory to write ``coverage_report.html`` into.
        template_dir: Optional override for the report template directory.

    Returns:
        The built CoverageReport and the path of the written HTML file.

    Raises:
        ParseError: If the input cannot be resolved or read.
        ASTBuildError: If the AST JSON is invalid.
        TransformError: If annotation/scoring fails or engine totals disagree.
        GenerationError: If the HTML cannot be rendered or written.
    """
    report = load_report(input_path)
    written = CoverageHtmlRenderer(template_dir).write(report, output)
    return report, written
