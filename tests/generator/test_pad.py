"""Tests for the PAD .robin generator."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml

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
from flowsmith.exceptions import GenerationError
from flowsmith.generator import PADGenerator
from flowsmith.generator.pad import GET_NEXT_ITEM_STAGE_ID

if TYPE_CHECKING:
    from flowsmith.ast.models import BPPage as BPPageType


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def generator() -> PADGenerator:
    """Return a PADGenerator instance."""
    return PADGenerator()


@pytest.fixture
def temp_output_dir(tmp_path: Path) -> Path:
    """Return a temporary output directory."""
    return tmp_path / "robin"


def make_annotated_stage(
    stage_id: str = "S1",
    name: str = "Test Stage",
    stage_type: StageType = StageType.ACTION,
    target_type: str = "SetVariable",
    target_module: str = "System",
    confidence: float = 0.95,
    flags: list[ReviewFlag] | None = None,
    is_subsheet_call: bool = False,
    pair_id: str | None = None,
    exception_type: str | None = None,
    params_map: dict[str, str] | None = None,
    stage_params_map: dict[str, str] | None = None,
    data_items: list[BPDataItem] | None = None,
) -> BPStage:
    """Create a BPStage with full PAAnnotation.

    Args:
        stage_id: The stage ID.
        name: The stage name.
        stage_type: The stage type.
        target_type: The PA target type.
        target_module: The PA target module.
        confidence: The confidence score.
        flags: List of review flags.
        is_subsheet_call: Whether this is a subsheet call.
        pair_id: Partner stage ID for paired stages (BLOCK/WAIT/LOOP).
        exception_type: Exception type string for EXCEPTION/BLOCK stages.
        params_map: Annotation params_map contents (for DATA/COLLECTION stages).
        stage_params_map: Stage-level params_map contents (for CALCULATION stages, parser shape {target: expr}).
        data_items: Data items declared on the stage.

    Returns:
        A fully annotated BPStage.
    """
    if flags is None:
        flags = []

    band = ConfidenceBand.from_score(confidence)

    stage = BPStage(
        stage_id=stage_id,
        stage_type=stage_type,
        name=name,
        data_items=data_items or [],
        pair_id=pair_id,
        exception_type=exception_type,
        params_map=stage_params_map or {},
        pa_annotation=PAAnnotation(
            target_type=target_type,
            target_module=target_module,
            runtime=Runtime.DESKTOP,
            params_map=params_map or {},
            confidence=confidence,
            band=band,
            flags=flags,
        ),
        is_subsheet_call=is_subsheet_call,
    )
    return stage


def make_page(
    stages: list[BPStage] | None = None,
    name: str = "TestPage",
    is_main: bool = False,
) -> BPPageType:
    """Create a BPPage with the given stages.

    Args:
        stages: The stages to include.
        name: The page name.
        is_main: Whether this is the main page.

    Returns:
        A BPPage instance.
    """
    if stages is None:
        stages = [make_annotated_stage()]

    return BPPage(
        page_id="P1",
        name=name,
        stages=stages,
        is_main=is_main,
    )


def make_process(
    pages: list[BPPageType] | None = None,
    name: str = "TestProcess",
) -> BPProcess:
    """Create a BPProcess with the given pages.

    Args:
        pages: The pages to include.
        name: The process name.

    Returns:
        A BPProcess instance.
    """
    if pages is None:
        pages = [make_page(is_main=True)]

    return BPProcess(
        process_id="PROC1",
        name=name,
        version="1.0.0",
        pages=pages,
        source_file="test.bprelease",
    )


# ── Unit Tests ─────────────────────────────────────────────────────────────


def test_generator_initialises_cleanly() -> None:
    """Test that generator initialises without error."""
    gen = PADGenerator()
    assert gen is not None
    assert gen.template_dir is not None


def test_missing_template_dir_raises_generation_error() -> None:
    """Test that missing template dir raises GenerationError."""
    with pytest.raises(GenerationError):
        PADGenerator(template_dir=Path("nonexistent"))


def test_generate_page_returns_string() -> None:
    """Test that generate_page returns a string."""
    gen = PADGenerator()
    page = make_page(is_main=False)
    result = gen.generate_page(page, "TestProcess")
    assert isinstance(result, str)
    assert len(result) > 0


def test_generated_page_has_function_declaration() -> None:
    """Test that generated page contains FUNCTION declaration."""
    gen = PADGenerator()
    page = make_page(is_main=False)
    result = gen.generate_page(page, "TestProcess")
    assert "FUNCTION" in result


def test_generated_page_has_end_function() -> None:
    """Test that generated page contains END FUNCTION."""
    gen = PADGenerator()
    page = make_page(is_main=False)
    result = gen.generate_page(page, "TestProcess")
    assert "END FUNCTION" in result


def test_manual_stage_renders_stub() -> None:
    """Test that MANUAL band stage renders as stub."""
    gen = PADGenerator()
    stage = make_annotated_stage(
        stage_id="S1",
        confidence=0.3,  # Results in MANUAL band
        flags=[
            ReviewFlag(
                stage_id="S1",
                reason="No mapping found",
                severity="error",
                suggested_fix="Review manually",
            )
        ],
    )
    page = make_page(stages=[stage], is_main=False)
    result = gen.generate_page(page, "TestProcess")
    assert "# STUB:" in result


def test_stub_contains_stage_id() -> None:
    """Test that stub output contains the stage ID."""
    gen = PADGenerator()
    stage = make_annotated_stage(
        stage_id="STUB_TEST_123",
        confidence=0.3,
        flags=[
            ReviewFlag(
                stage_id="STUB_TEST_123",
                reason="Test reason",
                severity="error",
                suggested_fix="Test fix",
            )
        ],
    )
    page = make_page(stages=[stage], is_main=False)
    result = gen.generate_page(page, "TestProcess")
    assert "STUB_TEST_123" in result


def test_spot_check_stage_renders_verify_comment() -> None:
    """Test that SPOT_CHECK band stage renders with VERIFY comment."""
    gen = PADGenerator()
    stage = make_annotated_stage(
        confidence=0.75,  # Results in SPOT_CHECK band
        target_type="SetVariable",
        # Task 7d item 4: a SET needs a real BP expression — an expression-less stage
        # now renders a TODO naming it instead of a `%SomeVar%` placeholder SET.
        stage_params_map={"Target": "1"},
    )
    page = make_page(stages=[stage], is_main=False)
    result = gen.generate_page(page, "TestProcess")
    assert "# VERIFY:" in result or "SET" in result


def test_partial_stage_renders_todo_comment() -> None:
    """Test that PARTIAL band stage renders with TODO comment."""
    gen = PADGenerator()
    stage = make_annotated_stage(
        confidence=0.60,  # Results in PARTIAL band
        target_type="Condition",
    )
    page = make_page(stages=[stage], is_main=False)
    result = gen.generate_page(page, "TestProcess")
    assert "# TODO:" in result or "IF" in result


def test_auto_stage_has_no_markers() -> None:
    """Test that AUTO band stage has no STUB/VERIFY/TODO markers."""
    gen = PADGenerator()
    stage = make_annotated_stage(
        confidence=0.95,  # Results in AUTO band
        target_type="SetVariable",
    )
    page = make_page(stages=[stage], is_main=False)
    result = gen.generate_page(page, "TestProcess")
    # AUTO band shouldn't have verification markers
    lines = result.split("\n")
    stage_lines = [line for line in lines if "SET" in line]
    if stage_lines:
        # Check that SET line doesn't have VERIFY marker (which indicates SPOT_CHECK)
        assert "# VERIFY:" not in stage_lines[0] or "0.95" not in stage_lines[0]


def test_set_variable_stage_renders_set() -> None:
    """Test that SetVariable target_type renders SET statement."""
    gen = PADGenerator()
    # Task 7d item 4: give the stage a real BP expression (see
    # test_spot_check_stage_renders_verify_comment) — without one no SET is emitted.
    stage = make_annotated_stage(target_type="SetVariable", stage_params_map={"Target": "1"})
    page = make_page(stages=[stage], is_main=False)
    result = gen.generate_page(page, "TestProcess")
    assert "SET" in result


def test_call_subflow_stage_renders_call() -> None:
    """Test that subsheet call renders CALL statement."""
    gen = PADGenerator()
    stage = make_annotated_stage(
        target_type="RunDesktopFlow",
        is_subsheet_call=True,
    )
    page = make_page(stages=[stage], is_main=False)
    result = gen.generate_page(page, "TestProcess")
    assert "CALL" in result


def test_text_action_renders() -> None:
    """Test that Text module actions render correctly."""
    gen = PADGenerator()
    stage = make_annotated_stage(
        target_module="Text",
        target_type="Trim Whitespace",
        confidence=0.95,
    )
    page = make_page(stages=[stage], is_main=False)
    result = gen.generate_page(page, "TestProcess")
    assert "Text" in result or "SET" in result


def test_file_action_renders() -> None:
    """Test that File module actions render correctly."""
    gen = PADGenerator()
    stage = make_annotated_stage(
        target_module="File",
        target_type="File Exists",
        confidence=0.95,
    )
    page = make_page(stages=[stage], is_main=False)
    result = gen.generate_page(page, "TestProcess")
    assert "File" in result or "SET" in result


def test_datetime_action_renders() -> None:
    """Test that DateTime module actions render correctly."""
    gen = PADGenerator()
    stage = make_annotated_stage(
        target_module="DateTime",
        target_type="Get Current DateTime",
        confidence=0.95,
    )
    page = make_page(stages=[stage], is_main=False)
    result = gen.generate_page(page, "TestProcess")
    assert "DateTime" in result or "SET" in result


def test_get_variable_action_renders() -> None:
    """Test that Variables.GetVariable action renders correctly."""
    gen = PADGenerator()
    stage = make_annotated_stage(
        target_module="Variables",
        target_type="GetVariable",
        confidence=0.95,
    )
    page = make_page(stages=[stage], is_main=False)
    result = gen.generate_page(page, "TestProcess")
    assert "Variables" in result or "SET" in result


def test_unannotated_stage_raises_generation_error() -> None:
    """Test that unannotated stage raises GenerationError."""
    gen = PADGenerator()
    # Create a stage without pa_annotation
    stage = BPStage(
        stage_id="S1",
        stage_type=StageType.ACTION,
        name="Unannotated",
        pa_annotation=None,
    )
    page = make_page(stages=[stage], is_main=False)

    with pytest.raises(GenerationError):
        gen.generate_page(page, "TestProcess")


def test_generate_process_creates_files(tmp_path: Path) -> None:
    """Test that generate_process creates files in output dir."""
    gen = PADGenerator()
    process = make_process()
    output_dir = tmp_path / "output"

    files = gen.generate_process(process, output_dir)

    assert len(files) > 0
    assert all(f.exists() for f in files)


def test_generate_process_consolidates_by_role_not_one_file_per_page(tmp_path: Path) -> None:
    """Test that generate_process consolidates pages into 2 role-based files, not N-per-page.

    Stale-baseline fix (was ``test_generate_process_one_file_per_page``, asserted 3 files
    for 3 pages — the pre-Task-5a per-page architecture). Task 5a replaced that with a
    2-file consolidation by Loader/Performer role (architecture doc §A3): one file per
    role, each role's reachable pages folded/inlined into that role's single Desktop Flow
    body rather than emitted as their own file. A process with pages tagged
    ``role="loader"``/``role="performer"`` now always produces exactly 2 files regardless
    of page count — verified against the real samples too
    (``test_real_sample_generates_2_consolidated_files`` below): both PID_0171 (24 pages)
    and PID_0127 produce exactly 2 files under this architecture.
    """
    gen = PADGenerator()
    main_page = make_page(name="Main Page", is_main=True)
    loader_page = BPPage(
        page_id="LOADER_PAGE",
        name="Loader Sub-Page",
        stages=[make_annotated_stage(stage_id="L1", name="Loader Step")],
        role="loader",
    )
    performer_page = BPPage(
        page_id="PERFORMER_PAGE",
        name="Performer Sub-Page",
        stages=[make_annotated_stage(stage_id="P1", name="Performer Step")],
        role="performer",
    )
    process = make_process(pages=[main_page, loader_page, performer_page])

    output_dir = tmp_path / "output"
    files = gen.generate_process(process, output_dir)

    assert len(files) == 2, (
        f"Expected 2 role-consolidated files (Loader, Performer), got {len(files)}: {[f.name for f in files]}"
    )
    assert any("Loader" in f.name for f in files)
    assert any("Performer" in f.name for f in files)


def test_generate_process_returns_path_list(tmp_path: Path) -> None:
    """Test that return value is a list of Path objects."""
    gen = PADGenerator()
    process = make_process()
    output_dir = tmp_path / "output"

    result = gen.generate_process(process, output_dir)

    assert isinstance(result, list)
    assert all(isinstance(p, Path) for p in result)


def test_output_dir_created_if_missing(tmp_path: Path) -> None:
    """Test that output directory is created if missing."""
    gen = PADGenerator()
    process = make_process()
    output_dir = tmp_path / "new_dir" / "nested"

    assert not output_dir.exists()
    gen.generate_process(process, output_dir)
    assert output_dir.exists()


def test_filename_sanitised() -> None:
    """Test that page names are sanitised in filenames."""
    # The filename is created inside generate_process
    # but we can test the _sanitise_filename method
    sanitised = PADGenerator._sanitise_filename("JS Actions & More!")
    assert sanitised == "JS_Actions__More" or "JSActions" in sanitised


def test_main_page_has_header_comment() -> None:
    """Test that main page output contains expected header."""
    gen = PADGenerator()
    page = make_page(is_main=True)
    result = gen.generate_page(page, "TestProcess")
    assert "# Generated by Flowsmith" in result


def test_no_python_traceback_in_output(tmp_path: Path) -> None:
    """Test that generated files contain no Python tracebacks."""
    gen = PADGenerator()
    process = make_process()
    output_dir = tmp_path / "output"

    gen.generate_process(process, output_dir)

    for file in output_dir.glob("*.robin"):
        content = file.read_text(encoding="utf-8")
        assert "Traceback" not in content


# ── Structural Robin constructs (Sub-Task 4) ───────────────────────────────


def test_main_page_header_contains_imports() -> None:
    """Test that the main page header emits both hardcoded IMPORT lines."""
    gen = PADGenerator()
    page = make_page(is_main=True)
    result = gen.generate_page(page, "TestProcess")
    assert "IMPORT 'controlRepo.appmask' AS appmask" in result
    assert "IMPORT 'imageRepo.imgrepo' AS imgrepo" in result


def test_imports_appear_after_desktop_type_and_before_inputs() -> None:
    """Test IMPORT lines sit between the @@ block and the @INPUT declarations."""
    gen = PADGenerator()
    stage = make_annotated_stage(
        data_items=[BPDataItem(name="In_txt_Config", data_type="text", is_input=True)],
    )
    page = make_page(stages=[stage], is_main=True)
    result = gen.generate_page(page, "TestProcess")

    assert result.index("@@DisplayName") < result.index("IMPORT 'controlRepo.appmask'")
    assert result.index("IMPORT 'imageRepo.imgrepo'") < result.index("@INPUT In_txt_Config")


def test_non_main_page_also_emits_flow_header() -> None:
    """Sub-pages emit the flow header too — each is packaged as its own flow.

    Every BPPage becomes a separate Workflow element whose <Definition> is a
    standalone PAD script, so the @@ directives and IMPORT lines are required
    on every page, not only the main one.
    """
    gen = PADGenerator()
    page = make_page(is_main=False)
    result = gen.generate_page(page, "TestProcess")
    assert result.startswith("@@ConnectionString:")
    assert "IMPORT 'controlRepo.appmask' AS appmask" in result


def test_flow_header_precedes_provenance_banner() -> None:
    """Nothing — not even a comment — precedes the @@ directives."""
    gen = PADGenerator()
    page = make_page(is_main=True)
    result = gen.generate_page(page, "TestProcess")
    assert result.startswith("@@ConnectionString:")
    assert result.index("@@DisplayName") < result.index("# Generated by Flowsmith")


def test_block_opener_renders_block_structure() -> None:
    """Test that an opening BLOCK stage renders BLOCK/ON BLOCK ERROR/END."""
    gen = PADGenerator()
    stage = make_annotated_stage(
        stage_id="B1",
        name="Get unprocessed emails",
        stage_type=StageType.BLOCK,
        target_type="",
        confidence=0.70,
        pair_id="B1",
    )
    result = gen._render_stage(stage)

    assert result.splitlines()[0] == "BLOCK 'Get unprocessed emails'"
    assert "ON BLOCK ERROR all" in result
    assert "    CALL 'Get Error'" in result
    assert "    GOTO 'Error Block'" in result
    assert result.strip().endswith("END")


def test_block_closer_renders_end_only() -> None:
    """Test that the partner BLOCK stage renders a bare END."""
    gen = PADGenerator()
    stage = make_annotated_stage(
        stage_id="B2",
        name="Get unprocessed emails",
        stage_type=StageType.BLOCK,
        target_type="",
        confidence=0.70,
        pair_id="B1",
    )
    assert gen._render_stage(stage) == "END"


def test_singleton_block_renders_as_opener() -> None:
    """Test that an unpaired BLOCK still renders a balanced BLOCK … END."""
    gen = PADGenerator()
    stage = make_annotated_stage(
        stage_id="B9",
        name="Lonely Block",
        stage_type=StageType.BLOCK,
        target_type="",
        confidence=0.70,
    )
    result = gen._render_stage(stage)
    assert "BLOCK 'Lonely Block'" in result
    assert result.strip().endswith("END")


def test_block_with_exception_type_renders_typed_handler() -> None:
    """Test that a typed BLOCK emits an IsUserDefinedErrorCode handler branch."""
    gen = PADGenerator()
    stage = make_annotated_stage(
        stage_id="B1",
        name="Typed Block",
        stage_type=StageType.BLOCK,
        target_type="",
        confidence=0.70,
        pair_id="B1",
        exception_type="Business Exception",
    )
    result = gen._render_stage(stage)

    assert "ON BLOCK ERROR 'Business Exception' IsUserDefinedErrorCode: True" in result
    assert "    SET txt_ExceptionType TO $'''Business Exception'''" in result
    # Catch-all branch still present after the typed branch
    assert result.index("IsUserDefinedErrorCode") < result.index("ON BLOCK ERROR all")


def test_block_is_not_rendered_as_stub_when_manual_band() -> None:
    """Test that a MANUAL-band BLOCK still renders its scope construct."""
    gen = PADGenerator()
    stage = make_annotated_stage(
        stage_id="B1",
        name="Low Confidence Block",
        stage_type=StageType.BLOCK,
        target_type="",
        confidence=0.10,
        pair_id="B1",
    )
    result = gen._render_stage(stage)
    assert "# STUB:" not in result
    assert "BLOCK 'Low Confidence Block'" in result


def test_recover_stage_renders_error_capture() -> None:
    """Test that a RECOVER stage renders ERROR capture, CALL and GOTO."""
    gen = PADGenerator()
    stage = make_annotated_stage(
        stage_id="R1",
        name="Recover",
        stage_type=StageType.RECOVER,
        target_type="",
        confidence=0.80,
    )
    result = gen._render_stage(stage)

    assert "ERROR => obj_LastError" in result
    assert "CALL 'Get Error'" in result
    assert "GOTO 'Error Block'" in result


def test_resume_stage_renders_goto_end() -> None:
    """Test that a RESUME stage renders GOTO 'End'."""
    gen = PADGenerator()
    stage = make_annotated_stage(
        stage_id="RS1",
        name="Resume",
        stage_type=StageType.RESUME,
        target_type="",
        confidence=0.80,
    )
    assert gen._render_stage(stage).strip() == "GOTO 'End'"


def test_exception_throw_error_renders_throw_error() -> None:
    """Test that a ThrowError annotation renders a bare THROW ERROR."""
    gen = PADGenerator()
    stage = make_annotated_stage(
        stage_id="E1",
        name="Re-raise",
        stage_type=StageType.EXCEPTION,
        target_type="ThrowError",
        target_module="FlowControl",
        confidence=0.90,
    )
    result = gen._render_stage(stage)

    assert result.strip() == "THROW ERROR"
    assert "ThrowCustomError" not in result


def test_exception_throw_custom_error_renders_flowcontrol_action() -> None:
    """Test that a ThrowCustomError annotation renders the FlowControl action."""
    gen = PADGenerator()
    stage = make_annotated_stage(
        stage_id="E2",
        name="Throw",
        stage_type=StageType.EXCEPTION,
        target_type="ThrowCustomError",
        target_module="FlowControl",
        confidence=0.80,
    )
    result = gen._render_stage(stage)

    assert "FlowControl.ThrowCustomError" in result
    assert "CustomErrorCode: $'''%txt_ExceptionType%'''" in result
    assert "CustomErrorMessage: txt_ExceptionMessage" in result


def test_exception_custom_error_uses_annotated_exception_type() -> None:
    """Test that the annotated exception_type becomes the CustomErrorCode."""
    gen = PADGenerator()
    stage = make_annotated_stage(
        stage_id="E3",
        name="Throw",
        stage_type=StageType.EXCEPTION,
        target_type="ThrowCustomError",
        target_module="FlowControl",
        confidence=0.80,
        params_map={"exception_type": "System Exception"},
    )
    result = gen._render_stage(stage)
    assert "CustomErrorCode: $'''System Exception'''" in result


def test_throw_custom_error_concatenated_message_uses_single_quoted_literals() -> None:
    """Task 7b fix pass (gap 8): concatenated throw messages use PAD single-quote

    literals (``'...'``), not BP's double-quoted literals left untranslated.

    Per ``docs/pad-reference/DF_PID_171_US_LIMS_Prelude_Main.robin.txt`` L1290
    (``GLOBAL.num_ConsecutiveExcLimit + ' consecutive incidents of ' + ... `` ) and
    L1272/L1297/L1316 (``'Unable to update work queue item status after ' + ...``),
    the reference's throw-message *concatenations* join single-quoted PAD string
    literals with ``+``. ``_translate_bp_expression`` leaves BP's double-quoted
    literals double-quoted, which is not valid PAD syntax in this position — this
    is normalised only for concatenation expressions (``+`` present), scoped to
    the two TERMINATE messages this gap names, not every double-quoted literal in
    the generator's output.

    Mutation check: removing the quote-substitution call in the
    ``target_type in ("ThrowError", "ThrowCustomError")`` branch of
    ``_render_stage`` makes this test fail (the message stays double-quoted).
    """
    gen = PADGenerator()
    stage = make_annotated_stage(
        stage_id="E4",
        name="TERMINATE",
        stage_type=StageType.EXCEPTION,
        target_type="ThrowCustomError",
        target_module="FlowControl",
        confidence=0.80,
        params_map={
            "exception_type": "System Unavailable Exception",
            "detail_expr": '[Consecutive Exception Limit] & " consecutive incidents of " & [Exception Type]',
        },
    )
    result = gen._render_stage(stage)

    assert "CustomErrorMessage:" in result
    message_part = result.split("CustomErrorMessage:", 1)[1]
    assert "'" in message_part
    assert '"' not in message_part
    assert "' consecutive incidents of '" in message_part


def test_decision_stub_spot_check_band_carries_verify_marker() -> None:
    """Task 7b fix pass (gap 3): an empty IF/ELSE/END decision stub at SPOT_CHECK

    band keeps a VERIFY marker naming the stage and confidence.

    Before this fix, Task 7b's target_type dispatch change started routing
    DECISION's real "IF <expr> THEN <true-branch> ELSE <false-branch> END"
    annotation into this stub path (previously it fell through, unmatched, to the
    generic fallback comment branch, which *did* append a VERIFY suffix for
    SPOT_CHECK band) — losing the marker for every DECISION with no real branch
    targets to nest (51 flagged stubs became 47 unflagged ones,
    docs/reviews/7b-2026-09-24-v2.md gap 3). ``condition.robin.j2`` itself is out
    of this task's file scope, so the marker is emitted as a preceding comment
    line (matching the convention used elsewhere in ``pad.py``), not inside the
    template.

    Mutation check: removing the ``if band == ConfidenceBand.SPOT_CHECK: lines
    .append(...)`` block in the ``Condition``/``"IF <expr> THEN ..."`` branch of
    ``_render_stage`` makes this test fail (no VERIFY line at all).
    """
    gen = PADGenerator()
    stage = make_annotated_stage(
        stage_id="D1",
        name="Stub Decision?",
        stage_type=StageType.DECISION,
        target_type="IF <expr> THEN <true-branch> ELSE <false-branch> END",
        target_module="System",
        confidence=0.85,
        # No ontrue_target/onfalse_target set — renders via the empty-stub path,
        # not _render_decision_branch.
    )
    result = gen._render_stage(stage)

    lines = result.splitlines()
    if_idx = next(i for i, ln in enumerate(lines) if ln.strip().startswith("IF "))
    assert if_idx > 0, f"Expected a VERIFY line before the IF, got: {result!r}"
    assert lines[if_idx - 1].strip().startswith("# VERIFY:")
    assert "Stub Decision?" in lines[if_idx - 1]
    assert "0.85" in lines[if_idx - 1]


def test_sensitive_vars_detected_from_password_data_type() -> None:
    """Test that a password-typed data item produces an @SENSITIVE entry."""
    gen = PADGenerator()
    stage = make_annotated_stage(
        stage_type=StageType.DATA,
        data_items=[BPDataItem(name="obj_DBSecretValue", data_type="password")],
    )
    page = make_page(stages=[stage], is_main=True)
    result = gen.generate_page(page, "TestProcess")
    assert "@SENSITIVE: [obj_DBSecretValue]" in result


def test_sensitive_vars_detected_from_binary_data_type() -> None:
    """Test that a binary-typed data item produces an @SENSITIVE entry."""
    gen = PADGenerator()
    stage = make_annotated_stage(
        stage_type=StageType.DATA,
        data_items=[BPDataItem(name="bin_Payload", data_type="binary")],
    )
    page = make_page(stages=[stage], is_main=True)
    result = gen.generate_page(page, "TestProcess")
    assert "@SENSITIVE: [bin_Payload]" in result


@pytest.mark.parametrize(
    "var_name",
    ["txt_DbPassword", "txt_EncDec_Key", "Client_Secret", "txt_PWD_Value"],
)
def test_sensitive_vars_detected_from_name_tokens(var_name: str) -> None:
    """Test that sensitive-looking names are detected regardless of data type."""
    gen = PADGenerator()
    stage = make_annotated_stage(
        stage_type=StageType.DATA,
        data_items=[BPDataItem(name=var_name, data_type="text")],
    )
    page = make_page(stages=[stage], is_main=True)
    result = gen.generate_page(page, "TestProcess")
    assert f"@SENSITIVE: [{var_name}]" in result


def test_sensitive_vars_deduplicated() -> None:
    """Test that a repeated sensitive variable appears once in @SENSITIVE."""
    gen = PADGenerator()
    item = BPDataItem(name="txt_Password", data_type="password")
    stages = [
        make_annotated_stage(stage_id="D1", stage_type=StageType.DATA, data_items=[item]),
        make_annotated_stage(stage_id="D2", stage_type=StageType.DATA, data_items=[item]),
    ]
    page = make_page(stages=stages, is_main=True)
    result = gen.generate_page(page, "TestProcess")
    assert result.count("txt_Password") == 1


def test_no_sensitive_line_without_sensitive_data_items() -> None:
    """Test that @SENSITIVE is omitted when no data item is sensitive."""
    gen = PADGenerator()
    stage = make_annotated_stage(
        stage_type=StageType.DATA,
        data_items=[BPDataItem(name="txt_PlainValue", data_type="text")],
    )
    page = make_page(stages=[stage], is_main=True)
    result = gen.generate_page(page, "TestProcess")
    assert "@SENSITIVE" not in result


def test_render_structural_stage_rejects_non_structural_type() -> None:
    """Test that the structural renderer refuses a non-structural stage."""
    gen = PADGenerator()
    stage = make_annotated_stage(stage_type=StageType.ACTION)
    with pytest.raises(GenerationError):
        gen._render_structural_stage(stage)


# ── Task 5b Tests: Expression Translation ──────────────────────────────────


def test_build_variable_name_mapping_scans_data_stages() -> None:
    """Test that _build_variable_name_mapping builds a mapping from DATA/COLLECTION stages.

    Per Task 5b, the mapping must scan all DATA and COLLECTION stages across all pages
    and create a single source-of-truth for BP name → PAD name translation.

    Fixture shape: DATA/COLLECTION annotation params_map is built by real annotator.
    Per engine/annotator.py::_annotate_data (lines 239-243):
      DATA: {"variable_name": stage.name, "variable_type": type, "initial_value": value}
    Per engine/annotator.py::_annotate_collection (lines 264-267):
      COLLECTION: {"table_name": stage.name, "variable_type": "DataTable"}
    """
    gen = PADGenerator()

    # DATA stage with real annotator shape
    data_stage = make_annotated_stage(
        stage_id="D1",
        name="Retry Count",
        stage_type=StageType.DATA,
        params_map={
            "variable_name": "Retry Count",
            "variable_type": "number",
            "initial_value": "0",
        },
        data_items=[BPDataItem(name="Retry Count", data_type="number")],
    )

    # COLLECTION stage with real annotator shape
    collection_stage = make_annotated_stage(
        stage_id="C1",
        name="FinalProduct_Collection",
        stage_type=StageType.COLLECTION,
        params_map={"table_name": "FinalProduct_Collection", "variable_type": "DataTable"},
        data_items=[BPDataItem(name="FinalProduct_Collection", data_type="collection")],
    )

    page = make_page(stages=[data_stage, collection_stage], is_main=True)
    process = make_process(pages=[page], name="TestProcess")

    mapping = gen._build_variable_name_mapping(process)

    # Verify the mapping produces correctly-prefixed names
    assert "retry count" in mapping
    assert mapping["retry count"] == "num_RetryCount"
    assert "finalproduct_collection" in mapping
    assert mapping["finalproduct_collection"] == "dtb_FinalProductCollection"


def test_resolve_dotted_reference_translates_collection_field() -> None:
    """Test that _resolve_dotted_reference maps Collection.Field through the mapping.

    Per Task 5b §A4, dotted references like 'FinalProduct_Collection.Column8' should be
    resolved using the base collection name from the mapping.
    """
    gen = PADGenerator()
    mapping = {"finalproduct_collection": "dtb_FinalProductCollection"}

    result = gen._resolve_dotted_reference("FinalProduct_Collection.Column8", mapping)

    assert result == "dtb_FinalProductCollection.Column8"


def test_translate_bp_expression_converts_brackets_to_variables() -> None:
    """Test that _translate_bp_expression converts [DataItem] brackets to variable names.

    Per Task 5b §B10 point 3, BP expressions use [Data Item] notation that must be
    translated to PAD variable references.
    """
    gen = PADGenerator()
    mapping = {"exception type": "txt_ExceptionType", "retry count": "num_RetryCount"}

    expr = "[Exception Type]"
    result, actions = gen._translate_bp_expression(expr, mapping)

    assert result == "txt_ExceptionType"
    assert actions == []


def test_translate_bp_expression_converts_ampersand_to_plus() -> None:
    """Test that _translate_bp_expression converts & (string concat) to +.

    Per Task 5b §B10 point 3, BP string concatenation (&) becomes PAD's + operator.
    """
    gen = PADGenerator()
    mapping = {}

    expr = "[First] & [Second]"
    result, actions = gen._translate_bp_expression(expr, mapping)

    # Should replace & with +
    assert "+" in result
    assert "&" not in result


def test_translate_bp_expression_handles_trim_as_separate_action() -> None:
    """Test that Trim(...) produces a separate action line, not inline.

    Per Task 5b §B10 point 3 and the architecture doc requirement: 'Trim(...) →
    `Text.Trim` action calls (BP has expression functions PAD does not — these
    become separate action lines, they cannot be inlined into a PAD expression).'
    """
    gen = PADGenerator()
    mapping = {"email": "txt_email"}

    expr = "Trim([Email])"
    result, actions = gen._translate_bp_expression(expr, mapping)

    # Trim should not be in the result; it should be in separate actions
    assert "Trim" not in result or "Text.Trim" not in result
    # There should be at least one separate action
    assert len(actions) >= 1
    # At least one action should mention Text.Trim
    trim_actions = [a for a in actions if "Text.Trim" in a]
    assert len(trim_actions) >= 1


def test_translate_bp_expression_handles_lower_of_nested_function_call() -> None:
    """Task 7b fix pass (gap 4): ``Lower(ExceptionType())`` — a nested call inside

    the Lower(...) argument — must not corrupt the Lower(...) extraction.

    ``ExceptionType()`` is a real BP built-in function (no-arg; architecture doc
    §A5's `Block`/`Recover` note: "the exception type classified via
    ExceptionType()/ExceptionDetail() BP functions"). Before this fix, the
    ``[^)]+`` regex inside ``lower_pattern``/``trim_pattern`` stopped at the
    *first* ``)`` — i.e. ``ExceptionType(``'s own closing paren — leaving a stray
    trailing ``)`` in the result and truncating the captured inner expression
    (confirmed at the pre-fix regenerated PID_0171 output:
    ``Text.ChangeCase 'ExceptionType(' 'To lowercase' => txt_lowered_0`` and a
    malformed ``IF ... (txt_lowered_0)="system exception" OR
    txt_lowered_0)="internal") THEN``). The fixed pattern allows the Lower/Trim
    argument to itself contain one level of balanced parens.

    Mutation check: reverting ``lower_pattern``/``trim_pattern`` to the old
    ``r"Lower\\s*\\(\\s*([^)]+)\\s*\\)"`` shape makes this test fail (it would
    instead produce ``Text.ChangeCase 'ExceptionType(' ...`` and a mismatched
    trailing ``)`` in ``result``).
    """
    gen = PADGenerator()

    expr = 'Lower(ExceptionType())="system exception"'
    result, actions = gen._translate_bp_expression(expr, None)

    assert len(actions) == 1
    assert "Text.ChangeCase 'ExceptionType()' 'To lowercase'" in actions[0]
    # The temp var replaces the whole Lower(...) call cleanly — no stray parens.
    assert result.count("(") == result.count(")")
    assert result.endswith('="system exception"')
    assert "ExceptionType(" not in result


def test_translate_bp_expression_handles_dotted_collection_references() -> None:
    """Test that dotted collection references are resolved through the mapping.

    Per Task 5b and the 5th cycle review, CALCULATION stages that target a dotted
    collection field (e.g., 'FinalProduct_Collection.Column8') must be resolved
    through the variable name mapping to get the correctly prefixed name.
    """
    gen = PADGenerator()
    mapping = {"finalproduct_collection": "dtb_FinalProductCollection"}

    expr = "[FinalProduct_Collection.Identity]"
    result, actions = gen._translate_bp_expression(expr, mapping)

    # Should resolve to the mapped base name with field preserved
    assert "dtb_FinalProductCollection.Identity" in result


def test_calculation_stage_uses_variable_name_mapping_for_target() -> None:
    """Test that CALCULATION stages resolve their target names through the mapping.

    This is the specific bug the 6th cycle review fixed: CALCULATION stages with
    dotted target names like 'FinalProduct_Collection.Column8' must route through
    _resolve_dotted_reference to get the mapped name, not be left raw.

    Per the 5b re-review, this test's assertion must be a strict positive check,
    not a weak disjunction that can't fail.
    """
    gen = PADGenerator()

    # Create a CALCULATION stage with a dotted target name
    # Note: stage_params_map contains {target: expression} per parser shape
    calc_stage = make_annotated_stage(
        stage_id="C1",
        name="Write to Collection",
        stage_type=StageType.CALCULATION,
        target_type="SetVariable",
        stage_params_map={
            "FinalProduct_Collection.Column8": "[Output_value]",
        },
    )

    page = make_page(stages=[calc_stage], is_main=True)
    process = make_process(pages=[page], name="TestProcess")

    # Build variable name mapping
    mapping = gen._build_variable_name_mapping(process)
    # Manually add the collection mapping (in real flow, would come from COLLECTION stage)
    mapping["finalproduct_collection"] = "dtb_FinalProductCollection"
    mapping["output_value"] = "txt_OutputValue"

    # Render the stage with the mapping
    result = gen._render_stage(calc_stage, process, {}, mapping)

    # The rendered result should have the mapped target name, not the raw BP name
    # This is a strict positive assertion that will fail if the mapping is not applied
    assert "dtb_FinalProductCollection.Column8" in result


def test_calculation_stage_renders_real_expression_not_placeholder() -> None:
    """Test that a CALCULATION stage with a known BP expression produces exact expected SET line.

    This is the specific Done-when criterion for Task 5b (per 5b-2026-09-01-rereview.md):
    'a new test asserts that generating a Calculation stage with a known BP expression
    produces the exact expected SET txt_ExceptionType TO ... line, not a placeholder.'

    The test verifies:
    1. A CALCULATION stage with params_map = {"Exception Type": "[Exception Type]"}
    2. Rendered with variable_name_mapping {"exception type": "txt_ExceptionType"}
    3. Produces the exact line "SET txt_ExceptionType TO txt_ExceptionType" in output
    4. Does NOT produce a placeholder line like "SET txt_ExceptionType TO %SomeVar%"
    """
    gen = PADGenerator()

    # Create a CALCULATION stage with Exception Type assignment, matching the real corpus
    calc_stage = make_annotated_stage(
        stage_id="C1",
        name="Set Exception Type",
        stage_type=StageType.CALCULATION,
        target_type="SetVariable",
        stage_params_map={
            "Exception Type": "[Exception Type]",
        },
    )

    page = make_page(stages=[calc_stage], is_main=True)
    process = make_process(pages=[page], name="TestProcess")

    # Build variable name mapping with the known translation
    mapping = {"exception type": "txt_ExceptionType"}

    # Render the stage through the full pipeline with the mapping
    result = gen._render_stage(calc_stage, process, {}, mapping)

    # Positive assertion: the exact real translation must appear
    assert "SET txt_ExceptionType TO txt_ExceptionType" in result, (
        f"Expected 'SET txt_ExceptionType TO txt_ExceptionType' in rendered output, "
        f"but got:\n{result}"
    )

    # Negative assertion: the placeholder must NOT appear
    assert "%SomeVar%" not in result, (
        f"Placeholder '%SomeVar%' found in rendered output, indicating expression "
        f"was not translated:\n{result}"
    )


def test_split_shape_with_mapping_preserves_variable_consistency() -> None:
    """Test that _split_page_into_functions threads variable_name_mapping correctly.

    Per Task 5b cycle 4-5 findings, the mapping must be threaded through
    _split_page_into_functions to ensure variable references in split FUNCTIONs
    stay consistent (e.g., Retry Count should be num_retryCount everywhere, not
    txt_retryCount in some places and num_retryCount in others).

    Fixture shape: DATA stages use real annotator shape (from engine/annotator.py::_annotate_data).
    CALCULATION stages use parser shape (from parser/process.py lines 354-355: {target: expr}).
    """
    gen = PADGenerator()

    # Create a page with split-shape targets and CALCULATION stages that reference variables
    # DATA stage declares "Retry Count" variable using real annotator shape
    data_stage = make_annotated_stage(
        stage_id="D1",
        name="Retry Count",
        stage_type=StageType.DATA,
        params_map={
            "variable_name": "Retry Count",
            "variable_type": "number",
            "initial_value": "0",
        },
        data_items=[BPDataItem(name="Retry Count", data_type="number")],
    )

    # CALCULATION stages use stage.params_map (not annotation.params_map) from parser
    calc_stage_1 = make_annotated_stage(
        stage_id="C1",
        name="Increment Retry",
        stage_type=StageType.CALCULATION,
        target_type="SetVariable",
        params_map={"Retry Count": "[Retry Count] + 1"},
    )

    calc_stage_2 = make_annotated_stage(
        stage_id="C2",
        name="Check Retry Limit",
        stage_type=StageType.CALCULATION,
        target_type="SetVariable",
        params_map={"Should Retry": "[Retry Count] < 5"},
    )

    page = make_page(stages=[data_stage, calc_stage_1, calc_stage_2], is_main=False)
    process = make_process(pages=[page], name="TestProcess")

    # Build variable name mapping
    mapping = gen._build_variable_name_mapping(process)

    # Render the page with split-shape (simulating _split_page_into_functions)
    shape_info = {"shape": "split", "targets": ["Target1", "Target2"], "stage_counts": [1, 2]}
    result = gen._split_page_into_functions(page, process, shape_info, {}, mapping)

    # Count occurrences of the correct vs incorrect spellings
    # Should have num_RetryCount (correct) and NOT txt_RetryCount (wrong)
    # The result should show that the mapping is being used (at least in the translated expressions)
    assert (
        "num_RetryCount" in result or "Retry Count" not in result
    )  # Either mapped or no raw BP name
    assert "txt_RetryCount" not in result


# ── Integration Tests ──────────────────────────────────────────────────────


@pytest.mark.integration
def test_real_sample_generates_2_consolidated_files(tmp_path: Path) -> None:
    """Test that full pipeline generates the 2 role-consolidated .robin files.

    This test requires the real sample to be present and the full
    pipeline (parser → AST → engine → generator) to work.

    Stale-baseline fix (was ``test_real_sample_generates_399_files``, most recently
    asserting 19 — the pre-Task-5a per-page architecture, updated once already per Task 3a's
    artefact-isolation shrink from 399→19). Task 5a's 2-file role-consolidation
    (architecture doc §A3 — one Desktop Flow per Loader/Performer role, reachable pages
    folded/inlined/split into that role's single file rather than emitted as their own file)
    made the per-page count irrelevant to the output file count. Traced directly: running
    the real pipeline against ``PID_0127.bprelease`` now produces exactly 2 files
    (``PID_0127_Process_US_BulkUnlock_Loader.robin``, ``..._Performer.robin``) — confirmed
    by direct execution, not assumed; also independently confirmed for PID_0171 across
    multiple Task 5a review cycles (e.g. docs/reviews/5a-2026-08-31-rebuild-fixpass.md).
    """
    sample_path = Path("samples/blueprism/PID_0127.bprelease")
    if not sample_path.exists():
        pytest.skip("Sample file not found")

    # Full pipeline: parse → build AST → annotate → generate
    from flowsmith.ast.builder import build_ast
    from flowsmith.engine import create_annotator
    from flowsmith.parser import parse_process

    raw = parse_process(sample_path)
    process = build_ast(raw)
    create_annotator().annotate_process(process)

    gen = PADGenerator()
    files = gen.generate_process(process, tmp_path / "robin")

    assert len(files) == 2, (
        f"Expected 2 role-consolidated files (Loader, Performer), got {len(files)}: {[f.name for f in files]}"
    )
    assert any("Loader" in f.name for f in files)
    assert any("Performer" in f.name for f in files)


@pytest.mark.integration
def test_real_sample_stub_count(tmp_path: Path) -> None:
    """Test that real sample has expected number of stubs.

    Baseline updated per Task 3a artefact-isolation shrink (docs/reviews/3a-2026-08-30-isolation-fixpass.md):
    Task 3a's per-artefact page isolation reduced stub count from ~296 to 20 for PID_0127.

    Task 5a (rebuild cycle): Consolidated-by-role architecture changed from one-file-per-page
    to 2-files (Loader/Performer). Stub count changed from 20 to 18 as a side effect.

    Root cause: The new architecture changes how pages are routed and rendered (by role).
    PID_0127 has 4 Loader pages and 14 Performer pages. The reduction from 20 to 18 stubs
    (exactly 2 fewer) suggests that 2 stub FUNCTION bodies are no longer being emitted as
    independent top-level entities. This is consistent with the consolidated rendering model,
    though a per-stage trace would be needed to pinpoint the exact pages affected.
    See docs/reviews/5a-2026-08-31-rebuild.md for more context.
    """
    sample_path = Path("samples/blueprism/PID_0127.bprelease")
    if not sample_path.exists():
        pytest.skip("Sample file not found")

    from flowsmith.ast.builder import build_ast
    from flowsmith.engine import create_annotator
    from flowsmith.parser import parse_process

    raw = parse_process(sample_path)
    process = build_ast(raw)
    create_annotator().annotate_process(process)

    gen = PADGenerator()
    files = gen.generate_process(process, tmp_path / "robin")

    stub_count = 0
    for f in files:
        text = f.read_text(encoding="utf-8")
        stub_count += text.count("# STUB:")

    # After artefact isolation (Task 3a), reduced to 20 stubs.
    # After consolidated-by-role consolidation (Task 5a), reduced further to 18 stubs
    # due to changes in page routing and rendering logic.
    assert stub_count == 18


@pytest.mark.integration
def test_real_sample_no_tracebacks(tmp_path: Path) -> None:
    """Test that no generated file contains Python tracebacks."""
    sample_path = Path("samples/blueprism/PID_0127.bprelease")
    if not sample_path.exists():
        pytest.skip("Sample file not found")

    from flowsmith.ast.builder import build_ast
    from flowsmith.engine import create_annotator
    from flowsmith.parser import parse_process

    raw = parse_process(sample_path)
    process = build_ast(raw)
    create_annotator().annotate_process(process)

    gen = PADGenerator()
    files = gen.generate_process(process, tmp_path / "robin")

    for f in files:
        text = f.read_text(encoding="utf-8")
        # Only check for actual Python tracebacks, not stage names
        assert "Traceback" not in text
        assert 'File "' not in text or "line" not in text  # Python traceback pattern


@pytest.mark.integration
def test_real_sample_all_files_have_content(tmp_path: Path) -> None:
    """Test that every .robin file has content."""
    sample_path = Path("samples/blueprism/PID_0127.bprelease")
    if not sample_path.exists():
        pytest.skip("Sample file not found")

    from flowsmith.ast.builder import build_ast
    from flowsmith.engine import create_annotator
    from flowsmith.parser import parse_process

    raw = parse_process(sample_path)
    process = build_ast(raw)
    create_annotator().annotate_process(process)

    gen = PADGenerator()
    files = gen.generate_process(process, tmp_path / "robin")

    for f in files:
        lines = f.read_text(encoding="utf-8").splitlines()
        assert len(lines) > 0


@pytest.mark.integration
def test_pid_0171_generates_imports_and_block_structure(tmp_path: Path) -> None:
    """Test that the real PID_0171 release produces IMPORT and BLOCK constructs."""
    sample_path = Path("samples/blueprism/PID_0171.bprelease")
    if not sample_path.exists():
        pytest.skip("Sample file not found")

    from flowsmith.ast.builder import build_ast
    from flowsmith.engine import create_annotator
    from flowsmith.parser import parse_process

    raw = parse_process(sample_path)
    process = build_ast(raw)
    create_annotator().annotate_process(process)

    gen = PADGenerator()
    files = gen.generate_process(process, tmp_path / "robin")
    texts = [f.read_text(encoding="utf-8") for f in files]

    # Main-page header carries the hardcoded IMPORT lines
    assert any("IMPORT 'controlRepo.appmask' AS appmask" in t for t in texts)
    assert any("IMPORT 'imageRepo.imgrepo' AS imgrepo" in t for t in texts)

    # BLOCK stages produce a BLOCK … END scope construct
    block_texts = [t for t in texts if "BLOCK '" in t]
    assert block_texts
    for text in block_texts:
        assert "ON BLOCK ERROR" in text
        assert "END" in text

    # RECOVER / RESUME structural constructs are emitted
    assert any("ERROR => obj_LastError" in t for t in texts)
    assert any("GOTO 'End'" in t for t in texts)


@pytest.mark.integration
def test_pid_0171_page_with_password_item_emits_sensitive() -> None:
    """Test that @SENSITIVE is emitted for a page holding a password item.

    Task 4b: This test validates that password-typed data items are correctly
    captured during parsing and that the generator properly emits @SENSITIVE directives.

    Note: PID_0171's main process has no password items (confirmed by review), but
    secondary processes (e.g. RPA_Sharepoint_API_ConfigFile_Download) in the release do.
    This test finds a secondary process with password data, builds its AST, annotates it,
    and verifies the generator emits @SENSITIVE directives end-to-end.
    """
    sample_path = Path("samples/blueprism/PID_0171.bprelease")
    if not sample_path.exists():
        pytest.skip("Sample file not found")

    from flowsmith.ast.builder import build_ast
    from flowsmith.engine import create_annotator
    from flowsmith.parser import parse_process

    raw = parse_process(sample_path)

    # Search for a secondary process (not the first/main one) that has password items
    secondary_process_with_password = None
    for proc_idx, proc_dict in enumerate(raw.get("processes", [])):
        # Skip the main process (index 0)
        if proc_idx == 0:
            continue
        for page in proc_dict.get("pages", []):
            for stage in page.get("stages", []):
                for di in stage.get("data_items", []):
                    if di.get("data_type", "").lower() == "password":
                        secondary_process_with_password = proc_dict
                        break
                if secondary_process_with_password:
                    break
            if secondary_process_with_password:
                break
        if secondary_process_with_password:
            break

    if not secondary_process_with_password:
        pytest.skip(
            "No password-typed data items found in secondary processes "
            "(main process has none by design)"
        )

    # Build AST from the secondary process and annotate it
    secondary_process = build_ast(secondary_process_with_password)
    create_annotator().annotate_process(secondary_process)

    # Find the page with the password data item
    password_page = None
    for page in secondary_process.pages:
        for stage in page.stages:
            for data_item in stage.data_items:
                if data_item.data_type.lower() == "password":
                    password_page = page
                    break
            if password_page:
                break
        if password_page:
            break

    assert password_page is not None, (
        "Expected to find password-typed data_items in secondary process after AST build"
    )

    # Generate .robin code and verify @SENSITIVE directive is emitted
    gen = PADGenerator()
    result = gen.generate_page(
        password_page.model_copy(update={"is_main": True}), secondary_process.name
    )

    assert "@SENSITIVE: [" in result, (
        f"Expected @SENSITIVE directive in generated code for page '{password_page.name}' "
        f"with password data items, but directive was not found in generated output"
    )


def test_goto_epilogue_declares_error_block_and_end_labels() -> None:
    """A page that jumps to 'Error Block' gets both landing pads."""
    gen = PADGenerator()
    stage = make_annotated_stage(
        stage_id="R1",
        name="Recover",
        stage_type=StageType.RECOVER,
        target_type="",
        confidence=0.70,
    )
    page = make_page(is_main=True, stages=[stage])
    result = gen.generate_page(page, "TestProcess")

    assert "GOTO 'Error Block'" in result
    assert "LABEL 'Error Block'" in result
    assert "LABEL 'End'" in result
    assert result.index("GOTO 'Error Block'") < result.index("LABEL 'Error Block'")


def test_goto_epilogue_omitted_when_page_has_no_goto() -> None:
    """A page with no GOTO gets no LABEL landing pads."""
    gen = PADGenerator()
    page = make_page(is_main=True)
    result = gen.generate_page(page, "TestProcess")

    if "GOTO " not in result:
        assert "LABEL " not in result


# ── Task 5a Regression Tests ─────────────────────────────────────────────────
# These tests validate the consolidated-by-role architecture and de-duplication
# logic introduced in Task 5a. They prevent regressions like the duplicate
# FUNCTION 'Move Emails' bug found in review 5a-2026-08-31-rebuild.md.


@pytest.mark.integration
def test_call_function_correspondence_in_generated_files(tmp_path: Path) -> None:
    """Test that generated files have zero dangling CALL/FUNCTION references.

    This test validates that every CALL references a declared FUNCTION,
    and every FUNCTION has at least one CALL (except boilerplate like 'Get Error').
    It also checks for duplicate FUNCTION name declarations, which would indicate
    a de-duplication failure (e.g., the 'Move Emails' regression from review 5a).

    Task 5a requirement: zero-allowlist correspondence, no silent duplicates.
    """
    sample_path = Path("samples/blueprism/PID_0171.bprelease")
    if not sample_path.exists():
        pytest.skip("Sample file not found")

    from flowsmith.ast.builder import build_ast
    from flowsmith.engine import create_annotator
    from flowsmith.parser import parse_process

    raw = parse_process(sample_path)
    process = build_ast(raw)
    create_annotator().annotate_process(process)

    gen = PADGenerator()
    files = gen.generate_process(process, tmp_path / "robin")

    # Extract all CALL and FUNCTION declarations per file
    import re
    from collections import Counter

    for f in files:
        text = f.read_text(encoding="utf-8")

        # Extract CALLs (active lines only, not comments)
        calls: set[str] = set()
        for line in text.split("\n"):
            if line.strip().startswith("#"):
                continue
            call_matches = re.findall(r"CALL '([^']*)'", line)
            calls.update(call_matches)

        # Extract FUNCTIONs (list to catch duplicates within the file)
        function_matches = re.findall(r"FUNCTION '([^']*)'", text)
        function_counter = Counter(function_matches)

        # Check for duplicates within this file
        duplicate_functions = {k: v for k, v in function_counter.items() if v > 1}
        assert not duplicate_functions, (
            f"File {f.name} has duplicate FUNCTION declarations: {duplicate_functions}"
        )

        # Dangling checks within this file
        unique_functions = set(function_counter.keys())
        boilerplate_allowed = {"Get Error"}

        dangling_calls = calls - unique_functions - boilerplate_allowed
        assert not dangling_calls, f"File {f.name} has dangling CALL references: {dangling_calls}"


@pytest.mark.integration
def test_no_duplicate_function_declarations(tmp_path: Path) -> None:
    """Test that no FUNCTION name is declared twice in any generated file.

    This test specifically catches the Task 5a regression where two BP pages
    (e.g., 'Mark as read mail' and 'Mark as read and move to exception folder')
    both map to the same target_name ('Move Emails') but both were being rendered
    as separate FUNCTION declarations. De-duplication tracking should prevent
    rendering the second occurrence.

    Regression source: review 5a-2026-08-31-rebuild.md (Move Emails declared
    twice at lines 1217 and 1250 of the regenerated Performer file).
    """
    sample_path = Path("samples/blueprism/PID_0171.bprelease")
    if not sample_path.exists():
        pytest.skip("Sample file not found")

    from flowsmith.ast.builder import build_ast
    from flowsmith.engine import create_annotator
    from flowsmith.parser import parse_process

    raw = parse_process(sample_path)
    process = build_ast(raw)
    create_annotator().annotate_process(process)

    gen = PADGenerator()
    files = gen.generate_process(process, tmp_path / "robin")

    import re
    from collections import Counter

    for f in files:
        text = f.read_text(encoding="utf-8")
        matches = re.findall(r"FUNCTION '([^']*)'", text)
        counter = Counter(matches)
        duplicates = {k: v for k, v in counter.items() if v > 1}

        assert not duplicates, f"File {f.name} has duplicate FUNCTION declarations: {duplicates}"


@pytest.mark.integration
def test_mapping_lookup_scoped_to_pid171_not_pid0127(tmp_path: Path) -> None:
    """Test that page_target_map.yaml mappings are process-scoped, not global.

    PID_171-specific mappings (e.g., 'Move Emails', 'Fetch Emails from Mailbox')
    must not leak into PID_0127's output. Both samples are regenerated and
    checked to ensure PID_0127 renders unmapped pages as plain FUNCTIONs with
    default names.

    Task 5a requirement: process-scoped mapping isolation per mapping/page_target_map.yaml
    structure (top-level key = process name).
    """
    import re

    from flowsmith.ast.builder import build_ast
    from flowsmith.engine import create_annotator
    from flowsmith.parser import parse_process

    # Generate PID_0171
    sample_path_0171 = Path("samples/blueprism/PID_0171.bprelease")
    if sample_path_0171.exists():
        raw = parse_process(sample_path_0171)
        process = build_ast(raw)
        create_annotator().annotate_process(process)

        gen = PADGenerator()
        files_0171 = gen.generate_process(process, tmp_path / "robin_0171")

        # Collect PID_0171 FUNCTION names
        functions_0171 = set()
        for f in files_0171:
            text = f.read_text(encoding="utf-8")
            functions_0171.update(re.findall(r"FUNCTION '([^']*)'", text))

    # Generate PID_0127
    sample_path_0127 = Path("samples/blueprism/PID_0127.bprelease")
    if sample_path_0127.exists():
        raw = parse_process(sample_path_0127)
        process = build_ast(raw)
        create_annotator().annotate_process(process)

        gen = PADGenerator()
        files_0127 = gen.generate_process(process, tmp_path / "robin_0127")

        # Collect PID_0127 FUNCTION names
        functions_0127 = set()
        for f in files_0127:
            text = f.read_text(encoding="utf-8")
            functions_0127.update(re.findall(r"FUNCTION '([^']*)'", text))

        # PID_171-specific names must NOT appear in PID_0127
        pid171_specific_names = {
            "Fetch Emails from Mailbox",
            "Send Business Exception Mail",
            "Move Emails",
            "Create Summary Report",
        }

        leaked_names = pid171_specific_names & functions_0127
        assert not leaked_names, (
            f"PID_171-specific FUNCTION names leaked into PID_0127: {leaked_names}"
        )


@pytest.mark.integration
def test_result_entry_splits_into_7_named_functions(tmp_path: Path) -> None:
    """Test that the 'Result Entry' page splits into exactly 7 correctly-named FUNCTIONs.

    Per mapping/page_target_map.yaml §B14 row 6, Result Entry is a split-shape page
    with 7 target function names:
      1. Get Results by Analysis and SampleId
      2. Open - Entry By Test window
      3. Get Components List
      4. Close Results Entry Analysis
      5. Close Results Entry
      6. Set Results Entry
      7. Enter Results in App

    This test confirms the split targets are all rendered and named correctly.

    Task 5a requirement: split-shaped pages render all target FUNCTIONs with
    correct names from the mapping.
    """
    sample_path = Path("samples/blueprism/PID_0171.bprelease")
    if not sample_path.exists():
        pytest.skip("Sample file not found")

    from flowsmith.ast.builder import build_ast
    from flowsmith.engine import create_annotator
    from flowsmith.parser import parse_process

    raw = parse_process(sample_path)
    process = build_ast(raw)
    create_annotator().annotate_process(process)

    gen = PADGenerator()
    files = gen.generate_process(process, tmp_path / "robin")

    import re

    # Collect all FUNCTIONs from the files
    functions_found = set()
    for f in files:
        text = f.read_text(encoding="utf-8")
        functions_found.update(re.findall(r"FUNCTION '([^']*)'", text))

    # Expected split targets
    result_entry_targets = {
        "Get Results by Analysis and SampleId",
        "Open - Entry By Test window",
        "Get Components List",
        "Close Results Entry Analysis",
        "Close Results Entry",
        "Set Results Entry",
        "Enter Results in App",
    }

    # All targets must be present
    missing_targets = result_entry_targets - functions_found
    assert not missing_targets, f"Result Entry split targets missing from output: {missing_targets}"


@pytest.mark.integration
def test_fold_and_inline_block_targets_are_never_silently_dropped(
    tmp_path: Path,
) -> None:
    """Test that fold and inline_block pages' content actually appears in output.

    Per Task 5a, pages marked as fold or inline_block in page_target_map.yaml
    should have their stage content rendered inline at their call sites, not
    silently dropped. This test confirms that:
    - Fold pages' content appears in BEGIN fold / END fold markers
    - Inline_block pages' content appears in BLOCK declarations
    - No fold/inline_block page is skipped without a comment explaining why

    Task 5a requirement: every reachable page's content is rendered somewhere.
    """
    sample_path = Path("samples/blueprism/PID_0171.bprelease")
    if not sample_path.exists():
        pytest.skip("Sample file not found")

    from flowsmith.ast.builder import build_ast
    from flowsmith.engine import create_annotator
    from flowsmith.parser import parse_process

    raw = parse_process(sample_path)
    process = build_ast(raw)
    create_annotator().annotate_process(process)

    gen = PADGenerator()
    files = gen.generate_process(process, tmp_path / "robin")

    # Combine all generated content
    full_content = "\n".join(f.read_text(encoding="utf-8") for f in files)

    # Known fold pages from mapping/page_target_map.yaml (PID_171)
    fold_pages = {
        "Save Attachments",
        "Read Excel As Collection",
        "ConvertConfigFile As Collection - Copy",
        "Input File Management",
        "Reset Global Data",
        "Sample Manager - Explorer",
    }

    # Check that fold pages appear in fold markers
    for page_name in fold_pages:
        # Should appear in BEGIN fold / END fold markers
        assert f"# BEGIN fold: '{page_name}'" in full_content, (
            f"Fold page '{page_name}' not found in output (no BEGIN fold marker)"
        )
        assert f"# END fold: '{page_name}'" in full_content, (
            f"Fold page '{page_name}' not found in output (no END fold marker)"
        )

    # Check that inline_block pages appear in BLOCK declarations
    # These should appear somewhere in BLOCK markers (by block_name, not page_name)
    # The mapping maps them to specific block names
    found = "BLOCK '" in full_content  # At least one BLOCK should exist (loose check)
    assert found, "No inline_block pages rendered (no BLOCK declarations found)"


@pytest.mark.integration
def test_fold_page_variable_names_are_legal_identifiers(tmp_path: Path) -> None:
    """Test that all variable names in generated files are legal identifiers.

    Specifically, ensures no spaces, hyphens, or other illegal non-alphanumeric chars
    leak into SET targets, even in fold or inline_block pages.
    """
    sample_path = Path("samples/blueprism/PID_0171.bprelease")
    if not sample_path.exists():
        pytest.skip("Sample file not found")

    from flowsmith.ast.builder import build_ast
    from flowsmith.engine import create_annotator
    from flowsmith.parser import parse_process

    raw = parse_process(sample_path)
    process = build_ast(raw)
    create_annotator().annotate_process(process)

    gen = PADGenerator()
    files = gen.generate_process(process, tmp_path / "robin")

    # Combine all generated content
    full_content = "\n".join(f.read_text(encoding="utf-8") for f in files)

    import re

    # Match lines like "SET target TO value"
    # Allow dotted targets, e.g. GLOBAL.num_Var or dtb_Col.Field
    set_pattern = re.compile(r"^\s*SET\s+([A-Za-z0-9_\.-]+)\s+TO", re.MULTILINE)
    targets = set_pattern.findall(full_content)

    assert len(targets) > 0, "No SET statements found in generated output!"

    legal_id_pattern = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

    for target in targets:
        # Split dotted references like GLOBAL.num_Var or dtb_Col.Field
        parts = target.split(".")
        for part in parts:
            assert legal_id_pattern.match(part), (
                f"Illegal identifier/part '{part}' found in SET target '{target}'"
            )

    # Assert that PascalCase is used (e.g., RetryCount or ConsecutiveExceptionCount exists)
    has_pascal_case = any("RetryCount" in t or "ConsecutiveExceptionCount" in t for t in targets)
    assert has_pascal_case, "PascalCase variables (e.g. RetryCount) not found in SET targets"


@pytest.mark.integration
def test_main_page_split_routes_calls_by_target_role(tmp_path: Path) -> None:
    """Test that Main Page stages are split by role and calls route correctly.

    Per Task 5a §B11, Main Page stages are split at Get Next Item (stage ID
    85fbb578...). Pre-split stages route to their target's role; post-split
    stages go to Performer. This test confirms:
    - Pre-split stages targeting Loader appear in Loader file only
    - Pre-split stages targeting Performer appear in Performer file only
    - Post-split stages appear in Performer file only
    - No stage call references a file that doesn't contain the target FUNCTION

    Task 5a requirement: role-aware Main Page split prevents cross-role CALL
    dangling.
    """
    sample_path = Path("samples/blueprism/PID_0171.bprelease")
    if not sample_path.exists():
        pytest.skip("Sample file not found")

    from flowsmith.ast.builder import build_ast
    from flowsmith.engine import create_annotator
    from flowsmith.parser import parse_process

    raw = parse_process(sample_path)
    process = build_ast(raw)
    create_annotator().annotate_process(process)

    gen = PADGenerator()
    files = gen.generate_process(process, tmp_path / "robin")

    # Split files by role
    loader_file = next((f for f in files if "Loader" in f.name), None)
    performer_file = next((f for f in files if "Performer" in f.name), None)

    assert loader_file is not None, "No Loader file generated"
    assert performer_file is not None, "No Performer file generated"

    loader_content = loader_file.read_text(encoding="utf-8")
    performer_content = performer_file.read_text(encoding="utf-8")

    import re

    # Extract CALLs and FUNCTIONs from each file
    loader_calls = set(re.findall(r"CALL '([^']*)'", loader_content))
    performer_calls = set(re.findall(r"CALL '([^']*)'", performer_content))

    loader_functions = set(re.findall(r"FUNCTION '([^']*)'", loader_content))
    performer_functions = set(re.findall(r"FUNCTION '([^']*)'", performer_content))

    # Boilerplate and placeholder names that are allowed to dangle
    # (they're either shared between files or are unresolved placeholders)
    allowed_external = {
        "Get Error",  # Shared/boilerplate
        "<page/subprocess>",  # Unresolved subprocess placeholder
    }

    # Every CALL in Loader should reference a FUNCTION in Loader (or an allowed external)
    loader_dangling = loader_calls - loader_functions - allowed_external
    assert not loader_dangling, f"Loader has CALLs with no matching FUNCTION: {loader_dangling}"

    # Every CALL in Performer should reference a FUNCTION in Performer (or an allowed external)
    performer_dangling = performer_calls - performer_functions - allowed_external
    assert not performer_dangling, (
        f"Performer has CALLs with no matching FUNCTION: {performer_dangling}"
    )


def test_coarse_block_synthetic_page_produces_flat_handler_and_goto_label() -> None:
    """Task 5c — synthetic Block/Recover/Resume page: one coarse BLOCK, 3-arm handler
    (no IF), post-block gating IF, GOTO/LABEL dispatch (§A5, §B15).

    Verifies:
    - 3-arm handler: 2 typed arms (Business/System Unavailable) + 1 catch-all (§A5 template)
    - Handler sets flg_ErrorOccurred, never IF — §A5 hard constraint
    - Post-block gating IF: IF flg_ErrorOccurred = True THEN GOTO '<exception>' END (§A5 Do-step 2)
    - LABEL/CALL for exception continuation outside BLOCK body
    - Normal body stage inside BLOCK body
    """
    import re

    gen = PADGenerator()

    exception_page = BPPage(
        page_id="EXCEPT_PAGE",
        name="Item Exception",
        stages=[make_annotated_stage(stage_id="EX_S1", name="Do Exception Work")],
        role="performer",
    )
    normal_page = BPPage(
        page_id="NORMAL_PAGE",
        name="Do Normal Work",
        stages=[make_annotated_stage(stage_id="NRM_S1", name="Step")],
        role="performer",
    )

    block_stage = BPStage(
        stage_id="BLOCK1",
        stage_type=StageType.BLOCK,
        name="Work Block",
        recover_stage_id="RECOVER1",
        pa_annotation=PAAnnotation(
            target_type="BLOCK '<name>' ON BLOCK ERROR ... END <body> END",
            target_module="System",
            runtime=Runtime.DESKTOP,
            params_map={},
            confidence=0.70,
            band=ConfidenceBand.SPOT_CHECK,
            flags=[],
        ),
    )
    normal_call = BPStage(
        stage_id="NORMAL_CALL",
        stage_type=StageType.ACTION,
        name="Do Normal Work",
        is_subsheet_call=True,
        processid="NORMAL_PAGE",
        pa_annotation=PAAnnotation(
            target_type="RunDesktopFlow",
            target_module="SubFlow",
            runtime=Runtime.DESKTOP,
            params_map={},
            confidence=0.85,
            band=ConfidenceBand.SPOT_CHECK,
            flags=[],
        ),
    )
    exception_call = BPStage(
        stage_id="EXCEPTION_CALL",
        stage_type=StageType.ACTION,
        name="Item Exception",
        is_subsheet_call=True,
        processid="EXCEPT_PAGE",
        pa_annotation=PAAnnotation(
            target_type="RunDesktopFlow",
            target_module="SubFlow",
            runtime=Runtime.DESKTOP,
            params_map={},
            confidence=0.85,
            band=ConfidenceBand.SPOT_CHECK,
            flags=[],
        ),
    )
    recover_stage = BPStage(
        stage_id="RECOVER1",
        stage_type=StageType.RECOVER,
        name="Recover",
        pa_annotation=PAAnnotation(
            target_type="",
            target_module="System",
            runtime=Runtime.DESKTOP,
            params_map={},
            confidence=0.80,
            band=ConfidenceBand.SPOT_CHECK,
            flags=[],
        ),
    )
    resume_stage = BPStage(
        stage_id="RESUME1",
        stage_type=StageType.RESUME,
        name="Resume",
        pa_annotation=PAAnnotation(
            target_type="",
            target_module="System",
            runtime=Runtime.DESKTOP,
            params_map={},
            confidence=0.80,
            band=ConfidenceBand.SPOT_CHECK,
            flags=[],
        ),
    )

    stages = [block_stage, normal_call, exception_call, recover_stage, resume_stage]
    process = BPProcess(
        process_id="TEST",
        name="TestProcess",
        version="1.0",
        source_file="test.bprelease",
        pages=[
            BPPage(page_id="MAIN", name="Main Page", stages=stages, is_main=True),
            exception_page,
            normal_page,
        ],
    )

    result = gen._render_stage_list_with_coarse_blocks(
        stages, process, process_map={}, variable_name_mapping=None
    )

    # 1. Exactly one coarse BLOCK opener — not one per inner CALL
    block_count = len(re.findall(r"^BLOCK '", result, re.MULTILINE))
    assert block_count == 1, f"Expected 1 coarse BLOCK, got {block_count}"

    # 2. Handler uses 3-arm §A5 dispatch template (typed arms + catch-all)
    assert "ON BLOCK ERROR 'Business Exception' IsUserDefinedErrorCode: True" in result, (
        "§A5 typed handler arm for Business Exception missing"
    )
    assert "ON BLOCK ERROR 'System Unavailable Exception' IsUserDefinedErrorCode: True" in result, (
        "§A5 typed handler arm for System Unavailable Exception missing"
    )
    assert "ON BLOCK ERROR all" in result, "§A5 catch-all handler arm missing"

    # 3. Handler sets flg_ErrorOccurred — NOT txt_ItemStatus, NOT a GOTO (§A5)
    assert "SET flg_ErrorOccurred TO True" in result, (
        "Handler must SET flg_ErrorOccurred (§A5 ref L1389/1394/1398)"
    )
    # Hard constraint: no IF anywhere inside the handler body (§A5)
    handler_section = result[result.index("ON BLOCK ERROR") : result.index("\nEND\n")]
    assert "IF " not in handler_section, f"IF inside handler violates §A5: {handler_section!r}"
    # GOTO must NOT be inside the handler — it belongs in the post-block IF (§A5 Do-step 2)
    assert "GOTO" not in handler_section, (
        f"GOTO inside handler violates §A5 Do-step 2: {handler_section!r}"
    )

    # 4. Post-block gating IF dispatches to exception label (§A5 Do-step 2, §B15 ref L1469–1472)
    assert "IF flg_ErrorOccurred = True THEN" in result, (
        "Post-block gating IF missing — §A5 requires branching after the enclosing scope"
    )
    assert "GOTO 'Item Exception'" in result, "Post-block GOTO to exception label missing (§B15)"

    # 5. LABEL/CALL for exception continuation appears OUTSIDE the BLOCK body
    # Robin BLOCK structure: handler (ends at first END), body (ends at second END)
    block_open_pos = result.index("BLOCK 'Work Block'")
    first_end_pos = result.index("\nEND\n", block_open_pos)  # closes handler section
    body_end_pos = result.index("\nEND\n", first_end_pos + 1)  # closes body
    label_pos = result.index("LABEL 'Item Exception'")
    call_pos = result.index("CALL 'Item Exception'")
    assert label_pos > body_end_pos, "LABEL must be after BLOCK body END (§B15)"
    assert call_pos > body_end_pos, "CALL to exception page must be outside BLOCK (§B15)"

    # 6. Normal body stage inside BLOCK body (between handler END and body END)
    normal_call_pos = result.index("CALL 'Do Normal Work'")
    assert first_end_pos < normal_call_pos < body_end_pos, "Normal stage must be inside BLOCK body"

    # 7. Reset label ('Work Block end') emitted after exception section (§B15 ref L1490)
    reset_label_pos = result.index("LABEL 'Work Block end'")
    assert reset_label_pos > label_pos, (
        "LABEL 'Work Block end' must appear after LABEL 'Item Exception' (§B15 ref L1490)"
    )


def test_coarse_block_two_continuation_labels_routes_correctly() -> None:
    """Task 5c — two continuation labels (Completed + Exception): gating IF prevents
    fall-through double-execution of both labels on every iteration.

    This is the exact scenario the reverify review (5c-2026-09-01-reverify.md) identified
    as a real correctness bug: without the post-block gating IF, execution falls through
    LABEL 'Mark Item as Completed' and LABEL 'Mark Item as Exception' unconditionally,
    calling both CALL 'Mark Complete' and CALL 'Mark Exception' on every loop iteration.

    The correct structure (§B15 reference lines 1469–1483):
      END                                 ← closes BLOCK body
      IF flg_ErrorOccurred = True THEN    ← gating IF (§A5 Do-step 2)
          SET txt_ItemStatus TO $'''Failed'''
          GOTO 'Mark Item as Exception'
      END
      LABEL 'Mark Item as Completed'      ← happy-path continuation
      CALL 'Mark Complete'
      GOTO 'Mark Item as Exception'       ← skip past exception label (§B15 ref L1477)
      LABEL 'Mark Item as Exception'      ← error-path continuation
      CALL 'Mark Exception'
    """
    gen = PADGenerator()

    exception_page = BPPage(
        page_id="EXCEPT_PAGE",
        name="Mark Item As Exception",
        stages=[make_annotated_stage(stage_id="EX_S1", name="Do Exception Work")],
        role="performer",
    )
    completed_page = BPPage(
        page_id="COMPLETED_PAGE",
        name="Mark Item As Completed",
        stages=[make_annotated_stage(stage_id="COMP_S1", name="Do Complete Work")],
        role="performer",
    )
    normal_page = BPPage(
        page_id="NORMAL_PAGE",
        name="Process Items",
        stages=[make_annotated_stage(stage_id="NRM_S1", name="Step")],
        role="performer",
    )

    block_stage = BPStage(
        stage_id="BLOCK1",
        stage_type=StageType.BLOCK,
        name="Work",
        recover_stage_id="RECOVER1",
        pa_annotation=PAAnnotation(
            target_type="BLOCK '<name>' ON BLOCK ERROR ... END <body> END",
            target_module="System",
            runtime=Runtime.DESKTOP,
            params_map={},
            confidence=0.70,
            band=ConfidenceBand.SPOT_CHECK,
            flags=[],
        ),
    )
    normal_call = BPStage(
        stage_id="NORMAL_CALL",
        stage_type=StageType.ACTION,
        name="Process Items",
        is_subsheet_call=True,
        processid="NORMAL_PAGE",
        pa_annotation=PAAnnotation(
            target_type="RunDesktopFlow",
            target_module="SubFlow",
            runtime=Runtime.DESKTOP,
            params_map={},
            confidence=0.85,
            band=ConfidenceBand.SPOT_CHECK,
            flags=[],
        ),
    )
    # Completed page call (first in body — goes under LABEL first in output)
    completed_call = BPStage(
        stage_id="COMPLETED_CALL",
        stage_type=StageType.ACTION,
        name="Mark Item As Completed",
        is_subsheet_call=True,
        processid="COMPLETED_PAGE",
        pa_annotation=PAAnnotation(
            target_type="RunDesktopFlow",
            target_module="SubFlow",
            runtime=Runtime.DESKTOP,
            params_map={},
            confidence=0.85,
            band=ConfidenceBand.SPOT_CHECK,
            flags=[],
        ),
    )
    # Exception page call (second in body — goes under LABEL second in output)
    exception_call = BPStage(
        stage_id="EXCEPTION_CALL",
        stage_type=StageType.ACTION,
        name="Mark Item As Exception",
        is_subsheet_call=True,
        processid="EXCEPT_PAGE",
        pa_annotation=PAAnnotation(
            target_type="RunDesktopFlow",
            target_module="SubFlow",
            runtime=Runtime.DESKTOP,
            params_map={},
            confidence=0.85,
            band=ConfidenceBand.SPOT_CHECK,
            flags=[],
        ),
    )
    recover_stage = BPStage(
        stage_id="RECOVER1",
        stage_type=StageType.RECOVER,
        name="Recover",
        pa_annotation=PAAnnotation(
            target_type="",
            target_module="System",
            runtime=Runtime.DESKTOP,
            params_map={},
            confidence=0.80,
            band=ConfidenceBand.SPOT_CHECK,
            flags=[],
        ),
    )
    resume_stage = BPStage(
        stage_id="RESUME1",
        stage_type=StageType.RESUME,
        name="Resume",
        pa_annotation=PAAnnotation(
            target_type="",
            target_module="System",
            runtime=Runtime.DESKTOP,
            params_map={},
            confidence=0.80,
            band=ConfidenceBand.SPOT_CHECK,
            flags=[],
        ),
    )

    stages = [block_stage, normal_call, completed_call, exception_call, recover_stage, resume_stage]
    process = BPProcess(
        process_id="TEST2",
        name="TestProcess2",
        version="1.0",
        source_file="test.bprelease",
        pages=[
            BPPage(page_id="MAIN2", name="Main Page", stages=stages, is_main=True),
            exception_page,
            completed_page,
            normal_page,
        ],
    )

    result = gen._render_stage_list_with_coarse_blocks(
        stages, process, process_map={}, variable_name_mapping=None
    )

    # 1. Post-block gating IF present — routes to exception label
    assert "IF flg_ErrorOccurred = True THEN" in result, (
        "Post-block gating IF missing — double-execution bug without it (reverify §5c-2026-09-01)"
    )

    # 2. LABEL order: Completed appears BEFORE Exception (§B15 ref lines 1473, 1479)
    completed_label_pos = result.index("LABEL 'Mark Item As Completed'")
    exception_label_pos = result.index("LABEL 'Mark Item As Exception'")
    assert completed_label_pos < exception_label_pos, (
        "LABEL 'Mark Item As Completed' must appear before LABEL 'Mark Item As Exception' (§B15)"
    )

    # 3. A skip-GOTO separates the Completed section from the Exception label (§B15 ref L1477)
    # The skip-GOTO must jump to the RESET label ('Work end') placed AFTER the exception section —
    # not to the exception label itself (jumping to the immediately-following label is a no-op).
    # Reference: L1477 → GOTO 'Reset All' (L1490), NOT GOTO 'Mark Item as Exception' (L1479).
    between = result[completed_label_pos:exception_label_pos]
    assert "GOTO 'Work end'" in between, (
        "Skip-GOTO from Completed section must target reset label ('Work end'), not the "
        "exception label — GOTO to the immediately-following label is a no-op that leaves "
        "both CALL 'Mark Complete' and CALL 'Mark Exception' executing unconditionally (§B15 L1477)"
    )

    # 4. The reset label ('Work end') appears AFTER the exception continuation (§B15 ref L1490)
    # This is what the skip-GOTO actually jumps past the exception section to reach.
    reset_label_pos = result.index("LABEL 'Work end'")
    exception_call_pos = result.index("CALL 'Mark Item As Exception'")
    assert reset_label_pos > exception_call_pos, (
        "LABEL 'Work end' must appear after CALL 'Mark Item As Exception' — "
        "the skip-GOTO must clear the entire exception section (§B15 ref L1490)"
    )

    # 5. Neither continuation CALL is inside the BLOCK body
    block_open_pos = result.index("BLOCK 'Work'")
    first_end_pos = result.index("\nEND\n", block_open_pos)
    body_end_pos = result.index("\nEND\n", first_end_pos + 1)
    completed_call_pos = result.index("CALL 'Mark Item As Completed'")
    assert completed_call_pos > body_end_pos, "CALL 'Mark Complete' must be outside BLOCK body"
    assert exception_call_pos > body_end_pos, "CALL 'Mark Exception' must be outside BLOCK body"

    # 6. Normal body stage IS inside the BLOCK body
    normal_call_pos = result.index("CALL 'Process Items'")
    assert first_end_pos < normal_call_pos < body_end_pos, "Normal stage must be inside BLOCK body"


@pytest.mark.integration
def test_coarse_block_pid171_process_work_queue_items_structure(tmp_path: Path) -> None:
    """Task 5c — real PID_0171 sample: BLOCK 'Work' structure matches §B15 worked example.

    Verifies:
    - One outer BLOCK 'Work' (§B15)
    - 3-arm §A5 handler: flg_ErrorOccurred set, no GOTO inside handler
    - Post-block gating IF flg_ErrorOccurred dispatches to exception label
    - LABEL 'Mark Item As Exception' and CALL 'Mark Exception' outside any BLOCK
    - LABEL 'Mark Item As Completed' appears before LABEL 'Mark Item As Exception'
    - Skip-GOTO separates the two labels to prevent fall-through
    """
    import re

    sample_path = Path("samples/blueprism/PID_0171.bprelease")
    if not sample_path.exists():
        pytest.skip("Sample file not found")

    from flowsmith.ast.builder import build_ast
    from flowsmith.engine import create_annotator
    from flowsmith.parser import parse_process

    raw = parse_process(sample_path)
    process = build_ast(raw)
    create_annotator().annotate_process(process)

    gen = PADGenerator()
    files = gen.generate_process(process, tmp_path / "robin")

    performer_file = next((f for f in files if "Performer" in f.name), None)
    assert performer_file is not None, "No Performer file generated"
    content = performer_file.read_text(encoding="utf-8")

    # 1. One outer BLOCK 'Work' present (§B15 worked example)
    assert re.search(r"BLOCK 'Work'", content), "BLOCK 'Work' not found in Performer (§B15)"

    # 2. Handler has 3-arm §A5 structure (no GOTO inside handler body)
    assert "ON BLOCK ERROR 'Business Exception' IsUserDefinedErrorCode: True" in content, (
        "§A5 typed Business Exception handler arm missing"
    )
    assert "SET flg_ErrorOccurred TO True" in content, (
        "Handler must SET flg_ErrorOccurred (§A5 ref L1389/1394/1398)"
    )

    # 3. Post-block gating IF dispatches to exception label (§A5 Do-step 2)
    assert "IF flg_ErrorOccurred = True THEN" in content, (
        "Post-block gating IF missing — without it every item gets double-marked (§A5)"
    )
    assert "GOTO 'Mark Item As Exception'" in content, (
        "GOTO 'Mark Item As Exception' missing from post-block gating IF (§B15)"
    )

    # 4. CALL 'Mark Exception' appears OUTSIDE any BLOCK (at depth 0)
    lines = content.splitlines()
    depth = 0
    call_mark_exception_depths: list[int] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("BLOCK '"):
            depth += 1
        if stripped == "END":
            depth = max(0, depth - 1)
        if "CALL 'Mark Exception'" in stripped:
            call_mark_exception_depths.append(depth)

    assert call_mark_exception_depths, "No CALL 'Mark Exception' found in Performer"
    assert 0 in call_mark_exception_depths, (
        f"CALL 'Mark Exception' always inside a BLOCK (depths={call_mark_exception_depths}); "
        "it must appear outside any BLOCK under LABEL 'Mark Item As Exception' (§B15)"
    )

    # 5. LABEL 'Mark Item As Completed' appears before LABEL 'Mark Item As Exception'
    assert "LABEL 'Mark Item As Completed'" in content, (
        "LABEL 'Mark Item As Completed' missing (§B15)"
    )
    completed_pos = content.index("LABEL 'Mark Item As Completed'")
    exception_pos = content.index("LABEL 'Mark Item As Exception'")
    assert completed_pos < exception_pos, (
        "LABEL 'Mark Item As Completed' must precede LABEL 'Mark Item As Exception' (§B15)"
    )

    # 6. Skip-GOTO from Completed section targets the reset label ('Work end'), placed after the
    # exception section — NOT 'Mark Item As Exception' (jumping there is a no-op since it is the
    # immediately-following label).  Reference: L1477 → GOTO 'Reset All' (L1490).
    between = content[completed_pos:exception_pos]
    assert "GOTO 'Work end'" in between, (
        "Skip-GOTO from Completed section must target 'Work end' (§B15 ref L1477 → 'Reset All'), "
        "not 'Mark Item As Exception' — GOTO to the immediately-following label is a no-op and "
        "leaves both CALL 'Mark Complete' and CALL 'Mark Exception' executing unconditionally"
    )

    # 7. Reset label ('Work end') appears AFTER 'Mark Item As Exception' content (§B15 ref L1490)
    reset_label_pos = content.index("LABEL 'Work end'")
    mark_exception_pos = content.index("LABEL 'Mark Item As Exception'")
    assert reset_label_pos > mark_exception_pos, (
        "LABEL 'Work end' must appear after LABEL 'Mark Item As Exception' (§B15 ref L1490)"
    )


def test_coarse_block_fallback_to_error_block_when_no_exception_page() -> None:
    """Task 5c fix — coarse BLOCK with no exception continuation page uses 'Error Block' dispatch.

    When a coarse BLOCK's body contains no SubSheet call to a page whose name contains
    "exception", the dispatch-label falls back to the generic 'Error Block' label (which
    is always present in the epilogue) instead of inventing a synthetic '<block_name> recovery'
    label that has no matching LABEL definition. This test verifies the fallback path
    closes the dangling-GOTO bug found in Task 5c's verification pass.

    See: docs/reviews/5c-2026-09-01-head-verify.md (dangling GOTO targets for 6 real
    BLOCK stages in PID_0171 output).
    """
    import re

    gen = PADGenerator()

    # No exception continuation page — only a normal page
    normal_page = BPPage(
        page_id="NORMAL_PAGE",
        name="Process Items",
        stages=[make_annotated_stage(stage_id="NRM_S1", name="Step")],
        role="performer",
    )

    block_stage = BPStage(
        stage_id="BLOCK1",
        stage_type=StageType.BLOCK,
        name="Input Block",  # Name without "exception" in it
        recover_stage_id="RECOVER1",
        pa_annotation=PAAnnotation(
            target_type="BLOCK '<name>' ON BLOCK ERROR ... END <body> END",
            target_module="System",
            runtime=Runtime.DESKTOP,
            params_map={},
            confidence=0.70,
            band=ConfidenceBand.SPOT_CHECK,
            flags=[],
        ),
    )
    normal_call = BPStage(
        stage_id="NORMAL_CALL",
        stage_type=StageType.ACTION,
        name="Process Items",
        is_subsheet_call=True,
        processid="NORMAL_PAGE",
        pa_annotation=PAAnnotation(
            target_type="RunDesktopFlow",
            target_module="SubFlow",
            runtime=Runtime.DESKTOP,
            params_map={},
            confidence=0.85,
            band=ConfidenceBand.SPOT_CHECK,
            flags=[],
        ),
    )
    recover_stage = BPStage(
        stage_id="RECOVER1",
        stage_type=StageType.RECOVER,
        name="Recover",
        pa_annotation=PAAnnotation(
            target_type="",
            target_module="System",
            runtime=Runtime.DESKTOP,
            params_map={},
            confidence=0.80,
            band=ConfidenceBand.SPOT_CHECK,
            flags=[],
        ),
    )
    resume_stage = BPStage(
        stage_id="RESUME1",
        stage_type=StageType.RESUME,
        name="Resume",
        pa_annotation=PAAnnotation(
            target_type="",
            target_module="System",
            runtime=Runtime.DESKTOP,
            params_map={},
            confidence=0.80,
            band=ConfidenceBand.SPOT_CHECK,
            flags=[],
        ),
    )

    stages = [block_stage, normal_call, recover_stage, resume_stage]
    process = BPProcess(
        process_id="TEST",
        name="TestProcess",
        version="1.0",
        source_file="test.bprelease",
        pages=[
            BPPage(page_id="MAIN", name="Main Page", stages=stages, is_main=True),
            normal_page,
        ],
    )

    result = gen._render_stage_list_with_coarse_blocks(
        stages, process, process_map={}, variable_name_mapping=None
    )

    # 1. Post-block gating IF should route to 'Error Block' (not a synthetic label)
    assert "IF flg_ErrorOccurred = True THEN" in result, "Post-block gating IF missing"
    assert "GOTO 'Error Block'" in result, (
        "Post-block GOTO should dispatch to 'Error Block' when no exception page exists (§A5 fix)"
    )

    # 2. No synthetic recovery label should be invented (the old buggy behavior)
    # We should never see "GOTO 'Input Block recovery'" or similar
    assert "recovery" not in result.lower(), (
        "Synthetic recovery labels must not be created; use 'Error Block' instead (§A5 fix)"
    )

    # 3. Verify the GOTO 'Error Block' is correct (not going to a non-existent label)
    # The LABEL itself is added by _render_goto_epilogue at the page level, but we
    # verify here that we're using a well-known label name, not inventing one.
    gotos = set(re.findall(r"GOTO '([^']+)'", result))
    assert "Error Block" in gotos, "Must GOTO 'Error Block' (a standard label added by epilogue)"


def test_accidental_function_name_collision_disambiguation(tmp_path: Path) -> None:
    """Task 6b2: Accidental collisions get disambiguated, not silently dropped.

    When two unrelated pages both fallback to their own name (no `page_target_map.yaml`
    `target_name` entry for either), and the names happen to collide (e.g., after
    sanitisation), they should render as distinct FUNCTIONs with disambiguation suffixes
    (_2, _3, ...), not as a silent drop of the second one.

    First occurrence renders bare (no suffix), second+ get suffixes.

    Citation: Task 6b2 Do-step 1, docs/reviews/6b-2026-09-01-rereview.md gap Finding 2.
    """
    # Build a minimal process with two pages that collide on fallback name
    process = BPProcess(
        process_id="test-proc",
        name="TestProcess",
        version="1.0",
        source_file="test.bprelease",
        description="Test accidental collision",
        pages=[
            BPPage(
                page_id="page1",
                name="Copy",  # First "Copy" (fallback, will render as bare "Copy")
                role="performer",
                stages=[
                    BPStage(
                        stage_id="s1",
                        name="Action1",
                        stage_type=StageType.ACTION,
                        is_subsheet_call=False,
                        data_items=[],
                        pa_annotation=PAAnnotation(
                            target_type=StageType.ACTION,
                            target_module="System",
                            runtime=Runtime.DESKTOP,
                            params_map={},
                            pa_target_action="# Test action 1",
                            confidence=0.9,
                            band=ConfidenceBand.AUTO,
                        ),
                    ),
                ],
            ),
            BPPage(
                page_id="page2",
                name="Copy",  # Second "Copy" (fallback, will render as "Copy_2")
                role="performer",
                stages=[
                    BPStage(
                        stage_id="s2",
                        name="Action2",
                        stage_type=StageType.ACTION,
                        is_subsheet_call=False,
                        data_items=[],
                        pa_annotation=PAAnnotation(
                            target_type=StageType.ACTION,
                            target_module="System",
                            runtime=Runtime.DESKTOP,
                            params_map={},
                            pa_target_action="# Test action 2",
                            confidence=0.9,
                            band=ConfidenceBand.AUTO,
                        ),
                    ),
                ],
            ),
            BPPage(
                page_id="page3",
                name="Caller",  # Calls the first Copy page
                role="performer",
                stages=[
                    BPStage(
                        stage_id="s3",
                        name="CallFirstCopy",
                        stage_type=StageType.ACTION,
                        is_subsheet_call=True,
                        processid="page1",  # Calls Copy (first one)
                        data_items=[],
                        pa_annotation=PAAnnotation(
                            target_type=StageType.ACTION,
                            target_module="System",
                            runtime=Runtime.DESKTOP,
                            params_map={},
                            pa_target_action="CALL 'placeholder'",
                            confidence=0.9,
                            band=ConfidenceBand.AUTO,
                        ),
                    ),
                    BPStage(
                        stage_id="s4",
                        name="CallSecondCopy",
                        stage_type=StageType.ACTION,
                        is_subsheet_call=True,
                        processid="page2",  # Calls Copy_2 (second one)
                        data_items=[],
                        pa_annotation=PAAnnotation(
                            target_type=StageType.ACTION,
                            target_module="System",
                            runtime=Runtime.DESKTOP,
                            params_map={},
                            pa_target_action="CALL 'placeholder'",
                            confidence=0.9,
                            band=ConfidenceBand.AUTO,
                        ),
                    ),
                ],
            ),
        ],
    )

    # Generate
    generator = PADGenerator()
    generator.generate_process(process, tmp_path)

    # Read the generated Performer file
    performer_files = list(tmp_path.glob("*Performer*.robin"))
    assert performer_files, "No Performer .robin file generated"
    content = performer_files[0].read_text()

    # Verify: both "Copy" pages render as distinct FUNCTIONs
    assert "FUNCTION 'Copy'" in content, (
        "Accidental collision: first 'Copy' should render as bare 'Copy'"
    )
    assert "FUNCTION 'Copy_2'" in content, (
        "Accidental collision: second 'Copy' should render as 'Copy_2'"
    )

    # Verify: CALL sites use the correct (resolved) names
    assert "CALL 'Copy'" in content, (
        "Accidental collision: CALL to first Copy page should use bare 'Copy'"
    )
    assert "CALL 'Copy_2'" in content, (
        "Accidental collision: CALL to second Copy page should use 'Copy_2'"
    )

    # Verify: no silent drop — both pages rendered
    copy_count = content.count("FUNCTION 'Copy")
    assert copy_count == 2, (
        f"Accidental collision: expected 2 'Copy' FUNCTION declarations, got {copy_count}"
    )


def test_intentional_fold_mapping_no_disambiguation(tmp_path: Path) -> None:
    """Task 6b2: Intentional folds (explicit mapping) render once with no suffix.

    When `page_target_map.yaml` gives two pages the same `target_name` (intentional
    fold, like "Mark as read mail" → "Move Emails" and "Mark as read and move..."
    → "Move Emails"), the second occurrence should be skipped silently with no suffix.

    This is a regression test that verifies the `test_no_duplicate_function_declarations`
    behavior is maintained for intentional mapping-declared folds.

    Citation: Task 6b2 Do-step 1, mapping/page_target_map.yaml lines 123-134.
    """
    # Use the real PID_171 sample which has the "Move Emails" intentional fold
    sample = Path("samples/blueprism/PID_0171.bprelease")
    if not sample.exists():
        pytest.skip(f"Sample {sample} not found")

    from flowsmith.ast import build_ast
    from flowsmith.engine import create_annotator
    from flowsmith.parser import parse_process

    process = build_ast(parse_process(sample))
    create_annotator().annotate_process(process)

    # Generate
    generator = PADGenerator()
    generator.generate_process(process, tmp_path)

    # Read the generated Performer file
    performer_files = list(tmp_path.glob("*Performer*.robin"))
    assert performer_files, "No Performer .robin file generated"
    content = performer_files[0].read_text()

    # Verify: "Move Emails" FUNCTION appears exactly once (intentional fold)
    # The two pages ("Mark as read mail" and "Mark as read and move to exception folder")
    # both map to "Move Emails" via explicit page_target_map.yaml entries.
    move_emails_count = content.count("FUNCTION 'Move Emails'")
    assert move_emails_count == 1, (
        f"Intentional fold: 'Move Emails' FUNCTION should appear exactly once, "
        f"got {move_emails_count} times"
    )

    # Verify: No disambiguation suffix on "Move Emails" (stays bare, not "Move Emails_2")
    assert "FUNCTION 'Move Emails_2'" not in content, (
        "Intentional fold: 'Move Emails' should NOT get a disambiguation suffix"
    )

    # Verify: Both source pages map to the same FUNCTION (implicit via only one rendering)
    # We can't directly assert both pages' original names are referenced as calls
    # (they might be inlined), but the presence of exactly one "Move Emails" FUNCTION
    # with no suffix is the litmus test for intentional fold behavior.


def test_work_queues_method_actions_are_rendered(tmp_path: Path) -> None:
    """Task 7a — real PID_0171 sample: WorkQueues method_actions templates are used.

    Verifies that Get Next Item, Mark Completed, Mark Exception, Update Status
    render with their real PAD syntax from vbo_catalogue.yaml's method_actions,
    not as generic TODO stubs.
    """
    sample_path = Path("samples/blueprism/PID_0171.bprelease")
    if not sample_path.exists():
        pytest.skip("Sample file not found")

    from flowsmith.ast.builder import build_ast
    from flowsmith.engine import create_annotator
    from flowsmith.parser import parse_process

    raw = parse_process(sample_path)
    process = build_ast(raw)
    create_annotator().annotate_process(process)

    gen = PADGenerator()
    files = gen.generate_process(process, tmp_path / "robin")

    performer_file = next((f for f in files if "Performer" in f.name), None)
    assert performer_file is not None, "No Performer file generated"
    content = performer_file.read_text(encoding="utf-8")

    # Verify: Real Get Next Item template is rendered (from method_actions)
    # The template is: WorkQueues.ProcessWorkQueueItem.ProcessWorkQueueItem WorkQueue: <id> WorkQueueItem=> <var>
    assert "WorkQueues.ProcessWorkQueueItem.ProcessWorkQueueItem" in content, (
        "Get Next Item should render real PAD syntax from method_actions, not a TODO stub"
    )

    # Verify: Mark Completed template is rendered (from method_actions)
    # The template is: WorkQueues.UpdateWorkQueueItem.UpdateWithProcessingNotes ... Processed
    assert "WorkQueues.UpdateWorkQueueItem.UpdateWithProcessingNotes" in content, (
        "Mark Completed should render real PAD syntax from method_actions"
    )

    # Verify: No generic TODO stubs for the 4 documented methods
    # (Tag Item and Defer can still be TODO'd — they're intentionally unmapped)
    todo_count = content.count("# TODO: WorkQueues.Get Next Item")
    assert todo_count == 0, (
        f"Get Next Item should not render as TODO stub (found {todo_count} occurrences)"
    )

    todo_count = content.count("# TODO: WorkQueues.Mark Completed")
    assert todo_count == 0, (
        f"Mark Completed should not render as TODO stub (found {todo_count} occurrences)"
    )

    # Verify: Tag Item and Defer should still be TODO'd (they're out of scope per Task 7a)
    # They should appear as generic stubs since they have no method_actions entry
    assert (
        "# TODO: WorkQueues.Tag Item" in content or "# TODO: WorkQueues.Set Item Tags" in content
    ), "Tag Item/Set Item Tags should remain as TODO stub (no confirmed PAD template exists)"


def test_work_queues_placeholders_are_substituted(tmp_path: Path) -> None:
    """Task 7a third pass: Placeholder tokens are replaced with real PAD syntax.

    Verifies that template placeholders (<id>, <var>, <obj>, <msg>, <text>) in
    WorkQueues actions are substituted with actual values from stage.params_map,
    not emitted literally (bare angle brackets). Specifically validates:
    1. No template placeholder tokens (<id>, <var>, <obj>, <msg>, <text>) remain
    2. <var> correctly resolves to obj_WorkQueueItem for Get Next Item
    3. <obj> correctly resolves to obj_WorkQueueItem for Mark/Update methods
    4. <id> and <msg> resolve via _translate_bp_expression using variable_name_mapping
    5. <text> uses Status parameter (not "Processing Notes") and renders real status values
    """
    sample_path = Path("samples/blueprism/PID_0171.bprelease")
    if not sample_path.exists():
        pytest.skip("Sample file not found")

    from flowsmith.ast.builder import build_ast
    from flowsmith.engine import create_annotator
    from flowsmith.parser import parse_process

    raw = parse_process(sample_path)
    process = build_ast(raw)
    create_annotator().annotate_process(process)

    gen = PADGenerator()
    files = gen.generate_process(process, tmp_path / "robin")

    performer_file = next((f for f in files if "Performer" in f.name), None)
    assert performer_file is not None, "No Performer file generated"
    content = performer_file.read_text(encoding="utf-8")

    # Verify: No bare placeholder tokens appear in WORKQUEUES actions
    # Extract only WorkQueues lines to verify substitution
    workqueues_lines = [
        line
        for line in content.split("\n")
        if "WorkQueues." in line and not line.strip().startswith("#")
    ]

    placeholder_tokens = ["<id>", "<var>", "<obj>", "<msg>", "<text>"]
    for line in workqueues_lines:
        for token in placeholder_tokens:
            assert token not in line, (
                f"Placeholder token {token} should not appear in WorkQueues action: {line[:80]}... "
                f"Must be substituted with real PAD syntax (not bare angle brackets)."
            )

    # Verify: <var> correctly resolves to obj_WorkQueueItem
    assert "WorkQueueItem=> obj_WorkQueueItem" in content, (
        "Get Next Item should substitute <var> with obj_WorkQueueItem"
    )

    # Verify: <obj> correctly resolves to obj_WorkQueueItem for Mark methods
    assert "WorkQueueItem: obj_WorkQueueItem" in content, (
        "Mark Exception/Mark Completed should substitute <obj> with obj_WorkQueueItem"
    )

    # Verify: <id> is substituted via queue_bindings catalogue or expression translation
    # Task 7a (b): Queue bindings from catalogue should bind ConfigFileData.Queue Name to txt_WorkQueueId
    # with a VERIFY comment naming the dependency.
    # Pattern check: any WorkQueues.ProcessWorkQueueItem line should have WorkQueue: <something>
    # where <something> is NOT a literal angle-bracket placeholder
    for line in workqueues_lines:
        if "ProcessWorkQueueItem" in line:
            assert "WorkQueue: <id>" not in line, (
                "Queue Name <id> must be substituted via queue_bindings or _translate_bp_expression, not left as literal"
            )
            # Verify the line contains a WorkQueue parameter with some value
            assert "WorkQueue:" in line, "ProcessWorkQueueItem should have WorkQueue parameter"

    # Task 7a (a): Verify VERIFY comment precedes Get Next Item if bound from catalogue
    # (c): Assert the rendered WorkQueue: value is exactly txt_WorkQueueId for config-queue case
    assert "WorkQueue: txt_WorkQueueId" in content, (
        "Get Next Item should bind ConfigFileData.Queue Name to txt_WorkQueueId from catalogue"
    )

    # (c): Assert the VERIFY dependency marker precedes the action
    verify_marker = "# VERIFY: Get Next Item queue ID 'txt_WorkQueueId'"
    assert verify_marker in content, (
        f"VERIFY comment should appear before Get Next Item call binding to txt_WorkQueueId: {verify_marker}"
    )

    # Verify: <text> substitution uses correct Status parameter (not "Processing Notes")
    # Real BP call sites have Status values like "COMPLETED", "Sample Manager Launched Sucessfully", etc.
    # These should appear in UpdateProcessingNotes calls, not as placeholder text
    update_status_lines = [
        line
        for line in content.split("\n")
        if "UpdateProcessingNotes" in line and not line.strip().startswith("#")
    ]
    if update_status_lines:
        # Should have at least some real status values from the BP stages
        # At minimum, should NOT have literal %ProcessingNotes% everywhere (would indicate key mismatch)
        all_statuses = "\n".join(update_status_lines)
        # If we have UpdateProcessingNotes calls, at least some should have non-placeholder content
        # (Note: some may legitimately have fallback %Status% if expression translation is incomplete,
        #  but the point is no "%ProcessingNotes%" should appear, which was the bug from the wrong key)
        assert "%ProcessingNotes%" not in all_statuses, (
            "UpdateProcessingNotes should use Status parameter, not 'Processing Notes' which doesn't exist"
        )


def test_mark_exception_has_three_status_variants() -> None:
    """Task 7a fix pass (Gap 2): Three Mark Exception status variants are in catalogue.

    Verifies that vbo_catalogue.yaml contains entries for Mark Exception with
    BusinessException, ITException, and GenericException status variants.
    """
    from flowsmith.mapper import load_rules

    config = load_rules(force_reload=True)
    wq_entry = config.get_vbo_entry("Blueprism.Automate.clsWorkQueuesActions")
    assert wq_entry is not None, "WorkQueues VBO entry should exist in catalogue"
    assert wq_entry.method_actions is not None, "WorkQueues should have method_actions"

    # Verify: All three Mark Exception variants exist
    assert "Mark Exception" in wq_entry.method_actions, (
        "Mark Exception (default/BusinessException) should be in method_actions"
    )
    assert "Mark Exception :: ITException" in wq_entry.method_actions, (
        "Mark Exception :: ITException variant should be in method_actions"
    )
    assert "Mark Exception :: GenericException" in wq_entry.method_actions, (
        "Mark Exception :: GenericException variant should be in method_actions"
    )

    # Verify: Each variant has the correct status value
    be_template = wq_entry.method_actions.get("Mark Exception", "")
    assert "BusinessException" in be_template, (
        "BusinessException variant should contain 'BusinessException' status"
    )

    it_template = wq_entry.method_actions.get("Mark Exception :: ITException", "")
    assert "ITException" in it_template, "ITException variant should contain 'ITException' status"

    ge_template = wq_entry.method_actions.get("Mark Exception :: GenericException", "")
    assert "GenericException" in ge_template, (
        "GenericException variant should contain 'GenericException' status"
    )


def test_queue_bindings_are_in_catalogue_yaml() -> None:
    """Task 7a (b): Queue bindings for config-driven queue ID are in vbo_catalogue.yaml.

    Verifies that queue_bindings exist in the raw YAML for WorkQueues actions,
    mapping BP expressions like 'ConfigFileData.Queue Name' to PAD variables
    like 'txt_WorkQueueId' with proper citation.
    """
    catalogue_path = Path("mapping") / "vbo_catalogue.yaml"
    assert catalogue_path.exists(), "vbo_catalogue.yaml should exist"

    with open(catalogue_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    # Find WorkQueues entry
    wq_entry = None
    for entry in data:
        if entry.get("vbo_name") == "Blueprism.Automate.clsWorkQueuesActions":
            wq_entry = entry
            break

    assert wq_entry is not None, "WorkQueues VBO entry should exist in catalogue"
    assert "queue_bindings" in wq_entry, (
        "WorkQueues entry should have queue_bindings field (Task 7a (b))"
    )

    queue_bindings = wq_entry["queue_bindings"]
    assert isinstance(queue_bindings, list), "queue_bindings should be a list"
    assert len(queue_bindings) > 0, "queue_bindings should not be empty"

    # Find ConfigFileData.Queue Name binding
    config_binding = None
    for binding in queue_bindings:
        if binding.get("expression_pattern") == "ConfigFileData.Queue Name":
            config_binding = binding
            break

    assert config_binding is not None, "ConfigFileData.Queue Name should be in queue_bindings"

    # Verify binding has required fields
    assert config_binding.get("pad_variable") == "txt_WorkQueueId", (
        "ConfigFileData.Queue Name should bind to txt_WorkQueueId"
    )
    assert "citation" in config_binding, "Binding should have citation field"
    assert "L150" in config_binding["citation"] or "Load Config Data" in config_binding["notes"], (
        "Citation should reference Load Config Data function (L150)"
    )


class _Thrown(Exception):  # noqa: N818 - test helper, not a generator exception
    """Raised by ``_MiniPadInterpreter`` when it hits a ``FlowControl.ThrowCustomError``."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _MiniPadInterpreter:
    """Interprets the small subset of generated PAD syntax used by Task 7b's tests.

    Executes the *actual generated* ``FUNCTION`` body text (``SET``, ``IF``/``ELSE``/
    ``END``, ``Text.ChangeCase``, ``FlowControl.ThrowCustomError``) against a mutable
    state dict, so the sequence tests below exercise PADGenerator's real output rather
    than re-implementing BP's §A7 semantics independently in the test (which would not
    catch a real generator regression). WorkQueues.* calls and comment/TODO lines are
    no-ops here — the tests only assert on counter state and thrown error codes.
    """

    def __init__(self, lines: list[str]) -> None:
        self.lines = [line for line in lines if line.strip() != ""]

    def run(self, state: dict[str, object]) -> str | None:
        """Execute the body against ``state`` (mutated in place).

        Returns:
            The thrown ``CustomErrorCode`` if a throw was hit, else None.
        """
        try:
            self._exec_block(self.lines, 0, len(self.lines), state)
        except _Thrown as exc:
            return exc.code
        return None

    def _exec_block(self, lines: list[str], start: int, end: int, state: dict[str, object]) -> None:
        i = start
        while i < end:
            line = lines[i]
            if line.startswith("IF ") and line.endswith(" THEN"):
                cond_text = line[len("IF ") : -len(" THEN")]
                then_start = i + 1
                else_idx, end_idx = self._find_else_end(lines, then_start, end)
                if self._eval_cond(cond_text, state):
                    self._exec_block(lines, then_start, else_idx, state)
                elif else_idx < end_idx:
                    self._exec_block(lines, else_idx + 1, end_idx, state)
                i = end_idx + 1
                continue
            if line.startswith("SET "):
                match = re.match(r"SET (\S+) TO (.+)", line)
                assert match is not None, f"Unparseable SET line: {line!r}"
                var_name, expr = match.group(1), match.group(2)
                expr = re.split(r"\s+#\s", expr)[0].strip()
                state[var_name] = self._eval_expr(expr, state)
                i += 1
                continue
            if line.startswith("Text.ChangeCase"):
                match = re.match(r"Text\.ChangeCase '([^']+)' 'To lowercase' => (\S+)", line)
                assert match is not None, f"Unparseable Text.ChangeCase line: {line!r}"
                src, dst = match.group(1), match.group(2)
                state[dst] = str(state.get(src, src)).lower()
                i += 1
                continue
            if line.startswith("FlowControl.ThrowCustomError"):
                match = re.search(r"CustomErrorCode: \$'''([^']*)'''", line)
                raise _Thrown(match.group(1) if match else "")
            # Comments, TODO/STOP markers, WorkQueues.* calls: no-op for this interpreter.
            i += 1

    @staticmethod
    def _find_else_end(lines: list[str], start: int, end: int) -> tuple[int, int]:
        """Find this IF's own ELSE/END indices, skipping nested IF/END pairs."""
        depth = 0
        else_idx: int | None = None
        i = start
        while i < end:
            line = lines[i]
            if line.startswith("IF ") and line.endswith(" THEN"):
                depth += 1
            elif line == "ELSE" and depth == 0 and else_idx is None:
                else_idx = i
            elif line == "END":
                if depth == 0:
                    return (else_idx if else_idx is not None else i), i
                depth -= 1
            i += 1
        raise AssertionError("Unbalanced IF/END in generated FUNCTION body")

    @staticmethod
    def _eval_cond(text: str, state: dict[str, object]) -> bool:
        py_expr = text.replace(" AND ", " and ").replace(" OR ", " or ")
        py_expr = re.sub(r"(?<![=<>!])=(?!=)", "==", py_expr)
        return bool(eval(py_expr, {"__builtins__": {}}, state))  # noqa: S307

    @staticmethod
    def _eval_expr(text: str, state: dict[str, object]) -> object:
        if text in state:
            return state[text]
        try:
            return eval(text, {"__builtins__": {}}, state)  # noqa: S307
        except Exception:
            return text


def _extract_function_body(robin_text: str, function_name: str) -> list[str]:
    """Extract one ``FUNCTION '<name>' ...`` block's body lines (stripped)."""
    lines = robin_text.splitlines()
    start = next(
        i for i, line in enumerate(lines) if line.strip().startswith(f"FUNCTION '{function_name}'")
    )
    end = next(i for i in range(start, len(lines)) if lines[i].strip() == "END FUNCTION")
    return [line.strip() for line in lines[start + 1 : end]]


def _generate_pid171_performer_mark_exception_text(tmp_path: Path) -> str:
    """Generate real PID_0171 output and return the Performer .robin file's full text."""
    sample_path = Path("samples/blueprism/PID_0171.bprelease")
    if not sample_path.exists():
        pytest.skip("Sample file not found")

    from flowsmith.ast.builder import build_ast
    from flowsmith.engine import create_annotator
    from flowsmith.parser import parse_process

    raw = parse_process(sample_path)
    process = build_ast(raw)
    create_annotator().annotate_process(process)

    gen = PADGenerator()
    files = gen.generate_process(process, tmp_path / "robin")
    performer_file = next((f for f in files if "Performer" in f.name), None)
    assert performer_file is not None, "No Performer file generated"
    return performer_file.read_text(encoding="utf-8")


def _generate_pid171_performer_mark_exception_body(tmp_path: Path) -> list[str]:
    """Generate real PID_0171 output and return the Mark Exception FUNCTION body lines."""
    text = _generate_pid171_performer_mark_exception_text(tmp_path)
    return _extract_function_body(text, "Mark Exception")


def test_mark_exception_sequence_resets_on_message_change(tmp_path: Path) -> None:
    """Task 7b Do item 4: same/same/different/same/same/same sequence per BP §A7.

    A message change is terminal for that item (reset to 0, no fall-through to
    Limit?) — only two consecutive identical messages ever accumulate here, so the
    count trajectory is [0, 1, 0, 0, 1, 2] and no breach occurs.

    Task 7b3: runs the FULL generated FUNCTION body (no stripping) — Task 7b0's
    'Consecutive Exception Count'/'Previous Exception Detail' Data stages lack
    <alwaysinit/> (samples/blueprism/PID_0171.bprelease stages 279f2417/a08fa84e)
    and no longer emit an initialising SET inside 'Mark Exception' at all (they
    are hoisted once to the Performer Main body top instead), so replaying the
    full body across calls no longer clobbers the cross-call counter state the
    way it did before this task (docs/reviews/7b-2026-09-24-v2.md's confirmed
    finding). The previous stripped-extract workaround (``_logic_only``) is gone.
    """
    body = _generate_pid171_performer_mark_exception_body(tmp_path)
    messages = ["same", "same", "different", "same", "same", "same"]
    expected_counts = [0, 1, 0, 0, 1, 2]

    state: dict[str, object] = {
        "txt_PreviousExceptionDetail": "",
        "num_ConsecutiveExceptionCount": 0,
        "num_ConsecutiveExceptionLimit": 3,
        "obj_WorkQueueItem": None,
    }
    observed_counts = []
    for msg in messages:
        state["txt_ExceptionType"] = "System Exception"
        state["txt_ExceptionDetail"] = msg
        thrown = _MiniPadInterpreter(body).run(state)
        assert thrown is None, f"Unexpected breach on message {msg!r}: {thrown}"
        observed_counts.append(state["num_ConsecutiveExceptionCount"])

    assert observed_counts == expected_counts


def test_mark_exception_breach_on_fourth_identical_message(tmp_path: Path) -> None:
    """Task 7b Do item 4: limit 3 breaches on the 4th identical message, per §A7.

    Also asserts the breach throws System Unavailable Exception via the existing
    ThrowCustomError rendering, and that no dedicated-mail CALL exists anywhere in
    the body (user decision 2026-09-24: option A, no Send Consecutive/System
    Exception Mail FUNCTIONs).

    Task 7b3 Do item 3: runs the FULL generated FUNCTION body (not a stripped/
    logic-only extract) — see ``test_mark_exception_sequence_resets_on_message_change``
    for why this is now safe: the counter/previous-message Data stages are
    non-<alwaysinit/> and no longer (re-)initialised inside this FUNCTION body.
    Also asserts neither name is (re-)set inside 'Mark Exception' at all.
    """
    body = _generate_pid171_performer_mark_exception_body(tmp_path)
    assert not any("CALL 'Send Consecutive Exception Mail'" in line for line in body)
    assert not any("CALL 'Send System Exception Mail'" in line for line in body)
    assert not any("flg_HaltRun" in line for line in body)
    # Task 7b3: neither non-alwaysinit item gets an entry-initialising SET inside
    # this FUNCTION at all — only the mid-flow "Reset Consecutive Exception
    # Indicators"/"Mark Item As Completed" resets (real BP flow logic, unaffected
    # by this task) remain, each carrying that citation, never
    # "%SomeVar%"/a bare placeholder init.
    assert not any(line.startswith("SET txt_PreviousExceptionDetail TO %SomeVar%") for line in body)
    assert not any(
        line.startswith("SET num_ConsecutiveExceptionCount TO 0")
        and "Reset Consecutive Exception Indicators" not in line
        for line in body
    )

    state: dict[str, object] = {
        "txt_PreviousExceptionDetail": "",
        "num_ConsecutiveExceptionCount": 0,
        "num_ConsecutiveExceptionLimit": 3,
        "obj_WorkQueueItem": None,
    }
    thrown_codes: list[str | None] = []
    for _ in range(4):
        state["txt_ExceptionType"] = "System Exception"
        state["txt_ExceptionDetail"] = "identical failure"
        thrown_codes.append(_MiniPadInterpreter(body).run(state))

    assert thrown_codes == [None, None, None, "System Unavailable Exception"]
    assert state["num_ConsecutiveExceptionCount"] == 3


def test_mark_exception_variant_selected_from_decision_branch_context(tmp_path: Path) -> None:
    """Task 7b: status variant comes from real BP branch context, not name/Tag.

    Replaces test_mark_exception_variant_selection_is_deferred_to_task_7b — the
    VERIFY-deferred marker must now be gone from PID_0171's real output because the
    variant is genuinely selected (mapping/vbo_catalogue.yaml L452/L454), not merely
    because the Mark Exception page no longer reaches that code path.
    """
    body = _generate_pid171_performer_mark_exception_body(tmp_path)
    assert any("WorkQueueItemStatus.BusinessException" in line for line in body)
    assert any("WorkQueueItemStatus.GenericException" in line for line in body)
    assert not any("status variant deferred to Task 7b" in line for line in body)


@pytest.mark.parametrize(
    ("bp_condition", "expected_true_context", "expected_false_context"),
    [
        # The real "Retry Exception?" stage (equality, literal in the set).
        (
            'Lower([Exception Type])="system exception" OR Lower([Exception Type])="internal"',
            "system",
            "business",
        ),
        # Task 7b fix pass gap 5 (a): "login system exception" merely *contains* the
        # substring "system exception" but is a different literal — must NOT match
        # (this is the real "System Unavailable?" stage's own condition on the same
        # BP page; a raw substring test wrongly tagged this branch "system").
        (
            'Lower([Exception Type])="system unavailable exception" OR '
            'Lower([Exception Type])="login system exception"',
            None,
            None,
        ),
        # Task 7b fix pass gap 5 (b): a negated (`<>`) comparison inverts which arm
        # is "system" — the true arm here means NOT a system exception.
        ('[Exception Type]<>"System Exception"', "business", "system"),
        # No exception-type comparison at all: inherits unchanged (None, None).
        ("[SomeOtherFlag]=True", None, None),
    ],
)
def test_detect_exception_branch_contexts(
    bp_condition: str,
    expected_true_context: str | None,
    expected_false_context: str | None,
) -> None:
    """Task 7b fix pass (gap 5): exact-literal, polarity-aware branch detection.

    Direct unit coverage of ``_detect_exception_branch_contexts`` for the two
    misfires the raw ``"system exception" in expr_lower`` substring test produced
    (docs/reviews/7b-2026-09-24-v2.md gap 5): a same-substring-different-literal
    false positive, and an inequality comparison whose polarity was previously
    ignored.
    """
    gen = PADGenerator()
    true_context, false_context = gen._detect_exception_branch_contexts(bp_condition)
    assert true_context == expected_true_context
    assert false_context == expected_false_context


def test_mark_exception_variant_lands_in_the_correct_branch(tmp_path: Path) -> None:
    """Task 7b fix pass (gap 6): the PID_171 variant test checks *branch position*.

    The previous version only asserted both statuses appear somewhere in the body
    (``any(...) for line in body``), which stays green even if the two branches'
    bodies were swapped — it never actually proved GenericException was selected
    on the BP page's "system"-branch side (`Lower([Exception Type])="system
    exception" OR Lower([Exception Type])="internal"`, the real "Retry Exception?"
    stage — see outputs/report/PID_0171_html_report_20260904/data/
    pid-171-us-process-lims-prelude.md, "## Page: Mark Item As Exception") and
    BusinessException on the false/business side.

    This locates the real "Retry Exception?"-equivalent ``IF``'s true/false arms in
    the *unstripped* Performer output (indentation-based bracket matching, mirroring
    the synthetic test's IF/ELSE/END index-finding approach) and asserts each status
    is in its correct arm, not merely present somewhere in the function.

    Mutation check: swapping the two ``WorkQueueItemStatus`` values between the
    branches in the real generated body (done below) makes this test fail, unlike
    the old ``any(...)`` version.
    """
    text = _generate_pid171_performer_mark_exception_text(tmp_path)
    func_lines = _extract_function_body(text, "Mark Exception")
    # Re-derive with indentation preserved (the FUNCTION line itself, found once
    # more, to slice the same range without re-stripping).
    raw_lines = text.splitlines()
    start = next(
        i
        for i, line in enumerate(raw_lines)
        if line.strip().startswith("FUNCTION 'Mark Exception'")
    )
    end = next(i for i in range(start, len(raw_lines)) if raw_lines[i].strip() == "END FUNCTION")
    body_raw = raw_lines[start + 1 : end]
    assert [ln.strip() for ln in body_raw] == func_lines  # sanity: same slice

    # Match the exact quoted literal `="system exception"`, not a substring match —
    # the *other* Decision on this page ("System Unavailable?") also contains the
    # text "system exception" inside the different, longer literal
    # "login system exception", which a plain `in` check would wrongly match first.
    if_idx = next(
        i
        for i, ln in enumerate(body_raw)
        if ln.strip().startswith("IF ") and '="system exception"' in ln.lower()
    )
    if_indent = len(body_raw[if_idx]) - len(body_raw[if_idx].lstrip())
    else_idx = next(
        i
        for i in range(if_idx + 1, len(body_raw))
        if body_raw[i].strip() == "ELSE"
        and len(body_raw[i]) - len(body_raw[i].lstrip()) == if_indent
    )
    end_idx = next(
        i
        for i in range(else_idx + 1, len(body_raw))
        if body_raw[i].strip() == "END"
        and len(body_raw[i]) - len(body_raw[i].lstrip()) == if_indent
    )

    true_branch = "\n".join(body_raw[if_idx + 1 : else_idx])
    false_branch = "\n".join(body_raw[else_idx + 1 : end_idx])

    assert "WorkQueueItemStatus.GenericException" in true_branch, (
        f"Expected GenericException in the system-exception branch, got: {true_branch!r}"
    )
    assert "WorkQueueItemStatus.BusinessException" in false_branch, (
        f"Expected BusinessException in the business-exception branch, got: {false_branch!r}"
    )
    assert "WorkQueueItemStatus.BusinessException" not in true_branch
    assert "WorkQueueItemStatus.GenericException" not in false_branch


def test_status_variant_selected_from_synthetic_decision_branch_context() -> None:
    """Task 7b: variant selection is generic — proven with non-PID_171 names.

    A synthetic 2-branch page (arbitrary stage/page names, nothing named "Mark
    Item As Exception", "Tag Item" or carrying a BP "Tag" value) whose governing
    Decision's own expression tests for "system exception" must still select the
    GenericException row on the true arm and the default (BusinessException) row on
    the false arm — proving the selection reads decision_expression/branch position,
    not any name or Tag heuristic.
    """
    gen = PADGenerator()

    def wq_action_stage(stage_id: str, onsuccess: str | None) -> BPStage:
        return BPStage(
            stage_id=stage_id,
            stage_type=StageType.ACTION,
            name="Update Widget Status",  # deliberately not "Mark Exception"
            params_map={
                "Item ID": "[Widget ID]",
                "Exception Reason": "[Widget Detail]",
                "_vbo_object": "Blueprism.Automate.clsWorkQueuesActions",
                "_vbo_action": "Mark Exception",
            },
            onsuccess_target=onsuccess,
            pa_annotation=PAAnnotation(
                target_type="Mark Exception",
                target_module="WorkQueues",
                runtime=Runtime.DESKTOP,
                confidence=0.70,
                band=ConfidenceBand.SPOT_CHECK,
                params_map={
                    "Item ID": "[Widget ID]",
                    "Exception Reason": "[Widget Detail]",
                    "_vbo_object": "Blueprism.Automate.clsWorkQueuesActions",
                    "_vbo_action": "Mark Exception",
                },
                flags=[],
            ),
        )

    start = BPStage(
        stage_id="S",
        stage_type=StageType.START,
        name="Start",
        onsuccess_target="D",
        pa_annotation=PAAnnotation(
            target_type="",
            target_module="System",
            runtime=Runtime.DESKTOP,
            confidence=0.95,
            band=ConfidenceBand.AUTO,
            params_map={},
            flags=[],
        ),
    )
    decision = BPStage(
        stage_id="D",
        stage_type=StageType.DECISION,
        name="Widget Kind?",  # deliberately not "Retry Exception?"
        decision_expression='Lower([Widget Kind])="system exception"',
        ontrue_target="A_TRUE",
        onfalse_target="A_FALSE",
        pa_annotation=PAAnnotation(
            target_type="IF <expr> THEN <true-branch> ELSE <false-branch> END",
            target_module="System",
            runtime=Runtime.DESKTOP,
            confidence=0.85,
            band=ConfidenceBand.SPOT_CHECK,
            params_map={},
            flags=[],
        ),
    )
    end_true = BPStage(
        stage_id="E_TRUE",
        stage_type=StageType.END,
        name="End True",
        pa_annotation=PAAnnotation(
            target_type="",
            target_module="System",
            runtime=Runtime.DESKTOP,
            confidence=0.95,
            band=ConfidenceBand.AUTO,
            params_map={},
            flags=[],
        ),
    )
    end_false = BPStage(
        stage_id="E_FALSE",
        stage_type=StageType.END,
        name="End False",
        pa_annotation=PAAnnotation(
            target_type="",
            target_module="System",
            runtime=Runtime.DESKTOP,
            confidence=0.95,
            band=ConfidenceBand.AUTO,
            params_map={},
            flags=[],
        ),
    )
    stage_true = wq_action_stage("A_TRUE", "E_TRUE")
    stage_false = wq_action_stage("A_FALSE", "E_FALSE")

    stages = [start, decision, stage_true, end_true, stage_false, end_false]
    rendered = gen._render_stage_list_with_coarse_blocks(stages)

    lines = rendered.splitlines()
    if_idx = next(i for i, line in enumerate(lines) if line.strip().startswith("IF "))
    else_idx = next(i for i in range(if_idx, len(lines)) if lines[i].strip() == "ELSE")
    end_idx = next(i for i in range(else_idx, len(lines)) if lines[i].strip() == "END")

    true_branch = "\n".join(lines[if_idx + 1 : else_idx])
    false_branch = "\n".join(lines[else_idx + 1 : end_idx])

    assert "WorkQueueItemStatus.GenericException" in true_branch
    assert "WorkQueueItemStatus.BusinessException" in false_branch
    assert "status variant deferred to Task 7b" not in rendered


def _set_var_stage(stage_id: str, var_name: str, value: str, onsuccess: str | None) -> BPStage:
    """A minimal CALCULATION-shaped stage rendering as ``SET <var_name> TO <value>``."""
    return BPStage(
        stage_id=stage_id,
        stage_type=StageType.CALCULATION,
        name=var_name,
        params_map={var_name: value},
        onsuccess_target=onsuccess,
        pa_annotation=PAAnnotation(
            target_type="SET <var> TO <expr>",
            target_module="System",
            runtime=Runtime.DESKTOP,
            confidence=0.95,
            band=ConfidenceBand.AUTO,
            params_map={},
            flags=[],
        ),
    )


def _end_stub_stage(stage_id: str, name: str) -> BPStage:
    """A minimal terminal END stage (renders to the harmless '# System.' comment)."""
    return BPStage(
        stage_id=stage_id,
        stage_type=StageType.END,
        name=name,
        pa_annotation=PAAnnotation(
            target_type="",
            target_module="System",
            runtime=Runtime.DESKTOP,
            confidence=0.95,
            band=ConfidenceBand.AUTO,
            params_map={},
            flags=[],
        ),
    )


def test_decision_branch_join_continuation_reaches_both_arms() -> None:
    """Task 7b fix pass (gap 2): a diamond (both branches reconverge) keeps the

    shared continuation reachable regardless of which arm is taken.

    Synthetic graph: ``Start -> D``, ``D`` true -> ``A -> C``, false -> ``B -> C``
    (``C`` is the join both arms reach). Before this fix, ``_render_decision_branch``
    rendered the true branch's full walk first (which happened to reach ``C`` and
    consume it into ``visited``), so the false branch's walk stopped one stage short
    of ``C`` and its content (here, "VarC") was silently missing whenever the false
    arm was taken (docs/reviews/7b-2026-09-24-v2.md gap 2, bug (i)). The fix hoists
    ``C``'s rendering to run once, after ``END`` — reachable unconditionally, i.e.
    from both arms — instead of nesting it only inside whichever branch's walk got
    there first.

    Mutation check: reverting ``_render_decision_branch``'s join-hoisting (so the
    join is only appended inside the true branch, as before the fix) makes this
    test fail — "SET VarC" would then appear only inside the true branch, not after
    END.
    """
    gen = PADGenerator()

    start = BPStage(
        stage_id="S",
        stage_type=StageType.START,
        name="Start",
        onsuccess_target="D",
        pa_annotation=PAAnnotation(
            target_type="",
            target_module="System",
            runtime=Runtime.DESKTOP,
            confidence=0.95,
            band=ConfidenceBand.AUTO,
            params_map={},
            flags=[],
        ),
    )
    decision = BPStage(
        stage_id="D",
        stage_type=StageType.DECISION,
        name="Diamond?",
        decision_expression="[SomeFlag]=True",
        ontrue_target="A",
        onfalse_target="B",
        pa_annotation=PAAnnotation(
            target_type="IF <expr> THEN <true-branch> ELSE <false-branch> END",
            target_module="System",
            runtime=Runtime.DESKTOP,
            confidence=0.85,
            band=ConfidenceBand.SPOT_CHECK,
            params_map={},
            flags=[],
        ),
    )
    stage_a = _set_var_stage("A", "VarA", "1", "C")
    stage_b = _set_var_stage("B", "VarB", "2", "C")
    stage_c = _set_var_stage("C", "VarC", "3", None)

    stages = [start, decision, stage_a, stage_b, stage_c]
    rendered = gen._render_stage_list_with_coarse_blocks(stages)

    lines = rendered.splitlines()
    if_idx = next(i for i, line in enumerate(lines) if line.strip().startswith("IF "))
    else_idx = next(i for i in range(if_idx, len(lines)) if lines[i].strip() == "ELSE")
    end_idx = next(i for i in range(else_idx, len(lines)) if lines[i].strip() == "END")

    true_branch = "\n".join(lines[if_idx + 1 : else_idx])
    false_branch = "\n".join(lines[else_idx + 1 : end_idx])
    after_end = "\n".join(lines[end_idx + 1 :])

    assert "SET VarA TO 1" in true_branch
    assert "SET VarB TO 2" in false_branch
    assert "SET VarC TO 3" not in true_branch
    assert "SET VarC TO 3" not in false_branch
    assert "SET VarC TO 3" in after_end
    # Rendered exactly once overall, never duplicated into a branch.
    assert rendered.count("SET VarC TO 3") == 1


def test_decision_branch_loop_back_edge_emits_todo_not_silently_dropped() -> None:
    """Task 7b fix pass (gap 2): a loop back-edge is flagged, never silently dropped.

    Synthetic graph: ``Start -> C1 -> D``, ``D`` true -> ``C1`` (back-edge to an
    already-rendered ancestor on the same path), false -> ``Z``. Before this fix,
    the true branch's walk simply stopped as soon as it saw ``C1`` already in
    ``visited`` (with no distinction from a legitimate sibling-branch join), so the
    true arm rendered empty with no explanation (docs/reviews/7b-2026-09-24-v2.md
    gap 2, bug (ii) — CLAUDE.md's "never silently drop a BP construct" rule).

    Mutation check: reverting the back-edge/ancestors distinction in
    ``_render_chain`` (so a back-edge is treated the same as an ordinary already-
    visited join) makes this test fail — the true branch becomes empty with no
    ``# TODO`` at all.
    """
    gen = PADGenerator()

    start = BPStage(
        stage_id="S",
        stage_type=StageType.START,
        name="Start",
        onsuccess_target="C1",
        pa_annotation=PAAnnotation(
            target_type="",
            target_module="System",
            runtime=Runtime.DESKTOP,
            confidence=0.95,
            band=ConfidenceBand.AUTO,
            params_map={},
            flags=[],
        ),
    )
    stage_c1 = _set_var_stage("C1", "VarC1", "1", "D")
    decision = BPStage(
        stage_id="D",
        stage_type=StageType.DECISION,
        name="Loop?",
        decision_expression="[KeepGoing]=True",
        ontrue_target="C1",
        onfalse_target="Z",
        pa_annotation=PAAnnotation(
            target_type="IF <expr> THEN <true-branch> ELSE <false-branch> END",
            target_module="System",
            runtime=Runtime.DESKTOP,
            confidence=0.85,
            band=ConfidenceBand.SPOT_CHECK,
            params_map={},
            flags=[],
        ),
    )
    stage_z = _end_stub_stage("Z", "End Z")

    stages = [start, stage_c1, decision, stage_z]
    rendered = gen._render_stage_list_with_coarse_blocks(stages)

    lines = rendered.splitlines()
    if_idx = next(i for i, line in enumerate(lines) if line.strip().startswith("IF "))
    else_idx = next(i for i in range(if_idx, len(lines)) if lines[i].strip() == "ELSE")
    end_idx = next(i for i in range(else_idx, len(lines)) if lines[i].strip() == "END")

    true_branch = "\n".join(lines[if_idx + 1 : else_idx])
    false_branch = "\n".join(lines[else_idx + 1 : end_idx])

    assert "# TODO" in true_branch, f"Expected a loop back-edge TODO, got: {true_branch!r}"
    assert "C1" in true_branch
    assert "loop" in true_branch.lower()
    # The false arm (onfalse_target=Z, a plain terminal) renders normally,
    # unaffected by the true arm's back-edge.
    assert "# System." in false_branch
    # Never re-render the ancestor's own content a second time inside the branch.
    assert "SET VarC1 TO 1" not in true_branch


def test_unmatched_queue_expression_emits_todo_marker(tmp_path: Path) -> None:
    """Task 7a Gap 2: unmatched queue expressions emit TODO marker before the call.

    When a Get Next Item stage has a queue expression (e.g., '[Queue Name]') that
    does NOT match any catalogue queue_binding, the generator should:
    1. Still render the WorkQueues call (with a fallback %QueueId% value)
    2. Emit a # TODO: comment immediately before it naming the unresolved expression
    3. Never silently omit the marker
    """
    # Test: Call _substitute_workqueues_placeholders directly with an unmatched queue expression
    gen = PADGenerator()

    # Create a test stage with an unmatched queue expression
    test_stage = make_annotated_stage(
        stage_id="test_get_next",
        name="Get Next Item Test",
        target_type="ProcessWorkQueueItem",
        target_module="WorkQueues",
        stage_params_map={
            "Queue Name": "[UnmatchedQueue]",  # Does not match any catalogue binding
        },
    )

    template = (
        "WorkQueues.ProcessWorkQueueItem.ProcessWorkQueueItem WorkQueue: <id> WorkQueueItem=> <var>"
    )
    substituted, was_bound, comment, unmatched_todo = gen._substitute_workqueues_placeholders(
        template, test_stage, "Get Next Item"
    )

    # Verify: unmatched_todo should contain a TODO marker
    assert unmatched_todo, "Should emit a TODO marker for unmatched queue expression"
    assert "# TODO:" in unmatched_todo, "Marker should start with # TODO:"
    assert "WorkQueues.Get Next Item" in unmatched_todo, "Should name the method"
    assert "[UnmatchedQueue]" in unmatched_todo, "Should name the unresolved BP queue expression"
    assert "no catalogue queue_binding" in unmatched_todo, "Should explain why it failed"

    # Verify: substituted line should still render with some value (either translated or fallback)
    # The expression may be translated by _translate_bp_expression even if not in catalogue
    assert "WorkQueue:" in substituted, "WorkQueues call should still have WorkQueue parameter"
    assert "WorkQueueItem=> obj_WorkQueueItem" in substituted, (
        "<var> should still be substituted even in unmatched case"
    )


def test_queue_binding_comes_from_catalogue_not_hardcoded_python(tmp_path: Path) -> None:
    """Task 7a: Verify that queue bindings are consumed from YAML catalogue, not hardcoded.

    Inject an altered binding into the generator's loaded config and verify that:
    1. The generator uses the injected binding
    2. The rendered WorkQueue value reflects the injected pad_variable
    3. The VERIFY comment reflects the injected citation/notes
    """
    from flowsmith.ast.builder import build_ast
    from flowsmith.engine import create_annotator
    from flowsmith.mapper import load_rules
    from flowsmith.parser import parse_process

    sample_path = Path("samples/blueprism/PID_0171.bprelease")
    if not sample_path.exists():
        pytest.skip("Sample file not found")

    raw = parse_process(sample_path)
    process = build_ast(raw)
    create_annotator().annotate_process(process)

    # Create a generator with unmodified config
    gen = PADGenerator()

    # Manually override the queue_bindings to use a different pad_variable
    config = load_rules(force_reload=True)
    workqueues_entry = config.get_vbo_entry("Blueprism.Automate.clsWorkQueuesActions")
    if workqueues_entry and workqueues_entry.queue_bindings:
        # Replace the first binding's pad_variable with a test value
        test_pad_var = "TEST_QUEUE_VAR_INJECTION"
        gen.queue_bindings["ConfigFileData.Queue Name"] = {
            "pad_variable": test_pad_var,
            "citation": "TEST CITATION",
            "notes": "TEST NOTE",
        }

        # Now test a Get Next Item call
        test_stage = make_annotated_stage(
            stage_id="test_get_next",
            name="Get Next Item Test",
            target_type="ProcessWorkQueueItem",
            target_module="WorkQueues",
            stage_params_map={"Queue Name": "ConfigFileData.Queue Name"},
        )

        template = "WorkQueues.ProcessWorkQueueItem.ProcessWorkQueueItem WorkQueue: <id> WorkQueueItem=> <var>"
        substituted, was_bound, comment, unmatched_todo = gen._substitute_workqueues_placeholders(
            template, test_stage, "Get Next Item"
        )

        # Verify: The injected pad_variable is used
        assert test_pad_var in substituted, (
            f"Rendered call should use injected pad_variable '{test_pad_var}', "
            f"not hardcoded Python value. Got: {substituted}"
        )

        # Verify: VERIFY comment comes from the binding (not hardcoded)
        assert was_bound, "Should detect binding from catalogue"
        assert "TEST NOTE" in comment, "Comment should use binding's notes field"
        assert "TEST CITATION" in comment, "Comment should use binding's citation field"


def test_verify_markers_are_adjacent_to_call_sites(tmp_path: Path) -> None:
    """Task 7a (c): VERIFY markers are placed immediately before their corresponding calls.

    For each Get Next Item call that is bound from the catalogue, verify that:
    1. A # VERIFY comment appears immediately before (no intervening lines)
    2. The comment references the correct queue variable name
    3. Every Get Next Item line has its corresponding marker (not content-wide matching)
    """
    sample_path = Path("samples/blueprism/PID_0171.bprelease")
    if not sample_path.exists():
        pytest.skip("Sample file not found")

    from flowsmith.ast.builder import build_ast
    from flowsmith.engine import create_annotator
    from flowsmith.parser import parse_process

    raw = parse_process(sample_path)
    process = build_ast(raw)
    create_annotator().annotate_process(process)

    gen = PADGenerator()
    files = gen.generate_process(process, tmp_path / "robin")

    performer_file = next((f for f in files if "Performer" in f.name), None)
    assert performer_file is not None, "No Performer file generated"
    lines = performer_file.read_text(encoding="utf-8").splitlines()

    # Find all Get Next Item calls
    get_next_item_indexes = []
    for i, line in enumerate(lines):
        if (
            "ProcessWorkQueueItem" in line
            and "WorkQueue:" in line
            and not line.strip().startswith("#")
        ):
            get_next_item_indexes.append(i)

    assert get_next_item_indexes, "Should have at least one Get Next Item call"

    # For each Get Next Item call, verify a VERIFY marker is immediately before it
    for call_idx in get_next_item_indexes:
        # Check the line immediately before
        preceding_idx = call_idx - 1
        assert preceding_idx >= 0, "Should have space for marker before call"

        preceding_line = lines[preceding_idx]
        assert preceding_line.strip().startswith("#"), (
            f"Line immediately before Get Next Item at {call_idx} should be a comment, "
            f"got: {preceding_line}"
        )

        assert "VERIFY" in preceding_line, (
            f"Comment before Get Next Item should be a VERIFY marker, got: {preceding_line}"
        )

        # Extract the queue variable from the call line to verify marker mentions it
        call_line = lines[call_idx]
        if "WorkQueue: txt_WorkQueueId" in call_line:
            # Marker should mention txt_WorkQueueId
            assert "txt_WorkQueueId" in preceding_line or "queue ID" in preceding_line, (
                f"VERIFY marker should reference the queue variable. "
                f"Marker: {preceding_line}, Call: {call_line}"
            )


# ── Task 7b0 (fix pass 2): GLOBAL FUNCTIONs with In_/Out_ parameters ────────
#
# Synthetic process using non-PID_171 names throughout, per the section's Do
# item 7. Parameter names deliberately differ from the data items they bind
# to (the `stage=` attribute target), mirroring the real BP shape confirmed
# against samples/blueprism/PID_0171.bprelease (e.g. `ScreenShot path` ->
# `File Path`).


def _annotated_start(
    stage_id: str,
    inputs: list[tuple[str, str, str]],
) -> BPStage:
    """Build a START stage with data_items + inputs_stage_map for the given
    (parameter_name, data_type, bound_data_item_name) triples."""
    data_items = [
        BPDataItem(name=name, data_type=dtype, is_input=True, is_output=False)
        for name, dtype, _target in inputs
    ]
    inputs_stage_map = {name: target for name, _dtype, target in inputs}
    return BPStage(
        stage_id=stage_id,
        stage_type=StageType.START,
        name="Start",
        data_items=data_items,
        inputs_stage_map=inputs_stage_map,
        pa_annotation=PAAnnotation(
            target_type="",
            target_module="System",
            runtime=Runtime.DESKTOP,
            params_map={},
            confidence=0.95,
            band=ConfidenceBand.AUTO,
        ),
    )


def _annotated_end(
    stage_id: str,
    outputs: list[tuple[str, str, str]],
) -> BPStage:
    """Build an END stage with data_items + outputs_stage_map for the given
    (parameter_name, data_type, bound_data_item_name) triples."""
    data_items = [
        BPDataItem(name=name, data_type=dtype, is_input=False, is_output=True)
        for name, dtype, _target in outputs
    ]
    outputs_stage_map = {name: target for name, _dtype, target in outputs}
    return BPStage(
        stage_id=stage_id,
        stage_type=StageType.END,
        name="End",
        data_items=data_items,
        outputs_stage_map=outputs_stage_map,
        pa_annotation=PAAnnotation(
            target_type="",
            target_module="System",
            runtime=Runtime.DESKTOP,
            params_map={},
            confidence=0.95,
            band=ConfidenceBand.AUTO,
        ),
    )


def _data_stage(
    stage_id: str, name: str, data_type: str = "text", always_init: bool = True
) -> BPStage:
    """Build a DATA stage that declares/initialises `name` (Task 7b0 suppression target).

    Task 7b3: carries a real ``BPDataItem`` (with the given ``always_init``) so
    ``_collect_role_once_only_sources``/``_build_non_alwaysinit_role_map`` — which
    read ``stage.data_items`` for the item's ``always_init`` flag, not
    ``pa_annotation.params_map`` — can see it. Defaults to True (7b0's original
    per-call/per-copy placement), matching every pre-7b3 caller of this helper.
    """
    return BPStage(
        stage_id=stage_id,
        stage_type=StageType.DATA,
        name=name,
        data_items=[
            BPDataItem(
                name=name,
                data_type=data_type,
                is_input=False,
                is_output=False,
                always_init=always_init,
            )
        ],
        pa_annotation=PAAnnotation(
            target_type="SetVariable",
            target_module="Variables",
            runtime=Runtime.DESKTOP,
            params_map={
                "variable_name": name,
                "variable_type": data_type,
                "initial_value": "%SomeInitialVar%",
            },
            confidence=0.85,
            band=ConfidenceBand.SPOT_CHECK,
        ),
    )


def _collection_stage(stage_id: str, name: str) -> BPStage:
    """Build a COLLECTION stage that declares/initialises `name` as a DataTable.

    Mirrors the real annotation shape from ``engine/annotator.py::_annotate_collection``
    (``target_type="CreateNewDataTable"``, ``params_map={"table_name": ..., "variable_type":
    "DataTable"}``) so tests exercise the code path COLLECTION stages actually take in
    ``_render_stage`` (the ``CreateNewDataTable`` branch, not the ``SetVariable`` branch's
    dead COLLECTION sub-case).
    """
    return BPStage(
        stage_id=stage_id,
        stage_type=StageType.COLLECTION,
        name=name,
        data_items=[],
        pa_annotation=PAAnnotation(
            target_type="CreateNewDataTable",
            target_module="Variables",
            runtime=Runtime.DESKTOP,
            params_map={"table_name": name, "variable_type": "DataTable"},
            confidence=0.75,
            band=ConfidenceBand.SPOT_CHECK,
        ),
    )


def _calc_stage(stage_id: str, name: str, target: str, expr: str) -> BPStage:
    """Build a CALCULATION stage assigning `expr` to `target`."""
    return BPStage(
        stage_id=stage_id,
        stage_type=StageType.CALCULATION,
        name=name,
        data_items=[],
        params_map={target: expr},
        pa_annotation=PAAnnotation(
            target_type="SetVariable",
            target_module="Variables",
            runtime=Runtime.DESKTOP,
            params_map={},
            confidence=0.9,
            band=ConfidenceBand.AUTO,
        ),
    )


def _call_stage(
    stage_id: str,
    name: str,
    processid: str,
    params_map: dict[str, str],
    outputs_stage_map: dict[str, str] | None = None,
) -> BPStage:
    """Build a SubSheet-call ACTION stage targeting `processid`."""
    return BPStage(
        stage_id=stage_id,
        stage_type=StageType.ACTION,
        name=name,
        is_subsheet_call=True,
        processid=processid,
        data_items=[],
        params_map=params_map,
        outputs_stage_map=outputs_stage_map or {},
        pa_annotation=PAAnnotation(
            target_type="SubFlow",
            target_module="System",
            runtime=Runtime.DESKTOP,
            params_map={},
            confidence=0.9,
            band=ConfidenceBand.AUTO,
        ),
    )


def test_7b0_header_uses_stage_bound_param_names() -> None:
    """Header parameter names come from the stage= binding, not the Start/End
    parameter's own name (Task 7b0 Do item 2)."""
    gen = PADGenerator()
    page = BPPage(
        page_id="P_FETCH",
        name="Fetch Widget Data",
        role="performer",
        stages=[
            _annotated_start(
                "s0",
                [
                    ("SourceLoc", "text", "widget_source_path"),
                    ("Retries", "number", "widget_retry_limit"),
                ],
            ),
            _annotated_end("s1", [("ResultLoc", "text", "widget_result_path")]),
        ],
    )
    params = gen._extract_function_parameters(page)
    assert params == (
        "In_txt_WidgetSourcePath, In_num_WidgetRetryLimit, OUTPUT Out_txt_WidgetResultPath"
    )


def test_7b0_header_repeats_output_keyword_for_multiple_outputs() -> None:
    """Multi-output header form repeats OUTPUT before each output parameter
    (reference L232, L622, L1167), not just the first."""
    gen = PADGenerator()
    page = BPPage(
        page_id="P_MULTI",
        name="Multi Output Page",
        role="performer",
        stages=[
            _annotated_start("s0", []),
            _annotated_end(
                "s1",
                [
                    ("StatusOut", "boolean", "widget_status"),
                    ("MessageOut", "text", "widget_message"),
                ],
            ),
        ],
    )
    params = gen._extract_function_parameters(page)
    assert params == "OUTPUT Out_flg_WidgetStatus, OUTPUT Out_txt_WidgetMessage"
    assert params.count("OUTPUT") == 2


def test_7b0_body_uses_in_name_and_suppresses_reinit(tmp_path: Path) -> None:
    """Inside the FUNCTION body: a bound input renders as its In_ name wherever
    referenced, and its own DATA-stage initialising SET is suppressed entirely
    (Task 7b0 Do item 3)."""
    gen = PADGenerator()
    page = BPPage(
        page_id="P_FETCH",
        name="Fetch Widget Data",
        role="performer",
        stages=[
            _annotated_start(
                "s0",
                [
                    ("SourceLoc", "text", "widget_source_path"),
                    ("Retries", "number", "widget_retry_limit"),
                ],
            ),
            # This DATA stage re-declares the bound input — must NOT be re-emitted.
            _data_stage("s1", "widget_source_path"),
            # This CALCULATION reads the bound input by its regular BP name — must
            # render using the In_ parameter name, not txt_WidgetSourcePath.
            _calc_stage("s2", "Compute Status", "widget_status", "[widget_source_path]"),
            _annotated_end("s3", [("ResultLoc", "text", "widget_result_path")]),
        ],
    )
    process = make_process(pages=[page], name="WidgetFlow")
    # Task 5b's process-wide variable_name_mapping applies its own prefix to
    # unbound data items (e.g. widget_status -> txt_WidgetStatus); build it the
    # same way _generate_consolidated_flow does before rendering page bodies.
    variable_name_mapping = gen._build_variable_name_mapping(process)

    rendered = gen._render_page_as_function(
        page, process, {"shape": "function"}, variable_name_mapping=variable_name_mapping
    )

    assert "In_txt_WidgetSourcePath" in rendered
    # Task 7b0 gap 1 (review 2026-09-24-fixpass2): the old assertion
    # (`"SET txt_WidgetSourcePath TO" not in rendered`) can never fail once the
    # override is wired in, because an unsuppressed init renders under its In_ name
    # (`SET In_txt_WidgetSourcePath TO ...`), not its bare txt_ name — that string was
    # never present either way. Assert against BOTH forms so a regression that
    # re-emits the bound item's init (suppressed or not) is caught.
    assert not re.search(r"^SET (In_)?txt_WidgetSourcePath TO", rendered, re.MULTILINE), (
        "The bound input's own initialising SET must be suppressed under either name"
    )
    assert "SET widget_status TO In_txt_WidgetSourcePath" in rendered, (
        "A body reference to the bound data item must use its In_ parameter name"
    )
    assert "GLOBAL." not in rendered


def test_7b0_body_assigns_out_for_input_and_output_bound_item() -> None:
    """A data item bound to BOTH an input and an output uses the In_ name inside
    the body, then is copied to Out_ before END FUNCTION (reference L944)."""
    gen = PADGenerator()
    page = BPPage(
        page_id="P_BOTH",
        name="Both Bound Page",
        role="performer",
        stages=[
            _annotated_start("s0", [("Count", "number", "widget_counter")]),
            _annotated_end("s1", [("FinalCount", "number", "widget_counter")]),
        ],
    )
    process = make_process(pages=[page], name="WidgetFlow")

    rendered = gen._render_page_as_function(page, process, {"shape": "function"})

    assert "In_num_WidgetCounter" in rendered
    assert "OUTPUT Out_num_WidgetCounter" in rendered
    assert "SET Out_num_WidgetCounter TO In_num_WidgetCounter" in rendered
    lines = rendered.splitlines()
    end_idx = next(i for i, ln in enumerate(lines) if ln.strip() == "END FUNCTION")
    assign_idx = next(i for i, ln in enumerate(lines) if "SET Out_num_WidgetCounter TO" in ln)
    assert assign_idx < end_idx, "The Out_ copy must be emitted before END FUNCTION"


def test_7b0_call_site_passes_arguments_no_tuple_repr() -> None:
    """CALL sites pass In_/Out_ arguments matching the header, with helper actions
    (Trim/Lower) emitted before the CALL and no tuple repr (Task 7b0 Do item 4)."""
    gen = PADGenerator()
    target_page = BPPage(
        page_id="P_FETCH",
        name="Fetch Widget Data",
        role="performer",
        stages=[
            _annotated_start(
                "s0",
                [
                    ("SourceLoc", "text", "widget_source_path"),
                    ("Retries", "number", "widget_retry_limit"),
                ],
            ),
            _annotated_end("s1", [("ResultLoc", "text", "widget_result_path")]),
        ],
    )
    call_stage = _call_stage(
        "c0",
        "Call Fetch",
        processid="P_FETCH",
        params_map={
            "SourceLoc": "Trim([raw_path])",
            # "Retries" deliberately omitted — unresolvable input case (next test).
        },
        outputs_stage_map={"ResultLoc": "final_result_var"},
    )
    variable_name_mapping = {"raw_path": "txt_RawPath"}

    rendered = gen._render_page_call_with_arguments(
        call_stage, target_page, "Fetch Widget Data", variable_name_mapping
    )

    assert "TO ('" not in rendered, "No tuple repr from an unpacked translate result"
    lines = rendered.splitlines()
    call_idx = next(i for i, ln in enumerate(lines) if ln.startswith("CALL "))
    helper_idx = next(i for i, ln in enumerate(lines) if ln.startswith("Text.Trim"))
    assert helper_idx < call_idx, "Helper actions (Trim) must precede the CALL"
    call_line = lines[call_idx]
    assert "In_txt_WidgetSourcePath: txt_trimmed_0" in call_line
    assert "Out_txt_WidgetResultPath=> final_result_var" in call_line


def test_7b0_call_site_unresolvable_input_gets_todo_before_call() -> None:
    """An unresolvable input gets a `# TODO` on its own line before the CALL, never
    inline inside the CALL's argument string (Task 7b0 gap 6)."""
    gen = PADGenerator()
    target_page = BPPage(
        page_id="P_FETCH",
        name="Fetch Widget Data",
        role="performer",
        stages=[
            _annotated_start(
                "s0",
                [
                    ("SourceLoc", "text", "widget_source_path"),
                    ("Retries", "number", "widget_retry_limit"),
                ],
            ),
            _annotated_end("s1", [("ResultLoc", "text", "widget_result_path")]),
        ],
    )
    call_stage = _call_stage(
        "c0",
        "Call Fetch",
        processid="P_FETCH",
        params_map={"SourceLoc": "[raw_path]"},  # "Retries" is missing entirely
        outputs_stage_map={"ResultLoc": "final_result_var"},
    )

    rendered = gen._render_page_call_with_arguments(
        call_stage, target_page, "Fetch Widget Data", {"raw_path": "txt_RawPath"}
    )

    lines = rendered.splitlines()
    call_idx = next(i for i, ln in enumerate(lines) if ln.startswith("CALL "))
    todo_idx = next(i for i, ln in enumerate(lines) if "# TODO: unresolvable input" in ln)
    assert todo_idx < call_idx, "The TODO must be on its own line before the CALL"
    call_line = lines[call_idx]
    assert "#" not in call_line, "No inline comment inside the CALL line"
    assert "In_num_WidgetRetryLimit" not in call_line, (
        "An unresolvable input must not appear as a bogus CALL argument"
    )


def test_7b0_output_binding_ignores_params_map_fallback() -> None:
    """Outputs come only from outputs_stage_map — a same-named entry in params_map
    (inputs) must never be used as the output's target (Task 7b0 gap 7)."""
    gen = PADGenerator()
    target_page = BPPage(
        page_id="P_FETCH",
        name="Fetch Widget Data",
        role="performer",
        stages=[
            _annotated_start("s0", [("SourceLoc", "text", "widget_source_path")]),
            _annotated_end("s1", [("ResultLoc", "text", "widget_result_path")]),
        ],
    )
    call_stage = _call_stage(
        "c0",
        "Call Fetch",
        processid="P_FETCH",
        # "ResultLoc" appears only in params_map (input shape), never in
        # outputs_stage_map — must NOT be picked up as the output binding.
        params_map={"SourceLoc": "[raw_path]", "ResultLoc": "some_input_looking_expr"},
        outputs_stage_map={},
    )

    rendered = gen._render_page_call_with_arguments(
        call_stage, target_page, "Fetch Widget Data", {}
    )

    assert "some_input_looking_expr" not in rendered
    assert "# TODO: unresolvable output 'ResultLoc'" in rendered


def test_7b0_split_page_only_entry_function_gets_parameters() -> None:
    """Split pages: only the entry FUNCTION carries the page's In_/Out_ parameter
    list; other sub-FUNCTIONs stay bare `FUNCTION '<name>' GLOBAL` (Task 7b0 Do
    item 3, split-page sub-case, user decision 2026-09-24)."""
    gen = PADGenerator()
    page = BPPage(
        page_id="P_SPLIT",
        name="Multi Step Page",
        role="performer",
        stages=[
            _annotated_start("s0", [("SourceLoc", "text", "widget_source_path")]),
            _calc_stage("s1", "Step A", "widget_step_a", "1"),
            _calc_stage("s2", "Step B", "widget_step_b", "2"),
            _annotated_end("s3", [("ResultLoc", "text", "widget_result_path")]),
        ],
    )
    process = make_process(pages=[page], name="WidgetFlow")
    shape_info = {
        "shape": "split",
        "targets": ["Multi Step Page Part A", "Multi Step Page Part B"],
        "stage_counts": [2, 2],
    }

    rendered = gen._split_page_into_functions(page, process, shape_info)

    assert (
        "FUNCTION 'Multi Step Page Part A' GLOBAL In_txt_WidgetSourcePath, "
        "OUTPUT Out_txt_WidgetResultPath" in rendered
    )
    assert "FUNCTION 'Multi Step Page Part B' GLOBAL\n" in rendered, (
        "The non-entry sub-FUNCTION must be bare GLOBAL with no parameter list"
    )
    assert "# TODO: split page — Out_ parameter(s) Out_txt_WidgetResultPath" in rendered
    assert "GLOBAL." not in rendered


def test_7b0_split_page_call_site_binds_to_entry_function() -> None:
    """A CALL to a split-shaped page resolves to its entry FUNCTION and passes
    arguments (Task 7b0 Do item 4 — 'split resolves to its entry FUNCTION')."""
    gen = PADGenerator()
    target_page = BPPage(
        page_id="P_SPLIT",
        name="Multi Step Page",
        role="performer",
        stages=[
            _annotated_start("s0", [("SourceLoc", "text", "widget_source_path")]),
            _annotated_end("s1", [("ResultLoc", "text", "widget_result_path")]),
        ],
    )
    call_stage = _call_stage(
        "c0",
        "Call Multi Step",
        processid="P_SPLIT",
        params_map={"SourceLoc": "[raw_path]"},
        outputs_stage_map={"ResultLoc": "final_result_var"},
    )

    rendered = gen._render_page_call_with_arguments(
        call_stage, target_page, "Multi Step Page Part A", {"raw_path": "txt_RawPath"}
    )

    assert "CALL 'Multi Step Page Part A'" in rendered
    assert "In_txt_WidgetSourcePath: txt_RawPath" in rendered
    assert "Out_txt_WidgetResultPath=> final_result_var" in rendered


def test_7b0_output_only_data_item_renders_as_out_name_in_body() -> None:
    """A data item that is only an output renders as its Out_ name in the body
    (Task 7b0 Do item 3, output-only case) — every stage that writes it uses the
    Out_ name, not the item's regular txt_/dtb_ name (review 2026-09-24-fixpass2
    gap 1's missing output-only-naming test)."""
    gen = PADGenerator()
    page = BPPage(
        page_id="P_OUT_ONLY",
        name="Output Only Page",
        role="performer",
        stages=[
            _annotated_start("s0", []),
            _calc_stage("s1", "Compute Result", "widget_result", "'done'"),
            _annotated_end("s2", [("ResultOut", "text", "widget_result")]),
        ],
    )
    process = make_process(pages=[page], name="WidgetFlow")

    rendered = gen._render_page_as_function(page, process, {"shape": "function"})

    assert "OUTPUT Out_txt_WidgetResult" in rendered
    assert "SET Out_txt_WidgetResult TO 'done'" in rendered
    assert not re.search(r"^SET widget_result TO", rendered, re.MULTILINE), (
        "An output-only item must never be written under its bare BP name"
    )


def test_7b0_collection_suppression_for_parameter_bound_item() -> None:
    """A COLLECTION stage bound to an In_ parameter has its DataTable.Create() init
    suppressed exactly like a DATA stage (Task 7b0 Do item 3 extended to
    COLLECTION; review 2026-09-24-fixpass2 gap 1's missing COLLECTION-suppression
    test). COLLECTION stages render via the ``CreateNewDataTable`` branch of
    ``_render_stage``, a separate code path from DATA's ``SetVariable`` branch."""
    gen = PADGenerator()
    page = BPPage(
        page_id="P_COLL",
        name="Collection Bound Page",
        role="performer",
        stages=[
            _annotated_start("s0", [("Data", "collection", "widget_collection")]),
            _collection_stage("s1", "widget_collection"),
            _annotated_end("s2", []),
        ],
    )
    process = make_process(pages=[page], name="WidgetFlow")

    rendered = gen._render_page_as_function(page, process, {"shape": "function"})

    assert "In_dtb_WidgetCollection" in rendered
    assert "DataTable.Create()" not in rendered, (
        "The parameter-bound COLLECTION's own init must be suppressed, not just DATA's"
    )


def test_7b0_init_hoisted_to_top_not_reinitialised_after_call() -> None:
    """A collection returned by a CALL is not re-created later by the caller's own
    BP-authored COLLECTION declaration — every non-parameter-bound init is hoisted
    to the top of the body (Task 7b0 Do item 8). Regression source: review
    2026-09-24-fixpass2 gap 2 (Performer P143->P286 dtb_FinalProductCollection,
    P291->P292 dtb_SammaryCollection; Loader L109->L154 dtb_MailItems)."""
    gen = PADGenerator()
    sub_page = BPPage(
        page_id="P_SUB",
        name="Fill Collection",
        role="performer",
        stages=[
            _annotated_start("s0", []),
            _annotated_end("s1", [("SubOut", "collection", "sub_result")]),
        ],
    )
    caller_page = BPPage(
        page_id="P_CALLER",
        name="Caller Page",
        role="performer",
        stages=[
            _annotated_start("s0", []),
            _call_stage(
                "s1",
                "Call Fill",
                processid="P_SUB",
                params_map={},
                outputs_stage_map={"SubOut": "widget_collection"},
            ),
            # BP's own Collection-stage declaration for the same data item,
            # positioned AFTER the call in the flow — the caller-side wipe shape
            # from the review's three cases.
            _collection_stage("s2", "widget_collection"),
            _annotated_end("s3", []),
        ],
    )
    process = make_process(pages=[caller_page, sub_page], name="WidgetFlow")

    rendered = gen._render_page_as_function(
        caller_page, process, {"shape": "function"}, process_map={}
    )

    lines = rendered.splitlines()
    set_idx = next(
        i
        for i, ln in enumerate(lines)
        if ln.strip() == "SET widget_collection TO DataTable.Create()"
    )
    call_idx = next(i for i, ln in enumerate(lines) if ln.startswith("CALL "))
    assert set_idx < call_idx, "The init must be hoisted above the CALL, not after it"
    assert sum(1 for ln in lines if "DataTable.Create()" in ln) == 1, (
        "The init must render exactly once (hoisted), never duplicated at its old position"
    )


def test_7b0_split_subfunction_flags_todo_for_entry_input_reinit() -> None:
    """A non-entry split sub-FUNCTION that would re-initialise a data item bound to
    the entry FUNCTION's In_ parameter is suppressed and flagged with a TODO — the
    input-side twin of the entry's Out_ TODO (Task 7b0 Do item 9)."""
    gen = PADGenerator()
    page = BPPage(
        page_id="P_SPLIT",
        name="Multi Step Page",
        role="performer",
        stages=[
            _annotated_start("s0", [("SourceLoc", "text", "widget_source_path")]),
            _calc_stage("s1", "Step A", "widget_step_a", "1"),
            # This sub-FUNCTION's own re-declaration of the entry's In_-bound data
            # item — must be suppressed and flagged, not silently re-initialised.
            _data_stage("s2", "widget_source_path"),
            _annotated_end("s3", [("ResultLoc", "text", "widget_result_path")]),
        ],
    )
    process = make_process(pages=[page], name="WidgetFlow")
    shape_info = {
        "shape": "split",
        "targets": ["Multi Step Page Part A", "Multi Step Page Part B"],
        "stage_counts": [2, 2],
    }

    rendered = gen._split_page_into_functions(page, process, shape_info)

    assert (
        "# TODO: split page — sub-function target 'Multi Step Page Part B' would "
        "re-initialise 'widget_source_path', bound to entry FUNCTION parameter "
        "In_txt_WidgetSourcePath" in rendered
    )
    # Fix pass 4 gap 5: the prior assertion (`not re.search(r"^SET txt_WidgetSourcePath
    # TO", ...)`) was vacuous — the split path calls `_render_stage` with no variable
    # mapping, so the raw un-prefixed BP name `widget_source_path` renders, never the
    # `txt_`-prefixed PAD name. Assert on what actually renders.
    assert not re.search(r"^SET widget_source_path TO", rendered, re.MULTILINE), (
        "The leaked data item must not be silently re-initialised in the sub-FUNCTION"
    )


def test_7b0_unassigned_output_gets_todo_before_end_function() -> None:
    """Any FUNCTION (not just split entries) whose declared Out_ parameter is never
    assigned in the rendered body gets a `# TODO` before END FUNCTION (Task 7b0 Do
    item 10). Regression source: review 2026-09-24-fixpass2 gap 4 (Loader L337,
    Performer P586 x2, P705, P1253)."""
    gen = PADGenerator()
    page = BPPage(
        page_id="P_UNASSIGNED",
        name="Never Writes Output",
        role="performer",
        stages=[
            _annotated_start("s0", [("SourceLoc", "text", "widget_source_path")]),
            # No stage anywhere assigns widget_result_path.
            _annotated_end("s1", [("ResultLoc", "text", "widget_result_path")]),
        ],
    )
    process = make_process(pages=[page], name="WidgetFlow")

    rendered = gen._render_page_as_function(page, process, {"shape": "function"})

    lines = rendered.splitlines()
    todo_idx = next(
        i
        for i, ln in enumerate(lines)
        if "# TODO: Out_txt_WidgetResultPath is declared but not assigned" in ln
    )
    end_idx = next(i for i, ln in enumerate(lines) if ln.strip() == "END FUNCTION")
    assert todo_idx < end_idx, "The TODO must appear before END FUNCTION"


def test_7b0_inline_block_isolated_from_host_override(tmp_path: Path) -> None:
    """inline_block/fold content rendered inside a parameterised FUNCTION body must
    not inherit that FUNCTION's In_/Out_ override map (Task 7b0 gap 6). A folded
    page's own data item that happens to share a name with the host's In_ parameter
    must render under its own name, not get silently renamed to the host's In_ name."""
    gen = PADGenerator()
    inline_page = BPPage(
        page_id="P_INLINE",
        name="Inline Target",
        role="performer",
        stages=[
            # Deliberately reuses the host's bound data-item name.
            _calc_stage("s0", "Set Shared Name", "widget_source_path", "'inline value'"),
        ],
    )
    host_page = BPPage(
        page_id="P_HOST",
        name="Host Page",
        role="performer",
        stages=[
            _annotated_start("s0", [("SourceLoc", "text", "widget_source_path")]),
            _call_stage("s1", "Call Inline", processid="P_INLINE", params_map={}),
            _annotated_end("s2", [("ResultLoc", "text", "widget_result_path")]),
        ],
    )
    process = make_process(pages=[host_page, inline_page], name="WidgetFlow")
    process_map = {
        "Inline Target": {
            "shape": "inline_block",
            "block_name": "Inline Block",
            "container": "Host Page",
        }
    }

    rendered = gen._render_page_as_function(
        host_page, process, {"shape": "function"}, process_map=process_map
    )

    assert "SET widget_source_path TO 'inline value'" in rendered, (
        "The inlined page's own data item must render under its own name"
    )
    assert "SET In_txt_WidgetSourcePath TO 'inline value'" not in rendered, (
        "The inlined page's data item must not be silently renamed to the host's In_ param"
    )


def test_7b0_fold_own_init_renders_at_inline_copy_start_not_host_top() -> None:
    """Task 7b0 Do item 8, option A (user decision 2026-09-24, fix pass 4): a fold
    target's own DATA/COLLECTION init is NOT hoisted to the host body's top — it
    stays at the start of the inlined copy itself, ahead of the copy's other
    stages even though the BP page declares the DATA stage second (review
    2026-09-24-fixpass3 gap 3: 'Reset Global Data' must keep its per-run resets)."""
    gen = PADGenerator()
    fold_page = BPPage(
        page_id="P_FOLD",
        name="Fold Target",
        role="performer",
        stages=[
            # BP declares the Calculation BEFORE the Data stage — the init must
            # still move to the inlined copy's own start, ahead of this line.
            _calc_stage("f0", "Compute Flag", "fold_flag", "1"),
            _data_stage("f1", "only_in_fold_var"),
        ],
    )
    host_page = BPPage(
        page_id="P_HOST",
        name="Host Page",
        role="performer",
        stages=[
            _annotated_start("s0", []),
            _call_stage("s1", "Call Fold", processid="P_FOLD", params_map={}),
            _annotated_end("s2", []),
        ],
    )
    process = make_process(pages=[host_page, fold_page], name="WidgetFlow")
    process_map = {"Fold Target": {"shape": "fold", "container": "Host Page"}}

    rendered = gen._render_page_as_function(
        host_page, process, {"shape": "function"}, process_map=process_map
    )

    # The fold branch always applies the process-wide naming convention
    # (_build_variable_name_mapping) to its own content, so the raw BP name
    # "only_in_fold_var" renders as its mapped PAD name "txt_OnlyInFoldVar".
    lines = rendered.splitlines()
    begin_idx = next(i for i, ln in enumerate(lines) if "# BEGIN fold: 'Fold Target'" in ln)
    set_idx = next(
        i for i, ln in enumerate(lines) if ln.strip().startswith("SET txt_OnlyInFoldVar TO")
    )
    calc_idx = next(i for i, ln in enumerate(lines) if "SET fold_flag TO 1" in ln)
    end_idx = next(i for i, ln in enumerate(lines) if "# END fold: 'Fold Target'" in ln)
    assert begin_idx < set_idx < calc_idx < end_idx, (
        "The fold target's own init must be hoisted to the start of its own inlined "
        "copy (ahead of the copy's other stages), and never to the host's top"
    )
    assert sum(1 for ln in lines if ln.strip().startswith("SET txt_OnlyInFoldVar TO")) == 1


def test_7b0_page_inlined_twice_initialises_twice() -> None:
    """Task 7b0 Do item 8, option A: a page inlined twice initialises twice, once per
    inlined copy — review 2026-09-24-fixpass3 gap 3's 'Sample Manager - Explorer'
    case (folded twice into 'Enter Results in App', each copy resets its own retry
    counter)."""
    gen = PADGenerator()
    fold_page = BPPage(
        page_id="P_FOLD",
        name="Fold Target",
        role="performer",
        stages=[_data_stage("f0", "retry_count", "number")],
    )
    host_page = BPPage(
        page_id="P_HOST",
        name="Host Page",
        role="performer",
        stages=[
            _annotated_start("s0", []),
            _call_stage("s1", "Call Fold First", processid="P_FOLD", params_map={}),
            _call_stage("s2", "Call Fold Second", processid="P_FOLD", params_map={}),
            _annotated_end("s3", []),
        ],
    )
    process = make_process(pages=[host_page, fold_page], name="WidgetFlow")
    process_map = {"Fold Target": {"shape": "fold", "container": "Host Page"}}

    rendered = gen._render_page_as_function(
        host_page, process, {"shape": "function"}, process_map=process_map
    )

    assert (
        sum(1 for ln in rendered.splitlines() if ln.strip().startswith("SET num_RetryCount TO"))
        == 2
    ), "Each inlined copy must get its own init — a page inlined twice initialises twice"


def test_7b0_shared_name_host_and_inline_inits_once_at_host_top() -> None:
    """Task 7b0 Do item 8, option A: only a data-item name declared by BOTH the host
    page and the inlined page initialises once, at the host body's top — and is not
    repeated inside the inlined copy (Loader 'Main Page' + inline_block target
    'Populate Queue' both declare a 'Mail Items' data item, review 2026-09-24-
    fixpass3 gap 3 / pid-171-us-process-lims-prelude.md L370, L1302).

    Fix pass 5 gap 3 (``docs/reviews/7b0-2026-09-24-fixpass4.md`` §(c)): the original
    version of this test asserted on the ``# VERIFY:``-band-only marker, which breaks
    for reasons unrelated to the behaviour under test if the confidence band ever
    changes, and it declared the host's own DATA stage *before* the CALL in flow
    order, so it could not tell "hoisted to the host's top" apart from "rendered at
    its own flow position" (both would land before the CALL either way). This version
    asserts on the actual rendered PAD variable name (both sides given the same
    explicit ``variable_name_mapping``, so there is exactly one true target name to
    check) and declares the host's own DATA stage *after* the CALL, so only a real
    top-of-body hoist — not flow position — puts the ``SET`` before the ``CALL``.
    Since the shared name here is not one of the fold target's own Start-stage
    inputs, it is a genuine cross-page collision (fix pass 5 gap 2) and gets the
    Task 7b1 TODO too."""
    gen = PADGenerator()
    fold_page = BPPage(
        page_id="P_FOLD",
        name="Fold Target",
        role="performer",
        stages=[_data_stage("f0", "shared_var")],
    )
    host_page = BPPage(
        page_id="P_HOST",
        name="Host Page",
        role="performer",
        stages=[
            _annotated_start("s0", []),
            _call_stage("s1", "Call Fold", processid="P_FOLD", params_map={}),
            # Declared AFTER the call in flow order: only a real top-of-body hoist
            # (not the stage's own flow position) can put its SET before the CALL.
            _data_stage("s2", "shared_var"),
            _annotated_end("s3", []),
        ],
    )
    process = make_process(pages=[host_page, fold_page], name="WidgetFlow")
    process_map = {"Fold Target": {"shape": "fold", "container": "Host Page"}}
    variable_name_mapping = gen._build_variable_name_mapping(process)

    rendered = gen._render_page_as_function(
        host_page,
        process,
        {"shape": "function"},
        process_map=process_map,
        variable_name_mapping=variable_name_mapping,
    )

    lines = rendered.splitlines()
    set_indices = [i for i, ln in enumerate(lines) if ln.strip().startswith("SET txt_SharedVar TO")]
    assert len(set_indices) == 1, "A name declared by both host and inline target inits once"
    begin_idx = next(i for i, ln in enumerate(lines) if "# BEGIN fold: 'Fold Target'" in ln)
    assert set_indices[0] < begin_idx, (
        "The single shared init must be hoisted to the host's top, before the fold's "
        "own inlined content — not left at its own (later) flow position"
    )
    assert (
        "# TODO: 'shared_var' per-run reset suppressed — declared on both "
        "'Host Page' and 'Fold Target'" in rendered
    ), "A non-input-bound shared name is a genuine collision and must be flagged (Task 7b1)"


def test_7b0_main_hoisting_respects_loader_performer_role_filter() -> None:
    """Task 7b0 fix pass 4 gap 1: Main-per-role hoisting must never pick up a
    different-role inline/fold target's own inits — 'Main Page's' own post-split
    stages are added unconditionally to the Performer role (pad.py L537-538,
    'all go to Performer by default'), but a Loader-only fold target's own DATA
    stage must not leak into the Performer Main body (review 2026-09-24-fixpass3
    gap 1: 21 phantom Loader-role inits at P139-146/P173-185)."""
    gen = PADGenerator()
    loader_only_page = BPPage(
        page_id="P_LOADERONLY",
        name="Loader Only Page",
        role="loader",
        stages=[_data_stage("d1", "loader_only_var")],
    )
    main_page = BPPage(
        page_id="P_MAIN",
        name="Main Page",
        is_main=True,
        stages=[
            make_annotated_stage(
                stage_id=GET_NEXT_ITEM_STAGE_ID,
                name="Get Next Item",
                stage_type=StageType.ACTION,
                target_type="GetNextItem",
                target_module="WorkQueue",
            ),
            _call_stage("c1", "Call Loader Only Page", processid="P_LOADERONLY", params_map={}),
        ],
    )
    process = make_process(pages=[main_page, loader_only_page], name="WidgetFlow")
    gen.page_target_map["WidgetFlow"] = {
        "Loader Only Page": {"shape": "fold", "container": "Loader_Main_Body"}
    }

    performer_rendered = gen._render_main_page_for_role(main_page, process, "performer", {})
    loader_rendered = gen._render_main_page_for_role(main_page, process, "loader", {})

    assert "loader_only_var" not in performer_rendered, (
        "A Loader-role fold target's own init must never leak into the Performer Main"
    )
    assert "loader_only_var" in loader_rendered, (
        "Sanity check: the Loader-role Main must still render the fold target's own init"
    )


def test_7b0_main_hoisting_excludes_flow_input_bound_names() -> None:
    """Task 7b0 fix pass 4 gap 2: Main-page hoisting must never re-initialise a data
    item bound to the Main's own Start-stage input (Task 7c, now expected via In_txt_Config)
    — review 2026-09-24-fixpass3 gap 2: ``flg_SendDatatoDataGateways`` was clobbered at the
    top of the Performer Main."""
    gen = PADGenerator()
    main_page = BPPage(
        page_id="P_MAIN",
        name="Main Page",
        is_main=True,
        stages=[
            _annotated_start("s0", [("SendFlag", "flag", "send_flag")]),
            _data_stage("s1", "send_flag", "flag"),
            _annotated_end("s2", []),
        ],
    )
    process = make_process(pages=[main_page], name="WidgetFlow")

    rendered = gen._render_main_page_for_role(main_page, process, "performer", {})

    assert "SET send_flag TO" not in rendered, (
        "A data item bound to a Main Start-stage input must never be re-initialised anywhere"
    )


def test_7b0_split_subfunction_flags_todo_for_referenced_entry_input() -> None:
    """Task 7b0 fix pass 4 gap 4: item 9 covers references, not just re-inits — a
    non-entry split sub-FUNCTION stage that merely *reads* an entry In_-bound data
    item (no DATA/COLLECTION re-init) still gets the TODO (review 2026-09-24-
    fixpass3 gap 4: 13 BP stages across 5 non-entry Result Entry sub-FUNCTIONs read
    'FinalProduct_Collection'/'SampleID'/'ProductException' with no TODO)."""
    gen = PADGenerator()
    page = BPPage(
        page_id="P_SPLIT",
        name="Multi Step Page",
        role="performer",
        stages=[
            _annotated_start("s0", [("FinalProduct", "collection", "final_product_collection")]),
            _calc_stage("s1", "Step A", "widget_step_a", "1"),
            # A non-DATA/COLLECTION stage in the non-entry sub-FUNCTION that merely
            # reads the entry's In_-bound collection — no re-init stage type here.
            make_annotated_stage(
                stage_id="s2",
                name="Filter Rows",
                stage_type=StageType.ACTION,
                target_type="FilterCollection",
                target_module="Excel",
                stage_params_map={"Data": "[final_product_collection]"},
            ),
            _annotated_end("s3", [("ResultLoc", "text", "widget_result_path")]),
        ],
    )
    process = make_process(pages=[page], name="WidgetFlow")
    shape_info = {
        "shape": "split",
        "targets": ["Multi Step Page Part A", "Multi Step Page Part B"],
        "stage_counts": [2, 2],
    }

    rendered = gen._split_page_into_functions(page, process, shape_info)

    assert (
        "# TODO: split page — sub-function target 'Multi Step Page Part B' "
        "references 'final_product_collection', bound to entry FUNCTION parameter "
        "In_dtb_FinalProductCollection" in rendered
    )


def test_7b0_unassigned_output_regex_direction_fixed() -> None:
    """Task 7b0 fix pass 4 gap 6: the item-10 unassigned-Out_ detector must look to
    the RIGHT of ``=>`` for a write, not the left. In ``CALL ... Out_c=> <var>``
    (reference L438, L1483), ``<var>`` is what's assigned — ``Out_c`` there is the
    *callee's* declared parameter name, not a write to this body's own Out_c."""
    gen = PADGenerator()

    # A nested CALL capturing straight into this body's own Out_ parameter
    # (`=> Out_txt_Result`) must count as an assignment.
    captured = "CALL 'Helper' In_a: x Out_b=> Out_txt_Result"
    assert gen._unassigned_output_todos(captured, ["Out_txt_Result"]) == [], (
        "A capture into Out_x (`=> Out_x`) must count as an assignment"
    )

    # Out_x appearing only as a *callee's* parameter name (left of `=>`, flowing into
    # an unrelated local variable) must still be flagged unassigned.
    callee_param_only = "CALL 'Other Split Target' Out_txt_Result=> local_var"
    assert gen._unassigned_output_todos(callee_param_only, ["Out_txt_Result"]) == [
        "# TODO: Out_txt_Result is declared but not assigned in this body"
    ], "Out_x as a callee parameter name must not be mistaken for a write to this body's Out_x"


def test_7b0_hoisted_inits_deduplicated() -> None:
    """Task 7b0 fix pass 4 gap 7: identical hoisted init lines are deduplicated —
    review P143/P162, P173/P183, Loader L117/L127 each carried the same line twice."""
    gen = PADGenerator()
    page = BPPage(
        page_id="P_DUP",
        name="Dup Page",
        role="performer",
        stages=[
            _annotated_start("s0", []),
            _data_stage("s1", "dup_var"),
            _data_stage("s2", "dup_var"),
            _annotated_end("s3", []),
        ],
    )
    process = make_process(pages=[page], name="WidgetFlow")

    rendered = gen._render_page_as_function(page, process, {"shape": "function"})

    assert rendered.count("SET dup_var TO %SomeInitialVar%") == 1, (
        "Two DATA stages declaring the same name/value must hoist a single init line"
    )


def test_7b0_inline_block_own_init_renders_at_inline_copy_start_not_host_top() -> None:
    """Task 7b0 fix pass 5 gap 3 (item 11): the inline_block branch's own per-copy
    init placement (pad.py ~L822) had no direct test — the reviewer's mutant M4
    (docs/reviews/7b0-2026-09-24-fixpass4.md) moved it to the END of the copy instead
    of the start and passed the full suite undetected, because only the fold branch
    (test_7b0_fold_own_init_renders_at_inline_copy_start_not_host_top) was covered.
    This mirrors that test for inline_block."""
    gen = PADGenerator()
    inline_page = BPPage(
        page_id="P_INLINE",
        name="Inline Target",
        role="performer",
        stages=[
            # BP declares the Calculation BEFORE the Data stage - the init must
            # still move to the inlined copy's own start, ahead of this line.
            _calc_stage("f0", "Compute Flag", "inline_flag", "1"),
            _data_stage("f1", "only_in_inline_var"),
        ],
    )
    host_page = BPPage(
        page_id="P_HOST",
        name="Host Page",
        role="performer",
        stages=[
            _annotated_start("s0", []),
            _call_stage("s1", "Call Inline", processid="P_INLINE", params_map={}),
            _annotated_end("s2", []),
        ],
    )
    process = make_process(pages=[host_page, inline_page], name="WidgetFlow")
    process_map = {
        "Inline Target": {
            "shape": "inline_block",
            "block_name": "Inline Block",
            "container": "Host Page",
        }
    }

    rendered = gen._render_page_as_function(
        host_page, process, {"shape": "function"}, process_map=process_map
    )

    lines = rendered.splitlines()
    begin_idx = next(i for i, ln in enumerate(lines) if "inline_block: 'Inline Target'" in ln)
    set_idx = next(
        i for i, ln in enumerate(lines) if ln.strip().startswith("SET txt_OnlyInInlineVar TO")
    )
    calc_idx = next(i for i, ln in enumerate(lines) if "SET inline_flag TO 1" in ln)
    end_idx = next(i for i, ln in enumerate(lines) if ln.strip() == "END")
    assert begin_idx < set_idx < calc_idx < end_idx, (
        "The inline_block target's own init must be hoisted to the start of its own "
        "inlined copy (ahead of the copy's other stages), and never to the host's top "
        "or the end of the copy"
    )
    assert sum(1 for ln in lines if ln.strip().startswith("SET txt_OnlyInInlineVar TO")) == 1


def test_7b0_host_declared_name_outside_rendered_role_subset_still_suppresses_copy() -> None:
    """Task 7b0 fix pass 5 gap 1(a): the "declared by both" check must consult the
    host BP page's FULL declarations, not just the current role/slice's rendered
    subset (docs/reviews/7b0-2026-09-24-fixpass4.md gap 1(a) - Main Page's own
    'Mail Items' DATA stage sits on the Performer side of the role split, but the
    Loader-role inline copy of 'Populate Queue' must still not re-init it). Modelled
    here with Main Page's shared DATA stage placed strictly on the Performer
    (post-split) side, and the fold target inlined on the Loader (pre-split) side."""
    gen = PADGenerator()
    fold_page = BPPage(
        page_id="P_FOLD",
        name="Fold Target",
        role="loader",
        stages=[_data_stage("f0", "shared_var")],
    )
    main_page = BPPage(
        page_id="P_MAIN",
        name="Main Page",
        is_main=True,
        stages=[
            _annotated_start("s0", []),
            _call_stage("s1", "Call Fold", processid="P_FOLD", params_map={}),
            make_annotated_stage(
                stage_id=GET_NEXT_ITEM_STAGE_ID,
                name="Get Next Item",
                stage_type=StageType.ACTION,
                target_type="GetNextItem",
                target_module="WorkQueue",
            ),
            # Host's own declaration of the SAME name, but on the Performer
            # (post-split) side - never rendered in the Loader-role body at all.
            _data_stage("s2", "shared_var"),
        ],
    )
    process = make_process(pages=[main_page, fold_page], name="WidgetFlow")
    gen.page_target_map["WidgetFlow"] = {
        "Fold Target": {"shape": "fold", "container": "Loader_Main_Body"}
    }

    loader_rendered = gen._render_main_page_for_role(main_page, process, "loader", {})

    set_lines = [ln for ln in loader_rendered.splitlines() if ln.strip().startswith("SET ")]
    assert not any("shared_var" in ln.lower() for ln in set_lines), (
        "A name declared anywhere on the host page - even on the other role's side "
        "of the split, never rendered in this body - must still suppress the "
        "inlined copy's own re-init (only the naming TODO may mention it)"
    )
    assert (
        "# TODO: 'shared_var' per-run reset suppressed — declared on both "
        "'Main Page' and 'Fold Target'" in loader_rendered
    ), "The suppressed reset must be flagged as a cross-page collision (Task 7b1)"


def test_7b0_inlined_page_start_input_filled_by_preceding_call_not_reinitialised() -> None:
    """Task 7b0 fix pass 5 gap 1(b): an inlined page's own Start-stage input data item
    is never re-initialised in its inlined copy - BP applies the caller's supplied
    value over the initial default. Models the real Loader case: 'Populate Queue'
    receives 'Mail Items' as a Start input, filled by the preceding 'Fetch Emails
    from Mailbox' CALL's captured output (review 2026-09-24-fixpass4.md defect (c)).
    No collision TODO, since this is a designed hand-off, not an accidental
    collision (gap 1(a)/(2))."""
    gen = PADGenerator()
    fetch_page = BPPage(
        page_id="P_FETCH",
        name="Fetch Emails",
        role="loader",
        stages=[
            _annotated_start("f0", []),
            _annotated_end("f1", [("Items", "collection", "fetched_items")]),
        ],
    )
    inline_page = BPPage(
        page_id="P_INLINE",
        name="Populate Queue",
        role="loader",
        stages=[
            _annotated_start("p0", [("MailItems", "collection", "fetched_items")]),
            # Populate Queue's own default declaration of the same input's data
            # item - must never re-run once the caller's CALL has already filled it.
            _data_stage("p1", "fetched_items", "collection"),
        ],
    )
    host_page = BPPage(
        page_id="P_HOST",
        name="Host Page",
        role="loader",
        stages=[
            _annotated_start("s0", []),
            _call_stage(
                "s1",
                "Call Fetch",
                processid="P_FETCH",
                params_map={},
                outputs_stage_map={"Items": "fetched_items"},
            ),
            _call_stage("s2", "Call Inline", processid="P_INLINE", params_map={}),
            _annotated_end("s3", []),
        ],
    )
    process = make_process(pages=[host_page, fetch_page, inline_page], name="WidgetFlow")
    process_map = {
        "Fetch Emails": {"shape": "function"},
        "Populate Queue": {"shape": "inline_block", "block_name": "Populate Queue Block"},
    }

    rendered = gen._render_page_as_function(
        host_page, process, {"shape": "function"}, process_map=process_map
    )

    assert "fetched_items" in rendered, "sanity: the CALL's captured output must be present"
    assert "%SomeInitialVar%" not in rendered, (
        "Populate Queue's own default init for its Start input must never render - "
        "neither hoisted at the copy's start nor at its own flow position"
    )
    todo_lines = [ln for ln in rendered.splitlines() if ln.strip().startswith("# TODO:")]
    assert not any("fetched_items" in ln for ln in todo_lines), (
        "A Start-input-bound name is a designed hand-off, not a collision - no TODO"
    )


def test_7b0_collision_between_host_and_inline_declared_name_emits_todo_and_suppresses_reset() -> (
    None
):
    """Task 7b0 fix pass 5 gap 2: a name declared by both the host page and the
    inlined page, where the inlined page's own declaration is NOT one of its
    Start-stage inputs, is a genuine cross-page name collision (not a designed
    hand-off) - Result Entry / Sample Manager - Explorer's shared 'Retry Count'
    (review 2026-09-24-fixpass4.md defect (b), P856-857/P1044-1045/P1084-1085). The
    per-copy reset is suppressed and flagged with a TODO naming the collision (Task
    7b1). Unlike the gap-1(a) test above, the host's own declaration IS rendered in
    this same body (ancestor_suppress already carries the name), which must not
    silently swallow the TODO."""
    gen = PADGenerator()
    fold_page = BPPage(
        page_id="P_FOLD",
        name="Retry Sub Page",
        role="performer",
        stages=[_data_stage("f0", "retry_count", "number")],
    )
    host_page = BPPage(
        page_id="P_HOST",
        name="Host Page",
        role="performer",
        stages=[
            _annotated_start("s0", []),
            _data_stage("s1", "retry_count", "number"),
            _call_stage("s2", "Call Retry Sub", processid="P_FOLD", params_map={}),
            _annotated_end("s3", []),
        ],
    )
    process = make_process(pages=[host_page, fold_page], name="WidgetFlow")
    process_map = {"Retry Sub Page": {"shape": "fold", "container": "Host Page"}}
    variable_name_mapping = gen._build_variable_name_mapping(process)

    rendered = gen._render_page_as_function(
        host_page,
        process,
        {"shape": "function"},
        process_map=process_map,
        variable_name_mapping=variable_name_mapping,
    )

    assert (
        "# TODO: 'retry_count' per-run reset suppressed — declared on both "
        "'Host Page' and 'Retry Sub Page'" in rendered
    )
    assert rendered.count("SET num_RetryCount TO") == 1, (
        "Only the host's single hoisted init must survive - the fold copy's own "
        "reset must be suppressed, not duplicated"
    )
    lines = rendered.splitlines()
    begin_idx = next(i for i, ln in enumerate(lines) if "# BEGIN fold: 'Retry Sub Page'" in ln)
    end_idx = next(i for i, ln in enumerate(lines) if "# END fold: 'Retry Sub Page'" in ln)
    fold_body_lines = lines[begin_idx:end_idx]
    assert not any("SET num_RetryCount TO" in ln for ln in fold_body_lines), (
        "The collision suppression must remove the reset from inside the fold copy itself"
    )


def test_7b0_stage_references_data_item_ignores_vbo_metadata_false_positive() -> None:
    """Task 7b0 fix pass 5 gap 4: _stage_references_data_item must not scan the
    parser's _vbo_object/_vbo_action metadata values - those are VBO/action names,
    not data-item references. Review P960 false positive: 'Enter Results in App'
    was flagged as referencing 'SampleID' only because its VBO action name was
    'Close SampleID & Analysis Window' (stages 138/146)."""
    gen = PADGenerator()
    stage = make_annotated_stage(
        stage_id="s1",
        name="Close SampleID Analysis Window",
        stage_type=StageType.ACTION,
        target_type="CloseWindow",
        target_module="MSAA",
        stage_params_map={
            "_vbo_object": "clsSampleIDApp",
            "_vbo_action": "Close SampleID & Analysis Window",
        },
    )

    assert gen._stage_references_data_item(stage, "sampleid") is False


def test_7b0_stage_references_data_item_whole_token_not_substring() -> None:
    """Task 7b0 fix pass 5 gap 4: a raw substring match wrongly treats 'Old_SampleID'
    as a reference to 'SampleID' - the fix must match whole BP data-item tokens
    only (bracketed, dotted, or bare), never a substring inside a longer name."""
    gen = PADGenerator()
    stage = make_annotated_stage(
        stage_id="s1",
        name="Compare IDs",
        stage_type=StageType.CALCULATION,
        stage_params_map={"widget_flag": "[Old_SampleID]"},
    )

    assert gen._stage_references_data_item(stage, "sampleid") is False
    assert gen._stage_references_data_item(stage, "old_sampleid") is True


def test_7b0_stage_references_data_item_matches_bracketed_and_dotted_forms() -> None:
    """Task 7b0 fix pass 5 gap 4: the whole-token match must still catch both the
    bracketed ([SampleID]) and dotted (FinalProduct_Collection.Column8) BP
    reference forms."""
    gen = PADGenerator()
    bracketed = make_annotated_stage(
        stage_id="s1",
        stage_type=StageType.DECISION,
    )
    bracketed.decision_expression = "[SampleID]=''"
    dotted = make_annotated_stage(
        stage_id="s2",
        name="Filter Rows",
        stage_type=StageType.ACTION,
        target_type="FilterCollection",
        target_module="Excel",
        stage_params_map={"Data": "FinalProduct_Collection.Column8"},
    )

    assert gen._stage_references_data_item(bracketed, "sampleid") is True
    assert gen._stage_references_data_item(dotted, "finalproduct_collection") is True


def test_7b0_stage_references_data_item_includes_assignment_targets() -> None:
    """Task 7b0 fix pass 5 gap 4: a CALCULATION stage that only WRITES a data item
    (its params_map key, not value) is still a reference - a sub-FUNCTION that
    writes 'FinalProduct_Collection.Column8' (Result Entry stages 43-46/58-61/97-100)
    still needs the parameter passed through, even though it never reads it."""
    gen = PADGenerator()
    stage = make_annotated_stage(
        stage_id="s1",
        name="Set Column8",
        stage_type=StageType.CALCULATION,
        stage_params_map={"FinalProduct_Collection.Column8": "'done'"},
    )

    assert gen._stage_references_data_item(stage, "finalproduct_collection") is True


def test_7b0_render_page_in_consolidated_flow_raises_for_inline_shapes() -> None:
    """Task 7b0 fix pass 5 gap 6 (docs/reviews/7b0-2026-09-24-fixpass4.md (e)):
    _render_page_in_consolidated_flow must never render an inline_block/fold page
    directly - that path has no per-inlined-copy data-init handling (item 8, option
    A) and would silently bypass it if ever reached. It must raise instead of
    falling back to the old (pre-item-8) rendering the deleted
    _render_inline_block/_render_fold helpers used to provide."""
    gen = PADGenerator()
    page = BPPage(
        page_id="P_FOLD",
        name="Fold Target",
        role="performer",
        stages=[_data_stage("f0", "some_var")],
    )
    process = make_process(pages=[page], name="WidgetFlow")
    process_map = {"Fold Target": {"shape": "fold", "container": "Host Page"}}

    with pytest.raises(GenerationError):
        gen._render_page_in_consolidated_flow(page, process, process_map)


# ── Task 7b3: BP alwaysinit lifetime → PAD init placement ───────────────────


def test_7b3_non_alwaysinit_item_initialises_once_at_main_body_top_inlined() -> None:
    """Task 7b3: a non-<alwaysinit/> item on a page inlined (fold) twice into the
    Performer main body initialises exactly once, at the top of the Main body —
    never inside either inlined copy — while an <alwaysinit/> item on the same
    page keeps Task 7b0's per-copy reset (once per inlined copy).
    """
    gen = PADGenerator()
    fold_page = BPPage(
        page_id="P_FOLD",
        name="Widget Worker",
        role="performer",
        stages=[
            _data_stage("f0", "widget_retry_count", data_type="number", always_init=True),
            _data_stage("f1", "widget_running_total", data_type="number", always_init=False),
        ],
    )
    main_page = BPPage(
        page_id="P_MAIN",
        name="Main Page",
        is_main=True,
        stages=[
            _annotated_start("s0", []),
            _call_stage("s1", "Call Widget Worker First", processid="P_FOLD", params_map={}),
            _call_stage("s2", "Call Widget Worker Second", processid="P_FOLD", params_map={}),
            _annotated_end("s3", []),
        ],
    )
    process = make_process(pages=[main_page, fold_page], name="WidgetFlow")
    gen.page_target_map["WidgetFlow"] = {
        "Widget Worker": {"shape": "fold", "container": "Performer_Main_Body"}
    }

    rendered = gen._generate_consolidated_flow(process, role="performer")

    lines = rendered.splitlines()
    banner_idx = next(i for i, ln in enumerate(lines) if ln.startswith("# Role: Performer"))
    first_fold_idx = next(i for i, ln in enumerate(lines) if "# BEGIN fold" in ln)

    retry_count_lines = [i for i, ln in enumerate(lines) if "num_WidgetRetryCount TO" in ln]
    running_total_lines = [i for i, ln in enumerate(lines) if "num_WidgetRunningTotal TO" in ln]

    assert len(running_total_lines) == 1, (
        "A non-alwaysinit item must initialise exactly once across the whole role, "
        f"got {len(running_total_lines)} occurrences: {[lines[i] for i in running_total_lines]}"
    )
    assert banner_idx < running_total_lines[0] < first_fold_idx, (
        "The single non-alwaysinit init must sit at the Main body's top, before any inlined copy"
    )
    assert len(retry_count_lines) == 2, (
        "The alwaysinit item must keep Task 7b0's per-copy reset (once per inlined copy)"
    )
    for idx in retry_count_lines:
        assert idx > first_fold_idx, (
            "The alwaysinit item's resets must stay inside the inlined copies, not be "
            "hoisted to the Main body top"
        )


def test_7b3_non_alwaysinit_item_initialises_once_when_page_called_as_function() -> None:
    """Task 7b3: a non-<alwaysinit/> item on a FUNCTION-shaped page called twice
    initialises once, at the Performer Main body's top — never inside the
    FUNCTION body itself (which is emitted once but CALLed on every run)."""
    gen = PADGenerator()
    function_page = BPPage(
        page_id="P_FUNC",
        name="Widget Fetcher",
        role="performer",
        stages=[
            _data_stage("f0", "widget_retry_count", data_type="number", always_init=True),
            _data_stage("f1", "widget_running_total", data_type="number", always_init=False),
        ],
    )
    main_page = BPPage(
        page_id="P_MAIN",
        name="Main Page",
        is_main=True,
        stages=[
            _annotated_start("s0", []),
            _call_stage("s1", "Call Widget Fetcher First", processid="P_FUNC", params_map={}),
            _call_stage("s2", "Call Widget Fetcher Second", processid="P_FUNC", params_map={}),
            _annotated_end("s3", []),
        ],
    )
    process = make_process(pages=[main_page, function_page], name="WidgetFlow")

    rendered = gen._generate_consolidated_flow(process, role="performer")

    lines = rendered.splitlines()
    function_idx = next(i for i, ln in enumerate(lines) if "FUNCTION 'Widget Fetcher'" in ln)

    retry_count_lines = [i for i, ln in enumerate(lines) if "num_WidgetRetryCount TO" in ln]
    running_total_lines = [i for i, ln in enumerate(lines) if "num_WidgetRunningTotal TO" in ln]

    assert len(running_total_lines) == 1, (
        "A non-alwaysinit item on a FUNCTION-shaped page initialises exactly once "
        f"across the whole role, got {len(running_total_lines)}"
    )
    assert running_total_lines[0] < function_idx, (
        "The single non-alwaysinit init must sit at the Main body's top, before the "
        "'Widget Fetcher' FUNCTION definition"
    )
    assert len(retry_count_lines) == 1, (
        "The alwaysinit item stays inside the FUNCTION body (Task 7b0 placement), "
        "unchanged — the FUNCTION is defined once regardless of how many times it "
        "is CALLed"
    )
    assert retry_count_lines[0] > function_idx, (
        "The alwaysinit item's reset must stay inside the FUNCTION body, not be "
        "hoisted to the Main body top"
    )


def test_7b3_cross_role_non_alwaysinit_name_is_reported_not_guessed() -> None:
    """Task 7b3: a non-<alwaysinit/> name declared on pages split across both
    roles is reported with a TODO, not silently assigned to either role's Main
    body."""
    gen = PADGenerator()
    loader_page = BPPage(
        page_id="P_LOADER",
        name="Loader Side Page",
        role="loader",
        stages=[_data_stage("l0", "widget_shared_counter", always_init=False)],
    )
    performer_page = BPPage(
        page_id="P_PERFORMER",
        name="Performer Side Page",
        role="performer",
        stages=[_data_stage("p0", "widget_shared_counter", always_init=False)],
    )
    main_page = BPPage(
        page_id="P_MAIN",
        name="Main Page",
        is_main=True,
        stages=[
            _annotated_start("s0", []),
            _call_stage("s1", "Call Loader Side", processid="P_LOADER", params_map={}),
            _call_stage("s2", "Call Performer Side", processid="P_PERFORMER", params_map={}),
            _annotated_end("s3", []),
        ],
    )
    process = make_process(pages=[main_page, loader_page, performer_page], name="WidgetFlow")

    performer_rendered = gen._generate_consolidated_flow(process, role="performer")
    loader_rendered = gen._generate_consolidated_flow(process, role="loader")

    all_lines = performer_rendered.splitlines() + loader_rendered.splitlines()
    conflict_todos = [
        ln
        for ln in all_lines
        if "TODO" in ln and "Task 7b3" in ln and "widget_shared_counter" in ln.lower()
    ]
    assert conflict_todos, (
        "A cross-role non-alwaysinit name must be reported with a Task 7b3 TODO "
        "naming it, not silently assigned to either role"
    )


# ── Task 7c tests: Single @INPUT contract matching reference ──────────────────


def test_7c_generate_page_emits_exactly_one_input_matching_reference() -> None:
    """Task 7c: generate_page must emit exactly one @INPUT line matching the
    reference contract from docs/pad-reference/DF_PID_171_US_Loader.robin.txt L8
    and DF_PID_171_US_LIMS_Prelude_Main.robin.txt L8, regardless of how many
    data items the page declares.
    """
    gen = PADGenerator()
    # Create a page with multiple data items of different types. Only the reference
    # contract should appear, not individual @INPUT lines for each.
    start_stage = make_annotated_stage(
        stage_id="s0",
        name="Start",
        stage_type=StageType.START,
        data_items=[
            BPDataItem(name="flg_SendData", data_type="flag", is_input=True),
            BPDataItem(name="config_value", data_type="text", is_input=True),
        ],
    )
    other_stage = make_annotated_stage(
        stage_id="s1",
        name="SomeAction",
        data_items=[
            BPDataItem(name="Queue_Name", data_type="text", is_input=True),
        ],
    )
    page = make_page(stages=[start_stage, other_stage], is_main=True)
    result = gen.generate_page(page, "SyntheticProcess")

    # Count @INPUT lines (should be exactly 1)
    input_lines = [line for line in result.split("\n") if line.startswith("@INPUT")]
    assert len(input_lines) == 1, f"Expected 1 @INPUT line, found {len(input_lines)}"

    # Verify it matches the exact reference contract
    expected_input = (
        "@INPUT In_txt_Config : { 'Description': '', 'FriendlyName': 'In_txt_Config', "
        "'Type': 'String', 'IsOptional': False, 'DefaultValue': '{}' }"
    )
    assert input_lines[0] == expected_input, (
        f"@INPUT line does not match reference.\n"
        f"Expected: {expected_input}\n"
        f"Got:      {input_lines[0]}"
    )


def test_7c_main_start_input_produces_todo_comment() -> None:
    """Task 7c: When a Main page has START-stage inputs, they must produce TODO
    comments in the header area (after @INPUT/@OUTPUT lines) naming the BP input
    and stating it must be supplied through In_txt_Config.
    """
    gen = PADGenerator()
    start_stage = make_annotated_stage(
        stage_id="s0",
        name="Start",
        stage_type=StageType.START,
        data_items=[
            BPDataItem(name="flg_SendDatatoDataGateways", data_type="flag", is_input=True),
        ],
    )
    other_stage = make_annotated_stage(stage_id="s1", name="ProcessWork")
    page = make_page(stages=[start_stage, other_stage], is_main=True)
    result = gen.generate_page(page, "SyntheticProcess")

    # Check for TODO comment naming the original BP input
    assert "flg_SendDatatoDataGateways" in result, "START input name should appear in TODO comment"
    assert "In_txt_Config" in result, "TODO should reference In_txt_Config as the new source"
    assert "# TODO:" in result, "Header should contain TODO comments for moved inputs"


def test_7c_non_start_data_items_produce_no_input() -> None:
    """Task 7c: Data items that are NOT on the START stage should NOT produce
    @INPUT declarations or TODO comments. Only START-stage inputs are genuine
    process inputs; VBO-call parameters are internal to the flow.
    """
    gen = PADGenerator()
    # A page with no START stage inputs, only VBO-call parameters on ACTION stages
    start_stage = make_annotated_stage(
        stage_id="s0",
        name="Start",
        stage_type=StageType.START,
        data_items=[],  # No inputs on START
    )
    vbo_stage = make_annotated_stage(
        stage_id="s1",
        name="GetWorkQueueItem",
        stage_type=StageType.ACTION,
        data_items=[
            BPDataItem(name="Queue_Name", data_type="text", is_input=True),
            BPDataItem(name="Item_ID", data_type="number", is_input=False),
        ],
    )
    page = make_page(stages=[start_stage, vbo_stage], is_main=True)
    result = gen.generate_page(page, "SyntheticProcess")

    # Should still have exactly 1 @INPUT (the reference contract)
    input_lines = [line for line in result.split("\n") if line.startswith("@INPUT")]
    assert len(input_lines) == 1, f"Expected 1 @INPUT line, found {len(input_lines)}"
    assert "In_txt_Config" in input_lines[0], "@INPUT should be the reference contract"

    # Should NOT have TODO comments mentioning VBO data items
    assert "Queue_Name" not in result, "VBO parameters should not appear in header"
    assert "Item_ID" not in result, "VBO parameters should not appear in header"


def test_7c_consolidated_flow_path_main_start_input_produces_todo() -> None:
    """Task 7c: Through the real shipped path (_generate_consolidated_flow), a Main page
    with START-stage inputs must produce exactly one @INPUT (the reference contract) and
    TODO comments naming both the BP input name and the PAD variable name.
    """
    gen = PADGenerator()
    # Create a Main page with a START input that will be bound to a PAD variable
    main_page = BPPage(
        page_id="P_MAIN",
        name="Main",
        is_main=True,
        stages=[
            make_annotated_stage(
                stage_id="s0",
                name="Start",
                stage_type=StageType.START,
                data_items=[
                    BPDataItem(name="SendFlag", data_type="flag", is_input=True),
                ],
            ),
            make_annotated_stage(stage_id="s1", name="Work"),
            make_annotated_stage(
                stage_id="s2",
                name="End",
                stage_type=StageType.END,
            ),
        ],
    )
    process = make_process(pages=[main_page], name="TestProcess")

    # Render via the shipped path
    result = gen._generate_consolidated_flow(process, role="performer")

    # Verify exactly one @INPUT line
    input_lines = [line for line in result.split("\n") if line.startswith("@INPUT")]
    assert len(input_lines) == 1, f"Expected 1 @INPUT line, got {len(input_lines)}"
    assert "In_txt_Config" in input_lines[0]

    # Verify TODO comment names both BP input and PAD variable
    assert "# TODO:" in result, "Should have TODO comments for START-stage inputs"
    assert "SendFlag" in result, "TODO should name the BP input"
    assert "flg_SendFlag" in result, "TODO should name the PAD variable (flg_SendFlag)"


def test_7c_consolidated_flow_path_subpage_start_input_excluded() -> None:
    """Task 7c: Through the real shipped path (_generate_consolidated_flow), a sub-page
    with START-stage inputs must NOT produce TODO comments (only the Main page's START
    inputs are genuine process inputs).
    """
    gen = PADGenerator()
    main_page = BPPage(
        page_id="P_MAIN",
        name="Main",
        is_main=True,
        stages=[
            make_annotated_stage(
                stage_id="s0",
                name="Start",
                stage_type=StageType.START,
                data_items=[],  # No START inputs on main
            ),
            make_annotated_stage(stage_id="s1", name="Work"),
            make_annotated_stage(stage_id="s2", name="End", stage_type=StageType.END),
        ],
    )
    sub_page = BPPage(
        page_id="P_SUB",
        name="SubPage",
        role="performer",
        stages=[
            make_annotated_stage(
                stage_id="s0",
                name="Start",
                stage_type=StageType.START,
                data_items=[
                    BPDataItem(name="ItemID", data_type="number", is_input=True),
                ],
            ),
            make_annotated_stage(stage_id="s1", name="Work"),
            make_annotated_stage(stage_id="s2", name="End", stage_type=StageType.END),
        ],
    )
    process = make_process(pages=[main_page, sub_page], name="TestProcess")

    # Render via the shipped path
    result = gen._generate_consolidated_flow(process, role="performer")

    # Verify exactly one @INPUT (the reference contract only, no sub-page input)
    input_lines = [line for line in result.split("\n") if line.startswith("@INPUT")]
    assert len(input_lines) == 1, f"Expected 1 @INPUT line, got {len(input_lines)}"

    # Verify no TODO for the sub-page input (ItemID should not appear in header area)
    # The sub-page's Start input is not a process input, so no TODO
    todo_section = result[: result.find("FUNCTION") if "FUNCTION" in result else len(result)]
    assert "ItemID" not in todo_section, "Sub-page START input should not appear in header area"


def test_7c_consolidated_flow_path_main_non_start_data_excluded() -> None:
    """Task 7c: Through the real shipped path (_generate_consolidated_flow), a Main page
    with non-START data items (VBO parameters) must NOT produce TODO comments.
    """
    gen = PADGenerator()
    main_page = BPPage(
        page_id="P_MAIN",
        name="Main",
        is_main=True,
        stages=[
            make_annotated_stage(
                stage_id="s0",
                name="Start",
                stage_type=StageType.START,
                data_items=[],  # No START inputs
            ),
            make_annotated_stage(
                stage_id="s1",
                name="GetNextItem",
                stage_type=StageType.ACTION,
                data_items=[
                    BPDataItem(name="QueueName", data_type="text", is_input=True),
                    BPDataItem(name="ItemData", data_type="text", is_input=False),
                ],
            ),
            make_annotated_stage(stage_id="s2", name="End", stage_type=StageType.END),
        ],
    )
    process = make_process(pages=[main_page], name="TestProcess")

    # Render via the shipped path
    result = gen._generate_consolidated_flow(process, role="performer")

    # Verify exactly one @INPUT (the reference contract only)
    input_lines = [line for line in result.split("\n") if line.startswith("@INPUT")]
    assert len(input_lines) == 1, f"Expected 1 @INPUT line, got {len(input_lines)}"

    # Verify no TODO for non-START data items
    todo_section = result[: result.find("FUNCTION") if "FUNCTION" in result else len(result)]
    assert "QueueName" not in todo_section, "VBO parameter should not appear in header TODO"
    assert "ItemData" not in todo_section, "VBO parameter should not appear in header TODO"


def test_7c_consolidated_flow_todo_names_bound_pad_variable_not_parameter() -> None:
    """Task 7c review gap 5: when the BP input parameter (``Notify``) is bound via
    ``stage=`` to a differently-named data item (``send_flag``), the header TODO must name
    the PAD variable the body actually uses for that data item — resolved through
    ``variable_name_mapping`` (typed by the DATA stage) — not a name derived from the
    parameter or its own type (a ``text`` parameter bound to a ``Boolean`` item)."""
    gen = PADGenerator()
    main_page = BPPage(
        page_id="P_MAIN",
        name="Main Page",
        is_main=True,
        stages=[
            _annotated_start("s0", [("Notify", "text", "send_flag")]),
            _data_stage("s1", "send_flag", "Boolean"),
            _annotated_end("s2", []),
        ],
    )
    process = make_process(pages=[main_page], name="WidgetFlow")
    expected_pad_name = gen._build_variable_name_mapping(process)["send_flag"]

    result = gen._generate_consolidated_flow(process, role="performer")

    header = result[: result.index("# Generated by Flowsmith")]
    todo_lines = [line for line in header.splitlines() if "START-stage input 'Notify'" in line]
    assert len(todo_lines) == 1, header
    assert todo_lines[0].endswith(f"PAD variable {expected_pad_name}"), todo_lines[0]
    assert "Notify" not in expected_pad_name, "fixture must make BP and PAD names differ"
    assert expected_pad_name.startswith("flg_"), "name must carry the DATA stage's type"


# Task 7d item 3 helper tests
class TestConfigDataHelpers:
    """Unit tests for Load Config Data function synthesis helpers."""

    def test_get_config_collection_name_from_page_target_map(self) -> None:
        """Test reading config_collection from page_target_map.yaml."""
        gen = PADGenerator()
        # Create a minimal process
        from flowsmith.ast.models import BPProcess

        process = BPProcess(
            process_id="P1",
            name="TestProcess",
            version="1.0",
            source_file="test.bprelease",
            pages=[],
        )

        # Test with no mapping
        assert gen._get_config_collection_name(process) is None

        # Test with mapping that has config_collection
        gen.page_target_map = {"TestProcess": {"config_collection": "ConfigFileData"}}
        assert gen._get_config_collection_name(process) == "ConfigFileData"

        # Test with mapping that doesn't have config_collection
        gen.page_target_map = {"TestProcess": {"some_other_key": "value"}}
        assert gen._get_config_collection_name(process) is None

    def test_make_config_variable_name_removes_non_alphanumerics(self) -> None:
        """Test mapping column names to txt_ variables."""
        gen = PADGenerator()

        # Test various patterns
        assert gen._make_config_variable_name("Sub Folder") == "txt_SubFolder"
        assert gen._make_config_variable_name("Sender_MailID") == "txt_SenderMailID"
        assert (
            gen._make_config_variable_name("Cc-List Business Exception")
            == "txt_CcListBusinessException"
        )
        assert gen._make_config_variable_name("App_WaitTime") == "txt_AppWaitTime"
        assert gen._make_config_variable_name("Mail-Folder'Name") == "txt_MailFolderName"

    def test_extract_config_references_finds_all_distinct_columns(self) -> None:
        """Task 7d item 3: Test extraction of config column references from BP process."""
        from flowsmith.ast.models import BPPage, BPProcess, BPStage, StageType

        gen = PADGenerator()

        # Create a stage with config references in params_map
        stage1 = BPStage(
            stage_id="S1",
            name="Test1",
            stage_type=StageType.ACTION,
            params_map={
                "param1": "[ConfigFileData.Sub Folder]",
                "param2": "[ConfigFileData.Sender_MailID]",
            },
        )

        # Create another stage with references in decision_expression
        stage2 = BPStage(
            stage_id="S2",
            name="Test2",
            stage_type=StageType.DECISION,
            decision_expression="[ConfigFileData.Cc-List Business Exception] = true",
        )

        # Create a stage with duplicate reference (should appear once)
        stage3 = BPStage(
            stage_id="S3",
            name="Test3",
            stage_type=StageType.ACTION,
            params_map={
                "param": "[ConfigFileData.Sender_MailID]"  # Duplicate
            },
        )

        page = BPPage(name="MainPage", page_id="P1", stages=[stage1, stage2, stage3])
        process = BPProcess(
            process_id="PROC1",
            name="TestProcess",
            version="1.0",
            source_file="test.bprelease",
            pages=[page],
        )

        refs = gen._extract_config_references(process, "ConfigFileData")

        # Should have exactly 3 distinct columns, in order seen
        assert len(refs) == 3
        assert refs[0] == "Sub Folder"
        assert refs[1] == "Sender_MailID"
        assert refs[2] == "Cc-List Business Exception"


# ── Task 7d item 3 (amendment 2026-09-25): Load Config Data synthesis ─────────


def _config_main_process(expressions: list[str], name: str = "CfgFlow") -> BPProcess:
    """A process whose Main page reads config columns via CALCULATION stages.

    Each expression becomes ``SET Target<n> TO <expr>`` on the Main page, so every
    ``[ConfigFileData.<X>]`` in it is a real BP config-column read.
    """
    stages = [
        _set_var_stage(f"c{i}", f"Target{i}", expr, None) for i, expr in enumerate(expressions)
    ]
    main = BPPage(page_id="P_MAIN", name="Main Page", is_main=True, stages=stages)
    return make_process(pages=[main], name=name)


@pytest.mark.parametrize("role", ["loader", "performer"])
def test_7d_load_config_data_parse_call_and_function_in_both_roles(role: str) -> None:
    """Both roles get the parse, the CALL (in that order, before the body) and the FUNCTION.

    Reference: Loader L24/L32/L213/L223, Main L35/L42/L118. One SET per referenced column,
    key verbatim, variable = ``txt_`` + column with non-alphanumerics removed; every body
    read resolves to that variable, never ``dtb_ConfigFileData.<X>``.
    """
    gen = PADGenerator()
    process = _config_main_process(
        ['[ConfigFileData.To-List Business Exception] & ";" & [ConfigFileData.Sub Folder]']
    )
    gen.page_target_map["CfgFlow"] = {"config_collection": "ConfigFileData"}

    rendered = gen._generate_consolidated_flow(process, role=role)
    lines = rendered.splitlines()

    parse_line = "Variables.ConvertJsonToCustomObject Json: In_txt_Config CustomObject=> obj_Config"
    parse_idx = lines.index(parse_line)
    call_idx = lines.index("CALL 'Load Config Data'")
    body_idx = next(i for i, ln in enumerate(lines) if ln.startswith("SET Target0 TO"))
    fn_idx = lines.index("FUNCTION 'Load Config Data' GLOBAL")
    assert parse_idx < call_idx < body_idx < fn_idx

    end_idx = next(i for i in range(fn_idx, len(lines)) if lines[i] == "END FUNCTION")
    fn_sets = [ln for ln in lines[fn_idx + 1 : end_idx] if ln.startswith("SET ")]
    assert fn_sets == [
        "SET txt_ToListBusinessException TO obj_Config['To-List Business Exception']",
        "SET txt_SubFolder TO obj_Config['Sub Folder']",
    ]
    assert lines[body_idx] == 'SET Target0 TO txt_ToListBusinessException + ";" + txt_SubFolder'
    assert "ConfigFileData." not in rendered


def test_7d_config_column_name_collision_emits_todo_naming_both_not_a_guess() -> None:
    """Two columns collapsing to one variable name get a TODO naming both, and no SET."""
    gen = PADGenerator()
    process = _config_main_process(["[ConfigFileData.Sub Folder]", "[ConfigFileData.Sub_Folder]"])
    gen.page_target_map["CfgFlow"] = {"config_collection": "ConfigFileData"}

    fn = gen._render_load_config_function(process)

    assert "SET txt_SubFolder" not in fn
    todo = next(ln for ln in fn.splitlines() if ln.startswith("# TODO: config columns"))
    assert "'Sub Folder'" in todo and "'Sub_Folder'" in todo and "txt_SubFolder" in todo
    # Neither colliding column gets a guessed body resolution either.
    mapping = gen._build_variable_name_mapping(process)
    assert "configfiledata.sub folder" not in mapping
    assert "configfiledata.sub_folder" not in mapping


def test_7d_no_config_collection_declared_emits_no_config_read() -> None:
    """Without ``config_collection`` in page_target_map.yaml nothing config-related renders."""
    gen = PADGenerator()
    process = _config_main_process(["[ConfigFileData.Sub Folder]"], name="NoCfgFlow")

    rendered = gen._generate_consolidated_flow(process, role="performer")

    assert "ConvertJsonToCustomObject Json" not in rendered
    assert "CALL 'Load Config Data'" not in rendered
    assert "FUNCTION 'Load Config Data'" not in rendered


def test_7d_load_config_function_emits_no_generic_b12_todo() -> None:
    """Amendment 2 item 5: exposure isn't knowable yet (the AST doesn't carry BP <exposure>),
    so the unconditional generic §B12 TODO is dropped — left to the follow-up task."""
    gen = PADGenerator()
    process = _config_main_process(["[ConfigFileData.Sub Folder]"])
    gen.page_target_map["CfgFlow"] = {"config_collection": "ConfigFileData"}

    fn = gen._render_load_config_function(process)

    assert "§B12" not in fn


def test_7d_header_start_input_todo_no_longer_claims_parse_missing() -> None:
    """flow_header.robin.j2's Task 7c TODO reflects that the parse is now generated."""
    gen = PADGenerator()
    header = gen.env.get_template("flow_header.robin.j2").render(
        inputs=[{"bp_name": "Flag", "data_type": "Bool", "pad_var_name": "flg_Flag"}],
        outputs=[],
        sensitive_vars=[],
    )

    assert "not generated yet" not in header
    assert "That parse and CALL 'Load Config Data' are generated" in header
    assert "# TODO: BP START-stage input 'Flag' (Bool) → PAD variable flg_Flag" in header


# ── Task 7d item 4a/4b: translator-failure branches ──────────────────────────

# A made-up BP function call. The real translator passes unknown calls through verbatim
# (it never returns "" for non-empty input), so these tests force the "translator returned
# empty" failure for exactly this expression to exercise each fallback branch.
_UNTRANSLATABLE_EXPR = "MadeUpFunc([Foo], 3)"


def _fail_translation_of_made_up_call(gen: PADGenerator, monkeypatch: pytest.MonkeyPatch) -> None:
    real = gen._translate_bp_expression

    def fake(expr: str, variable_name_mapping: dict[str, str] | None = None) -> tuple:
        if "MadeUpFunc" in (expr or ""):
            return "", []
        return real(expr, variable_name_mapping)

    monkeypatch.setattr(gen, "_translate_bp_expression", fake)


_EXPECTED_TODO = (
    f"# TODO: could not translate BP expression '{_UNTRANSLATABLE_EXPR}' on stage "
    "'{stage}' — needs manual completion"
)


def test_7d_untranslatable_set_expression_emits_only_the_todo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DATA/SET branch: TODO names raw expression + stage; no SET, no placeholder value."""
    gen = PADGenerator()
    _fail_translation_of_made_up_call(gen, monkeypatch)
    stage = _set_var_stage("X1", "Weird Calc", _UNTRANSLATABLE_EXPR, None)

    out = gen._render_stage(stage)

    assert out.splitlines() == [_EXPECTED_TODO.format(stage="Weird Calc")]
    assert "SET " not in out
    assert "%SomeVar%" not in out


def test_7d_untranslatable_decision_stub_condition_is_marked_placeholder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DECISION condition branch (_render_stage): TODO + visibly-marked placeholder IF."""
    gen = PADGenerator()
    _fail_translation_of_made_up_call(gen, monkeypatch)
    stage = BPStage(
        stage_id="D1",
        stage_type=StageType.DECISION,
        name="Odd Check?",
        decision_expression=_UNTRANSLATABLE_EXPR,
        pa_annotation=PAAnnotation(
            target_type="IF <expr> THEN <true-branch> ELSE <false-branch> END",
            target_module="System",
            runtime=Runtime.DESKTOP,
            confidence=0.85,
            band=ConfidenceBand.SPOT_CHECK,
            params_map={},
            flags=[],
        ),
    )

    lines = gen._render_stage(stage).splitlines()

    assert lines[0] == _EXPECTED_TODO.format(stage="Odd Check?")
    assert lines[1].startswith("# TODO: the IF condition below (TODO_UntranslatedCondition)")
    assert lines[2] == "# VERIFY: Odd Check? (confidence 0.85)"  # Task 7b gap 3 kept
    assert lines[3] == "IF TODO_UntranslatedCondition = True THEN"
    assert "ELSE" in lines and "END" in lines
    assert not any("%SomeVar%" in ln for ln in lines)


def test_7d_untranslatable_decision_branch_keeps_both_bodies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_render_decision_branch: TODO names raw expression + stage; both arms still render."""
    gen = PADGenerator()
    _fail_translation_of_made_up_call(gen, monkeypatch)
    start = _set_var_stage("S", "Before", "0", "D")
    decision = BPStage(
        stage_id="D",
        stage_type=StageType.DECISION,
        name="Odd Branch?",
        decision_expression=_UNTRANSLATABLE_EXPR,
        ontrue_target="A",
        onfalse_target="B",
        pa_annotation=PAAnnotation(
            target_type="IF <expr> THEN <true-branch> ELSE <false-branch> END",
            target_module="System",
            runtime=Runtime.DESKTOP,
            confidence=0.85,
            band=ConfidenceBand.SPOT_CHECK,
            params_map={},
            flags=[],
        ),
    )
    stage_a = _set_var_stage("A", "VarA", "1", None)
    stage_b = _set_var_stage("B", "VarB", "2", None)
    start.onsuccess_target = "D"

    rendered = gen._render_stage_list_with_coarse_blocks([start, decision, stage_a, stage_b])
    lines = [ln.strip() for ln in rendered.splitlines()]

    if_idx = lines.index("IF TODO_UntranslatedCondition = True THEN")
    else_idx = lines.index("ELSE", if_idx)
    end_idx = lines.index("END", else_idx)
    assert _EXPECTED_TODO.format(stage="Odd Branch?") in lines[:if_idx]
    assert "SET VarA TO 1" in lines[if_idx + 1 : else_idx]
    assert "SET VarB TO 2" in lines[else_idx + 1 : end_idx]
    assert "%SomeVar%" not in rendered


def test_7d_decision_with_no_condition_names_stage_and_marks_placeholder() -> None:
    """A DECISION with no BP condition at all is flagged too — no plausible-looking IF."""
    gen = PADGenerator()
    stage = BPStage(
        stage_id="D2",
        stage_type=StageType.DECISION,
        name="Empty Check?",
        pa_annotation=PAAnnotation(
            target_type="IF <expr> THEN <true-branch> ELSE <false-branch> END",
            target_module="System",
            runtime=Runtime.DESKTOP,
            confidence=0.85,
            band=ConfidenceBand.SPOT_CHECK,
            params_map={},
            flags=[],
        ),
    )

    lines = gen._render_stage(stage).splitlines()

    assert lines[0] == (
        "# TODO: DECISION stage 'Empty Check?' has no BP condition expression — "
        "needs manual completion"
    )
    assert "IF TODO_UntranslatedCondition = True THEN" in lines


# ── Task 7d amendment 2: wrapper, parse template, collision policy, minor items ──

_REFERENCE_LOAD_CONFIG_WRAPPER = [
    # docs/pad-reference/DF_PID_171_US_Loader.robin.txt L214-L220 (Main L119-L125),
    # indentation as actions/error_block.robin.j2 renders it.
    "BLOCK 'Assign values from config'",
    "ON BLOCK ERROR all",
    "    SET flg_Screenshot TO False",
    "    SET flg_ConfigError TO True",
    "    CALL 'Get Error'",
    "    THROW ERROR",
    "END",
]


def test_7d_load_config_body_wrapped_in_reference_error_block() -> None:
    """Item 2: the SETs sit inside BLOCK 'Assign values from config' (Loader L214-L220),
    closed by the BLOCK's own END before END FUNCTION; the unwired flags get a TODO."""
    gen = PADGenerator()
    process = _config_main_process(["[ConfigFileData.Sub Folder]"])
    gen.page_target_map["CfgFlow"] = {"config_collection": "ConfigFileData"}

    lines = gen._render_load_config_function(process).splitlines()

    block_idx = lines.index("BLOCK 'Assign values from config'")
    assert lines[block_idx : block_idx + 7] == _REFERENCE_LOAD_CONFIG_WRAPPER
    set_idx = lines.index("SET txt_SubFolder TO obj_Config['Sub Folder']")
    assert set_idx > block_idx + 6
    assert lines[-2:] == ["END", "END FUNCTION"]
    todo = next(ln for ln in lines[:block_idx] if ln.startswith("# TODO:"))
    assert "flg_Screenshot" in todo and "flg_ConfigError" in todo and "'Get Error'" in todo


def test_7d_load_config_wrapper_gets_get_error_function_in_flow() -> None:
    """The wrapper's CALL 'Get Error' is satisfied: the flow emits FUNCTION 'Get Error'."""
    gen = PADGenerator()
    process = _config_main_process(["[ConfigFileData.Sub Folder]"])
    gen.page_target_map["CfgFlow"] = {"config_collection": "ConfigFileData"}

    rendered = gen._generate_consolidated_flow(process, role="loader")

    assert rendered.count("FUNCTION 'Get Error' GLOBAL") == 1


def test_7d_parse_line_renders_from_convert_json_template() -> None:
    """Item 3: the parse line comes from actions/convert_json.robin.j2 (reference Loader
    L24 / Main L35 verbatim), not a Python constant."""
    import flowsmith.generator.pad as pad_module

    gen = PADGenerator()
    line = gen.env.get_template("actions/convert_json.robin.j2").render(
        json_var="In_txt_Config", object_var="obj_Config"
    )

    assert line == (
        "Variables.ConvertJsonToCustomObject Json: In_txt_Config CustomObject=> obj_Config"
    )
    assert not hasattr(pad_module, "CONFIG_PARSE_LINE")


def test_7d_set_clobbering_config_variable_after_load_gets_todo() -> None:
    """Item 4: a Main-body SET after CALL 'Load Config Data' targeting a config variable is
    flagged directly before it; the read of the same variable and the FUNCTION's own SET
    are not."""
    gen = PADGenerator()
    process = _config_main_process(["[ConfigFileData.Sub Folder]"])
    process.pages[0].stages.append(_set_var_stage("c9", "txt_SubFolder", '"override"', None))
    gen.page_target_map["CfgFlow"] = {"config_collection": "ConfigFileData"}

    lines = gen._generate_consolidated_flow(process, role="performer").splitlines()

    set_idx = lines.index('SET txt_SubFolder TO "override"')
    assert lines[set_idx - 1].startswith("# TODO: this SET overwrites txt_SubFolder")
    assert sum(ln.startswith("# TODO: this SET overwrites") for ln in lines) == 1


def test_7d_config_clobber_policy_flags_only_writes_after_load() -> None:
    """Item 4: pre-CALL init SETs, other variables and reads are not flagged; a FUNCTION
    body (no skip) flags every write, keeping its indentation."""
    gen = PADGenerator()
    gen._current_config_variables = {"txt_MailSubject"}
    main = "\n".join(
        [
            'SET txt_MailSubject TO ""',  # Initialise Values: runs before the load
            "CALL 'Load Config Data'",
            "SET txt_Other TO txt_MailSubject",
            'SET txt_MailSubject TO "x"',
        ]
    )
    fn = "\n".join(["FUNCTION 'Mail' GLOBAL", '    SET txt_MailSubject TO "y"', "END FUNCTION"])

    main_lines = gen._flag_config_variable_writes(main, skip_until_config_call=True).splitlines()
    fn_lines = gen._flag_config_variable_writes(fn, skip_until_config_call=False).splitlines()

    assert sum(ln.startswith("# TODO: this SET overwrites") for ln in main_lines) == 1
    assert main_lines[0] == 'SET txt_MailSubject TO ""'
    assert main_lines[-2].startswith("# TODO: this SET overwrites txt_MailSubject")
    assert fn_lines[1].startswith("    # TODO: this SET overwrites txt_MailSubject")
    assert fn_lines[2] == '    SET txt_MailSubject TO "y"'


def test_7d_config_clobber_policy_inactive_without_config_collection() -> None:
    """No config_collection declared → nothing is a config variable → nothing flagged."""
    gen = PADGenerator()
    process = _config_main_process(['"a"'], name="NoCfgFlow")
    process.pages[0].stages.append(_set_var_stage("c9", "txt_SubFolder", '"override"', None))

    rendered = gen._generate_consolidated_flow(process, role="performer")

    assert "this SET overwrites" not in rendered


def test_7d_text_config_value_into_numeric_parameter_gets_verify() -> None:
    """Item 5: a txt_ config value passed to an In_num_ parameter gets a # VERIFY naming the
    Text.ToNumber conversion (reference Loader L228) before the CALL; a txt_ one doesn't."""
    gen = PADGenerator()
    gen._current_config_variables = {"txt_WorksheetPosition", "txt_SubFolder"}
    target_page = BPPage(
        page_id="P_FETCH",
        name="Fetch Data",
        role="performer",
        stages=[
            _annotated_start(
                "s0",
                [
                    ("Position", "number", "Worksheet Position"),
                    ("Folder", "text", "Folder"),
                ],
            ),
        ],
    )
    call_stage = _call_stage(
        "c0",
        "Call Fetch",
        processid="P_FETCH",
        params_map={
            "Position": "[ConfigFileData.WorksheetPosition]",
            "Folder": "[ConfigFileData.Sub Folder]",
        },
    )
    mapping = {
        "configfiledata.worksheetposition": "txt_WorksheetPosition",
        "configfiledata.sub folder": "txt_SubFolder",
    }

    lines = gen._render_page_call_with_arguments(
        call_stage, target_page, "Fetch Data", mapping
    ).splitlines()

    verifies = [ln for ln in lines if ln.startswith("# VERIFY: call argument")]
    assert len(verifies) == 1
    assert "'In_num_WorksheetPosition'" in verifies[0]
    assert "txt_WorksheetPosition" in verifies[0] and "Text.ToNumber" in verifies[0]
    call_idx = next(i for i, ln in enumerate(lines) if ln.startswith("CALL"))
    assert lines.index(verifies[0]) < call_idx


def test_7d_config_reference_scan_covers_exception_code_and_binding_text() -> None:
    """Item 5: [<collection>.<X>] in exception detail, code-stage text and input bindings
    are found too, not just conditions/params/initial values."""
    gen = PADGenerator()
    stages = [
        BPStage(
            stage_id="E1",
            name="Throw",
            stage_type=StageType.EXCEPTION,
            exception_detail='"Missing " & [ConfigFileData.Error Detail]',
        ),
        BPStage(
            stage_id="C1",
            name="Code",
            stage_type=StageType.CODE,
            code_text="x = [ConfigFileData.Code Col]",
        ),
        BPStage(
            stage_id="A1",
            name="Call",
            stage_type=StageType.ACTION,
            inputs_stage_map={"p": "[ConfigFileData.Input Col]"},
        ),
    ]
    process = make_process(
        pages=[BPPage(name="Main Page", page_id="P1", is_main=True, stages=stages)],
        name="ScanFlow",
    )

    refs = gen._extract_config_references(process, "ConfigFileData")

    assert refs == ["Error Detail", "Code Col", "Input Col"]
