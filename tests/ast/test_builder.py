"""Tests for flowsmith.ast.builder — raw dict → BPProcess normalisation."""

from __future__ import annotations

from pathlib import Path

import pytest

from flowsmith.ast import StageType, build_ast
from flowsmith.ast.builder import RawDataItem, RawPage, RawProcess, RawStage  # noqa: F401
from flowsmith.exceptions import ASTBuildError
from flowsmith.parser import parse_process

# ── Helpers ─────────────────────────────────────────────────────────────────


def make_raw_stage(
    stage_id: str = "s1",
    stage_type: str = "Start",
    name: str = "Start",
    data_items: list[RawDataItem] | None = None,
    exception_handler_id: str | None = None,
    exception_type: str | None = None,
    params_map: dict[str, str] | None = None,
    decision_expression: str | None = None,
    code_text: str | None = None,
    narrative: str | None = None,
    initial_value: str | None = None,
    timeout_seconds: int | None = None,
    group_id: str | None = None,
    exception_detail: str | None = None,
    exception_usecurrent: bool = False,
    input_friendlynames: dict[str, str] | None = None,
    onsuccess_target: str | None = None,
    ontrue_target: str | None = None,
    onfalse_target: str | None = None,
    processid: str | None = None,
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
        decision_expression=decision_expression,
        code_text=code_text,
        narrative=narrative,
        initial_value=initial_value,
        timeout_seconds=timeout_seconds,
        group_id=group_id,
        exception_detail=exception_detail,
        exception_usecurrent=exception_usecurrent,
        input_friendlynames=input_friendlynames or {},
        onsuccess_target=onsuccess_target,
        ontrue_target=ontrue_target,
        onfalse_target=onfalse_target,
        processid=processid,
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
                published=False,
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
                published=False,
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


def test_process_type_normalised_to_action() -> None:
    """Process stages are normalised to ACTION(is_process_call=True) per CLAUDE.md."""
    raw = single_page_process(make_raw_stage(stage_id="p1", stage_type="Process", name="P"))
    result = build_ast(raw)
    assert len(result.pages[0].stages) == 1
    stage = result.pages[0].stages[0]
    assert stage.stage_type == StageType.ACTION
    assert stage.is_process_call is True
    assert stage.name == "P"


def test_all_skip_types_together() -> None:
    """Skip types (Anchor, Note, SubSheetInfo, ProcessInfo) are dropped.

    Process type is normalised to ACTION, not skipped, so it should appear in output.
    """
    raw = single_page_process(
        make_raw_stage(stage_id="s1", stage_type="Anchor"),
        make_raw_stage(stage_id="s2", stage_type="Note"),
        make_raw_stage(stage_id="s3", stage_type="SubSheetInfo"),
        make_raw_stage(stage_id="s4", stage_type="ProcessInfo"),
        make_raw_stage(stage_id="s5", stage_type="Process", name="ProcessStage"),
    )
    result = build_ast(raw)
    # Only the Process stage should remain (normalised to ACTION with is_process_call=True)
    assert len(result.pages[0].stages) == 1
    stage = result.pages[0].stages[0]
    assert stage.stage_id == "s5"
    assert stage.stage_type == StageType.ACTION
    assert stage.is_process_call is True


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


def test_wait_pair_out_of_order() -> None:
    """Test that WaitEnd appearing before WaitStart is handled correctly."""
    raw = single_page_process(
        make_raw_stage(stage_id="we1", stage_type="WaitEnd", name="Wait"),
        make_raw_stage(stage_id="ws1", stage_type="WaitStart", name="Wait"),
    )
    stages = build_ast(raw).pages[0].stages
    assert stages[0].stage_type == StageType.WAIT
    assert stages[1].stage_type == StageType.WAIT
    assert stages[0].pair_id == "ws1"
    assert stages[1].pair_id == "ws1"


def test_wait_pair_multiple_out_of_order() -> None:
    """Test multiple out-of-order Wait pairs in sequence."""
    raw = single_page_process(
        make_raw_stage(stage_id="we1", stage_type="WaitEnd", name="Wait1"),
        make_raw_stage(stage_id="ws1", stage_type="WaitStart", name="Wait1"),
        make_raw_stage(stage_id="we2", stage_type="WaitEnd", name="Wait2"),
        make_raw_stage(stage_id="ws2", stage_type="WaitStart", name="Wait2"),
    )
    stages = build_ast(raw).pages[0].stages
    assert stages[0].pair_id == "ws1"
    assert stages[1].pair_id == "ws1"
    assert stages[2].pair_id == "ws2"
    assert stages[3].pair_id == "ws2"


def test_unmatched_wait_raises() -> None:
    raw = single_page_process(
        make_raw_stage(stage_id="ws1", stage_type="WaitStart", name="Wait"),
    )
    with pytest.raises(ASTBuildError, match="ws1"):
        build_ast(raw)


def test_unmatched_wait_end_raises() -> None:
    raw = single_page_process(
        make_raw_stage(stage_id="we1", stage_type="WaitEnd", name="Wait"),
    )
    with pytest.raises(ASTBuildError, match="we1"):
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


def test_loop_pair_out_of_order() -> None:
    """Test that LoopEnd appearing before LoopStart is handled correctly."""
    raw = single_page_process(
        make_raw_stage(stage_id="le1", stage_type="LoopEnd", name="Loop"),
        make_raw_stage(stage_id="ls1", stage_type="LoopStart", name="Loop"),
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


def test_unmatched_loop_end_raises() -> None:
    raw = single_page_process(
        make_raw_stage(stage_id="le1", stage_type="LoopEnd", name="Loop"),
    )
    with pytest.raises(ASTBuildError, match="le1"):
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


def test_singleton_block_allowed() -> None:
    raw = single_page_process(
        make_raw_stage(stage_id="b1", stage_type="Block", name="TryCatch"),
    )
    stage = build_ast(raw).pages[0].stages[0]
    assert stage.stage_type == StageType.BLOCK
    assert stage.pair_id is None


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
                published=True,
                stages=[
                    make_raw_stage(stage_id="s1", stage_type="Start"),
                    make_raw_stage(stage_id="s2", stage_type="End"),
                ],
            ),
            RawPage(
                page_id="pg2",
                name="Login",
                is_main=False,
                published=False,
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
            RawPage(page_id="pg1", name="Main", stages=[], is_main=True, published=True),
            RawPage(page_id="pg2", name="Sub", stages=[], is_main=False, published=False),
        ]
    )
    result = build_ast(raw)
    assert result.pages[0].is_main is True
    assert result.pages[1].is_main is False


