"""Tests for the Solution Packager."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from lxml import etree

from flowsmith.ast.models import BPProcess
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
        """Test that all .robin files appear in Workflows/."""
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

            assert len(robin_files) == 3
            assert all("DesktopFlows/" in n for n in robin_files)

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
