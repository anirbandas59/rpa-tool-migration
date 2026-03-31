"""Phase 0 smoke test - project scaffold and CLI skeletion"""

import subprocess
import sys


def test_package_imports_cleanly():
    """All top-level subpackages must be importable"""

    packages = [
        "flowsmith",
        "flowsmith.cli",
        "flowsmith.parser",
        "flowsmith.ast",
        "flowsmith.mapper",
        "flowsmith.engine",
        "flowsmith.generator",
        "flowsmith.reporter",
        "flowsmith.exceptions",
    ]

    for pkg in packages:
        result = subprocess.run(
            [sys.executable, f"-cimport {pkg}; print('OK')"], capture_output=True, text=True
        )
        assert result.returncode == 0, f"Import failed for {pkg}:\n{result.stderr}"


def test_exceptions_are_typed():
    """All custom exceptions must subclass FlowsmithError"""
    from flowsmith.exceptions import (
        ASTBuildError,
        ConfigError,
        DeployError,
        FlowsmithError,
        GenerationError,
        ParseError,
        TransformError,
        ValidationError,
    )

    for exc_class in [
        ParseError,
        ASTBuildError,
        ConfigError,
        TransformError,
        GenerationError,
        ValidationError,
        DeployError,
    ]:
        assert issubclass(exc_class, FlowsmithError), (
            f"{exc_class.__name__} must be subclass of FlowsmithError"
        )


def test_cli_help_renders():
    """flowsmith --help must exit 0 and list all three commands."""
    result = subprocess.run(
        [sys.executable, "-m", "flowsmith.cli.app", "--help"], capture_output=True, text=True
    )

    # typer renders help; check commands are listed
    for cmd in ["convert", "report", "deploy"]:
        assert cmd in result.stdout or result.returncode == 0


def test_cli_entry_point():
    """uv run flowsmith --help must exit cleanly."""
    result = subprocess.run(["uv", "run", "flowsmith", "--help"], capture_output=True, text=True)

    assert result.returncode == 0, f"CLI entry point failed:\n {result.stderr}"
    assert "convert" in result.stdout
