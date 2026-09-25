"""HTML rendering of a CoverageReport via the Jinja2 template in templates/report/coverage/."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateError, select_autoescape

from flowsmith.exceptions import GenerationError
from flowsmith.reporter.models import CoverageReport

TEMPLATE_NAME = "coverage_report.html.j2"
DEFAULT_REPORT_FILENAME = "coverage_report.html"


def resolve_output_path(output: Path) -> Path:
    """Resolve the ``--output`` value to the HTML file to write.

    Args:
        output: A target ``.html`` file path, or a directory to write
            ``coverage_report.html`` into.

    Returns:
        Path of the HTML file to write.
    """
    if output.is_dir() or not output.suffix:
        return output / DEFAULT_REPORT_FILENAME
    return output


class CoverageHtmlRenderer:
    """Render a CoverageReport to a standalone HTML page."""

    def __init__(self, template_dir: Path | None = None) -> None:
        """Set up the Jinja2 environment.

        Args:
            template_dir: Override for the template directory; defaults to
                ``templates/report/coverage`` under the working directory
                (same convention as ``generator.packager``).

        Raises:
            GenerationError: If the template directory does not exist.
        """
        if template_dir is None:
            template_dir = Path.cwd() / "templates" / "report" / "coverage"
        if not template_dir.is_dir():
            raise GenerationError(f"Template directory not found: {template_dir.absolute()}")
        self.template_dir = template_dir
        self.env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            undefined=StrictUndefined,
            autoescape=select_autoescape(enabled_extensions=("html", "j2"), default=True),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render(self, report: CoverageReport) -> str:
        """Render the report to an HTML string.

        Args:
            report: The coverage report.

        Returns:
            Complete HTML document text.

        Raises:
            GenerationError: If the template is missing or fails to render.
        """
        try:
            template = self.env.get_template(TEMPLATE_NAME)
            return template.render(report=report)
        except TemplateError as exc:
            raise GenerationError(f"Failed to render coverage report: {exc}") from exc

    def write(self, report: CoverageReport, output: Path) -> Path:
        """Render the report and write it to disk.

        Args:
            report: The coverage report.
            output: Target ``.html`` path, or a directory (see resolve_output_path).

        Returns:
            Path of the written HTML file.

        Raises:
            GenerationError: If rendering or writing fails.
        """
        html = self.render(report)
        path = resolve_output_path(output)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(html, encoding="utf-8")
        except OSError as exc:
            raise GenerationError(f"Failed to write coverage report to '{path}': {exc}") from exc
        return path
