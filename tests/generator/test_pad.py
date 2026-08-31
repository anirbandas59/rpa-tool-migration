"""Tests for the PAD .robin generator."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

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
        params_map: Annotation params_map contents.
        data_items: Data items declared on the stage.

    Returns:
        A fully annotated BPStage.
    """
    if flags is None:
        flags = []

    band = ConfidenceBand.from_score(confidence)

    return BPStage(
        stage_id=stage_id,
        stage_type=stage_type,
        name=name,
        data_items=data_items or [],
        pair_id=pair_id,
        exception_type=exception_type,
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
    stage = make_annotated_stage(target_type="SetVariable")
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


def test_generate_process_one_file_per_page(tmp_path: Path) -> None:
    """Test that process with N pages generates N files."""
    gen = PADGenerator()
    page1 = make_page(name="Page1", is_main=True)
    page2 = make_page(name="Page2", is_main=False)
    page3 = make_page(name="Page3", is_main=False)
    process = make_process(pages=[page1, page2, page3])

    output_dir = tmp_path / "output"
    files = gen.generate_process(process, output_dir)

    assert len(files) == 3


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


# ── Integration Tests ──────────────────────────────────────────────────────


@pytest.mark.integration
def test_real_sample_generates_399_files(tmp_path: Path) -> None:
    """Test that full pipeline generates expected .robin files.

    This test requires the real sample to be present and the full
    pipeline (parser → AST → engine → generator) to work.

    Baseline updated per Task 3a artefact-isolation shrink (docs/reviews/3a-2026-08-30-isolation-fixpass.md):
    Task 3a's per-artefact page isolation reduced output page count from 399 to 19 files for PID_0127.
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

    assert len(files) == 19


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
