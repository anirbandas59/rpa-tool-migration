# Task 7a Gap Analysis and Remediation Plan

## Top-Level Overview

Task 7a has correctly populated the WorkQueues catalogue templates and removed literal TODO stubs for the four documented actions. The latest review still rejects the implementation because two generated behaviors are not semantically reliable: `Get Next Item` receives an unsupported queue expression, and `Mark Exception` attempts an unsupported `Tag`-based status dispatch. The tests also accept these defects.

This plan keeps Task 7a strictly scoped. It preserves the four cited WorkQueues templates, preserves `Tag Item` and `Defer` as TODOs, corrects parameter binding using existing project conventions and cited PAD syntax, and explicitly defers exception-type-specific status selection to Task 7b. No implementation files are changed by this plan.

## Acceptance Baseline

- Task 7a scope is defined in [`pad-generation-task-prompts.md`](pad-generation-task-prompts.md:1138): `mapping/vbo_catalogue.yaml`, the WorkQueues dispatch branch in `src/flowsmith/generator/pad.py`, `tests/generator/test_pad.py`, and `tests/mapper/test_vbo_router.py`.
- The required catalogue actions are `Get Next Item`, `Mark Completed`, `Mark Exception`, and `Update Status` ([`pad-generation-task-prompts.md`](pad-generation-task-prompts.md:1150)).
- `Tag Item` and `Defer` must remain TODOs because the reference table says STOP and provides no confirmed PAD call ([`vbo-action-mapping.md`](pad-reference/vbo-action-mapping.md:32)).
- `GLOBAL.` qualification and consecutive-exception dispatch belong to Task 7b ([`pad-generation-task-prompts.md`](pad-generation-task-prompts.md:1164)).
- The source report shows `Mark Exception` has no `Tag` input; `Tag` is present on separate `Tag Item` stages ([`pid-171-us-process-lims-prelude.md`](../outputs/report/PID_0171_html_report_20260904/data/pid-171-us-process-lims-prelude.md:978)).

## Confirmed Gaps

### Gap 1 — Unsupported `Get Next Item` queue expression

The generated action currently uses `dtb_ConfigFileData.Queue Name`. The source expression is `[ConfigFileData.Queue Name]` ([`pid-171-us-process-lims-prelude.md`](../outputs/report/PID_0171_html_report_20260904/data/pid-171-us-process-lims-prelude.md:98)). The base variable name is consistent with the generated DataTable declaration, but dotted access with an embedded-space field name has no precedent in the PAD reference corpus. The cited WorkQueues example uses a scalar queue variable ([`vbo-action-mapping.md`](pad-reference/vbo-action-mapping.md:24)).

**Impact:** the output is no longer a literal placeholder, but it is not citation-backed PAD syntax and may not resolve at runtime.

### Gap 2 — Unsupported `Mark Exception` dispatch heuristic

The catalogue contains the three cited statuses ([`vbo_catalogue.yaml`](../mapping/vbo_catalogue.yaml:449)), but the implementation chooses variants using `Tag`. The real `Mark Exception` inputs are `Item ID`, `Exception Reason`, `Retry`, and `Keep Locked` ([`pid-171-us-process-lims-prelude.md`](../outputs/report/PID_0171_html_report_20260904/data/pid-171-us-process-lims-prelude.md:990)); no `Tag` is available there. Both real call sites therefore render `BusinessException`.

**Impact:** the implementation silently emits the wrong status for system and system-unavailable contexts. The correct signal is surrounding exception/control-flow context, which is part of Task 7b rather than this strictly scoped task.

### Gap 3 — Tests do not verify semantic correctness

The current tests verify that placeholders are absent and catalogue keys exist, but they do not verify that the queue expression is valid or that exception dispatch works. The review explicitly identifies the dispatch test as self-referential ([`7a-2026-09-04-thirdpass.md`](reviews/7a-2026-09-04-thirdpass.md:94)).

### Gap 4 — Scope and commit hygiene

The latest review found an unrelated documentation diff outside Task 7a scope and noted that the reviewed fixes were uncommitted ([`7a-2026-09-04-thirdpass.md`](reviews/7a-2026-09-04-thirdpass.md:121)). The final implementation must isolate the declared Task 7a files and commit them before review.

## Sub-Tasks

### Sub-Task 1 — Confirm the queue-name binding design

**Intent:** Replace the unsupported compound queue expression with a source- and reference-backed PAD value without adding a new mapping abstraction.

**Expected Outcomes:** The generated `Get Next Item` action uses either an already-declared scalar queue variable or a documented PAD DataTable access form. No bare dotted field access with an embedded-space field name remains.

**Todo List:**

1. Trace the existing config-read and variable-mapping path for `ConfigFileData.Queue Name`.
2. Determine whether the conversion already creates a scalar queue-name variable.
3. If a scalar exists, bind `<id>` to that canonical variable.
4. If no scalar exists, select only a DataTable access form supported by the PAD reference documentation; do not invent syntax.
5. Keep the change inside the WorkQueues dispatch branch and its tests.
6. Regenerate PID_0171 and inspect every `Get Next Item` call site.

