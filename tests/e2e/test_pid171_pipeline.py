"""End-to-end acceptance test — Sub-Task 8.

Runs the full .bprelease → .zip pipeline against the real PID_0171 sample and
asserts the structural invariants the reference managed solution
(`samples/pad/Shell_PP_PID_US_171_US_PreludeLIMS_V12_1_0_0_2_managed/`)
satisfies. Divergences that are known, documented gaps — workflow count,
Category split, WorkQueues action fidelity, environment variables — are
recorded in `docs/SUBTASK8_VALIDATION_REPORT.md` rather than asserted here.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from lxml import etree

from flowsmith.ast import build_ast
from flowsmith.ast.models import BPProcess, ConfidenceBand, StageType
from flowsmith.engine import create_annotator
from flowsmith.generator import PADGenerator, SolutionPackager
from flowsmith.parser import parse_process

SAMPLE = Path("samples/blueprism/PID_0171.bprelease")

pytestmark = pytest.mark.skipif(not SAMPLE.exists(), reason="PID_0171 sample not present")


@pytest.fixture(scope="module")
def annotated_process() -> BPProcess:
    """Parse, build and annotate the PID_0171 process once per module."""
    process = build_ast(parse_process(SAMPLE))
    create_annotator().annotate_process(process)
    return process


@pytest.fixture(scope="module")
def solution_zip(annotated_process: BPProcess, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Generate the full solution .zip from the annotated process.

    Task 7d item 1: in consolidated path, CloudFlowGenerator is embedded in the packager.
    The per-page CloudFlowGenerator.generate_process() call is no longer part of the pipeline.
    """
    out = tmp_path_factory.mktemp("pid171")
    robin_dir = out / "robin"
    PADGenerator().generate_process(annotated_process, robin_dir)
    # Task 7d: no per-page Cloud Flow files and no cloudflow/ folder — the packager
    # generates the orchestrator itself on the consolidated path (mirrors cli/app.py).
    zip_path = out / "solution.zip"
    SolutionPackager().package(annotated_process, robin_dir, None, zip_path, managed=True)
    return zip_path


class TestAstAnnotation:
    """Step 2 — the AST is fully annotated before generation."""

    def test_every_stage_is_annotated(self, annotated_process: BPProcess) -> None:
        """No stage is left without a PAAnnotation."""
        stages = [s for p in annotated_process.pages for s in p.stages]
        assert stages
        assert [s.stage_id for s in stages if s.pa_annotation is None] == []

    def test_zero_confidence_actions_are_flagged_manual(self, annotated_process: BPProcess) -> None:
        """A 0.0-confidence ACTION is always MANUAL with an error flag.

        PID_0171 calls custom business VBOs (PID_0005_Object_US_…,
        MS Outlook Extended VBO, …) that mapping/vbo_catalogue.yaml does not
        cover, so they legitimately score 0.0. What must never happen is a
        0.0 score that still generates code: those stages have to land in the
        MANUAL band carrying an error ReviewFlag.
        """
        actions = [
            s for p in annotated_process.pages for s in p.stages if s.stage_type == StageType.ACTION
        ]
        assert actions

        for action in actions:
            annotation = action.pa_annotation
            if annotation.confidence > 0.0:
                continue
            assert annotation.band == ConfidenceBand.MANUAL, action.stage_id
            assert any(f.severity == "error" for f in annotation.flags), action.stage_id

    def test_most_action_stages_are_mapped(self, annotated_process: BPProcess) -> None:
        """The catalogue covers the large majority of ACTION stages."""
        actions = [
            s for p in annotated_process.pages for s in p.stages if s.stage_type == StageType.ACTION
        ]
        mapped = [a for a in actions if a.pa_annotation.confidence > 0.0]
        assert len(mapped) / len(actions) > 0.90