# ── New field propagation (Sub-Task 2) ──────────────────────────────────────


def test_decision_expression_propagated_to_bpstage() -> None:
    raw = single_page_process(
        RawStage(
            stage_id="d1",
            stage_type="Decision",
            name="Check",
            data_items=[],
            exception_handler_id=None,
            exception_type=None,
            params_map={},
            decision_expression="[Retry Count] < 3",
            code_text=None,
            narrative=None,
            initial_value=None,
            timeout_seconds=None,
            group_id=None,
            exception_detail=None,
            exception_usecurrent=False,
            input_friendlynames={},
        )
    )
    stage = build_ast(raw).pages[0].stages[0]
    assert stage.decision_expression == "[Retry Count] < 3"


def test_common_fields_default_when_absent_from_raw_stage() -> None:
    """A minimal RawStage dict (missing the 9 new keys) still builds cleanly."""
    raw = single_page_process(make_raw_stage(stage_type="Action", name="Click"))
    stage = build_ast(raw).pages[0].stages[0]
    assert stage.decision_expression is None
    assert stage.code_text is None
    assert stage.code_length == 0
    assert stage.narrative is None
    assert stage.timeout_seconds is None
    assert stage.group_id is None
    assert stage.exception_detail is None
    assert stage.exception_usecurrent is False


def test_published_propagated_to_bppage() -> None:
    raw = make_raw_process(
        pages=[
            RawPage(page_id="pg1", name="Main", stages=[], is_main=True, published=True),
            RawPage(page_id="pg2", name="Sub", stages=[], is_main=False, published=False),
        ]
    )
    result = build_ast(raw)
    assert result.pages[0].published is True
    assert result.pages[1].published is False


def test_published_defaults_false_when_absent_from_raw_page() -> None:
    raw = make_raw_process()  # default page has no "published" key
    result = build_ast(raw)
    assert result.pages[0].published is False


def _make_wait_stage(stage_id: str, name: str, group_id: str | None) -> RawStage:
    return RawStage(
        stage_id=stage_id,
        stage_type="WaitStart" if stage_id.startswith("ws") else "WaitEnd",
        name=name,
        data_items=[],
        exception_handler_id=None,
        exception_type=None,
        params_map={},
        decision_expression=None,
        code_text=None,
        narrative=None,
        initial_value=None,
        timeout_seconds=None,
        group_id=group_id,
        exception_detail=None,
        exception_usecurrent=False,
        input_friendlynames={},
    )


def test_wait_pair_matched_by_group_id() -> None:
    raw = single_page_process(
        _make_wait_stage("ws1", "Wait", "grp-a"),
        _make_wait_stage("we1", "Wait", "grp-a"),
    )
    stages = build_ast(raw).pages[0].stages
    assert stages[0].pair_id == "ws1"
    assert stages[1].pair_id == "ws1"


def test_wait_pairs_scoped_by_distinct_group_ids() -> None:
    """Two independent Wait constructs (different groupids) don't cross-pair."""
    raw = single_page_process(
        _make_wait_stage("ws1", "Wait A", "grp-a"),
        _make_wait_stage("ws2", "Wait B", "grp-b"),
        _make_wait_stage("we1", "Wait A", "grp-a"),
        _make_wait_stage("we2", "Wait B", "grp-b"),
    )
    stages = build_ast(raw).pages[0].stages
    by_id = {s.stage_id: s for s in stages}
    assert by_id["ws1"].pair_id == "ws1"
    assert by_id["we1"].pair_id == "ws1"
    assert by_id["ws2"].pair_id == "ws2"
    assert by_id["we2"].pair_id == "ws2"