**Relevant Context:** [`vbo-action-mapping.md`](pad-reference/vbo-action-mapping.md:24), [`pid-171-us-process-lims-prelude.md`](../outputs/report/PID_0171_html_report_20260904/data/pid-171-us-process-lims-prelude.md:98), [`pad.py`](../src/flowsmith/generator/pad.py:1503), existing variable mapping in [`pad.py`](../src/flowsmith/generator/pad.py:1213).

**Status:** [ ] pending

### Sub-Task 2 — Remove unsupported exception dispatch from Task 7a

**Intent:** Prevent Task 7a from making an uncited status decision and establish an explicit handoff to Task 7b.

**Expected Outcomes:** No `Tag`-based heuristic remains. Task 7a either renders the documented default with an explicit verification/deferred marker, or uses a clearly documented placeholder pathway that cannot be mistaken for completed three-way dispatch. The implementation does not claim to select `ITException` or `GenericException` without exception context.

**Todo List:**

1. Remove the `stage.params_map["Tag"]` and stage-name heuristic.
2. Preserve the cited catalogue variants for Task 7b consumption.
3. Use the smallest explicit deferred behavior supported by existing generator conventions.
4. Document that exception-type selection requires the calling Block/control-flow context and is deferred to Task 7b.
5. Ensure `Tag Item` remains a separate TODO action and is not used as an exception-status signal.

**Relevant Context:** [`vbo_catalogue.yaml`](../mapping/vbo_catalogue.yaml:449), [`vbo-action-mapping.md`](pad-reference/vbo-action-mapping.md:26), [`pid-171-us-process-lims-prelude.md`](../outputs/report/PID_0171_html_report_20260904/data/pid-171-us-process-lims-prelude.md:990), Task 7b boundary in [`pad-generation-task-prompts.md`](pad-generation-task-prompts.md:1169).

**Status:** [ ] pending

### Sub-Task 3 — Strengthen generator and router tests

**Intent:** Make the tests fail for the exact defects identified by the reviews rather than only checking catalogue presence or placeholder removal.

**Expected Outcomes:** Tests verify source-bound parameter substitution, valid queue binding, correct status-text preservation, expected TODO behavior, and explicit deferral of context-sensitive exception selection.

**Todo List:**

1. Assert no literal angle-bracket placeholders appear in rendered WorkQueues actions.
2. Assert the `Get Next Item` queue expression is canonical and not a dotted embedded-space field reference.
3. Assert the generated queue and exception-detail references correspond to declared/canonical variables or documented PAD access syntax.
4. Retain assertions that `Update Status` uses the BP `Status` value and does not fall back to a generic processing-note token.
5. Retain assertions that only `Tag Item` and `Defer` remain TODOs.
6. Replace the self-referential three-variant test with an assertion for explicit Task 7b deferral, not false three-way success.
7. Keep router coverage for catalogue method-action resolution without expanding the task into unrelated router refactoring.

**Relevant Context:** [`test_pad.py`](../tests/generator/test_pad.py:1), [`test_vbo_router.py`](../tests/mapper/test_vbo_router.py:1), prior review findings in [`7a-2026-09-04-thirdpass.md`](reviews/7a-2026-09-04-thirdpass.md:94).

**Status:** [ ] pending

### Sub-Task 4 — Validate scope, regeneration, and review readiness

**Intent:** Produce a clean, reviewable Task 7a change with evidence that the generated PID_0171 output meets the revised acceptance criteria.

**Expected Outcomes:** Declared tests pass, lint is clean, generated output contains correct WorkQueues bindings, and the implementation diff contains no unrelated documentation changes.

**Todo List:**

1. Reconcile or revert unrelated [`docs/bp-to-pad-pipeline-plan.md`](bp-to-pad-pipeline-plan.md) changes before implementation review.
2. Run the focused generator, router, and PID_0171 end-to-end tests.
3. Run Ruff on `src/` and `tests/`.
4. Regenerate PID_0171 into a fresh output directory.
5. Manually inspect every generated `WorkQueues.` call.
6. Separate known pre-existing PID_0127 fixture failures from Task 7a results.
7. Commit only the declared Task 7a implementation and test files.
8. Request a new 7a review against the committed change.

**Relevant Context:** [`7a-2026-09-04-thirdpass.md`](reviews/7a-2026-09-04-thirdpass.md:110), Task 7a file scope in [`pad-generation-task-prompts.md`](pad-generation-task-prompts.md:1141).

**Status:** [ ] pending

## Non-Goals

- No `GLOBAL.` qualification changes.
- No consecutive-exception counter or breach-limit implementation.
- No new PAD syntax for `Tag Item` or `Defer`.
- No changes to unrelated VBO catalogue entries.
- No generator/annotator architecture refactor to eliminate the pre-existing duplicate method-action lookup unless separately approved.
- No edits to implementation files as part of this planning step.

## Validation Checklist for the Next Implementation Phase

- [ ] Queue binding is scalar or citation-backed DataTable access.
- [ ] No `Tag`-based exception dispatch remains.
- [ ] Context-sensitive `Mark Exception` variant selection is explicitly deferred to Task 7b.
- [ ] `Get Next Item`, `Mark Completed`, and `Update Status` render source-bound values.
- [ ] `Tag Item` and `Defer` remain TODOs.
- [ ] Tests detect the former queue-expression and self-referential-dispatch failures.
- [ ] Focused tests and lint pass.
- [ ] Generated PID_0171 output is manually checked.
- [ ] Only declared Task 7a files are committed.
