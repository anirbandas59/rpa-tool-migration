"""Cloud Flow JSON generator for Power Automate Cloud runtime stages.

Converts CLOUD-runtime annotated stages into Power Automate Cloud Flow JSON.
One .json file per BP page (if it has at least one CLOUD stage).
Pages with zero CLOUD stages produce no file.

Main page → {process_name}_main_cloudflow.json
Sub-pages → {page_name}_cloudflow.json
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from flowsmith.ast.models import BPProcess, BPStage, Runtime, StageType
from flowsmith.exceptions import GenerationError
from flowsmith.generator.connections import (
    DATAVERSE_CONNECTION,
    OFFICE365_CONNECTION,
    UIFLOW_CONNECTION,
    build_cloudflow_connection_references,
    resolve_connection_names,
)
from flowsmith.generator.naming import env_var_parameter_key, env_var_schema_name

# Connections the orchestrator always uses: it invokes desktop flows
# (shared_uiflow), queries the work queue (Dataverse) and mails the global
# error handler output (Office 365).
ORCHESTRATOR_CONNECTIONS = (
    UIFLOW_CONNECTION,
    OFFICE365_CONNECTION,
    DATAVERSE_CONNECTION,
)

# Blue Prism data type → Power Automate flow parameter type.
_PARAMETER_TYPES = {
    "number": "Float",
    "flag": "Bool",
    "collection": "Object",
}


class CloudFlowGenerator:
    """Generate Cloud Flow JSON files for annotated BP processes."""

    def __init__(self, template_dir: Path | None = None) -> None:
        """Initialise Jinja2 environment from templates/cloudflow/.

        Args:
            template_dir: Override for template directory.
                          Defaults to templates/cloudflow/ relative to project root.

        Raises:
            GenerationError: If template directory not found.
        """
        if template_dir is None:
            template_dir = Path.cwd() / "templates" / "cloudflow"

        if not template_dir.exists():
            raise GenerationError(f"Template directory not found: {template_dir.absolute()}")

        self.template_dir = template_dir
        self.env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def generate_process(
        self,
        process: BPProcess,
        output_dir: Path,
        publisher_prefix: str = "new",
    ) -> list[Path]:
        """Generate Cloud Flow JSON files for CLOUD-runtime stages.

        Groups CLOUD stages by page. Each page with at least one CLOUD stage
        becomes one Cloud Flow JSON file. Pages with zero CLOUD stages produce
        no file.

        Args:
            process: Fully annotated BPProcess.
            output_dir: Directory to write .json files.
                        Created if it does not exist.
            publisher_prefix: Publisher customisation prefix used to derive
                connection reference logical names.

        Returns:
            List of Path objects for all generated files.
            Empty list if no CLOUD stages exist.

        Raises:
            GenerationError: If any file cannot be written
                or any template rendering fails.
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        generated_files: list[Path] = []

        try:
            for page in process.pages:
                flow_json = self.generate_page(page, process.name, publisher_prefix)

                if flow_json is None:
                    # Page has no CLOUD stages, skip it
                    continue

                # Sanitise filename
                if page.is_main:
                    filename = f"{self._sanitise_filename(process.name)}_main_cloudflow.json"
                else:
                    filename = f"{self._sanitise_filename(page.name)}_cloudflow.json"

                output_path = output_dir / filename

                # Validate JSON before writing
                try:
                    json.loads(flow_json)
                except json.JSONDecodeError as e:
                    raise GenerationError(
                        f"Generated invalid JSON for page '{page.name}': {e}"
                    ) from e

                output_path.write_text(flow_json, encoding="utf-8")
                generated_files.append(output_path)

        except GenerationError:
            raise
        except Exception as e:
            raise GenerationError(
                f"Failed to generate Cloud Flow files for process '{process.name}': {e}"
            ) from e

        return generated_files

    def generate_page(
        self,
        page,  # BPPage type annotation deferred to avoid circular import
        process_name: str,
        publisher_prefix: str = "new",
    ) -> str | None:
        """Generate Cloud Flow JSON for one page.

        Filters to CLOUD-runtime stages only. Returns None if page has no
        CLOUD stages.

        Args:
            page: The BPPage to generate.
            process_name: Parent process name.
            publisher_prefix: Publisher customisation prefix used to derive
                connection reference logical names.

        Returns:
            JSON string or None if no CLOUD stages.

        Raises:
            GenerationError: If any template rendering fails.
        """
        try:
            # Separate CLOUD stages
            cloud_stages = [
                s
                for s in page.stages
                if s.pa_annotation and s.pa_annotation.runtime == Runtime.CLOUD
            ]

            if not cloud_stages:
                return None

            # Collect variable initializations (DATA stages)
            var_init_actions: dict[str, str] = {}
            for stage in cloud_stages:
                if stage.stage_type == StageType.DATA:
                    var_name = stage.name.replace(" ", "_")
                    var_type = self._map_bp_type_to_cf_type(
                        stage.data_items[0].data_type if stage.data_items else "text"
                    )
                    var_template = self.env.get_template("actions/initialize_variable.json.j2")
                    var_json = var_template.render(
                        var_name=var_name,
                        var_type=var_type,
                        initial_value="",
                        run_after_json=json.dumps({}),
                    )
                    var_init_actions[var_name] = var_json

            # Render action stages inside Try scope
            action_dict_list: dict[str, dict] = {}
            prev_action = None

            for stage in cloud_stages:
                if stage.stage_type == StageType.DATA:
                    continue  # Already handled

                action = self._render_action(stage, prev_action or "")
                action_dict_list.update(action)
                prev_action = stage.name.replace(" ", "_")

            # Build all actions dict
            all_actions_dict: dict[str, dict] = {}

            # Add variable initializations
            for _var_name, var_action_str in var_init_actions.items():
                var_action_dict = json.loads("{" + var_action_str + "}")
                all_actions_dict.update(var_action_dict)

            # Add Try scope with nested actions
            try_scope_dict = {
                "Try": {
                    "type": "Scope",
                    "actions": action_dict_list,
                    "runAfter": {},
                }
            }
            all_actions_dict.update(try_scope_dict)

            # Add Catch scope
            catch_scope_dict = {
                "Catch": {
                    "type": "Scope",
                    "actions": {
                        "Terminate_Flow": {
                            "type": "Terminate",
                            "inputs": {
                                "runStatus": "Failed",
                                "runError": {
                                    "code": "500",
                                    "message": "@variables('ExceptionMessage')",
                                },
                            },
                            "runAfter": {},
                        }
                    },
                    "runAfter": {"Try": ["Failed", "TimedOut"]},
                }
            }
            all_actions_dict.update(catch_scope_dict)

            # Build full flow definition
            flow_definition = {
                "properties": {
                    "definition": {
                        "$schema": "https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#",
                        "contentVersion": "1.0.0.0",
                        "triggers": {
                            "manual": {
                                "type": "Request",
                                "kind": "PowerApp",
                                "inputs": {"schema": {}},
                            }
                        },
                        "actions": all_actions_dict,
                    },
                    "connectionReferences": build_cloudflow_connection_references(
                        resolve_connection_names(
                            s.pa_annotation.target_module for s in cloud_stages
                        ),
                        publisher_prefix,
                    ),
                }
            }

            return json.dumps(flow_definition, indent=2)

        except GenerationError:
            raise
        except Exception as e:
            raise GenerationError(
                f"Failed to generate Cloud Flow for page '{page.name}': {e}"
            ) from e

    # ── Orchestrator Cloud Flow ────────────────────────────────────────────

    def generate_orchestrator(
        self,
        process: BPProcess,
        desktop_flow_ids: dict[str, str],
        publisher_prefix: str = "new",
    ) -> str:
        """Generate the orchestrator Cloud Flow JSON for a whole process.

        The orchestrator is the button-triggered Cloud Flow that drives the
        generated desktop flows: it initialises the shared variables, resolves
        configuration from environment variables, invokes the Loader and
        Performer desktop flows by their WorkflowId, and mails out any failure
        from a global catch scope.

        The `desktop_flow_ids` map must be produced *before* this call — see
        `WorkflowBuilder.prepare_workflow_ids()`. That is what resolves the
        forward reference between the CF JSON and the desktop flow GUIDs.

        Args:
            process: Fully annotated BPProcess.
            desktop_flow_ids: Map of desktop flow page name → WorkflowId GUID.
            publisher_prefix: Publisher customisation prefix used for
                connection reference logical names and env var schema names.

        Returns:
            The orchestrator Cloud Flow JSON as a string.

        Raises:
            GenerationError: If `desktop_flow_ids` is empty, template rendering
                fails, or the rendered result is not valid JSON.
        """
        loader_id, performer_id = self._resolve_role_ids(desktop_flow_ids)

        modules = [
            stage.pa_annotation.target_module
            for page in process.pages
            for stage in page.stages
            if stage.pa_annotation
        ]
        connection_names = resolve_connection_names(modules, always=ORCHESTRATOR_CONNECTIONS)
        connection_references = build_cloudflow_connection_references(
            connection_names, publisher_prefix
        )

        parameters = self._build_parameters(process, publisher_prefix)
        config_compose = self._build_config_compose(process, publisher_prefix)

        try:
            template = self.env.get_template("orchestrator.json.j2")
            rendered = template.render(
                connection_references_json=json.dumps(connection_references, indent=2),
                parameters_json=json.dumps(parameters, indent=2),
                config_compose_json=json.dumps(config_compose, indent=2),
                loader_uiflow_id=loader_id,
                performer_uiflow_id=performer_id,
            )
        except Exception as e:
            raise GenerationError(
                f"Failed to render orchestrator Cloud Flow for '{process.name}': {e}"
            ) from e

        try:
            parsed = json.loads(rendered)
        except json.JSONDecodeError as e:
            raise GenerationError(
                f"Orchestrator Cloud Flow for '{process.name}' is not valid JSON: {e}"
            ) from e

        return json.dumps(parsed, indent=2)

    @staticmethod
    def _resolve_role_ids(desktop_flow_ids: dict[str, str]) -> tuple[str, str]:
        """Pick the Loader and Performer WorkflowIds from the desktop flow map.

        Matches on page name first ("loader" / "performer" or "main"), and
        falls back to positional order. When only one desktop flow exists it
        fills both roles, so the generated CF JSON still references a real
        WorkflowId rather than a placeholder.

        Args:
            desktop_flow_ids: Map of desktop flow page name → WorkflowId GUID.

        Returns:
            Tuple of (loader_workflow_id, performer_workflow_id).

        Raises:
            GenerationError: If `desktop_flow_ids` is empty.
        """
        if not desktop_flow_ids:
            raise GenerationError(
                "Cannot generate an orchestrator Cloud Flow: no desktop flow "
                "WorkflowIds were supplied."
            )

        names = list(desktop_flow_ids)

        loader_name = next((n for n in names if "loader" in n.lower()), names[0])
        performer_name = next(
            (n for n in names if n != loader_name and "performer" in n.lower()),
            next(
                (n for n in names if n != loader_name and "main" in n.lower()),
                next((n for n in names if n != loader_name), loader_name),
            ),
        )

        return desktop_flow_ids[loader_name], desktop_flow_ids[performer_name]

    def _build_parameters(
        self,
        process: BPProcess,
        publisher_prefix: str,
    ) -> dict[str, dict]:
        """Build the Cloud Flow `parameters` section.

        Always emits the two Power Automate built-ins (`$authentication`,
        `$connections`), then one entry per Blue Prism environment variable.
        Processes with no environment variables yield just the built-ins.

        Args:
            process: The BPProcess whose environment variables to project.
            publisher_prefix: Publisher customisation prefix.

        Returns:
            The parameters mapping, keyed by parameter name.
        """
        parameters: dict[str, dict] = {
            "$authentication": {"defaultValue": {}, "type": "SecureObject"},
            "$connections": {"defaultValue": {}, "type": "Object"},
        }

        for env_var in process.environment_variables:
            schema_name = env_var_schema_name(publisher_prefix, env_var.name)
            parameters[env_var_parameter_key(env_var.name, schema_name)] = {
                "defaultValue": env_var.value or "",
                "type": _PARAMETER_TYPES.get(env_var.data_type.lower(), "String"),
                "metadata": {"schemaName": schema_name},
            }

        return parameters

    def _build_config_compose(
        self,
        process: BPProcess,
        publisher_prefix: str,
    ) -> dict[str, str]:
        """Build the Try:_Init Compose inputs that seed the `var` config object.

        Each environment variable becomes one key resolved from the matching
        flow parameter, mirroring how the reference flow hydrates `var` from
        its configuration source.

        Args:
            process: The BPProcess whose environment variables to project.
            publisher_prefix: Publisher customisation prefix.

        Returns:
            Mapping of config key → Power Automate parameter expression.
        """
        compose: dict[str, str] = {}
        for env_var in process.environment_variables:
            schema_name = env_var_schema_name(publisher_prefix, env_var.name)
            key = env_var_parameter_key(env_var.name, schema_name)
            compose[env_var.name] = f"@parameters('{key}')"
        return compose

    def _render_action(self, stage: BPStage, run_after: str) -> dict:
        """Render a single CLOUD stage to a Cloud Flow action dict.

        Never reads stage_type directly — dispatches on
        pa_annotation.target_type and target_module.

        Args:
            stage: An annotated BPStage with CLOUD runtime.
            run_after: Name of the preceding action.

        Returns:
            Dict with action name as key and action definition as value.

        Raises:
            GenerationError: If pa_annotation is None.
        """
        if stage.pa_annotation is None:
            raise GenerationError(
                f"Stage '{stage.name}' (ID: {stage.stage_id}) has no pa_annotation."
            )

        annotation = stage.pa_annotation
        target_type = annotation.target_type
        target_module = annotation.target_module
        action_name = stage.name.replace(" ", "_")
        run_after_dict = {run_after: ["Succeeded"]} if run_after else {}

        # SetVariable
        if target_type == "SetVariable":
            return {
                action_name: {
                    "type": "SetVariable",
                    "inputs": {
                        "name": action_name,
                        "value": "@variables('SomeVar')",
                    },
                    "runAfter": run_after_dict,
                }
            }

        # Condition
        if target_type == "Condition":
            return {
                action_name: {
                    "type": "If",
                    "expression": {"equals": ["@variables('SomeVar')", "true"]},
                    "actions": {
                        "true_branch": {
                            "type": "Compose",
                            "inputs": "# TODO: implement true branch",
                        }
                    },
                    "else": {
                        "actions": {
                            "false_branch": {
                                "type": "Compose",
                                "inputs": "# TODO: implement false branch",
                            }
                        }
                    },
                    "runAfter": run_after_dict,
                }
            }

        # Foreach (loop)
        if target_type == "Foreach":
            return {
                action_name: {
                    "type": "Foreach",
                    "foreach": "@variables('ItemCollection')",
                    "actions": {
                        "ForEach_Item": {
                            "type": "Compose",
                            "inputs": "@items('" + action_name + "')",
                            "runAfter": {},
                        }
                    },
                    "runAfter": run_after_dict,
                }
            }

        # ParseJson
        if target_type == "ParseJson":
            return {
                action_name: {
                    "type": "ParseJson",
                    "inputs": {
                        "content": "@variables('JsonContent')",
                        "schema": {
                            "type": "object",
                            "properties": {"example": {"type": "string"}},
                        },
                    },
                    "runAfter": run_after_dict,
                }
            }

        # Query (array filter)
        if target_type == "Query":
            return {
                action_name: {
                    "type": "Query",
                    "inputs": {
                        "from": "@variables('ItemArray')",
                        "where": "@equals(item()?['field'], 'value')",
                    },
                    "runAfter": run_after_dict,
                }
            }

        # Response (respond to Power App)
        if target_type == "Response":
            return {
                action_name: {
                    "type": "Response",
                    "kind": "http",
                    "inputs": {
                        "statusCode": 200,
                        "body": {
                            "status": "@variables('ResultStatus')",
                        },
                        "schema": {
                            "type": "object",
                            "properties": {"status": {"type": "string"}},
                        },
                    },
                    "runAfter": run_after_dict,
                }
            }

        # Select (select array fields)
        if target_type == "Select":
            return {
                action_name: {
                    "type": "Select",
                    "inputs": {
                        "from": "@variables('ItemArray')",
                        "select": {
                            "id": "@item()?['id']",
                            "name": "@item()?['name']",
                        },
                    },
                    "runAfter": run_after_dict,
                }
            }

        # Workflow (call child flow)
        if target_type == "Workflow":
            return {
                action_name: {
                    "type": "OpenApiConnection",
                    "inputs": {
                        "host": {
                            "apiId": "/providers/Microsoft.PowerApps/apis/shared_logicflows",
                            "connectionName": "shared_logicflows",
                            "operationId": "ExecuteFlow",
                        },
                        "parameters": {
                            "flowId": "{{ child_flow_id }}",
                            "body": {
                                "param1": "@variables('Param1')",
                            },
                        },
                    },
                    "runAfter": run_after_dict,
                }
            }

        # HTTP (for Utility - HTTP VBOs)
        if target_module == "Utility" and "HTTP" in target_type:
            return {
                action_name: {
                    "type": "Http",
                    "inputs": {
                        "method": "GET",
                        "uri": "@variables('RequestUrl')",
                    },
                    "runAfter": run_after_dict,
                }
            }

        # SharePoint (External VBOs)
        if target_module == "External" or "SharePoint" in target_module:
            return {
                action_name: {
                    "type": "OpenApiConnection",
                    "inputs": {
                        "host": {
                            "connectionName": "shared_sharepointonline",
                            "operationId": "GetFileContent",
                            "apiId": "/providers/Microsoft.PowerApps/apis/shared_sharepointonline",
                        },
                        "parameters": {"site": "@variables('SharePointSite')"},
                        "authentication": "@parameters('$authentication')",
                    },
                    "runAfter": run_after_dict,
                }
            }

        # Office365 (Email)
        if target_module == "Outlook" or "Office365" in target_module or "Email" in target_type:
            return {
                action_name: {
                    "type": "OpenApiConnection",
                    "inputs": {
                        "host": {
                            "connectionName": "shared_office365",
                            "operationId": "SendEmailV2",
                            "apiId": "/providers/Microsoft.PowerApps/apis/shared_office365",
                        },
                        "parameters": {
                            "emailMessage": {
                                "to": "@variables('EmailTo')",
                                "subject": "@variables('EmailSubject')",
                                "body": "@variables('EmailBody')",
                            }
                        },
                        "authentication": "@parameters('$authentication')",
                    },
                    "runAfter": run_after_dict,
                }
            }

        # Default: stub for MANUAL or unknown types
        return {
            action_name: {
                "type": "Compose",
                "inputs": f"STUB: {stage.name} — {target_module}.{target_type}",
                "runAfter": run_after_dict,
            }
        }

    @staticmethod
    def _sanitise_filename(name: str) -> str:
        """Sanitise a filename.

        Args:
            name: The filename to sanitise.

        Returns:
            Sanitised filename.
        """
        name = name.replace(" ", "_")
        name = re.sub(r"[^a-zA-Z0-9_]", "", name)
        return name or "flow"

    @staticmethod
    def _map_bp_type_to_cf_type(bp_type: str) -> str:
        """Map Blue Prism type to Cloud Flow type.

        Args:
            bp_type: Blue Prism type.

        Returns:
            Cloud Flow type string.
        """
        mapping = {
            "text": "string",
            "number": "float",
            "flag": "bool",
            "currency": "float",
            "date": "string",
            "time": "string",
            "collection": "array",
            "binary": "string",
        }
        return mapping.get(bp_type.lower(), "string")