class TestPackageStructure:
    """Steps 3-5 — required files, well-formed XML, valid JSON, GUID consistency."""

    REQUIRED = (
        "solution.xml",
        "customizations.xml",
        "[Content_Types].xml",
        "Other/ManifestFile.json",
        "Other/DependenciesFile.json",
    )

    def test_required_files_present(self, solution_zip: Path) -> None:
        """The zip carries every file a Power Platform solution needs."""
        with zipfile.ZipFile(solution_zip) as zf:
            names = set(zf.namelist())
        assert [r for r in self.REQUIRED if r not in names] == []
        assert any(n.startswith("Workflows/") and n.endswith(".json") for n in names)

    def test_all_xml_is_well_formed(self, solution_zip: Path) -> None:
        """solution.xml, customizations.xml and [Content_Types].xml all parse."""
        with zipfile.ZipFile(solution_zip) as zf:
            for name in ("solution.xml", "customizations.xml", "[Content_Types].xml"):
                assert etree.fromstring(zf.read(name)) is not None

    def test_all_json_is_valid(self, solution_zip: Path) -> None:
        """Every .json entry in the zip parses."""
        with zipfile.ZipFile(solution_zip) as zf:
            invalid = []
            for name in zf.namelist():
                if not name.endswith(".json"):
                    continue
                try:
                    json.loads(zf.read(name))
                except ValueError:
                    invalid.append(name)
        assert invalid == []

    def test_root_components_match_workflow_ids(self, solution_zip: Path) -> None:
        """Every solution.xml RootComponent id has a customizations.xml Workflow."""
        with zipfile.ZipFile(solution_zip) as zf:
            cust = etree.fromstring(zf.read("customizations.xml"))
            sol = etree.fromstring(zf.read("solution.xml"))

        workflow_ids = {
            w.get("WorkflowId").strip("{}").lower() for w in cust.findall(".//{*}Workflow")
        }
        root_ids = {r.get("id").strip("{}").lower() for r in sol.findall(".//{*}RootComponent")}
        assert root_ids
        assert root_ids.issubset(workflow_ids)

    def test_root_components_are_type_29(self, solution_zip: Path) -> None:
        """RootComponents are workflow components, matching the reference."""
        with zipfile.ZipFile(solution_zip) as zf:
            sol = etree.fromstring(zf.read("solution.xml"))
        types = {r.get("type") for r in sol.findall(".//{*}RootComponent")}
        assert types == {"29"}

    def test_managed_flag_is_one(self, solution_zip: Path) -> None:
        """managed=True produces <Managed>1</Managed>, matching the reference."""
        with zipfile.ZipFile(solution_zip) as zf:
            sol = etree.fromstring(zf.read("solution.xml"))
        assert sol.findtext(".//{*}Managed") == "1"

    def test_every_json_file_name_resolves(self, solution_zip: Path) -> None:
        """No Workflow points at a Workflows/*.json entry that is absent."""
        with zipfile.ZipFile(solution_zip) as zf:
            names = set(zf.namelist())
            cust = etree.fromstring(zf.read("customizations.xml"))
        referenced = [
            w.findtext("JsonFileName").lstrip("/") for w in cust.findall(".//{*}Workflow")
        ]
        assert [r for r in referenced if r not in names] == []


