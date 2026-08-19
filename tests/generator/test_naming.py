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


class TestFlowFileStem:
    """Tests for flow_file_stem() — shared page/process file-stem derivation."""

    def test_spaces_become_underscores(self) -> None:
        """Spaces map to underscores, as PADGenerator writes them."""
        from flowsmith.generator.naming import flow_file_stem

        assert flow_file_stem("Mark Item As Completed") == "Mark_Item_As_Completed"

    def test_other_specials_are_removed(self) -> None:
        """Characters outside [A-Za-z0-9_] are dropped."""
        from flowsmith.generator.naming import flow_file_stem

        assert flow_file_stem("Launch_Sample Manager (v2)") == "Launch_Sample_Manager_v2"

    def test_empty_result_falls_back(self) -> None:
        """A name with nothing usable falls back to 'flow'."""
        from flowsmith.generator.naming import flow_file_stem

        assert flow_file_stem("!!!") == "flow"

    def test_matches_pad_generator_derivation(self) -> None:
        """PADGenerator's filename stem is the same derivation."""
        from flowsmith.generator.naming import flow_file_stem
        from flowsmith.generator.pad import PADGenerator

        for name in ("Mark Item As Completed", "Get Mails", "Result Entry"):
            assert PADGenerator._sanitise_filename(name) == flow_file_stem(name)
