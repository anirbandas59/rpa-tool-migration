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

        # Extract queue_bindings from the WorkQueues VBO entry (Task 7a).
        # Queue bindings map BP queue expressions to PAD variables with citations.
        self.queue_bindings: dict[str, dict[str, str]] = {}
        workqueues_entry = self.mapping_config.get_vbo_entry(
            "Blueprism.Automate.clsWorkQueuesActions"
        )
        if workqueues_entry and workqueues_entry.queue_bindings:
            for binding in workqueues_entry.queue_bindings:
                if binding.expression_pattern:
                    self.queue_bindings[binding.expression_pattern] = {
                        "pad_variable": binding.pad_variable,
                        "citation": binding.citation,
                        "notes": binding.notes,
                    }

        # Instance variable to hold the current page name resolution map (built during
        # role-based generation to handle collision disambiguation — Task 6b2).
        # Used by _render_page_as_function and _render_call_or_inline to ensure both
        # FUNCTION definitions and CALL sites use consistent resolved names (with
        # suffixes for accidental collisions, not intentional folds).
        self._current_page_name_map: dict[str, str] = {}

        # Instance variable holding the set of lowercase BP data-item names whose
        # initialising SET must be suppressed while rendering the current FUNCTION body
        # (Task 7b0 Do item 3) — set from _render_page_as_function/_split_page_into_functions
        # before rendering that FUNCTION's stages, and restored afterward. Consulted by
        # _render_stage's DATA/COLLECTION branches.
        self._current_suppress_init_names: set[str] = set()

        # Instance variable holding the BPPage currently being rendered as a body
        # (Main page for a role, a "function"-shaped page, or a "split" page's whole
        # page — never just a rendered subset/slice), set before rendering that body's
        # stages and restored afterward. Task 7b0 fix pass 5 gap 1: consulted by
        # _hoist_data_inits_for_inline_copy so the "declared by both the host page and
        # the inlined page" check (item 8 clarification) is checked against the host's
        # *full* BP page declarations, not just the current role/slice's rendered
        # subset — docs/reviews/7b0-2026-09-24-fixpass4.md gap 1(a)/(b).
        self._current_host_page: Any | None = None

        # Task 7b: the exception-type branch ("system" | "business" | None) currently
        # being rendered, set by _render_decision_branch while walking a Decision's
        # true/false branches, consulted by _render_stage's WorkQueues branch to pick
        # the "Mark Exception" status variant generically from *where in the BP
        # decision structure* the stage sits — never from the stage's own name or a
        # Tag value (task hard constraint; rejected heuristic per
        # docs/reviews/7a-2026-09-04-thirdpass.md). None means "not determinable from
        # a recognised branch", which keeps the pre-existing
        # "# VERIFY: Mark Exception status variant deferred to Task 7b" marker.
        self._current_exception_branch_context: str | None = None

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
                construct_type="function",  # Task 7b0: every FUNCTION is GLOBAL (template-fixed)
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

            # Task 7b0 Do item 8: hoist Main's own DATA/COLLECTION inits — only the
            # subset this role actually renders (``stages_to_render`` is already
            # role-filtered above, L523-547 — fix pass 4 gap 1: an inline_block/fold
            # target's inits are no longer collected transitively here under option A,
            # they render at their own inlined-copy start instead, so a Loader-only
            # target's inits can no longer leak into the Performer Main) — to the top
            # of the main body.
            #
            # Fix pass 4 gap 2: Main's Start-stage inputs become the flow's ``@INPUT``s
            # (Task 7c) — a hoisted re-init must never clobber one (e.g.
            # ``flg_SendDatatoDataGateways``). Exclude them the same way Do item 3
            # excludes a FUNCTION's own In_/Out_ parameters.
            main_input_bound = self._get_input_bound_names(main_page)
            hoistable_sources = self._collect_hoistable_stage_sources(
                stages_to_render, process, process_map, variable_name_mapping
            )
            hoisted_inits, suppress_names = self._hoist_data_inits_from_sources(
                hoistable_sources, process, process_map, set(main_input_bound.keys())
            )

            previous_suppress = self._current_suppress_init_names
            previous_host_page = self._current_host_page
            self._current_suppress_init_names = suppress_names
            # Fix pass 5 gap 1: the host page for any inline_block/fold call rendered
            # inside this body is Main Page itself (its full declarations, not just
            # this role's rendered subset) — see _hoist_data_inits_for_inline_copy.
            self._current_host_page = main_page
            try:
                actions_content = self._render_stage_list_with_coarse_blocks(
                    stages_to_render,
                    process,
                    process_map,
                    variable_name_mapping,
                    render_stage_fn=_render_main_stage,
                )
            finally:
                self._current_suppress_init_names = previous_suppress
                self._current_host_page = previous_host_page

            if hoisted_inits:
                actions_content = (
                    f"{hoisted_inits}\n{actions_content}" if actions_content else hoisted_inits
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

            elif shape in ("inline_block", "fold"):
                # Unreachable in practice: the only caller (generate_process's
                # per-role loop, ~L436-444) already ``continue``s past every
                # inline_block/fold page before calling this method — those pages
                # are only ever rendered on demand, from _render_call_or_inline's
                # own inline_block/fold branches (item 8, option A's per-copy
                # init/suppression logic). Task 7b0 fix pass 5 gap 6
                # (docs/reviews/7b0-2026-09-24-fixpass4.md (e)): raise instead of
                # rendering, so a future caller can never bypass option A's
                # per-inlined-copy data-init handling by reaching this path.
                raise GenerationError(
                    f"Page '{page.name}' has shape '{shape}' and must be rendered "
                    "only via _render_call_or_inline's inline_block/fold branches "
                    "(Task 7b0 item 8, option A) — _render_page_in_consolidated_flow "
                    "has no per-copy data-init handling for it"
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

            # Task 7b0: generate CALL with arguments instead of shared-variable bindings
            call_with_args = self._render_page_call_with_arguments(
                stage, target_page, target_name, variable_name_mapping
            )

            return call_with_args

        elif shape == "inline_block":
            # Inline BLOCK content into container
            block_name = shape_info.get("block_name", target_page.name)
            container = shape_info.get("container", "Loader_Main_Body")
            citation = shape_info.get("citation", "§B14")
            notes = shape_info.get("notes", "")

            # Task 7b0 gap 6 (review 2026-09-24-fixpass2): inline_block content rendered
            # from inside a parameterised FUNCTION body must not inherit that FUNCTION's
            # In_/Out_ override map — a folded page's own data item sharing a name with
            # the host's parameter would otherwise be silently renamed. Isolate by
            # recomputing the plain per-process mapping (never the host's overridden one)
            # for this target's own stages.
            inline_mapping = (
                self._build_variable_name_mapping(process)
                if process is not None
                else variable_name_mapping
            )

            # Task 7b0 Do item 8, option A (fix pass 4): this inline_block target's own
            # DATA/COLLECTION inits render at the start of THIS inlined copy (BP resets
            # a page's data items every time it runs, and an inlined page runs on every
            # call) — except a name already hoisted by an ancestor host body (shared
            # declaration, e.g. Loader's ``dtb_MailItems``), which is suppressed here
            # instead of repeated. See ``_hoist_data_inits_for_inline_copy``.
            local_inits, copy_suppress = self._hoist_data_inits_for_inline_copy(
                target_page, process, process_map, inline_mapping
            )
            previous_suppress = self._current_suppress_init_names
            previous_host_page = self._current_host_page
            self._current_suppress_init_names = copy_suppress
            # Fix pass 5 gap 1: a further inline_block/fold nested inside this copy
            # treats this copy's own page as its host, not the outer host.
            self._current_host_page = target_page
            try:
                # Render the target page's stages
                action_lines: list[str] = []
                for s in target_page.stages:
                    rendered = self._render_stage(s, process, process_map, inline_mapping)
                    if rendered:
                        action_lines.append(rendered)

                actions_content = "\n".join(action_lines)
            finally:
                self._current_suppress_init_names = previous_suppress
                self._current_host_page = previous_host_page

            if local_inits:
                actions_content = (
                    f"{local_inits}\n{actions_content}" if actions_content else local_inits
                )
            epilogue = self._render_goto_epilogue(actions_content)
            if epilogue:
                actions_content = f"{actions_content}\n{epilogue}"

            # Emit the inline BLOCK
            block_template = self.env.get_template("subflow.robin.j2")
            block = block_template.render(
                subflow_name=block_name,
                actions=actions_content,
                construct_type="block",
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

            # Task 7b0 gap 6: same mapping isolation as the inline_block branch above —
            # fold content must not inherit the host FUNCTION's In_/Out_ override map.
            fold_mapping = (
                self._build_variable_name_mapping(process)
                if process is not None
                else variable_name_mapping
            )

            # Task 7b0 Do item 8, option A (fix pass 4): this fold target's own
            # DATA/COLLECTION inits render at the start of THIS inlined copy, except a
            # name already hoisted by an ancestor host body (shared declaration) —
            # see ``_hoist_data_inits_for_inline_copy`` and the inline_block branch above.
            local_inits, copy_suppress = self._hoist_data_inits_for_inline_copy(
                target_page, process, process_map, fold_mapping
            )
            previous_suppress = self._current_suppress_init_names
            previous_host_page = self._current_host_page
            self._current_suppress_init_names = copy_suppress
            # Fix pass 5 gap 1: a further inline_block/fold nested inside this copy
            # treats this copy's own page as its host, not the outer host.
            self._current_host_page = target_page
            try:
                # Render the target page's stages
                action_lines: list[str] = []
                for s in target_page.stages:
                    rendered = self._render_stage(s, process, process_map, fold_mapping)
                    if rendered:
                        action_lines.append(rendered)

                actions_content = "\n".join(action_lines)
            finally:
                self._current_suppress_init_names = previous_suppress
                self._current_host_page = previous_host_page

            if local_inits:
                actions_content = (
                    f"{local_inits}\n{actions_content}" if actions_content else local_inits
                )

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

            # Task 7b0: generate CALL with arguments
            call_with_args = self._render_page_call_with_arguments(
                stage, target_page, entry_point, variable_name_mapping
            )
            comment = f"# {citation} — split: routed to entry point '{entry_point}'"
            comment += (
                "\n# TODO: split routing to real per-function call chain still needs verification"
            )
            return f"{comment}\n{call_with_args}"

        elif shape == "stop":
            # Orphan/unreachable page — emit a comment instead of a CALL
            reason = shape_info.get("reason", "No PAD counterpart")
            citation = shape_info.get("citation", "§B14")
            return f"# STOP: {target_page.name} — {reason} ({citation})"

        else:
            return f"# TODO: Unknown shape '{shape}' for target page '{target_page.name}'"

    def _extract_function_parameters(
        self,
        page: Any,
    ) -> str:
        """Extract and format parameter list for a FUNCTION header (Task 7b0).

        Examines START and END stages to extract input/output parameters,
        maps them to PAD variable names, and formats as:
        In_txt_FileName, In_num_Count, OUTPUT Out_txt_Result

        Per architecture doc §A4, parameter names are prefixed with In_/Out_
        and include the type prefix (txt_, num_, etc.) based on the data item's type.

        Args:
            page: The BPPage.

        Returns:
            Parameter list string, e.g., "In_txt_FileName, OUTPUT Out_txt_Result",
            or empty string if no parameters.
        """
        input_params: list[str] = []
        output_params: list[str] = []

        # Find START and END stages
        start_stage = None
        end_stage = None
        for stage in page.stages:
            if stage.stage_type == StageType.START:
                start_stage = stage
            elif stage.stage_type == StageType.END:
                end_stage = stage

        # Extract inputs from START stage
        if start_stage and start_stage.data_items:
            for data_item in start_stage.data_items:
                if data_item.is_input:
                    # Get the data item name this parameter binds to (from stage= attribute)
                    data_item_name = start_stage.inputs_stage_map.get(
                        data_item.name, data_item.name
                    )

                    # Generate PAD variable name with type prefix
                    pad_var_name = self._apply_type_prefix(data_item_name, data_item.data_type)

                    # Add In_ prefix per §A4
                    param_name = f"In_{pad_var_name}"
                    input_params.append(param_name)

        # Extract outputs from END stage
        if end_stage and end_stage.data_items:
            for data_item in end_stage.data_items:
                if data_item.is_output:
                    # Get the data item name this parameter binds to (from stage= attribute)
                    data_item_name = end_stage.outputs_stage_map.get(data_item.name, data_item.name)

                    # Generate PAD variable name with type prefix
                    pad_var_name = self._apply_type_prefix(data_item_name, data_item.data_type)

                    # Add Out_ prefix per §A4
                    param_name = f"Out_{pad_var_name}"
                    output_params.append(param_name)

        # Format parameter list. Single-output form (reference L1226, L1155): "In_x, OUTPUT Out_z".
        # Multi-output form: OUTPUT is repeated before EACH output parameter, not just the
        # first — reference L232 ("OUTPUT out_txt_SampleId, OUTPUT out_dtb_DataCollection"),
        # L622 (4 outputs, each prefixed with OUTPUT), L1167 ("OUTPUT Out_flg_Success, OUTPUT
        # Out_txt_Message"). Without the repeated keyword, PAD reads the second+ output as an
        # (untyped) input.
        output_part = ", ".join(f"OUTPUT {name}" for name in output_params)
        if input_params and output_part:
            return ", ".join(input_params) + ", " + output_part
        elif input_params:
            return ", ".join(input_params)
        elif output_part:
            return output_part
        else:
            # No parameters
            return ""

    def _render_page_call_with_arguments(
        self,
        call_stage: BPStage,
        target_page: Any,
        target_name: str,
        variable_name_mapping: dict[str, str] | None = None,
    ) -> str:
        """Render a CALL statement with arguments (Task 7b0).

        Generates `CALL '<name>' In_a: <expr> Out_c=> <var>` format, including
        helper actions from expression translation before the CALL.

        Per Task 7b0:
        - Inputs are passed as `In_<data_item>: <caller_expr>`
        - Outputs are captured as `Out_<data_item>=> <caller_var>`
        - Helper actions (Trim, Lower, etc.) are emitted before the CALL

        Args:
            call_stage: The calling ACTION stage (is_subsheet_call or is_process_call).
            target_page: The target BPPage.
            target_name: The resolved PAD name of the target FUNCTION.
            variable_name_mapping: Optional mapping for translating data item names.

        Returns:
            Rendered CALL statement with arguments and any helper actions, or
            empty string with TODO comments for unresolvable bindings.

        Raises:
            GenerationError: If CALL rendering fails.
        """
        if not target_page or not target_page.stages:
            return ""

        # Find START and END stages in target page
        start_stage = None
        end_stage = None
        for stage in target_page.stages:
            if stage.stage_type == StageType.START:
                start_stage = stage
            elif stage.stage_type == StageType.END:
                end_stage = stage

        helper_actions: list[str] = []
        input_args: list[str] = []
        output_args: list[str] = []
        # Task 7b0 gap 6: unresolvable-binding TODOs go on their own line BEFORE the CALL,
        # never inline inside the argument string — a `#` mid-line comments out every
        # argument after it in PAD, which is a silent drop.
        pre_call_todos: list[str] = []

        # Process input bindings from START stage
        if start_stage and start_stage.data_items:
            for data_item in start_stage.data_items:
                if data_item.is_input:
                    # Get the data item this parameter binds to (from stage= attribute)
                    data_item_name = start_stage.inputs_stage_map.get(
                        data_item.name, data_item.name
                    )

                    # Generate the parameter name (In_ prefix)
                    pad_var_name = self._apply_type_prefix(data_item_name, data_item.data_type)
                    param_name = f"In_{pad_var_name}"

                    # Get the caller's expression from call_stage params_map
                    caller_expr = None
                    if call_stage.params_map and data_item.name in call_stage.params_map:
                        caller_expr = call_stage.params_map[data_item.name]

                    if caller_expr:
                        # Translate the expression and unpack helper actions
                        translated_expr, actions = self._translate_bp_expression(
                            caller_expr, variable_name_mapping or {}
                        )
                        if actions:
                            helper_actions.extend(actions)

                        # Task 7b0 gap 5: a translated expression containing a space (e.g. a
                        # raw BP field name like `dtb_ConfigFileData.Sub Folder`) is not valid
                        # PAD syntax unmarked at a call site. Flag it with a TODO on its own
                        # line before the CALL, but keep the argument in the CALL (per Do item
                        # 4's "never a silent drop" — the root cause is Task 5b's translator).
                        if " " in translated_expr.strip():
                            pre_call_todos.append(
                                f"# TODO: call argument '{param_name}' → '{translated_expr}' "
                                f"for page '{target_page.name}' contains a raw BP field name "
                                "with a space — not valid PAD syntax as-is"
                            )

                        # Format as In_param: <expr>
                        input_args.append(f"{param_name}: {translated_expr}")
                    elif caller_expr == "":
                        # Empty expression — skip this input (per task)
                        pass
                    else:
                        # Unresolvable input — emit TODO on its own line, never inline
                        pre_call_todos.append(
                            f"# TODO: unresolvable input '{data_item.name}' → {param_name} "
                            f"for page '{target_page.name}'"
                        )

        # Process output bindings from END stage
        if end_stage and end_stage.data_items:
            for data_item in end_stage.data_items:
                if data_item.is_output:
                    # Get the data item this parameter binds to (from stage= attribute)
                    data_item_name = end_stage.outputs_stage_map.get(data_item.name, data_item.name)

                    # Generate the parameter name (Out_ prefix)
                    pad_var_name = self._apply_type_prefix(data_item_name, data_item.data_type)
                    param_name = f"Out_{pad_var_name}"

                    # Task 7b0 gap 7: outputs come ONLY from the call stage's captured
                    # outputs_stage_map (the <output stage="..."> binding) — the params_map
                    # fallback removed here was the input/output crossover both reviews
                    # flagged (an input's expression could land as an output's target).
                    caller_var = None
                    if (
                        call_stage.outputs_stage_map
                        and data_item.name in call_stage.outputs_stage_map
                    ):
                        caller_var = call_stage.outputs_stage_map[data_item.name]

                    if caller_var:
                        # Translate the caller's variable name if needed
                        if variable_name_mapping and caller_var.lower() in variable_name_mapping:
                            caller_var = variable_name_mapping[caller_var.lower()]

                        if " " in caller_var.strip():
                            pre_call_todos.append(
                                f"# TODO: call argument '{param_name}' → '{caller_var}' "
                                f"for page '{target_page.name}' contains a raw BP field name "
                                "with a space — not valid PAD syntax as-is"
                            )

                        # Format as Out_param=> <var>
                        output_args.append(f"{param_name}=> {caller_var}")
                    else:
                        # Unresolvable output — emit TODO on its own line, never inline
                        pre_call_todos.append(
                            f"# TODO: unresolvable output '{data_item.name}' → {param_name} "
                            f"for page '{target_page.name}'"
                        )

        # Build the CALL statement
        all_args = input_args + output_args
        args_str = " ".join(all_args) if all_args else ""

        call_stmt = f"CALL '{target_name}' {args_str}" if args_str else f"CALL '{target_name}'"

        # Combine helper actions, TODO comments (own line, before CALL) and the CALL itself
        result_parts: list[str] = []
        if helper_actions:
            result_parts.extend(helper_actions)
        if pre_call_todos:
            result_parts.extend(pre_call_todos)
        result_parts.append(call_stmt)

        return "\n".join(result_parts)

    def _data_collection_target_name(self, stage: BPStage) -> str | None:
        """Return the PAD variable name a DATA/COLLECTION stage initialises, or None.

        Mirrors the target-name extraction ``_render_stage`` uses for its ``SetVariable``
        (DATA, ``engine/annotator.py::_annotate_data`` ``params_map["variable_name"]``) and
        ``CreateNewDataTable`` (COLLECTION, ``_annotate_collection`` ``params_map["table_name"]``)
        branches, so callers can identify a data item's declaring stage without duplicating
        that dispatch logic.

        Args:
            stage: Any BPStage.

        Returns:
            The declared variable/table name if ``stage`` is a DATA or COLLECTION stage,
            else None.
        """
        if stage.stage_type == StageType.DATA:
            if stage.pa_annotation and stage.pa_annotation.params_map:
                return stage.pa_annotation.params_map.get("variable_name", stage.name)
            return stage.name
        if stage.stage_type == StageType.COLLECTION:
            if stage.pa_annotation and stage.pa_annotation.params_map:
                return stage.pa_annotation.params_map.get("table_name", stage.name)
            return stage.name
        return None

    def _get_page_declared_names(self, page: Any) -> set[str]:
        """Return the lowercase names of every DATA/COLLECTION stage a BP page declares.

        Task 7b0 fix pass 5 gap 1(a): the "declared by both the host page and the
        inlined page" check (item 8 clarification, ``docs/reviews/
        7b0-2026-09-24-fixpass4.md`` gap 1) must consult **every** data item the host
        BP page declares, not only the subset the current role/slice happens to
        render — a name on the other role's side of the Main-page split (e.g. Loader's
        ``dtb_MailItems``, whose Main-page ``Mail Items`` DATA stage sits in the
        Performer-role stage range) still counts.

        Args:
            page: The host BPPage (its full ``page.stages``, unfiltered by role/slice).

        Returns:
            A set of lowercase DATA/COLLECTION target names declared anywhere on
            ``page``.
        """
        return {
            name.lower()
            for stage in page.stages
            if (name := self._data_collection_target_name(stage)) is not None
        }

    def _collect_hoistable_stage_sources(
        self,
        stages: list[BPStage],
        process: BPProcess | None,
        process_map: dict[str, Any] | None,
        host_mapping: dict[str, str] | None,
    ) -> list[tuple[BPStage, dict[str, str] | None]]:
        """Collect this host body's own DATA/COLLECTION stages, for top-of-body hoisting.

        Task 7b0 Do item 8, option A (user decision 2026-09-24, superseding fix pass 3's
        "hoist inline_block/fold targets' inits too"): only a host body's *own* DATA/
        COLLECTION stages are unconditionally hoisted to that body's top. An
        inline_block/fold *target*'s own inits are never collected here — they render at
        the start of each inlined copy instead (``_hoist_data_inits_for_inline_copy``,
        called from ``_render_call_or_inline``'s inline_block/fold branches), because BP
        resets a page's data items every time that page runs, and an inlined page "runs"
        on every call, not once per host. The one exception (a name declared by *both*
        the host and the inlined page, e.g. Loader's ``dtb_MailItems`` — 'Main Page' and
        its inline_block target 'Populate Queue' both declare a "Mail Items" data item,
        per ``outputs/report/PID_0171_html_report_20260904/data/
        pid-171-us-process-lims-prelude.md`` L370 and L1302) is handled at the inline
        call site: the target's copy of that name is suppressed there because it is
        already in ``self._current_suppress_init_names`` once the host's own version
        (collected here) has been hoisted.

        Args:
            stages: The stage list to scan (a page's full ``page.stages``, a split
                target's stage slice, or a Main-page role's rendered stage subset).
            process: Unused (kept for call-site symmetry with other hoisting helpers).
            process_map: Unused (kept for call-site symmetry with other hoisting helpers).
            host_mapping: The host body's variable-name mapping, paired with each stage.

        Returns:
            A list of (stage, mapping) pairs, in stage order, ready to be rendered by
            ``_hoist_data_inits_from_sources``.
        """
        del process, process_map  # unused: no recursion under option A — see docstring
        return [
            (stage, host_mapping)
            for stage in stages
            if self._data_collection_target_name(stage) is not None
        ]

    def _hoist_data_inits_for_inline_copy(
        self,
        target_page: Any,
        process: BPProcess | None,
        process_map: dict[str, Any] | None,
        mapping: dict[str, str] | None,
    ) -> tuple[str, set[str]]:
        """Render an inlined page's own DATA/COLLECTION inits at its own copy's top.

        Task 7b0 Do item 8, option A: each inlined copy of an inline_block/fold target
        gets its own data initialisations at the start of that copy — a page inlined
        twice initialises twice (e.g. 'Sample Manager - Explorer', inlined twice into
        'Enter Results in App', re-inits its retry counter each time) — *except*, in
        priority order:

        1. (fix pass 5 gap 1(b)) a name that is this inlined page's own Start-stage
           input: BP applies the caller's input value over the initial value, so the
           inlined page's own declaration is never re-run — no TODO, this is the
           intended input hand-off, not a collision (e.g. Loader's 'Populate Queue'
           receiving 'Mail Items' from the preceding 'Fetch Emails from Mailbox'
           CALL's captured output).
        2. (fix pass 5 gap 1(a), ``docs/reviews/7b0-2026-09-24-fixpass4.md``) a name
           declared anywhere on ``self._current_host_page`` — the host BP page's
           *full* declarations, not just this body's rendered role/slice subset —
           even when the host's own declaration isn't rendered in this body at all
           (e.g. it sits on the other role's side of the Main-page split). This is a
           genuine cross-page name collision (same PAD variable, two independent BP
           declarations, neither one a caller-to-callee hand-off), so it gets a
           ``# TODO`` naming the suppressed per-run reset (fix pass 5 gap 2, Task
           7b1) — e.g. Result Entry / Sample Manager - Explorer's shared 'Retry
           Count'. Checked before the plain ancestor-suppress case below so a host
           that *does* render its own copy of the name in this same body (already in
           ``self._current_suppress_init_names``) still gets flagged, not silently
           skipped.
        3. a name already hoisted/suppressed by an ancestor host body this run for an
           unrelated reason (present in ``self._current_suppress_init_names`` on
           entry, e.g. it coincides with an ambient FUNCTION parameter name) — inits
           once elsewhere and must not repeat here; no TODO, since it is not
           necessarily a second BP page declaration.

        Args:
            target_page: The inline_block/fold target BPPage being inlined.
            process: The BPProcess (forwarded so init expressions needing CALL
                resolution render correctly).
            process_map: The process entry from page_target_map.yaml.
            mapping: The target's own (un-overridden — gap 6) variable-name mapping.

        Returns:
            A 2-tuple: (hoisted_inits_text, copy_suppress_names) where
            ``copy_suppress_names`` is the suppress set to use while rendering this
            inlined copy's remaining stages — the inherited ancestor suppress set plus
            this copy's own newly hoisted/suppressed names.
        """
        ancestor_suppress = self._current_suppress_init_names
        host_page = self._current_host_page
        host_declared = self._get_page_declared_names(host_page) if host_page is not None else set()
        own_input_bound = self._get_input_bound_names(target_page)

        own_sources: list[tuple[BPStage, dict[str, str] | None]] = []
        collision_todos: list[str] = []
        collision_suppress: set[str] = set()
        for stage in target_page.stages:
            name = self._data_collection_target_name(stage)
            if name is None:
                continue
            name_lower = name.lower()
            if name_lower in own_input_bound:
                # This inlined page's own Start-stage input — the caller's argument
                # applies over the initial value; never re-init it here (gap 1(b)).
                continue
            if host_page is not None and name_lower in host_declared:
                # Declared by both the host BP page and this inlined page (gap 1(a)):
                # a cross-page name collision, not a caller-supplied input. Suppress
                # the per-copy reset the inlined page relied on and flag it (gap 2).
                # Checked ahead of the plain ancestor-suppress case so a host that
                # renders its own copy in this very body is still flagged.
                collision_suppress.add(name_lower)
                collision_todos.append(
                    f"# TODO: '{name}' per-run reset suppressed — declared on both "
                    f"'{host_page.name}' and '{target_page.name}'; the two BP data "
                    "items collapse into one PAD variable under Task 7b0's all-GLOBAL "
                    "output (Task 7b1 name-collision disambiguation)"
                )
                continue
            if name_lower in ancestor_suppress:
                # Already hoisted/suppressed once elsewhere, for an unrelated reason.
                continue
            own_sources.append((stage, mapping))

        hoisted_text, suppress_from_sources = self._hoist_data_inits_from_sources(
            own_sources, process, process_map, ancestor_suppress
        )
        all_suppress = suppress_from_sources | set(own_input_bound.keys()) | collision_suppress
        if collision_todos:
            todo_text = "\n".join(collision_todos)
            hoisted_text = f"{todo_text}\n{hoisted_text}" if hoisted_text else todo_text
        return hoisted_text, all_suppress

    def _hoist_data_inits_from_sources(
        self,
        stage_sources: list[tuple[BPStage, dict[str, str] | None]],
        process: BPProcess | None,
        process_map: dict[str, Any] | None,
        param_suppress_names: set[str],
    ) -> tuple[str, set[str]]:
        """Render DATA/COLLECTION initialising SETs up front (Task 7b0 Do item 8).

        BP Data/Collection stages are not part of a page's flow: their initial values
        apply when the page starts, not at the stage's position in the flow. Hoisting
        every non-parameter-bound data item's initialising ``SET``/``DataTable.Create()``
        to the top of the body (and suppressing it at its original flow position) stops a
        caller's own re-initialisation from wiping a value/collection a ``CALL`` already
        populated — the review's three wipe cases: Performer P143->P286
        ``dtb_FinalProductCollection``, P291->P292 ``dtb_SammaryCollection``, and Loader
        L109->L154 ``dtb_MailItems`` (host-side, via this host body's own DATA stage;
        the inline_block target 'Populate Queue''s own copy of the same name is
        suppressed instead of re-hoisted — see ``_hoist_data_inits_for_inline_copy``).

        Task 7b0 fix pass 4 gap 7: identical rendered init lines are deduplicated
        (first occurrence kept, order preserved) — a body can otherwise carry the same
        ``SET``/``DataTable.Create()`` line twice when two DATA/COLLECTION stages
        declare the same target name with the same value (review P143/P162, P173/P183,
        Loader L117/L127).

        Args:
            stage_sources: (stage, mapping) pairs from ``_collect_hoistable_stage_sources``
                — each stage is rendered with its own paired mapping so a nested
                inline_block/fold target's data items never pick up the host's
                In_/Out_ overrides (Task 7b0 gap 6).
            process: The BPProcess (forwarded so init expressions needing CALL
                resolution render correctly).
            process_map: The process entry from page_target_map.yaml.
            param_suppress_names: Data-item names already suppressed because they are
                bound to a FUNCTION parameter — never rendered, hoisted or not (Do item 3).

        Returns:
            A 2-tuple: (hoisted_inits_text, all_suppress_names). ``all_suppress_names``
            is ``param_suppress_names`` unioned with every DATA/COLLECTION stage's
            target name found in ``stage_sources`` — pass this as the suppress set
            while rendering the body's (and any nested inline_block/fold's) normal
            flow, so every hoisted stage renders as "" in place, wherever it lives.
        """
        hoist_targets: set[str] = set()
        for stage, _mapping in stage_sources:
            name = self._data_collection_target_name(stage)
            if name is not None:
                hoist_targets.add(name.lower())

        previous = self._current_suppress_init_names
        self._current_suppress_init_names = set(param_suppress_names)
        try:
            hoisted_lines: list[str] = []
            seen_lines: set[str] = set()
            for stage, mapping in stage_sources:
                rendered = self._render_stage(stage, process, process_map, mapping)
                if rendered and rendered not in seen_lines:
                    hoisted_lines.append(rendered)
                    seen_lines.add(rendered)
        finally:
            self._current_suppress_init_names = previous

        all_suppress = set(param_suppress_names) | hoist_targets
        return "\n".join(hoisted_lines), all_suppress

    def _get_input_bound_names(self, page: Any) -> dict[str, str]:
        """Return this page's In_-bound BP data-item names, lowercase -> original case.

        Used by Do item 9 (split sub-FUNCTION input TODO, for both re-init and
        reference detection) to identify when a non-entry split sub-FUNCTION would
        silently re-initialise or read a data item that only the entry FUNCTION
        receives as an In_ parameter — the split call chain (Task 5a follow-up) does
        not yet propagate it there. Also used by Do item 8's gap 2 fix (Main-page
        hoisting must never re-initialise a flow ``@INPUT``) with the Main page's own
        START stage.

        Args:
            page: The BPPage whose START stage carries the ``stage=`` input bindings.

        Returns:
            A dict mapping each lowercase data-item name bound to an In_ parameter to
            its original-cased name (for building human-readable TODO text).
        """
        names: dict[str, str] = {}
        start_stage = next((s for s in page.stages if s.stage_type == StageType.START), None)
        if start_stage and start_stage.data_items:
            for data_item in start_stage.data_items:
                if data_item.is_input:
                    data_item_name = start_stage.inputs_stage_map.get(
                        data_item.name, data_item.name
                    )
                    names[data_item_name.lower()] = data_item_name
        return names

    def _stage_references_data_item(self, stage: BPStage, name_lower: str) -> bool:
        """Return True if a stage's BP expressions reference the named data item.

        Scans every expression-bearing field the parser captures on a stage — action/
        CALL input expressions and CALCULATION assignments (``params_map`` values,
        ``parser/process.py`` L274/L298/L369-391), DECISION/CHOICE conditions
        (``decision_expression``), ``stage=``-bound call input/output data-item names
        (``inputs_stage_map``/``outputs_stage_map`` values) and CALCULATION
        assignment *targets* (``params_map`` keys, e.g. ``FinalProduct_Collection.
        Column8`` — a stage that only writes a data item still needs it passed
        through) — for a case-insensitive, whole-token occurrence of ``name_lower``.
        BP references a data item either bracketed (``[FinalProduct_Collection]``),
        dotted (``FinalProduct_Collection.SomeColumn``) or bare; a ``\\b``-bounded
        regex match catches all three while a raw substring match would not (Task
        7b0 fix pass 5 gap 4, ``docs/reviews/7b0-2026-09-24-fixpass4.md`` gap (d)):
        ``_`` is a regex word character, so ``\\bsampleid\\b`` does not match inside
        ``old_sampleid``, and ``[``/``]``/``.`` are all non-word characters, so the
        same pattern already matches both the bracketed and dotted forms without a
        separate pattern for each.

        ``params_map`` keys/values starting with ``_`` are parser metadata (e.g.
        ``_vbo_object``/``_vbo_action``, ``parser/process.py`` L401/L403) whose
        *values* are VBO/action names, not data-item references — excluded, else a
        stage whose action name happens to contain the data-item name as a word
        (P960: ``Close SampleID & Analysis Window`` via ``_vbo_action``) is a false
        positive.

        Args:
            stage: Any BPStage.
            name_lower: The lowercase BP data-item name to look for.

        Returns:
            True if any expression field on the stage references ``name_lower`` as
            a whole token.
        """
        pattern = re.compile(rf"\b{re.escape(name_lower)}\b", re.IGNORECASE)

        candidates: list[str | None] = [stage.decision_expression]
        candidates.extend(
            value for key, value in stage.params_map.items() if not key.startswith("_")
        )
        candidates.extend(key for key in stage.params_map if not key.startswith("_"))
        candidates.extend(stage.inputs_stage_map.values())
        candidates.extend(stage.outputs_stage_map.values())
        return any(text and pattern.search(text) for text in candidates)

    def _unassigned_output_todos(
        self, actions_content: str, output_param_names: list[str]
    ) -> list[str]:
        """Build Do item 10 TODOs for declared Out_ parameters never assigned in the body.

        A body assigns an Out_ parameter one of two ways: ``SET Out_x TO ...`` (the
        both-input-and-output copy-before-exit form, reference L944:
        ``SET out_dtb_filteredTable TO In_dtb_FinalProduct``) or an action/nested CALL
        writing straight into it, ``... => Out_x`` (reference L438, L1483's ``Out_c=>
        <var>`` call form — here ``Out_x`` is the receiving *caller* variable on the
        right of ``=>``, not a callee parameter name on the left). If neither appears
        anywhere in the rendered body, the parameter is declared but silently
        unassigned.

        Task 7b0 fix pass 4 gap 6: the prior pattern, ``\\b{name}\\s*=>``, matched
        ``Out_x`` on the *left* of ``=>`` — that is a *callee's* declared parameter in
        ``CALL ... Out_x=> some_var`` (the callee's Out_x flows into ``some_var``, which
        is what gets assigned, not Out_x), not a write to this body's own Out_x. The
        fixed pattern looks to the right of ``=>`` instead.

        Args:
            actions_content: The FUNCTION body's rendered text so far.
            output_param_names: Every Out_ parameter name the page declares.

        Returns:
            One ``# TODO`` line per unassigned Out_ parameter, in declaration order.
        """
        todos: list[str] = []
        for name in output_param_names:
            pattern = rf"\bSET\s+{re.escape(name)}\s+TO\b|=>\s*{re.escape(name)}\b"
            if not re.search(pattern, actions_content):
                todos.append(f"# TODO: {name} is declared but not assigned in this body")
        return todos

    def _build_body_variable_overrides(
        self,
        page: Any,
    ) -> tuple[dict[str, str], list[tuple[str, str]], list[str]]:
        """Build per-FUNCTION body variable-name overrides for parameter-bound data items.

        Task 7b0 Do item 3: inside a parameterised FUNCTION, every reference to a data item
        bound (via the ``stage=`` attribute captured by the parser — ``inputs_stage_map``/
        ``outputs_stage_map``) to an In_/Out_ parameter must render as that parameter's name,
        not its regular txt_/dtb_ name, and the data item's own initialising SET must be
        suppressed. Reference L944 (``SET out_dtb_filteredTable TO In_dtb_FinalProduct``,
        'Enter Results in App') shows the ``SET Out_x TO In_x``-before-``END FUNCTION`` form
        this method implements for both-input-and-output items (``both_bindings``), though with
        different item names on each side, not the same name bound both ways. L395-396
        (``SET out_dtb_DataCollection TO dtb_ExcelData`` / ``SET out_txt_SampleId TO
        txt_SampleId``, 'Fetch Data from Excel file') show something different: a *local*
        variable copied to its ``out_`` name at the end of the body — they do not show a body
        reading or writing the parameter name directly, and are cited here only for the general
        "copy to Out_ before exit" shape, not as evidence of In_-name reads inside a body.

        Args:
            page: The BPPage whose Start/End stages carry the ``stage=`` bindings.

        Returns:
            A 3-tuple:
            - overrides: dict mapping lowercase BP data-item name -> PAD parameter name
              (``In_x`` for input-bound and input+output-bound items, ``Out_x`` for
              output-only items). Merge over (so it takes priority over) the page's regular
              ``variable_name_mapping`` when rendering this FUNCTION's body.
            - both_bindings: list of (in_name, out_name) pairs for data items bound to both
              an input and an output parameter — emit ``SET <out_name> TO <in_name>`` before
              ``END FUNCTION`` for each (reference L944).
            - output_param_names: every Out_ parameter name the page declares (output-only
              and input+output), in declaration order — used to flag unassigned Out_
              parameters on split pages (Do item 3, split-page sub-case).
        """
        overrides: dict[str, str] = {}
        input_names: dict[str, str] = {}  # bp_name_lower -> In_ name
        both_bindings: list[tuple[str, str]] = []
        output_param_names: list[str] = []

        start_stage = next((s for s in page.stages if s.stage_type == StageType.START), None)
        end_stage = next((s for s in page.stages if s.stage_type == StageType.END), None)

        if start_stage and start_stage.data_items:
            for data_item in start_stage.data_items:
                if data_item.is_input:
                    data_item_name = start_stage.inputs_stage_map.get(
                        data_item.name, data_item.name
                    )
                    pad_var_name = self._apply_type_prefix(data_item_name, data_item.data_type)
                    in_name = f"In_{pad_var_name}"
                    key = data_item_name.lower()
                    overrides[key] = in_name
                    input_names[key] = in_name

        if end_stage and end_stage.data_items:
            for data_item in end_stage.data_items:
                if data_item.is_output:
                    data_item_name = end_stage.outputs_stage_map.get(data_item.name, data_item.name)
                    pad_var_name = self._apply_type_prefix(data_item_name, data_item.data_type)
                    out_name = f"Out_{pad_var_name}"
                    key = data_item_name.lower()
                    output_param_names.append(out_name)
                    if key in input_names:
                        # Both input- and output-bound: the body uses the In_ name for
                        # reads and writes; overrides[key] already holds the In_ name.
                        both_bindings.append((input_names[key], out_name))
                    else:
                        overrides[key] = out_name

        return overrides, both_bindings, output_param_names

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

            # Extract parameter list for FUNCTION header (Task 7b0)
            parameters = self._extract_function_parameters(page)

            # Task 7b0 Do item 3: build the body-local override map so every reference to a
            # parameter-bound data item renders as its In_/Out_ name inside this FUNCTION's
            # body, and suppress that data item's own initialising SET (the parameter already
            # carries the value). Reference L944 (`SET out_dtb_filteredTable TO
            # In_dtb_FinalProduct`) shows the SET Out_x TO In_x-before-exit form for
            # both-bound items; L395-396 show a local copied to its out_ name at the end
            # (not a parameter-name read/write) — see _build_body_variable_overrides'
            # docstring for the full citation.
            overrides, both_bindings, output_param_names = self._build_body_variable_overrides(page)
            body_variable_name_mapping = dict(variable_name_mapping or {})
            body_variable_name_mapping.update(overrides)

            # Task 7b0 Do item 8, option A: hoist this page's own non-parameter-bound
            # DATA/COLLECTION inits to the top of the body (before rendering the flow)
            # so a caller's own re-initialisation can never wipe a value a CALL already
            # returned. An inline_block/fold target's own inits are handled separately,
            # at the start of each inlined copy — see _hoist_data_inits_for_inline_copy.
            hoistable_sources = self._collect_hoistable_stage_sources(
                page.stages, process, process_map, body_variable_name_mapping
            )
            hoisted_inits, suppress_names = self._hoist_data_inits_from_sources(
                hoistable_sources, process, process_map, set(overrides.keys())
            )

            previous_suppress = self._current_suppress_init_names
            previous_host_page = self._current_host_page
            self._current_suppress_init_names = suppress_names
            # Fix pass 5 gap 1: this page is the host for any inline_block/fold call
            # rendered inside its body — see _hoist_data_inits_for_inline_copy.
            self._current_host_page = page
            try:
                # Render all stages in the page, applying coarse BLOCK pattern (§A5, §B15)
                # where the page has Block stages with a persisted recover_stage_id (Task 4b).
                actions_content = self._render_stage_list_with_coarse_blocks(
                    page.stages, process, process_map, body_variable_name_mapping
                )

                # Task 7b0 Do item 3: a data item bound to both an input and an output uses
                # the In_ name throughout the body, then is copied to its Out_ name right
                # before END FUNCTION (reference L944).
                if both_bindings:
                    assign_lines = [
                        f"SET {out_name} TO {in_name}" for in_name, out_name in both_bindings
                    ]
                    actions_content = (
                        f"{actions_content}\n" + "\n".join(assign_lines)
                        if actions_content
                        else "\n".join(assign_lines)
                    )
            finally:
                self._current_suppress_init_names = previous_suppress
                self._current_host_page = previous_host_page

            if hoisted_inits:
                actions_content = (
                    f"{hoisted_inits}\n{actions_content}" if actions_content else hoisted_inits
                )

            # Task 7b0 Do item 10: flag any declared Out_ parameter that is never assigned
            # anywhere in the rendered body, so it is never silently dropped.
            unassigned_todos = self._unassigned_output_todos(actions_content, output_param_names)
            if unassigned_todos:
                todo_text = "\n".join(unassigned_todos)
                actions_content = (
                    f"{actions_content}\n{todo_text}" if actions_content else todo_text
                )

            epilogue = self._render_goto_epilogue(actions_content)
            if epilogue:
                actions_content = f"{actions_content}\n{epilogue}"

            # Render the FUNCTION wrapper (always GLOBAL — template-fixed, Task 7b0)
            subflow_template = self.env.get_template("subflow.robin.j2")
            return subflow_template.render(
                subflow_name=target_name,
                actions=actions_content,
                construct_type="function",
                parameters=parameters,  # Task 7b0
            )

        except Exception as e:
            raise GenerationError(f"Failed to render page '{page.name}' as function: {e}") from e

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

        # Task 7b0 Do item 3 (split pages, user decision 2026-09-24): only the entry
        # FUNCTION (targets[0]) carries the page's In_/Out_ parameter list; the other
        # sub-FUNCTIONs stay bare `FUNCTION '<name>' GLOBAL`. Because the page's End
        # stage lands in the last sub-FUNCTION and the split call chain (Task 5a) doesn't
        # exist yet, the entry FUNCTION's Out_ parameter(s) cannot be assigned here — a
        # TODO naming them is emitted instead of a silent unassigned output.
        entry_overrides, _both_bindings, entry_output_param_names = (
            self._build_body_variable_overrides(page)
        )
        entry_parameters = self._extract_function_parameters(page)
        # Task 7b0 Do item 9: data items bound to the entry FUNCTION's In_ parameters —
        # used to detect a non-entry sub-FUNCTION silently re-initialising one of them.
        entry_input_names = self._get_input_bound_names(page)

        # Render each target FUNCTION
        function_blocks: list[str] = []
        for target_idx, target_name in enumerate(targets):
            start_idx, end_idx = boundaries[target_idx]
            stages_for_target = page.stages[start_idx:end_idx]
            is_entry = target_idx == 0

            leak_todos: list[str] = []
            if is_entry:
                body_variable_name_mapping = dict(variable_name_mapping or {})
                body_variable_name_mapping.update(entry_overrides)
                param_suppress = set(entry_overrides.keys())
            else:
                body_variable_name_mapping = variable_name_mapping
                # Task 7b0 Do item 9: this non-entry sub-FUNCTION only receives whatever
                # the (not-yet-existing, Task 5a follow-up) split call chain passes it —
                # not the entry FUNCTION's In_ parameters. A DATA/COLLECTION stage here
                # whose target is one of those In_-bound data items would otherwise
                # silently re-initialise it to the BP default instead of the caller's
                # value. Suppress it and flag a TODO naming the missing In_ parameter,
                # the input-side twin of the entry FUNCTION's Out_ TODO above.
                leaked: dict[str, str] = {}
                for stage in stages_for_target:
                    tname = self._data_collection_target_name(stage)
                    if tname and tname.lower() in entry_input_names:
                        leaked[tname.lower()] = tname
                param_suppress = set(leaked.keys())

                # Fix pass 4 gap 4: item 9 says "reference or re-initialise" — a
                # non-entry sub-FUNCTION stage that only *reads* an entry In_-bound data
                # item (no re-init) still needs the parameter, and the split call chain
                # doesn't pass it either. Detect via expression scanning
                # (`_stage_references_data_item`) since these stages are not
                # DATA/COLLECTION targets and the re-init check above never sees them
                # (review 2026-09-24-fixpass3 gap 4: 13 BP stages across all 5 non-entry
                # Result Entry sub-FUNCTIONs). Read-only references are not suppressed
                # (there is nothing to wipe) — only flagged.
                referenced: dict[str, str] = {}
                for stage in stages_for_target:
                    for lower_name, orig_name in entry_input_names.items():
                        if lower_name in leaked:
                            continue
                        if self._stage_references_data_item(stage, lower_name):
                            referenced.setdefault(lower_name, orig_name)

                for lower_name, orig_name in leaked.items():
                    in_param = entry_overrides.get(lower_name, f"In_{orig_name}")
                    leak_todos.append(
                        f"# TODO: split page — sub-function target '{target_name}' would "
                        f"re-initialise '{orig_name}', bound to entry FUNCTION parameter "
                        f"{in_param}; the split call chain (Task 5a follow-up) does not "
                        "yet pass it to this sub-function"
                    )
                for lower_name, orig_name in referenced.items():
                    in_param = entry_overrides.get(lower_name, f"In_{orig_name}")
                    leak_todos.append(
                        f"# TODO: split page — sub-function target '{target_name}' "
                        f"references '{orig_name}', bound to entry FUNCTION parameter "
                        f"{in_param}; the split call chain (Task 5a follow-up) does not "
                        "yet pass it to this sub-function"
                    )

            # Task 7b0 Do item 8, option A: hoist this sub-FUNCTION's own
            # non-parameter-bound DATA/COLLECTION inits to the top of its body
            # (per-sub-FUNCTION, as for a regular FUNCTION body). An inline_block/fold
            # target's own inits render at its inlined copy's own start instead.
            hoistable_sources = self._collect_hoistable_stage_sources(
                stages_for_target, process, process_map, body_variable_name_mapping
            )
            hoisted_inits, suppress_names = self._hoist_data_inits_from_sources(
                hoistable_sources,
                process,
                process_map,
                param_suppress,
            )

            previous_suppress = self._current_suppress_init_names
            previous_host_page = self._current_host_page
            self._current_suppress_init_names = suppress_names
            # Fix pass 5 gap 1: the host for any inline_block/fold call rendered
            # inside a sub-FUNCTION is the whole split page (its full declarations,
            # not just this sub-FUNCTION's stage slice) — Result Entry's sub-
            # FUNCTIONs inlining Sample Manager - Explorer (gap 2, num_RetryCount).
            self._current_host_page = page
            try:
                # Render stages for this target
                action_lines: list[str] = []
                for stage in stages_for_target:
                    rendered = self._render_stage(
                        stage, process, process_map, body_variable_name_mapping
                    )
                    if rendered:
                        action_lines.append(rendered)

                actions_content = "\n".join(action_lines)

                if is_entry and entry_output_param_names:
                    todo = (
                        "# TODO: split page — Out_ parameter(s) "
                        + ", ".join(entry_output_param_names)
                        + f" are not yet assigned; the page's End stage lands in the last "
                        f"split target ('{targets[-1]}'), and the split call chain "
                        "(Task 5a follow-up) does not yet exist to return the value here"
                    )
                    actions_content = f"{actions_content}\n{todo}" if actions_content else todo
            finally:
                self._current_suppress_init_names = previous_suppress
                self._current_host_page = previous_host_page

            if hoisted_inits:
                actions_content = (
                    f"{hoisted_inits}\n{actions_content}" if actions_content else hoisted_inits
                )
            if leak_todos:
                leak_text = "\n".join(leak_todos)
                actions_content = (
                    f"{leak_text}\n{actions_content}" if actions_content else leak_text
                )

            epilogue = self._render_goto_epilogue(actions_content)
            if epilogue:
                actions_content = f"{actions_content}\n{epilogue}"

            # Render the FUNCTION wrapper (always GLOBAL — template-fixed, Task 7b0)
            parameters = entry_parameters if is_entry else ""
            subflow_template = self.env.get_template("subflow.robin.j2")
            function = subflow_template.render(
                subflow_name=target_name,
                actions=actions_content,
                construct_type="function",
                parameters=parameters,  # Task 7b0
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
        # Task 7b: dedupe repeated identical Trim(...)/Lower(...) calls within the
        # same expression (e.g. the Mark Item As Exception page's "Retry Exception?"
        # `Lower([Exception Type])="system exception" OR Lower([Exception Type])=
        # "internal"` — the same Lower(...) call appears twice) so they reuse one
        # temp var/action instead of emitting a second, unused SET — str.replace on
        # the whole literal substring already collapses both occurrences to the same
        # temp var name at the call site, so a second pass previously only added
        # dead output, never a second usable reference.
        trim_pattern = r"Trim\s*\(\s*([^)]+)\s*\)"
        seen_trim: dict[str, str] = {}
        for match in re.finditer(trim_pattern, result):
            inner_expr = match.group(1).strip()
            if inner_expr in seen_trim:
                result = result.replace(match.group(0), seen_trim[inner_expr])
                continue
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
            seen_trim[inner_expr] = temp_var
            temp_var_counter += 1

        lower_pattern = r"Lower\s*\(\s*([^)]+)\s*\)"
        seen_lower: dict[str, str] = {}
        for match in re.finditer(lower_pattern, result):
            inner_expr = match.group(1).strip()
            if inner_expr in seen_lower:
                result = result.replace(match.group(0), seen_lower[inner_expr])
                continue
            translated_inner, inner_actions = self._translate_bp_expression(
                inner_expr, variable_name_mapping
            )
            separate_actions.extend(inner_actions)
            # Create a temporary variable for the Lower result using deterministic counter
            temp_var = f"txt_lowered_{temp_var_counter}"
            action = f"Text.ChangeCase '{translated_inner}' 'To lowercase' => {temp_var}"
            separate_actions.append(action)
            result = result.replace(match.group(0), temp_var)
            seen_lower[inner_expr] = temp_var
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

    def _lookup_method_actions_template(
        self, stage: BPStage, method_name_override: str | None = None
    ) -> str | None:
        """Look up a method_actions template for a VBO call stage.

        Used by Task 7a to wire WorkQueues and other VBO method_actions into generation.
        Tries to find an exact method match in the VBO catalogue's method_actions field.

        Args:
            stage: A BPStage with _vbo_object and _vbo_action in params_map.
            method_name_override: Task 7b — look up this catalogue key instead of the
                stage's own _vbo_action (used to select a "Mark Exception :: <Variant>"
                row per mapping/vbo_catalogue.yaml L452-454 from real BP branch
                context, since the stage's own _vbo_action is always the bare
                "Mark Exception" regardless of which exception-type branch it sits
                in). Falls back to the stage's own _vbo_action when not given.

        Returns:
            The PAD action template string if found in method_actions, None otherwise.
        """
        vbo_name = stage.params_map.get("_vbo_object")
        method_name = method_name_override or stage.params_map.get("_vbo_action")

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
    ) -> tuple[str, bool, str, str]:
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
            A tuple of (substituted_string, was_bound_from_catalogue, dependency_comment, unmatched_todo_marker).
            was_bound_from_catalogue: True if the queue binding came from queue_bindings catalogue.
            dependency_comment: Citation/notes about where the variable must be assigned.
            unmatched_todo_marker: TODO comment if queue_name was unmatched, empty string otherwise.

        Raises:
            GenerationError: If substitution fails critically.
        """
        result = template
        was_bound_from_catalogue = False
        dependency_comment = ""
        unmatched_todo_marker = ""

        # Queue Name parameter: <id>
        if "<id>" in result:
            queue_name = stage.params_map.get("Queue Name", "")
            id_value = ""

            # Task 7a (b): Check queue_bindings catalogue for expression-to-variable mapping
            matched_from_catalogue = False
            if queue_name:
                for expr_pattern, binding_info in self.queue_bindings.items():
                    if expr_pattern in queue_name:
                        id_value = binding_info["pad_variable"]
                        citation = binding_info["citation"]
                        notes = binding_info["notes"]
                        was_bound_from_catalogue = True
                        matched_from_catalogue = True
                        # Task 7a: VERIFY text from binding's fields (not hardcoded in Python)
                        dependency_comment = (
                            f"Get Next Item queue ID '{id_value}' — {notes}. {citation}"
                        )
                        break

            # Fallback: if not bound from catalogue, translate via expression machinery
            if not matched_from_catalogue and queue_name:
                # Task 7a Gap 2: if no catalogue binding matched, emit TODO before rendering
                translated, _ = self._translate_bp_expression(queue_name, variable_name_mapping)
                if translated:
                    id_value = translated
                    # Still emit TODO because we had to fall back to expression translation
                    unmatched_todo_marker = (
                        f"# TODO: WorkQueues.{method_name} queue expression '{queue_name}' "
                        f"has no catalogue queue_binding — needs manual completion"
                    )
                else:
                    # Expression translation also failed
                    id_value = "%QueueId%"
                    unmatched_todo_marker = (
                        f"# TODO: WorkQueues.{method_name} queue expression '{queue_name}' "
                        f"has no catalogue queue_binding — needs manual completion"
                    )
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

        return result, was_bound_from_catalogue, dependency_comment, unmatched_todo_marker

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
            # Task 7b: use the stage's real BP message expression (annotator.py's
            # _annotate_exception carries it as params_map["detail_expr"], e.g. the
            # Mark Item As Exception page's TERMINATE stages: "[Consecutive Exception
            # Limit] & \" consecutive incidents of \" & [Exception Type] & \": \" &
            # [Exception Detail]") instead of the bare hardcoded "txt_ExceptionMessage"
            # placeholder — §A5 raise template: "CustomErrorMessage: <message expr>".
            detail_expr = annotation.params_map.get("detail_expr", "")
            translated_detail, detail_actions = self._translate_bp_expression(
                detail_expr, variable_name_mapping
            )
            for action in detail_actions:
                lines.append(action)
            message_expr = translated_detail if translated_detail else "txt_ExceptionMessage"
            rendered = throw_template.render(
                custom=target_type == "ThrowCustomError",
                error_code=annotation.params_map.get("exception_type", "%txt_ExceptionType%"),
                message_var=message_expr,
            )
            lines.append(rendered)

        elif target_type in ("SetVariable", "SET <var> TO <expr>"):
            # SetVariable handling differs by stage type:
            # - DATA: variable declaration (target_type="SetVariable" from _annotate_data)
            # - CALCULATION: assignment stage (stage_type=CALCULATION, params_map={target: expr})
            #   Task 7b: CALCULATION/MultipleCalculation stages are annotated via
            #   _annotate_from_rules, which sets target_type to the literal
            #   mapping/stage_rules.yaml pa_target_action string "SET <var> TO <expr>"
            #   (L77, L243 — §B12 CALCULATION row), not the DATA-only "SetVariable"
            #   sentinel — this branch previously never matched real CALCULATION
            #   stages (e.g. the Mark Item As Exception page's "Count" and "Reset
            #   Consecutive Exception Indicators"), which fell through to the generic
            #   comment branch below instead of emitting a SET line.
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

            # Task 7b0 Do item 3: suppress the initialising SET for a data item bound to a
            # FUNCTION parameter — the parameter already carries the caller-supplied value
            # (input) or will be assigned via `SET Out_<x> TO In_<x>`/its own body writes
            # before END FUNCTION (output); re-emitting the BP declaration's SET here would
            # overwrite the bound value with the BP-authored default/`DataTable.Create()`.
            # Only applies to DATA/COLLECTION declarations, never CALCULATION assignments.
            if (
                stage.stage_type
                in (
                    StageType.DATA,
                    StageType.COLLECTION,
                )
                and target_var_name.lower() in self._current_suppress_init_names
            ):
                return ""

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
            # Task 7b0 Do item 3: same suppression as the SetVariable/COLLECTION branch above.
            if target_var_name.lower() in self._current_suppress_init_names:
                return ""
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

        elif target_type in ("Condition", "IF <expr> THEN <true-branch> ELSE <false-branch> END"):
            # DECISION stage: translate the BP condition expression to PAD syntax.
            # Only reached here for a DECISION with no real branch targets to nest
            # (rendered as an empty IF/ELSE stub) — a DECISION with both
            # ontrue_target/onfalse_target populated is handled by
            # _render_decision_branch instead (real nested branch bodies, Task 7b).
            cond_template = self.env.get_template("actions/condition.robin.j2")

            # Get the BP condition expression. Task 7b: DECISION stages are annotated
            # via _annotate_from_rules with target_type set to the literal
            # mapping/stage_rules.yaml pa_target_action string "IF <expr> THEN
            # <true-branch> ELSE <false-branch> END" (L66, §B12 DECISION row) and an
            # always-empty annotation.params_map — the real condition text lives on
            # stage.decision_expression (ast/models.py BPStage field), which this
            # branch never read before, so bp_condition always fell back to the
            # literal placeholder "[SomeCondition]".
            bp_condition = annotation.params_map.get("condition") or stage.decision_expression or ""

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
            # Task 7a: consume the cited method_actions template. Task 7b: "Mark
            # Exception" status-variant selection is resolved here from
            # self._current_exception_branch_context — set by _render_decision_branch
            # while walking a Decision's true/false branches (§A7; the Task 7a
            # hand-off note this replaces used to say "deferred to Task 7b").
            method_name = stage.params_map.get("_vbo_action")

            if band != ConfidenceBand.MANUAL:
                # Task 7b hard constraint: select the catalogue variant from real BP
                # branch context (mapping/vbo_catalogue.yaml L452-454), never from the
                # stage's own name or a Tag value. "system" -> GenericException row
                # (BP's plain-System-Exception branch, §A7); "business"/undetermined
                # -> the default "Mark Exception" row (BusinessException, the BP
                # default per the task's binding decision). "Mark Exception ::
                # ITException" is left unused — no BP branch in this page maps to it.
                lookup_method_name = method_name
                variant_selected_from_context = False
                if method_name == "Mark Exception":
                    if self._current_exception_branch_context == "system":
                        lookup_method_name = "Mark Exception :: GenericException"
                        variant_selected_from_context = True
                    elif self._current_exception_branch_context == "business":
                        lookup_method_name = "Mark Exception"
                        variant_selected_from_context = True

                method_template = self._lookup_method_actions_template(
                    stage, method_name_override=lookup_method_name
                )
                if method_template:
                    substituted, was_bound_from_catalogue, dependency_comment, unmatched_todo = (
                        self._substitute_workqueues_placeholders(
                            method_template, stage, method_name, variable_name_mapping
                        )
                    )
                    # Task 7a Gap 2: emit TODO if queue expression is unmatched
                    if unmatched_todo:
                        lines.append(unmatched_todo)

                    # Task 7a (a): Add VERIFY comment before Get Next Item if binding came from catalogue
                    if method_name == "Get Next Item" and was_bound_from_catalogue:
                        # Build VERIFY text from the binding's citation and notes
                        lines.append(f"# VERIFY: {dependency_comment}")
                    if method_name == "Mark Exception" and not variant_selected_from_context:
                        # Context not determinable (stage reached outside a
                        # recognised Decision branch) — keep the VERIFY marker per
                        # Task 7b's "keep it wherever context isn't determinable".
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

        # Task 7b: a stage list with no coarse-BLOCK groups but with a real
        # branching DECISION (both ontrue_target/onfalse_target populated) is
        # rendered via a control-flow graph walk instead of the positional loop
        # below — see _render_decision_graph's docstring for why raw BPPage.stages
        # declaration order cannot be trusted as execution order for such pages.
        # Scoped to "no coarse-BLOCK groups" so Task 5c's already-reviewed
        # BLOCK/RECOVER handling (the positional loop below) is never touched by
        # this generic addition.
        if not coarse_block_map and any(
            s.stage_type == StageType.DECISION and s.ontrue_target and s.onfalse_target
            for s in stages
        ):
            return self._render_decision_graph(
                stages, process, process_map, variable_name_mapping, render_stage_fn
            )

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

    def _render_decision_graph(
        self,
        stages: list[BPStage],
        process: BPProcess | None,
        process_map: dict[str, Any] | None,
        variable_name_mapping: dict[str, str] | None,
        render_stage_fn: Any,
    ) -> str:
        """Render a stage list by walking its control-flow graph, not declaration order.

        ``BPPage.stages`` preserves raw BP XML declaration order — ``ast/builder.py``'s
        ``_build_page`` applies no reordering. For a page with real branching this is
        frequently *not* execution order: on the "Mark Item As Exception" page (Task
        7b, architecture doc §A7), the Start stage's actual successor ("System
        Unavailable?") is declared near the end of the page's stage list, while an
        unrelated downstream decision ("Retry Exception?") is declared 2nd — confirmed
        directly via ``outputs/generated/PID_0171/ast.json``. Rendering positionally
        (the loop above, still used unchanged for every stage list without this
        problem) would emit "Retry Exception?"'s `IF` before the `IF` that actually
        gates whether that code path is ever reached.

        This walks forward from the page's ``START`` stage via
        ``onsuccess_target``/``ontrue_target``/``onfalse_target`` edges, so the emitted
        statement order always matches BP's real control flow, for any page (not
        specific to Mark Item As Exception) with a genuine branching DECISION.

        Args:
            stages: The stage list to render (the full page — this is only invoked
                when the whole list has no coarse-BLOCK groups, see the call site).
            process: The BPProcess (forwarded to per-stage renderers).
            process_map: Process map from page_target_map.yaml.
            variable_name_mapping: Optional BP-name→PAD-name dict from Task 5b.
            render_stage_fn: Callable(stage, process, process_map, variable_name_mapping) → str.

        Returns:
            All rendered lines joined by newlines.
        """
        stages_by_id = {s.stage_id: s for s in stages}
        start = next(
            (s for s in stages if s.stage_type == StageType.START),
            stages[0] if stages else None,
        )

        visited: set[str] = set()
        lines: list[str] = []
        if start is not None:
            lines.extend(
                self._render_chain(
                    start.stage_id,
                    stages_by_id,
                    visited,
                    process,
                    process_map,
                    variable_name_mapping,
                    render_stage_fn,
                )
            )

        # Never silently drop a stage (CLAUDE.md): anything the graph walk didn't
        # reach (orphaned stages, or a shape this generic walk doesn't resolve) is
        # still rendered, appended in original declaration order.
        for stage in stages:
            if stage.stage_id not in visited:
                visited.add(stage.stage_id)
                rendered = render_stage_fn(stage, process, process_map, variable_name_mapping)
                if rendered:
                    lines.append(rendered)

        return "\n".join(line for line in lines if line)

    def _render_chain(
        self,
        stage_id: str | None,
        stages_by_id: dict[str, BPStage],
        visited: set[str],
        process: BPProcess | None,
        process_map: dict[str, Any] | None,
        variable_name_mapping: dict[str, str] | None,
        render_stage_fn: Any,
    ) -> list[str]:
        """Render a straight-line control-flow chain starting at ``stage_id``.

        Follows ``onsuccess_target`` stage-to-stage. A ``DECISION`` stage with both
        branch targets populated is rendered as a real nested ``IF``/``ELSE``/``END``
        via ``_render_decision_branch`` (§B12 DECISION row: "IF <translated expr> THEN
        <true-branch> ELSE <false-branch> END"; nesting syntax confirmed at
        ``docs/pad-reference/DF_PID_171_US_LIMS_Prelude_Main.robin.txt`` L1271-1310).
        A ``MultipleCalculation`` fan-out group (``ast/builder.py``'s
        ``_normalise_stages``: one BP stage becomes N ``CALCULATION`` sub-stages with
        ids ``<base>__calc_1..N``, each carrying an *identical* ``onsuccess_target`` —
        confirmed via ``outputs/generated/PID_0171/ast.json`` — since they are not
        chained to each other) is rendered as one contiguous group, in id order,
        before following their shared successor.

        The walk stops at a stage with no further target (an ``EXCEPTION`` throw or an
        ``END`` stage, both terminal per §B12), or at a stage already in ``visited``
        (a join point already rendered by a sibling branch — see
        ``_render_decision_branch``).

        Args:
            stage_id: The stage to start at (``None`` renders nothing).
            stages_by_id: id → BPStage map for the whole stage list being rendered.
            visited: Mutable set of already-rendered stage ids, shared across the
                whole page render so a join point is emitted exactly once.
            process: The BPProcess (forwarded to per-stage renderers).
            process_map: Process map from page_target_map.yaml.
            variable_name_mapping: Optional BP-name→PAD-name dict from Task 5b.
            render_stage_fn: Callable(stage, process, process_map, variable_name_mapping) → str.

        Returns:
            Rendered lines for this chain, in order.
        """
        lines: list[str] = []

        while stage_id is not None and stage_id in stages_by_id and stage_id not in visited:
            stage = stages_by_id[stage_id]

            base, sep, _suffix = stage.stage_id.partition("__calc_")
            if sep:
                group_prefix = f"{base}__calc_"
                group_ids = sorted(sid for sid in stages_by_id if sid.startswith(group_prefix))
                next_id: str | None = None
                for gid in group_ids:
                    if gid in visited:
                        continue
                    visited.add(gid)
                    gstage = stages_by_id[gid]
                    rendered = render_stage_fn(gstage, process, process_map, variable_name_mapping)
                    if rendered:
                        lines.append(rendered)
                    next_id = gstage.onsuccess_target
                stage_id = next_id
                continue

            visited.add(stage.stage_id)

            if (
                stage.stage_type == StageType.DECISION
                and stage.ontrue_target
                and stage.onfalse_target
            ):
                rendered = self._render_decision_branch(
                    stage,
                    stages_by_id,
                    visited,
                    process,
                    process_map,
                    variable_name_mapping,
                    render_stage_fn,
                )
                if rendered:
                    lines.append(rendered)
                # DECISION stages have no onsuccess_target in practice (both arms
                # already fully render their own continuation via the recursive
                # branch walk) — following it defensively costs nothing if a future
                # AST does set one.
                stage_id = stage.onsuccess_target
                continue

            rendered = render_stage_fn(stage, process, process_map, variable_name_mapping)
            if rendered:
                lines.append(rendered)
            stage_id = stage.onsuccess_target

        return lines

    def _render_decision_branch(
        self,
        stage: BPStage,
        stages_by_id: dict[str, BPStage],
        visited: set[str],
        process: BPProcess | None,
        process_map: dict[str, Any] | None,
        variable_name_mapping: dict[str, str] | None,
        render_stage_fn: Any,
    ) -> str:
        """Render one DECISION stage as a real nested ``IF``/``ELSE``/``END``.

        Built directly from already-rendered fragments (each produced by its own
        template via ``render_stage_fn``/``_render_chain``), joined with literal
        ``IF``/``ELSE``/``END`` marker lines — the same style Task 5c's coarse-BLOCK
        post-block gating IF already uses in this file (e.g. the
        ``f"IF {COARSE_BLOCK_ERROR_FLAG} = True THEN"`` lines above), not raw
        string-built PAD *action* syntax. condition.robin.j2 is not used here because
        it has no way to receive nested branch content (out of this task's file scope
        — ``templates/`` is not in Task 7b's Files in scope).

        The true branch is walked first; the false branch's walk then stops as soon
        as it reaches any stage the true branch already rendered — i.e. their first
        common (join) stage — so a join point (e.g. the Mark Item As Exception page's
        shared ``End2``) is emitted exactly once, nested wherever it was first
        reached, never duplicated.

        Task 7b status-variant selection: while walking each branch, if this
        DECISION's own ``decision_expression`` recognisably tests the BP
        exception-type vocabulary (CLAUDE.md's canonical exception-type strings) for
        "system exception" — the Mark Item As Exception page's "Retry Exception?"
        stage (`Lower([Exception Type])="system exception" OR
        Lower([Exception Type])="internal"`) — the true branch is tagged
        ``self._current_exception_branch_context = "system"`` and the false branch
        (the binary complement in this page's 3-way BE/SUE/SE dispatch, §A7) is
        tagged ``"business"``, consulted by ``_render_stage``'s WorkQueues branch to
        pick the "Mark Exception" catalogue variant. This is derived purely from the
        governing Decision's own condition text and branch position — never from a
        stage's own name or a Tag value (task hard constraint). A DECISION whose
        expression doesn't recognisably match either keyword inherits the enclosing
        context unchanged (usually ``None``, keeping the VERIFY marker).

        Args:
            stage: The DECISION stage (``ontrue_target``/``onfalse_target`` both set).
            stages_by_id: id → BPStage map for the whole stage list being rendered.
            visited: Mutable set of already-rendered stage ids (shared, see
                ``_render_chain``).
            process: The BPProcess (forwarded to per-stage renderers).
            process_map: Process map from page_target_map.yaml.
            variable_name_mapping: Optional BP-name→PAD-name dict from Task 5b.
            render_stage_fn: Callable(stage, process, process_map, variable_name_mapping) → str.

        Returns:
            The rendered ``IF``/``ELSE``/``END`` block as one string.
        """
        bp_condition = stage.decision_expression or ""
        translated_cond, cond_actions = self._translate_bp_expression(
            bp_condition, variable_name_mapping
        )
        condition_text = translated_cond if translated_cond else "%SomeVar% = True"

        expr_lower = bp_condition.lower()
        true_context = self._current_exception_branch_context
        false_context = self._current_exception_branch_context
        if "system exception" in expr_lower:
            true_context = "system"
            false_context = "business"

        previous_context = self._current_exception_branch_context
        try:
            self._current_exception_branch_context = true_context
            true_lines = self._render_chain(
                stage.ontrue_target,
                stages_by_id,
                visited,
                process,
                process_map,
                variable_name_mapping,
                render_stage_fn,
            )
            self._current_exception_branch_context = false_context
            false_lines = self._render_chain(
                stage.onfalse_target,
                stages_by_id,
                visited,
                process,
                process_map,
                variable_name_mapping,
                render_stage_fn,
            )
        finally:
            self._current_exception_branch_context = previous_context

        out: list[str] = list(cond_actions)
        out.append(f"IF {condition_text} THEN")
        for block in true_lines:
            out.extend(f"    {ln}" for ln in block.split("\n"))
        out.append("ELSE")
        for block in false_lines:
            out.extend(f"    {ln}" for ln in block.split("\n"))
        out.append("END")
        return "\n".join(out)

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
        # Per Task 7b0: every FUNCTION is GLOBAL.
        return template.render(
            subflow_name="Get Error",
            actions=stub_body,
            construct_type="function",
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
