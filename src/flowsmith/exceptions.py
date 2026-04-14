"""Typed exceptions for Flowsmith — never return None on failure, raise these instead.

Base class is FlowsmithError. BP2PAError is an alias kept for compatibility.
All typed exceptions subclass FlowsmithError.
"""


class FlowsmithError(Exception):
    """Base exception for all Flowsmith errors."""


# Compatibility alias — FlowsmithError is canonical; BP2PAError resolves to the same class.
BP2PAError = FlowsmithError


class ParseError(FlowsmithError):
    """Raised when a .bprelease file cannot be parsed."""


class ASTBuildError(FlowsmithError):
    """Raised when the canonical AST cannot be constructed from parsed data."""


class ConfigError(FlowsmithError):
    """Raised when mapping config YAML is malformed or missing required keys."""


class TransformError(FlowsmithError):
    """Raised when the transformation engine cannot annotate a stage."""


class GenerationError(FlowsmithError):
    """Raised when code generation fails for a stage or page."""


class ValidationError(FlowsmithError):
    """Raised when generated output fails schema validation."""


class DeployError(FlowsmithError):
    """Raised when PAC CLI deployment fails or pre-flight checks fail."""
