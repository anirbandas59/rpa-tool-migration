"""Build Workflow XML elements with embedded PAD script definitions.

Converts generated .robin files and AST metadata into complete Workflow XML
elements suitable for embedding in customizations.xml. Handles:
  - PAD script source embedding (Definition element)
  - Metadata JSON generation (clientversion, schemaVersion, flags)
  - Input/Output schema extraction from AST data items
  - Dependency tracking (child flows, connectors, modules)
  - Connection reference mapping
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from flowsmith.ast.models import BPPage, BPProcess, Runtime
from flowsmith.exceptions import GenerationError
from flowsmith.generator.connections import (
    build_workflow_connection_references,
    resolve_connection_names,
)

# Blue Prism VBO catalogue module name used for Work Queue actions
# (mapping/vbo_catalogue.yaml: pa_module: "WorkQueues"). Any stage annotated
# with this target_module drives the containsActiveWorkQueuesActions
# metadata flag and the workqueues.* Claims entries.
WORKQUEUES_MODULE = "WorkQueues"


class WorkflowBuilder:
    """Builds complete Workflow XML elements with embedded PAD definitions."""

    # Default engine version for generated flows
    CREATED_ENGINE_VERSION = {"Major": 2, "Minor": 43, "Build": 0, "Revision": 0}
    DEFAULT_SCHEMA_VERSION = "2022.07"
    DEFAULT_ROBIN_SCHEMA = "ROBIN_20211012"

    def __init__(self, publisher_prefix: str = "new") -> None:
        """Initialise the workflow builder.

        Args:
            publisher_prefix: Publisher customisation prefix used to derive
                connection reference logical names.
        """
        self.workflows: list[dict[str, Any]] = []
        self.publisher_prefix = publisher_prefix
        # page_id → WorkflowId, populated by prepare_workflow_ids().
        self._page_workflow_ids: dict[str, str] = {}

    def prepare_workflow_ids(self, pages: Iterable[BPPage]) -> dict[str, str]:
        """Pre-allocate a WorkflowId for every page, before any build.

        The Cloud Flow orchestrator has to reference desktop flow WorkflowIds
        (`uiFlowId`) that `build_workflow()` would otherwise mint lazily,
        creating a forward reference. Calling this first fixes every GUID up
        front; `build_workflow()` then reuses the pre-allocated value.

        Idempotent: a page that already has an allocated ID keeps it.

        Args:
            pages: The pages that will be packaged as Workflow elements.

        Returns:
            Map of page_id → WorkflowId GUID for the supplied pages.
        """
        allocated: dict[str, str] = {}
        for page in pages:
            workflow_id = self._page_workflow_ids.get(page.page_id)
            if workflow_id is None:
                workflow_id = str(uuid.uuid4()).upper()
                self._page_workflow_ids[page.page_id] = workflow_id
            allocated[page.page_id] = workflow_id
        return allocated

    def desktop_flow_ids(self, pages: Iterable[BPPage]) -> dict[str, str]:
        """Return the pre-allocated WorkflowIds of the desktop (PAD) pages.

        Args:
            pages: The pages that will be packaged as Workflow elements.
                  Must already have been passed to `prepare_workflow_ids()`.

        Returns:
            Map of page name → WorkflowId GUID, restricted to DESKTOP pages
            that have an allocated ID. Empty when the process has no desktop
            flows.
        """
        return {
            page.name: self._page_workflow_ids[page.page_id]
            for page in pages
            if self._page_runtime(page) != Runtime.CLOUD and page.page_id in self._page_workflow_ids
        }

    def build_workflow(
        self,
        page: BPPage,
        process: BPProcess,
        robin_file: Path,
        json_file: Path | None = None,
    ) -> dict[str, Any]:
        """Build a complete Workflow element for a BP page.

        Args:
            page: The BPPage to build from.
            process: The parent BPProcess (for name context).
            robin_file: Path to the generated .robin file containing PAD script.
            json_file: Optional path to the page's Cloud Flow JSON file.
                Retained for caller compatibility; the Workflow element's
                <JsonFileName> is always the generated
                "<Name>-<WorkflowId>.json" manifest, not this file.

        Returns:
            Dictionary containing workflow XML element data ready for templating.

        Raises:
            GenerationError: If robin_file cannot be read or is empty.
        """
        try:
            # Read the .robin file content
            if not robin_file.exists():
                raise GenerationError(f"Robin file not found: {robin_file}")

            robin_content = robin_file.read_text(encoding="utf-8")
            if not robin_content.strip():
                raise GenerationError(f"Robin file is empty: {robin_file}")

            # Escape the content for XML/JSON embedding
            escaped_definition = self._escape_definition(robin_content)

            # Extract metadata from the AST
            inputs_schema = self._build_inputs_schema(page)
            outputs_schema = self._build_outputs_schema(page)
            dependencies = self._build_dependencies(page)
            connection_refs = self._build_connection_references(page)

            # Build metadata JSON
            metadata = self._build_metadata(page)

            # Reuse the GUID pre-allocated by prepare_workflow_ids() so the
            # Cloud Flow orchestrator's uiFlowId references stay valid.
            workflow_id = self._page_workflow_ids.get(page.page_id)
            if workflow_id is None:
                workflow_id = str(uuid.uuid4()).upper()
                self._page_workflow_ids[page.page_id] = workflow_id

            # Category/UIFlowType depend on whether the page is a desktop
            # (PAD .robin) flow or a cloud (Power Automate) flow.
            page_runtime = self._page_runtime(page)
            category = 5 if page_runtime == Runtime.CLOUD else 6
            ui_flow_type = 0 if page_runtime == Runtime.CLOUD else 2

            # Build the workflow element
            workflow = {
                "workflow_id": workflow_id,
                "name": page.name,
                # Reference convention: "<Name>-<WorkflowId>.json". The packager
                # writes this file, so <JsonFileName> always resolves inside
                # the .zip. `json_file` (the per-page Cloud Flow JSON) is kept
                # as a separate payload and is not the workflow's own manifest.
                "json_file_name": f"{self._sanitise_name(page.name)}-{workflow_id}.json",
                "type": 1,  # Workflow type
                "subprocess": 0,
                "category": category,  # 6 = desktop flow, 5 = cloud flow
                "mode": 0,
                "scope": 4,
                "on_demand": 0,
                "trigger_on_create": 0,
                "trigger_on_delete": 0,
                "async_autodelete": 0,
                "sync_workflow_log_on_failure": 0,
                "state_code": 1,
                "status_code": 2,
                "run_as": 1,
                "is_transacted": 1,
                "introduced_version": "1.0",
                "is_customizable": 1,
                "business_process_type": 0,
                "ui_flow_type": ui_flow_type,  # 2 = desktop flow marker, 0 = cloud flow
                "is_custom_processing_step_allowed_for_other_publishers": 1,
                "modern_flow_type": 0,
                "metadata": metadata,
                "inputs": inputs_schema,
                "outputs": outputs_schema,
                "dependencies": dependencies,
                "connection_references": connection_refs,
                "definition": escaped_definition,
                "schema_version": self.DEFAULT_SCHEMA_VERSION,
                "claims": self._build_claims(page),
                "primary_entity": "none",
                "localized_name": page.name,
                "localized_description": f"Generated by Flowsmith from {process.name}",
            }

            self.workflows.append(workflow)
            return workflow

        except GenerationError:
            raise
        except Exception as e:
            raise GenerationError(f"Failed to build workflow for page '{page.name}': {e}") from e

    @staticmethod
    def _sanitise_name(name: str) -> str:
        """Make a page name safe for use inside a zip entry path.

        Args:
            name: Blue Prism page name.

        Returns:
            The name with every character outside [A-Za-z0-9_-] replaced by
            an underscore.
        """
        return "".join(ch if (ch.isalnum() or ch in "_-") else "_" for ch in name)

    @staticmethod
    def build_definition_json(workflow: dict[str, Any]) -> str:
        """Build the per-workflow manifest JSON referenced by <JsonFileName>.

        Every Workflow element in customizations.xml names a JSON file under
        `Workflows/`. For a desktop flow that file is a thin manifest — the
        PAD script itself lives in <Definition> — carrying only the inputs and
        outputs schemas, mirroring the reference managed solution's
        `DF_PID_171_US_Loader-*.json`.

        Args:
            workflow: A workflow dict as returned by `build_workflow()`.

        Returns:
            The manifest as a JSON string.

        Raises:
            GenerationError: If the workflow's inputs/outputs are not valid JSON.
        """
        try:
            inputs = json.loads(workflow["inputs"])
            outputs = json.loads(workflow["outputs"])
        except (KeyError, ValueError) as e:
            raise GenerationError(
                f"Cannot build manifest JSON for workflow '{workflow.get('name')}': {e}"
            ) from e

        manifest = {
            "properties": {
                "definition": {"package": ""},
                "inputs": inputs,
                "outputs": outputs,
            },
            "schemaversion": "ROBIN_202208_DVRS",
        }
        return json.dumps(manifest, indent=1)

    def _escape_definition(self, robin_content: str) -> str:
        """Encode PAD script as the JSON string literal held by <Definition>.

        The reference managed solution stores the whole .robin script as a
        single quoted JSON string with CRLF line endings, so line breaks are
        normalised to `\\r\\n` before encoding.

        Encoding goes through `json.dumps` rather than hand-rolled
        replacements: tabs and other C0 control characters are illegal raw
        inside a JSON string, and generated .robin bodies are tab-indented.
        `ensure_ascii=False` keeps non-ASCII characters literal, matching the
        reference (the surrounding XML document is UTF-8).

        Args:
            robin_content: Raw PAD script source code.

        Returns:
            A complete JSON string literal, including the surrounding quotes.
        """
        # Normalise every line ending to CRLF, matching the reference solution.
        normalized = robin_content.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")
        return json.dumps(normalized, ensure_ascii=False)

    def _page_runtime(self, page: BPPage) -> Runtime:
        """Classify a page as a Cloud Flow or a Desktop (PAD) flow.

        A page is treated as CLOUD only when every annotated stage on it
        targets the CLOUD runtime. Any DESKTOP-targeted stage makes the
        whole page a DESKTOP flow, since a .robin script always executes
        as a single desktop process even when individual actions (e.g.
        WorkQueues) are annotated CLOUD in the VBO catalogue. A page with
        no annotated stages defaults to DESKTOP.

        Args:
            page: The BPPage to classify.

        Returns:
            Runtime.CLOUD if every annotated stage targets CLOUD,
            otherwise Runtime.DESKTOP.
        """
        annotated = [stage.pa_annotation for stage in page.stages if stage.pa_annotation]
        if not annotated:
            return Runtime.DESKTOP
        if all(annotation.runtime == Runtime.CLOUD for annotation in annotated):
            return Runtime.CLOUD
        return Runtime.DESKTOP

    def _page_has_workqueues(self, page: BPPage) -> bool:
        """Check whether any stage on the page targets the WorkQueues module.

        Args:
            page: The BPPage to inspect.

        Returns:
            True if any stage's pa_annotation.target_module == "WorkQueues".
        """
        return any(
            stage.pa_annotation is not None
            and stage.pa_annotation.target_module == WORKQUEUES_MODULE
            for stage in page.stages
        )

    def _build_inputs_schema(self, page: BPPage) -> str:
        """Build JSON schema for workflow inputs from page data items.

        Args:
            page: The BPPage to extract inputs from.

        Returns:
            JSON string containing the inputs schema.
        """
        input_items = {}
        required_inputs = []

        for stage in page.stages:
            for data_item in stage.data_items:
                if data_item.is_input and data_item.name not in input_items:
                    input_items[data_item.name] = {
                        "isOptional": False,
                        "default": data_item.initial_value or "",
                        "description": "",
                        "type": self._map_bp_type_to_json_type(data_item.data_type),
                        "title": data_item.name,
                    }
                    required_inputs.append(data_item.name)

        if not input_items:
            return json.dumps({"schema": None}, separators=(",", ":"))

        schema = {
            "schema": {
                "type": "object",
                "required": required_inputs,
                "properties": input_items,
            }
        }
        return json.dumps(schema, separators=(",", ":"))

    def _build_outputs_schema(self, page: BPPage) -> str:
        """Build JSON schema for workflow outputs from page data items.

        Args:
            page: The BPPage to extract outputs from.

        Returns:
            JSON string containing the outputs schema.
        """
        output_items = {}

        for stage in page.stages:
            for data_item in stage.data_items:
                if data_item.is_output and data_item.name not in output_items:
                    output_items[data_item.name] = {
                        "type": self._map_bp_type_to_json_type(data_item.data_type),
                        "description": "",
                    }

        if not output_items:
            return json.dumps({"schema": None}, separators=(",", ":"))

        schema = {
            "schema": {
                "type": "object",
                "properties": output_items,
            }
        }
        return json.dumps(schema, separators=(",", ":"))

    def _build_dependencies(self, page: BPPage) -> str:
        """Build dependency object referencing connectors and modules.

        Args:
            page: The BPPage to extract dependencies from.

        Returns:
            JSON string containing dependencies structure.
        """
        child_flows = []
        required_binaries = []

        # Extract module references from annotations
        modules_seen = set()
        for stage in page.stages:
            if stage.pa_annotation:
                module = stage.pa_annotation.target_module
                if module and module not in modules_seen:
                    modules_seen.add(module)
                    # Each module gets a GUID placeholder
                    required_binaries.append(str(uuid.uuid4()).upper())

        dependencies = {
            "childFlows": child_flows,
            "workQueues": [],
            "environmentVariables": [],
            "requiredBinaries": required_binaries,
        }
        return json.dumps(dependencies, separators=(",", ":"))

    def _build_connection_references(self, page: BPPage) -> str:
        """Build connection references for cloud connectors used by the flow.

        Derived from the `target_module` of every annotated stage on the page
        (see `flowsmith.generator.connections`), so the same derivation drives
        both this element and the Cloud Flow `connectionReferences` mapping.

        Args:
            page: The BPPage to extract connector references from.

        Returns:
            JSON string containing connection references array.
        """
        connection_names = resolve_connection_names(
            stage.pa_annotation.target_module for stage in page.stages if stage.pa_annotation
        )
        connections = build_workflow_connection_references(connection_names, self.publisher_prefix)
        return json.dumps(connections, separators=(",", ":"))

    def _build_metadata(self, page: BPPage) -> str:
        """Build metadata JSON object for the workflow.

        Args:
            page: The BPPage being packaged.

        Returns:
            JSON string containing workflow metadata.
        """
        metadata = {
            "clientversion": "2.69.217.26166",
            "isvalid": True,
            "$schema": "https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#",
            "schemaVersion": self.DEFAULT_ROBIN_SCHEMA,
            "containsActiveConnections": False,
            "containsGptPredictActions": False,
            "containsActiveCopilotActions": False,
            "containsActiveWorkQueuesActions": self._page_has_workqueues(page),
            "containsActiveLogMessageActions": False,
            "containsActiveRepairWithAIActions": False,
            "containsActiveCredentialsActions": False,
            "multipleRequestsState": 0,
            "scriptType": 0,
            "disableScreenshotCaptureOnError": False,
            "missingUiElementRepairType": None,
            "flowTimeout": None,
            "screenResolution": None,
            "flowLogsVerbosity": None,
            "flowGeneratedBy": "Flowsmith",
        }
        return json.dumps(metadata, separators=(",", ":"))

    def _build_claims(self, page: BPPage) -> list[dict[str, str]]:
        """Build Claims array based on page requirements.

        Args:
            page: The BPPage being packaged.

        Returns:
            List of deduplicated claim dictionaries, in first-seen order.
        """
        claim_names: list[str] = ["selfheal"]

        if self._page_has_workqueues(page):
            claim_names.append("workqueues.items.get")

        # Deduplicate while preserving first-seen order.
        seen: set[str] = set()
        claims = []
        for name in claim_names:
            if name not in seen:
                seen.add(name)
                claims.append({"name": name})

        return claims

    def _map_bp_type_to_json_type(self, bp_type: str) -> str:
        """Map Blue Prism data type to JSON Schema type.

        Args:
            bp_type: Blue Prism data type string.

        Returns:
            JSON Schema type string.
        """
        bp_type_lower = bp_type.lower()
        if "number" in bp_type_lower or "integer" in bp_type_lower:
            return "number"
        elif "flag" in bp_type_lower or "boolean" in bp_type_lower:
            return "boolean"
        elif "collection" in bp_type_lower or "list" in bp_type_lower:
            return "array"
        else:
            return "object" if "custom" in bp_type_lower else "string"
