"""Flowsmith CLI - Automation migration tool to Power Automate solutions."""

from collections import Counter
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from flowsmith.ast.serialiser import deserialise
from flowsmith.exceptions import ASTBuildError, ParseError

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
    from pathlib import Path

    from flowsmith.ast import build_ast, serialise
    from flowsmith.engine import create_annotator
    from flowsmith.generator import CloudFlowGenerator, PADGenerator, SolutionPackager
    from flowsmith.parser import parse_process

    input_path = Path(input)
    output_dir = Path(output)

    try:
        console.print(f"[bold]Parsing[/bold] {input_path.name}...")
        raw = parse_process(input_path)
        process = build_ast(raw)

        console.print("[bold]Annotating[/bold] stages...")
        create_annotator().annotate_process(process)

        console.print("[bold]Serialising[/bold] AST...")
        serialise(process, output_dir / "ast.json")

        console.print("[bold]Generating[/bold] PAD .robin files...")
        robin_dir = output_dir / "robin"
        PADGenerator().generate_process(process, robin_dir)

        console.print("[bold]Generating[/bold] Cloud Flow JSON...")
        cf_dir = output_dir / "cloudflow"
        CloudFlowGenerator().generate_process(process, cf_dir)

        console.print("[bold]Packaging[/bold] solution...")
        zip_path = output_dir / f"{process.name}_solution.zip"
        SolutionPackager().package(process, robin_dir, cf_dir, zip_path)

        console.print(f"[green]Done[/green] -> {zip_path}")
    except (ParseError, Exception) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None


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


@app.command()
def inspect(
    ast_file: str = typer.Option(..., "--ast", "-a", help="Path to a serialised AST JSON file"),
    show_stages: bool = typer.Option(
        False, "--stages", "-s", help="Print per-stage breakdown for each page"
    ),
) -> None:
    """Inspect a serialised AST JSON file and print a summary."""
    try:
        process = deserialise(Path(ast_file))
    except (ParseError, ASTBuildError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None

    all_stages = [stage for page in process.pages for stage in page.stages]
    total_stages = len(all_stages)
    annotated = sum(1 for s in all_stages if s.pa_annotation is not None)
    pending = total_stages - annotated

    type_counts = Counter(s.stage_type.value for s in all_stages)
    type_breakdown = "\n".join(
        f"  {t}: {c}" for t, c in sorted(type_counts.items(), key=lambda x: -x[1])
    )

    summary = (
        f"[bold]Process:[/bold] {process.name}\n"
        f"[bold]ID:[/bold]      {process.process_id}\n"
        f"[bold]Version:[/bold] {process.version}\n"
        f"[bold]Source:[/bold]  {process.source_file}\n"
        f"\n"
        f"[bold]Pages:[/bold]   {len(process.pages)}\n"
        f"[bold]Stages:[/bold]  {total_stages}  "
        f"(annotated: {annotated}, pending: {pending})\n"
        f"\n"
        f"[bold]Stage type breakdown:[/bold]\n"
        f"{type_breakdown if type_breakdown else '  (none)'}"
    )
    console.print(Panel(summary, title="[bold cyan]Flowsmith AST Inspector[/bold cyan]"))

    if show_stages:
        for page in process.pages:
            main_flag = " [is_main]" if page.is_main else ""
            table = Table(
                title=f"Page: {page.name}{main_flag} ({len(page.stages)} stages)",
                show_lines=True,
            )
            table.add_column("stage_id", style="dim")
            table.add_column("stage_type")
            table.add_column("name")
            table.add_column("pa_annotation")
            for stage in page.stages:
                pa_status = "annotated" if stage.pa_annotation is not None else "pending"
                table.add_row(stage.stage_id, stage.stage_type.value, stage.name, pa_status)
            console.print(table)


if __name__ == "__main__":
    app()
