"""Tests for Dataverse naming helpers."""

from __future__ import annotations

import pytest

from flowsmith.exceptions import GenerationError
from flowsmith.generator.naming import env_var_parameter_key, env_var_schema_name


def test_schema_name_prefixes_publisher() -> None:
    """Schema name is <prefix>_<safe name>."""
    assert env_var_schema_name("cr3ac", "ConfigFile") == "cr3ac_ConfigFile"


def test_schema_name_replaces_unsafe_characters() -> None:
    """Characters outside [A-Za-z0-9_] become underscores."""
    assert env_var_schema_name("cr3ac", "Config File-01") == "cr3ac_Config_File_01"


def test_schema_name_strips_surrounding_whitespace() -> None:
    """Leading/trailing whitespace is trimmed before sanitising."""
    assert env_var_schema_name("new", "  Retry Count  ") == "new_Retry_Count"


def test_schema_name_empty_raises() -> None:
    """An empty name raises GenerationError rather than returning a bare prefix."""
    with pytest.raises(GenerationError):
        env_var_schema_name("cr3ac", "   ")


def test_parameter_key_format() -> None:
    """Parameter key is '<display name> (<schema name>)'."""
    assert env_var_parameter_key("Config File", "cr3ac_Config_File") == (
        "Config File (cr3ac_Config_File)"
    )
