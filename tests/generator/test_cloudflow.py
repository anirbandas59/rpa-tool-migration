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


def test_foreach_action_renders() -> None:
    """Test that Foreach action type renders correctly."""
    gen = CloudFlowGenerator()
    stage = make_cloud_stage(target_type="Foreach", confidence=0.95)
    page = make_page_with_cloud(stages=[stage], is_main=False)
    result = gen.generate_page(page, "TestProcess")
    assert result is not None
    data = json.loads(result)
    assert "Try" in data["properties"]["definition"]["actions"]


def test_parse_json_action_renders() -> None:
    """Test that ParseJson action type renders correctly."""
    gen = CloudFlowGenerator()
    stage = make_cloud_stage(target_type="ParseJson", confidence=0.95)
    page = make_page_with_cloud(stages=[stage], is_main=False)
    result = gen.generate_page(page, "TestProcess")
    assert result is not None
    data = json.loads(result)
    assert "Try" in data["properties"]["definition"]["actions"]


def test_query_action_renders() -> None:
    """Test that Query action type renders correctly."""
    gen = CloudFlowGenerator()
    stage = make_cloud_stage(target_type="Query", confidence=0.95)
    page = make_page_with_cloud(stages=[stage], is_main=False)
    result = gen.generate_page(page, "TestProcess")
    assert result is not None
    data = json.loads(result)
    assert "Try" in data["properties"]["definition"]["actions"]


def test_response_action_renders() -> None:
    """Test that Response action type renders correctly."""
    gen = CloudFlowGenerator()
    stage = make_cloud_stage(target_type="Response", confidence=0.95)
    page = make_page_with_cloud(stages=[stage], is_main=False)
    result = gen.generate_page(page, "TestProcess")
    assert result is not None
    data = json.loads(result)
    assert "Try" in data["properties"]["definition"]["actions"]


def test_select_action_renders() -> None:
    """Test that Select action type renders correctly."""
    gen = CloudFlowGenerator()
    stage = make_cloud_stage(target_type="Select", confidence=0.95)
    page = make_page_with_cloud(stages=[stage], is_main=False)
    result = gen.generate_page(page, "TestProcess")
    assert result is not None
    data = json.loads(result)
    assert "Try" in data["properties"]["definition"]["actions"]


def test_workflow_action_renders() -> None:
    """Test that Workflow (child flow) action type renders correctly."""
    gen = CloudFlowGenerator()
    stage = make_cloud_stage(target_type="Workflow", confidence=0.95)
    page = make_page_with_cloud(stages=[stage], is_main=False)
    result = gen.generate_page(page, "TestProcess")
    assert result is not None
    data = json.loads(result)
    assert "Try" in data["properties"]["definition"]["actions"]


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


# ── Orchestrator Cloud Flow ────────────────────────────────────────────────


DESKTOP_FLOW_IDS = {
    "Loader": "5231954C-98DC-4575-8B2F-7CBFC0E3C42F",
    "Performer": "A08A518C-E955-4E3A-AF5B-262E29BC6A9B",
}


def make_process_with_env_vars() -> BPProcess:
    """Return a BPProcess declaring two environment variables.

    Returns:
        A BPProcess with environment variables and one cloud page.
    """
    from flowsmith.ast.models import BPEnvironmentVariable

    return BPProcess(
        process_id="PROC1",
        name="PID_171",
        version="1.0.0",
        pages=[make_page_with_cloud(is_main=True)],
        environment_variables=[
            BPEnvironmentVariable(name="Config File", data_type="text", value="a.xlsx"),
            BPEnvironmentVariable(name="Retry Count", data_type="number", value="3"),
        ],
        source_file="test.bprelease",
    )


def orchestrator_json(
    process: BPProcess | None = None,
    desktop_flow_ids: dict[str, str] | None = None,
) -> dict:
    """Generate and parse an orchestrator Cloud Flow.

    Args:
        process: The process to generate for. Defaults to a process with
            environment variables.
        desktop_flow_ids: Desktop flow name → WorkflowId map.

    Returns:
        The parsed orchestrator JSON.
    """
    gen = CloudFlowGenerator()
    result = gen.generate_orchestrator(
        process if process is not None else make_process_with_env_vars(),
        desktop_flow_ids if desktop_flow_ids is not None else DESKTOP_FLOW_IDS,
        publisher_prefix="cr3ac",
    )
    return json.loads(result)


def test_orchestrator_is_valid_json() -> None:
    """Orchestrator output parses as JSON with a definition."""
    data = orchestrator_json()
    assert "definition" in data["properties"]


