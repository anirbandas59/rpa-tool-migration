"""Shared fixtures for all tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from flowsmith.ast import build_ast
from flowsmith.parser import parse_process


@pytest.fixture(scope="session")
def real_raw():
    """Return raw parsed dict from real sample once per session.

    Parses samples/blueprism/PID_0127.bprelease without building AST.
    Skips if file not available (CI environments may not have it).

    As of Task 3a, parse_process() returns MultiArtefactRelease.
    This fixture extracts the first process (the main PID_0127 process)
    and returns it as a RawProcess for backward compatibility with
    existing test_integration.py and other consuming tests.

    Returns:
        RawProcess dict (first process from MultiArtefactRelease).
    """
    sample = Path("samples/blueprism/PID_0127.bprelease")
    if not sample.exists():
        pytest.skip("Real sample file not available")
    release = parse_process(sample)
    # Extract first process from MultiArtefactRelease
    if release["processes"]:
        return release["processes"][0]
    pytest.skip("No processes found in release")


@pytest.fixture(scope="session")
def real_process(real_raw):
    """Parse and build the real sample once per session.

    Uses real_raw fixture to avoid re-parsing. Builds the AST.
    Skips if file not available (CI environments may not have it).

    Args:
        real_raw: RawProcess dict from real_raw fixture.

    Returns:
        BPProcess AST after normalisation.
    """
    return build_ast(real_raw)