class TestDefinitionContent:
    """Step 4/6 — <Definition> holds compilable PAD script."""

    @staticmethod
    def _definitions(solution_zip: Path) -> list[str]:
        """Decode every Desktop Flow (Category 6) Workflow's <Definition> to PAD script text.

        Filters to Desktop Flows only (Category == 6 in workflow_builder.py) because Cloud Flows
        have Category == 5 and their <Definition> is Logic App JSON, not PAD script.
        """
        with zipfile.ZipFile(solution_zip) as zf:
            cust = etree.fromstring(zf.read("customizations.xml"))
        # Filter to workflows with Category=6 (Desktop Flows, PAD script)
        pad_workflows = [
            w for w in cust.findall(".//{*}Workflow") if w.findtext("{*}Category") == "6"
        ]
        return [json.loads(w.findtext("Definition")) for w in pad_workflows]

    @staticmethod
    def _cloud_flow_definitions(solution_zip: Path) -> list[dict]:
        """Load every Cloud Flow (Category 5) Workflow's actual JSON from the referenced file.

        Task 7d item 2: Cloud Flows store their Logic App JSON in the <JsonFileName> file,
        not in a <Definition> XML element. This method reads the actual JSON files.

        Used for Cloud Flow (orchestrator) well-formedness checks.
        """
        with zipfile.ZipFile(solution_zip) as zf:
            cust = etree.fromstring(zf.read("customizations.xml"))
            # Filter to workflows with Category=5 (Cloud Flows, Logic App JSON)
            cloud_workflows = [
                w for w in cust.findall(".//{*}Workflow") if w.findtext("{*}Category") == "5"
            ]
            # No error swallowing: a missing or undecodable file must fail the test.
            return [
                json.loads(zf.read(w.findtext("{*}JsonFileName").lstrip("/")).decode("utf-8"))
                for w in cloud_workflows
            ]

    def test_definitions_are_non_empty(self, solution_zip: Path) -> None:
        """Every Desktop Flow carries embedded PAD script."""
        definitions = self._definitions(solution_zip)
        assert definitions, "At least one Desktop Flow (PAD script) should exist"
        assert all(d.strip() for d in definitions)

    def test_definitions_start_with_connection_string(self, solution_zip: Path) -> None:
        """PAD's @@ directives lead every Desktop Flow script, as in the reference."""
        pad_scripts = self._definitions(solution_zip)
        assert pad_scripts, "No Desktop Flow PAD scripts found to check"
        assert all(d.startswith("@@ConnectionString:") for d in pad_scripts)

    def test_definitions_carry_import_statements(self, solution_zip: Path) -> None:
        """Both repo IMPORT lines the reference uses are present in Desktop Flow scripts."""
        for definition in self._definitions(solution_zip):
            assert "IMPORT 'controlRepo.appmask' AS appmask" in definition
            assert "IMPORT 'imageRepo.imgrepo' AS imgrepo" in definition

    def test_definitions_wrap_body_in_a_function(self, solution_zip: Path) -> None:
        """Each Desktop Flow script declares exactly one FUNCTION ... END FUNCTION."""
        for definition in self._definitions(solution_zip):
            assert "FUNCTION " in definition
            assert "END FUNCTION" in definition

    def test_block_structure_is_generated(self, solution_zip: Path) -> None:
        """BLOCK stages produce BLOCK / ON BLOCK ERROR / END scopes in Desktop Flows."""
        definitions = self._definitions(solution_zip)
        with_blocks = [d for d in definitions if "BLOCK '" in d]
        assert with_blocks, "At least one Desktop Flow should contain BLOCK stages"
        for definition in with_blocks:
            assert "ON BLOCK ERROR" in definition

    def test_no_goto_dangles(self, solution_zip: Path) -> None:
        """Every GOTO target has a matching LABEL in the same Desktop Flow script."""
        for definition in self._definitions(solution_zip):
            for target in ("Error Block", "End"):
                if f"GOTO '{target}'" in definition:
                    assert f"LABEL '{target}'" in definition

    def test_cloud_flow_definitions_are_well_formed_json(self, solution_zip: Path) -> None:
        """Every Cloud Flow definition is valid JSON (orchestrator well-formedness check)."""
        cloud_defs = self._cloud_flow_definitions(solution_zip)
        assert cloud_defs, "At least one Cloud Flow (orchestrator) should exist"
        for definition in cloud_defs:
            # Validate that it's well-formed JSON (already parsed from json.loads calls)
            assert isinstance(definition, dict), (
                f"Cloud Flow definition should be a dict after JSON parsing, got {type(definition)}"
            )

    def test_cloud_flow_json_file_is_real_logic_app_definition(self, solution_zip: Path) -> None:
        """Task 7d item 2 (§A1): the CF <JsonFileName> payload is the Logic App JSON."""
        cloud_defs = self._cloud_flow_definitions(solution_zip)
        assert len(cloud_defs) == 1
        assert cloud_defs[0] != {"package": ""}
        definition = cloud_defs[0]["properties"]["definition"]
        assert "triggers" in definition and "actions" in definition

    def test_cloud_flow_workflow_has_no_inline_definition(self, solution_zip: Path) -> None:
        """Task 7d item 2 (§A1): Category-5 <Workflow>s carry no <Definition>; DFs do."""
        with zipfile.ZipFile(solution_zip) as zf:
            cust = etree.fromstring(zf.read("customizations.xml"))
        workflows = cust.findall(".//{*}Workflow")
        by_category = {
            cat: [w for w in workflows if w.findtext("{*}Category") == cat] for cat in ("5", "6")
        }
        assert len(by_category["5"]) == 1 and len(by_category["6"]) == 2
        assert all(w.find("{*}Definition") is None for w in by_category["5"])
        assert all(w.find("{*}Definition") is not None for w in by_category["6"])

    def test_no_unreferenced_workflow_json(self, solution_zip: Path) -> None:
        """Task 7d item 1: every Workflows/*.json file is referenced by a <JsonFileName>."""
        with zipfile.ZipFile(solution_zip) as zf:
            cust = etree.fromstring(zf.read("customizations.xml"))
            files = {n for n in zf.namelist() if n.startswith("Workflows/")}
        referenced = {
            w.findtext("{*}JsonFileName").lstrip("/") for w in cust.findall(".//{*}Workflow")
        }
        assert files == referenced


