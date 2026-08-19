"""Dataverse naming helpers shared by the packager and the Cloud Flow generator.

Both `SolutionPackager` (which writes environmentvariabledefinitions/*.xml) and
`CloudFlowGenerator` (which emits `parameters` entries referencing the same
variables) must agree on the schema name of every environment variable.
This module is the single source of truth for that derivation.
"""

from __future__ import annotations

from flowsmith.exceptions import GenerationError


def env_var_schema_name(publisher_prefix: str, name: str) -> str:
    """Build the Dataverse schema name for a Blue Prism environment variable.

    Args:
        publisher_prefix: Publisher customisation prefix (e.g. "cr3ac").
        name: Blue Prism environment variable name.

    Returns:
        Schema name of the form ``<prefix>_<name>`` with every character
        outside ``[A-Za-z0-9_]`` replaced by an underscore.

    Raises:
        GenerationError: If `name` is empty or contains no usable characters.
    """
    stripped = name.strip()
    if not stripped:
        raise GenerationError("Environment variable name is empty — cannot derive a schema name.")

    safe = "".join(c if c.isalnum() or c == "_" else "_" for c in stripped)
    return f"{publisher_prefix}_{safe}"


def env_var_parameter_key(name: str, schema_name: str) -> str:
    """Build the Cloud Flow `parameters` key for an environment variable.

    Power Automate names environment-variable parameters
    ``"<display name> (<schema name>)"`` — see the reference CF JSON.

    Args:
        name: Blue Prism environment variable display name.
        schema_name: Dataverse schema name from `env_var_schema_name`.

    Returns:
        The parameter key string.
    """
    return f"{name} ({schema_name})"
