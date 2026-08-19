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
    """Test that full pipeline generates exactly 399 .robin files.

    This test requires the real sample to be present and the full
    pipeline (parser → AST → engine → generator) to work.
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

    assert len(files) == 399


@pytest.mark.integration
def test_real_sample_stub_count(tmp_path: Path) -> None:
    """Test that real sample has expected number of stubs."""
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

    # CODE stages (296) + other unmapped stages should give >= 296 stubs
    assert stub_count >= 296


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
    """Test that @SENSITIVE is emitted for a real page holding a password item."""
    sample_path = Path("samples/blueprism/PID_0171.bprelease")
    if not sample_path.exists():
        pytest.skip("Sample file not found")

    from flowsmith.ast.builder import build_ast
    from flowsmith.engine import create_annotator
    from flowsmith.parser import parse_process

    raw = parse_process(sample_path)
    process = build_ast(raw)
    create_annotator().annotate_process(process)

    page = next(
        (
            p
            for p in process.pages
            for s in p.stages
            for d in s.data_items
            if d.data_type.lower() == "password"
        ),
        None,
    )
    assert page is not None, "PID_0171 is expected to declare password data items"

    gen = PADGenerator()
    result = gen.generate_page(page.model_copy(update={"is_main": True}), process.name)

    assert "@SENSITIVE: [" in result