@pytest.fixture(scope="module")
def robin_flows(annotated_process: BPProcess, tmp_path_factory: pytest.TempPathFactory) -> dict:
    """The generated Loader/Performer .robin text, keyed by role."""
    out = tmp_path_factory.mktemp("pid171_7e")
    files = PADGenerator().generate_process(annotated_process, out)
    return {
        role: next(f for f in files if f.name.endswith(f"_{role.capitalize()}.robin")).read_text(
            encoding="utf-8"
        )
        for role in ("loader", "performer")
    }


def _load_config_body(text: str) -> list[str]:
    """Lines of FUNCTION 'Load Config Data' (header to END FUNCTION)."""
    lines = text.splitlines()
    start = lines.index("FUNCTION 'Load Config Data' GLOBAL")
    end = next(i for i in range(start, len(lines)) if lines[i] == "END FUNCTION")
    return lines[start : end + 1]


@pytest.mark.parametrize("role", ["loader", "performer"])
class TestTask7eConfigFollowUp:
    """Task 7e done condition on the real PID_0171 output, both flows."""

    def test_environment_items_accounted_for(self, robin_flows: dict, role: str) -> None:
        """§B12: the 3 process-level Environment items (no initial value) are read in Load
        Config Data by BP name; the 8 of the called process are each named in a TODO."""
        body = _load_config_body(robin_flows[role])
        for bp_name, var in (
            ("PID_171_US_EV_LIMS_Prelude_ConfigFile", "txt_PID171USEVLIMSPreludeConfigFile"),
            ("Generic_SupportTeam_EmailID", "txt_GenericSupportTeamEmailID"),
            (
                "Generic_RPA_Sharepoint_API_Config_File_Folder_Path",
                "txt_GenericRPASharepointAPIConfigFileFolderPath",
            ),
        ):
            assert f"SET {var} TO obj_Config['{bp_name}']" in body
        linked = [ln for ln in body if "belongs to 'RPA_Sharepoint_API_ConfigFile_Download'" in ln]
        assert len(linked) == 8

    def test_config_read_stages_replaced_not_live(self, robin_flows: dict, role: str) -> None:
        """Item 3: the BP config-read machinery leaves only its comments."""
        text = robin_flows[role]
        assert (
            "# Replaced by Load Config Data: BP 'ConvertConfigFile As Collection' loaded "
            "ConfigFileData from the config file"
        ) in text
        assert "# BEGIN fold: 'ConvertConfigFile As Collection - Copy'" not in text
        assert "# BEGIN fold: 'Read Excel As Collection'" not in text
        assert "SET dtb_ConfigFileData TO" not in text
        assert "SET txt_ConfigFileSheetName TO" not in text
        assert "TODO: complete Download Config File from SharePoint" not in text

    def test_generic_support_email_assigned_and_no_unflagged_unassigned_read(
        self, robin_flows: dict, role: str
    ) -> None:
        """Item 4: txt_GenericSupportTeamEmailID (BP Environment item
        'Generic_SupportTeam_EmailID') is now assigned in Load Config Data, so it is never
        TODO-flagged as unassigned."""
        text = robin_flows[role]
        assert "txt_GenericSupportTeamEmailID is read here" not in text

    def test_handler_flags_initialised(self, robin_flows: dict, role: str) -> None:
        """Item 5: both flags initialised before CALL 'Load Config Data'."""
        lines = robin_flows[role].splitlines()
        call_idx = lines.index("CALL 'Load Config Data'")
        assert lines.index("SET flg_Screenshot TO True") < call_idx
        assert lines.index("SET flg_ConfigError TO False") < call_idx

    def test_7d_invariants_hold(self, robin_flows: dict, role: str) -> None:
        """Task 7d invariants still hold after Task 7e."""
        text = robin_flows[role]
        parse = "Variables.ConvertJsonToCustomObject Json: In_txt_Config CustomObject=> obj_Config"
        assert text.count(parse) == 1
        assert text.splitlines().count("CALL 'Load Config Data'") == 1
        assert text.count("FUNCTION 'Load Config Data' GLOBAL") == 1
        assert "dtb_ConfigFileData." not in text
        assert "%SomeVar%" not in text