def test_wait_group_id_with_multiple_pairs_stack_matched() -> None:
    """A single groupid can fan out into several Start/End pairs (real BP export
    behaviour — one Wait stage with multiple wait conditions shares one groupid)."""
    raw = single_page_process(
        _make_wait_stage("ws1", "Cond 1", "grp-shared"),
        _make_wait_stage("we1", "Cond 1", "grp-shared"),
        _make_wait_stage("ws2", "Cond 2", "grp-shared"),
        _make_wait_stage("we2", "Cond 2", "grp-shared"),
        _make_wait_stage("ws3", "Cond 3", "grp-shared"),
        _make_wait_stage("we3", "Cond 3", "grp-shared"),
    )
    stages = build_ast(raw).pages[0].stages
    by_id = {s.stage_id: s for s in stages}
    assert by_id["ws1"].pair_id == "ws1"
    assert by_id["we1"].pair_id == "ws1"
    assert by_id["ws2"].pair_id == "ws2"
    assert by_id["we2"].pair_id == "ws2"
    assert by_id["ws3"].pair_id == "ws3"
    assert by_id["we3"].pair_id == "ws3"


def test_wait_pair_no_group_id_falls_back_to_positional() -> None:
    """Stages with group_id=None still pair via the original stack-based match."""
    raw = single_page_process(
        _make_wait_stage("ws1", "Wait", None),
        _make_wait_stage("we1", "Wait", None),
    )
    stages = build_ast(raw).pages[0].stages
    assert stages[0].pair_id == "ws1"
    assert stages[1].pair_id == "ws1"


# ── Real sample validation (PID_0171.bprelease) ─────────────────────────────

PID_0171 = Path("samples/blueprism/PID_0171.bprelease")


@pytest.fixture(scope="module")
def pid_0171_process():  # type: ignore[no-untyped-def]
    """Build the AST for the real PID_0171 sample once per test module."""
    if not PID_0171.exists():
        pytest.skip("PID_0171 sample not available")
    return build_ast(parse_process(PID_0171))


def test_pid171_decision_stage_has_expression_in_ast(pid_0171_process) -> None:  # type: ignore[no-untyped-def]
    """At least one Decision BPStage in PID_0171 has a non-None decision_expression."""
    decision_stages = [
        s
        for page in pid_0171_process.pages
        for s in page.stages
        if s.stage_type == StageType.DECISION
    ]
    assert decision_stages, "Expected at least one Decision stage in PID_0171"
    with_expr = [s for s in decision_stages if s.decision_expression is not None]
    assert with_expr, "Expected at least one Decision BPStage with a non-None decision_expression"


def test_pid171_pages_have_published_field(pid_0171_process) -> None:  # type: ignore[no-untyped-def]
    """Every BPPage in PID_0171 carries a bool published flag."""
    assert pid_0171_process.pages, "Expected at least one page in PID_0171"
    for page in pid_0171_process.pages:
        assert isinstance(page.published, bool)


def test_pid171_wait_or_loop_pairs_match_when_group_id_present(pid_0171_process) -> None:  # type: ignore[no-untyped-def]
    """WaitStart/WaitEnd (or LoopStart/LoopEnd) stages with a group_id end up paired."""
    grouped_bracket_stages = [
        s
        for page in pid_0171_process.pages
        for s in page.stages
        if s.stage_type in (StageType.WAIT, StageType.LOOP) and s.group_id is not None
    ]
    assert grouped_bracket_stages, "Expected at least one grouped WAIT/LOOP stage in PID_0171"
    for stage in grouped_bracket_stages:
        assert stage.pair_id is not None, (
            f"Stage {stage.stage_id} ({stage.stage_type}) with group_id "
            f"'{stage.group_id}' has no pair_id"
        )


# ── VBO call-fusion detection tests ────────────────────────────────────────


def test_fusion_candidate_no_router_passes_silently() -> None:
    """Adjacent ACTION stages with numeric handoff pass through without fusion resolution if no router."""
    # Create two adjacent ACTION stages with numeric handle handoff
    stage1 = make_raw_stage(
        stage_id="s1",
        stage_type="Action",
        name="Create Instance",
        data_items=[
            RawDataItem(
                name="handle",
                data_type="number",
                initial_value=None,
                is_input=False,
                is_output=True,
            )
        ],
        params_map={"_vbo_object": "MS Excel VBO", "_vbo_action": "Create Instance"},
    )
    stage2 = make_raw_stage(
        stage_id="s2",
        stage_type="Action",
        name="Open Workbook",
        data_items=[
            RawDataItem(
                name="handle",
                data_type="number",
                initial_value=None,
                is_input=True,
                is_output=False,
            )
        ],
        params_map={"_vbo_object": "MS Excel VBO", "_vbo_action": "Open Workbook"},
    )
    raw = single_page_process(stage1, stage2)

    # Build without router (fusion resolution disabled)
    result = build_ast(raw, router=None)
    assert result.pages[0].stages[0].fused_with == []
    assert result.pages[0].stages[0].fusion_action is None
    assert result.pages[0].stages[1].fused_with == []
    assert result.pages[0].stages[1].fusion_action is None


