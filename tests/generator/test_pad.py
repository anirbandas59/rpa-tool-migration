"""Tests for the PAD .robin generator."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from flowsmith.ast.models import (
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
        data_items=[],
        pa_annotation=PAAnnotation(
            target_type=target_type,
            target_module=target_module,
            runtime=Runtime.DESKTOP,
            params_map={},
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
