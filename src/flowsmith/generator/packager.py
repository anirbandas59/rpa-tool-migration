"""Solution packager for Power Platform .zip assembly.

Converts generated .robin and Cloud Flow JSON files into a deployment-ready
Power Platform solution package (.zip) that can be imported via:
  pac solution import --path solution.zip

Architecture (Phase 6.4):
  - Embeds full PAD script code in customizations.xml Workflow elements
  - Uses GUID-based RootComponent IDs in solution.xml
  - Creates per-flow metadata (Inputs, Outputs, Dependencies, ConnectionReferences)
  - Generates workflow definitions with complete metadata JSON
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from flowsmith.ast.models import BPProcess
from flowsmith.exceptions import GenerationError
from flowsmith.generator.cloudflow import CloudFlowGenerator
from flowsmith.generator.naming import env_var_schema_name
from flowsmith.generator.workflow_builder import WORKQUEUES_MODULE, WorkflowBuilder


class SolutionPackager:
    """Assemble a Power Platform solution .zip package."""

    def __init__(self, template_dir: Path | None = None) -> None:
        """Initialise Jinja2 environment from templates/report/.

        Args:
            template_dir: Override for template directory.
                          Defaults to templates/report/
                          relative to project root (cwd).

        Raises:
            GenerationError: If template directory not found.
        """
        if template_dir is None:
            template_dir = Path.cwd() / "templates" / "report"

        if not template_dir.exists():
            raise GenerationError(f"Template directory not found: {template_dir.absolute()}")

        self.template_dir = template_dir
        self.env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def package(
        self,
        process: BPProcess,
        robin_dir: Path,
        cloudflow_dir: Path,
        output_path: Path,
        publisher_prefix: str = "flowsmith",
        version: str = "1.0.0.0",
        managed: bool = False,
    ) -> Path:
        """Assemble a Power Platform solution .zip package with embedded definitions.

        Converts annotated BPProcess pages into Workflow elements with embedded
        PAD script definitions in customizations.xml. Uses GUID-based RootComponent
        references in solution.xml.

        Architecture (Phase 6.4):
          - Embeds full .robin script content in <Workflow><Definition> elements
          - Generates complete workflow metadata (Inputs, Outputs, Dependencies)
          - Creates solution.xml with GUID-based RootComponent ids
          - Includes per-flow connection and module references

        Args:
            process:          Fully annotated BPProcess.
            robin_dir:        Directory containing .robin files from PADGenerator.
            cloudflow_dir:    Directory containing .json files from CloudFlowGenerator.
            output_path:      Full path for output .zip file.
            publisher_prefix: PA publisher unique name.
            version:          Solution version string.
            managed:          Whether the solution should be flagged as managed
                               (<Managed>1</Managed>) or unmanaged (<Managed>0</Managed>).

        Returns:
            Path to the created .zip file.

        Raises:
            GenerationError: If input directories missing, files unreadable,
                or .zip cannot be written.
        """
        # Validate input directories exist
        if not robin_dir.exists():
            raise GenerationError(f"Robin directory not found: {robin_dir.absolute()}")
        if not cloudflow_dir.exists():
            raise GenerationError(f"Cloud Flow directory not found: {cloudflow_dir.absolute()}")

        try:
            # Collect files
            robin_files = sorted(robin_dir.glob("*.robin"))
            cf_files = sorted(cloudflow_dir.glob("*.json"))

            # Pass 1 — pre-allocate every WorkflowId.
            #
            # The Cloud Flow orchestrator references desktop flow WorkflowIds
            # via `uiFlowId`, but those GUIDs used to be minted inside
            # build_workflow(), i.e. after the CF JSON would have to exist.
            # Allocating them up front resolves that forward reference without
            # changing the CLI's generate-then-package ordering.
            builder = WorkflowBuilder(publisher_prefix=publisher_prefix)

            packaged_pages = [
                (page, robin_file, self._find_cloudflow_file(page, cf_files))
                for page in process.pages
                if (robin_file := self._find_robin_file(page, robin_files)) is not None
            ]
            pages = [page for page, _robin, _cf in packaged_pages]
            builder.prepare_workflow_ids(pages)
            desktop_flow_ids = builder.desktop_flow_ids(pages)

            # Orchestrator Cloud Flow — only meaningful when the solution
            # actually contains desktop flows to invoke.
            orchestrator_json: str | None = None
            if desktop_flow_ids:
                orchestrator_json = CloudFlowGenerator().generate_orchestrator(
                    process, desktop_flow_ids, publisher_prefix
                )

            # Pass 2 — build the Workflow elements using the allocated GUIDs.
            workflow_ids = []
            for page, robin_file, cf_file in packaged_pages:
                workflow = builder.build_workflow(page, process, robin_file, cf_file)
                workflow_ids.append(workflow["workflow_id"])

            # Prepare template variables
            solution_name = self._sanitise_filename(process.name)

            # A solution needs the WorkQueues (workqueueitem) dependency declared
            # whenever any stage across any page targets the WorkQueues module.
            has_workqueues = any(
                stage.pa_annotation is not None
                and stage.pa_annotation.target_module == WORKQUEUES_MODULE
                for page in process.pages
                for stage in page.stages
            )

            # Render templates with workflow data
            solution_xml = self._render_template(
                "solution_with_guids.xml.j2",
                solution_name=solution_name,
                publisher_prefix=publisher_prefix,
                version=version,
                workflow_ids=workflow_ids,
                managed=1 if managed else 0,
                has_workqueues=has_workqueues,
            )

            content_types_xml = self._render_template("content_types.xml.j2")

            customizations_xml = self._render_template(
                "customizations_workflows.xml.j2",
                workflows=builder.workflows,
            )

            manifest_json = self._build_manifest_stub(solution_name, version)
            dependencies_json = self._build_dependencies_stub()

            # Create output directory if it doesn't exist
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Create .zip file with correct structure
            with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
                # Root level files
                zf.writestr("solution.xml", solution_xml)
                zf.writestr("[Content_Types].xml", content_types_xml)
                zf.writestr("customizations.xml", customizations_xml)

                # Cloud Flow JSON files (if any)
                for cf_file in cf_files:
                    arcname = f"Workflows/{cf_file.name}"
                    zf.write(cf_file, arcname=arcname)

                # Orchestrator Cloud Flow (references the desktop flow GUIDs)
                if orchestrator_json is not None:
                    zf.writestr(
                        f"Workflows/CF_{solution_name}_Cloud_Main.json",
                        orchestrator_json,
                    )

                # Other files
                zf.writestr("Other/ManifestFile.json", manifest_json)
                zf.writestr("Other/DependenciesFile.json", dependencies_json)

                # Environment variable definitions (one folder per variable)
                for env_var in process.environment_variables:
                    schema_name = self._env_var_schema_name(publisher_prefix, env_var.name)
                    env_xml = self._render_template(
                        "environmentvariabledefinition.xml.j2",
                        schema_name=schema_name,
                        display_name=env_var.name,
                        default_value=env_var.value,
                        data_type=env_var.data_type,
                    )
                    arcname = (
                        f"environmentvariabledefinitions/{schema_name}/"
                        "environmentvariabledefinition.xml"
                    )
                    zf.writestr(arcname, env_xml)

            return output_path

        except GenerationError:
            raise
        except Exception as e:
            raise GenerationError(
                f"Failed to package solution for process '{process.name}': {e}"
            ) from e

    def _render_template(self, template_name: str, **kwargs) -> str:
        """Render a Jinja2 template with given context.

        Args:
            template_name: Name of the template file.
            **kwargs: Context variables for template rendering.

        Returns:
            Rendered template as a string.

        Raises:
            GenerationError: If template rendering fails.
        """
        try:
            template = self.env.get_template(template_name)
            return template.render(**kwargs)
        except Exception as e:
            raise GenerationError(f"Failed to render template '{template_name}': {e}") from e

    def _find_robin_file(self, page, robin_files: list[Path]) -> Path | None:
        """Find the .robin file matching a BP page.

        Args:
            page: The BPPage to match.
            robin_files: List of available .robin files.

        Returns:
            Path to matching .robin file, or None if not found.
        """
        # Pages are stored as sanitised filenames
        target_stem = self._sanitise_filename(page.name)

        for robin_file in robin_files:
            if robin_file.stem == target_stem or target_stem in robin_file.stem:
                return robin_file

        return None

    def _find_cloudflow_file(self, page, cf_files: list[Path]) -> Path | None:
        """Find the Cloud Flow JSON file matching a BP page.

        Args:
            page: The BPPage to match.
            cf_files: List of available Cloud Flow JSON files.

        Returns:
            Path to matching JSON file, or None if not found.
        """
        target_stem = self._sanitise_filename(page.name)

        for cf_file in cf_files:
            if cf_file.stem == target_stem or target_stem in cf_file.stem:
                return cf_file

        return None

    @staticmethod
    def _env_var_schema_name(publisher_prefix: str, name: str) -> str:
        """Build the Dataverse schema name for an environment variable.

        Args:
            publisher_prefix: Publisher customisation prefix (e.g. "cr3ac").
            name: Blue Prism environment variable name.

        Returns:
            Schema name of the form <prefix>_<name> with all characters
            outside [A-Za-z0-9_] replaced by underscores.

        Raises:
            GenerationError: If `name` is empty.
        """
        return env_var_schema_name(publisher_prefix, name)

    def _sanitise_filename(self, name: str) -> str:
        """Sanitise a process name for use as a filename.

        Removes or replaces invalid filename characters.

        Args:
            name: The process name to sanitise.

        Returns:
            A filename-safe version of the name.
        """
        # Remove or replace invalid filename characters
        invalid_chars = '<>:"/\\|?*'
        result = name
        for char in invalid_chars:
            result = result.replace(char, "_")
        return result.strip()

    def _build_customizations_stub(self) -> str:
        """Build minimal customizations.xml stub.

        Returns:
            XML string for customizations.xml.
        """
        return (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<ImportExportXml version="9.0.0.0">'
            "<Entities/>"
            "<Roles/>"
            "<Workflows/>"
            "<FieldSecurityProfiles/>"
            "<Templates/>"
            "<EntityMaps/>"
            "<EntityRelationships/>"
            "<OrganizationSettings/>"
            "<optionsets/>"
            "<CustomControls/>"
            "<SolutionPluginAssemblies/>"
            "<EntityDataProviders/>"
            "</ImportExportXml>"
        )

    def _build_manifest_stub(self, solution_name: str, version: str) -> str:
        """Build minimal ManifestFile.json stub.

        Args:
            solution_name: The solution name.
            version: The solution version.

        Returns:
            JSON string for ManifestFile.json.
        """
        manifest = {
            "Version": version,
            "SolutionName": solution_name,
            "ModuleReferences": [],
            "CreatedEngineVersion": {
                "Major": 2,
                "Minor": 43,
                "Build": 0,
            },
        }
        return json.dumps(manifest, indent=2)

    def _build_dependencies_stub(self) -> str:
        """Build minimal DependenciesFile.json stub.

        Returns:
            JSON string for DependenciesFile.json.
        """
        dependencies = {"Dependencies": []}
        return json.dumps(dependencies, indent=2)
