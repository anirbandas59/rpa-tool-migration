"""Tests for flowsmith.ast.builder — raw dict → BPProcess normalisation."""

from __future__ import annotations

import pytest

from flowsmith.ast import StageType, build_ast
from flowsmith.ast.builder import RawDataItem, RawPage, RawProcess, RawStage  # noqa: F401
from flowsmith.exceptions import ASTBuildError

# ── Helpers ─────────────────────────────────────────────────────────────────


def make_raw_stage(
    stage_id: str = "s1",
    stage_type: str = "Start",
    name: str = "Start",
    data_items: list[RawDataItem] | None = None,
    exception_handler_id: str | None = None,
    exception_type: str | None = None,
    params_map: dict[str, str] | None = None,
) -> RawStage:
    """Build a minimal valid RawStage dict."""
    return RawStage(
        stage_id=stage_id,
        stage_type=stage_type,
        name=name,
        data_items=data_items or [],
        exception_handler_id=exception_handler_id,
        exception_type=exception_type,
        params_map=params_map or {},
    )


def make_raw_process(
    process_id: str = "proc1",
    name: str = "TestProcess",
    version: str = "1.0",
    pages: list[RawPage] | None = None,
    source_file: str = "test.bprelease",
) -> RawProcess:
    """Build a minimal valid RawProcess dict."""
    if pages is None:
        pages = [
            RawPage(
                page_id="pg1",
                name="Main",
                stages=[],
                is_main=True,
            )
        ]
    return RawProcess(
        process_id=process_id,
        name=name,
        version=version,
        pages=pages,
        source_file=source_file,
    )


def single_page_process(*stages: RawStage, is_main: bool = True) -> RawProcess:
    """Build a RawProcess with one page containing the given stages."""
    return make_raw_process(
        pages=[
            RawPage(
                page_id="pg1",
                name="Main",
                stages=list(stages),
                is_main=is_main,
            )
        ]
    )


# ── Empty / structural tests ────────────────────────────────────────────────


def test_empty_process() -> None:
    raw = make_raw_process(pages=[])
    result = build_ast(raw)
    assert result.process_id == "proc1"
    assert result.pages == []


# ── Skip type tests ─────────────────────────────────────────────────────────


def test_skip_anchor() -> None:
    raw = single_page_process(make_raw_stage(stage_type="Anchor", name="A"))
    assert build_ast(raw).pages[0].stages == []


def test_skip_note() -> None:
    raw = single_page_process(make_raw_stage(stage_type="Note", name="N"))
    assert build_ast(raw).pages[0].stages == []


def test_skip_subsheetinfo() -> None:
    raw = single_page_process(make_raw_stage(stage_type="SubSheetInfo", name="SSI"))
    assert build_ast(raw).pages[0].stages == []


def test_skip_processinfo() -> None:
    raw = single_page_process(make_raw_stage(stage_type="ProcessInfo", name="PI"))
    assert build_ast(raw).pages[0].stages == []


def test_skip_process_type() -> None:
    raw = single_page_process(make_raw_stage(stage_type="Process", name="P"))
    assert build_ast(raw).pages[0].stages == []


def test_all_skip_types_together() -> None:
    raw = single_page_process(
        make_raw_stage(stage_id="s1", stage_type="Anchor"),
        make_raw_stage(stage_id="s2", stage_type="Note"),
        make_raw_stage(stage_id="s3", stage_type="SubSheetInfo"),
        make_raw_stage(stage_id="s4", stage_type="ProcessInfo"),
        make_raw_stage(stage_id="s5", stage_type="Process"),
    )
    assert build_ast(raw).pages[0].stages == []


# ── Direct map tests ─────────────────────────────────────────────────────────


def test_direct_map_start() -> None:
    raw = single_page_process(make_raw_stage(stage_type="Start", name="Start"))
    stage = build_ast(raw).pages[0].stages[0]
    assert stage.stage_type == StageType.START