class TestTask8bLoops:
    """Task 8b item 2 on the real PID_0171 output."""

    def test_mail_items_loop_built_with_row_read(self, robin_flows: dict) -> None:
        """Populate Queue's 'Mail Items' ForEach loop (inlined into the Loader) renders as
        one LOOP FOREACH over dtb_MailItems with its body nested and its row read."""
        lines = robin_flows["loader"].splitlines()
        loop_idx = lines.index("LOOP FOREACH dtr_CurrentMailItems IN dtb_MailItems")
        end_idx = next(i for i in range(loop_idx, len(lines)) if lines[i] == "END")
        body = lines[loop_idx + 1 : end_idx]
        assert body[0].startswith("    SET txt_EmailSubject TO dtr_CurrentMailItems['Subject']")
        assert all(line == "" or line.startswith("    ") for line in body)

    @pytest.mark.parametrize(("role", "built", "unbuilt"), [("loader", 1, 0), ("performer", 2, 2)])
    def test_every_emitted_loop_built_or_todo(
        self, robin_flows: dict, role: str, built: int, unbuilt: int
    ) -> None:
        """Each LoopStart reaching the flow is either a LOOP FOREACH dtr_... IN ... or a
        TODO naming it (Loader: Mail Items built; Performer: Loop Final Product and
        Component Names built, Loop Input and Final Product left as TODOs), and no
        commented '# System.LOOP' template remains."""
        text = robin_flows[role]
        stripped = [line.strip() for line in text.splitlines()]
        assert sum(line.startswith("LOOP FOREACH dtr_Current") for line in stripped) == built
        assert sum(line.startswith("# TODO: LOOP '") for line in stripped) == unbuilt
        assert sum(line.startswith("# TODO: end of unbuilt LOOP '") for line in stripped) == unbuilt
        assert "# System.LOOP" not in text


# ── Task 8b fix pass (gap 1): string-literal well-formedness of the .robin output ──

SAMPLE_0127 = Path("samples/blueprism/PID_0127.bprelease")

# Pre-existing (present at base 8592c84, before Task 8b): PID_0127's 'WithSIMAAS'/
# 'WithOutSIMAAS' Calculation stages carry a raw multi-line PowerShell script as their BP
# expression, which the CALCULATION renderer emits verbatim; its
# `$itm.FieldValues"FSObjType"` lines put a literal against an identifier. Not a quoting
# bug of the Trim/ChangeCase wrapper — tracked as an open question, not fixed here.
_PREEXISTING_MALFORMED_PREFIXES = ("Get-PnPListItem -List $SourceName",)


