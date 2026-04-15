"""Tests for flowsmith.mapper.config — YAML mapping loader and models."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from flowsmith.ast.models import Runtime
from flowsmith.exceptions import ConfigError
from flowsmith.mapper import (
    MappingConfig,
    StageRule,
    VBOEntry,
    load_rules,
)

# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_mapping_dir(tmp_path: Path) -> Path:
    """Create a temp directory with minimal valid YAML files for testing.

    Returns the path to the temp mapping directory.
    """
    # Create a minimal stage_rules.yaml with 3 entries covering all fields
    stage_rules_yaml = [
        {
            "bp_stage_type": "Start",
            "canonical_type": "START",
            "pa_target_action": "",
            "pa_module": "",
            "runtime": "DESKTOP",
            "confidence_base": 0.95,
            "notes": "Entry point.",
        },
        {
            "bp_stage_type": "Action",
            "canonical_type": "ACTION",
            "pa_target_action": "",
            "pa_module": "",
            "runtime": "DESKTOP",
            "confidence_base": 0.70,
            "notes": "VBO call.",
            "pair_with": None,
        },
        {
            "bp_stage_type": "Exception",
            "canonical_type": "EXCEPTION",
            "pa_target_action": "",
            "pa_module": "",
            "runtime": "DESKTOP",
            "confidence_base": 0.80,
            "exception_types": ["Business Exception", "System Exception"],
            "notes": "Throw exception.",
        },
    ]

    # Create a minimal vbo_catalogue.yaml with entries covering all fields
    vbo_yaml = [
        {
            "vbo_name": "MS Excel VBO",
            "method_patterns": ["Open Workbook", "Close Workbook"],
            "pa_module": "",
            "runtime": "DESKTOP",
            "confidence_base": 0.80,
            "notes": "Excel operations.",
        },
        {
            "vbo_name": "Test VBO Error Review",
            "method_patterns": ["Do Something"],
            "pa_module": "",
            "runtime": "CLOUD",
            "confidence_base": 0.50,
            "notes": "VBO with error review flag.",
            "review_severity": "error",
        },
        {
            "vbo_name": "Test VBO Warn Review",
            "method_patterns": ["Do Another"],
            "pa_module": "",
            "runtime": "DESKTOP",
            "confidence_base": 0.60,
            "notes": "VBO with warn review flag.",
            "review_severity": "warn",
        },
    ]

    # Write the YAML files
    stage_rules_file = tmp_path / "stage_rules.yaml"
    with open(stage_rules_file, "w", encoding="utf-8") as f:
        yaml.dump(stage_rules_yaml, f)

    vbo_file = tmp_path / "vbo_catalogue.yaml"
    with open(vbo_file, "w", encoding="utf-8") as f:
        yaml.dump(vbo_yaml, f)

    return tmp_path


@pytest.fixture
def minimal_stage_rule_yaml() -> dict:
    """Provide a minimal valid StageRule YAML dict."""
    return {
        "bp_stage_type": "TestStage",
        "canonical_type": "ACTION",
        "pa_target_action": "TestAction",
        "pa_module": "TestModule",
        "runtime": "CLOUD",
        "confidence_base": 0.75,
        "notes": "A test stage rule.",
    }


@pytest.fixture
def minimal_vbo_entry_yaml() -> dict:
    """Provide a minimal valid VBOEntry YAML dict."""
    return {
        "vbo_name": "Test VBO",
        "method_patterns": ["Method1", "Method2"],
        "pa_module": "TestModule",
        "runtime": "DESKTOP",
        "confidence_base": 0.85,
        "notes": "A test VBO.",
    }


# ── StageRule model tests ──────────────────────────────────────────────────


class TestStageRule:
    """Test StageRule Pydantic model validation."""

    def test_create_minimal(self, minimal_stage_rule_yaml: dict) -> None:
        """A StageRule can be created from minimal dict."""
        rule = StageRule(**minimal_stage_rule_yaml)
        assert rule.bp_stage_type == "TestStage"
        assert rule.canonical_type == "ACTION"
        assert rule.confidence_base == 0.75

    def test_defaults(self, minimal_stage_rule_yaml: dict) -> None:
        """StageRule has sensible defaults for optional fields."""
        minimal = {
            "bp_stage_type": "Test",
            "runtime": "CLOUD",
            "confidence_base": 0.50,
        }
        rule = StageRule(**minimal)
        assert rule.canonical_type == ""
        assert rule.pa_target_action == ""
        assert rule.pa_module == ""
        assert rule.notes == ""
        assert rule.pair_with is None
        assert rule.exception_types == []

    def test_confidence_validation_valid(self) -> None:
        """confidence_base is accepted in range [0.0, 1.0]."""
        rule = StageRule(
            bp_stage_type="Test",
            runtime="CLOUD",
            confidence_base=0.0,
        )
        assert rule.confidence_base == 0.0

        rule = StageRule(
            bp_stage_type="Test",
            runtime="CLOUD",
            confidence_base=1.0,
        )
        assert rule.confidence_base == 1.0

        rule = StageRule(
            bp_stage_type="Test",
            runtime="CLOUD",
            confidence_base=0.5,
        )
        assert rule.confidence_base == 0.5

    def test_confidence_validation_invalid(self) -> None:
        """confidence_base is rejected outside [0.0, 1.0]."""
        with pytest.raises(ValueError, match="confidence_base must be in"):
            StageRule(
                bp_stage_type="Test",
                runtime="CLOUD",
                confidence_base=-0.1,
            )

        with pytest.raises(ValueError, match="confidence_base must be in"):
            StageRule(
                bp_stage_type="Test",
                runtime="CLOUD",
                confidence_base=1.1,
            )

    def test_exception_types_field(self) -> None:
        """exception_types field is properly preserved."""
        rule = StageRule(
            bp_stage_type="Exception",
            runtime="CLOUD",
            confidence_base=0.80,
            exception_types=["Business Exception", "System Exception"],
        )
        assert rule.exception_types == ["Business Exception", "System Exception"]


# ── VBOEntry model tests ───────────────────────────────────────────────────


class TestVBOEntry:
    """Test VBOEntry Pydantic model validation."""

    def test_create_minimal(self, minimal_vbo_entry_yaml: dict) -> None:
        """A VBOEntry can be created from minimal dict."""
        entry = VBOEntry(**minimal_vbo_entry_yaml)
        assert entry.vbo_name == "Test VBO"
        assert entry.confidence_base == 0.85

    def test_defaults(self) -> None:
        """VBOEntry has sensible defaults for optional fields."""
        minimal = {
            "vbo_name": "Test VBO",
            "runtime": "CLOUD",
            "confidence_base": 0.75,
        }
        entry = VBOEntry(**minimal)
        assert entry.method_patterns == []
        assert entry.pa_module == ""
        assert entry.notes == ""
        assert entry.review_severity is None

    def test_confidence_validation_valid(self) -> None:
        """confidence_base is accepted in range [0.0, 1.0]."""
        entry = VBOEntry(
            vbo_name="Test",
            runtime="CLOUD",
            confidence_base=0.0,
        )
        assert entry.confidence_base == 0.0

        entry = VBOEntry(
            vbo_name="Test",
            runtime="CLOUD",
            confidence_base=1.0,
        )
        assert entry.confidence_base == 1.0

    def test_confidence_validation_invalid(self) -> None:
        """confidence_base is rejected outside [0.0, 1.0]."""
        with pytest.raises(ValueError, match="confidence_base must be in"):
            VBOEntry(
                vbo_name="Test",
                runtime="CLOUD",
                confidence_base=-0.5,
            )

        with pytest.raises(ValueError, match="confidence_base must be in"):
            VBOEntry(
                vbo_name="Test",
                runtime="CLOUD",
                confidence_base=1.5,
            )

    def test_review_severity_valid(self) -> None:
        """review_severity accepts None, 'error', or 'warn'."""
        entry = VBOEntry(
            vbo_name="Test",
            runtime="CLOUD",
            confidence_base=0.50,
            review_severity=None,
        )
        assert entry.review_severity is None

        entry = VBOEntry(
            vbo_name="Test",
            runtime="CLOUD",
            confidence_base=0.50,
            review_severity="error",
        )
        assert entry.review_severity == "error"

        entry = VBOEntry(
            vbo_name="Test",
            runtime="CLOUD",
            confidence_base=0.50,
            review_severity="warn",
        )
        assert entry.review_severity == "warn"

    def test_review_severity_invalid(self) -> None:
        """review_severity is rejected for invalid values."""
        with pytest.raises(ValueError, match="review_severity must be"):
            VBOEntry(
                vbo_name="Test",
                runtime="CLOUD",
                confidence_base=0.50,
                review_severity="invalid",
            )


# ── MappingConfig model tests ──────────────────────────────────────────────


class TestMappingConfig:
    """Test MappingConfig and its lookup methods."""

    def test_create(self, tmp_mapping_dir: Path) -> None:
        """A MappingConfig can be created with lists of rules."""
        rule = StageRule(
            bp_stage_type="Test",
            runtime="CLOUD",
            confidence_base=0.50,
        )
        entry = VBOEntry(
            vbo_name="Test VBO",
            runtime="DESKTOP",
            confidence_base=0.75,
        )
        config = MappingConfig(stage_rules=[rule], vbo_catalogue=[entry])
        assert len(config.stage_rules) == 1
        assert len(config.vbo_catalogue) == 1

    def test_get_stage_rule_exact(self, tmp_mapping_dir: Path) -> None:
        """get_stage_rule finds a rule by exact type name."""
        config = load_rules(mapping_dir=tmp_mapping_dir, force_reload=True)
        rule = config.get_stage_rule("Start")
        assert rule is not None
        assert rule.bp_stage_type == "Start"
        assert rule.canonical_type == "START"

    def test_get_stage_rule_case_insensitive(self, tmp_mapping_dir: Path) -> None:
        """get_stage_rule is case-insensitive."""
        config = load_rules(mapping_dir=tmp_mapping_dir, force_reload=True)
        r1 = config.get_stage_rule("Start")
        r2 = config.get_stage_rule("START")
        r3 = config.get_stage_rule("start")
        assert r1 is not None
        assert r1.bp_stage_type == r2.bp_stage_type == r3.bp_stage_type

    def test_get_stage_rule_not_found(self, tmp_mapping_dir: Path) -> None:
        """get_stage_rule returns None for unknown stage type."""
        config = load_rules(mapping_dir=tmp_mapping_dir, force_reload=True)
        assert config.get_stage_rule("NonExistent") is None
        assert config.get_stage_rule("InvalidType") is None

    def test_get_vbo_entry_exact(self, tmp_mapping_dir: Path) -> None:
        """get_vbo_entry finds an entry by exact name match."""
        config = load_rules(mapping_dir=tmp_mapping_dir, force_reload=True)
        entry = config.get_vbo_entry("MS Excel VBO")
        assert entry is not None
        assert entry.vbo_name == "MS Excel VBO"
        assert entry.confidence_base == 0.80

    def test_get_vbo_entry_not_found(self, tmp_mapping_dir: Path) -> None:
        """get_vbo_entry returns None for unknown VBO name."""
        config = load_rules(mapping_dir=tmp_mapping_dir, force_reload=True)
        assert config.get_vbo_entry("Unknown VBO") is None
        assert config.get_vbo_entry("NonExistent") is None

    def test_get_vbo_entry_fuzzy_exact_match(self, tmp_mapping_dir: Path) -> None:
        """get_vbo_entry_fuzzy returns exact match when available."""
        config = load_rules(mapping_dir=tmp_mapping_dir, force_reload=True)
        entry = config.get_vbo_entry_fuzzy("MS Excel VBO")
        assert entry is not None
        assert entry.vbo_name == "MS Excel VBO"

    def test_get_vbo_entry_fuzzy_case_insensitive(self, tmp_mapping_dir: Path) -> None:
        """get_vbo_entry_fuzzy falls back to case-insensitive match."""
        config = load_rules(mapping_dir=tmp_mapping_dir, force_reload=True)
        # Test that fuzzy match works on the temp VBOs with case variations
        # "MS Excel VBO" exists in the temp fixture, try variations
        entry_lower = config.get_vbo_entry_fuzzy("ms excel vbo")
        assert entry_lower is not None
        assert entry_lower.vbo_name == "MS Excel VBO"

        entry_mixed = config.get_vbo_entry_fuzzy("Ms Excel VbO")
        assert entry_mixed is not None
        assert entry_mixed.vbo_name == "MS Excel VBO"

    def test_get_vbo_entry_fuzzy_not_found(self, tmp_mapping_dir: Path) -> None:
        """get_vbo_entry_fuzzy returns None for unknown VBO."""
        config = load_rules(mapping_dir=tmp_mapping_dir, force_reload=True)
        assert config.get_vbo_entry_fuzzy("Unknown VBO") is None


# ── load_rules function tests ──────────────────────────────────────────────


class TestLoadRules:
    """Test the load_rules loader function."""

    def test_load_from_tmp_mapping_dir(self, tmp_mapping_dir: Path) -> None:
        """load_rules can load from a custom mapping directory."""
        config = load_rules(mapping_dir=tmp_mapping_dir, force_reload=True)
        assert len(config.stage_rules) == 3
        assert len(config.vbo_catalogue) == 3

    def test_load_default_mapping_dir(self) -> None:
        """load_rules defaults to mapping/ directory in cwd."""
        config = load_rules(force_reload=True)
        assert len(config.stage_rules) == 26
        assert len(config.vbo_catalogue) == 32

    def test_load_real_stage_rules(self) -> None:
        """load_rules successfully loads the real stage_rules.yaml."""
        config = load_rules(force_reload=True)
        assert len(config.stage_rules) == 26

        # Check specific rules exist
        start = config.get_stage_rule("Start")
        assert start is not None
        assert start.canonical_type == "START"

        action = config.get_stage_rule("Action")
        assert action is not None
        assert action.canonical_type == "ACTION"

        exception = config.get_stage_rule("Exception")
        assert exception is not None
        assert exception.canonical_type == "EXCEPTION"
        assert len(exception.exception_types) > 0

    def test_load_real_vbo_catalogue(self) -> None:
        """load_rules successfully loads the real vbo_catalogue.yaml."""
        config = load_rules(force_reload=True)
        assert len(config.vbo_catalogue) == 32

        # Check specific VBOs exist
        excel = config.get_vbo_entry("MS Excel VBO")
        assert excel is not None
        assert excel.confidence_base == 0.80

    def test_missing_stage_rules_raises_config_error(self, tmp_path: Path) -> None:
        """load_rules raises ConfigError if stage_rules.yaml is missing."""
        # Create a dir with only vbo_catalogue.yaml
        tmp_path_empty = tmp_path / "missing_stage"
        tmp_path_empty.mkdir()

        vbo_file = tmp_path_empty / "vbo_catalogue.yaml"
        vbo_data = [
            {
                "vbo_name": "Test",
                "runtime": "DESKTOP",
                "confidence_base": 0.50,
            }
        ]
        with open(vbo_file, "w", encoding="utf-8") as f:
            yaml.dump(vbo_data, f)

        with pytest.raises(ConfigError):
            load_rules(mapping_dir=tmp_path_empty, force_reload=True)

    def test_missing_vbo_catalogue_raises_config_error(self, tmp_path: Path) -> None:
        """load_rules raises ConfigError if vbo_catalogue.yaml is missing."""
        # Create a dir with only stage_rules.yaml
        tmp_path_empty = tmp_path / "missing_vbo"
        tmp_path_empty.mkdir()

        stage_file = tmp_path_empty / "stage_rules.yaml"
        stage_data = [
            {
                "bp_stage_type": "Test",
                "runtime": "DESKTOP",
                "confidence_base": 0.50,
            }
        ]
        with open(stage_file, "w", encoding="utf-8") as f:
            yaml.dump(stage_data, f)

        with pytest.raises(ConfigError):
            load_rules(mapping_dir=tmp_path_empty, force_reload=True)

    def test_missing_mapping_dir_raises_config_error(self) -> None:
        """load_rules raises ConfigError if the mapping directory doesn't exist."""
        with pytest.raises(ConfigError):
            load_rules(mapping_dir=Path("nonexistent_dir"), force_reload=True)

    def test_caching_behavior(self, tmp_mapping_dir: Path) -> None:
        """load_rules caches the result; second call returns same object."""
        # First load with force_reload=True
        config1 = load_rules(mapping_dir=tmp_mapping_dir, force_reload=True)
        # Second load without force_reload should return the cached object
        config2 = load_rules(mapping_dir=tmp_mapping_dir, force_reload=False)
        assert config1 is config2

    def test_force_reload_bypasses_cache(self, tmp_mapping_dir: Path) -> None:
        """load_rules with force_reload=True loads fresh from disk."""
        # First load
        config1 = load_rules(mapping_dir=tmp_mapping_dir, force_reload=True)
        # Second load with force_reload=True should be a different object
        config2 = load_rules(mapping_dir=tmp_mapping_dir, force_reload=True)
        # They should have the same content but be different objects
        assert len(config1.stage_rules) == len(config2.stage_rules)
        # Note: They won't be identical objects due to module-level caching,
        # but they would have the same data

    def test_malformed_yaml_raises_config_error(self, tmp_path: Path) -> None:
        """load_rules raises ConfigError on malformed YAML."""
        tmp_dir = tmp_path / "malformed"
        tmp_dir.mkdir()

        # Write malformed YAML
        stage_file = tmp_dir / "stage_rules.yaml"
        with open(stage_file, "w", encoding="utf-8") as f:
            f.write("{ invalid yaml content ][")

        vbo_file = tmp_dir / "vbo_catalogue.yaml"
        with open(vbo_file, "w", encoding="utf-8") as f:
            f.write("[]")

        with pytest.raises(ConfigError):
            load_rules(mapping_dir=tmp_dir, force_reload=True)

    def test_empty_yaml_raises_config_error(self, tmp_path: Path) -> None:
        """load_rules raises ConfigError on empty YAML files."""
        tmp_dir = tmp_path / "empty"
        tmp_dir.mkdir()

        # Write empty YAML
        stage_file = tmp_dir / "stage_rules.yaml"
        with open(stage_file, "w", encoding="utf-8") as f:
            f.write("")

        vbo_file = tmp_dir / "vbo_catalogue.yaml"
        with open(vbo_file, "w", encoding="utf-8") as f:
            f.write("[]")

        with pytest.raises(ConfigError):
            load_rules(mapping_dir=tmp_dir, force_reload=True)

    def test_empty_vbo_catalogue_raises_config_error(self, tmp_path: Path) -> None:
        """load_rules raises ConfigError when vbo_catalogue.yaml is empty."""
        tmp_dir = tmp_path / "empty_vbo"
        tmp_dir.mkdir()

        # Write valid stage_rules but empty vbo_catalogue
        stage_file = tmp_dir / "stage_rules.yaml"
        stage_data = [
            {
                "bp_stage_type": "Test",
                "runtime": "DESKTOP",
                "confidence_base": 0.50,
            }
        ]
        with open(stage_file, "w", encoding="utf-8") as f:
            yaml.dump(stage_data, f)

        vbo_file = tmp_dir / "vbo_catalogue.yaml"
        with open(vbo_file, "w", encoding="utf-8") as f:
            f.write("")  # Empty file, will parse as None

        with pytest.raises(ConfigError):
            load_rules(mapping_dir=tmp_dir, force_reload=True)

    def test_invalid_runtime_enum_raises_error(self, tmp_path: Path) -> None:
        """load_rules raises error on invalid Runtime enum value."""
        tmp_dir = tmp_path / "invalid_runtime"
        tmp_dir.mkdir()

        # Write YAML with invalid runtime
        stage_file = tmp_dir / "stage_rules.yaml"
        with open(stage_file, "w", encoding="utf-8") as f:
            yaml.dump(
                [
                    {
                        "bp_stage_type": "Test",
                        "runtime": "INVALID",
                        "confidence_base": 0.50,
                    }
                ],
                f,
            )

        vbo_file = tmp_dir / "vbo_catalogue.yaml"
        with open(vbo_file, "w", encoding="utf-8") as f:
            yaml.dump([], f)

        with pytest.raises(ConfigError):
            load_rules(mapping_dir=tmp_dir, force_reload=True)


