"""Tests for flowsmith.ast.serialiser — JSON round-trip for BPProcess."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from deepdiff import DeepDiff

from flowsmith.ast.models import (
    BPDataItem,
    BPPage,
    BPProcess,
    BPStage,
    ConfidenceBand,
    PAAnnotation,
    ReviewFlag,
    Runtime,
    StageType,
)
from flowsmith.ast.serialiser import deserialise, from_json_str, serialise, to_json_str
from flowsmith.exceptions import ASTBuildError, GenerationError, ParseError

# ── Helpers ─────────────────────────────────────────────────────────────────


def make_minimal_process() -> BPProcess:
    """Build a minimal BPProcess with one page and one START stage, no pa_annotation."""
    return BPProcess(
        process_id="p1",
        name="TestProcess",
        version="1.0",
        source_file="test.bprelease",
        pages=[
            BPPage(
                page_id="pg1",
                name="Main",
                is_main=True,
                stages=[
                    BPStage(
                        stage_id="s1",
                        stage_type=StageType.START,
                        name="Start",
                        data_items=[],
                        exception_handler_id=None,
                        exception_type=None,
                        pair_id=None,
                        is_subsheet_call=False,
                        params_map={},
                        pa_annotation=None,
                    )
                ],
            )
        ],
    )


def make_annotated_process() -> BPProcess:
    """Build a BPProcess where the START stage has a fully populated PAAnnotation."""
    flag = ReviewFlag(
        stage_id="s1",
        reason="Manual review needed",
        severity="warn",
        suggested_fix="Check the action mapping",
    )
    annotation = PAAnnotation(
        target_type="Excel.LaunchExcel",
        target_module="Excel",
        runtime=Runtime.DESKTOP,
        params_map={"FilePath": "ExcelFilePath"},
        confidence=0.75,
        band=ConfidenceBand.SPOT_CHECK,
        flags=[flag],
    )
    stage = BPStage(
        stage_id="s1",
        stage_type=StageType.START,
        name="Start",
        data_items=[
            BPDataItem(
                name="myVar",
                data_type="text",
                initial_value="hello",
                is_input=True,
                is_output=False,
            )
        ],
        exception_handler_id="recover1",
        exception_type=None,
        pair_id=None,
        is_subsheet_call=False,
        params_map={"key": "value"},
        pa_annotation=annotation,
    )
    return BPProcess(
        process_id="p2",
        name="AnnotatedProcess",
        version="2.1",
        source_file="annotated.bprelease",
        pages=[BPPage(page_id="pg1", name="Main", is_main=True, stages=[stage])],
    )


# ── to_json_str ──────────────────────────────────────────────────────────────


def test_to_json_str_returns_string() -> None:
    result = to_json_str(make_minimal_process())
    assert isinstance(result, str)


def test_to_json_str_is_valid_json() -> None:
    result = to_json_str(make_minimal_process())
    parsed = json.loads(result)
    assert parsed["process_id"] == "p1"


# ── Round-trip tests ─────────────────────────────────────────────────────────


def test_round_trip_minimal() -> None:
    original = make_minimal_process()
    restored = from_json_str(to_json_str(original))
    diff = DeepDiff(original, restored)
    assert not diff, f"Round-trip diff: {diff}"


def test_round_trip_annotated() -> None:
    original = make_annotated_process()
    restored = from_json_str(to_json_str(original))
    diff = DeepDiff(original, restored)
    assert not diff, f"Round-trip diff: {diff}"


# ── Enum and None serialisation ───────────────────────────────────────────────


def test_enum_serialises_as_string() -> None:
    data = json.loads(to_json_str(make_minimal_process()))
    stage = data["pages"][0]["stages"][0]
    assert stage["stage_type"] == "START"
    assert isinstance(stage["stage_type"], str)


def test_none_fields_present_in_json() -> None:
    data = json.loads(to_json_str(make_minimal_process()))
    stage = data["pages"][0]["stages"][0]
    assert "pa_annotation" in stage
    assert stage["pa_annotation"] is None
    assert "exception_handler_id" in stage
    assert stage["exception_handler_id"] is None
    assert "pair_id" in stage
    assert stage["pair_id"] is None


# ── from_json_str error cases ─────────────────────────────────────────────────


def test_from_json_str_invalid_raises_ast_build_error() -> None:
    with pytest.raises(ASTBuildError):
        from_json_str('{"not": "a valid BPProcess"}')


def test_from_json_str_empty_string_raises_ast_build_error() -> None:
    with pytest.raises(ASTBuildError):
        from_json_str("")


# ── File-based serialise / deserialise ───────────────────────────────────────


def test_serialise_to_file_creates_file(tmp_path: Path) -> None:
    dest = tmp_path / "process.json"
    serialise(make_minimal_process(), dest)
    assert dest.exists()


def test_serialise_creates_parent_dirs(tmp_path: Path) -> None:
    dest = tmp_path / "sub" / "nested" / "process.json"
    serialise(make_minimal_process(), dest)
    assert dest.exists()


def test_deserialise_from_file_round_trip(tmp_path: Path) -> None:
    original = make_annotated_process()
    dest = tmp_path / "process.json"
    serialise(original, dest)
    restored = deserialise(dest)
    diff = DeepDiff(original, restored)
    assert not diff, f"Round-trip diff: {diff}"


def test_deserialise_missing_file_raises_parse_error() -> None:
    with pytest.raises(ParseError):
        deserialise(Path("nonexistent_file_xyz.json"))


def test_deserialise_invalid_json_file_raises_ast_build_error(tmp_path: Path) -> None:
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("not valid json {{{", encoding="utf-8")
    with pytest.raises(ASTBuildError):
        deserialise(bad_file)


# ── Multi-page round-trip ─────────────────────────────────────────────────────


def test_multipage_round_trip() -> None:
    wait_start = BPStage(
        stage_id="ws1",
        stage_type=StageType.WAIT,
        name="WaitBlock",
        data_items=[],
        exception_handler_id=None,
        exception_type=None,
        pair_id="ws1",
        is_subsheet_call=False,
        params_map={},
        pa_annotation=None,
    )
    wait_end = BPStage(
        stage_id="we1",
        stage_type=StageType.WAIT,
        name="WaitBlock",
        data_items=[],
        exception_handler_id=None,
        exception_type=None,
        pair_id="ws1",
        is_subsheet_call=False,
        params_map={},
        pa_annotation=None,
    )
    block_open = BPStage(
        stage_id="b1",
        stage_type=StageType.BLOCK,
        name="TryCatch",
        data_items=[],
        exception_handler_id=None,
        exception_type=None,
        pair_id="b1",
        is_subsheet_call=False,
        params_map={},
        pa_annotation=None,
    )
    block_close = BPStage(
        stage_id="b2",
        stage_type=StageType.BLOCK,
        name="TryCatch",
        data_items=[],
        exception_handler_id=None,
        exception_type=None,
        pair_id="b1",
        is_subsheet_call=False,
        params_map={},
        pa_annotation=None,
    )
    original = BPProcess(
        process_id="mp1",
        name="MultiPage",
        version="3.0",
        source_file="multi.bprelease",
        pages=[
            BPPage(
                page_id="pg1",
                name="Main",
                is_main=True,
                stages=[
                    BPStage(
                        stage_id="s1",
                        stage_type=StageType.START,
                        name="Start",
                        data_items=[],
                        exception_handler_id=None,
                        exception_type=None,
                        pair_id=None,
                        is_subsheet_call=False,
                        params_map={},
                        pa_annotation=None,
                    ),
                    wait_start,
                    wait_end,
                ],
            ),
            BPPage(
                page_id="pg2",
                name="Login",
                is_main=False,
                stages=[block_open, block_close],
            ),
            BPPage(
                page_id="pg3",
                name="Cleanup",
                is_main=False,
                stages=[
                    BPStage(
                        stage_id="s2",
                        stage_type=StageType.ACTION,
                        name="Log Out",
                        data_items=[],
                        exception_handler_id=None,
                        exception_type=None,
                        pair_id=None,
                        is_subsheet_call=True,
                        params_map={"token": "authToken"},
                        pa_annotation=None,
                    )
                ],
            ),
        ],
    )
    restored = from_json_str(to_json_str(original))
    diff = DeepDiff(original, restored)
    assert not diff, f"Round-trip diff: {diff}"


# ── Write error ───────────────────────────────────────────────────────────────


def test_write_error_raises_generation_error(tmp_path: Path) -> None:
    # Create a file where a directory would need to be — triggering an OSError on mkdir
    blocker = tmp_path / "blocker"
    blocker.write_text("I am a file, not a dir", encoding="utf-8")
    dest = blocker / "process.json"  # parent is a file, not a dir
    with pytest.raises(GenerationError):
        serialise(make_minimal_process(), dest)