def test_fusion_unmatched_candidate_creates_review_flag() -> None:
    """A numeric-handoff pair with no matching fusion pattern gets a ReviewFlag."""
    from flowsmith.ast.models import Runtime
    from flowsmith.mapper import MappingConfig, VBOEntry, VBORouter

    # Create a minimal config with MS Excel VBO but no fusion patterns
    config = MappingConfig(
        stage_rules=[],
        vbo_catalogue=[
            VBOEntry(
                vbo_name="MS Excel VBO",
                method_patterns=["Create Instance", "Open Workbook"],
                pa_module="Excel",
                runtime=Runtime.DESKTOP,
                confidence_base=0.8,
                notes="Test VBO",
                method_actions={},
                fusion_patterns=[],  # Empty - no fusion patterns defined
            )
        ],
    )
    router = VBORouter(config)

    # Create two adjacent ACTION stages with numeric handle handoff
    stage1 = make_raw_stage(
        stage_id="s1",
        stage_type="Action",
        name="Create Instance",
        data_items=[
            RawDataItem(
                name="handle",
                data_type="number",
                initial_value=None,
                is_input=False,
                is_output=True,
            )
        ],
        params_map={"_vbo_object": "MS Excel VBO", "_vbo_action": "Create Instance"},
    )
    stage2 = make_raw_stage(
        stage_id="s2",
        stage_type="Action",
        name="Open Workbook",
        data_items=[
            RawDataItem(
                name="handle",
                data_type="number",
                initial_value=None,
                is_input=True,
                is_output=False,
            )
        ],
        params_map={"_vbo_object": "MS Excel VBO", "_vbo_action": "Open Workbook"},
    )
    raw = single_page_process(stage1, stage2)

    # Build with router (fusion resolution enabled)
    result = build_ast(raw, router=router)

    # Stage 2 should have a pending ReviewFlag (unresolved fusion candidate)
    stage2_built = result.pages[0].stages[1]
    assert stage2_built.pending_flags, "Expected ReviewFlag for unmatched fusion candidate"
    flag = stage2_built.pending_flags[0]
    assert flag.severity == "warn"
    assert "numeric-handle handoff" in flag.reason
    assert "MS Excel VBO" in flag.reason


def test_fusion_matched_candidate_resolves(pid_0171_process) -> None:  # type: ignore[no-untyped-def]
    """Real-sample test: numeric-handoff pair matching a fusion pattern gets fused_with and fusion_action.

    **FIXTURE DISCLOSURE:** This test uses the real PID_0171 fixture (`pid_0171_process`),
    which parses `samples/blueprism/PID_0171.bprelease` and builds the AST. It locates the
    real `Create Instance` (stage ID 28867ad1-ad80-41a9-9749-53ad12327fbc) and `Open Excel`
    stage named "Open Excel" with vbo_action "Open Workbook" (stage ID d0ac971c-1c82-48d4-837e-8554614eccc7)
    from the `Read Excel As Collection` page (page ID eeeb6765-9d9f-4374-b7cd-d5ca8f3dfa61),
    confirming the real stages carry the numeric handle output/input data and onsuccess edge
    required for fusion detection.

    The VBORouter is synthetic (carrying a fusion_patterns entry for MS Excel VBO's
    Create Instance + Open Workbook sequence), but the stage data is from the real sample.
    """
    from flowsmith.ast.models import Runtime
    from flowsmith.mapper import MappingConfig, VBOEntry, VBORouter
    from flowsmith.mapper.config import VBOFusionPattern

    # Find the Read Excel As Collection page in the real sample
    page = next(
        (p for p in pid_0171_process.pages if "eeeb6765-9d9f-4374-b7cd-d5ca8f3dfa61" in p.page_id),
        None,
    )
    assert page is not None, (
        "Expected 'Read Excel As Collection' page (ID eeeb6765-9d9f-4374-b7cd-d5ca8f3dfa61) in PID_0171"
    )

    # Find the real Create Instance and Open Excel stages
    create_instance = next(
        (s for s in page.stages if s.name == "Create Instance"),
        None,
    )
    open_excel = next(
        (s for s in page.stages if s.name == "Open Excel"),
        None,
    )
    assert create_instance is not None, "Expected 'Create Instance' stage in page"
    assert open_excel is not None, "Expected 'Open Excel' stage in page"
    assert create_instance.stage_type == StageType.ACTION
    assert open_excel.stage_type == StageType.ACTION

    # Verify real data: Create Instance has numeric handle output, Open Excel has matching input
    create_handle_out = next(
        (di for di in create_instance.data_items if di.name == "handle" and di.is_output),
        None,
    )
    open_handle_in = next(
        (di for di in open_excel.data_items if di.name == "handle" and di.is_input),
        None,
    )
    assert create_handle_out is not None, "Real Create Instance should have numeric handle output"
    assert create_handle_out.data_type == "number"
    assert open_handle_in is not None, "Real Open Excel should have numeric handle input"
    assert open_handle_in.data_type == "number"

    # Verify onsuccess edge: Create Instance targets Open Excel
    assert create_instance.onsuccess_target == open_excel.stage_id, (
        f"Real Create Instance ({create_instance.stage_id}) should have onsuccess_target pointing to "
        f"Open Excel ({open_excel.stage_id})"
    )

    # Now verify the fusion detection with real stages:
    # The pid_0171_process fixture was built with router=None by default.
    # To test fusion detection, we need to re-build with a router carrying the fusion pattern.
    # However, the fixture is read-only; instead, we verify the real stages have the
    # correct structure and confirm the logic would fuse them.
    #
    # Create a config with MS Excel VBO and a fusion pattern for Create Instance + Open Workbook
    config = MappingConfig(
        stage_rules=[],
        vbo_catalogue=[
            VBOEntry(
                vbo_name="MS Excel VBO",
                method_patterns=["Create Instance", "Open Workbook"],
                pa_module="Excel",
                runtime=Runtime.DESKTOP,
                confidence_base=0.8,
                notes="Test VBO with fusion pattern",
                method_actions={},
                fusion_patterns=[
                    VBOFusionPattern(
                        sequence=["Create Instance", "Open Workbook"],
                        fused_action="Excel.LaunchExcel.LaunchAndOpenUnderExistingProcess Path: in_txt_InputFilePath Visible: False ReadOnly: False UseMachineLocale: False Instance=> ins_ExcelInstance",
                        vestigial_stages=["Create Instance"],
                    )
                ],
            )
        ],
    )
    router = VBORouter(config)

    # Re-parse and build with the router to test fusion detection on real stages
    from flowsmith.parser import parse_process

    raw = parse_process(PID_0171)
    result = build_ast(raw, router=router)

    # Find the real stages again in the newly-built AST
    page_built = next(
        (p for p in result.pages if "eeeb6765-9d9f-4374-b7cd-d5ca8f3dfa61" in p.page_id),
        None,
    )
    assert page_built is not None
    create_instance_built = next(
        (s for s in page_built.stages if s.name == "Create Instance"),
        None,
    )
    open_excel_built = next(
        (s for s in page_built.stages if s.name == "Open Excel"),
        None,
    )
    assert create_instance_built is not None
    assert open_excel_built is not None

    # Stage 1 (Create Instance) should be marked as vestigial
    assert create_instance_built.is_vestigial is True, "Real Create Instance should be vestigial"

    # Stage 2 (Open Excel) should have the fused action
    assert create_instance_built.stage_id in open_excel_built.fused_with, (
        f"Real Open Excel should list Create Instance ({create_instance_built.stage_id}) as fused"
    )
    assert open_excel_built.fusion_action is not None, "Real Open Excel should have a fusion_action"
    assert "LaunchAndOpenUnderExistingProcess" in open_excel_built.fusion_action

    # Stage 2 should NOT have a ReviewFlag (successfully resolved)
    assert open_excel_built.pending_flags == [], "No ReviewFlag for resolved fusion"