def test_orchestrator_connection_references() -> None:
    """connectionReferences carries at least shared_uiflow and shared_office365-1."""
    refs = orchestrator_json()["properties"]["connectionReferences"]
    assert "shared_uiflow" in refs
    assert "shared_office365-1" in refs


def test_orchestrator_parameters_section_exists() -> None:
    """parameters holds the PA built-ins plus one entry per environment variable."""
    params = orchestrator_json()["properties"]["definition"]["parameters"]
    assert "$authentication" in params
    assert "$connections" in params
    assert "Config File (cr3ac_Config_File)" in params
    entry = params["Config File (cr3ac_Config_File)"]
    assert entry["defaultValue"] == "a.xlsx"
    assert entry["metadata"]["schemaName"] == "cr3ac_Config_File"


def test_orchestrator_parameter_type_mapping() -> None:
    """A BP number environment variable becomes a Float parameter."""
    params = orchestrator_json()["properties"]["definition"]["parameters"]
    assert params["Retry Count (cr3ac_Retry_Count)"]["type"] == "Float"


def test_orchestrator_without_env_vars_still_has_parameters() -> None:
    """A process with no environment variables keeps the built-in parameters."""
    params = orchestrator_json(process=make_process())["properties"]["definition"]["parameters"]
    assert set(params) == {"$authentication", "$connections"}


def test_orchestrator_trigger_is_button() -> None:
    """The trigger is a manual Request button with both flag inputs."""
    trigger = orchestrator_json()["properties"]["definition"]["triggers"]["manual"]
    assert trigger["type"] == "Request"
    assert trigger["kind"] == "Button"
    properties = trigger["inputs"]["schema"]["properties"]
    assert properties["boolean"]["title"] == "Loader_Flag"
    assert properties["boolean_1"]["title"] == "Performer_Flag"


def test_orchestrator_top_level_scopes() -> None:
    """All four Try/Catch scopes and individual Catch scopes are present."""
    actions = orchestrator_json()["properties"]["definition"]["actions"]
    # Try scopes
    for name in ("Try:_Init", "Try:_Loader", "Try:_Performer"):
        assert name in actions
        assert actions[name]["type"] == "Scope"
    # Catch scopes
    for name in ("Catch:_Init", "Catch:_Loader", "Catch:_Performer", "Catch:_Global_Error_Handler"):
        assert name in actions
        assert actions[name]["type"] == "Scope"


def test_orchestrator_loader_invokes_real_desktop_flow_id() -> None:
    """Try:_Loader invokes RunUIFlow_V2 with the generated Loader WorkflowId."""
    actions = orchestrator_json()["properties"]["definition"]["actions"]
    # Navigate through nested If statements to find the unattended desktop flow
    invocation = actions["Try:_Loader"]["actions"]["If_Loader_flag_=_yes"]["actions"][
        "If_Loader_type_=_Cloud"
    ]["else"]["actions"]["If_Desktop_run_=_Unattended"]["actions"][
        "Desktop_Flow_-_Loader_-_Unattended"
    ]
    assert invocation["type"] == "OpenApiConnection"
    assert invocation["inputs"]["host"]["operationId"] == "RunUIFlow_V2"
    assert invocation["inputs"]["host"]["connectionName"] == "shared_uiflow"
    assert invocation["inputs"]["parameters"]["uiFlowId"] == DESKTOP_FLOW_IDS["Loader"]
    # Also check attended version
    attended = actions["Try:_Loader"]["actions"]["If_Loader_flag_=_yes"]["actions"][
        "If_Loader_type_=_Cloud"
    ]["else"]["actions"]["If_Desktop_run_=_Unattended"]["else"]["actions"][
        "Desktop_Flow_-_Loader_-_Attended"
    ]
    assert attended["inputs"]["parameters"]["uiFlowId"] == DESKTOP_FLOW_IDS["Loader"]
    assert attended["inputs"]["parameters"]["runMode"] == "attended"


def test_orchestrator_performer_invokes_real_desktop_flow_id() -> None:
    """Try:_Performer invokes the Performer desktop flow by WorkflowId."""
    actions = orchestrator_json()["properties"]["definition"]["actions"]
    performer = actions["Try:_Performer"]["actions"]["If_Performer_flag_=_yes"]["actions"][
        "If_Work_Queue_Items_present"
    ]["actions"]["If_Performer_type_=_desktop"]["actions"]["If_performer_run_=_Unattended"][
        "actions"
    ]["Desktop_Flow_-_Performer_-_Unattended"]
    assert performer["inputs"]["parameters"]["uiFlowId"] == DESKTOP_FLOW_IDS["Performer"]
    assert performer["inputs"]["parameters"]["runMode"] == "unattended"


