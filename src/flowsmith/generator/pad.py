"""PAD .robin file generator using Jinja2 templates.

Converts an annotated BPProcess into consolidated .robin files for Power Automate Desktop flows.
Task 5a: 2 consolidated files (Loader, Performer), each containing multiple FUNCTION blocks
for pages with that role, instead of one file per page.

Main page stages split by role boundary (Get Next Item stage).
Sub-pages rendered based on page-shape mapping (function/inline_block/fold/split).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from flowsmith.ast.models import BPProcess, BPStage, ConfidenceBand, StageType
from flowsmith.exceptions import GenerationError
from flowsmith.generator.naming import flow_file_stem
from flowsmith.mapper.config import load_rules

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

# Flag variable set by the coarse BLOCK handler (§A5, §B15 reference lines 1389/1394/1398).
# The real reference uses flg_ErrorOccurred; the post-block gating IF reads this flag.
COARSE_BLOCK_ERROR_FLAG = "flg_ErrorOccurred"

# The 3-tier exception type strings (§A5) used in the typed handler arms of coarse BLOCKs.
# These are the only valid values — derived from §A5, not from stage.exception_type (which
# is only populated on EXCEPTION/throw stages, never on BLOCK stages — ast/models.py).
_COARSE_TYPED_HANDLERS: list[tuple[str, list[str]]] = [
    (
        "Business Exception",
        [
            "CALL 'Get Error'",
            "SET txt_ExceptionType TO $'''Business Exception'''",
            f"SET {COARSE_BLOCK_ERROR_FLAG} TO True",
        ],
    ),
    (
        "System Unavailable Exception",
        [
            "SET flg_Screenshot TO True",
            "CALL 'Get Error'",
            "SET txt_ExceptionType TO $'''System Unavailable Exception'''",
            f"SET {COARSE_BLOCK_ERROR_FLAG} TO True",
        ],
    ),
]

# Catch-all handler actions for the coarse BLOCK (§A5 reference lines 1395–1398).
_COARSE_CATCHALL_ACTIONS: list[str] = [
    "SET flg_Screenshot TO True",
    "CALL 'Get Error'",
    f"SET {COARSE_BLOCK_ERROR_FLAG} TO True",
]

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

        # Load MappingConfig to access VBO catalogue for method_actions lookup (Task 7a).
        try:
            self.mapping_config = load_rules()
        except Exception as e:
            raise GenerationError(f"Failed to load mapping config: {e}") from e

        # Load queue_bindings from raw vbo_catalogue.yaml for WorkQueues queue parameter handling (Task 7a).
        # Queue bindings map BP queue expressions to PAD variables with citations.
        self.queue_bindings: dict[str, dict[str, str]] = {}
        try:
            vbo_catalogue_path = Path.cwd() / "mapping" / "vbo_catalogue.yaml"
            if vbo_catalogue_path.exists():
                with open(vbo_catalogue_path, encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    if data and isinstance(data, list):
                        for entry in data:
                            if entry.get("vbo_name") == "Blueprism.Automate.clsWorkQueuesActions":
                                bindings = entry.get("queue_bindings", [])
                                if isinstance(bindings, list):
                                    for binding in bindings:
                                        expr_pattern = binding.get("expression_pattern", "")
                                        if expr_pattern:
                                            self.queue_bindings[expr_pattern] = {
                                                "pad_variable": binding.get("pad_variable", ""),
                                                "citation": binding.get("citation", ""),
                                                "notes": binding.get("notes", ""),
                                            }
        except Exception:
            # Non-fatal: queue_bindings is optional, generator can continue with fallback matching
            pass

        # Instance variable to hold the current page name resolution map (built during
        # role-based generation to handle collision disambiguation — Task 6b2).
        # Used by _render_page_as_function and _render_call_or_inline to ensure both
        # FUNCTION definitions and CALL sites use consistent resolved names (with
        # suffixes for accidental collisions, not intentional folds).
        self._current_page_name_map: dict[str, str] = {}

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

            # Build variable name mapping for Task 5b expression translation (per §A4, §B10)
            variable_name_mapping = self._build_variable_name_mapping(process)

            # Render main page content (split by role)
            if main_page:
                main_content = self._render_main_page_for_role(
                    main_page, process, role, variable_name_mapping
                )
                if main_content:
                    lines.append(main_content)
                    lines.append("")

            # Render sub-pages as FUNCTION blocks (or inline/fold if mapped)
            process_map = self.page_target_map.get(process.name, {})
            rendered_functions: list[str] = []

            # Build the page name resolution mapping (handles collisions with disambiguation)
            # This maps each page to its final resolved target name, distinguishing between
            # intentional folds (explicit mapping) and accidental collisions (fallback names).
            # Store in instance variable so it's accessible to _render_page_as_function and
            # _render_call_or_inline without threading through every method signature.
            self._current_page_name_map = self._build_page_name_resolution_map(
                pages_for_role, process_map
            )

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

                # De-duplication: use resolved target name from the mapping built above
                # This mapping distinguishes between:
                # - Intentional folds: multiple pages map to same target_name via explicit
                #   mapping entry — skip silently on collision (don't disambiguate)
                # - Accidental collisions: pages fallback to their own name and happen to
                #   collide — add disambiguation suffix (e.g., _2, _3)
                resolved_target_name = self._current_page_name_map.get(page.page_id, page.name)
                if resolved_target_name in seen_function_names:
                    # FUNCTION with this name already emitted; skip the duplicate
                    # (cite the first occurrence; the mapping file notes parameterization)
                    continue

                page_content = self._render_page_in_consolidated_flow(
                    page, process, process_map, variable_name_mapping
                )
                if page_content:
                    rendered_functions.append(page_content)
                    lines.append(page_content)
                    lines.append("")
                    # Track this function name to prevent duplicates
                    seen_function_names.add(resolved_target_name)

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
        variable_name_mapping: dict[str, str] | None = None,
    ) -> str:
        """Render Main Page stages split by role (Get Next Item boundary).

        Per architecture doc §B11, Get Next Item (stage ID 85fbb578...) is the split point.
        Pre-split stages (0-13) route to their target's role (via mapping).
        Post-split stages (14+) route to Performer.

        Args:
            main_page: The main BPPage.
            process: The BPProcess.
            role: Either "loader" or "performer".
            variable_name_mapping: Optional dict mapping lowercase BP names to PAD names (Task 5b).

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

            # Render each stage, applying coarse BLOCK pattern (§A5, §B15) where applicable.
            # Use a role-aware render function that filters calls by target role.
            def _render_main_stage(
                s: BPStage,
                proc: BPProcess | None,
                pmap: dict[str, Any] | None,
                vnm: dict[str, str] | None,
            ) -> str:
                return self._render_stage_in_main_page(
                    s, process, process_map, role, variable_name_mapping
                )

            actions_content = self._render_stage_list_with_coarse_blocks(
                stages_to_render,
                process,
                process_map,
                variable_name_mapping,
                render_stage_fn=_render_main_stage,
            )
            epilogue = self._render_goto_epilogue(actions_content)
            if epilogue:
                actions_content = f"{actions_content}\n{epilogue}"

            return actions_content if actions_content.strip() else ""

        except Exception as e:
            raise GenerationError(f"Failed to render Main Page for role '{role}': {e}") from e

    def _render_stage_in_main_page(
        self,
        stage: BPStage,
        process: BPProcess,
        process_map: dict[str, Any],
        role: str,
        variable_name_mapping: dict[str, str] | None = None,
    ) -> str:
        """Render a Main Page stage, resolving CALL targets by target's role.

        If a stage is a SubSheet/Process call, look up the target page's role and only
        emit the CALL if the target belongs to the current role. Otherwise, emit the stage normally.

        Args:
            stage: The BPStage to render.
            process: The BPProcess (to look up target pages).
            process_map: The process entry from page_target_map.yaml.
            role: The current role being rendered.
            variable_name_mapping: Optional dict mapping lowercase BP names to PAD names (Task 5b).

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
            return self._render_call_or_inline(stage, process, process_map, variable_name_mapping)

        # Non-call stages are rendered normally
        # Pass process and process_map for SubSheet call resolution
        return self._render_stage(stage, process, process_map, variable_name_mapping)

    def _render_page_in_consolidated_flow(
        self,
        page: Any,
        process: BPProcess,
        process_map: dict[str, Any],
        variable_name_mapping: dict[str, str] | None = None,
    ) -> str:
        """Render a sub-page according to its shape mapping (function/inline_block/fold/split).

        Args:
            page: The BPPage.
            process: The BPProcess.
            process_map: The process entry from page_target_map.yaml.
            variable_name_mapping: Optional dict mapping lowercase BP names to PAD names (Task 5b).

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
                result += self._render_page_as_function(
                    page, process, shape_info, process_map, variable_name_mapping
                )
                return result

            elif shape == "inline_block":
                # Render as a BLOCK inside a container (usually Loader_Main_Body)
                return self._render_inline_block(
                    page, shape_info, process, process_map, variable_name_mapping
                )

            elif shape == "fold":
                # Render stages directly into container with no wrapper
                return self._render_fold(
                    page, shape_info, process, process_map, variable_name_mapping
                )

            elif shape == "split":
                # Render as multiple FUNCTIONs
                return self._split_page_into_functions(
                    page, process, shape_info, process_map, variable_name_mapping
                )

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
        variable_name_mapping: dict[str, str] | None = None,
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
            variable_name_mapping: Optional dict mapping lowercase BP names to PAD names.
                                   Used for inline_block and fold branches to apply naming
                                   conventions to DATA/CALCULATION stages within those pages.

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
            # Regular FUNCTION call — use self._current_page_name_map if available
            # (includes disambiguation suffixes), otherwise use mapped target_name from
            # shape_info or fallback to page.name.
            if target_page.page_id in self._current_page_name_map:
                target_name = self._current_page_name_map[target_page.page_id]
            else:
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
                rendered = self._render_stage(s, process, process_map, variable_name_mapping)
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
                rendered = self._render_stage(s, process, process_map, variable_name_mapping)
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
        variable_name_mapping: dict[str, str] | None = None,
    ) -> str:
        """Render a page as a single FUNCTION block.

        Args:
            page: The BPPage.
            process: The BPProcess.
            shape_info: The shape mapping entry for this page.
            process_map: Optional process entry from page_target_map.yaml.
            variable_name_mapping: Optional dict mapping lowercase BP names to PAD names (Task 5b).

        Returns:
            Rendered FUNCTION block.
        """
        try:
            # Get target name: use self._current_page_name_map if available (includes
            # disambiguation suffixes), otherwise fall back to shape_info (explicit mapping)
            # or page.name (default).
            if page.page_id in self._current_page_name_map:
                target_name = self._current_page_name_map[page.page_id]
            else:
                target_name = shape_info.get("target_name", page.name)

            # Determine GLOBAL qualifier
            is_global = shape_info.get("global", False)

            # Render all stages in the page, applying coarse BLOCK pattern (§A5, §B15)
            # where the page has Block stages with a persisted recover_stage_id (Task 4b).
            actions_content = self._render_stage_list_with_coarse_blocks(
                page.stages, process, process_map, variable_name_mapping
            )
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
        variable_name_mapping: dict[str, str] | None = None,
    ) -> str:
        """Render a page as an inline BLOCK (not a separate FUNCTION).

        Args:
            page: The BPPage.
            shape_info: The shape mapping entry for this page.
            process: Optional BPProcess (used for SubSheet call resolution).
            process_map: Optional process entry from page_target_map.yaml.
            variable_name_mapping: Optional dict mapping lowercase BP names to PAD names (Task 5b).

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
            rendered = self._render_stage(stage, process, process_map, variable_name_mapping)
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
        variable_name_mapping: dict[str, str] | None = None,
    ) -> str:
        """Render a page's stages directly into container with no wrapper (fold).

        Args:
            page: The BPPage.
            shape_info: The shape mapping entry for this page.
            process: Optional BPProcess (used for SubSheet call resolution).
            process_map: Optional process entry from page_target_map.yaml.
            variable_name_mapping: Optional dict mapping lowercase BP names to PAD names (Task 5b).

        Returns:
            Rendered content with fold markers.
        """
        container = shape_info.get("container", "")
        citation = shape_info.get("citation", "§B14")
        notes = shape_info.get("notes", "")

        # Render all stages
        action_lines: list[str] = []
        for stage in page.stages:
            rendered = self._render_stage(stage, process, process_map, variable_name_mapping)
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
        variable_name_mapping: dict[str, str] | None = None,
    ) -> str:
        """Render a split-shape page into multiple FUNCTIONs.

        Args:
            page: The BPPage.
            process: The BPProcess.
            shape_info: The shape mapping entry for this page (contains targets and stage_counts).
            process_map: Optional process entry from page_target_map.yaml.
            variable_name_mapping: Optional dict mapping lowercase BP names to PAD names (Task 5b).

        Returns:
            All rendered FUNCTION blocks concatenated.
        """
        targets = shape_info.get("targets", [])
        stage_counts = shape_info.get("stage_counts")

        if not targets:
            # No targets specified — render as single FUNCTION
            return self._render_page_as_function(
                page, process, {"shape": "function"}, process_map, variable_name_mapping
            )

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
                rendered = self._render_stage(stage, process, process_map, variable_name_mapping)
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

    def _build_page_name_resolution_map(
        self,
        pages_for_role: list,
        process_map: dict[str, Any],
    ) -> dict[str, str]:
        """Build a mapping from page_id to its final resolved FUNCTION name.

        Distinguishes between intentional folds (explicit mapping) and accidental collisions:
        - Intentional fold: page_target_map.yaml gives two pages the same target_name
          → both map to the same name; rendering loop will skip the second via
          seen_function_names deduplication (no suffix added)
        - Accidental collision: two pages both fallback to their own name and happen to collide
          → add disambiguation suffix (e.g., _2, _3) so both render as distinct FUNCTIONs

        Args:
            pages_for_role: List of BPPage objects for the current role.
            process_map: The process entry from page_target_map.yaml.

        Returns:
            Dict mapping page_id → final_resolved_target_name (may include disambiguation suffix).

        Raises:
            GenerationError: If name resolution fails.
        """
        # Collect each page's target name and track whether it's from explicit mapping or fallback
        page_targets: dict[str, tuple[str, bool]] = {}  # page_id -> (target_name, is_explicit)
        explicit_targets: dict[
            str, list[str]
        ] = {}  # target_name -> [page_ids with this explicit target]
        fallback_targets: dict[
            str, list[str]
        ] = {}  # target_name -> [page_ids with this fallback target]

        for page in pages_for_role:
            shape_info = self._get_page_shape(page.name, process_map)
            shape = shape_info.get("shape", "function")

            # Skip inline_block/fold pages — they're not rendered as top-level FUNCTIONs
            if shape in ("inline_block", "fold"):
                continue

            # Determine if target_name is explicit (from mapping) or fallback
            if "target_name" in shape_info:
                target_name = shape_info["target_name"]
                is_explicit = True
                if target_name not in explicit_targets:
                    explicit_targets[target_name] = []
                explicit_targets[target_name].append(page.page_id)
            else:
                target_name = page.name
                is_explicit = False
                if target_name not in fallback_targets:
                    fallback_targets[target_name] = []
                fallback_targets[target_name].append(page.page_id)

            page_targets[page.page_id] = (target_name, is_explicit)

        # Build final resolution map, handling collisions
        final_map: dict[str, str] = {}

        for page in pages_for_role:
            shape_info = self._get_page_shape(page.name, process_map)
            shape = shape_info.get("shape", "function")
            if shape in ("inline_block", "fold"):
                continue

            target_name, is_explicit = page_targets[page.page_id]

            if is_explicit:
                # Intentional fold: all pages with this explicit target_name map to the same
                # resolved name. The rendering loop will skip duplicates via seen_function_names.
                final_map[page.page_id] = target_name
            else:
                # Fallback name: check for collision with other fallback names
                fallback_count = len(fallback_targets.get(target_name, []))
                if fallback_count > 1:
                    # Collision detected: add disambiguation suffix
                    # Find the ordinal position of this page among pages with the same fallback name
                    fallback_pages = fallback_targets[target_name]
                    ordinal = fallback_pages.index(page.page_id)  # 0-indexed position
                    if ordinal == 0:
                        # First occurrence: no suffix (leave original name bare)
                        final_map[page.page_id] = target_name
                    else:
                        # Second+ occurrences: _2, _3, etc. (suffix at position+1)
                        final_map[page.page_id] = f"{target_name}_{ordinal + 1}"
                else:
                    # No collision: use the fallback name as-is
                    final_map[page.page_id] = target_name

        return final_map

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

    def _build_variable_name_mapping(self, process: BPProcess) -> dict[str, str]:
        """Build a mapping of BP variable names to PAD-prefixed names.

        Scans all DATA and COLLECTION stages across all pages in the process and builds
        a single source-of-truth mapping for BP name → PAD name. This ensures consistent
        variable naming across all references to the same BP data item, whether they appear
        as declarations, reads, or writes.

        Per architecture doc §A4, BP data item names with spaces are prefixed based on type:
        - text → txt_
        - number → num_
        - collection/collection_data → dtb_ (DataTable)
        etc.

        Args:
            process: The BPProcess to scan.

        Returns:
            Dict mapping lowercase BP names to their PAD-prefixed equivalents.
            Examples: {'retry_count': 'num_retryCount', 'exception_type': 'txt_ExceptionType'}.
        """
        mapping: dict[str, str] = {}

        for page in process.pages:
            for stage in page.stages:
                # DATA stages declare variables
                # Per engine/annotator.py::_annotate_data (lines 239-243), params_map has:
                # {"variable_name": stage.name, "variable_type": type, "initial_value": value}
                if stage.stage_type == StageType.DATA and stage.pa_annotation:
                    var_name = stage.pa_annotation.params_map.get("variable_name", stage.name)
                    var_type = stage.pa_annotation.params_map.get("variable_type", "text").lower()
                    bp_name_lower = var_name.lower()

                    if bp_name_lower not in mapping:
                        # Generate the padded name based on type
                        padded_name = self._apply_type_prefix(var_name, var_type)
                        mapping[bp_name_lower] = padded_name

                # COLLECTION stages declare data tables
                # Per engine/annotator.py::_annotate_collection (lines 264-267), params_map has:
                # {"table_name": stage.name, "variable_type": "DataTable"}
                elif stage.stage_type == StageType.COLLECTION and stage.pa_annotation:
                    table_name = stage.pa_annotation.params_map.get("table_name", stage.name)
                    var_type = stage.pa_annotation.params_map.get(
                        "variable_type", "collection"
                    ).lower()
                    bp_name_lower = table_name.lower()

                    if bp_name_lower not in mapping:
                        # Generate the padded name for collections (dtb_)
                        padded_name = self._apply_type_prefix(table_name, var_type)
                        mapping[bp_name_lower] = padded_name

                # CALCULATION stages can also reference collections in dotted notation
                # For CALCULATION stages, params_map is set by parser (lines 354-355 of process.py)
                # with {calc_stage: calc_expr} shape, NOT by annotator which returns params_map={}
                elif stage.stage_type == StageType.CALCULATION and stage.params_map:
                    for target_name in stage.params_map:
                        if "." in target_name:
                            # Extract the base collection name
                            base_name = target_name.split(".")[0]
                            base_lower = base_name.lower()
                            if base_lower not in mapping:
                                # Try to find the mapped name via a lookup
                                # (may have been declared in a DATA/COLLECTION stage)
                                # If not found, use default collection prefix
                                padded_name = self._apply_type_prefix(base_name, "collection")
                                mapping[base_lower] = padded_name

        return mapping

    def _apply_type_prefix(self, name: str, pad_type: str) -> str:
        """Apply the appropriate type prefix to a variable name per architecture doc §A4.

        Strips any pre-existing BP-author-supplied prefix before applying the new one,
        to avoid doubled prefixes like "bool_flgSendDatatoDataGateways".

        Args:
            name: The base variable name (e.g., "Retry Count" or "FinalProduct_Collection").
            pad_type: The variable type (e.g., "number", "text", "datatable", "datetime").

        Returns:
            The prefixed name (e.g., "num_retryCount", "dtb_finalproductCollection", "dt_currentDateTime").
        """
        # Normalize the type string
        type_lower = pad_type.lower().strip()

        # Determine prefix based on type per architecture doc §A4
        if type_lower in ("number", "integer", "decimal"):
            prefix = "num_"
        elif type_lower in ("collection", "datatable", "table"):
            prefix = "dtb_"
        elif type_lower in ("datatabletrow", "tablerow", "row"):
            prefix = "dtr_"
        elif type_lower in ("datetime", "date", "time"):
            prefix = "dt_"
        elif type_lower in ("boolean", "bool", "true/false"):
            prefix = "flg_"  # Fixed: was "bool_", correct per §A4 is "flg_"
        elif type_lower in ("customobject", "object"):
            prefix = "obj_"
        elif type_lower in ("list", "array"):
            prefix = "lst_"
        else:  # text, string, or unknown
            prefix = "txt_"

        # Strip any pre-existing BP-author-supplied prefix to avoid doubling
        # Known prefixes from §A4 + legacy variants (datetm_, bool_)
        existing_prefixes = {
            "txt_",
            "num_",
            "flg_",
            "obj_",
            "lst_",
            "dtb_",
            "dtr_",
            "dt_",
            "ins_",
            "bool_",
            "datetm_",  # legacy variants
        }

        name_to_process = name
        for existing_prefix in existing_prefixes:
            if name.lower().startswith(existing_prefix.lower()):
                # Found a pre-existing prefix, strip it
                name_to_process = name[len(existing_prefix) :]
                break

        # Convert name to PascalCase: handle both spaces and underscores as word separators
        # Split by both spaces and underscores, then reconstruct in PascalCase
        # E.g., "Retry Count" → "RetryCount", "FinalProduct_Collection" → "FinalProductCollection"
        # First, normalize underscores to spaces for uniform handling
        name_normalized = name_to_process.replace("_", " ")
        parts = name_normalized.split()

        if not parts:
            pascal_name = name_to_process
        else:
            # Capitalize the first letter of each part, preserving the rest of its casing as-is
            pascal_name = "".join(p[0].upper() + p[1:] if p else "" for p in parts)

        # Sanitize any remaining non-alphanumeric/non-underscore characters from the name (e.g. hyphens in Sleep-2s)
        import re

        sanitized_name = re.sub(r"[^A-Za-z0-9_]", "", pascal_name)

        return prefix + sanitized_name

    def _resolve_dotted_reference(
        self,
        reference: str,
        variable_name_mapping: dict[str, str] | None = None,
    ) -> str:
        """Resolve a dotted reference (Collection.Field) through the variable name mapping.

        Handles references like 'FinalProduct_Collection.Column8' where the base collection
        name needs to be looked up in the mapping (e.g., FinalProduct_Collection → dtb_finalproductCollection)
        but the field suffix (.Column8) is preserved.

        Args:
            reference: The dotted reference string (e.g., 'FinalProduct_Collection.Column8').
            variable_name_mapping: Optional dict mapping lowercase BP names to PAD names.
                                   If None, the reference is returned unchanged.

        Returns:
            The resolved reference with mapped base name, or the original reference if no mapping found.
            Examples: 'FinalProduct_Collection.Column8' → 'dtb_finalproductCollection.Column8'
        """
        if not variable_name_mapping or "." not in reference:
            return reference

        parts = reference.split(".", 1)
        base_name = parts[0].strip()
        field_suffix = parts[1] if len(parts) > 1 else ""

        base_lower = base_name.lower()
        if base_lower in variable_name_mapping:
            mapped_base = variable_name_mapping[base_lower]
            return f"{mapped_base}.{field_suffix}" if field_suffix else mapped_base

        # No mapping found; return original
        return reference

    def _translate_bp_expression(
        self,
        expr: str,
        variable_name_mapping: dict[str, str] | None = None,
    ) -> tuple[str, list[str]]:
        """Translate a BP expression to PAD syntax.

        Handles:
        - [Data Item] references → variable references (prefixed per §A4)
        - String concatenation & → +
        - Trim(...) / Lower(...) → separate action lines returned in the 2nd tuple element

        Per architecture doc §B10 point 3: `Trim(...)`/`Lower(...)` become separate action lines
        (PAD cannot inline them into expressions).

        Args:
            expr: The BP expression string.
            variable_name_mapping: Optional dict mapping lowercase BP names to PAD names.

        Returns:
            Tuple of (translated_expression, separate_action_lines).
            The expression has data items and operators translated; separate_action_lines
            contains any Trim/Lower action lines that must be emitted separately (can be empty).

        Raises:
            GenerationError: If expression translation fails critically.
        """
        if not expr or not expr.strip():
            return "", []

        separate_actions: list[str] = []
        result = expr

        # Counter for deterministic temp variable naming (replaces non-deterministic id(match))
        # Using a counter ensures that identical expressions produce identical temp var names
        # across different runs and processes, per project's offline/deterministic constraint
        temp_var_counter = 0

        # Extract and replace Trim(...) and Lower(...) calls
        # These must become separate action lines, not be inlined
        trim_pattern = r"Trim\s*\(\s*([^)]+)\s*\)"
        for match in re.finditer(trim_pattern, result):
            inner_expr = match.group(1).strip()
            # Recursively translate the inner expression
            translated_inner, inner_actions = self._translate_bp_expression(
                inner_expr, variable_name_mapping
            )
            separate_actions.extend(inner_actions)
            # Create a temporary variable for the Trim result using deterministic counter
            temp_var = f"txt_trimmed_{temp_var_counter}"
            action = f"Text.Trim '{translated_inner}' => {temp_var}"
            separate_actions.append(action)
            # Replace the Trim call with the temp var
            result = result.replace(match.group(0), temp_var)
            temp_var_counter += 1

        lower_pattern = r"Lower\s*\(\s*([^)]+)\s*\)"
        for match in re.finditer(lower_pattern, result):
            inner_expr = match.group(1).strip()
            translated_inner, inner_actions = self._translate_bp_expression(
                inner_expr, variable_name_mapping
            )
            separate_actions.extend(inner_actions)
            # Create a temporary variable for the Lower result using deterministic counter
            temp_var = f"txt_lowered_{temp_var_counter}"
            action = f"Text.ChangeCase '{translated_inner}' 'To lowercase' => {temp_var}"
            separate_actions.append(action)
            result = result.replace(match.group(0), temp_var)
            temp_var_counter += 1

        # Translate [Data Item] references
        # Pattern: [ClassName] or [ClassName.PropertyName]
        bracket_pattern = r"\[([^\]]+)\]"

        def replace_bracket_ref(match):
            ref = match.group(1).strip()
            if variable_name_mapping and "." in ref:
                # Dotted reference like [Collection.Field]
                return self._resolve_dotted_reference(ref, variable_name_mapping)
            elif variable_name_mapping:
                # Simple reference like [DataItem]
                ref_lower = ref.lower()
                if ref_lower in variable_name_mapping:
                    return variable_name_mapping[ref_lower]
            return ref

        result = re.sub(bracket_pattern, replace_bracket_ref, result)

        # Handle bare dotted references (without brackets)
        bare_dotted_pattern = r"\b([A-Za-z_]\w*)\.\s*([A-Za-z_]\w*)\b"

        def replace_bare_dotted(match):
            base_name = match.group(1)
            field_name = match.group(2)
            base_lower = base_name.lower()
            if variable_name_mapping and base_lower in variable_name_mapping:
                mapped_base = variable_name_mapping[base_lower]
                return f"{mapped_base}.{field_name}"
            return match.group(0)

        result = re.sub(bare_dotted_pattern, replace_bare_dotted, result)

        # Translate operators: & → +
        result = result.replace("&", "+")

        return result, separate_actions

    def _lookup_method_actions_template(self, stage: BPStage) -> str | None:
        """Look up a method_actions template for a VBO call stage.

        Used by Task 7a to wire WorkQueues and other VBO method_actions into generation.
        Tries to find an exact method match in the VBO catalogue's method_actions field.

        Args:
            stage: A BPStage with _vbo_object and _vbo_action in params_map.

        Returns:
            The PAD action template string if found in method_actions, None otherwise.
        """
        vbo_name = stage.params_map.get("_vbo_object")
        method_name = stage.params_map.get("_vbo_action")

        if not vbo_name or not method_name:
            return None

        # Look up VBO entry from catalogue
        vbo_entry = self.mapping_config.get_vbo_entry(vbo_name)
        if not vbo_entry:
            vbo_entry = self.mapping_config.get_vbo_entry_fuzzy(vbo_name)

        if not vbo_entry or not vbo_entry.method_actions:
            return None

        # Check for exact method match in method_actions
        return vbo_entry.method_actions.get(method_name)

    def _substitute_workqueues_placeholders(
        self,
        template: str,
        stage: BPStage,
        method_name: str,
        variable_name_mapping: dict[str, str] | None = None,
    ) -> tuple[str, bool, str]:
        """Substitute placeholder tokens in a WorkQueues action template.

        Per Task 7a (§Gap 1), template tokens like <id>, <var>, <obj>, <msg>, <text>
        must be replaced with actual values from stage.params_map and stage context,
        using the codebase's established expression-translation machinery to ensure
        consistency with other variable-name resolution throughout the generator.

        Mapping (per vbo-action-mapping.md):
        - <id> = Queue Name parameter (translated via _translate_bp_expression,
                 OR mapped from queue_bindings catalogue entry with citation)
        - <var> = Output variable name for the action result (e.g., obj_WorkQueueItem)
        - <obj> = Work queue item object variable (obj_WorkQueueItem)
        - <msg> = Exception message parameter (Exception Reason, translated)
        - <text> = Status parameter (translated) — NOT "Processing Notes" key

        Args:
            template: The template string with placeholders.
            stage: The BPStage with params_map.
            method_name: The VBO method name (e.g., "Get Next Item").
            variable_name_mapping: Optional dict mapping lowercase BP names to PAD names,
                                   used for consistent expression translation.

        Returns:
            A tuple of (substituted_string, was_bound_from_catalogue, dependency_comment).
            was_bound_from_catalogue: True if the queue binding came from queue_bindings catalogue.
            dependency_comment: Citation/notes about where the variable must be assigned.

        Raises:
            GenerationError: If substitution fails critically.
        """
        result = template
        was_bound_from_catalogue = False
        dependency_comment = ""

        # Queue Name parameter: <id>
        if "<id>" in result:
            queue_name = stage.params_map.get("Queue Name", "")
            id_value = ""

            # Task 7a (b): Check queue_bindings catalogue for expression-to-variable mapping
            if queue_name:
                for expr_pattern, binding_info in self.queue_bindings.items():
                    if expr_pattern in queue_name:
                        id_value = binding_info["pad_variable"]
                        citation = binding_info["citation"]
                        notes = binding_info["notes"]
                        was_bound_from_catalogue = True
                        dependency_comment = f"Queue binding from catalogue: {notes} ({citation})"
                        break

            # Fallback: if not bound from catalogue, translate via expression machinery
            if not id_value and queue_name:
                id_value, _ = self._translate_bp_expression(queue_name, variable_name_mapping)
                if not id_value:
                    id_value = "%QueueId%"
            elif not id_value:
                id_value = "%QueueId%"

            result = result.replace("<id>", id_value)

        # Output variable: <var>
        if "<var>" in result:
            var_value = "obj_WorkQueueItem" if method_name == "Get Next Item" else "%OutputVar%"
            result = result.replace("<var>", var_value)

        # Work queue item object: <obj>
        if "<obj>" in result:
            result = result.replace("<obj>", "obj_WorkQueueItem")

        # Exception message / processing result: <msg>
        if "<msg>" in result:
            exception_reason = stage.params_map.get("Exception Reason", "")
            if exception_reason:
                # Use established expression translation machinery for consistency
                msg_value, _ = self._translate_bp_expression(
                    exception_reason, variable_name_mapping
                )
                if not msg_value:
                    msg_value = "%ExceptionMessage%"
            else:
                msg_value = "%ExceptionMessage%"
            result = result.replace("<msg>", msg_value)

        # Status text: <text> (note: BP key is "Status", NOT "Processing Notes")
        # Task 7a Gap 2 fix: use correct parameter key
        if "<text>" in result:
            status = stage.params_map.get("Status", "")
            if status:
                # Use established expression translation machinery for consistency
                text_value, _ = self._translate_bp_expression(status, variable_name_mapping)
                if not text_value:
                    text_value = "%Status%"
            else:
                text_value = "%Status%"
            result = result.replace("<text>", text_value)

        return result, was_bound_from_catalogue, dependency_comment

    def _render_stage(
        self,
        stage: BPStage,
        process: BPProcess | None = None,
        process_map: dict[str, Any] | None = None,
        variable_name_mapping: dict[str, str] | None = None,
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
            variable_name_mapping: Optional dict mapping lowercase BP names to PAD names (Task 5b).
                                   Used for CALCULATION, DATA, and DECISION stages.

        Returns:
            One or more Robin lines as a string (may include separate Trim/Lower action lines).

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
            return self._render_call_or_inline(stage, process, process_map, variable_name_mapping)

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
            # SetVariable handling differs by stage type:
            # - DATA: variable declaration (target_type="SetVariable" from _annotate_data)
            # - CALCULATION: assignment stage (stage_type=CALCULATION, params_map={target: expr})
            set_template = self.env.get_template("actions/set_variable.robin.j2")
            verify_comment = (
                f"{stage.name} (confidence {annotation.confidence:.2f})"
                if band == ConfidenceBand.SPOT_CHECK
                else None
            )

            # Branch based on stage type and annotation structure
            if stage.stage_type == StageType.DATA:
                # DATA stage: declaration with type and optional initial value
                # Per engine/annotator.py::_annotate_data (lines 239-243):
                # params_map = {"variable_name": stage.name, "variable_type": type, "initial_value": value}
                target_var_name = annotation.params_map.get("variable_name", stage.name)
                bp_expr = annotation.params_map.get("initial_value", "")

            elif stage.stage_type == StageType.COLLECTION:
                # COLLECTION stage: data table declaration
                # Per engine/annotator.py::_annotate_collection (lines 264-267):
                # params_map = {"table_name": stage.name, "variable_type": "DataTable"}
                target_var_name = annotation.params_map.get("table_name", stage.name)
                bp_expr = ""  # Will be set to DataTable.Create() below

            else:
                # CALCULATION stage: assignment of expression to variable
                # Stage type is CALCULATION; params_map comes from parser (lines 354-355)
                # with {calc_stage: calc_expr} shape, attached to stage.params_map not annotation
                if stage.params_map:
                    # Use the first (typically only) entry from params_map
                    target_var_name = next(iter(stage.params_map.keys()), stage.name)
                    bp_expr = next(iter(stage.params_map.values()), "")
                else:
                    # Fallback: use stage name as target, empty expression
                    target_var_name = stage.name
                    bp_expr = ""

            # Map target variable name using dotted reference resolution if needed
            if variable_name_mapping and "." in target_var_name:
                mapped_target = self._resolve_dotted_reference(
                    target_var_name, variable_name_mapping
                )
            elif variable_name_mapping:
                target_lower = target_var_name.lower()
                mapped_target = variable_name_mapping.get(target_lower, target_var_name)
            else:
                mapped_target = target_var_name

            # Translate the BP expression
            translated_expr, separate_actions = self._translate_bp_expression(
                bp_expr, variable_name_mapping
            )

            # Add any separate Trim/Lower action lines
            for action in separate_actions:
                lines.append(action)

            # Determine the final value to assign
            if stage.stage_type == StageType.COLLECTION:
                final_value = "DataTable.Create()"
            elif translated_expr:
                final_value = translated_expr
            else:
                # For empty expressions or DATA stages with no initial value
                final_value = "%SomeVar%"

            # Add the SET variable line
            rendered = set_template.render(
                var_name=mapped_target,
                value=final_value,
                verify_comment=verify_comment,
            )
            lines.append(rendered)

        elif target_type == "CreateNewDataTable":
            # COLLECTION stage: create new data table (legacy, now handled in SetVariable branch above)
            # Use the variable_name_mapping to apply proper prefixes per architecture doc §A4
            set_template = self.env.get_template("actions/set_variable.robin.j2")

            target_var_name = stage.name
            if variable_name_mapping:
                target_lower = target_var_name.lower()
                mapped_target = variable_name_mapping.get(target_lower, target_var_name)
            else:
                mapped_target = target_var_name

            rendered = set_template.render(
                var_name=mapped_target,
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
            # DECISION stage: translate the BP condition expression to PAD syntax.
            cond_template = self.env.get_template("actions/condition.robin.j2")

            # Get the BP condition expression
            bp_condition = annotation.params_map.get("condition", "[SomeCondition]")

            # Translate the BP expression
            translated_cond, separate_actions = self._translate_bp_expression(
                bp_condition, variable_name_mapping
            )

            # Add any separate Trim/Lower action lines
            for action in separate_actions:
                lines.append(action)

            rendered = cond_template.render(
                condition=translated_cond if translated_cond else "%SomeVar% = True",
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
            # Task 7a: consume the cited method_actions template. Exception-type selection
            # requires calling Block/control-flow context and is deferred to Task 7b.
            method_name = stage.params_map.get("_vbo_action")

            if band != ConfidenceBand.MANUAL:
                method_template = self._lookup_method_actions_template(stage)
                if method_template:
                    substituted, was_bound_from_catalogue, dependency_comment = (
                        self._substitute_workqueues_placeholders(
                            method_template, stage, method_name, variable_name_mapping
                        )
                    )
                    # Task 7a (a): Add VERIFY comment before Get Next Item if binding came from catalogue
                    if method_name == "Get Next Item" and was_bound_from_catalogue:
                        lines.append(
                            f"# VERIFY: Get Next Item queue ID '{substituted.split('WorkQueue: ')[1].split()[0]}' "
                            f"must be assigned from obj_Config['Ctrl_WorkQueueId'] in Load Config Data function "
                            f"(DF_PID_171_US_LIMS_Prelude_Main.robin.txt L150)"
                        )
                    if method_name == "Mark Exception":
                        lines.append("# VERIFY: Mark Exception status variant deferred to Task 7b")
                    lines.append(substituted)
                else:
                    # Fallback to generic template for unmapped methods (Tag Item, Defer, etc.)
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
            else:
                # Fallback to generic template for MANUAL band
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

    def _render_stage_list_with_coarse_blocks(
        self,
        stages: list[BPStage],
        process: BPProcess | None = None,
        process_map: dict[str, Any] | None = None,
        variable_name_mapping: dict[str, str] | None = None,
        render_stage_fn: Any = None,
    ) -> str:
        """Render a list of stages, applying the coarse BLOCK/ON BLOCK ERROR pattern (§A5, §B15).

        When a BLOCK stage has ``recover_stage_id`` set (Task 4b persistence), that BLOCK
        wraps everything between itself and its paired RECOVER in a single coarse BLOCK —
        one BLOCK per real BP Block stage, never one per CALL (§B15 generation rule).

        The ``ON BLOCK ERROR`` handler body is a flat action sequence:
        ``SET txt_ItemStatus TO 'System Exception'`` + ``GOTO '<label>'`` (§B15),
        with no ``IF`` inside (§A5 hard constraint).

        Continuation stages (SubSheet calls to pages whose BP name contains "Exception"
        between BLOCK and RECOVER) are placed under ``LABEL '<bp_page_name>'`` after the
        BLOCK body — they are the recovery dispatch targets, not re-executed inside the
        protected scope (§B15 worked example).

        Stages with no enclosing BLOCK (``recover_stage_id`` is None) are rendered
        normally via ``render_stage_fn`` — no wrapping is invented (§B15 Do-step 5).

        Args:
            stages: Ordered stage list to render.
            process: The BPProcess (forwarded to per-stage renderers).
            process_map: Process map from page_target_map.yaml.
            variable_name_mapping: Optional BP-name→PAD-name dict from Task 5b.
            render_stage_fn: Callable(stage, process, process_map, variable_name_mapping) → str.
                             Defaults to ``self._render_stage``.

        Returns:
            All rendered lines joined by newlines.
        """
        if render_stage_fn is None:
            render_stage_fn = self._render_stage

        # Identify coarse-BLOCK groups: map from BLOCK stage_id → (block_idx, recover_idx, resume_idx)
        # A coarse BLOCK is one whose recover_stage_id is set (Task 4b).
        coarse_block_map: dict[str, tuple[int, int, int | None]] = {}
        for idx, stage in enumerate(stages):
            if stage.stage_type == StageType.BLOCK and stage.recover_stage_id:
                recover_id = stage.recover_stage_id
                # Find the RECOVER stage index
                recover_idx = next(
                    (i for i, s in enumerate(stages) if s.stage_id == recover_id),
                    None,
                )
                if recover_idx is None:
                    # Recover stage not in this list — skip coarse-BLOCK treatment
                    continue
                # Find the first RESUME after the RECOVER
                resume_idx: int | None = next(
                    (
                        i
                        for i, s in enumerate(stages)
                        if i > recover_idx and s.stage_type == StageType.RESUME
                    ),
                    None,
                )
                coarse_block_map[stage.stage_id] = (idx, recover_idx, resume_idx)

        # Build the set of stage indices that are consumed as part of a coarse BLOCK group
        # so we can skip them in the main render loop.
        consumed_indices: set[int] = set()
        for _block_id, (block_idx, recover_idx, resume_idx) in coarse_block_map.items():
            consumed_indices.add(block_idx)  # the BLOCK stage itself
            consumed_indices.add(recover_idx)  # the RECOVER stage
            if resume_idx is not None:
                consumed_indices.add(resume_idx)  # the RESUME stage

        output_lines: list[str] = []
        idx = 0
        while idx < len(stages):
            stage = stages[idx]

            # Is this the opener of a coarse BLOCK group?
            if stage.stage_id in coarse_block_map:
                block_idx, recover_idx, resume_idx = coarse_block_map[stage.stage_id]

                # --- Identify continuation stages (go under LABELs, outside BLOCK) ---
                # These are SubSheet calls between BLOCK and RECOVER that target pages whose
                # name contains "Exception" or "Completed" (the item-status-update terminal
                # pages — §B15 worked example: 'Mark Item as Completed' + 'Mark Item as
                # Exception').  The exception page is the dispatch label; the completed page
                # goes under its own LABEL first so the happy-path flow can GOTO it directly
                # and then skip past the exception label (per reference lines 1473–1483).
                exception_label: str | None = None
                continuation_indices: set[int] = set()
                # (label, stage) — ordered: Completed first, Exception second, matching reference
                continuation_stages: list[tuple[str, BPStage]] = []
                if process is not None:
                    for body_idx in range(block_idx + 1, recover_idx):
                        body_stage = stages[body_idx]
                        if body_stage.is_subsheet_call and body_stage.processid:
                            tp = next(
                                (p for p in process.pages if p.page_id == body_stage.processid),
                                None,
                            )
                            if tp and "exception" in tp.name.lower():
                                exception_label = tp.name
                                continuation_indices.add(body_idx)
                                # Exception stage added last (after Completed) — see ordering
                            elif tp and "completed" in tp.name.lower():
                                continuation_indices.add(body_idx)
                                continuation_stages.append((tp.name, body_stage))

                    # Append exception stage last so LABEL order is: Completed … Exception
                    if exception_label is not None:
                        for body_idx in range(block_idx + 1, recover_idx):
                            body_stage = stages[body_idx]
                            if body_stage.is_subsheet_call and body_stage.processid:
                                tp = next(
                                    (p for p in process.pages if p.page_id == body_stage.processid),
                                    None,
                                )
                                if tp and tp.name == exception_label:
                                    continuation_stages.append((tp.name, body_stage))
                                    break

                # The post-block gating IF dispatches to the exception label (§A5 Do-step 2,
                # §B15 reference line 1469: "IF flg_ErrorOccurred = True THEN GOTO … END").
                # If no exception continuation page is found, fall back to 'Error Block', which
                # is always present in the epilogue (via _render_goto_epilogue) when any GOTO
                # appears in the body (§A5 architecture doc).
                dispatch_label = exception_label if exception_label is not None else "Error Block"

                # The skip-GOTO from the Completed section must jump PAST the exception section
                # to a third label placed after all continuation sections — not to the exception
                # label itself.  In the reference this is 'Reset All' (line 1477→1490).
                # We synthesize it as '<block_name> end' so it is unique per BLOCK.
                # (§B15 reference lines 1477, 1490 — GOTO 'Reset All' → LABEL 'Reset All')
                reset_label = f"{stage.name} end"

                # --- Build the coarse BLOCK header (§A5 3-arm dispatch template) ---
                # Typed handler arms use the §A5 3-tier taxonomy directly — stage.exception_type
                # is never set on BLOCK stages (only on EXCEPTION/throw stages, per ast/models.py),
                # so we always emit the full typed arms from the module-level constant (§A5).
                block_template = self.env.get_template("actions/error_block.robin.j2")
                typed_handlers: list[dict[str, object]] = [
                    {"error_code": err_code, "actions": list(actions)}
                    for err_code, actions in _COARSE_TYPED_HANDLERS
                ]
                output_lines.append(
                    block_template.render(
                        block_name=stage.name,
                        typed_handlers=typed_handlers,
                        catchall_actions=list(_COARSE_CATCHALL_ACTIONS),
                    )
                )

                # --- Render the BLOCK body (stages between BLOCK and RECOVER) ---
                # Continuation stages (Exception, Completed) are excluded — they live
                # under LABELs after END, not re-executed inside the protected scope.
                for body_idx in range(block_idx + 1, recover_idx):
                    if body_idx in continuation_indices:
                        continue
                    body_stage = stages[body_idx]
                    rendered = render_stage_fn(
                        body_stage, process, process_map, variable_name_mapping
                    )
                    if rendered:
                        output_lines.append(rendered)

                # --- Close the BLOCK body ---
                output_lines.append("END")

                # --- Post-block gating IF (§A5 Do-step 2, §B15 reference lines 1469–1472) ---
                # "any branching on what happened belongs in a plain IF placed after the
                # enclosing scope, checking a flag the handler set" — §A5 hard constraint.
                # This is the gate that routes between the Completed and Exception paths.
                # Without it, execution falls through LABEL 'Mark Item as Completed' and
                # LABEL 'Mark Item as Exception' unconditionally (Robin LABELs are no-ops).
                output_lines.append(
                    f"IF {COARSE_BLOCK_ERROR_FLAG} = True THEN"  # §A5, §B15 ref L1469
                )
                output_lines.append(
                    "    SET txt_ItemStatus TO $'''Failed'''"  # §B15 ref L1470
                )
                output_lines.append(
                    f"    GOTO '{dispatch_label}'"  # §B15 ref L1471
                )
                output_lines.append("END")

                # --- Render continuation sections under their labels (§B15) ---
                # Order: LABEL 'Mark Item as Completed' (with skip-GOTO) then
                #        LABEL 'Mark Item as Exception' — matching reference lines 1473–1483.
                seen_labels: set[str] = set()
                for cont_label, cont_stage in continuation_stages:
                    if cont_label in seen_labels:
                        continue
                    seen_labels.add(cont_label)
                    output_lines.append(
                        f"LABEL '{cont_label}'"  # §B15
                    )
                    rendered = render_stage_fn(
                        cont_stage, process, process_map, variable_name_mapping
                    )
                    if rendered:
                        output_lines.append(rendered)
                    # After the Completed section, skip past the Exception label to the reset
                    # label — a third label placed after all continuation sections (§B15 ref
                    # L1477: GOTO 'Reset All').  Jumping to 'exception_label' would be a no-op
                    # because it is the immediately following label; the GOTO must reach past it.
                    if exception_label is not None and cont_label != exception_label:
                        output_lines.append(
                            f"GOTO '{reset_label}'"  # §B15 ref L1477 → 'Reset All'
                        )

                # --- Emit the reset label after all continuation sections (§B15 ref L1490) ---
                # Happy-path skip-GOTO lands here; exception path falls through to here too.
                # This label is the per-item "Reset All" equivalent — execution continues with
                # whatever stages follow (DataGateway block, per-item resets, etc.).
                if continuation_stages:
                    output_lines.append(
                        f"LABEL '{reset_label}'"  # §B15 ref L1490
                    )

                # --- Advance past all consumed stages in this group ---
                # Skip to after the RESUME (or after the RECOVER if no RESUME found).
                idx = resume_idx + 1 if resume_idx is not None else recover_idx + 1
                continue

            # Not part of a coarse-BLOCK group — render normally
            if idx not in consumed_indices:
                rendered = render_stage_fn(stage, process, process_map, variable_name_mapping)
                if rendered:
                    output_lines.append(rendered)
            idx += 1

        return "\n".join(output_lines)

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
