"""Solution packager for Power Platform .zip assembly.

Converts generated .robin and Cloud Flow JSON files into a deployment-ready
Power Platform solution package (.zip) that can be imported via:
  pac solution import --path solution.zip
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from flowsmith.ast.models import BPProcess
from flowsmith.exceptions import GenerationError


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
    ) -> Path:
        """Assemble a Power Platform solution .zip package.

        Collects all generated .robin and .json files and
        packs them into a solution .zip ready for
        pac solution import.

        Args:
            process:          Annotated BPProcess (for names).
            robin_dir:        Directory containing .robin files
                              from PADGenerator.
            cloudflow_dir:    Directory containing .json files
                              from CloudFlowGenerator.
            output_path:      Full path for output .zip file.
                              Parent created if missing.
            publisher_prefix: PA publisher unique name.
            version:          Solution version string.

        Returns:
            Path to the created .zip file.

        Raises:
            GenerationError: If robin_dir or cloudflow_dir
                do not exist, or if .zip cannot be written.
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

            # Prepare template variables
            solution_name = self._sanitise_filename(process.name)
            cloud_flow_names = [f.stem for f in cf_files]
            desktop_flow_names = [f.stem for f in robin_files]

            # Render templates
            solution_xml = self._render_template(
                "solution.xml.j2",
                solution_name=solution_name,
                publisher_prefix=publisher_prefix,
                version=version,
                cloud_flow_names=cloud_flow_names,
                desktop_flow_names=desktop_flow_names,
            )

            content_types_xml = self._render_template("content_types.xml.j2")

            # Build stub files
            customizations_xml = self._build_customizations_stub()
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

                # Cloud Flow JSON files
                for cf_file in cf_files:
                    arcname = f"Workflows/{cf_file.name}"
                    zf.write(cf_file, arcname=arcname)

                # Desktop Flow .robin files
                for robin_file in robin_files:
                    arcname = f"DesktopFlows/{robin_file.name}"
                    zf.write(robin_file, arcname=arcname)

                # Other files
                zf.writestr("Other/ManifestFile.json", manifest_json)
                zf.writestr("Other/DependenciesFile.json", dependencies_json)

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
