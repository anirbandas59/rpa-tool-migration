# Review: Task 7c — 2026-09-25 (post-merge)

This is the third review of Task 7c. The earlier ones are `docs/reviews/7c-2026-09-24.md` (78%) and `docs/reviews/7c-2026-09-25-fixpass.md` (97%, pass).

**What changed since the fix-pass review:** `feature/bp-to-pad-pipeline` (Task 7b3 and the 7b fix pass) was merged into the 7c branch at merge commit `cd8d1eb`. The 7c changes alone (`git diff feature/bp-to-pad-pipeline...HEAD`) are the same as in the original PR: `pad.py` +114/-56, the template 11 lines, and `test_pad.py` +282. This review focuses on whether the merge broke how 7c works with the 7b3 and 7b code. It also re-checks the open gaps from the fix-pass review.

**Overall: 98%**

| Dimension | Score | Evidence |
|---|---|---|
| Structural | N/A | Not in this task's scope (header only). |
| FUNCTION functional fidelity | N/A | Not in this task's scope. 7c changes no `FUNCTION` body logic. |
| VBO/action fidelity | N/A | Not in this task's scope. |
| Naming convention | 97% | **Done-condition:** I regenerated `samples/blueprism/PID_0171.bprelease` into the scratchpad. Loader and Performer each have exactly 1 `@INPUT`. `cmp` shows each line is byte-identical to L8 of `DF_PID_171_US_Loader.robin.txt` and of `DF_PID_171_US_LIMS_Prelude_Main.robin.txt`. The header TODO names the BP input and the PAD variable (`'flg_SendDatatoDataGateways' (Bool) → PAD variable flg_SendDatatoDataGateways`). The citations are correct: `ConvertJsonToCustomObject Json: In_txt_Config` is at Loader L24 and Main L35. **Fix-pass gap 1 is closed:** I re-ran mutants M6 (helper ignores `variable_name_mapping`) and M7 (shipped path passes `{}`) on a scratch copy of HEAD. Both are now killed, by `test_7c_consolidated_flow_todo_names_bound_pad_variable_not_parameter`. **Deductions (minor):** (a) The legacy `generate_page` still passes `{}`, so its TODO names always use the §A4 type-prefix fallback. It is not the shipped path. (b) The docstring of `test_7c_main_start_input_produces_todo_comment` still says "after @INPUT/@OUTPUT lines". |
| Error-handling/stop/consecutive-exception | N/A | Not in this task's scope. |
| Well-formedness | 100% | I ran every check myself on HEAD `cd8d1eb`. `tests/generator/test_pad.py`: 140 passed, including all 7 `test_7c_*`. `tests/e2e`: 17/17 passed; the fixture regenerates from the sample. `ruff check src/ tests/` is clean, and `ruff format --check` reports 58 files already formatted. Full suite (`--no-cov`): 877 passed, 10 failed. All 10 failures are in modules 7c doesn't touch: 8 `tests/engine/test_flag_index.py::test_real_*` and 2 `tests/mapper/test_vbo_router.py::TestIntegration`. The coordinator's run had 5 more (CLI typer and scaffold failures, `test_inspect_command_on_real_sample`), but they don't reproduce in my environment. Neither run has a failure in `generator/` or `e2e/`. |

## Merge-interaction checks (requested)
- **`variable_name_mapping` defined before every use in `_generate_consolidated_flow`:** Yes. It is built once, at L392, straight after the early-return guard. It is first used at L396 (header inputs). Later uses are: the 7b3 `_collect_role_once_only_sources` call, `_render_main_page_for_role`, and `_render_page_in_consolidated_flow`. The base's later duplicate build (base L462) is gone, and no second assignment remains in the function. `_build_variable_name_mapping` is pure: it only calls `_apply_type_prefix` and reads no per-role state such as `_current_role_once_only_names` or `_current_page_name_map`. So building it earlier does not change its result.
- **`_get_input_bound_names` / `main_input_bound` hoisting exclusion:** Intact at L658-663, and only the comment wording changed. I mutated the exclusion to `set()`, which killed `test_7b0_main_hoisting_excludes_flow_input_bound_names`, so the guard is still tested after the merge. In the regenerated output, `flg_SendDatatoDataGateways` appears only on the header TODO line (L14) of both files. Neither the Main hoist nor the 7b3 once-only prefix re-initialises it, so the TODO's statement that it is "neither flow inputs nor initialised" is still accurate.
- **Render order:** The three-dot diff does not touch the Main-render or FUNCTION-loop ordering. Both the base and HEAD append the Main body, with the 7b3 once-only prefix, before the FUNCTION blocks. The coordinator described this as "Main-page render relocated to after the FUNCTION blocks", but the code doesn't show that. The inaccuracy is in the summary only; the code has no regression.
- **Residual edge case (7b3-owned, not a 7c regression):** `_collect_role_once_only_sources` excludes a sub-page's own In_/Out_ overrides, but it does not exclude Main's START-bound names. A sub-page that declared a non-`<alwaysinit/>` data item with the same name as a Main START input would be hoisted once to the top of Main and would clobber the input. PID_171 doesn't hit this (verified by grep), and no test covers it.

## Most significant gaps
1. **Open design follow-up, outside 7c's scope, still unscheduled.** No task in `docs/pad-generation-task-prompts.md` generates `Variables.ConvertJsonToCustomObject Json: In_txt_Config CustomObject=> obj_Config` (reference Loader L24 / Main L35). As a result, Main START-bound variables such as `flg_SendDatatoDataGateways` are declared nowhere and never initialised. The header TODO documents this honestly, but the coordinator needs to add a task.
2. **@OUTPUT ordering constraint.** The TODO block sits directly after `@INPUT`, but in the reference, `@OUTPUT` follows `@INPUT` immediately (Loader L9-10). A future @OUTPUT task must render its lines above the TODO block, or comments will end up inside the directive block. This should be written into that task's prompt.
3. **Legacy `generate_page` naming uses only the fallback,** because it passes an empty mapping. This is low impact because the path isn't shipped.
4. **Cosmetic.**
   - The stale "after @INPUT/@OUTPUT lines" test docstring.
   - The comment "Flow header (... / @INPUT / @OUTPUT)" and the `outputs=[]` kwargs are now unused by the template. They are harmless.
   - There is the 7b3 once-only / Main-START-name edge case noted above; if it is fixed, the fix belongs to 7b3.

## Verdict
Pass. The merge introduced no regression. The done-condition still holds on the merged HEAD: exactly 1 `@INPUT In_txt_Config` per file, byte-identical to reference L8. The 7b0/7b3 hoisting exclusion is intact and tested. `variable_name_mapping` is defined once, before every use. The fix pass's surviving mutants M6/M7 are now killed. Gap 1 needs a new task from the coordinator; it does not block 7c.