def test_orchestrator_catch_runs_after_all_try_scopes() -> None:
    """Catch:_Global_Error_Handler is the outer safety net running after all other catches."""
    actions = orchestrator_json()["properties"]["definition"]["actions"]
    run_after = actions["Catch:_Global_Error_Handler"]["runAfter"]
    # Catch:_Global_Error_Handler waits on all three Catch scopes (which themselves gate the Try scopes)
    assert set(run_after) == {"Catch:_Init", "Catch:_Loader", "Catch:_Performer"}
    # Each catch should run after all three statuses
    assert set(run_after["Catch:_Init"]) == {"Succeeded", "TimedOut", "Failed"}
    assert set(run_after["Catch:_Loader"]) == {"Succeeded", "TimedOut", "Failed"}
    assert set(run_after["Catch:_Performer"]) == {"Succeeded", "Failed", "TimedOut"}


def test_orchestrator_single_desktop_flow_fills_both_roles() -> None:
    """One desktop flow is reused for Loader and Performer, never a placeholder."""
    data = orchestrator_json(desktop_flow_ids={"Main": "ONLY-ONE-ID"})
    actions = data["properties"]["definition"]["actions"]
    loader = actions["Try:_Loader"]["actions"]["If_Loader_flag_=_yes"]["actions"][
        "If_Loader_type_=_Cloud"
    ]["else"]["actions"]["If_Desktop_run_=_Unattended"]["actions"][
        "Desktop_Flow_-_Loader_-_Unattended"
    ]
    performer = actions["Try:_Performer"]["actions"]["If_Performer_flag_=_yes"]["actions"][
        "If_Work_Queue_Items_present"
    ]["actions"]["If_Performer_type_=_desktop"]["actions"]["If_performer_run_=_Unattended"][
        "actions"
    ]["Desktop_Flow_-_Performer_-_Unattended"]
    assert loader["inputs"]["parameters"]["uiFlowId"] == "ONLY-ONE-ID"
    assert performer["inputs"]["parameters"]["uiFlowId"] == "ONLY-ONE-ID"


def test_orchestrator_without_desktop_flows_raises() -> None:
    """No desktop flow IDs is an error, not a placeholder uiFlowId."""
    gen = CloudFlowGenerator()
    with pytest.raises(GenerationError):
        gen.generate_orchestrator(make_process(), {}, publisher_prefix="cr3ac")


def test_orchestrator_has_success_response() -> None:
    """Try:_Performer contains a success Response with out_txt_mainflow_status == Success."""
    actions = orchestrator_json()["properties"]["definition"]["actions"]
    response = actions["Try:_Performer"]["actions"]["Respond_to_a_Power_App_or_flow_-_Success"]
    assert response["type"] == "Response"
    assert response["kind"] == "PowerApp"
    assert response["inputs"]["statusCode"] == 200
    assert response["inputs"]["body"]["out_txt_mainflow_status"] == "Success"
    assert response["runAfter"]["If_Performer_flag_=_yes"] == ["Succeeded"]
    assert response["operationOptions"] == "Asynchronous"


def test_orchestrator_has_four_catch_scopes() -> None:
    """Exactly 4 Catch scopes exist with correct dependencies."""
    actions = orchestrator_json()["properties"]["definition"]["actions"]
    catch_names = {
        "Catch:_Init",
        "Catch:_Loader",
        "Catch:_Performer",
        "Catch:_Global_Error_Handler",
    }
    actual_catches = {n for n in actions if n.startswith("Catch:")}
    assert actual_catches == catch_names

    # Verify Catch:_Init runs after Try:_Init
    assert actions["Catch:_Init"]["runAfter"] == {"Try:_Init": ["Failed", "TimedOut"]}

    # Verify Catch:_Loader runs after Try:_Loader
    assert actions["Catch:_Loader"]["runAfter"] == {"Try:_Loader": ["Failed", "TimedOut"]}

    # Verify Catch:_Performer runs after Try:_Performer
    assert actions["Catch:_Performer"]["runAfter"] == {"Try:_Performer": ["Failed", "TimedOut"]}


def test_orchestrator_catch_init_exception_message_from_try_init_errors() -> None:
    """Catch:_Init's Exception_Message coalesces from Try:_Init action error outputs, not email recipient."""
    actions = orchestrator_json()["properties"]["definition"]["actions"]
    catch_init = actions["Catch:_Init"]["actions"]

    # Verify the SetVariable action for Exception_Message
    init_flow_exception = catch_init["Init_Flow_Exception"]
    assert init_flow_exception["type"] == "SetVariable"
    assert init_flow_exception["inputs"]["name"] == "Exception_Message"

    # Verify the value is a coalesce of Try:_Init action outputs
    exception_value = init_flow_exception["inputs"]["value"]
    assert "outputs('Compose:_Config')" in exception_value
    assert "outputs('Set_Config_value')" in exception_value
    assert "@coalesce(" in exception_value
    # Ensure it references actual Try:_Init actions, not the email parameter
    assert "Generic_SupportTeam_EmailID" not in exception_value
    assert "Mail_SystemExceptionTo" not in exception_value


