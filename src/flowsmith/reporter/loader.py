"""Report input loading - resolve a report input artefact to an annotated BPProcess.

The report is built from the ``ast.json`` that ``flowsmith convert`` serialises
*after* ``engine.annotate_process()`` (see ``cli/app.py::convert``), so every stage
already carries its ``PAAnnotation`` (confidence, band, ReviewFlags). The solution
``.zip`` is not a usable input: it holds only generated PAD/Cloud Flow source, with
no confidence scores or ReviewFlags to report on.

If an AST lacks annotations (e.g. serialised before annotation), they are
re-derived by calling the engine's own ``create_annotator().annotate_process()`` -
never recomputed here.
"""

from __future__ import annotations

from pathlib import Path

from flowsmith.ast import BPProcess
from flowsmith.ast.serialiser import deserialise
from flowsmith.engine import create_annotator
from flowsmith.exceptions import ParseError

AST_FILENAME = "ast.json"


def resolve_ast_path(input_path: Path) -> Path:
    """Resolve a report ``--input`` value to the ``ast.json`` file to load.

    Accepts either the ``ast.json`` file itself or a ``flowsmith convert`` output
    directory containing one.

    Args:
        input_path: Path given on the command line.

    Returns:
        Path to an existing AST JSON file.

    Raises:
        ParseError: If the path does not exist, is a solution ``.zip`` (which
            carries no confidence/flag data), or a directory without ``ast.json``.
    """
    if not input_path.exists():
        raise ParseError(f"Report input not found: '{input_path}'")

    if input_path.is_dir():
        candidate = input_path / AST_FILENAME
        if not candidate.is_file():
            raise ParseError(
                f"No '{AST_FILENAME}' in directory '{input_path}' - pass the ast.json "
                "written by 'flowsmith convert' or its output directory"
            )
        return candidate

    if input_path.suffix.lower() == ".zip":
        sibling = input_path.parent / AST_FILENAME
        hint = f" - use '{sibling}' instead" if sibling.is_file() else ""
        raise ParseError(
            f"'{input_path.name}' is a solution package: it contains generated flow "
            f"source only, no confidence scores or ReviewFlags to report on{hint}"
        )

    if input_path.suffix.lower() != ".json":
        raise ParseError(
            f"Unsupported report input '{input_path.name}': expected an AST .json file "
            "or a 'flowsmith convert' output directory"
        )
    return input_path


def load_annotated_process(input_path: Path) -> BPProcess:
    """Load an annotated BPProcess for reporting.

    Args:
        input_path: An ``ast.json`` file or a directory containing one.

    Returns:
        The BPProcess with ``pa_annotation`` set on every stage.

    Raises:
        ParseError: If the input cannot be resolved or read.
        ASTBuildError: If the JSON does not validate as a BPProcess.
        TransformError: If annotations are missing and re-annotation fails.
    """
    process = deserialise(resolve_ast_path(input_path))
    if any(stage.pa_annotation is None for page in process.pages for stage in page.stages):
        create_annotator().annotate_process(process)
    return process