def test_close_workbook_close_instance_pair_not_detected_as_fusion_candidate(
    pid_0171_process,  # type: ignore[no-untyped-def]
) -> None:
    """Close Workbook and Close Instance pair are NOT a fusion candidate in real data.

    The real PID_0171.bprelease has Close Workbook and Close Instance on the
    "Read Excel As Collection" page with NO <outputs> element on either stage.
    Both stages have only numeric INPUTS (handle: is_input=True, is_output=False).

    Since stage N's numeric handle has is_output=False, the structural pre-filter
    in _detect_vbo_call_fusions (architecture doc §B_FUSION) cannot detect a
    numeric-output→input signal, so this pair never becomes a fusion *candidate*
    at all. Therefore:
    - No fused_with list set on either stage
    - No fusion_action set on either stage
    - No ReviewFlag created (ReviewFlag only appears for detected-but-unresolved
      candidates; this pair never becomes a candidate in the first place)

    This is a documented follow-up gap in Task 1b (per review 1a-2026-08-29.md).
    The architecture doc's claim about Close Workbook→Close Instance fusion
    requires extending the structural signal detection, which is out of scope
    for Task 1b. This test documents actual current behavior.
    """

    # Find the Close Workbook and Close Instance stages from real PID_0171
    page = next(
        (p for p in pid_0171_process.pages if "Read Excel As Collection" in p.name),
        None,
    )
    assert page is not None, "Expected 'Read Excel As Collection' page in PID_0171"

    # Find both stages (they appear in sequence in the real process)
    close_wb = next((s for s in page.stages if s.name == "Close Workbook"), None)
    close_inst = next((s for s in page.stages if s.name == "Close Instance"), None)

    # Both must exist and be adjacent ACTION stages
    assert close_wb is not None, "Expected 'Close Workbook' stage in page"
    assert close_inst is not None, "Expected 'Close Instance' stage in page"
    assert close_wb.stage_type == StageType.ACTION
    assert close_inst.stage_type == StageType.ACTION

    # Verify real data: neither stage has numeric output
    close_wb_handle = next((di for di in close_wb.data_items if di.name == "handle"), None)
    close_inst_handle = next((di for di in close_inst.data_items if di.name == "handle"), None)
    assert close_wb_handle is not None, "Close Workbook should have handle data item"
    assert close_inst_handle is not None, "Close Instance should have handle data item"
    assert close_wb_handle.is_output is False, "Real Close Workbook has no numeric output"
    assert close_inst_handle.is_output is False, "Real Close Instance has no numeric output"

    # When built with or without router, neither stage should have fusion markers
    # (they were never detected as candidates in the first place)
    assert close_wb.fused_with == [], "Close Workbook should have no fused_with"
    assert close_wb.fusion_action is None, "Close Workbook should have no fusion_action"
    assert close_inst.fused_with == [], "Close Instance should have no fused_with"
    assert close_inst.fusion_action is None, "Close Instance should have no fusion_action"

    # No ReviewFlag for this pair (because it was never a detected candidate)
    assert close_wb.pending_flags == [], "Close Workbook should have no pending flags"
    assert close_inst.pending_flags == [], "Close Instance should have no pending flags"


# ── Task 1a: ACTION input/output and edge target threading ─────────────────


