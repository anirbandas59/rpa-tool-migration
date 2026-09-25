"""Tests for CLI entry point — structural only, no business logic."""

import subprocess


def test_cli_help_exits_clean():
    """flowsmith --help must exit 0."""
    result = subprocess.run(
        ["uv", "run", "flowsmith", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0


def test_cli_has_all_three_commands():
    """All three commands must be registered: convert, report, deploy."""
    result = subprocess.run(
        ["uv", "run", "flowsmith", "--help"],
        capture_output=True,
        text=True,
    )
    for cmd in ["convert", "report", "deploy"]:
        assert cmd in result.stdout, f"Missing command: {cmd}"


def test_convert_requires_input_flag():
    """convert must require --input flag."""
    result = subprocess.run(
        ["uv", "run", "flowsmith", "convert"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0


def test_report_requires_input_flag():
    """report must require --input flag."""
    result = subprocess.run(
        ["uv", "run", "flowsmith", "report"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0


def test_deploy_requires_solution_and_env_flags():
    """deploy must require both --solution and --env flags."""
    result = subprocess.run(
        ["uv", "run", "flowsmith", "deploy"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0


def test_convert_exposes_managed_flag():
    """convert must expose --managed so a managed solution can be produced."""
    result = subprocess.run(
        ["uv", "run", "flowsmith", "convert", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "--managed" in result.stdout


def test_convert_creates_no_cloudflow_folder_and_packages(tmp_path):
    """Task 7d items 1/5: convert no longer runs the per-page Cloud Flow path — no
    cloudflow/ folder is created, and packaging succeeds (the consolidated packager
    raises if it is handed per-page Cloud Flow files)."""
    result = subprocess.run(
        [
            "uv",
            "run",
            "flowsmith",
            "convert",
            "--input",
            "samples/blueprism/PID_0171.bprelease",
            "--output",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (tmp_path / "cloudflow").exists()
    assert list(tmp_path.glob("*_solution.zip"))


def _report_ast(tmp_path):
    """Serialise the reporter tests' synthetic annotated process to tmp_path/ast.json."""
    from flowsmith.ast.serialiser import serialise
    from tests.reporter.conftest import make_process

    path = tmp_path / "ast.json"
    serialise(make_process(), path)
    return path


def test_report_writes_html_from_ast(tmp_path):
    """Task 8: report --input <ast.json> --output <file.html> writes the coverage report."""
    from typer.testing import CliRunner

    from flowsmith.cli.app import app

    out = tmp_path / "report.html"
    result = CliRunner().invoke(
        app, ["report", "--input", str(_report_ast(tmp_path)), "--output", str(out)]
    )
    assert result.exit_code == 0, result.output
    assert out.is_file()
    assert "ReviewFlags: 2" in result.output


def test_report_terminal_format_writes_no_file(tmp_path):
    """Task 8: --format terminal prints the summary only."""
    from typer.testing import CliRunner

    from flowsmith.cli.app import app

    out = tmp_path / "report.html"
    result = CliRunner().invoke(
        app,
        ["report", "-i", str(_report_ast(tmp_path)), "-o", str(out), "--format", "terminal"],
    )
    assert result.exit_code == 0, result.output
    assert not out.exists()
    assert "MANUAL" in result.output


def test_report_rejects_zip_input(tmp_path):
    """Task 8: a solution .zip carries no scores/flags, so report exits 1 with a message."""
    from typer.testing import CliRunner

    from flowsmith.cli.app import app

    zip_path = tmp_path / "solution.zip"
    zip_path.write_bytes(b"PK")
    result = CliRunner().invoke(app, ["report", "-i", str(zip_path)])
    assert result.exit_code == 1
    assert "solution package" in result.output
