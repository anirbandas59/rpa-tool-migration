"""Mapper module — YAML-based mapping configuration for Blue Prism → Power Automate."""

from flowsmith.mapper.config import (
    MappingConfig,
    StageRule,
    VBOEntry,
    load_rules,
)

__all__ = [
    "StageRule",
    "VBOEntry",
    "MappingConfig",
    "load_rules",
]