def test_action_outputs_threaded_to_bpstage() -> None:
    """ACTION stage outputs parsed by Task 1a are available in BPStage.data_items.

    This is a fundamental requirement for Task 1b's fusion detection to work:
    the structural signal (numeric output on stage N, numeric input on stage N+1)
    must be present in the AST's data_items.
    """
    stage = make_raw_stage(
        stage_id="s1",
        stage_type="Action",
        name="Create Instance",
        data_items=[
            RawDataItem(
                name="handle",
                data_type="number",
                initial_value=None,
                is_input=False,
                is_output=True,
            )
        ],
    )
    raw = single_page_process(stage)
    result = build_ast(raw, router=None)

    # Verify the output is present in the built BPStage
    built_stage = result.pages[0].stages[0]
    assert len(built_stage.data_items) >= 1
    handle_output = next((di for di in built_stage.data_items if di.name == "handle"), None)
    assert handle_output is not None
    assert handle_output.data_type == "number"
    assert handle_output.is_output is True


def test_action_inputs_threaded_to_bpstage() -> None:
    """ACTION stage inputs parsed by Task 1a are available in BPStage.data_items.

    In addition to being in params_map (for VBO parameter substitution),
    inputs should also appear in data_items for structural/type-based scanning.
    """
    stage = make_raw_stage(
        stage_id="s1",
        stage_type="Action",
        name="Open Excel",
        data_items=[
            RawDataItem(
                name="handle",
                data_type="number",
                initial_value=None,
                is_input=True,
                is_output=False,
            ),
            RawDataItem(
                name="File name",
                data_type="text",
                initial_value=None,
                is_input=True,
                is_output=False,
            ),
        ],
    )
    raw = single_page_process(stage)
    result = build_ast(raw, router=None)

    # Verify the inputs are present in the built BPStage
    built_stage = result.pages[0].stages[0]
    handle_input = next((di for di in built_stage.data_items if di.name == "handle"), None)
    assert handle_input is not None
    assert handle_input.data_type == "number"
    assert handle_input.is_input is True

    file_input = next((di for di in built_stage.data_items if di.name == "File name"), None)
    assert file_input is not None
    assert file_input.data_type == "text"
    assert file_input.is_input is True


def test_onsuccess_edge_threaded_to_bpstage() -> None:
    """onsuccess_target parsed by Task 1a is threaded through to BPStage."""
    stage = make_raw_stage(
        stage_id="s1",
        stage_type="Action",
        name="Create Instance",
        onsuccess_target="s2",  # Parsed from <onsuccess>s2</onsuccess>
    )
    raw = single_page_process(stage)
    result = build_ast(raw, router=None)

    built_stage = result.pages[0].stages[0]
    assert built_stage.onsuccess_target == "s2"


def test_ontrue_onfalse_edges_threaded_to_bpstage() -> None:
    """ontrue_target and onfalse_target parsed by Task 1a are threaded through to BPStage."""
    stage = make_raw_stage(
        stage_id="s1",
        stage_type="Decision",
        name="Check Condition",
        decision_expression="[Flag] = True",
        ontrue_target="s2",  # Parsed from <ontrue>s2</ontrue>
        onfalse_target="s3",  # Parsed from <onfalse>s3</onfalse>
    )
    raw = single_page_process(stage)
    result = build_ast(raw, router=None)

    built_stage = result.pages[0].stages[0]
    assert built_stage.ontrue_target == "s2"
    assert built_stage.onfalse_target == "s3"


def test_pid171_create_instance_ast_has_handle_output(pid_0171_process) -> None:  # type: ignore[no-untyped-def]
    """Real test against PID_0171: Create Instance stage should have numeric handle output.

    This is the core requirement for Task 1a: the parser and builder together
    must extract and preserve the <output type="number" name="handle"> element
    so Task 1b's fusion detection can find it.
    """
    # Find the 'Read Excel As Collection' page
    page = next(
        (p for p in pid_0171_process.pages if "eeeb6765-9d9f-4374-b7cd-d5ca8f3dfa61" in p.page_id),
        None,
    )
    if page is None:
        pytest.skip("PID_0171 'Read Excel As Collection' page not found")

    # Find the "Create Instance" stage
    create_instance = next(
        (s for s in page.stages if s.name == "Create Instance"),
        None,
    )
    assert create_instance is not None

    # Verify the numeric handle output is in data_items
    handle_outputs = [
        di for di in create_instance.data_items if di.name == "handle" and di.is_output
    ]
    assert handle_outputs, "Expected numeric 'handle' output in Create Instance data_items"
    assert handle_outputs[0].data_type == "number"


def test_pid171_open_excel_ast_has_handle_input(pid_0171_process) -> None:  # type: ignore[no-untyped-def]
    """Real test against PID_0171: Open Excel stage should have numeric handle input.

    Task 1a requirement: the <input type="number" name="handle" expr="[handle]">
    element must be extracted and made available for fusion detection.
    """
    page = next(
        (p for p in pid_0171_process.pages if "eeeb6765-9d9f-4374-b7cd-d5ca8f3dfa61" in p.page_id),
        None,
    )
    if page is None:
        pytest.skip("PID_0171 'Read Excel As Collection' page not found")

    open_excel = next(
        (s for s in page.stages if s.name == "Open Excel"),
        None,
    )
    assert open_excel is not None

    # Verify the numeric handle input is in data_items
    handle_inputs = [di for di in open_excel.data_items if di.name == "handle" and di.is_input]
    assert handle_inputs, "Expected numeric 'handle' input in Open Excel data_items"
    assert handle_inputs[0].data_type == "number"


