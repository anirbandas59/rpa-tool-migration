"""Tests for the Solution Packager."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from lxml import etree

from flowsmith.ast.models import (
    BPPage,
    BPProcess,
    BPStage,
    ConfidenceBand,
    PAAnnotation,
    Runtime,
    StageType,
)
from flowsmith.exceptions import GenerationError
from flowsmith.generator import SolutionPackager

# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def packager() -> SolutionPackager:
    """Return a SolutionPackager instance."""
    return SolutionPackager()


@pytest.fixture
def minimal_process() -> BPProcess:
    """Return a minimal BPProcess for testing."""
    return BPProcess(
        process_id="test_123",
        name="TestProcess",
        version="1.0",
        pages=[],
        source_file="test.bprelease",
    )


@pytest.fixture
def robin_dir(tmp_path: Path) -> Path:
    """Create a temporary directory with dummy .robin files."""
    robin_path = tmp_path / "robin"
    robin_path.mkdir(parents=True, exist_ok=True)

    # Create 3 dummy .robin files
    (robin_path / "flow1.robin").write_text("robin content 1")
    (robin_path / "flow2.robin").write_text("robin content 2")
    (robin_path / "flow3.robin").write_text("robin content 3")

    return robin_path


@pytest.fixture
def cloudflow_dir(tmp_path: Path) -> Path:
    """Create a temporary directory with dummy .json files."""
    cf_path = tmp_path / "cf"
    cf_path.mkdir(parents=True, exist_ok=True)

    # Create 2 dummy .json files with valid JSON
    cf1 = {"name": "CloudFlow1", "type": "cloud_flow"}
    cf2 = {"name": "CloudFlow2", "type": "cloud_flow"}

    (cf_path / "flow1.json").write_text(json.dumps(cf1))
    (cf_path / "flow2.json").write_text(json.dumps(cf2))

    return cf_path


# ── Tests ──────────────────────────────────────────────────────────────────


class TestPackagerInitialisation:
    """Tests for packager initialisation."""

    def test_packager_initialises_cleanly(self) -> None:
        """Test that SolutionPackager can be instantiated."""
        packager = SolutionPackager()
        assert packager is not None
        assert packager.template_dir is not None

    def test_packager_loads_jinja_environment(self) -> None:
        """Test that Jinja2 environment is initialised."""
        packager = SolutionPackager()
        assert packager.env is not None

    def test_missing_template_dir_raises_generation_error(self, tmp_path: Path) -> None:
        """Test that missing template dir raises GenerationError."""
        with pytest.raises(GenerationError) as exc_info:
            SolutionPackager(template_dir=tmp_path / "nonexistent")
        assert "Template directory not found" in str(exc_info.value)

    def test_custom_template_dir(self, tmp_path: Path) -> None:
        """Test that custom template dir is used."""
        custom_dir = tmp_path / "custom"
        custom_dir.mkdir()

        # Create minimal templates
        (custom_dir / "solution.xml.j2").write_text("<root/>")
        (custom_dir / "content_types.xml.j2").write_text("<types/>")

        packager = SolutionPackager(template_dir=custom_dir)
        assert packager.template_dir == custom_dir


class TestPackageCreation:
    """Tests for .zip package creation."""

    def test_package_creates_zip_file(
        self,
        packager: SolutionPackager,
        minimal_process: BPProcess,
        robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Test that package() creates a zip file."""
        output_path = tmp_path / "solution.zip"
        result = packager.package(
            minimal_process,
            robin_dir=robin_dir,
            cloudflow_dir=cloudflow_dir,
            output_path=output_path,
        )

        assert result.exists()
        assert result.suffix == ".zip"

    def test_package_returns_output_path(
        self,
        packager: SolutionPackager,
        minimal_process: BPProcess,
        robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Test that package() returns the output_path."""
        output_path = tmp_path / "solution.zip"
        result = packager.package(
            minimal_process,
            robin_dir=robin_dir,
            cloudflow_dir=cloudflow_dir,
            output_path=output_path,
        )

        assert result == output_path

    def test_output_parent_dir_created(
        self,
        packager: SolutionPackager,
        minimal_process: BPProcess,
        robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Test that output_path parent dirs are created automatically."""
        output_path = tmp_path / "nested" / "out.zip"
        assert not output_path.parent.exists()

        packager.package(
            minimal_process,
            robin_dir=robin_dir,
            cloudflow_dir=cloudflow_dir,
            output_path=output_path,
        )

        assert output_path.parent.exists()
        assert output_path.exists()


class TestZipContents:
    """Tests for zip file contents."""

    def test_zip_contains_solution_xml(
        self,
        packager: SolutionPackager,
        minimal_process: BPProcess,
        robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Test that zip contains solution.xml."""
        output_path = tmp_path / "solution.zip"
        packager.package(
            minimal_process,
            robin_dir=robin_dir,
            cloudflow_dir=cloudflow_dir,
            output_path=output_path,
        )

        with zipfile.ZipFile(output_path) as zf:
            assert "solution.xml" in zf.namelist()

    def test_zip_contains_content_types_xml(
        self,
        packager: SolutionPackager,
        minimal_process: BPProcess,
        robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Test that zip contains [Content_Types].xml."""
        output_path = tmp_path / "solution.zip"
        packager.package(
            minimal_process,
            robin_dir=robin_dir,
            cloudflow_dir=cloudflow_dir,
            output_path=output_path,
        )

        with zipfile.ZipFile(output_path) as zf:
            assert "[Content_Types].xml" in zf.namelist()

    def test_zip_contains_customizations_xml(
        self,
        packager: SolutionPackager,
        minimal_process: BPProcess,
        robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Test that zip contains customizations.xml."""
        output_path = tmp_path / "solution.zip"
        packager.package(
            minimal_process,
            robin_dir=robin_dir,
            cloudflow_dir=cloudflow_dir,
            output_path=output_path,
        )

        with zipfile.ZipFile(output_path) as zf:
            assert "customizations.xml" in zf.namelist()

    def test_zip_contains_robin_files(
        self,
        packager: SolutionPackager,
        minimal_process: BPProcess,
        robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Test that .robin content is embedded in customizations.xml (not as separate files).

        In Phase 6.4, PAD script content from .robin files is embedded directly in
        the Workflow elements' Definition field within customizations.xml, so separate
        .robin files should NOT appear in the solution package.
        """
        output_path = tmp_path / "solution.zip"
        packager.package(
            minimal_process,
            robin_dir=robin_dir,
            cloudflow_dir=cloudflow_dir,
            output_path=output_path,
        )

        with zipfile.ZipFile(output_path) as zf:
            names = zf.namelist()
            robin_files = [n for n in names if n.endswith(".robin")]

            # Robin files should be embedded in customizations.xml, not separate
            assert len(robin_files) == 0, (
                "Robin files should not be in zip (embedded in customizations.xml)"
            )
            # Verify customizations.xml exists with workflows
            assert "customizations.xml" in names

    def test_zip_contains_cloudflow_files(
        self,
        packager: SolutionPackager,
        minimal_process: BPProcess,
        robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Test that all .json files appear in Workflows/."""
        output_path = tmp_path / "solution.zip"
        packager.package(
            minimal_process,
            robin_dir=robin_dir,
            cloudflow_dir=cloudflow_dir,
            output_path=output_path,
        )

        with zipfile.ZipFile(output_path) as zf:
            names = zf.namelist()
            cf_files = [n for n in names if "Workflows/" in n and n.endswith(".json")]

            assert len(cf_files) == 2

    def test_zip_contains_manifest(
        self,
        packager: SolutionPackager,
        minimal_process: BPProcess,
        robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Test that zip contains Other/ManifestFile.json."""
        output_path = tmp_path / "solution.zip"
        packager.package(
            minimal_process,
            robin_dir=robin_dir,
            cloudflow_dir=cloudflow_dir,
            output_path=output_path,
        )

        with zipfile.ZipFile(output_path) as zf:
            assert "Other/ManifestFile.json" in zf.namelist()

    def test_zip_contains_dependencies(
        self,
        packager: SolutionPackager,
        minimal_process: BPProcess,
        robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Test that zip contains Other/DependenciesFile.json."""
        output_path = tmp_path / "solution.zip"
        packager.package(
            minimal_process,
            robin_dir=robin_dir,
            cloudflow_dir=cloudflow_dir,
            output_path=output_path,
        )

        with zipfile.ZipFile(output_path) as zf:
            assert "Other/DependenciesFile.json" in zf.namelist()


class TestXMLValidity:
    """Tests for XML validity."""

    def test_solution_xml_is_valid_xml(
        self,
        packager: SolutionPackager,
        minimal_process: BPProcess,
        robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Test that solution.xml is valid XML."""
        output_path = tmp_path / "solution.zip"
        packager.package(
            minimal_process,
            robin_dir=robin_dir,
            cloudflow_dir=cloudflow_dir,
            output_path=output_path,
        )

        with zipfile.ZipFile(output_path) as zf:
            sol_xml = zf.read("solution.xml")

        # Should not raise an exception
        root = etree.fromstring(sol_xml)
        assert root is not None

    def test_solution_xml_has_solution_manifest(
        self,
        packager: SolutionPackager,
        minimal_process: BPProcess,
        robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Test that solution.xml has SolutionManifest element."""
        output_path = tmp_path / "solution.zip"
        packager.package(
            minimal_process,
            robin_dir=robin_dir,
            cloudflow_dir=cloudflow_dir,
            output_path=output_path,
        )

        with zipfile.ZipFile(output_path) as zf:
            sol_xml = zf.read("solution.xml")

        root = etree.fromstring(sol_xml)
        manifest = root.find(".//{*}SolutionManifest")
        assert manifest is not None

    def test_solution_xml_has_correct_name(
        self,
        packager: SolutionPackager,
        minimal_process: BPProcess,
        robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Test that solution.xml contains correct process name."""
        output_path = tmp_path / "solution.zip"
        packager.package(
            minimal_process,
            robin_dir=robin_dir,
            cloudflow_dir=cloudflow_dir,
            output_path=output_path,
        )

        with zipfile.ZipFile(output_path) as zf:
            sol_xml = zf.read("solution.xml")

        root = etree.fromstring(sol_xml)
        unique_name = root.find(".//{*}UniqueName")
        assert unique_name is not None
        assert unique_name.text == minimal_process.name


class TestErrorHandling:
    """Tests for error handling."""

    def test_missing_robin_dir_raises_generation_error(
        self,
        packager: SolutionPackager,
        minimal_process: BPProcess,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Test that missing robin_dir raises GenerationError."""
        with pytest.raises(GenerationError) as exc_info:
            packager.package(
                minimal_process,
                robin_dir=tmp_path / "nonexistent_robin",
                cloudflow_dir=cloudflow_dir,
                output_path=tmp_path / "test.zip",
            )
        assert "Robin directory not found" in str(exc_info.value)

    def test_missing_cloudflow_dir_raises_generation_error(
        self,
        packager: SolutionPackager,
        minimal_process: BPProcess,
        robin_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Test that missing cloudflow_dir raises GenerationError."""
        with pytest.raises(GenerationError) as exc_info:
            packager.package(
                minimal_process,
                robin_dir=robin_dir,
                cloudflow_dir=tmp_path / "nonexistent_cf",
                output_path=tmp_path / "test.zip",
            )
        assert "Cloud Flow directory not found" in str(exc_info.value)

    def test_empty_robin_dir_still_packages(
        self,
        packager: SolutionPackager,
        minimal_process: BPProcess,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Test that empty robin_dir doesn't cause errors."""
        empty_robin = tmp_path / "empty_robin"
        empty_robin.mkdir()

        output_path = tmp_path / "solution.zip"
        result = packager.package(
            minimal_process,
            robin_dir=empty_robin,
            cloudflow_dir=cloudflow_dir,
            output_path=output_path,
        )

        assert result.exists()

    def test_empty_cloudflow_dir_still_packages(
        self,
        packager: SolutionPackager,
        minimal_process: BPProcess,
        robin_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Test that empty cloudflow_dir doesn't cause errors."""
        empty_cf = tmp_path / "empty_cf"
        empty_cf.mkdir()

        output_path = tmp_path / "solution.zip"
        result = packager.package(
            minimal_process,
            robin_dir=robin_dir,
            cloudflow_dir=empty_cf,
            output_path=output_path,
        )

        assert result.exists()


class TestManifestContent:
    """Tests for manifest file content."""

    def test_manifest_file_has_solution_name(
        self,
        packager: SolutionPackager,
        minimal_process: BPProcess,
        robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Test that ManifestFile.json contains solution name."""
        output_path = tmp_path / "solution.zip"
        packager.package(
            minimal_process,
            robin_dir=robin_dir,
            cloudflow_dir=cloudflow_dir,
            output_path=output_path,
        )

        with zipfile.ZipFile(output_path) as zf:
            manifest_str = zf.read("Other/ManifestFile.json").decode("utf-8")

        manifest = json.loads(manifest_str)
        assert manifest["SolutionName"] == minimal_process.name

    def test_manifest_file_has_version(
        self,
        packager: SolutionPackager,
        minimal_process: BPProcess,
        robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Test that ManifestFile.json contains version."""
        version = "2.0.0.0"
        output_path = tmp_path / "solution.zip"
        packager.package(
            minimal_process,
            robin_dir=robin_dir,
            cloudflow_dir=cloudflow_dir,
            output_path=output_path,
            version=version,
        )

        with zipfile.ZipFile(output_path) as zf:
            manifest_str = zf.read("Other/ManifestFile.json").decode("utf-8")

        manifest = json.loads(manifest_str)
        assert manifest["Version"] == version

    def test_dependencies_file_has_dependencies_array(
        self,
        packager: SolutionPackager,
        minimal_process: BPProcess,
        robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Test that DependenciesFile.json has Dependencies array."""
        output_path = tmp_path / "solution.zip"
        packager.package(
            minimal_process,
            robin_dir=robin_dir,
            cloudflow_dir=cloudflow_dir,
            output_path=output_path,
        )

        with zipfile.ZipFile(output_path) as zf:
            deps_str = zf.read("Other/DependenciesFile.json").decode("utf-8")

        deps = json.loads(deps_str)
        assert "Dependencies" in deps
        assert isinstance(deps["Dependencies"], list)


class TestZipSize:
    """Tests for zip file size."""

    def test_zip_size_is_reasonable(
        self,
        packager: SolutionPackager,
        minimal_process: BPProcess,
        robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Test that zip file size is not zero."""
        output_path = tmp_path / "solution.zip"
        packager.package(
            minimal_process,
            robin_dir=robin_dir,
            cloudflow_dir=cloudflow_dir,
            output_path=output_path,
        )

        size_bytes = output_path.stat().st_size
        assert size_bytes > 100  # Should be at least 100 bytes

    def test_zip_is_valid_archive(
        self,
        packager: SolutionPackager,
        minimal_process: BPProcess,
        robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Test that zip file is a valid archive."""
        output_path = tmp_path / "solution.zip"
        packager.package(
            minimal_process,
            robin_dir=robin_dir,
            cloudflow_dir=cloudflow_dir,
            output_path=output_path,
        )

        # Should not raise an exception
        with zipfile.ZipFile(output_path) as zf:
            test_result = zf.testzip()
            # testzip() returns None if all files are OK
            assert test_result is None


class TestEnvironmentVariableDefinitions:
    """Tests for environmentvariabledefinitions/ emission."""

    @pytest.fixture
    def process_with_env_vars(self) -> BPProcess:
        """Return a BPProcess declaring two environment variables."""
        from flowsmith.ast.models import BPEnvironmentVariable

        return BPProcess(
            process_id="test_123",
            name="TestProcess",
            version="1.0",
            pages=[],
            environment_variables=[
                BPEnvironmentVariable(name="Config File", data_type="text", value="a.xlsx"),
                BPEnvironmentVariable(name="Retry Count", data_type="number", value="3"),
            ],
            source_file="test.bprelease",
        )

    def test_env_var_folders_created(
        self,
        packager: SolutionPackager,
        process_with_env_vars: BPProcess,
        robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Each env var gets environmentvariabledefinitions/<schema>/…xml."""
        output_path = tmp_path / "solution.zip"
        packager.package(
            process_with_env_vars,
            robin_dir=robin_dir,
            cloudflow_dir=cloudflow_dir,
            output_path=output_path,
            publisher_prefix="cr3ac",
        )

        with zipfile.ZipFile(output_path) as zf:
            names = zf.namelist()
        assert (
            "environmentvariabledefinitions/cr3ac_Config_File/"
            "environmentvariabledefinition.xml" in names
        )
        assert (
            "environmentvariabledefinitions/cr3ac_Retry_Count/"
            "environmentvariabledefinition.xml" in names
        )

    def test_env_var_xml_content(
        self,
        packager: SolutionPackager,
        process_with_env_vars: BPProcess,
        robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Definition XML carries schemaname, defaultvalue and mapped type code."""
        output_path = tmp_path / "solution.zip"
        packager.package(
            process_with_env_vars,
            robin_dir=robin_dir,
            cloudflow_dir=cloudflow_dir,
            output_path=output_path,
            publisher_prefix="cr3ac",
        )

        with zipfile.ZipFile(output_path) as zf:
            text_var = etree.fromstring(
                zf.read(
                    "environmentvariabledefinitions/cr3ac_Config_File/"
                    "environmentvariabledefinition.xml"
                )
            )
            num_var = etree.fromstring(
                zf.read(
                    "environmentvariabledefinitions/cr3ac_Retry_Count/"
                    "environmentvariabledefinition.xml"
                )
            )

        assert text_var.get("schemaname") == "cr3ac_Config_File"
        assert text_var.findtext("defaultvalue") == "a.xlsx"
        assert text_var.findtext("type") == "100000000"
        assert num_var.findtext("type") == "100000001"

    def test_no_env_vars_no_folder(
        self,
        packager: SolutionPackager,
        minimal_process: BPProcess,
        robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """No env vars → no environmentvariabledefinitions/ entries."""
        output_path = tmp_path / "solution.zip"
        packager.package(
            minimal_process,
            robin_dir=robin_dir,
            cloudflow_dir=cloudflow_dir,
            output_path=output_path,
        )

        with zipfile.ZipFile(output_path) as zf:
            assert not [n for n in zf.namelist() if n.startswith("environmentvariabledefinitions/")]


class TestPublisherPrefix:
    """Tests for publisher prefix customization."""

    def test_custom_publisher_prefix(
        self,
        packager: SolutionPackager,
        minimal_process: BPProcess,
        robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Test that custom publisher_prefix is used."""
        custom_prefix = "mycompany"
        output_path = tmp_path / "solution.zip"
        packager.package(
            minimal_process,
            robin_dir=robin_dir,
            cloudflow_dir=cloudflow_dir,
            output_path=output_path,
            publisher_prefix=custom_prefix,
        )

        with zipfile.ZipFile(output_path) as zf:
            sol_xml = zf.read("solution.xml")

        root = etree.fromstring(sol_xml)
        publisher = root.find(".//{*}Publisher")
        unique_name = publisher.find("{*}UniqueName")
        assert unique_name.text == custom_prefix


class TestMetadataAndClaims:
    """Sub-Task 5 — Metadata JSON flags and Claims derived from annotations."""

    @staticmethod
    def _annotated_stage(
        stage_id: str,
        name: str,
        target_module: str,
        runtime: Runtime,
    ) -> BPStage:
        """Build a single annotated BPStage for use in a page fixture."""
        return BPStage(
            stage_id=stage_id,
            stage_type=StageType.ACTION,
            name=name,
            data_items=[],
            pa_annotation=PAAnnotation(
                target_type=f"{target_module}.Action",
                target_module=target_module,
                runtime=runtime,
                params_map={},
                confidence=0.90,
                band=ConfidenceBand.AUTO,
                flags=[],
            ),
        )

    @pytest.fixture
    def process_with_workqueues(self) -> BPProcess:
        """A single-page process whose only stage targets the WorkQueues module."""
        stage = self._annotated_stage("S1", "Get Next Item", "WorkQueues", Runtime.CLOUD)
        page = BPPage(page_id="P1", name="flow1", stages=[stage], is_main=True, published=True)
        return BPProcess(
            process_id="test_wq",
            name="TestProcessWQ",
            version="1.0",
            pages=[page],
            source_file="test.bprelease",
        )

    @pytest.fixture
    def process_mixed_workqueues(self) -> BPProcess:
        """A page mixing a DESKTOP action with a WorkQueues (CLOUD) action.

        Mirrors the real reference solution, where a desktop .robin flow
        also contains WorkQueues actions annotated CLOUD in the catalogue.
        """
        desktop_stage = self._annotated_stage("S1", "Set Variable", "System", Runtime.DESKTOP)
        wq_stage = self._annotated_stage("S2", "Get Next Item", "WorkQueues", Runtime.CLOUD)
        page = BPPage(
            page_id="P1",
            name="flow1",
            stages=[desktop_stage, wq_stage],
            is_main=True,
            published=True,
        )
        return BPProcess(
            process_id="test_mixed_wq",
            name="TestProcessMixedWQ",
            version="1.0",
            pages=[page],
            source_file="test.bprelease",
        )

    @pytest.fixture
    def process_without_workqueues(self) -> BPProcess:
        """A single-page process with only a DESKTOP action (no WorkQueues)."""
        stage = self._annotated_stage("S1", "Set Variable", "System", Runtime.DESKTOP)
        page = BPPage(page_id="P1", name="flow1", stages=[stage], is_main=True, published=True)
        return BPProcess(
            process_id="test_no_wq",
            name="TestProcessNoWQ",
            version="1.0",
            pages=[page],
            source_file="test.bprelease",
        )

    def test_metadata_flags_workqueues_true_when_stage_present(
        self,
        packager: SolutionPackager,
        process_with_workqueues: BPProcess,
        robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Metadata contains containsActiveWorkQueuesActions:true for a WorkQueues stage."""
        output_path = tmp_path / "solution.zip"
        packager.package(
            process_with_workqueues,
            robin_dir=robin_dir,
            cloudflow_dir=cloudflow_dir,
            output_path=output_path,
        )

        with zipfile.ZipFile(output_path) as zf:
            xml = zf.read("customizations.xml").decode("utf-8")

        assert '"containsActiveWorkQueuesActions":true' in xml

    def test_metadata_flags_workqueues_false_without_workqueues_stage(
        self,
        packager: SolutionPackager,
        process_without_workqueues: BPProcess,
        robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Metadata contains containsActiveWorkQueuesActions:false without WorkQueues stages."""
        output_path = tmp_path / "solution.zip"
        packager.package(
            process_without_workqueues,
            robin_dir=robin_dir,
            cloudflow_dir=cloudflow_dir,
            output_path=output_path,
        )

        with zipfile.ZipFile(output_path) as zf:
            xml = zf.read("customizations.xml").decode("utf-8")

        assert '"containsActiveWorkQueuesActions":false' in xml

    def test_metadata_clientversion_updated(
        self,
        packager: SolutionPackager,
        process_without_workqueues: BPProcess,
        robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Metadata clientversion matches the real reference output."""
        output_path = tmp_path / "solution.zip"
        packager.package(
            process_without_workqueues,
            robin_dir=robin_dir,
            cloudflow_dir=cloudflow_dir,
            output_path=output_path,
        )

        with zipfile.ZipFile(output_path) as zf:
            xml = zf.read("customizations.xml").decode("utf-8")

        assert '"clientversion":"2.69.217.26166"' in xml

    def test_claims_always_include_selfheal(
        self,
        packager: SolutionPackager,
        process_without_workqueues: BPProcess,
        robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Claims array always contains {"name": "selfheal"}."""
        output_path = tmp_path / "solution.zip"
        packager.package(
            process_without_workqueues,
            robin_dir=robin_dir,
            cloudflow_dir=cloudflow_dir,
            output_path=output_path,
        )

        with zipfile.ZipFile(output_path) as zf:
            sol_xml = zf.read("customizations.xml")

        root = etree.fromstring(sol_xml)
        claims_text = root.find(".//{*}Claims").text
        claims = json.loads(claims_text)
        assert {"name": "selfheal"} in claims

    def test_claims_include_workqueues_claim_when_stage_present(
        self,
        packager: SolutionPackager,
        process_with_workqueues: BPProcess,
        robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Claims array includes workqueues.items.get when a WorkQueues stage exists."""
        output_path = tmp_path / "solution.zip"
        packager.package(
            process_with_workqueues,
            robin_dir=robin_dir,
            cloudflow_dir=cloudflow_dir,
            output_path=output_path,
        )

        with zipfile.ZipFile(output_path) as zf:
            sol_xml = zf.read("customizations.xml")

        root = etree.fromstring(sol_xml)
        claims_text = root.find(".//{*}Claims").text
        claims = json.loads(claims_text)
        assert {"name": "selfheal"} in claims
        assert {"name": "workqueues.items.get"} in claims

    def test_claims_deduplicated(
        self,
        packager: SolutionPackager,
        process_with_workqueues: BPProcess,
        robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Claims array contains no duplicate entries."""
        output_path = tmp_path / "solution.zip"
        packager.package(
            process_with_workqueues,
            robin_dir=robin_dir,
            cloudflow_dir=cloudflow_dir,
            output_path=output_path,
        )

        with zipfile.ZipFile(output_path) as zf:
            sol_xml = zf.read("customizations.xml")

        root = etree.fromstring(sol_xml)
        claims_text = root.find(".//{*}Claims").text
        claims = json.loads(claims_text)
        names = [c["name"] for c in claims]
        assert len(names) == len(set(names))

    def test_desktop_only_page_gets_category_6_and_ui_flow_type_2(
        self,
        packager: SolutionPackager,
        process_without_workqueues: BPProcess,
        robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """A DESKTOP-only page is packaged with Category=6 and UIFlowType=2."""
        output_path = tmp_path / "solution.zip"
        packager.package(
            process_without_workqueues,
            robin_dir=robin_dir,
            cloudflow_dir=cloudflow_dir,
            output_path=output_path,
        )

        with zipfile.ZipFile(output_path) as zf:
            sol_xml = zf.read("customizations.xml")

        root = etree.fromstring(sol_xml)
        workflow = root.find(".//{*}Workflow")
        assert workflow.find("{*}Category").text == "6"
        assert workflow.find("{*}UIFlowType").text == "2"

    def test_mixed_desktop_and_workqueues_page_stays_category_6(
        self,
        packager: SolutionPackager,
        process_mixed_workqueues: BPProcess,
        robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """A page mixing DESKTOP and CLOUD (WorkQueues) stages remains a desktop flow."""
        output_path = tmp_path / "solution.zip"
        packager.package(
            process_mixed_workqueues,
            robin_dir=robin_dir,
            cloudflow_dir=cloudflow_dir,
            output_path=output_path,
        )

        with zipfile.ZipFile(output_path) as zf:
            sol_xml = zf.read("customizations.xml")

        root = etree.fromstring(sol_xml)
        workflow = root.find(".//{*}Workflow")
        assert workflow.find("{*}Category").text == "6"
        assert workflow.find("{*}UIFlowType").text == "2"

    def test_all_cloud_page_gets_category_5(
        self,
        packager: SolutionPackager,
        process_with_workqueues: BPProcess,
        robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """A page whose every annotated stage targets CLOUD is Category=5."""
        output_path = tmp_path / "solution.zip"
        packager.package(
            process_with_workqueues,
            robin_dir=robin_dir,
            cloudflow_dir=cloudflow_dir,
            output_path=output_path,
        )

        with zipfile.ZipFile(output_path) as zf:
            sol_xml = zf.read("customizations.xml")

        root = etree.fromstring(sol_xml)
        workflow = root.find(".//{*}Workflow")
        assert workflow.find("{*}Category").text == "5"

    def test_all_cloud_page_omits_ui_flow_type_element(
        self,
        packager: SolutionPackager,
        process_with_workqueues: BPProcess,
        robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """A page whose every annotated stage targets CLOUD has no <UIFlowType> element."""
        output_path = tmp_path / "solution.zip"
        packager.package(
            process_with_workqueues,
            robin_dir=robin_dir,
            cloudflow_dir=cloudflow_dir,
            output_path=output_path,
        )

        with zipfile.ZipFile(output_path) as zf:
            sol_xml = zf.read("customizations.xml")

        root = etree.fromstring(sol_xml)
        workflow = root.find(".//{*}Workflow")
        assert workflow.find("{*}UIFlowType") is None

    def test_desktop_page_has_ui_flow_type_element(
        self,
        packager: SolutionPackager,
        process_without_workqueues: BPProcess,
        robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """A DESKTOP-only page keeps an explicit <UIFlowType>2</UIFlowType>."""
        output_path = tmp_path / "solution.zip"
        packager.package(
            process_without_workqueues,
            robin_dir=robin_dir,
            cloudflow_dir=cloudflow_dir,
            output_path=output_path,
        )

        with zipfile.ZipFile(output_path) as zf:
            sol_xml = zf.read("customizations.xml")

        root = etree.fromstring(sol_xml)
        workflow = root.find(".//{*}Workflow")
        assert workflow.find("{*}UIFlowType").text == "2"

    # -- Sub-Task 6: Managed flag, Publisher expansion, MissingDependencies --

    def test_managed_defaults_to_zero(
        self,
        packager: SolutionPackager,
        minimal_process: BPProcess,
        robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """When managed is not passed, <Managed>0</Managed> is emitted."""
        output_path = tmp_path / "solution.zip"
        packager.package(
            minimal_process,
            robin_dir=robin_dir,
            cloudflow_dir=cloudflow_dir,
            output_path=output_path,
        )

        with zipfile.ZipFile(output_path) as zf:
            sol_xml = zf.read("solution.xml")

        root = etree.fromstring(sol_xml)
        assert root.find(".//{*}Managed").text == "0"

    def test_managed_true_sets_managed_one(
        self,
        packager: SolutionPackager,
        minimal_process: BPProcess,
        robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """When managed=True is requested, <Managed>1</Managed> is emitted."""
        output_path = tmp_path / "solution.zip"
        packager.package(
            minimal_process,
            robin_dir=robin_dir,
            cloudflow_dir=cloudflow_dir,
            output_path=output_path,
            managed=True,
        )

        with zipfile.ZipFile(output_path) as zf:
            sol_xml = zf.read("solution.xml")

        root = etree.fromstring(sol_xml)
        assert root.find(".//{*}Managed").text == "1"

    def test_publisher_has_customization_prefix(
        self,
        packager: SolutionPackager,
        minimal_process: BPProcess,
        robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Publisher block includes a CustomizationPrefix matching publisher_prefix."""
        output_path = tmp_path / "solution.zip"
        packager.package(
            minimal_process,
            robin_dir=robin_dir,
            cloudflow_dir=cloudflow_dir,
            output_path=output_path,
            publisher_prefix="cr3ac",
        )

        with zipfile.ZipFile(output_path) as zf:
            sol_xml = zf.read("solution.xml")

        root = etree.fromstring(sol_xml)
        publisher = root.find(".//{*}Publisher")
        assert publisher.find("{*}CustomizationPrefix").text == "cr3ac"

    def test_no_workqueues_omits_missing_dependencies(
        self,
        packager: SolutionPackager,
        minimal_process: BPProcess,
        robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """No WorkQueues stages anywhere in the process -> no MissingDependencies block."""
        output_path = tmp_path / "solution.zip"
        packager.package(
            minimal_process,
            robin_dir=robin_dir,
            cloudflow_dir=cloudflow_dir,
            output_path=output_path,
        )

        with zipfile.ZipFile(output_path) as zf:
            sol_xml = zf.read("solution.xml")

        root = etree.fromstring(sol_xml)
        assert root.find(".//{*}MissingDependencies") is None

    def test_workqueues_stage_adds_missing_dependencies(
        self,
        packager: SolutionPackager,
        process_with_workqueues: BPProcess,
        robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """A WorkQueues-targeting stage anywhere in the process adds MissingDependencies."""
        output_path = tmp_path / "solution.zip"
        packager.package(
            process_with_workqueues,
            robin_dir=robin_dir,
            cloudflow_dir=cloudflow_dir,
            output_path=output_path,
        )

        with zipfile.ZipFile(output_path) as zf:
            sol_xml = zf.read("solution.xml")

        root = etree.fromstring(sol_xml)
        missing_deps = root.find(".//{*}MissingDependencies")
        assert missing_deps is not None
        required = missing_deps.find(".//{*}Required")
        assert required.get("schemaName") == "workqueueitem"


class TestOrchestratorCloudFlow:
    """Sub-Task 7 — orchestrator CF JSON and desktop flow GUID cross-reference."""

    @pytest.fixture
    def two_desktop_page_process(self) -> BPProcess:
        """A process with two desktop pages (Loader and Performer roles).

        Page names match the .robin filenames created by the `robin_dir`
        fixture so both pages are packaged as Workflow elements. Role
        assignment therefore falls back to page order: flow1 = Loader,
        flow2 = Performer.
        """
        from flowsmith.ast.models import BPEnvironmentVariable

        def page(page_id: str, name: str) -> BPPage:
            stage = BPStage(
                stage_id=f"{page_id}_S1",
                stage_type=StageType.ACTION,
                name="Get Next Item",
                data_items=[],
                pa_annotation=PAAnnotation(
                    target_type="WorkQueues.GetNextItem",
                    target_module="WorkQueues",
                    runtime=Runtime.DESKTOP,
                    params_map={},
                    confidence=0.90,
                    band=ConfidenceBand.AUTO,
                    flags=[],
                ),
            )
            return BPPage(
                page_id=page_id,
                name=name,
                stages=[stage],
                is_main=(page_id == "P1"),
                published=True,
            )

        return BPProcess(
            process_id="test_orch",
            name="TestProcessOrch",
            version="1.0",
            pages=[page("P1", "flow1"), page("P2", "flow2")],
            environment_variables=[
                BPEnvironmentVariable(name="Config File", data_type="text", value="a.xlsx"),
            ],
            source_file="test.bprelease",
        )

    @staticmethod
    def _orchestrator(zip_path: Path) -> dict:
        """Read and parse the orchestrator CF JSON from a packaged solution."""
        with zipfile.ZipFile(zip_path) as zf:
            names = [
                n
                for n in zf.namelist()
                if n.startswith("Workflows/CF_") and n.endswith("_Cloud_Main.json")
            ]
            assert len(names) == 1, f"Expected one orchestrator, got {names}"
            return json.loads(zf.read(names[0]).decode("utf-8"))

    def test_orchestrator_written_to_workflows(
        self,
        packager: SolutionPackager,
        two_desktop_page_process: BPProcess,
        robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """The packaged zip carries an orchestrator CF JSON under Workflows/."""
        output_path = tmp_path / "solution.zip"
        packager.package(
            two_desktop_page_process,
            robin_dir=robin_dir,
            cloudflow_dir=cloudflow_dir,
            output_path=output_path,
            publisher_prefix="cr3ac",
        )

        data = self._orchestrator(output_path)
        assert data["properties"]["definition"]["triggers"]["manual"]["kind"] == "Button"

    def test_orchestrator_connection_references_and_parameters(
        self,
        packager: SolutionPackager,
        two_desktop_page_process: BPProcess,
        robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Orchestrator declares its connections and environment parameters."""
        output_path = tmp_path / "solution.zip"
        packager.package(
            two_desktop_page_process,
            robin_dir=robin_dir,
            cloudflow_dir=cloudflow_dir,
            output_path=output_path,
            publisher_prefix="cr3ac",
        )

        data = self._orchestrator(output_path)
        refs = data["properties"]["connectionReferences"]
        assert "shared_uiflow" in refs
        assert "shared_office365-1" in refs

        params = data["properties"]["definition"]["parameters"]
        assert "Config File (cr3ac_Config_File)" in params

    def test_orchestrator_uiflow_ids_match_customizations_workflow_ids(
        self,
        packager: SolutionPackager,
        two_desktop_page_process: BPProcess,
        robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """uiFlowId values are real generated WorkflowIds, not placeholders."""
        output_path = tmp_path / "solution.zip"
        packager.package(
            two_desktop_page_process,
            robin_dir=robin_dir,
            cloudflow_dir=cloudflow_dir,
            output_path=output_path,
            publisher_prefix="cr3ac",
        )

        data = self._orchestrator(output_path)
        actions = data["properties"]["definition"]["actions"]
        loader_id = actions["Try:_Loader"]["actions"]["If_Loader_flag_=_yes"]["actions"][
            "Desktop_Flow_-_Loader"
        ]["inputs"]["parameters"]["uiFlowId"]
        performer_id = actions["Try:_Performer"]["actions"]["If_Performer_flag_=_yes"]["actions"][
            "If_Work_Queue_Items_present"
        ]["actions"]["Desktop_Flow_-_Performer"]["inputs"]["parameters"]["uiFlowId"]

        with zipfile.ZipFile(output_path) as zf:
            root = etree.fromstring(zf.read("customizations.xml"))
        workflow_ids = {
            wf.get("WorkflowId").strip("{}").lower() for wf in root.findall(".//{*}Workflow")
        }

        assert len(workflow_ids) == 2
        assert loader_id.strip("{}").lower() in workflow_ids
        assert performer_id.strip("{}").lower() in workflow_ids
        assert loader_id != performer_id

    def test_no_desktop_flows_produces_no_orchestrator(
        self,
        packager: SolutionPackager,
        minimal_process: BPProcess,
        robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """A process with no packaged pages emits no orchestrator CF JSON."""
        output_path = tmp_path / "solution.zip"
        packager.package(
            minimal_process,
            robin_dir=robin_dir,
            cloudflow_dir=cloudflow_dir,
            output_path=output_path,
        )

        with zipfile.ZipFile(output_path) as zf:
            names = [n for n in zf.namelist() if n.endswith("_Cloud_Main.json")]
        assert names == []

    def test_connection_references_element_populated(
        self,
        packager: SolutionPackager,
        two_desktop_page_process: BPProcess,
        robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """<ConnectionReferences> is derived from stage modules, not left empty."""
        output_path = tmp_path / "solution.zip"
        packager.package(
            two_desktop_page_process,
            robin_dir=robin_dir,
            cloudflow_dir=cloudflow_dir,
            output_path=output_path,
            publisher_prefix="cr3ac",
        )

        with zipfile.ZipFile(output_path) as zf:
            root = etree.fromstring(zf.read("customizations.xml"))

        element = root.find(".//{*}ConnectionReferences")
        assert element is not None
        refs = json.loads(element.text)
        assert any(
            r["connectionReferenceLogicalName"].startswith("cr3ac_sharedcommondataserviceforapps")
            for r in refs
        )


class TestXmlEscaping:
    """Regression tests — embedded PAD script must not break XML well-formedness."""

    # Verbatim from samples/blueprism/PID_0171.bprelease (CheckInstanceAndWorkbook
    # Code stage). The `<>` inequality opened a bogus element before the fix.
    VBSCRIPT_SNIPPET = 'If ex.Message.IndexOf("DISP_E_BADINDEX")<>-1 Then'

    @pytest.fixture
    def hostile_robin_dir(self, tmp_path: Path) -> Path:
        """A .robin directory whose script contains raw <, > and & characters."""
        robin_path = tmp_path / "robin_hostile"
        robin_path.mkdir(parents=True, exist_ok=True)
        (robin_path / "flow1.robin").write_text(
            "# Narrative: compare A & B, then <check> the result\n"
            f"    {self.VBSCRIPT_SNIPPET}\n"
            "    If a < b And c > d Then\n",
            encoding="utf-8",
        )
        return robin_path

    @pytest.fixture
    def hostile_process(self) -> BPProcess:
        """A one-page process whose page name also contains XML metacharacters."""
        stage = BPStage(
            stage_id="S1",
            stage_type=StageType.CODE,
            name="Check <Instance> & Workbook",
            data_items=[],
            code_text=TestXmlEscaping.VBSCRIPT_SNIPPET,
            pa_annotation=PAAnnotation(
                target_type="Scripting.RunVBScript",
                target_module="Scripting",
                runtime=Runtime.DESKTOP,
                params_map={},
                confidence=0.40,
                band=ConfidenceBand.MANUAL,
                flags=[],
            ),
        )
        return BPProcess(
            process_id="test_escape",
            name="TestEscape",
            version="1.0",
            pages=[BPPage(page_id="P1", name="flow1", stages=[stage], is_main=True)],
            source_file="test.bprelease",
        )

    def test_customizations_xml_parses_with_hostile_definition(
        self,
        packager: SolutionPackager,
        hostile_process: BPProcess,
        hostile_robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """customizations.xml stays well-formed when the script contains `<>`."""
        output_path = tmp_path / "solution.zip"
        packager.package(
            hostile_process,
            robin_dir=hostile_robin_dir,
            cloudflow_dir=cloudflow_dir,
            output_path=output_path,
        )

        with zipfile.ZipFile(output_path) as zf:
            root = etree.fromstring(zf.read("customizations.xml"))

        assert root is not None

    def test_definition_round_trips_to_original_script(
        self,
        packager: SolutionPackager,
        hostile_process: BPProcess,
        hostile_robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """The escaped Definition parses back to the exact PAD script."""
        output_path = tmp_path / "solution.zip"
        packager.package(
            hostile_process,
            robin_dir=hostile_robin_dir,
            cloudflow_dir=cloudflow_dir,
            output_path=output_path,
        )

        with zipfile.ZipFile(output_path) as zf:
            root = etree.fromstring(zf.read("customizations.xml"))

        definition = root.find(".//{*}Definition")
        assert definition is not None
        script = json.loads(definition.text)
        assert self.VBSCRIPT_SNIPPET in script
        assert "compare A & B, then <check> the result" in script

    def test_workflow_name_attribute_is_escaped(
        self,
        packager: SolutionPackager,
        hostile_process: BPProcess,
        hostile_robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """A page name containing `&` survives as an XML attribute value."""
        hostile_process.pages[0].stages[0].pa_annotation = None
        output_path = tmp_path / "solution.zip"
        packager.package(
            hostile_process,
            robin_dir=hostile_robin_dir,
            cloudflow_dir=cloudflow_dir,
            output_path=output_path,
        )

        with zipfile.ZipFile(output_path) as zf:
            root = etree.fromstring(zf.read("customizations.xml"))

        workflow = root.find(".//{*}Workflow")
        assert workflow is not None
        assert workflow.get("Name") == "flow1"


class TestDefinitionJsonEncoding:
    """Regression tests — <Definition> must hold a valid JSON string literal."""

    @pytest.fixture
    def tabbed_robin_dir(self, tmp_path: Path) -> Path:
        """A .robin directory whose script is tab-indented, as PADGenerator emits."""
        robin_path = tmp_path / "robin_tabbed"
        robin_path.mkdir(parents=True, exist_ok=True)
        (robin_path / "flow1.robin").write_text(
            "BLOCK 'Main'\n\tSET txt_A TO $'''café'''\n\tIf a <> b Then\nEND\n",
            encoding="utf-8",
        )
        return robin_path

    @pytest.fixture
    def tabbed_process(self) -> BPProcess:
        """A one-page process matching the tabbed_robin_dir filename."""
        return BPProcess(
            process_id="test_json",
            name="TestJson",
            version="1.0",
            pages=[BPPage(page_id="P1", name="flow1", stages=[], is_main=True)],
            source_file="test.bprelease",
        )

    def _definition(
        self,
        packager: SolutionPackager,
        process: BPProcess,
        robin_dir_: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> str:
        """Package the process and return the raw <Definition> text."""
        output_path = tmp_path / "solution.zip"
        packager.package(
            process,
            robin_dir=robin_dir_,
            cloudflow_dir=cloudflow_dir,
            output_path=output_path,
        )
        with zipfile.ZipFile(output_path) as zf:
            root = etree.fromstring(zf.read("customizations.xml"))
        definition = root.find(".//{*}Definition")
        assert definition is not None
        assert definition.text is not None
        return definition.text

    def test_tab_indented_script_yields_parseable_json(
        self,
        packager: SolutionPackager,
        tabbed_process: BPProcess,
        tabbed_robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Tabs are escaped, so json.loads() on <Definition> succeeds."""
        text = self._definition(packager, tabbed_process, tabbed_robin_dir, cloudflow_dir, tmp_path)
        script = json.loads(text)
        assert "\tSET txt_A" in script

    def test_line_endings_normalised_to_crlf(
        self,
        packager: SolutionPackager,
        tabbed_process: BPProcess,
        tabbed_robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Decoded script uses CRLF line endings, matching the reference."""
        text = self._definition(packager, tabbed_process, tabbed_robin_dir, cloudflow_dir, tmp_path)
        script = json.loads(text)
        assert "\r\n" in script
        assert "\n" not in script.replace("\r\n", "")

    def test_non_ascii_kept_literal(
        self,
        packager: SolutionPackager,
        tabbed_process: BPProcess,
        tabbed_robin_dir: Path,
        cloudflow_dir: Path,
        tmp_path: Path,
    ) -> None:
        r"""Non-ASCII characters are not \uXXXX-escaped, matching the reference."""
        text = self._definition(packager, tabbed_process, tabbed_robin_dir, cloudflow_dir, tmp_path)
        assert r"\u00e9" not in text
        assert json.loads(text).count("café") == 1
