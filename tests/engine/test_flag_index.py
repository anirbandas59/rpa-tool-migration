"""Tests for review flag index — FlagEntry, FlagIndex, FlagIndexBuilder."""

from __future__ import annotations

from pathlib import Path

import pytest

from flowsmith.ast import BPPage, BPProcess, BPStage, PAAnnotation, ReviewFlag, Runtime, StageType
from flowsmith.engine import FlagEntry, FlagIndex, FlagIndexBuilder, create_annotator
from flowsmith.exceptions import TransformError

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def builder() -> FlagIndexBuilder:
    """Return a FlagIndexBuilder instance."""
    return FlagIndexBuilder()


@pytest.fixture
def make_flag_entry():
    """Build a FlagEntry with sensible defaults, accept kwargs to override."""

    def _make(**kwargs) -> FlagEntry:
        defaults = {
            "stage_id": "s1",
            "stage_type": "CODE",
            "stage_name": "Test Stage",
            "page_id": "pg1",
            "page_name": "Main",
            "is_main_page": True,
            "severity": "error",
            "reason": "Test reason",
            "suggested_fix": "Fix this",
            "vbo_name": "",
            "target_module": "Excel",
            "confidence": 0.75,
        }
        defaults.update(kwargs)
        return FlagEntry(**defaults)

    return _make


@pytest.fixture
def make_annotated_stage():
    """Build a BPStage with PAAnnotation and optional ReviewFlag."""

    def _make(severity: str | None = None, vbo_name: str = "") -> BPStage:
        flags = []
        if severity:
            flags.append(
                ReviewFlag(
                    stage_id="s1",
                    reason="Test flag",
                    severity=severity,
                    suggested_fix="Fix this",
                )
            )

        params_map = {}
        if vbo_name:
            params_map["_vbo_object"] = vbo_name

        return BPStage(
            stage_id="s1",
            stage_type=StageType.CODE,
            name="Test Stage",
            data_items=[],
            exception_handler_id=None,
            exception_type=None,
            pair_id=None,
            is_subsheet_call=False,
            params_map=params_map,
            pa_annotation=PAAnnotation(
                target_type="Excel.LaunchExcel",
                target_module="Excel",
                runtime=Runtime.DESKTOP,
                params_map={},
                confidence=0.75,
                band="SPOT_CHECK",
                flags=flags,
            ),
        )

    return _make


@pytest.fixture
def simple_process_with_flags(make_annotated_stage) -> BPProcess:
    """Build a simple annotated process with known flags for testing.

    Structure:
      Page 1 "Main" (is_main=True):
        - START stage (no flags)
        - CODE stage (1 error flag)
        - DATA stage with password type (1 warn flag)
      Page 2 "SubFlow":
        - ACTION stage with ACS VBO (1 error flag)
        - END stage (no flags)
    """
    # Page 1 stages
    start = make_annotated_stage(severity=None)
    start.stage_id = "s_start"
    start.stage_type = StageType.START
    start.name = "Start"

    code = make_annotated_stage(severity="error")
    code.stage_id = "s_code"
    code.stage_type = StageType.CODE
    code.name = "Process Data"

    data = make_annotated_stage(severity="warn")
    data.stage_id = "s_data"
    data.stage_type = StageType.DATA
    data.name = "Get Password"

    page1 = BPPage(
        page_id="pg1",
        name="Main",
        is_main=True,
        stages=[start, code, data],
    )

    # Page 2 stages
    action = make_annotated_stage(severity="error", vbo_name="RPA Sharepoint ACS Authentication")
    action.stage_id = "s_action"
    action.stage_type = StageType.ACTION
    action.name = "Authenticate with ACS"

    end = make_annotated_stage(severity=None)
    end.stage_id = "s_end"
    end.stage_type = StageType.END
    end.name = "End"

    page2 = BPPage(
        page_id="pg2",
        name="SubFlow",
        is_main=False,
        stages=[action, end],
    )

    return BPProcess(
        process_id="p1",
        name="Test Process",
        version="1.0",
        source_file="test.bprelease",
        pages=[page1, page2],
    )


