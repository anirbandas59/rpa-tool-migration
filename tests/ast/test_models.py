"""Tests for flowsmith.ast.models — canonical AST Pydantic models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from flowsmith.ast import (
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
from flowsmith.exceptions import ASTBuildError

# ── StageType ──────────────────────────────────────────────────────────────


def test_stage_type_has_17_members() -> None:
    assert len(StageType) == 17


def test_stage_type_all_names_present() -> None:
    expected = {
        "START",
        "END",
        "ACTION",
        "DECISION",
        "CALCULATION",
        "CODE",
        "WAIT",
        "NAVIGATE",
        "READ",
        "WRITE",
        "LOOP",
        "EXCEPTION",
        "RECOVER",
        "RESUME",
        "BLOCK",
        "COLLECTION",
        "DATA",
    }
    assert {m.name for m in StageType} == expected


# ── Runtime ────────────────────────────────────────────────────────────────


def test_runtime_members() -> None:
    assert Runtime.CLOUD.value == "CLOUD"
    assert Runtime.DESKTOP.value == "DESKTOP"
    assert len(Runtime) == 2


# ── ConfidenceBand.from_score ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "score, expected",
    [
        (1.0, ConfidenceBand.AUTO),
        (0.90, ConfidenceBand.AUTO),
        (0.89, ConfidenceBand.SPOT_CHECK),
        (0.70, ConfidenceBand.SPOT_CHECK),
        (0.69, ConfidenceBand.PARTIAL),
        (0.50, ConfidenceBand.PARTIAL),
        (0.49, ConfidenceBand.MANUAL),
        (0.0, ConfidenceBand.MANUAL),
    ],
)
def test_confidence_band_from_score(score: float, expected: ConfidenceBand) -> None:
    assert ConfidenceBand.from_score(score) == expected


# ── ReviewFlag ─────────────────────────────────────────────────────────────


def test_review_flag_valid_construction() -> None:
    flag = ReviewFlag(
        stage_id="s1",
        reason="Needs review",
        severity="warn",
        suggested_fix="Check manually",
    )
    assert flag.stage_id == "s1"
    assert flag.severity == "warn"


def test_review_flag_invalid_severity() -> None:
    with pytest.raises(ValidationError):
        ReviewFlag(
            stage_id="s1",
            reason="Bad",
            severity="critical",  # not a valid Literal
            suggested_fix="N/A",
        )


def test_review_flag_is_frozen() -> None:
    flag = ReviewFlag(stage_id="s1", reason="r", severity="info", suggested_fix="fix")
    with pytest.raises(ValidationError):
        flag.stage_id = "s2"  # type: ignore[misc]


# ── PAAnnotation ──────────────────────────────────────────────────────────


def _make_annotation(**overrides: object) -> PAAnnotation:
    defaults: dict = {
        "target_type": "Excel.LaunchExcel",
        "target_module": "Excel",
        "runtime": Runtime.DESKTOP,
        "params_map": {},
        "confidence": 0.80,
        "band": ConfidenceBand.SPOT_CHECK,
    }
    defaults.update(overrides)
    return PAAnnotation(**defaults)  # type: ignore[arg-type]


def test_pa_annotation_valid_construction() -> None:
    ann = _make_annotation()
    assert ann.confidence == 0.80
    assert ann.band == ConfidenceBand.SPOT_CHECK
    assert ann.flags == []


def test_pa_annotation_band_mismatch_raises() -> None:
    with pytest.raises(ValidationError, match="inconsistent"):
        _make_annotation(confidence=0.95, band=ConfidenceBand.MANUAL)


def test_pa_annotation_confidence_below_zero_raises() -> None:
    with pytest.raises(ValidationError):
        _make_annotation(confidence=-0.1, band=ConfidenceBand.MANUAL)


def test_pa_annotation_confidence_above_one_raises() -> None:
    with pytest.raises(ValidationError):
        _make_annotation(confidence=1.1, band=ConfidenceBand.AUTO)


def test_pa_annotation_auto_band_boundaries() -> None:
    ann = _make_annotation(confidence=0.90, band=ConfidenceBand.AUTO)
    assert ann.band == ConfidenceBand.AUTO

    ann2 = _make_annotation(confidence=0.49, band=ConfidenceBand.MANUAL)
    assert ann2.band == ConfidenceBand.MANUAL


def test_pa_annotation_with_flags() -> None:
    flag = ReviewFlag(
        stage_id="s1", reason="Check auth", severity="error", suggested_fix="Migrate to AAD"
    )
    ann = _make_annotation(flags=[flag])
    assert len(ann.flags) == 1
    assert ann.flags[0].severity == "error"


def test_pa_annotation_is_frozen() -> None:
    ann = _make_annotation()
    with pytest.raises(ValidationError):
        ann.target_module = "File"  # type: ignore[misc]


# ── BPDataItem ────────────────────────────────────────────────────────────


def test_bp_data_item_valid_construction() -> None:
    item = BPDataItem(name="CustomerName", data_type="text")
    assert item.name == "CustomerName"
    assert item.initial_value is None
    assert item.is_input is False
    assert item.is_output is False


def test_bp_data_item_with_all_fields() -> None:
    item = BPDataItem(
        name="Count",
        data_type="number",
        initial_value="0",
        is_input=True,
        is_output=False,
    )
    assert item.initial_value == "0"
    assert item.is_input is True


def test_bp_data_item_is_frozen() -> None:
    item = BPDataItem(name="X", data_type="text")
    with pytest.raises(ValidationError):
        item.name = "Y"  # type: ignore[misc]


# ── BPStage ───────────────────────────────────────────────────────────────


def _make_stage(**overrides: object) -> BPStage:
    defaults: dict = {
        "stage_id": "stage-001",
        "stage_type": StageType.ACTION,
        "name": "Get Workbook",
    }
    defaults.update(overrides)
    return BPStage(**defaults)  # type: ignore[arg-type]


def test_bp_stage_minimal_construction() -> None:
    stage = _make_stage()
    assert stage.stage_id == "stage-001"
    assert stage.stage_type == StageType.ACTION
    assert stage.data_items == []
    assert stage.exception_handler_id is None
    assert stage.exception_type is None
    assert stage.pair_id is None
    assert stage.is_subsheet_call is False
    assert stage.params_map == {}
    assert stage.pa_annotation is None


def test_bp_stage_pa_annotation_starts_none() -> None:
    stage = _make_stage()
    assert stage.pa_annotation is None


def test_bp_stage_pa_annotation_is_mutable() -> None:
    """Engine must be able to set pa_annotation after construction."""
    stage = _make_stage()
    ann = PAAnnotation(
        target_type="Excel.LaunchExcel",
        target_module="Excel",
        runtime=Runtime.DESKTOP,
        params_map={},
        confidence=0.80,
        band=ConfidenceBand.SPOT_CHECK,
    )
    stage.pa_annotation = ann
    assert stage.pa_annotation == ann


def test_bp_stage_other_fields_are_mutable() -> None:
    """BPStage is not frozen — fields can be reassigned."""
    stage = _make_stage()
    stage.name = "Updated Name"
    assert stage.name == "Updated Name"


# ── BPPage ────────────────────────────────────────────────────────────────


def test_bp_page_valid_construction() -> None:
    page = BPPage(page_id="page-1", name="Main Page")
    assert page.stages == []
    assert page.is_main is False


def test_bp_page_is_main_flag() -> None:
    page = BPPage(page_id="page-1", name="Main Page", is_main=True)
    assert page.is_main is True


def test_bp_page_is_frozen() -> None:
    page = BPPage(page_id="page-1", name="Main Page")
    with pytest.raises(ValidationError):
        page.name = "Other"  # type: ignore[misc]


# ── BPProcess ─────────────────────────────────────────────────────────────


def _make_process(**overrides: object) -> BPProcess:
    defaults: dict = {
        "process_id": "proc-1",
        "name": "BulkUnlock",
        "version": "1.0",
        "pages": [],
        "source_file": "samples/test.bprelease",
    }
    defaults.update(overrides)
    return BPProcess(**defaults)  # type: ignore[arg-type]


def test_bp_process_valid_construction() -> None:
    proc = _make_process()
    assert proc.process_id == "proc-1"
    assert proc.pages == []


def test_bp_process_get_stage_returns_correct_stage() -> None:
    stage = _make_stage(stage_id="s-42", name="Read Cell")
    page = BPPage(page_id="p1", name="Main", stages=[stage])
    proc = _make_process(pages=[page])
    found = proc.get_stage("s-42")
    assert found.name == "Read Cell"


def test_bp_process_get_stage_raises_on_missing() -> None:
    proc = _make_process()
    with pytest.raises(ASTBuildError, match="not found"):
        proc.get_stage("nonexistent")


def test_bp_process_get_stage_searches_multiple_pages() -> None:
    stage_a = _make_stage(stage_id="s-1", name="Stage A")
    stage_b = _make_stage(stage_id="s-2", name="Stage B")
    page1 = BPPage(page_id="p1", name="Page 1", stages=[stage_a])
    page2 = BPPage(page_id="p2", name="Page 2", stages=[stage_b])
    proc = _make_process(pages=[page1, page2])

    assert proc.get_stage("s-1").name == "Stage A"
    assert proc.get_stage("s-2").name == "Stage B"


def test_bp_process_is_frozen() -> None:
    proc = _make_process()
    with pytest.raises(ValidationError):
        proc.name = "Other"  # type: ignore[misc]
