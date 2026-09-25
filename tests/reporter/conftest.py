"""Shared fixtures for reporter tests: a small hand-built annotated process."""

from __future__ import annotations

from pathlib import Path

import pytest

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
from flowsmith.ast.serialiser import serialise

REAL_AST = Path("outputs/generated/PID_0171/ast.json")


def _ann(
    confidence: float,
    flags: list[ReviewFlag] | None = None,
    target_type: str = "Target.Action",
    target_module: str = "Module",
) -> PAAnnotation:
    """Build a PAAnnotation whose band matches its confidence."""
    return PAAnnotation(
        target_type=target_type,
        target_module=target_module,
        runtime=Runtime.DESKTOP,
        params_map={},
        confidence=confidence,
        band=ConfidenceBand.from_score(confidence),
        flags=flags or [],
    )


def make_process(annotated: bool = True) -> BPProcess:
    """Build a two-page process covering every band and a flagged VBO call.

    Main page: START (AUTO), a VBO ACTION with a UI-selector error flag (MANUAL),
    a SubSheet call to 'Helper' (SPOT_CHECK), END (AUTO).
    Helper page: a DATA stage with a warn flag (SPOT_CHECK), an unflagged
    PARTIAL VBO ACTION, and an unflagged MANUAL CODE stage.

    Args:
        annotated: If False, every pa_annotation is left None.

    Returns:
        The BPProcess.
    """

    def ann(
        confidence: float,
        flags: list[ReviewFlag] | None = None,
        target_type: str = "Target.Action",
        target_module: str = "Module",
    ) -> PAAnnotation | None:
        """Return an annotation, or None when building an unannotated process."""
        return _ann(confidence, flags, target_type, target_module) if annotated else None

    vbo = BPStage(
        stage_id="s-vbo",
        stage_type=StageType.ACTION,
        name="Click <Login> Button",
        narrative="Clicks the login button on the SampleManager window",
        data_items=[
            BPDataItem(name="Window Title", data_type="text", is_input=True),
            BPDataItem(name="Success", data_type="flag", is_output=True),
        ],
        params_map={
            "Window Title": '"SampleManager"',
            "Timeout": "5",
            "_vbo_object": "PID_0005_Object_US_ SampleResultsEntry",
            "_vbo_action": "Click Login",
        },
        outputs_stage_map={"Success": "Login OK"},
        pa_annotation=ann(
            0.15,
            [
                ReviewFlag(
                    stage_id="s-vbo",
                    reason="UI automation - needs a PAD UI selector",
                    severity="error",
                    suggested_fix="Capture the Login button selector in PAD",
                )
            ],
            "Click Login",
            "UIAutomation",
        ),
    )
    call = BPStage(
        stage_id="s-call",
        stage_type=StageType.ACTION,
        name="Run Helper",
        is_subsheet_call=True,
        processid="p-helper",
        pa_annotation=ann(0.85, None, "RunDesktopFlow", "SubFlow"),
    )
    main = BPPage(
        page_id="p-main",
        name="Main Page",
        is_main=True,
        role="loader",
        stages=[
            BPStage(
                stage_id="s-start", stage_type=StageType.START, name="Start", pa_annotation=ann(1.0)
            ),
            vbo,
            call,
            BPStage(
                stage_id="s-end", stage_type=StageType.END, name="End", pa_annotation=ann(0.95)
            ),
        ],
    )
    helper = BPPage(
        page_id="p-helper",
        name="Helper",
        role="performer",
        stages=[
            BPStage(
                stage_id="s-data",
                stage_type=StageType.DATA,
                name="Wait Time",
                data_items=[
                    BPDataItem(name="Wait Time", data_type="timespan", initial_value="00:00:05")
                ],
                pa_annotation=ann(
                    0.8,
                    [
                        ReviewFlag(
                            stage_id="s-data",
                            reason="TimeSpan mapped to Text",
                            severity="warn",
                            suggested_fix="",
                        )
                    ],
                ),
            ),
            BPStage(
                stage_id="s-partial",
                stage_type=StageType.ACTION,
                name="Delete Input File",
                params_map={
                    "_vbo_object": "Utility - File Management",
                    "_vbo_action": "Delete File",
                },
                pa_annotation=ann(0.6, None, "Delete Files", "File"),
            ),
            BPStage(
                stage_id="s-code",
                stage_type=StageType.CODE,
                name="Clean Up",
                code_text="If x < 1 Then y = 2",
                pa_annotation=ann(0.3, None, "RunVBScript", "Scripting"),
            ),
        ],
    )
    return BPProcess(
        process_id="proc-1",
        name="Test Process",
        version="1.0",
        pages=[main, helper],
        source_file="samples/test.bprelease",
    )


@pytest.fixture
def process() -> BPProcess:
    """An annotated synthetic process."""
    return make_process()


@pytest.fixture
def ast_file(tmp_path: Path, process: BPProcess) -> Path:
    """The synthetic process serialised to tmp_path/out/ast.json."""
    path = tmp_path / "out" / "ast.json"
    serialise(process, path)
    return path


@pytest.fixture
def real_ast() -> Path:
    """Path to the PID_0171 ast.json from Task 7; skips if not generated."""
    if not REAL_AST.is_file():
        pytest.skip("outputs/generated/PID_0171/ast.json not generated")
    return REAL_AST
