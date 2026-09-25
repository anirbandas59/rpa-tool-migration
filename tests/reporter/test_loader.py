"""Tests for flowsmith.reporter.loader - resolving and loading report input."""

from __future__ import annotations

from pathlib import Path

import pytest

from flowsmith.ast.serialiser import serialise
from flowsmith.exceptions import ASTBuildError, ParseError
from flowsmith.reporter.loader import load_annotated_process, resolve_ast_path
from tests.reporter.conftest import make_process


class TestResolveAstPath:
    """resolve_ast_path accepts ast.json or its directory and rejects everything else."""

    def test_json_file_returned_as_is(self, ast_file: Path) -> None:
        assert resolve_ast_path(ast_file) == ast_file

    def test_directory_resolves_to_ast_json(self, ast_file: Path) -> None:
        assert resolve_ast_path(ast_file.parent) == ast_file

    def test_missing_path_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ParseError, match="not found"):
            resolve_ast_path(tmp_path / "nope.json")

    def test_directory_without_ast_json_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ParseError, match="No 'ast.json'"):
            resolve_ast_path(tmp_path)

    def test_zip_rejected_with_sibling_hint(self, ast_file: Path) -> None:
        zip_path = ast_file.parent / "solution.zip"
        zip_path.write_bytes(b"PK")
        with pytest.raises(ParseError, match="solution package.*ast.json"):
            resolve_ast_path(zip_path)

    def test_zip_rejected_without_sibling(self, tmp_path: Path) -> None:
        zip_path = tmp_path / "solution.zip"
        zip_path.write_bytes(b"PK")
        with pytest.raises(ParseError, match="solution package") as exc:
            resolve_ast_path(zip_path)
        assert "instead" not in str(exc.value)

    def test_other_suffix_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "process.bprelease"
        path.write_text("<x/>", encoding="utf-8")
        with pytest.raises(ParseError, match="Unsupported"):
            resolve_ast_path(path)


class TestLoadAnnotatedProcess:
    """load_annotated_process returns a fully annotated BPProcess."""

    def test_annotations_preserved(self, ast_file: Path) -> None:
        process = load_annotated_process(ast_file)
        stage = process.pages[0].stages[1]
        assert stage.pa_annotation is not None
        assert stage.pa_annotation.confidence == 0.15
        assert stage.pa_annotation.flags[0].severity == "error"

    def test_unannotated_ast_is_annotated_by_engine(self, tmp_path: Path) -> None:
        path = tmp_path / "ast.json"
        serialise(make_process(annotated=False), path)
        process = load_annotated_process(path)
        assert all(s.pa_annotation is not None for p in process.pages for s in p.stages)

    def test_invalid_json_raises_ast_build_error(self, tmp_path: Path) -> None:
        path = tmp_path / "ast.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(ASTBuildError):
            load_annotated_process(path)

    def test_real_pid0171_ast_loads_annotated(self, real_ast: Path) -> None:
        process = load_annotated_process(real_ast)
        assert all(s.pa_annotation is not None for p in process.pages for s in p.stages)