@pytest.mark.parametrize(
    "raw_type,expected",
    [
        ("Start", StageType.START),
        ("End", StageType.END),
        ("Action", StageType.ACTION),
        ("Decision", StageType.DECISION),
        ("Calculation", StageType.CALCULATION),
        ("Code", StageType.CODE),
        ("Navigate", StageType.NAVIGATE),
        ("Read", StageType.READ),
        ("Write", StageType.WRITE),
        ("Exception", StageType.EXCEPTION),
        ("Recover", StageType.RECOVER),
        ("Resume", StageType.RESUME),
        ("Block", StageType.BLOCK),
        ("Collection", StageType.COLLECTION),
        ("Data", StageType.DATA),
    ],
)
def test_direct_map_all_canonical(raw_type: str, expected: StageType) -> None:
    # Block stages must come in pairs; supply a pair for the pairing test
    if raw_type == "Block":
        raw = single_page_process(
            make_raw_stage(stage_id="b1", stage_type="Block", name="MyBlock"),
            make_raw_stage(stage_id="b2", stage_type="Block", name="MyBlock"),
        )
        stages = build_ast(raw).pages[0].stages
        assert stages[0].stage_type == expected
    else:
        raw = single_page_process(make_raw_stage(stage_id="s1", stage_type=raw_type, name=raw_type))
        stage = build_ast(raw).pages[0].stages[0]
        assert stage.stage_type == expected


# ── Collapse: SubSheet ───────────────────────────────────────────────────────


def test_subsheet_collapses_to_action() -> None:
    raw = single_page_process(
        make_raw_stage(stage_id="ss1", stage_type="SubSheet", name="Call Login")
    )
    stage = build_ast(raw).pages[0].stages[0]
    assert stage.stage_type == StageType.ACTION
    assert stage.is_subsheet_call is True
    assert stage.stage_id == "ss1"
    assert stage.name == "Call Login"


# ── Collapse: MultipleCalculation ───────────────────────────────────────────


def test_multiple_calculation_fanout() -> None:
    raw = single_page_process(
        make_raw_stage(
            stage_id="mc1",
            stage_type="MultipleCalculation",
            name="Calc",
            params_map={"a": "x", "b": "y", "c": "z"},
        )
    )
    stages = build_ast(raw).pages[0].stages
    assert len(stages) == 3
    for i, stage in enumerate(stages, start=1):
        assert stage.stage_type == StageType.CALCULATION
        assert stage.name == f"Calc [{i}]"
    assert list(stages[0].params_map.keys()) == ["a"]
    assert list(stages[1].params_map.keys()) == ["b"]
    assert list(stages[2].params_map.keys()) == ["c"]


# ── Collapse: WaitStart / WaitEnd pairing ───────────────────────────────────


def test_wait_pair_assigned() -> None:
    raw = single_page_process(
        make_raw_stage(stage_id="ws1", stage_type="WaitStart", name="Wait"),
        make_raw_stage(stage_id="we1", stage_type="WaitEnd", name="Wait"),
    )
    stages = build_ast(raw).pages[0].stages
    assert stages[0].stage_type == StageType.WAIT
    assert stages[1].stage_type == StageType.WAIT
    assert stages[0].pair_id == "ws1"
    assert stages[1].pair_id == "ws1"


def test_unmatched_wait_raises() -> None:
    raw = single_page_process(
        make_raw_stage(stage_id="ws1", stage_type="WaitStart", name="Wait"),
    )
    with pytest.raises(ASTBuildError, match="ws1"):
        build_ast(raw)


# ── Collapse: LoopStart / LoopEnd pairing ───────────────────────────────────


def test_loop_pair_assigned() -> None:
    raw = single_page_process(
        make_raw_stage(stage_id="ls1", stage_type="LoopStart", name="Loop"),
        make_raw_stage(stage_id="le1", stage_type="LoopEnd", name="Loop"),
    )
    stages = build_ast(raw).pages[0].stages
    assert stages[0].stage_type == StageType.LOOP
    assert stages[1].stage_type == StageType.LOOP
    assert stages[0].pair_id == "ls1"
    assert stages[1].pair_id == "ls1"