@pytest.fixture(scope="session")
def sample_path() -> Path | None:
    """Return path to real sample if available, else None."""
    path = Path("samples/blueprism/PID_0127.bprelease")
    return path if path.exists() else None


@pytest.fixture(scope="session")
def real_index(sample_path):
    """Build FlagIndex from real sample (session scope, skip if unavailable)."""
    if not sample_path:
        pytest.skip("Sample file not available")

    from flowsmith.ast import build_ast
    from flowsmith.parser import parse_process

    raw = parse_process(sample_path)
    process = build_ast(raw)
    create_annotator().annotate_process(process)
    return FlagIndexBuilder().build(process)


# ── Unit Tests ──────────────────────────────────────────────────────────────


def test_build_returns_flag_index(builder, simple_process_with_flags):
    """Test that build() returns a FlagIndex instance."""
    result = builder.build(simple_process_with_flags)
    assert isinstance(result, FlagIndex)


def test_build_empty_process_returns_empty_index(builder):
    """Test that a process with no flags produces an empty index."""
    from flowsmith.ast import BPPage, BPProcess, BPStage, PAAnnotation, Runtime, StageType

    stage = BPStage(
        stage_id="s1",
        stage_type=StageType.START,
        name="Start",
        data_items=[],
        exception_handler_id=None,
        exception_type=None,
        pair_id=None,
        is_subsheet_call=False,
        params_map={},
        pa_annotation=PAAnnotation(
            target_type="",
            target_module="",
            runtime=Runtime.CLOUD,
            params_map={},
            confidence=0.5,
            band="PARTIAL",
            flags=[],
        ),
    )
    process = BPProcess(
        process_id="p1",
        name="Empty",
        version="1.0",
        source_file="empty.bprelease",
        pages=[BPPage(page_id="pg1", name="Main", is_main=True, stages=[stage])],
    )
    result = builder.build(process)
    assert len(result.entries) == 0


def test_build_collects_all_flags(builder, simple_process_with_flags):
    """Test that build() collects all flags from all pages."""
    result = builder.build(simple_process_with_flags)
    assert len(result.entries) == 3  # 3 flags total


def test_flag_entry_has_page_context(builder, simple_process_with_flags):
    """Test that FlagEntry includes page context."""
    result = builder.build(simple_process_with_flags)
    entry = result.entries[0]
    assert entry.page_id == "pg1"
    assert entry.page_name == "Main"
    assert entry.is_main_page is True


def test_flag_entry_has_stage_context(builder, simple_process_with_flags):
    """Test that FlagEntry includes stage context."""
    result = builder.build(simple_process_with_flags)
    entry = result.entries[0]
    # Check that stage_id is populated (from ReviewFlag)
    assert entry.stage_id != ""
    assert entry.stage_type in ["CODE", "DATA", "ACTION"]
    assert entry.stage_name != ""


def test_flag_entry_vbo_name_from_params_map(builder, simple_process_with_flags):
    """Test that vbo_name is extracted from params_map._vbo_object."""
    result = builder.build(simple_process_with_flags)
    acs_entry = [e for e in result.entries if e.vbo_name == "RPA Sharepoint ACS Authentication"][0]
    assert acs_entry.vbo_name == "RPA Sharepoint ACS Authentication"


def test_flag_entry_no_vbo_for_non_action(builder, simple_process_with_flags):
    """Test that non-VBO stages have empty vbo_name."""
    result = builder.build(simple_process_with_flags)
    code_entry = [e for e in result.entries if e.stage_type == "CODE"][0]
    assert code_entry.vbo_name == ""


def test_by_severity_error(builder, simple_process_with_flags):
    """Test by_severity('error') returns only error entries."""
    result = builder.build(simple_process_with_flags)
    errors = result.by_severity("error")
    assert len(errors) == 2
    assert all(e.severity == "error" for e in errors)


