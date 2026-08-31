"""PAD .robin file generator using Jinja2 templates.

Converts an annotated BPProcess into consolidated .robin files for Power Automate Desktop flows.
Task 5a: 2 consolidated files (Loader, Performer), each containing multiple FUNCTION blocks
for pages with that role, instead of one file per page.

Main page stages split by role boundary (Get Next Item stage).
Sub-pages rendered based on page-shape mapping (function/inline_block/fold/split).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from flowsmith.ast.models import BPProcess, BPStage, ConfidenceBand, StageType
from flowsmith.exceptions import GenerationError
from flowsmith.generator.naming import flow_file_stem

# Data types that always make a variable sensitive in the generated @SENSITIVE list.
SENSITIVE_DATA_TYPES: frozenset[str] = frozenset({"password", "binary"})

# Substrings that mark a variable name as sensitive (matched case-insensitively).
SENSITIVE_NAME_TOKENS: tuple[str, ...] = ("pass", "key", "secret", "pwd")

# Structural stage types rendered directly from stage_type rather than from
# pa_annotation.target_type. mapping/stage_rules.yaml deliberately leaves
# pa_target_action empty for Block/Recover/Resume (they are scope markers, not
# PAD actions), so there is nothing in the annotation to route on — the Robin
# construct is determined by the stage's structural role alone.
STRUCTURAL_STAGE_TYPES: frozenset[StageType] = frozenset(
    {StageType.BLOCK, StageType.RECOVER, StageType.RESUME}
)

# GOTO targets emitted by RECOVER/RESUME stages. Each needs a matching LABEL
# in the same FUNCTION or the generated .robin script will not compile.
GOTO_ERROR_BLOCK = "GOTO 'Error Block'"
GOTO_END = "GOTO 'End'"

# Main Page split point (Get Next Item stage ID, per architecture doc §B11)
GET_NEXT_ITEM_STAGE_ID = "85fbb578-f410-4f72-8ca9-58513939bc51"


class PADGenerator:
    """Generate .robin files for annotated BP processes."""

    def __init__(self, template_dir: Path | None = None, mapping_file: Path | None = None) -> None:
        """Initialise Jinja2 environment from templates/pad/.

        Args:
            template_dir: Override for template directory.
                          Defaults to templates/pad/ relative to project root.
            mapping_file: Override for page_target_map.yaml location.
                          Defaults to mapping/page_target_map.yaml relative to project root.

        Raises:
            GenerationError: If template directory not found.
        """
        if template_dir is None:
            template_dir = Path.cwd() / "templates" / "pad"

        if not template_dir.exists():
            raise GenerationError(f"Template directory not found: {template_dir.absolute()}")

        self.template_dir = template_dir
        self.env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )

        # Load page_target_map.yaml for shape mapping
        if mapping_file is None:
            mapping_file = Path.cwd() / "mapping" / "page_target_map.yaml"

        self.page_target_map: dict[str, Any] = {}
        if mapping_file.exists():
            try:
                with open(mapping_file, encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    if data:
                        self.page_target_map = data
            except Exception as e:
                raise GenerationError(f"Failed to load page_target_map.yaml: {e}") from e

    def generate_process(
        self,
        process: BPProcess,
        output_dir: Path,
    ) -> list[Path]:
        """Generate consolidated .robin files for an annotated BPProcess.

        Task 5a: Generates 2 files (one per role: Loader, Performer),
        each containing multiple FUNCTION blocks for reachable pages with that role.

        Args:
            process: Fully annotated BPProcess.
            output_dir: Directory to write .robin files.
                        Created if it does not exist.

        Returns:
            List of Path objects for all generated files.

        Raises:
            GenerationError: If any file cannot be written
                or any template rendering fails.
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        generated_files: list[Path] = []

        try:
            # Consolidate pages by role (Loader/Performer)
            loader_content = self._generate_consolidated_flow(process, role="loader")
            performer_content = self._generate_consolidated_flow(process, role="performer")

            # Write Loader file
            if loader_content:
                loader_filename = f"{self._sanitise_filename(process.name)}_Loader.robin"
                loader_path = output_dir / loader_filename
                loader_path.write_text(loader_content, encoding="utf-8")
                generated_files.append(loader_path)

            # Write Performer file
            if performer_content:
                performer_filename = f"{self._sanitise_filename(process.name)}_Performer.robin"
                performer_path = output_dir / performer_filename
                performer_path.write_text(performer_content, encoding="utf-8")
                generated_files.append(performer_path)

        except Exception as e:
            raise GenerationError(
                f"Failed to generate consolidated .robin files for process '{process.name}': {e}"
            ) from e

        return generated_files

    def generate_page(
        self,
        page,  # BPPage type annotation deferred to avoid circular import
        process_name: str,
    ) -> str:
        """Generate Robin script content for one BP page (legacy method for testing).

        This method exists for backward compatibility with tests that expect per-page rendering.
        In the new Task 5a architecture, pages are rendered as part of consolidated flows by role.

        For testing purposes, this renders a single page as if it were a standalone flow.

        Args:
            page: The BPPage to generate.
            process_name: Name of the parent process (used in header comments).

        Returns:
            Complete Robin script as a string.

        Raises:
            GenerationError: If any template rendering fails.
        """
        try:
            lines: list[str] = []

            # Flow header
            input_vars = []
            for stage in page.stages:
                for data_item in stage.data_items:
                    if data_item.is_input:
                        input_vars.append(
                            {
                                "name": data_item.name,
                                "data_type": self._map_bp_type_to_robin(data_item.data_type),
                                "is_optional": False,
                            }
                        )

            header_template = self.env.get_template("flow_header.robin.j2")
            header = header_template.render(
                inputs=input_vars,
                outputs=[],
                sensitive_vars=self._collect_sensitive_vars(page.stages),
            )
            lines.append(header)

            # Provenance banner
            lines.append("# Generated by Flowsmith")
            lines.append(f"# Process: {process_name}")
            lines.append(f"# Page: {page.name}")
            lines.append(f"# Stages: {len(page.stages)}")
            lines.append("")

            # Render one FUNCTION block per page
            action_lines: list[str] = []
            for stage in page.stages:
                rendered = self._render_stage(stage)
                if rendered:
                    action_lines.append(rendered)

            actions_content = "\n".join(action_lines)
            epilogue = self._render_goto_epilogue(actions_content)
            if epilogue:
                actions_content = f"{actions_content}\n{epilogue}"

            subflow_template = self.env.get_template("subflow.robin.j2")
            subflow = subflow_template.render(
                subflow_name=self._sanitise_filename(page.name),
                actions=actions_content,
                construct_type="function",
                is_global=False,
            )
            lines.append(subflow)

            return "\n".join(lines)

        except Exception as e:
            raise GenerationError(f"Failed to generate Robin for page '{page.name}': {e}") from e

    def _generate_consolidated_flow(
        self,
        process: BPProcess,
        role: str,
    ) -> str:
        """Generate one consolidated .robin file for a single role (Loader/Performer).

        Combines the main page (split by role) and all sub-pages with matching role
        into one file, with each page becoming a FUNCTION (or BLOCK/fold content) within.

        Args:
            process: The BPProcess.
            role: Either "loader" or "performer".

        Returns:
            Complete Robin script as a string, or empty string if no reachable pages for this role.

        Raises:
            GenerationError: If any template rendering fails.
        """
        try:
            lines: list[str] = []

            # Get the main page (if it exists)
            main_page = next((p for p in process.pages if p.is_main), None)

            # Collect all reachable pages for this role
            pages_for_role: list[Any] = []
            for page in process.pages:
                # Skip unreachable pages (Task 4a)
                if not page.reachable:
                    continue

                # Main page gets special treatment (split by role)
                if page.is_main:
                    # Will be handled separately below
                    continue

                # Sub-pages: include if role matches
                if page.role == role:
                    pages_for_role.append(page)

            # If no pages and no main content for this role, return empty
            if not pages_for_role and not main_page:
                return ""

            # Determine input vars from all pages for this role
            input_vars: list[dict[str, Any]] = []
            seen_inputs: set[str] = set()

            # Collect from main page if it exists
            if main_page:
                for stage in main_page.stages:
                    for data_item in stage.data_items:
                        if data_item.is_input and data_item.name not in seen_inputs:
                            input_vars.append(
                                {
                                    "name": data_item.name,
                                    "data_type": self._map_bp_type_to_robin(data_item.data_type),
                                    "is_optional": False,
                                }
                            )
                            seen_inputs.add(data_item.name)

            # Collect from sub-pages
            for page in pages_for_role:
                for stage in page.stages:
                    for data_item in stage.data_items:
                        if data_item.is_input and data_item.name not in seen_inputs:
                            input_vars.append(
                                {
                                    "name": data_item.name,
                                    "data_type": self._map_bp_type_to_robin(data_item.data_type),
                                    "is_optional": False,
                                }
                            )
                            seen_inputs.add(data_item.name)

            # Collect sensitive vars from all pages for this role
            sensitive_vars: list[str] = []
            seen_sensitive: set[str] = set()
            if main_page:
                for var in self._collect_sensitive_vars(main_page.stages):
                    if var not in seen_sensitive:
                        sensitive_vars.append(var)
                        seen_sensitive.add(var)
            for page in pages_for_role:
                for var in self._collect_sensitive_vars(page.stages):
                    if var not in seen_sensitive:
                        sensitive_vars.append(var)
                        seen_sensitive.add(var)

            # Flow header (@@ConnectionString / @@Type / IMPORT / @SENSITIVE / @INPUT / @OUTPUT)
            # Must be the very first content of every .robin script
            # Output vars are not determined at this stage (Task 5b work); provide empty list
            header_template = self.env.get_template("flow_header.robin.j2")
            header = header_template.render(
                inputs=input_vars,
                outputs=[],
                sensitive_vars=sensitive_vars,
            )
            lines.append(header)

            # Provenance banner — after the directives, before the content
            lines.append("# Generated by Flowsmith")
            lines.append(f"# Process: {process.name}")
            lines.append(f"# Role: {role.capitalize()}")
            lines.append("")

            # Render main page content (split by role)
            if main_page:
                main_content = self._render_main_page_for_role(main_page, process, role)
                if main_content:
                    lines.append(main_content)
                    lines.append("")

            # Render sub-pages as FUNCTION blocks (or inline/fold if mapped)
            process_map = self.page_target_map.get(process.name, {})
            rendered_functions: list[str] = []
            seen_function_names: set[str] = set()
            for page in pages_for_role:
                # Skip pages that are shaped as inline_block/fold — they're rendered
                # on-demand when called, not as top-level entities.
                # BUT: split-shaped pages SHOULD be rendered (they emit multiple FUNCTIONs)
                shape_info = self._get_page_shape(page.name, process_map)
                shape = shape_info.get("shape", "function")
                if shape in ("inline_block", "fold"):
                    # These will be rendered when called from other pages
                    continue

                # De-duplication: skip if this function name has already been rendered
                # This handles cases where multiple BP pages map to the same target function
                # (e.g., "Mark as read mail" and "Mark as read and move to exception folder"
                # both map to target_name "Move Emails" per §B14 rows 10-11)
                target_name = shape_info.get("target_name", page.name)
                if target_name in seen_function_names:
                    # FUNCTION with this name already emitted; skip the duplicate
                    # (cite the first occurrence; the mapping file notes parameterization)
                    continue

                page_content = self._render_page_in_consolidated_flow(page, process, process_map)
                if page_content:
                    rendered_functions.append(page_content)
                    lines.append(page_content)
                    lines.append("")
                    # Track this function name to prevent duplicates
                    seen_function_names.add(target_name)

            # Emit boilerplate "Get Error" FUNCTION if any page references it
            full_content = "\n".join(lines)
            if "CALL 'Get Error'" in full_content and "FUNCTION 'Get Error'" not in full_content:
                get_error_fn = self._render_get_error_boilerplate()
                lines.append(get_error_fn)
                lines.append("")

            # Only return if we have content beyond the header
            if len(lines) > 3:  # header + banner lines + empty line
                return "\n".join(lines).rstrip("\n") + "\n"

            return ""

        except Exception as e:
            raise GenerationError(
                f"Failed to generate consolidated flow for role '{role}': {e}"
            ) from e

    def _render_main_page_for_role(
        self,
        main_page: Any,
        process: BPProcess,
        role: str,
    ) -> str:
        """Render Main Page stages split by role (Get Next Item boundary).

        Per architecture doc §B11, Get Next Item (stage ID 85fbb578...) is the split point.
        Pre-split stages (0-13) route to their target's role (via mapping).
        Post-split stages (14+) route to Performer.

        Args:
            main_page: The main BPPage.
            process: The BPProcess.
            role: Either "loader" or "performer".

        Returns:
            Rendered Robin content for Main Page's role-appropriate stages (no FUNCTION wrapper).
        """
        try:
            process_map = self.page_target_map.get(process.name, {})

            # Find the split point (Get Next Item)
            split_index = None
            for idx, stage in enumerate(main_page.stages):
                if stage.stage_id == GET_NEXT_ITEM_STAGE_ID:
                    split_index = idx
                    break

            # Collect stages to render for this role:
            # - Loader: all pre-split stages that target Loader role + post-split loader-role targets
            # - Performer: all pre-split stages that target Performer role + all post-split stages
            stages_to_render: list[BPStage] = []

            if split_index is not None:
                # Pre-split stages (0 to split_index, not including split point)
                pre_split = main_page.stages[:split_index]
                # Post-split stages (split_index onward)
                post_split = main_page.stages[split_index:]
            else:
                # No split found, treat all stages as pre-split
                pre_split = main_page.stages
                post_split = []

            # Add pre-split stages that target this role
            for stage in pre_split:
                if stage.is_subsheet_call:
                    target_page = next(
                        (p for p in process.pages if p.page_id == stage.processid), None
                    )
                    if target_page and target_page.role == role:
                        stages_to_render.append(stage)
                else:
                    # Non-call stages in pre-split go to both Loader and Performer
                    # (they're infrastructure stages like START/END)
                    stages_to_render.append(stage)

            # Add post-split stages (all go to Performer by default)
            if role == "performer":
                stages_to_render.extend(post_split)
            else:
                # For Loader, check post-split stages for loader-role targets
                for stage in post_split:
                    if stage.is_subsheet_call:
                        target_page = next(
                            (p for p in process.pages if p.page_id == stage.processid), None
                        )
                        if target_page and target_page.role == role:
                            stages_to_render.append(stage)

            action_lines: list[str] = []

            # Render each stage, but resolve CALL targets by their own role
            for stage in stages_to_render:
                rendered = self._render_stage_in_main_page(stage, process, process_map, role)
                if rendered:
                    action_lines.append(rendered)

            actions_content = "\n".join(action_lines)
            epilogue = self._render_goto_epilogue(actions_content)
            if epilogue:
                actions_content = f"{actions_content}\n{epilogue}"

            return actions_content if action_lines else ""

        except Exception as e:
            raise GenerationError(f"Failed to render Main Page for role '{role}': {e}") from e

    def _render_stage_in_main_page(
        self,
        stage: BPStage,
        process: BPProcess,
        process_map: dict[str, Any],
        role: str,
    ) -> str:
        """Render a Main Page stage, resolving CALL targets by target's role.

        If a stage is a SubSheet/Process call, look up the target page's role and only
        emit the CALL if the target belongs to the current role. Otherwise, emit the stage normally.

        Args:
            stage: The BPStage to render.
            process: The BPProcess (to look up target pages).
            process_map: The process entry from page_target_map.yaml.
            role: The current role being rendered.

        Returns:
            Rendered Robin content, or empty string if not applicable to this role.
        """
        # Check if this is a SubSheet/Process call that targets a different role
        if stage.is_subsheet_call:
            # Look up the target page to determine its role
            target_page = next((p for p in process.pages if p.page_id == stage.processid), None)

            if target_page and target_page.role != role:
                # This call targets a different role, skip it for this flow
                return ""

            # Call targets the same role, render it
            return self._render_call_or_inline(stage, process, process_map)

        # Non-call stages are rendered normally
        # Pass process and process_map for SubSheet call resolution
        return self._render_stage(stage, process, process_map)

    def _render_page_in_consolidated_flow(
        self,
        page: Any,
        process: BPProcess,
        process_map: dict[str, Any],
    ) -> str:
        """Render a sub-page according to its shape mapping (function/inline_block/fold/split).

        Args:
            page: The BPPage.
            process: The BPProcess.
            process_map: The process entry from page_target_map.yaml.

        Returns:
            Rendered Robin content for this page.
        """
        try:
            # Get the page's shape
            shape_info = self._get_page_shape(page.name, process_map)
            shape = shape_info.get("shape", "function")

            if shape == "function":
                # Emit a comment if this page fell back to the unmapped default
                result = ""
                if shape_info.get("unmapped_fallback"):
                    fallback_page = shape_info.get("fallback_page_name", page.name)
                    result = f"# TODO: no page_target_map.yaml entry for '{fallback_page}' — treating as default FUNCTION\n"
                result += self._render_page_as_function(page, process, shape_info, process_map)
                return result

            elif shape == "inline_block":
                # Render as a BLOCK inside a container (usually Loader_Main_Body)
                return self._render_inline_block(page, shape_info, process, process_map)

            elif shape == "fold":
                # Render stages directly into container with no wrapper
                return self._render_fold(page, shape_info, process, process_map)

            elif shape == "split":
                # Render as multiple FUNCTIONs
                return self._split_page_into_functions(page, process, shape_info, process_map)

            elif shape == "stop":
                # Unreachable/orphan page — just emit a comment
                reason = shape_info.get("reason", "No PAD counterpart")
                return f"# STOP: {page.name} — {reason}"

            else:
                # Fallback: unknown shape
                return f"# TODO: Unknown shape '{shape}' for page '{page.name}'"

        except Exception as e:
            raise GenerationError(f"Failed to render page '{page.name}': {e}") from e

    def _render_call_or_inline(
        self,
        stage: BPStage,
        process: BPProcess,
        process_map: dict[str, Any],
    ) -> str:
        """Render a CALL to a target page, or inline its content if mapped as inline_block/fold.

        Dispatches on the target page's shape:
        - function: emit CALL '<target_name>'
        - inline_block: inline the BLOCK content (or # TODO if container doesn't exist)
        - fold: inline the stages with # BEGIN fold/# END fold markers
        - split: resolve to the entry-point FUNCTION name
        - stop: emit a citing comment

        Args:
            stage: The SubSheet/Process call stage.
            process: The BPProcess.
            process_map: The process entry from page_target_map.yaml.

        Returns:
            Rendered Robin content (CALL, inlined content, or citing comment).
        """
        # Find the target page
        target_page = next((p for p in process.pages if p.page_id == stage.processid), None)

        # Determine target name (use stage name as fallback)
        target_name = stage.name
        if target_page:
            target_name = target_page.name

        # Get the target page's shape (from mapping or default)
        shape_info = self._get_page_shape(target_name, process_map)
        shape = shape_info.get("shape", "function")

        # Handle "stop" shape even if target page doesn't exist
        # (it might be an orphan page that's in the mapping but not in the AST)
        if shape == "stop":
            reason = shape_info.get("reason", "No PAD counterpart")
            citation = shape_info.get("citation", "§B14")
            return f"# STOP: {target_name} — {reason} ({citation})"

        if not target_page:
            # Page doesn't exist (or was filtered out) and is not marked as "stop"
            # This is a real gap we should report
            return f"# TODO: Target page not found for call stage '{stage.name}'"

        if shape == "function":
            # Regular FUNCTION call — use target_name if available
            target_name = shape_info.get("target_name", target_page.name)
            call_template = self.env.get_template("actions/call_subflow.robin.j2")
            return call_template.render(subflow_name=target_name)

        elif shape == "inline_block":
            # Inline BLOCK content into container
            block_name = shape_info.get("block_name", target_page.name)
            container = shape_info.get("container", "Loader_Main_Body")
            citation = shape_info.get("citation", "§B14")
            notes = shape_info.get("notes", "")

            # Render the target page's stages
            action_lines: list[str] = []
            for s in target_page.stages:
                rendered = self._render_stage(s, process, process_map)
                if rendered:
                    action_lines.append(rendered)

            actions_content = "\n".join(action_lines)
            epilogue = self._render_goto_epilogue(actions_content)
            if epilogue:
                actions_content = f"{actions_content}\n{epilogue}"

            # Emit the inline BLOCK
            block_template = self.env.get_template("subflow.robin.j2")
            block = block_template.render(
                subflow_name=block_name,
                actions=actions_content,
                construct_type="block",
                is_global=False,
            )

            # Add citation comment
            result = f"# {citation} — inline_block: '{target_page.name}' → BLOCK '{block_name}'"
            if notes:
                result += f"\n# NOTE: {notes}"
            result += f"\n{block}"
            return result

        elif shape == "fold":
            # Fold stages directly into container with no wrapper
            container = shape_info.get("container", "")
            citation = shape_info.get("citation", "§B14")
            notes = shape_info.get("notes", "")

            # Render the target page's stages
            action_lines: list[str] = []
            for s in target_page.stages:
                rendered = self._render_stage(s, process, process_map)
                if rendered:
                    action_lines.append(rendered)

            actions_content = "\n".join(action_lines)

            # Emit fold markers
            result = f"# BEGIN fold: '{target_page.name}' ({citation})"
            if container:
                result += f"\n# NOTE: mapped container '{container}' — content inlined at call site"
            if notes:
                result += f"\n# {notes}"
            result += f"\n{actions_content}\n"
            result += f"# END fold: '{target_page.name}'"
            return result

        elif shape == "split":
            # Split shape: resolve to entry-point FUNCTION name
            targets = shape_info.get("targets", [])
            entry_point = targets[0] if targets else target_page.name
            citation = shape_info.get("citation", "§B14")

            call_template = self.env.get_template("actions/call_subflow.robin.j2")
            call = call_template.render(subflow_name=entry_point)
            comment = f"# {citation} — split: routed to entry point '{entry_point}'"
            comment += (
                "\n# TODO: split routing to real per-function call chain still needs verification"
            )
            return f"{comment}\n{call}"

        elif shape == "stop":
            # Orphan/unreachable page — emit a comment instead of a CALL
            reason = shape_info.get("reason", "No PAD counterpart")
            citation = shape_info.get("citation", "§B14")
            return f"# STOP: {target_page.name} — {reason} ({citation})"

        else:
            return f"# TODO: Unknown shape '{shape}' for target page '{target_page.name}'"

    def _render_page_as_function(
        self,
        page: Any,
        process: BPProcess,
        shape_info: dict[str, Any],
        process_map: dict[str, Any] | None = None,
    ) -> str:
        """Render a page as a single FUNCTION block.

        Args:
            page: The BPPage.
            process: The BPProcess.
            shape_info: The shape mapping entry for this page.
            process_map: Optional process entry from page_target_map.yaml.

        Returns:
            Rendered FUNCTION block.
        """
        try:
            # Get target name if mapped (for renaming)
            target_name = shape_info.get("target_name", page.name)

            # Determine GLOBAL qualifier
            is_global = shape_info.get("global", False)

            # Render all stages in the page
            action_lines: list[str] = []
            for stage in page.stages:
                rendered = self._render_stage(stage, process, process_map)
                if rendered:
                    action_lines.append(rendered)

            actions_content = "\n".join(action_lines)
            epilogue = self._render_goto_epilogue(actions_content)
            if epilogue:
                actions_content = f"{actions_content}\n{epilogue}"

            # Render the FUNCTION wrapper
            subflow_template = self.env.get_template("subflow.robin.j2")
            return subflow_template.render(
                subflow_name=target_name,
                actions=actions_content,
                construct_type="function",
                is_global=is_global,
            )

        except Exception as e:
            raise GenerationError(f"Failed to render page '{page.name}' as function: {e}") from e

    def _render_inline_block(
        self,
        page: Any,
        shape_info: dict[str, Any],
        process: BPProcess | None = None,
        process_map: dict[str, Any] | None = None,
    ) -> str:
        """Render a page as an inline BLOCK (not a separate FUNCTION).

        Args:
            page: The BPPage.
            shape_info: The shape mapping entry for this page.
            process: Optional BPProcess (used for SubSheet call resolution).
            process_map: Optional process entry from page_target_map.yaml.

        Returns:
            Rendered BLOCK content.
        """
        block_name = shape_info.get("block_name", page.name)
        container = shape_info.get("container", "")
        citation = shape_info.get("citation", "§B14")
        notes = shape_info.get("notes", "")

        # Render all stages
        action_lines: list[str] = []
        for stage in page.stages:
            rendered = self._render_stage(stage, process, process_map)
            if rendered:
                action_lines.append(rendered)

        actions_content = "\n".join(action_lines)
        epilogue = self._render_goto_epilogue(actions_content)
        if epilogue:
            actions_content = f"{actions_content}\n{epilogue}"

        # Render the BLOCK wrapper
        block_template = self.env.get_template("subflow.robin.j2")
        block = block_template.render(
            subflow_name=block_name,
            actions=actions_content,
            construct_type="block",
            is_global=False,
        )

        # Add citation comment
        result = f"# {citation} — inline_block: '{page.name}' → BLOCK '{block_name}'"
        if container:
            result += f"\n# NOTE: intended to inline into '{container}' (container not synthesized yet — Task 5c)"
        if notes:
            result += f"\n# {notes}"
        result += f"\n{block}"
        return result

    def _render_fold(
        self,
        page: Any,
        shape_info: dict[str, Any],
        process: BPProcess | None = None,
        process_map: dict[str, Any] | None = None,
    ) -> str:
        """Render a page's stages directly into container with no wrapper (fold).

        Args:
            page: The BPPage.
            shape_info: The shape mapping entry for this page.
            process: Optional BPProcess (used for SubSheet call resolution).
            process_map: Optional process entry from page_target_map.yaml.

        Returns:
            Rendered content with fold markers.
        """
        container = shape_info.get("container", "")
        citation = shape_info.get("citation", "§B14")
        notes = shape_info.get("notes", "")

        # Render all stages
        action_lines: list[str] = []
        for stage in page.stages:
            rendered = self._render_stage(stage, process, process_map)
            if rendered:
                action_lines.append(rendered)

        actions_content = "\n".join(action_lines)

        # Emit fold markers (no FUNCTION/BLOCK wrapper)
        result = f"# BEGIN fold: '{page.name}' ({citation})"
        if container:
            result += f"\n# NOTE: mapped container '{container}' — content inlined at call site"
        if notes:
            result += f"\n# {notes}"
        result += f"\n{actions_content}\n"
        result += f"# END fold: '{page.name}'"
        return result

    def _split_page_into_functions(
        self,
        page: Any,
        process: BPProcess,
        shape_info: dict[str, Any],
        process_map: dict[str, Any] | None = None,
    ) -> str:
        """Render a split-shape page into multiple FUNCTIONs.

        Args:
            page: The BPPage.
            process: The BPProcess.
            shape_info: The shape mapping entry for this page (contains targets and stage_counts).
            process_map: Optional process entry from page_target_map.yaml.

        Returns:
            All rendered FUNCTION blocks concatenated.
        """
        targets = shape_info.get("targets", [])
        stage_counts = shape_info.get("stage_counts")

        if not targets:
            # No targets specified — render as single FUNCTION
            return self._render_page_as_function(page, process, {"shape": "function"}, process_map)

        # Compute stage boundaries
        num_stages = len(page.stages)
        if stage_counts and len(stage_counts) == len(targets):
            # Use provided stage_counts for boundaries
            boundaries = self._compute_boundaries_from_counts(stage_counts)
        else:
            # Evenly divide stages across targets
            boundaries = self._compute_even_boundaries(num_stages, len(targets))

        # Render each target FUNCTION
        function_blocks: list[str] = []
        for target_idx, target_name in enumerate(targets):
            start_idx, end_idx = boundaries[target_idx]
            stages_for_target = page.stages[start_idx:end_idx]

            # Render stages for this target
            action_lines: list[str] = []
            for stage in stages_for_target:
                rendered = self._render_stage(stage, process, process_map)
                if rendered:
                    action_lines.append(rendered)

            actions_content = "\n".join(action_lines)
            epilogue = self._render_goto_epilogue(actions_content)
            if epilogue:
                actions_content = f"{actions_content}\n{epilogue}"

            # Render the FUNCTION wrapper
            subflow_template = self.env.get_template("subflow.robin.j2")
            function = subflow_template.render(
                subflow_name=target_name,
                actions=actions_content,
                construct_type="function",
                is_global=False,
            )
            function_blocks.append(function)

        return "\n".join(function_blocks)

    def _get_page_shape(
        self,
        page_name: str,
        process_map: dict[str, Any],
    ) -> dict[str, Any]:
        """Get the shape mapping for a page (from process_map or default).

        Args:
            page_name: The BP page name.
            process_map: The process entry from page_target_map.yaml.

        Returns:
            A dict with "shape" and optional "target_name", "block_name", "container", etc.
        """
        # Look up in process_map
        if page_name in process_map:
            return process_map[page_name]

        # Default to "function" shape if unmapped
        # Per Task 5a, an unmapped page gets a default FUNCTION shape.
        # This preserves the fallback for pages that exist in the AST but are not curated
        # in page_target_map.yaml. Per architecture doc §B9, this scenario should raise
        # a ReviewFlag, but the current design uses a silent default. See Task 5a's open
        # design question (docs/reviews/) regarding whether to upgrade this to a real flag.
        # TODO: no page_target_map.yaml entry for '{page_name}' — treating as default FUNCTION
        return {"shape": "function", "unmapped_fallback": True, "fallback_page_name": page_name}

    @staticmethod
    def _compute_boundaries_from_counts(stage_counts: list[int]) -> list[tuple[int, int]]:
        """Compute stage index boundaries from per-target stage counts.

        Args:
            stage_counts: List of stage counts per target (e.g., [16, 11, 16, 7, 5, 47, 59]).

        Returns:
            List of (start_idx, end_idx) tuples for each target.
        """
        boundaries: list[tuple[int, int]] = []
        start = 0
        for count in stage_counts:
            end = start + count
            boundaries.append((start, end))
            start = end
        return boundaries

    @staticmethod
    def _compute_even_boundaries(
        num_stages: int,
        num_targets: int,
    ) -> list[tuple[int, int]]:
        """Compute stage index boundaries for even division across targets.

        Args:
            num_stages: Total number of stages.
            num_targets: Number of targets to divide into.

        Returns:
            List of (start_idx, end_idx) tuples for each target.
        """
        boundaries: list[tuple[int, int]] = []
        per_target = num_stages // num_targets
        remainder = num_stages % num_targets

        start = 0
        for i in range(num_targets):
            # Distribute remainder across first targets
            count = per_target + (1 if i < remainder else 0)
            end = start + count
            boundaries.append((start, end))
            start = end

        return boundaries

    def _render_goto_epilogue(self, body: str) -> str:
        """Render the LABEL landing pads for the GOTOs a page body emits.

        RECOVER stages emit ``GOTO 'Error Block'`` and RESUME stages emit
        ``GOTO 'End'``, but nothing previously declared those labels, so every
        jump dangled. This appends the same epilogue the reference flows use,
        and only when the body actually jumps.

        Args:
            body: The rendered action lines of the page, joined by newlines.

        Returns:
            The epilogue lines, or an empty string when the body has no GOTO.
        """
        needs_error_block = GOTO_ERROR_BLOCK in body
        needs_end = GOTO_END in body
        if not (needs_error_block or needs_end):
            return ""

        template = self.env.get_template("actions/goto_epilogue.robin.j2")
        return template.render(
            needs_error_block=needs_error_block,
            needs_end=needs_end,
        ).strip("\n")

    def _render_stage(
        self,
        stage: BPStage,
        process: BPProcess | None = None,
        process_map: dict[str, Any] | None = None,
    ) -> str:
        """Render a single stage to Robin action line(s).

        Dispatches on pa_annotation.band and target_type for every stage that
        maps to a PAD action. The single exception is the structural stage
        types in ``STRUCTURAL_STAGE_TYPES`` (BLOCK/RECOVER/RESUME): those carry
        an empty ``pa_target_action`` in mapping/stage_rules.yaml because they
        are Robin scope markers rather than PAD actions, so they are rendered
        from stage_type — and rendered before the MANUAL-band check, since a
        stub in place of a BLOCK/END would unbalance the script.

        Args:
            stage: An annotated BPStage.
            process: Optional BPProcess (used for SubSheet call resolution).
            process_map: Optional process entry from page_target_map.yaml.

        Returns:
            One or more Robin lines as a string.

        Raises:
            GenerationError: If pa_annotation is None.
        """
        if stage.pa_annotation is None:
            raise GenerationError(
                f"Stage '{stage.name}' (ID: {stage.stage_id}) has no pa_annotation. "
                "The annotator must have run before code generation."
            )

        annotation = stage.pa_annotation
        band = annotation.band
        target_type = annotation.target_type
        target_module = annotation.target_module

        # Structural constructs: rendered from stage_type (see docstring)
        if stage.stage_type in STRUCTURAL_STAGE_TYPES:
            return self._render_structural_stage(stage)

        # SubSheet/Process calls: route through mapping (if context available)
        if stage.is_subsheet_call and process and process_map is not None:
            return self._render_call_or_inline(stage, process, process_map)

        # MANUAL band: always render stub
        if band == ConfidenceBand.MANUAL:
            flags = annotation.flags
            reason = flags[0].reason if flags else "No mapping found"
            suggested_fix = flags[0].suggested_fix if flags else "Review manually"
            stub_template = self.env.get_template("actions/stub.robin.j2")
            return stub_template.render(
                stage_id=stage.stage_id,
                stage_name=stage.name,
                reason=reason,
                suggested_fix=suggested_fix,
            )

        # Dispatch on target_type
        lines: list[str] = []

        if target_type in ("ThrowError", "ThrowCustomError"):
            throw_template = self.env.get_template("actions/throw_error.robin.j2")
            rendered = throw_template.render(
                custom=target_type == "ThrowCustomError",
                error_code=annotation.params_map.get("exception_type", "%txt_ExceptionType%"),
                message_var="txt_ExceptionMessage",
            )
            lines.append(rendered)

        elif target_type == "SetVariable":
            set_template = self.env.get_template("actions/set_variable.robin.j2")
            verify_comment = (
                f"{stage.name} (confidence {annotation.confidence:.2f})"
                if band == ConfidenceBand.SPOT_CHECK
                else None
            )
            rendered = set_template.render(
                var_name=stage.name,
                value="%SomeVar%",  # Placeholder
                verify_comment=verify_comment,
            )
            lines.append(rendered)

        elif target_type == "CreateNewDataTable":
            set_template = self.env.get_template("actions/set_variable.robin.j2")
            rendered = set_template.render(
                var_name=stage.name,
                value="DataTable.Create()",
                verify_comment=None,
            )
            lines.append(rendered)

        elif target_type in ("RunDesktopFlow", "SubFlow"):
            # SubFlow/RunDesktopFlow calls get placeholder names; will be handled by mapping
            call_template = self.env.get_template("actions/call_subflow.robin.j2")
            rendered = call_template.render(
                subflow_name=stage.name,
            )
            lines.append(rendered)

        elif target_type == "Condition":
            cond_template = self.env.get_template("actions/condition.robin.j2")
            rendered = cond_template.render(
                condition="%SomeVar% = True",  # Placeholder
                band=band.value,
            )
            lines.append(rendered)

        elif target_type == "RunPowershellScript":
            # Always MANUAL for PowerShell
            stub_template = self.env.get_template("actions/stub.robin.j2")
            rendered = stub_template.render(
                stage_id=stage.stage_id,
                stage_name=stage.name,
                reason="PowerShell scripts require manual migration",
                suggested_fix="Convert to inline C# or external script",
            )
            lines.append(rendered)

        elif target_module == "Excel" and band != ConfidenceBand.MANUAL:
            excel_template = self.env.get_template("actions/excel_read.robin.j2")
            rendered = excel_template.render(
                filepath="$'''C:\\path\\to\\file.xlsx'''",
                excel_var="ExcelInstance",
                sheet_name="Sheet1",
                output_var="DataTable",
            )
            lines.append(rendered)

        elif target_module == "Text":
            text_template = self.env.get_template("actions/text.robin.j2")
            rendered = text_template.render(
                target_type=target_type,
                input_var="%InputVar%",
                output_var=stage.name.replace(" ", "_"),
                delimiter="','",
                find_text="'Old'",
                replace_text="'New'",
                search_text="'Pattern'",
            )
            lines.append(rendered)

        elif target_module == "Variables" and target_type == "GetVariable":
            get_var_template = self.env.get_template("actions/get_variable.robin.j2")
            rendered = get_var_template.render(
                variable_name="'VariableName'",
                output_var=stage.name.replace(" ", "_"),
            )
            lines.append(rendered)

        elif target_module == "File":
            file_template = self.env.get_template("actions/file.robin.j2")
            rendered = file_template.render(
                target_type=target_type,
                output_var=stage.name.replace(" ", "_"),
                file_path="'C:\\\\path\\\\to\\\\file.txt'",
                source_path="'C:\\\\source\\\\file.txt'",
                destination_path="'C:\\\\dest\\\\file.txt'",
                folder_path="'C:\\\\folder'",
            )
            lines.append(rendered)

        elif target_module == "DateTime":
            datetime_template = self.env.get_template("actions/datetime.robin.j2")
            rendered = datetime_template.render(
                target_type=target_type,
                output_var=stage.name.replace(" ", "_"),
                date_value="%DateVar%",
                time_unit="'Days'",
                amount="1",
                date1="%Date1%",
                date2="%Date2%",
                from_format="'MM/dd/yyyy'",
                to_format="'yyyy-MM-dd'",
                date_string="'2025-04-16'",
                format="'yyyy-MM-dd'",
            )
            lines.append(rendered)

        elif target_module == "Folder":
            folder_template = self.env.get_template("actions/folder.robin.j2")
            rendered = folder_template.render(
                target_type=target_type,
                output_var=stage.name.replace(" ", "_"),
                folder_path="'C:\\\\folder'",
                new_name="'NewFolderName'",
            )
            lines.append(rendered)

        elif target_module == "WorkQueues":
            wq_template = self.env.get_template("actions/work_queues.robin.j2")
            rendered = wq_template.render(
                target_type=target_type,
                output_var=stage.name.replace(" ", "_"),
                queue_name="'QueueName'",
                queue_id="%QueueId%",
                item_data="%ItemData%",
                item_id="%ItemId%",
                updated_data="%UpdatedData%",
            )
            lines.append(rendered)

        elif target_module == "Scripting":
            scripting_template = self.env.get_template("actions/scripting.robin.j2")
            rendered = scripting_template.render(
                target_type=target_type,
                output_var=stage.name.replace(" ", "_"),
                script_content="'# Your script here'",
                script_type="'PowerShell'",
                vba_code="'Sub Main()...'",
                workbook_path="'C:\\\\file.xlsx'",
            )
            lines.append(rendered)

        else:
            # Generic comment for unhandled types
            comment = f"# {target_module}.{target_type}"
            if band == ConfidenceBand.SPOT_CHECK:
                comment += f" # VERIFY: {stage.name} (confidence {annotation.confidence:.2f})"
            elif band == ConfidenceBand.PARTIAL:
                comment += f" # TODO: complete {stage.name}"
            lines.append(comment)

        return "\n".join(lines) if lines else ""

    def _render_structural_stage(self, stage: BPStage) -> str:
        """Render a BLOCK/RECOVER/RESUME stage to its Robin scope construct.

        BLOCK stages are paired by ``pair_id`` (assigned by the AST builder):
        the opener carries ``pair_id == stage_id`` and emits the
        ``BLOCK … ON BLOCK ERROR … END`` handler prologue; its partner emits
        the closing ``END``. An unpaired (singleton) BLOCK is treated as an
        opener so the emitted construct is still balanced.

        Args:
            stage: A BPStage whose stage_type is in STRUCTURAL_STAGE_TYPES.

        Returns:
            One or more Robin lines as a string.

        Raises:
            GenerationError: If the stage_type is not a structural type.
        """
        if stage.stage_type == StageType.BLOCK:
            is_closer = stage.pair_id is not None and stage.pair_id != stage.stage_id
            if is_closer:
                return "END"
            return self._render_block_open(stage)

        if stage.stage_type == StageType.RECOVER:
            recover_template = self.env.get_template("actions/recover.robin.j2")
            return recover_template.render(
                error_var="obj_LastError",
                handler_name="Get Error",
                goto_label="Error Block",
            )

        if stage.stage_type == StageType.RESUME:
            goto_template = self.env.get_template("actions/goto.robin.j2")
            return goto_template.render(label="End")

        raise GenerationError(
            f"Stage '{stage.name}' (ID: {stage.stage_id}) has non-structural "
            f"type '{stage.stage_type.value}' and cannot be rendered as a scope construct."
        )

    def _render_block_open(self, stage: BPStage) -> str:
        """Render the opening ``BLOCK … END`` handler prologue for a BLOCK stage.

        When the stage carries an ``exception_type`` a typed handler branch
        (``ON BLOCK ERROR '<type>' IsUserDefinedErrorCode: True``) is emitted
        ahead of the catch-all ``ON BLOCK ERROR all`` branch.

        Args:
            stage: The opening BLOCK stage.

        Returns:
            The rendered Robin block prologue.
        """
        typed_handlers: list[dict[str, object]] = []
        if stage.exception_type:
            typed_handlers.append(
                {
                    "error_code": stage.exception_type,
                    "actions": [
                        f"SET txt_ExceptionType TO $'''{stage.exception_type}'''",
                        "GOTO 'End'",
                    ],
                }
            )

        block_template = self.env.get_template("actions/error_block.robin.j2")
        return block_template.render(
            block_name=stage.name,
            typed_handlers=typed_handlers,
            catchall_actions=["CALL 'Get Error'", "GOTO 'Error Block'"],
        )

    def _render_get_error_boilerplate(self) -> str:
        """Render the 'Get Error' FUNCTION stub (pre-existing boilerplate).

        Per architecture doc §A3, 'Get Error' is a boilerplate FUNCTION that all
        exception handlers call. It is not derived from BP but exists in the real
        reference PAD solution. This stub is rendered once per output file, for every
        BLOCK that references it.

        Returns:
            A FUNCTION 'Get Error' stub with a TODO comment.
        """
        template = self.env.get_template("subflow.robin.j2")
        stub_body = (
            "# TODO: Implement error logging per §A3\n"
            "# Placeholder stub for pre-existing boilerplate FUNCTION"
        )
        return template.render(
            subflow_name="Get Error",
            actions=stub_body,
            construct_type="function",
            is_global=False,
        )

    @staticmethod
    def _collect_sensitive_vars(stages: list[BPStage]) -> list[str]:
        """Collect the variable names that must appear in the @SENSITIVE header.

        A variable is sensitive when its BP data type is ``password`` or
        ``binary``, or when its name contains any of ``pass``, ``key``,
        ``secret`` or ``pwd`` (case-insensitive).

        Args:
            stages: The stages of one page.

        Returns:
            De-duplicated variable names in first-seen order.
        """
        sensitive: list[str] = []
        seen: set[str] = set()

        for stage in stages:
            for data_item in stage.data_items:
                if data_item.name in seen:
                    continue
                lowered_name = data_item.name.lower()
                is_sensitive = data_item.data_type.lower() in SENSITIVE_DATA_TYPES or any(
                    token in lowered_name for token in SENSITIVE_NAME_TOKENS
                )
                if is_sensitive:
                    seen.add(data_item.name)
                    sensitive.append(data_item.name)

        return sensitive

    @staticmethod
    def _sanitise_filename(name: str) -> str:
        """Sanitise a filename by removing/replacing special characters.

        Args:
            name: The filename to sanitise.

        Returns:
            Sanitised filename (spaces → underscores, special chars removed).
        """
        return flow_file_stem(name)

    @staticmethod
    def _map_bp_type_to_robin(bp_type: str) -> str:
        """Map Blue Prism data type to Robin type string.

        Args:
            bp_type: Blue Prism type (e.g., 'text', 'number', 'flag', 'collection').

        Returns:
            Robin type string.
        """
        mapping = {
            "text": "String",
            "number": "Number",
            "flag": "Bool",
            "currency": "Number",
            "date": "DateTime",
            "time": "TimeSpan",
            "collection": "RecordSet",
            "binary": "String",
        }
        return mapping.get(bp_type.lower(), "String")