def robin_literal_errors(text: str) -> list[tuple[int, str]]:
    """Scan PAD .robin text for malformed string literals, outside comments.

    Recognises the literal forms used in the reference sources
    (``docs/pad-reference/*.robin.txt``): ``$'''...'''`` (may span lines and contain
    ``''``, e.g. Main L801 ``$'''%''%'''``), ``'...'`` (single line, backslash escapes,
    e.g. Loader L109 ``'\\'``) and the generator's BP ``"..."`` literals (may span lines,
    ``""`` escapes a quote). ``#`` outside a literal starts a comment to end of line.
    A literal that never closes is unbalanced; a literal directly touching an identifier
    character or another quote (``'dtr_X['Field']'`` tokenises as literal, identifier,
    literal) is a broken quote pair.

    Args:
        text: The .robin file content.

    Returns:
        ``(line_number, reason)`` per malformed literal.
    """
    errors: list[tuple[int, str]] = []
    n = len(text)
    i = 0

    def line_of(pos: int) -> int:
        return text.count("\n", 0, pos) + 1

    while i < n:
        char = text[i]
        start = i
        if char == "#":
            newline = text.find("\n", i)
            i = n if newline < 0 else newline
            continue
        if text.startswith("$'''", i):
            close = text.find("'''", i + 4)
            if close < 0:
                errors.append((line_of(start), "unterminated $''' literal"))
                break
            i = close + 3
        elif char == "'":
            j = i + 1
            while j < n and text[j] not in "'\n":
                j += 2 if text[j] == "\\" else 1
            if j >= n or text[j] != "'":
                errors.append((line_of(start), "unterminated ' literal"))
                i = j
                continue
            i = j + 1
        elif char == '"':
            j = i + 1
            while True:
                close = text.find('"', j)
                if close >= 0 and text.startswith('""', close):
                    j = close + 2
                    continue
                break
            if close < 0:
                errors.append((line_of(start), 'unterminated " literal'))
                break
            i = close + 1
        else:
            i += 1
            continue
        before = text[start - 1] if start > 0 else " "
        after = text[i] if i < n else " "
        if after.isalnum() or after in "_'\"" or before.isalnum() or before == "_":
            errors.append((line_of(start), "literal touches an identifier or quote"))
    return errors


def _unexpected_literal_errors(text: str) -> list[str]:
    """The malformed-literal lines of ``text`` not in the pre-existing allowlist."""
    lines = text.splitlines()
    return sorted(
        {
            f"L{line_no}: {reason}: {lines[line_no - 1].strip()[:160]}"
            for line_no, reason in robin_literal_errors(text)
            if not lines[line_no - 1].strip().startswith(_PREEXISTING_MALFORMED_PREFIXES)
        }
    )


def test_literal_checker_accepts_reference_and_rejects_broken_quoting() -> None:
    """The checker passes the real reference sources and catches the 8b regression shape."""
    for ref in Path("docs/pad-reference").glob("*.robin.txt"):
        assert robin_literal_errors(ref.read_text(encoding="utf-8")) == [], ref.name
    assert robin_literal_errors("Text.Trim 'dtr_CurrentX['Identity']' => txt_t") != []
    assert robin_literal_errors("SET txt_A TO 'unclosed\nSET txt_B TO 1") != []
    assert robin_literal_errors("SET txt_A TO $'''%''%''' # it's a comment") == []


@pytest.fixture(scope="module")
def robin_flows_0127(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """The generated PID_0127 Loader/Performer .robin text, keyed by role."""
    if not SAMPLE_0127.exists():
        pytest.skip("PID_0127 sample not present")
    process = build_ast(parse_process(SAMPLE_0127))
    create_annotator().annotate_process(process)
    files = PADGenerator().generate_process(process, tmp_path_factory.mktemp("pid127_8b"))
    return {
        role: next(f for f in files if f.name.endswith(f"_{role.capitalize()}.robin")).read_text(
            encoding="utf-8"
        )
        for role in ("loader", "performer")
    }


@pytest.mark.parametrize("role", ["loader", "performer"])
def test_pid171_robin_literals_well_formed(robin_flows: dict, role: str) -> None:
    """Gap 1: no malformed string literal in the PID_0171 flows (was 2 in the Performer:
    `Text.Trim 'dtr_CurrentFinalProduct['Identity']'`, `'dtr_CurrentComponentNames['Value']'`)."""
    assert _unexpected_literal_errors(robin_flows[role]) == []


@pytest.mark.parametrize("role", ["loader", "performer"])
def test_pid127_robin_literals_well_formed(robin_flows_0127: dict, role: str) -> None:
    """Gap 1: no malformed string literal in the PID_0127 flows beyond the pre-existing
    PowerShell dump (was 1 more in the Loader: `'dtr_CurrentParentQ['Sno']'`)."""
    assert _unexpected_literal_errors(robin_flows_0127[role]) == []