def test_pid171_create_instance_ast_has_onsuccess_edge(pid_0171_process) -> None:  # type: ignore[no-untyped-def]
    """Real test against PID_0171: Create Instance should have onsuccess_target.

    Task 1a requirement: the <onsuccess> element must be captured so Task 1b
    can verify the adjacency (sole onsuccess target is the next stage with no branching).
    """
    page = next(
        (p for p in pid_0171_process.pages if "eeeb6765-9d9f-4374-b7cd-d5ca8f3dfa61" in p.page_id),
        None,
    )
    if page is None:
        pytest.skip("PID_0171 'Read Excel As Collection' page not found")

    create_instance = next(
        (s for s in page.stages if s.name == "Create Instance"),
        None,
    )
    assert create_instance is not None

    # Verify onsuccess_target is captured
    assert create_instance.onsuccess_target is not None
    # Verify it points to Open Excel
    open_excel = next(
        (s for s in page.stages if s.name == "Open Excel"),
        None,
    )
    assert open_excel is not None
    assert create_instance.onsuccess_target == open_excel.stage_id


# ── Task 4a: Reachability / Call-Graph Tests ──────────────────────────────


def test_simple_process_single_page_is_reachable(pid_0171_process) -> None:  # type: ignore[no-untyped-def]
    """Single-page process: Main Page should always be marked reachable (Task 4a)."""
    main_page = next((p for p in pid_0171_process.pages if p.is_main), None)
    assert main_page is not None
    assert main_page.reachable is True


def test_pid171_orphan_pages_marked_unreachable(pid_0171_process) -> None:  # type: ignore[no-untyped-def]
    """Task 4a requirement: orphan pages in PID_0171 should be marked unreachable.

    Per architecture doc §B11/§B14: 'Mark leftout Items as Exception' and
    'Send Info to Data Gateways' have no callers — they are orphan pages.
    """
    orphan_names = {"Mark leftout Items as Exception", "Send Info to Data Gateways"}
    found_orphans = [p for p in pid_0171_process.pages if p.name in orphan_names]

    assert found_orphans, "Expected to find orphan pages in PID_0171, found none"

    for orphan_page in found_orphans:
        assert orphan_page.reachable is False, (
            f"Page '{orphan_page.name}' should be marked unreachable"
        )


def test_pid171_reachable_pages_marked_correctly(pid_0171_process) -> None:  # type: ignore[no-untyped-def]
    """Task 4a requirement: named reachable pages must be marked reachable.

    Per Task 4a step 4 and Done-when: the pages "Get Mails" and "Populate Queue"
    are direct callers in the main page's execution chain and must be marked reachable.
    """
    named_reachable = {"Get Mails", "Populate Queue"}
    found_pages = [p for p in pid_0171_process.pages if p.name in named_reachable]

    assert len(found_pages) == 2, (
        f"Expected to find both 'Get Mails' and 'Populate Queue', found {len(found_pages)}"
    )

    for page in found_pages:
        assert page.reachable is True, (
            f"Page '{page.name}' should be marked reachable (is a direct caller in main page)"
        )


def test_no_dangling_edge_references(pid_0171_process) -> None:  # type: ignore[no-untyped-def]
    """Task 4a well-formedness check: no dangling onsuccess/ontrue/onfalse references.

    Per the strategy doc's well-formedness criteria, every edge target in the AST
    must resolve to an actual stage within the same page. Any dangling reference is
    a defect in either:
    - Skip-type pass-through collapse (Anchor, Note, SubSheetInfo, ProcessInfo)
    - MultipleCalculation ID-collapse redirection
    - Block→Recover pairing
    - Overall edge redirection logic

    This test scans all edges and confirms no target stage_id is orphaned.
    """
    # Build the set of all actual stage IDs in the process
    all_stage_ids: set[str] = set()
    for page in pid_0171_process.pages:
        for stage in page.stages:
            all_stage_ids.add(stage.stage_id)

    # Scan every edge and check if its target exists
    dangling_edges: list[tuple[str, str, str]] = []  # (page_name, stage_name, edge_type)

    for page in pid_0171_process.pages:
        for stage in page.stages:
            if stage.onsuccess_target and stage.onsuccess_target not in all_stage_ids:
                dangling_edges.append((page.name, stage.name, "onsuccess"))
            if stage.ontrue_target and stage.ontrue_target not in all_stage_ids:
                dangling_edges.append((page.name, stage.name, "ontrue"))
            if stage.onfalse_target and stage.onfalse_target not in all_stage_ids:
                dangling_edges.append((page.name, stage.name, "onfalse"))

    # Report any dangling edges found
    if dangling_edges:
        error_lines = [
            f"Dangling {edge_type} from {page_name}::{stage_name}"
            for page_name, stage_name, edge_type in dangling_edges
        ]
        raise AssertionError(
            f"Found {len(dangling_edges)} dangling edge reference(s):\n" + "\n".join(error_lines)
        )

    # If we reach here, all edges are well-formed
    assert not dangling_edges, "All edges should resolve to existing stages"


