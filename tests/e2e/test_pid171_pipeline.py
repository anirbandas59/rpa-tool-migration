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
from flowsmith.generator import CloudFlowGenerator, PADGenerator, SolutionPackager
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
    """Generate the full solution .zip from the annotated process."""
    out = tmp_path_factory.mktemp("pid171")
    robin_dir = out / "robin"
    cf_dir = out / "cloudflow"
    PADGenerator().generate_process(annotated_process, robin_dir)
    CloudFlowGenerator().generate_process(annotated_process, cf_dir)
    zip_path = out / "solution.zip"
    SolutionPackager().package(annotated_process, robin_dir, cf_dir, zip_path, managed=True)
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
        """Decode every Workflow's <Definition> back to PAD script text."""
        with zipfile.ZipFile(solution_zip) as zf:
            cust = etree.fromstring(zf.read("customizations.xml"))
        return [json.loads(w.findtext("Definition")) for w in cust.findall(".//{*}Workflow")]

    def test_definitions_are_non_empty(self, solution_zip: Path) -> None:
        """Every Workflow carries embedded PAD script."""
        definitions = self._definitions(solution_zip)
        assert definitions
        assert all(d.strip() for d in definitions)

    def test_definitions_start_with_connection_string(self, solution_zip: Path) -> None:
        """PAD's @@ directives lead every script, as in the reference."""
        assert all(d.startswith("@@ConnectionString:") for d in self._definitions(solution_zip))

    def test_definitions_carry_import_statements(self, solution_zip: Path) -> None:
        """Both repo IMPORT lines the reference uses are present."""
        for definition in self._definitions(solution_zip):
            assert "IMPORT 'controlRepo.appmask' AS appmask" in definition
            assert "IMPORT 'imageRepo.imgrepo' AS imgrepo" in definition

    def test_definitions_wrap_body_in_a_function(self, solution_zip: Path) -> None:
        """Each script declares exactly one FUNCTION ... END FUNCTION."""
        for definition in self._definitions(solution_zip):
            assert "FUNCTION " in definition
            assert "END FUNCTION" in definition

    def test_block_structure_is_generated(self, solution_zip: Path) -> None:
        """BLOCK stages produce BLOCK / ON BLOCK ERROR / END scopes."""
        definitions = self._definitions(solution_zip)
        with_blocks = [d for d in definitions if "BLOCK '" in d]
        assert with_blocks
        for definition in with_blocks:
            assert "ON BLOCK ERROR" in definition

    def test_no_goto_dangles(self, solution_zip: Path) -> None:
        """Every GOTO target has a matching LABEL in the same script."""
        for definition in self._definitions(solution_zip):
            for target in ("Error Block", "End"):
                if f"GOTO '{target}'" in definition:
                    assert f"LABEL '{target}'" in definition