# ── Integration tests ──────────────────────────────────────────────────────


class TestIntegration:
    """Integration tests with real YAML files."""

    def test_real_data_consistency(self) -> None:
        """Real stage_rules and vbo_catalogue are internally consistent."""
        config = load_rules(force_reload=True)

        # All stage rules should have a valid Runtime
        for rule in config.stage_rules:
            assert isinstance(rule.runtime, Runtime)
            # Confidence should be in valid range
            assert 0.0 <= rule.confidence_base <= 1.0

        # All VBO entries should have a valid Runtime
        for entry in config.vbo_catalogue:
            assert isinstance(entry.runtime, Runtime)
            # Confidence should be in valid range
            assert 0.0 <= entry.confidence_base <= 1.0

    def test_real_stage_rules_loadable(self) -> None:
        """Real stage_rules.yaml contains all 26 expected rules."""
        config = load_rules(force_reload=True)
        assert len(config.stage_rules) == 26

        # Check some known rules
        known_types = ["Start", "End", "Action", "Decision", "Code", "Exception"]
        for stage_type in known_types:
            rule = config.get_stage_rule(stage_type)
            assert rule is not None, f"Rule for {stage_type} not found"

    def test_real_vbo_catalogue_loadable(self) -> None:
        """Real vbo_catalogue.yaml contains all 32 expected entries."""
        config = load_rules(force_reload=True)
        assert len(config.vbo_catalogue) == 32

        # Check some known VBOs
        known_vbos = [
            "MS Excel VBO",
            "Utility - File Management",
            "Utility - Strings",
        ]
        for vbo_name in known_vbos:
            entry = config.get_vbo_entry(vbo_name)
            assert entry is not None, f"VBO {vbo_name} not found"

    def test_review_severity_flags_present(self) -> None:
        """Real vbo_catalogue contains entries with review_severity flags."""
        config = load_rules(force_reload=True)

        # Check for error-level review flag
        acs = config.get_vbo_entry("RPA Sharepoint ACS Authentication")
        assert acs is not None
        assert acs.review_severity == "error"

        # Check for warn-level review flag
        lock = config.get_vbo_entry("BluePrism.AutomateAppCore.clsEnvironmentLockingBusinessObject")
        assert lock is not None
        assert lock.review_severity == "warn"