def test_by_severity_warn(builder, simple_process_with_flags):
    """Test by_severity('warn') returns only warn entries."""
    result = builder.build(simple_process_with_flags)
    warnings = result.by_severity("warn")
    assert len(warnings) == 1
    assert all(e.severity == "warn" for e in warnings)


def test_by_severity_empty_for_info(builder, simple_process_with_flags):
    """Test by_severity('info') returns empty list when no info flags."""
    result = builder.build(simple_process_with_flags)
    infos = result.by_severity("info")
    assert len(infos) == 0


def test_errors_shorthand_matches_by_severity(builder, simple_process_with_flags):
    """Test that errors() shorthand matches by_severity('error')."""
    result = builder.build(simple_process_with_flags)
    assert result.errors() == result.by_severity("error")


def test_warnings_shorthand_matches_by_severity(builder, simple_process_with_flags):
    """Test that warnings() shorthand matches by_severity('warn')."""
    result = builder.build(simple_process_with_flags)
    assert result.warnings() == result.by_severity("warn")


def test_by_page_filters_correctly(builder, simple_process_with_flags):
    """Test by_page() filters entries by page_id."""
    result = builder.build(simple_process_with_flags)
    page1_flags = result.by_page("pg1")
    assert len(page1_flags) == 2  # code error + data warn
    assert all(e.page_id == "pg1" for e in page1_flags)


def test_by_stage_type_code(builder, simple_process_with_flags):
    """Test by_stage_type('CODE') filters correctly."""
    result = builder.build(simple_process_with_flags)
    code_flags = result.by_stage_type("CODE")
    assert len(code_flags) == 1
    assert all(e.stage_type == "CODE" for e in code_flags)


def test_by_vbo_returns_matching_entries(builder, simple_process_with_flags):
    """Test by_vbo() returns entries matching the VBO name."""
    result = builder.build(simple_process_with_flags)
    acs_flags = result.by_vbo("RPA Sharepoint ACS Authentication")
    assert len(acs_flags) == 1
    assert acs_flags[0].vbo_name == "RPA Sharepoint ACS Authentication"


def test_by_vbo_empty_for_unknown_vbo(builder, simple_process_with_flags):
    """Test by_vbo() returns empty list for unknown VBO."""
    result = builder.build(simple_process_with_flags)
    unknown = result.by_vbo("Unknown VBO")
    assert len(unknown) == 0


def test_summary_by_severity_counts(builder, simple_process_with_flags):
    """Test summary_by_severity() counts correctly."""
    result = builder.build(simple_process_with_flags)
    summary = result.summary_by_severity()
    assert summary == {"error": 2, "warn": 1}


def test_summary_by_page_sorted_desc(builder, simple_process_with_flags):
    """Test summary_by_page() is sorted descending by count."""
    result = builder.build(simple_process_with_flags)
    summary = result.summary_by_page()
    items = list(summary.items())
    counts = [count for _, count in items]
    assert counts == sorted(counts, reverse=True)


def test_summary_by_stage_type_sorted_desc(builder, simple_process_with_flags):
    """Test summary_by_stage_type() is sorted descending by count."""
    result = builder.build(simple_process_with_flags)
    summary = result.summary_by_stage_type()
    items = list(summary.items())
    counts = [count for _, count in items]
    assert counts == sorted(counts, reverse=True)


def test_summary_by_vbo_excludes_empty_vbo_name(builder, simple_process_with_flags):
    """Test summary_by_vbo() excludes entries with empty vbo_name."""
    result = builder.build(simple_process_with_flags)
    summary = result.summary_by_vbo()
    assert "" not in summary
    assert "RPA Sharepoint ACS Authentication" in summary


