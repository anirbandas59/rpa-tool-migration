"""AST serialiser — JSON round-trip for BPProcess.

Provides four functions:
  serialise()     — BPProcess → JSON file
  deserialise()   — JSON file → BPProcess
  to_json_str()   — BPProcess → JSON string
  from_json_str() — JSON string → BPProcess

All enum values serialise as their string representations.
None fields are always present in the output (as null), never omitted.
Pydantic ValidationError is always wrapped as ASTBuildError.
IOError on read is wrapped as ParseError; on write as GenerationError.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError as PydanticValidationError

from flowsmith.ast.models import BPProcess
from flowsmith.exceptions import ASTBuildError, GenerationError, ParseError


def to_json_str(process: BPProcess) -> str:
    """Serialise a BPProcess to a JSON string.

    Enums serialise as their string values. None fields are emitted as null.

    Args:
        process: The BPProcess AST to serialise.

    Returns:
        Indented JSON string (indent=2).
    """
    return process.model_dump_json(indent=2)


def from_json_str(json_str: str) -> BPProcess:
    """Deserialise a BPProcess from a JSON string.

    Args:
        json_str: JSON string produced by to_json_str().

    Returns:
        Reconstructed BPProcess instance.

    Raises:
        ASTBuildError: If the string does not validate as a BPProcess.
    """
    try:
        return BPProcess.model_validate_json(json_str)
    except PydanticValidationError as exc:
        raise ASTBuildError(f"AST validation failed: {exc}") from exc
    except Exception as exc:
        raise ASTBuildError(f"Failed to parse JSON: {exc}") from exc


def serialise(process: BPProcess, path: Path) -> None:
    """Serialise a BPProcess to a JSON file.

    Args:
        process: The BPProcess AST to serialise.
        path:    Destination file path. Parent directories are created
                 if they do not exist.

    Raises:
        GenerationError: If the file cannot be written.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(to_json_str(process), encoding="utf-8")
    except OSError as exc:
        raise GenerationError(f"Failed to write AST to '{path}': {exc}") from exc


def deserialise(path: Path) -> BPProcess:
    """Deserialise a BPProcess from a JSON file.

    Args:
        path: Path to a JSON file written by serialise().

    Returns:
        Reconstructed BPProcess instance.

    Raises:
        ParseError:    If the file does not exist or cannot be read.
        ASTBuildError: If the JSON does not validate as a BPProcess.
    """
    try:
        json_str = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ParseError(f"Failed to read AST file '{path}': {exc}") from exc
    return from_json_str(json_str)
