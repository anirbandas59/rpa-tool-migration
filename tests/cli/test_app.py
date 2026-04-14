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