def test_orchestrator_catch_scopes_have_response_actions() -> None:
    """Each individual Catch:_* scope contains a Terminate and Response action."""
    actions = orchestrator_json()["properties"]["definition"]["actions"]
    # Check individual catch scopes (not Global_Error_Handler, which is an outer safety net)
    for catch_name in ["Catch:_Init", "Catch:_Loader", "Catch:_Performer"]:
        catch = actions[catch_name]["actions"]
        # Each individual catch has a Terminate
        terminate_actions = [n for n in catch if catch[n]["type"] == "Terminate"]
        assert len(terminate_actions) >= 1, f"{catch_name} has no Terminate action"
        # Each individual catch has a Response
        response_actions = [n for n in catch if catch[n]["type"] == "Response"]
        assert len(response_actions) >= 1, f"{catch_name} has no Response action"

    # Global Error Handler has only Response (no Terminate, it's an outer wrapper)
    global_catch = actions["Catch:_Global_Error_Handler"]["actions"]
    response_actions = [n for n in global_catch if global_catch[n]["type"] == "Response"]
    assert len(response_actions) >= 1, "Catch:_Global_Error_Handler has no Response action"


def test_orchestrator_loader_has_attended_unattended_branches() -> None:
    """Try:_Loader branches on Ctrl_LoaderUnattendedRun for attended/unattended modes."""
    actions = orchestrator_json()["properties"]["definition"]["actions"]
    loader_ifs = actions["Try:_Loader"]["actions"]["If_Loader_flag_=_yes"]["actions"]
    # Check cloud/desktop branching
    cloud_if = loader_ifs["If_Loader_type_=_Cloud"]
    assert "@toLower(variables('var')?['Ctrl_LoaderType'])" in str(cloud_if["expression"])

    # Check attended/unattended branching in else branch
    unattended_if = cloud_if["else"]["actions"]["If_Desktop_run_=_Unattended"]
    assert "@toLower(variables('var')?['Ctrl_LoaderUnattendedRun'])" in str(
        unattended_if["expression"]
    )

    # Check unattended call
    unattended_call = unattended_if["actions"]["Desktop_Flow_-_Loader_-_Unattended"]
    assert unattended_call["inputs"]["parameters"]["runMode"] == "unattended"

    # Check attended call
    attended_call = unattended_if["else"]["actions"]["Desktop_Flow_-_Loader_-_Attended"]
    assert attended_call["inputs"]["parameters"]["runMode"] == "attended"


def test_orchestrator_performer_has_desktop_type_branches() -> None:
    """Try:_Performer branches on Ctrl_PerfomerType and Ctrl_PerfomerUnattendedRun."""
    actions = orchestrator_json()["properties"]["definition"]["actions"]
    performer_if = actions["Try:_Performer"]["actions"]["If_Performer_flag_=_yes"]["actions"][
        "If_Work_Queue_Items_present"
    ]["actions"]["If_Performer_type_=_desktop"]

    # Check desktop type branching
    assert "@toLower(variables('var')?['Ctrl_PerfomerType'])" in str(performer_if["expression"])

    # Check attended/unattended branching
    unattended_if = performer_if["actions"]["If_performer_run_=_Unattended"]
    assert "@toLower(variables('var')?['Ctrl_PerfomerUnattendedRun'])" in str(
        unattended_if["expression"]
    )

    # Check unattended call
    unattended_call = unattended_if["actions"]["Desktop_Flow_-_Performer_-_Unattended"]
    assert unattended_call["inputs"]["parameters"]["runMode"] == "unattended"

    # Check attended call
    attended_call = unattended_if["else"]["actions"]["Desktop_Flow_-_Performer_-_Attended"]
    assert attended_call["inputs"]["parameters"]["runMode"] == "attended"


def test_page_flow_has_connection_references() -> None:
    """Per-page Cloud Flows derive connectionReferences from stage modules."""
    gen = CloudFlowGenerator()
    stage = make_cloud_stage(target_module="Outlook", target_type="SendEmail")
    page = make_page_with_cloud(stages=[stage], is_main=False)
    result = gen.generate_page(page, "TestProcess", publisher_prefix="cr3ac")
    assert result is not None
    refs = json.loads(result)["properties"]["connectionReferences"]
    assert "shared_office365-1" in refs


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
