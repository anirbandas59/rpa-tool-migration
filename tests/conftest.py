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

    Returns:
        RawProcess dict from parser.
    """
    sample = Path("samples/blueprism/PID_0127.bprelease")
    if not sample.exists():
        pytest.skip("Real sample file not available")
    return parse_process(sample)


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