def test_unmatched_loop_raises() -> None:
    raw = single_page_process(
        make_raw_stage(stage_id="ls1", stage_type="LoopStart", name="Loop"),
    )
    with pytest.raises(ASTBuildError, match="ls1"):
        build_ast(raw)


# ── Collapse: Block pairing ──────────────────────────────────────────────────


def test_block_pair_assigned() -> None:
    raw = single_page_process(
        make_raw_stage(stage_id="b1", stage_type="Block", name="TryCatch"),
        make_raw_stage(stage_id="b2", stage_type="Block", name="TryCatch"),
    )
    stages = build_ast(raw).pages[0].stages
    assert stages[0].stage_type == StageType.BLOCK
    assert stages[1].stage_type == StageType.BLOCK
    assert stages[0].pair_id == "b1"
    assert stages[1].pair_id == "b1"


def test_unmatched_block_raises() -> None:
    raw = single_page_process(
        make_raw_stage(stage_id="b1", stage_type="Block", name="TryCatch"),
    )
    with pytest.raises(ASTBuildError, match="TryCatch"):
        build_ast(raw)


# ── Error handling ───────────────────────────────────────────────────────────


def test_unknown_stage_type_raises() -> None:
    raw = single_page_process(
        make_raw_stage(stage_id="s1", stage_type="WeirdUnknownType", name="X")
    )
    with pytest.raises(ASTBuildError, match="WeirdUnknownType"):
        build_ast(raw)


def test_pydantic_error_wrapped() -> None:
    # Pass None as process_id to trigger a Pydantic ValidationError
    raw = make_raw_process()
    raw["process_id"] = None  # type: ignore[typeddict-item]
    with pytest.raises(ASTBuildError, match="AST validation failed"):
        build_ast(raw)


# ── Multi-page ───────────────────────────────────────────────────────────────


def test_multipage_process() -> None:
    raw = make_raw_process(
        pages=[
            RawPage(
                page_id="pg1",
                name="Main",
                is_main=True,
                stages=[
                    make_raw_stage(stage_id="s1", stage_type="Start"),
                    make_raw_stage(stage_id="s2", stage_type="End"),
                ],
            ),
            RawPage(
                page_id="pg2",
                name="Login",
                is_main=False,
                stages=[
                    make_raw_stage(stage_id="s3", stage_type="Action", name="Click"),
                ],
            ),
        ]
    )
    result = build_ast(raw)
    assert len(result.pages) == 2
    assert len(result.pages[0].stages) == 2
    assert len(result.pages[1].stages) == 1


# ── Specific type mapping smoke tests ───────────────────────────────────────


def test_data_stage_maps_to_data() -> None:
    raw = single_page_process(make_raw_stage(stage_type="Data", name="MyVar"))
    stage = build_ast(raw).pages[0].stages[0]
    assert stage.stage_type == StageType.DATA


def test_collection_stage_maps_to_collection() -> None:
    raw = single_page_process(make_raw_stage(stage_type="Collection", name="MyColl"))
    stage = build_ast(raw).pages[0].stages[0]
    assert stage.stage_type == StageType.COLLECTION


def test_exception_type_preserved() -> None:
    raw = single_page_process(
        make_raw_stage(
            stage_type="Exception",
            name="Throw",
            exception_type="Business Exception",
        )
    )
    stage = build_ast(raw).pages[0].stages[0]
    assert stage.stage_type == StageType.EXCEPTION
    assert stage.exception_type == "Business Exception"


def test_is_main_page_preserved() -> None:
    raw = make_raw_process(
        pages=[
            RawPage(page_id="pg1", name="Main", stages=[], is_main=True),
            RawPage(page_id="pg2", name="Sub", stages=[], is_main=False),
        ]
    )
    result = build_ast(raw)
    assert result.pages[0].is_main is True
    assert result.pages[1].is_main is False
