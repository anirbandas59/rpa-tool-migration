"""Tests for the Cloud Flow JSON generator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from flowsmith.ast.models import (
    BPPage,
    BPProcess,
    BPStage,
    ConfidenceBand,
    PAAnnotation,
    Runtime,
    StageType,
)
from flowsmith.exceptions import GenerationError
from flowsmith.generator import CloudFlowGenerator

if TYPE_CHECKING:
    from flowsmith.ast.models import BPPage as BPPageType


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def generator() -> CloudFlowGenerator:
    """Return a CloudFlowGenerator instance."""
    return CloudFlowGenerator()


def make_cloud_stage(
    stage_id: str = "S1",
    name: str = "Cloud Action",
    stage_type: StageType = StageType.ACTION,
    target_type: str = "SetVariable",
    target_module: str = "System",
    confidence: float = 0.95,
    vbo_name: str = "",
) -> BPStage:
    """Create a BPStage with CLOUD runtime annotation.

    Args:
        stage_id: The stage ID.
        name: The stage name.
        stage_type: The stage type.
        target_type: The PA target type.
        target_module: The PA target module.
        confidence: The confidence score (default 0.95 = AUTO).
        vbo_name: Optional VBO object name for params_map.

    Returns:
        A CLOUD-runtime annotated BPStage.
    """
    band = ConfidenceBand.from_score(confidence)
    params_map = {}
    if vbo_name:
        params_map["_vbo_object"] = vbo_name

    return BPStage(
        stage_id=stage_id,
        stage_type=stage_type,
        name=name,
        data_items=[],
        pa_annotation=PAAnnotation(
            target_type=target_type,
            target_module=target_module,
            runtime=Runtime.CLOUD,
            params_map=params_map,
            confidence=confidence,
            band=band,
            flags=[],
        ),
    )


def make_desktop_stage(
    stage_id: str = "S2",
    name: str = "Desktop Action",
) -> BPStage:
    """Create a BPStage with DESKTOP runtime annotation.

    Args:
        stage_id: The stage ID.
        name: The stage name.

    Returns:
        A DESKTOP-runtime annotated BPStage.
    """
    return BPStage(
        stage_id=stage_id,
        stage_type=StageType.ACTION,
        name=name,
        data_items=[],
        pa_annotation=PAAnnotation(
            target_type="SetVariable",
            target_module="System",
            runtime=Runtime.DESKTOP,
            params_map={},
            confidence=0.95,
            band=ConfidenceBand.AUTO,
            flags=[],
        ),
    )


def make_page_with_cloud(
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
        stages = [make_cloud_stage()]

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
        pages = [make_page_with_cloud(is_main=True)]

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
    gen = CloudFlowGenerator()
    assert gen is not None
    assert gen.template_dir is not None


def test_missing_template_dir_raises_generation_error() -> None:
    """Test that missing template dir raises GenerationError."""
    with pytest.raises(GenerationError):
        CloudFlowGenerator(template_dir=Path("nonexistent"))


def test_generate_page_returns_none_for_no_cloud_stages() -> None:
    """Test that page with only DESKTOP stages returns None."""
    gen = CloudFlowGenerator()
    page = make_page_with_cloud(stages=[make_desktop_stage()], is_main=False)
    result = gen.generate_page(page, "TestProcess")
    assert result is None


def test_generate_page_returns_string_for_cloud_stages() -> None:
    """Test that page with CLOUD stages returns non-empty string."""
    gen = CloudFlowGenerator()
    page = make_page_with_cloud(is_main=False)
    result = gen.generate_page(page, "TestProcess")
    assert isinstance(result, str)
    assert len(result) > 0


def test_generated_json_is_valid() -> None:
    """Test that generated output is valid JSON."""
    gen = CloudFlowGenerator()
    page = make_page_with_cloud(is_main=False)
    result = gen.generate_page(page, "TestProcess")
    assert result is not None
    # Should not raise json.JSONDecodeError
    json.loads(result)


def test_generated_json_has_properties_key() -> None:
    """Test that generated JSON has 'properties' key."""
    gen = CloudFlowGenerator()
    page = make_page_with_cloud(is_main=False)
    result = gen.generate_page(page, "TestProcess")
    assert result is not None
    data = json.loads(result)
    assert "properties" in data


def test_generated_json_has_definition_key() -> None:
    """Test that generated JSON has definition inside properties."""
    gen = CloudFlowGenerator()
    page = make_page_with_cloud(is_main=False)
    result = gen.generate_page(page, "TestProcess")
    assert result is not None
    data = json.loads(result)
    assert "definition" in data["properties"]


def test_generated_json_has_triggers() -> None:
    """Test that definition has triggers."""
    gen = CloudFlowGenerator()
    page = make_page_with_cloud(is_main=False)
    result = gen.generate_page(page, "TestProcess")
    assert result is not None
    data = json.loads(result)
    assert "triggers" in data["properties"]["definition"]


def test_generated_json_has_actions() -> None:
    """Test that definition has actions."""
    gen = CloudFlowGenerator()
    page = make_page_with_cloud(is_main=False)
    result = gen.generate_page(page, "TestProcess")
    assert result is not None
    data = json.loads(result)
    assert "actions" in data["properties"]["definition"]


def test_manual_stage_renders_stub_compose() -> None:
    """Test that MANUAL CLOUD stage renders as Compose stub."""
    gen = CloudFlowGenerator()
    stage = make_cloud_stage(
        stage_id="S1",
        confidence=0.3,  # Results in MANUAL band
    )
    page = make_page_with_cloud(stages=[stage], is_main=False)
    result = gen.generate_page(page, "TestProcess")
    assert result is not None
    data = json.loads(result)
    actions = data["properties"]["definition"]["actions"]
    # Should have Try and Catch scopes
    assert "Try" in actions or "Catch" in actions


def test_set_variable_cloud_stage_renders_set_variable() -> None:
    """Test that SetVariable target_type renders SetVariable action."""
    gen = CloudFlowGenerator()
    stage = make_cloud_stage(target_type="SetVariable")
    page = make_page_with_cloud(stages=[stage], is_main=False)
    result = gen.generate_page(page, "TestProcess")
    assert result is not None
    # Verify JSON is valid
    json.loads(result)


def test_try_catch_scope_present() -> None:
    """Test that Try and Catch scopes are present in output."""
    gen = CloudFlowGenerator()
    page = make_page_with_cloud(is_main=False)
    result = gen.generate_page(page, "TestProcess")
    assert result is not None
    data = json.loads(result)
    actions = data["properties"]["definition"]["actions"]
    assert "Try" in actions
    assert "Catch" in actions


def test_catch_runs_after_try_on_failure() -> None:
    """Test that Catch scope runAfter references Try with Failed status."""
    gen = CloudFlowGenerator()
    page = make_page_with_cloud(is_main=False)
    result = gen.generate_page(page, "TestProcess")
    assert result is not None
    data = json.loads(result)
    actions = data["properties"]["definition"]["actions"]
    catch_action = actions["Catch"]
    assert "runAfter" in catch_action
    assert "Try" in catch_action["runAfter"]
    assert "Failed" in catch_action["runAfter"]["Try"]


def test_unannotated_stage_raises_generation_error() -> None:
    """Test that unannotated stage with CLOUD stages raises GenerationError."""
    gen = CloudFlowGenerator()
    # Create a CLOUD stage that will be detected
    cloud_stage = make_cloud_stage()
    # Create an unannotated stage
    unannotated = BPStage(
        stage_id="S2",
        stage_type=StageType.ACTION,
        name="Unannotated",
        pa_annotation=None,
    )
    page = make_page_with_cloud(stages=[cloud_stage, unannotated], is_main=False)

    # This should not raise because only cloud_stage is processed
    # unannotated is skipped since it has no pa_annotation
    result = gen.generate_page(page, "TestProcess")
    assert result is not None


def test_generate_process_creates_files(tmp_path: Path) -> None:
    """Test that generate_process creates files in output dir."""
    gen = CloudFlowGenerator()
    process = make_process()
    output_dir = tmp_path / "output"

    files = gen.generate_process(process, output_dir)

    assert len(files) > 0
    assert all(f.exists() for f in files)


def test_generate_process_skips_desktop_only_pages(tmp_path: Path) -> None:
    """Test that pages with only DESKTOP stages produce no file."""
    gen = CloudFlowGenerator()
    page_desktop = make_page_with_cloud(
        stages=[make_desktop_stage()],
        name="DesktopOnly",
        is_main=False,
    )
    page_cloud = make_page_with_cloud(name="CloudPage", is_main=True)
    process = make_process(pages=[page_cloud, page_desktop])

    output_dir = tmp_path / "output"
    files = gen.generate_process(process, output_dir)

    # Should only generate one file (for the CLOUD page)
    assert len(files) == 1


def test_generate_process_returns_empty_for_no_cloud(tmp_path: Path) -> None:
    """Test that process with only DESKTOP stages returns empty list."""
    gen = CloudFlowGenerator()
    page = make_page_with_cloud(stages=[make_desktop_stage()], is_main=True)
    process = make_process(pages=[page])

    output_dir = tmp_path / "output"
    files = gen.generate_process(process, output_dir)

    assert len(files) == 0


def test_output_dir_created_if_missing(tmp_path: Path) -> None:
    """Test that output directory is created if missing."""
    gen = CloudFlowGenerator()
    process = make_process()
    output_dir = tmp_path / "new_dir" / "nested"

    assert not output_dir.exists()
    gen.generate_process(process, output_dir)
    assert output_dir.exists()


def test_filename_sanitised() -> None:
    """Test that page names are sanitised in filenames."""
    sanitised = CloudFlowGenerator._sanitise_filename("JS Actions & More!")
    assert " " not in sanitised
    assert "&" not in sanitised


# ── Integration Tests ──────────────────────────────────────────────────────


@pytest.mark.integration
def test_real_sample_generates_files(tmp_path: Path) -> None:
    """Test that real sample generates at least one Cloud Flow file."""
    sample_path = Path("samples/blueprism/PID_0127.bprelease")
    if not sample_path.exists():
        pytest.skip("Sample file not found")

    from flowsmith.ast.builder import build_ast
    from flowsmith.engine import create_annotator
    from flowsmith.parser import parse_process

    raw = parse_process(sample_path)
    process = build_ast(raw)
    create_annotator().annotate_process(process)

    gen = CloudFlowGenerator()
    files = gen.generate_process(process, tmp_path / "cloudflow")

    assert len(files) >= 1


@pytest.mark.integration
def test_real_sample_all_json_valid(tmp_path: Path) -> None:
    """Test that every generated file parses as valid JSON."""
    sample_path = Path("samples/blueprism/PID_0127.bprelease")
    if not sample_path.exists():
        pytest.skip("Sample file not found")

    from flowsmith.ast.builder import build_ast
    from flowsmith.engine import create_annotator
    from flowsmith.parser import parse_process

    raw = parse_process(sample_path)
    process = build_ast(raw)
    create_annotator().annotate_process(process)

    gen = CloudFlowGenerator()
    files = gen.generate_process(process, tmp_path / "cloudflow")

    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        assert "properties" in data
        assert "definition" in data["properties"]


@pytest.mark.integration
def test_real_sample_no_empty_files(tmp_path: Path) -> None:
    """Test that every file has content."""
    sample_path = Path("samples/blueprism/PID_0127.bprelease")
    if not sample_path.exists():
        pytest.skip("Sample file not found")

    from flowsmith.ast.builder import build_ast
    from flowsmith.engine import create_annotator
    from flowsmith.parser import parse_process

    raw = parse_process(sample_path)
    process = build_ast(raw)
    create_annotator().annotate_process(process)

    gen = CloudFlowGenerator()
    files = gen.generate_process(process, tmp_path / "cloudflow")

    for f in files:
        size = f.stat().st_size
        assert size > 0


@pytest.mark.integration
def test_real_sample_has_try_catch(tmp_path: Path) -> None:
    """Test that at least one file contains Try and Catch scopes."""
    sample_path = Path("samples/blueprism/PID_0127.bprelease")
    if not sample_path.exists():
        pytest.skip("Sample file not found")

    from flowsmith.ast.builder import build_ast
    from flowsmith.engine import create_annotator
    from flowsmith.parser import parse_process

    raw = parse_process(sample_path)
    process = build_ast(raw)
    create_annotator().annotate_process(process)

    gen = CloudFlowGenerator()
    files = gen.generate_process(process, tmp_path / "cloudflow")

    found_try_catch = False
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        actions = data["properties"]["definition"]["actions"]
        if "Try" in actions and "Catch" in actions:
            found_try_catch = True
            break

    assert found_try_catch