def test_checklist_error_before_warn(builder, simple_process_with_flags):
    """Test checklist() places all errors before all warnings."""
    result = builder.build(simple_process_with_flags)
    checklist = result.checklist()
    severities = [e.severity for e in checklist]
    # All errors should come first
    last_error = max(i for i, s in enumerate(severities) if s == "error")
    first_warn = min((i for i, s in enumerate(severities) if s == "warn"), default=len(severities))
    assert last_error < first_warn


def test_checklist_sorted_by_page_within_severity(builder, simple_process_with_flags):
    """Test checklist() sorts by page name within same severity."""
    result = builder.build(simple_process_with_flags)
    checklist = result.checklist()
    # Within error entries, should be sorted by page name
    errors = [e for e in checklist if e.severity == "error"]
    page_names = [e.page_name for e in errors]
    assert page_names == sorted(page_names)


def test_build_raises_transform_error_unannotated(builder):
    """Test build() raises TransformError if stage has no pa_annotation."""
    stage = BPStage(
        stage_id="s1",
        stage_type=StageType.START,
        name="Start",
        data_items=[],
        exception_handler_id=None,
        exception_type=None,
        pair_id=None,
        is_subsheet_call=False,
        params_map={},
        pa_annotation=None,  # Missing annotation
    )
    process = BPProcess(
        process_id="p1",
        name="Test",
        version="1.0",
        source_file="test.bprelease",
        pages=[BPPage(page_id="pg1", name="Main", is_main=True, stages=[stage])],
    )
    with pytest.raises(TransformError, match="has no PAAnnotation"):
        builder.build(process)


def test_flag_index_is_frozen():
    """Test that FlagIndex is frozen (immutable)."""
    from pydantic import ValidationError

    index = FlagIndex(process_id="p1", process_name="Test", entries=[])
    with pytest.raises(ValidationError):
        index.entries = []  # type: ignore


def test_flag_entry_is_frozen(make_flag_entry):
    """Test that FlagEntry is frozen (immutable)."""
    from pydantic import ValidationError

    entry = make_flag_entry()
    with pytest.raises(ValidationError):
        entry.stage_id = "different"  # type: ignore


# ── Integration Tests (real sample) ─────────────────────────────────────────


def test_real_total_flags_538(real_index):
    """Test real sample has 538 total flags."""
    assert len(real_index.entries) == 538


def test_real_error_count_485(real_index):
    """Test real sample has 485 error flags."""
    assert len(real_index.errors()) == 485


def test_real_warn_count_53(real_index):
    """Test real sample has 53 warn flags."""
    assert len(real_index.warnings()) == 53


def test_real_code_flags_296(real_index):
    """Test real sample has 296 CODE stage flags."""
    code_flags = real_index.by_stage_type("CODE")
    assert len(code_flags) == 296


def test_real_data_flags_50(real_index):
    """Test real sample has 50 DATA stage flags (all warn severity)."""
    data_flags = real_index.by_stage_type("DATA")
    assert len(data_flags) == 50
    # All DATA flags should be warn severity
    assert all(f.severity == "warn" for f in data_flags)


def test_real_checklist_starts_with_error(real_index):
    """Test real checklist starts with error severity."""
    checklist = real_index.checklist()
    assert checklist[0].severity == "error"


def test_real_checklist_length_538(real_index):
    """Test real checklist contains all 538 entries."""
    checklist = real_index.checklist()
    assert len(checklist) == 538


def test_real_summary_by_vbo_contains_acs(real_index):
    """Test real summary_by_vbo contains ACS VBO."""
    summary = real_index.summary_by_vbo()
    assert "RPA Sharepoint ACS Authentication" in summary


def test_real_all_entries_have_stage_id(real_index):
    """Test all entries have non-empty stage_id."""
    assert all(e.stage_id for e in real_index.entries)


def test_real_all_entries_have_page_name(real_index):
    """Test all entries have non-empty page_name."""
    assert all(e.page_name for e in real_index.entries)


def test_real_by_page_sums_to_total(real_index):
    """Test summary_by_page counts sum to total flags."""
    summary = real_index.summary_by_page()
    assert sum(summary.values()) == 538
