"""Flowsmith CLI - Automation migration tool to Power Automate solutions."""

import typer
from rich.console import Console

app = typer.Typer(
    name="flowsmith", help="Migrate any RPA tool to Power Automate flows.", add_completion=False
)

console = Console()


@app.command()
def convert(
    input: str = typer.Option(..., "--input", "-i", help="Path to .bprelease file"),
    output: str = typer.Option("output", "--output", "-o", help="Output directory"),
    overrides: str = typer.Option(None, "--overrides", help="Path to overrides.yaml"),
):
    """Parse, transform and generate Power Automate flows from a .bprelease files"""
    console.print(f"[bold]Flowsmith Report[/bold] - Input: {input}")
    console.print("[yellow]Not yet implemented — Phase 7[/yellow]")


@app.command()
def report(
    input: str = typer.Option(..., "--input", "-i", help="Path to .bprelease file"),
    output: str = typer.Option("output", "--output", "-o", help="Output directory for report"),
    format: str = typer.Option("html", "--format", "-f", help="Report format: html or terminal"),
) -> None:
    """Generate a migration assessment report without producing output files."""
    console.print(f"[bold]flowsmith report[/bold] — input: {input}")
    console.print("[yellow]Not yet implemented — Phase 7[/yellow]")


@app.command()
def deploy(
    solution: str = typer.Option(..., "--solution", "-s", help="Path to solution .zip"),
    env: str = typer.Option(..., "--env", "-e", help="Power platform environment ID"),
    confirm: bool = typer.Option(False, "--confirm", help="Skip confirmation prompt"),
):
    """Deploy a generated solution package via Power Platform CLI"""
    console.print(f"[bold]Flowsmith Deploy[/bold] - Solution: {solution} | Env: {env}")
    console.print("[yellow]Not yet implemented — Phase 8[/yellow]")


if __name__ == "__main__":
    app()
