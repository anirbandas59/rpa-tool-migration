"""Rich terminal summary of a CoverageReport (band table + flag counts)."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from flowsmith.reporter.models import CoverageReport


def render_terminal_summary(report: CoverageReport, console: Console) -> None:
    """Print a compact band/flag summary of the report to the console.

    Args:
        report: The coverage report.
        console: Rich console to print to.
    """
    console.print(
        f"[bold]{report.process_name}[/bold]: {report.stage_count} stages, "
        f"{report.page_count} pages, mean confidence {report.mean_confidence:.2f}, "
        f"readiness: {report.readiness}"
    )
    table = Table(title="Coverage by confidence band")
    table.add_column("Band")
    table.add_column("Stages", justify="right")
    table.add_column("%", justify="right")
    for band in report.bands:
        table.add_row(band.band, str(band.count), f"{band.percent:.1f}")
    table.add_row(
        "Total",
        str(sum(b.count for b in report.bands)),
        f"{sum(b.percent for b in report.bands):.1f}",
    )
    console.print(table)

    severities = ", ".join(
        f"{sev}: {report.flag_counts.get(sev, 0)}" for sev in ("error", "warn", "info")
    )
    console.print(f"ReviewFlags: {report.flag_total} ({severities})")
    console.print(f"PARTIAL/MANUAL stages without a ReviewFlag: {len(report.unflagged_attention)}")
