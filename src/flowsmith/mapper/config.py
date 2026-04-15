"""YAML-based mapping configuration loader for Flowsmith.

This module is the single point of entry for all mapping decisions.
It loads and validates two YAML files:
  - mapping/stage_rules.yaml    — Blue Prism stage type mappings
  - mapping/vbo_catalogue.yaml  — VBO name to Power Automate module mappings

Invalid YAML or missing files raise ConfigError immediately, never at mapping time.
The module caches loaded config in memory so YAML is read only once per process.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

from flowsmith.ast.models import Runtime
from flowsmith.exceptions import ConfigError

# ── Module-level cache ─────────────────────────────────────────────────────

_MAPPING_DIR = Path("mapping")
_config_cache: MappingConfig | None = None


# ── Pydantic models for YAML validation ────────────────────────────────────


class StageRule(BaseModel):
    """A mapping rule for a single Blue Prism stage type.

    Fields correspond directly to stage_rules.yaml entries.
    confidence_base is validated to be in [0.0, 1.0].
    """

    bp_stage_type: str
    canonical_type: str = ""
    pa_target_action: str = ""
    pa_module: str = ""
    runtime: Runtime
    confidence_base: float
    notes: str = ""
    pair_with: str | None = None
    exception_types: list[str] = Field(default_factory=list)

    @field_validator("confidence_base")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        """Ensure confidence_base is in [0.0, 1.0]."""
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"confidence_base must be in [0.0, 1.0], got {v}")
        return v


class VBOEntry(BaseModel):
    """A mapping entry for a single Blue Prism VBO (Virtual Business Object).

    Fields correspond directly to vbo_catalogue.yaml entries.
    confidence_base is validated to be in [0.0, 1.0].
    review_severity, if present, must be "error" or "warn".
    """

    vbo_name: str
    method_patterns: list[str] = Field(default_factory=list)
    pa_module: str = ""
    runtime: Runtime
    confidence_base: float
    notes: str = ""
    review_severity: str | None = None

    @field_validator("confidence_base")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        """Ensure confidence_base is in [0.0, 1.0]."""
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"confidence_base must be in [0.0, 1.0], got {v}")
        return v

    @field_validator("review_severity")
    @classmethod
    def validate_review_severity(cls, v: str | None) -> str | None:
        """Ensure review_severity is None, 'error', or 'warn'."""
        if v is not None and v not in ("error", "warn"):
            raise ValueError(f"review_severity must be 'error', 'warn', or None, got {v!r}")
        return v


class MappingConfig(BaseModel):
    """The complete mapping configuration loaded from both YAML files.

    Provides lookup methods for stage rules and VBO entries with optional
    fuzzy matching (case-insensitive).
    """

    stage_rules: list[StageRule]
    vbo_catalogue: list[VBOEntry]

    def get_stage_rule(self, bp_stage_type: str) -> StageRule | None:
        """Look up a stage rule by bp_stage_type (case-insensitive).

        Args:
            bp_stage_type: The Blue Prism stage type to look up.

        Returns:
            The matching StageRule, or None if not found.
        """
        target = bp_stage_type.lower()
        for rule in self.stage_rules:
            if rule.bp_stage_type.lower() == target:
                return rule
        return None

    def get_vbo_entry(self, vbo_name: str) -> VBOEntry | None:
        """Look up a VBO entry by exact name match.

        Args:
            vbo_name: The VBO name to look up.

        Returns:
            The matching VBOEntry, or None if not found.
        """
        for entry in self.vbo_catalogue:
            if entry.vbo_name == vbo_name:
                return entry
        return None

    def get_vbo_entry_fuzzy(self, vbo_name: str) -> VBOEntry | None:
        """Look up a VBO entry with fuzzy matching (case-insensitive).

        First tries exact match. If that fails, falls back to case-insensitive.

        Args:
            vbo_name: The VBO name to look up.

        Returns:
            The matching VBOEntry, or None if not found.
        """
        # Try exact match first
        exact = self.get_vbo_entry(vbo_name)
        if exact is not None:
            return exact

        # Try case-insensitive match
        target = vbo_name.lower()
        for entry in self.vbo_catalogue:
            if entry.vbo_name.lower() == target:
                return entry
        return None


# ── Loader function ────────────────────────────────────────────────────────


def load_rules(
    mapping_dir: Path | None = None,
    force_reload: bool = False,
) -> MappingConfig:
    """Load and cache stage rules and VBO catalogue from YAML files.

    Loads two YAML files from mapping_dir:
      - stage_rules.yaml    — stage type mappings
      - vbo_catalogue.yaml  — VBO name mappings

    The result is cached in module memory after the first load, so subsequent
    calls return the same object (unless force_reload=True).

    Args:
        mapping_dir: Path to directory containing stage_rules.yaml and
            vbo_catalogue.yaml. Defaults to mapping/ relative to cwd.
        force_reload: If True, bypass the cache and reload from disk.
            Used in tests to get a clean instance.

    Returns:
        MappingConfig with validated rules and catalogue.

    Raises:
        ConfigError: If either YAML file is missing, cannot be read,
            or fails Pydantic validation.
    """
    global _config_cache

    if not force_reload and _config_cache is not None:
        return _config_cache

    if mapping_dir is None:
        mapping_dir = _MAPPING_DIR

    mapping_dir = Path(mapping_dir)
    stage_rules_file = mapping_dir / "stage_rules.yaml"
    vbo_catalogue_file = mapping_dir / "vbo_catalogue.yaml"

    try:
        # Load stage_rules.yaml
        if not stage_rules_file.exists():
            raise FileNotFoundError(f"stage_rules.yaml not found at {stage_rules_file.absolute()}")

        with open(stage_rules_file, encoding="utf-8") as f:
            stage_rules_data = yaml.safe_load(f)
            if stage_rules_data is None:
                raise ValueError("stage_rules.yaml is empty")
            stage_rules = [StageRule(**item) for item in stage_rules_data]

        # Load vbo_catalogue.yaml
        if not vbo_catalogue_file.exists():
            raise FileNotFoundError(
                f"vbo_catalogue.yaml not found at {vbo_catalogue_file.absolute()}"
            )

        with open(vbo_catalogue_file, encoding="utf-8") as f:
            vbo_data = yaml.safe_load(f)
            if vbo_data is None:
                raise ValueError("vbo_catalogue.yaml is empty")
            vbo_catalogue = [VBOEntry(**item) for item in vbo_data]

        # Create and cache the config
        config = MappingConfig(stage_rules=stage_rules, vbo_catalogue=vbo_catalogue)
        _config_cache = config
        return config

    except FileNotFoundError as e:
        raise ConfigError(str(e)) from e
    except yaml.YAMLError as e:
        raise ConfigError(f"Failed to parse YAML: {e}") from e
    except ValueError as e:
        raise ConfigError(f"Invalid YAML content: {e}") from e
