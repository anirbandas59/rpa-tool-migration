"""Tests for the Workflow Builder.

Task 6a: Tests for 4-flow consolidation and orchestrator registration.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from flowsmith.ast.models import (
    BPEnvironmentVariable,
    BPPage,
    BPProcess,
    BPStage,
    ConfidenceBand,
    PAAnnotation,
    Runtime,
    StageType,
)
from flowsmith.generator.workflow_builder import WorkflowBuilder


class TestWorkflowBuilderConsolidation:
    """Tests for 4-flow consolidation: 2 Desktop + 1 Orchestrator Cloud Flow."""

    @pytest.fixture
    def loader_robin_file(self, tmp_path: Path) -> Path:
        """Create a dummy Loader .robin file."""
        file = tmp_path / "process_Loader.robin"
        file.write_text("GLOBAL txt_Status TO \"Idle\"\nFUNCTION 'Loader Page 1'\nEND\n")
        return file

    @pytest.fixture
    def performer_robin_file(self, tmp_path: Path) -> Path:
        """Create a dummy Performer .robin file."""
        file = tmp_path / "process_Performer.robin"
        file.write_text("GLOBAL txt_ItemId TO \"\"\nFUNCTION 'Process Work Items'\nEND\n")
        return file

    @pytest.fixture
    def loader_page(self) -> BPPage:
        """Create a minimal Loader BPPage."""
        stage = BPStage(
            stage_id="loader_s1",
            stage_type=StageType.ACTION,
            name="Fetch Mail",
            data_items=[],
            pa_annotation=PAAnnotation(
                target_type="Mail.GetMails",
                target_module="Mail",
                runtime=Runtime.DESKTOP,
                params_map={},
                confidence=0.90,
                band=ConfidenceBand.AUTO,
                flags=[],
            ),
        )
        return BPPage(
            page_id="loader_p1",
            name="Get Mails",
            stages=[stage],
            is_main=True,
            published=True,
            role="loader",
        )

    @pytest.fixture
    def performer_page(self) -> BPPage:
        """Create a minimal Performer BPPage."""
        stage = BPStage(
            stage_id="perf_s1",
            stage_type=StageType.ACTION,
            name="Process Item",
            data_items=[],
            pa_annotation=PAAnnotation(
                target_type="WorkQueues.ProcessItem",
                target_module="WorkQueues",
                runtime=Runtime.DESKTOP,
                params_map={},
                confidence=0.90,
                band=ConfidenceBand.AUTO,
                flags=[],
            ),
        )
        return BPPage(
            page_id="perf_p1",
            name="Process Work Items",
            stages=[stage],
            is_main=False,
            published=True,
            role="performer",
        )

    @pytest.fixture
    def two_role_process(self, loader_page: BPPage, performer_page: BPPage) -> BPProcess:
        """Create a BPProcess with Loader and Performer pages."""
        return BPProcess(
            process_id="test_consolidation",
            name="ConsolidatedProcess",
            version="1.0",
            pages=[loader_page, performer_page],
            environment_variables=[
                BPEnvironmentVariable(name="Config Key", data_type="text", value="config.xlsx"),
            ],
            source_file="test.bprelease",
        )

    def test_prepare_workflow_ids_allocates_per_page(
        self, loader_page: BPPage, performer_page: BPPage
    ) -> None:
        """prepare_workflow_ids() pre-allocates a WorkflowId for each page."""
        builder = WorkflowBuilder()
        pages = [loader_page, performer_page]
        ids = builder.prepare_workflow_ids(pages)

        assert len(ids) == 2
        assert loader_page.page_id in ids
        assert performer_page.page_id in ids
        assert ids[loader_page.page_id] != ids[performer_page.page_id]

    def test_desktop_flow_ids_filters_to_desktop_pages(
        self, loader_page: BPPage, performer_page: BPPage
    ) -> None:
        """desktop_flow_ids() returns only DESKTOP pages."""
        builder = WorkflowBuilder()
        pages = [loader_page, performer_page]
        builder.prepare_workflow_ids(pages)

        ids = builder.desktop_flow_ids(pages)
        assert len(ids) == 2
        assert loader_page.name in ids
        assert performer_page.name in ids

    def test_build_workflow_creates_workflow_element(
        self,
        two_role_process: BPProcess,
        loader_page: BPPage,
        loader_robin_file: Path,
    ) -> None:
        """build_workflow() creates a single Workflow element for a page."""
        builder = WorkflowBuilder()
        builder.prepare_workflow_ids([loader_page])

        workflow = builder.build_workflow(loader_page, two_role_process, loader_robin_file)

        assert workflow is not None
        assert "workflow_id" in workflow
        assert "name" in workflow
        assert workflow["name"] == "Get Mails"
        assert workflow["category"] == 6  # Desktop flow
        assert workflow["ui_flow_type"] == 2  # Desktop flow marker

    def test_build_workflow_embeds_robin_content(
        self,
        two_role_process: BPProcess,
        loader_page: BPPage,
        loader_robin_file: Path,
    ) -> None:
        """build_workflow() embeds the .robin file content in the Definition."""
        builder = WorkflowBuilder()
        builder.prepare_workflow_ids([loader_page])

        workflow = builder.build_workflow(loader_page, two_role_process, loader_robin_file)

        definition = json.loads(workflow["definition"])
        assert "GLOBAL txt_Status" in definition
        assert "FUNCTION 'Loader Page 1'" in definition


class TestConsolidatedWorkflowGeneration:
    """Integration tests: 4-flow consolidation with real PID_0171 data.

    Task 6a Done-when requirement: "a new test asserts the generated
    customizations.xml-equivalent structure has exactly 2 Desktop Flow
    `<Workflow>` elements + 1 orchestrator `<Workflow>` element for
    PID_0171.bprelease, not N-per-page."
    """

    @pytest.mark.integration
    def test_build_all_workflows_consolidated_produces_3_workflows_for_pid171(
        self,
    ) -> None:
        """Consolidated generation produces exactly 2 desktop + 1 orchestrator workflow.

        This is the core Done-when test for Task 6a. It exercises the full
        real generation pipeline and asserts the final 3-workflow structure.
        """
        from pathlib import Path

        from flowsmith.ast import build_ast
        from flowsmith.engine import create_annotator
        from flowsmith.generator.cloudflow import CloudFlowGenerator
        from flowsmith.generator.pad import PADGenerator
        from flowsmith.generator.workflow_builder import WorkflowBuilder
        from flowsmith.parser import parse_process

        # Parse real PID_0171
        bprelease_path = Path("samples/blueprism/PID_0171.bprelease")
        if not bprelease_path.exists():
            pytest.skip("PID_0171.bprelease not found")

        release = parse_process(bprelease_path)
        process = release["processes"][0]

        # Build AST and annotate
        process = build_ast(process)
        create_annotator().annotate_process(process)

        # Generate .robin files and orchestrator
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Generate consolidated .robin files (Loader, Performer)
            robin_dir = tmpdir_path / "robin"
            PADGenerator().generate_process(process, robin_dir)
            robin_files = sorted(robin_dir.glob("*.robin"))

            assert len(robin_files) == 2, f"Expected 2 .robin files, got {len(robin_files)}"

            # Use consolidated workflow builder with freshly-generated orchestrator
            # This ensures GUID consistency between Desktop Flows and Orchestrator
            builder = WorkflowBuilder()
            cf_gen = CloudFlowGenerator()

            workflows = builder.build_all_workflows_consolidated(
                process=process,
                robin_files=robin_files,
                cloudflow_generator=cf_gen,  # Let the builder generate the orchestrator
            )

            # ASSERTION: Exactly 3 workflows (2 desktop + 1 orchestrator)
            assert len(workflows) == 3, f"Expected 3 workflows, got {len(workflows)}"

            # Check workflow types and names
            categories = [w["category"] for w in workflows]
            names = [w["name"] for w in workflows]

            # 2 desktop (category 6), 1 cloud (category 5)
            assert categories.count(6) == 2, f"Expected 2 desktop flows, got {categories}"
            assert categories.count(5) == 1, (
                f"Expected 1 cloud flow (orchestrator), got {categories}"
            )

            # Check naming follows DF_/CF_ convention from architecture doc §A2
            desktop_names = [n for c, n in zip(categories, names, strict=True) if c == 6]
            cloud_names = [n for c, n in zip(categories, names, strict=True) if c == 5]

            for name in desktop_names:
                assert name.startswith("DF_"), f"Desktop flow name '{name}' must start with DF_"

            assert cloud_names[0].startswith("CF_"), (
                f"Cloud flow name '{cloud_names[0]}' must start with CF_"
            )

            # GUID CONSISTENCY CHECK (Task 6a requirement)
            # Extract Desktop Flow workflow_ids
            desktop_workflow_ids = [w["workflow_id"] for w in workflows if w["category"] == 6]

            # Get the orchestrator workflow
            orchestrator_workflow = [w for w in workflows if w["category"] == 5][0]

            # Verify orchestrator JSON contains references to these exact Desktop Flow GUIDs
            # The "definition" field in the workflow is an escaped JSON string
            orchestrator_definition = json.loads(orchestrator_workflow["definition"])
            # Parse it again to get the actual object (it's a JSON string holding JSON)
            orchestrator_def = json.loads(orchestrator_definition)
            orchestrator_actions = (
                orchestrator_def.get("properties", {}).get("definition", {}).get("actions", {})
            )

            # Find uiFlowId references in the orchestrator (in Try:_Loader and Try:_Performer actions)
            orchestrator_uiflow_ids = set()

            def extract_uiflow_ids(obj):
                """Recursively extract uiFlowId values from nested JSON."""
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        if k == "uiFlowId":
                            orchestrator_uiflow_ids.add(v.strip("{}"))
                        elif isinstance(v, (dict, list)):
                            extract_uiflow_ids(v)
                elif isinstance(obj, list):
                    for item in obj:
                        extract_uiflow_ids(item)

            extract_uiflow_ids(orchestrator_actions)

            # Verify orchestrator uiFlowIds match registered Desktop Flow GUIDs
            desktop_ids_normalized = {gid.strip("{}").lower() for gid in desktop_workflow_ids}
            orchestrator_ids_normalized = {gid.lower() for gid in orchestrator_uiflow_ids}

            assert len(orchestrator_ids_normalized) == 2, (
                f"Orchestrator should reference exactly 2 Desktop Flow GUIDs, "
                f"found {len(orchestrator_ids_normalized)}: {orchestrator_uiflow_ids}"
            )
            assert desktop_ids_normalized == orchestrator_ids_normalized, (
                f"Orchestrator uiFlowIds do not match registered Desktop Flow workflow_ids. "
                f"Desktop: {desktop_ids_normalized}, Orchestrator: {orchestrator_ids_normalized}"
            )

            # Verify orchestrator contains proper structure
            assert orchestrator_workflow["ui_flow_type"] == 0, (
                "Orchestrator should have ui_flow_type=0 (cloud)"
            )
            assert "Cloud_Main" in orchestrator_workflow["name"], (
                "Orchestrator should be named Cloud_Main"
            )

            # Verify desktop flows are properly structured
            for desktop in [w for w in workflows if w["category"] == 6]:
                assert desktop["ui_flow_type"] == 2, "Desktop flows should have ui_flow_type=2"
                assert desktop["category"] == 6, "Desktop flows should have category=6"
                # Verify .robin content is embedded
                definition = json.loads(desktop["definition"])
                assert "FUNCTION" in definition, (
                    "Desktop flow definition should contain FUNCTION blocks"
                )