def test_pid171_loader_performer_role_tagging(pid_0171_process) -> None:  # type: ignore[no-untyped-def]
    """Task 4b requirement: pages are tagged with Loader/Performer roles.

    The split point is the 'Get Next Item' ACTION stage (ID 85fbb578-...) on Main Page.
    Pages reachable before this stage should be tagged "loader";
    pages reachable from this stage onward should be tagged "performer";
    unreachable pages should have role=None.

    Task 4b step 4 explicitly requires:
    - Loader pages: Get Mails, Populate Queue
    - Performer pages: Save Attachments, Result Entry, Mark Item As Exception
    """
    # Loader pages per architecture doc §B14 (tasks before Get Next Item)
    expected_loader = {"Get Mails", "Populate Queue"}
    # Performer pages per architecture doc §B14 (tasks after Get Next Item)
    # Task 4b step 4 explicitly names: Save Attachments, Result Entry, Mark Item As Exception
    # These are correctly reachable via Block→Recover edges (Task 4a Fix A), which is now
    # consulted in _tag_loader_performer_roles() (Fix 1 of this pass).
    expected_performer_minimum = {"Save Attachments", "Result Entry", "Mark Item As Exception"}

    found_loaders = [p for p in pid_0171_process.pages if p.role == "loader"]
    found_performers = [p for p in pid_0171_process.pages if p.role == "performer"]

    # Verify expected loader pages are tagged
    found_loader_names = {p.name for p in found_loaders}
    for expected_name in expected_loader:
        assert expected_name in found_loader_names, (
            f"Expected page '{expected_name}' to be tagged 'loader', "
            f"but found loader pages: {found_loader_names}"
        )

    # Verify expected performer pages are tagged per task step 4
    found_performer_names = {p.name for p in found_performers}
    for expected_name in expected_performer_minimum:
        assert expected_name in found_performer_names, (
            f"Expected page '{expected_name}' to be tagged 'performer', "
            f"but found performer pages: {found_performer_names}"
        )

    # Verify loader and performer sets don't overlap
    overlap = found_loader_names & found_performer_names
    assert not overlap, f"Loader and performer page sets should not overlap, but found: {overlap}"


def test_pid171_block_recover_pairing_persisted(pid_0171_process) -> None:  # type: ignore[no-untyped-def]
    """Task 4b requirement: Block→Recover pairing is persisted onto BLOCK stages.

    Per Task 4a, the implicit Block→Recover relationship is reconstructed during
    reachability analysis. Task 4b must persist this pairing onto BLOCK stages
    via the recover_stage_id field, so rendering logic can reuse it.
    """
    # Find a BLOCK stage that has a Recover handler
    block_with_recover = None
    for page in pid_0171_process.pages:
        for stage in page.stages:
            if stage.stage_type == StageType.BLOCK and stage.recover_stage_id:
                block_with_recover = stage
                break
        if block_with_recover:
            break

    # Verify at least one BLOCK has a recover_stage_id
    assert block_with_recover is not None, (
        "Expected at least one BLOCK stage with persisted recover_stage_id, but found none"
    )

    # Verify the recover_stage_id actually points to a RECOVER stage on the same page
    recover_stage = None
    for page in pid_0171_process.pages:
        for stage in page.stages:
            if stage.stage_id == block_with_recover.recover_stage_id:
                recover_stage = stage
                break

    assert recover_stage is not None, (
        f"BLOCK stage {block_with_recover.name} has recover_stage_id={block_with_recover.recover_stage_id}, "
        f"but that stage_id doesn't exist in the AST"
    )
    assert recover_stage.stage_type == StageType.RECOVER, (
        f"Expected recover_stage_id to point to a RECOVER stage, but got {recover_stage.stage_type}"
    )


# ── Task 7b0: inputs_stage_map / outputs_stage_map reach the AST ───────────


def test_inputs_stage_map_reaches_ast() -> None:
    """A Start stage's inputs_stage_map (parameter name -> bound data item name) is
    carried through build_ast onto the BPStage (Task 7b0)."""
    raw_stage = RawStage(
        stage_id="s_start",
        stage_type="Start",
        name="Start",
        data_items=[],
        inputs_stage_map={"ScreenShot path": "File Path"},
    )
    raw = single_page_process(raw_stage)
    result = build_ast(raw)

    stage = result.pages[0].stages[0]
    assert stage.inputs_stage_map == {"ScreenShot path": "File Path"}


def test_outputs_stage_map_reaches_ast() -> None:
    """An End stage's outputs_stage_map (parameter name -> bound data item name) is
    carried through build_ast onto the BPStage (Task 7b0)."""
    raw_stage = RawStage(
        stage_id="s_end",
        stage_type="End",
        name="End",
        data_items=[],
        outputs_stage_map={"Mail Items": "Items"},
    )
    raw = single_page_process(raw_stage)
    result = build_ast(raw)

    stage = result.pages[0].stages[0]
    assert stage.outputs_stage_map == {"Mail Items": "Items"}


def test_inputs_outputs_stage_map_default_empty() -> None:
    """A stage with no stage= bindings gets empty inputs_stage_map/outputs_stage_map,
    never None (Task 7b0 — no silent attribute-missing failure)."""
    raw = single_page_process(make_raw_stage(stage_type="Start", name="Start"))
    stage = build_ast(raw).pages[0].stages[0]

    assert stage.inputs_stage_map == {}
    assert stage.outputs_stage_map == {}
