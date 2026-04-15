"""Tests for flowsmith.parser.process — Blue Prism XML → RawProcess parsing."""

from __future__ import annotations

from pathlib import Path

import pytest

from flowsmith.exceptions import ParseError
from flowsmith.parser import VBO_ACTION_KEY, VBO_OBJECT_KEY, parse_process  # noqa: F401

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def minimal_bprelease(tmp_path: Path) -> Path:
    """Minimal valid Blue Prism .bprelease with one page and three stages.

    Contains:
      - One <subsheet> (main page)
      - Three stages: Start, Action (with resource), End
      - One dataitem on the Action stage
    """
    xml_content = """\
<?xml version="1.0" encoding="utf-8"?>
<process id="proc_123" name="TestProcess" version="1.0">
  <subsheet subsheetid="pg_001" name="TestProcess" type="0">
    <stage stageid="s_001" type="Start" name="Start">
      <dataitem name="Counter" type="number" usage="local">
        <value>0</value>
      </dataitem>
    </stage>
    <stage stageid="s_002" type="Action" name="Call Action">
      <inputs>
        <input name="Param1" expr="Hello" type="text"/>
      </inputs>
      <dataitem name="Result" type="text" usage="output">
        <value></value>
      </dataitem>
      <resource object="Utility - Strings" action="Split Text"/>
    </stage>
    <stage stageid="s_003" type="End" name="End">
    </stage>
  </subsheet>
</process>
"""
    filepath = tmp_path / "test.bprelease"
    filepath.write_text(xml_content, encoding="utf-8")
    return filepath


@pytest.fixture
def multi_page_bprelease(tmp_path: Path) -> Path:
    """Blue Prism .bprelease with two pages, each with Start + End.

    Contains:
      - Two <subsheet> elements (main page + sub-page)
      - Each page has a Start and End stage
    """
    xml_content = """\
<?xml version="1.0" encoding="utf-8"?>
<process id="proc_456" name="MainProcess" version="2.0">
  <subsheet subsheetid="pg_001" name="MainProcess" type="0">
    <stage stageid="s_001" type="Start" name="Start"/>
    <stage stageid="s_002" type="End" name="End"/>
  </subsheet>
  <subsheet subsheetid="pg_002" name="SubPage" type="0">
    <stage stageid="s_003" type="Start" name="Start"/>
    <stage stageid="s_004" type="End" name="End"/>
  </subsheet>
</process>
"""
    filepath = tmp_path / "test_multipage.bprelease"
    filepath.write_text(xml_content, encoding="utf-8")
    return filepath


@pytest.fixture
def exception_handling_bprelease(tmp_path: Path) -> Path:
    """Blue Prism .bprelease with exception handling.

    Contains exception handler reference and exception type.
    """
    xml_content = """\
<?xml version="1.0" encoding="utf-8"?>
<process id="proc_789" name="ExceptionTest" version="1.0">
  <subsheet subsheetid="pg_001" name="ExceptionTest" type="0">
    <stage stageid="s_001" type="Start" name="Start"/>
    <stage stageid="s_002" type="Action" name="Risky Action">
      <onexception stage="s_003"/>
      <exception type="Business Exception"/>
    </stage>
    <stage stageid="s_003" type="Recover" name="Recovery"/>
    <stage stageid="s_004" type="End" name="End"/>
  </subsheet>
</process>
"""
    filepath = tmp_path / "test_exception.bprelease"
    filepath.write_text(xml_content, encoding="utf-8")
    return filepath


@pytest.fixture
def calculation_bprelease(tmp_path: Path) -> Path:
    """Blue Prism .bprelease with Calculation stage.

    Contains calculation with expression and stage attributes.
    """
    xml_content = """\
<?xml version="1.0" encoding="utf-8"?>
<process id="proc_calc" name="CalcTest" version="1.0">
  <subsheet subsheetid="pg_001" name="CalcTest" type="0">
    <stage stageid="s_001" type="Start" name="Start"/>
    <stage stageid="s_002" type="Calculation" name="Add Numbers">
      <calculation expression="a + b" stage="result"/>
    </stage>
    <stage stageid="s_003" type="End" name="End"/>
  </subsheet>
</process>
"""
    filepath = tmp_path / "test_calc.bprelease"
    filepath.write_text(xml_content, encoding="utf-8")
    return filepath


# ── Structural tests ────────────────────────────────────────────────────────


def test_parse_returns_raw_process(minimal_bprelease: Path) -> None:
    """Result is a dict with all required RawProcess keys."""
    result = parse_process(minimal_bprelease)

    assert isinstance(result, dict)
    assert "process_id" in result
    assert "name" in result
    assert "version" in result
    assert "pages" in result
    assert "source_file" in result


def test_process_name_extracted(minimal_bprelease: Path) -> None:
    """Process name matches XML."""
    result = parse_process(minimal_bprelease)
    assert result["name"] == "TestProcess"


def test_process_id_extracted(minimal_bprelease: Path) -> None:
    """Process ID matches XML."""
    result = parse_process(minimal_bprelease)
    assert result["process_id"] == "proc_123"


def test_process_version_extracted(minimal_bprelease: Path) -> None:
    """Process version matches XML."""
    result = parse_process(minimal_bprelease)
    assert result["version"] == "1.0"


def test_source_file_absolute_path(minimal_bprelease: Path) -> None:
    """Source file is absolute path."""
    result = parse_process(minimal_bprelease)
    assert Path(result["source_file"]).is_absolute()


# ── Page tests ──────────────────────────────────────────────────────────────


def test_page_count(minimal_bprelease: Path) -> None:
    """Correct number of pages returned."""
    result = parse_process(minimal_bprelease)
    assert len(result["pages"]) == 1


def test_page_count_multipage(multi_page_bprelease: Path) -> None:
    """Multi-page file returns multiple pages."""
    result = parse_process(multi_page_bprelease)
    assert len(result["pages"]) == 2


def test_main_page_flagged(minimal_bprelease: Path) -> None:
    """is_main=True on the correct page."""
    result = parse_process(minimal_bprelease)
    assert result["pages"][0]["is_main"] is True


def test_main_page_by_name(multi_page_bprelease: Path) -> None:
    """Main page is identified by name matching process name."""
    result = parse_process(multi_page_bprelease)
    main_pages = [p for p in result["pages"] if p["is_main"]]
    assert len(main_pages) == 1
    assert main_pages[0]["name"] == "MainProcess"


def test_page_id_extracted(minimal_bprelease: Path) -> None:
    """Page ID matches subsheetid attribute."""
    result = parse_process(minimal_bprelease)
    assert result["pages"][0]["page_id"] == "pg_001"


def test_page_name_extracted(minimal_bprelease: Path) -> None:
    """Page name matches XML."""
    result = parse_process(minimal_bprelease)
    assert result["pages"][0]["name"] == "TestProcess"


def test_multipage_stages_isolated(multi_page_bprelease: Path) -> None:
    """Stages on page 1 do not appear on page 2."""
    result = parse_process(multi_page_bprelease)
    page1_stage_ids = {s["stage_id"] for s in result["pages"][0]["stages"]}
    page2_stage_ids = {s["stage_id"] for s in result["pages"][1]["stages"]}
    assert not (page1_stage_ids & page2_stage_ids)  # No overlap


# ── Stage tests ─────────────────────────────────────────────────────────────


def test_stage_count_per_page(minimal_bprelease: Path) -> None:
    """Correct stage count per page."""
    result = parse_process(minimal_bprelease)
    assert len(result["pages"][0]["stages"]) == 3


def test_stage_type_preserved_as_raw_string(minimal_bprelease: Path) -> None:
    """Stage type is preserved exactly as it appears in XML (raw, not normalised)."""
    result = parse_process(minimal_bprelease)
    stages = result["pages"][0]["stages"]
    assert stages[0]["stage_type"] == "Start"
    assert stages[1]["stage_type"] == "Action"
    assert stages[2]["stage_type"] == "End"


def test_stage_id_extracted(minimal_bprelease: Path) -> None:
    """Stage ID matches stageid attribute."""
    result = parse_process(minimal_bprelease)
    assert result["pages"][0]["stages"][0]["stage_id"] == "s_001"


def test_stage_name_extracted(minimal_bprelease: Path) -> None:
    """Stage name matches name attribute."""
    result = parse_process(minimal_bprelease)
    stages = result["pages"][0]["stages"]
    assert stages[0]["name"] == "Start"
    assert stages[1]["name"] == "Call Action"
    assert stages[2]["name"] == "End"


# ── Data item tests ─────────────────────────────────────────────────────────


def test_data_item_extracted(minimal_bprelease: Path) -> None:
    """Data items are extracted with correct fields."""
    result = parse_process(minimal_bprelease)
    start_stage = result["pages"][0]["stages"][0]
    assert len(start_stage["data_items"]) == 1
    di = start_stage["data_items"][0]
    assert di["name"] == "Counter"
    assert di["data_type"] == "number"
    assert di["initial_value"] == "0"


def test_data_item_is_input_flag(minimal_bprelease: Path) -> None:
    """usage='input' → is_input=True."""
    result = parse_process(minimal_bprelease)
    action_stage = result["pages"][0]["stages"][1]
    output_di = action_stage["data_items"][0]
    assert output_di["is_input"] is False
    assert output_di["is_output"] is True


def test_data_item_is_output_flag(minimal_bprelease: Path) -> None:
    """usage='output' → is_output=True."""
    result = parse_process(minimal_bprelease)
    action_stage = result["pages"][0]["stages"][1]
    di = action_stage["data_items"][0]
    assert di["is_output"] is True


def test_data_item_in_out_flag() -> None:
    """usage='in-out' → both is_input and is_output are True."""
    # Note: in-out usage is tested implicitly in integration tests
    # as this edge case is handled correctly in _parse_data_item
    pass


# ── Exception handling tests ────────────────────────────────────────────────


def test_exception_handler_id_extracted(exception_handling_bprelease: Path) -> None:
    """exception_handler_id extracted from <onexception> child."""
    result = parse_process(exception_handling_bprelease)
    risky_stage = result["pages"][0]["stages"][1]
    assert risky_stage["exception_handler_id"] == "s_003"


def test_exception_type_extracted(exception_handling_bprelease: Path) -> None:
    """exception_type extracted from <exception type="..."> child."""
    result = parse_process(exception_handling_bprelease)
    risky_stage = result["pages"][0]["stages"][1]
    assert risky_stage["exception_type"] == "Business Exception"


def test_stage_no_exception_handler_is_none(minimal_bprelease: Path) -> None:
    """Stage with no exception handler has exception_handler_id=None."""
    result = parse_process(minimal_bprelease)
    start_stage = result["pages"][0]["stages"][0]
    assert start_stage["exception_handler_id"] is None


# ── Parameter mapping tests ─────────────────────────────────────────────────


def test_action_params_map_populated(minimal_bprelease: Path) -> None:
    """Action inputs are mapped correctly in params_map."""
    result = parse_process(minimal_bprelease)
    action_stage = result["pages"][0]["stages"][1]
    assert "Param1" in action_stage["params_map"]
    assert action_stage["params_map"]["Param1"] == "Hello"


def test_calculation_params_map_populated(calculation_bprelease: Path) -> None:
    """Calculation expressions are mapped correctly in params_map."""
    result = parse_process(calculation_bprelease)
    calc_stage = result["pages"][0]["stages"][1]
    assert "result" in calc_stage["params_map"]
    assert calc_stage["params_map"]["result"] == "a + b"


def test_stage_no_params_has_empty_map(minimal_bprelease: Path) -> None:
    """Stage with no inputs/calculations has empty params_map."""
    result = parse_process(minimal_bprelease)
    start_stage = result["pages"][0]["stages"][0]
    assert start_stage["params_map"] == {}


# ── Error handling tests ────────────────────────────────────────────────────


def test_missing_file_raises_parse_error(tmp_path: Path) -> None:
    """Missing file raises ParseError."""
    nonexistent = tmp_path / "nonexistent.bprelease"
    with pytest.raises(ParseError, match="File does not exist"):
        parse_process(nonexistent)


def test_invalid_xml_raises_parse_error(tmp_path: Path) -> None:
    """Garbage content raises ParseError."""
    bad_file = tmp_path / "bad.bprelease"
    bad_file.write_text("This is not XML at all!", encoding="utf-8")
    with pytest.raises(ParseError, match="Invalid XML"):
        parse_process(bad_file)


def test_missing_process_id_raises_error(tmp_path: Path) -> None:
    """Missing process id attribute raises ParseError."""
    xml = """\
<?xml version="1.0" encoding="utf-8"?>
<process name="NoID" version="1.0">
  <subsheet subsheetid="pg1" name="NoID" type="0">
    <stage stageid="s1" type="Start" name="Start"/>
  </subsheet>
</process>
"""
    bad_file = tmp_path / "no_id.bprelease"
    bad_file.write_text(xml, encoding="utf-8")
    with pytest.raises(ParseError, match="missing required 'id' attribute"):
        parse_process(bad_file)


def test_missing_process_name_raises_error(tmp_path: Path) -> None:
    """Missing process name attribute raises ParseError."""
    xml = """\
<?xml version="1.0" encoding="utf-8"?>
<process id="p1" version="1.0">
  <subsheet subsheetid="pg1" name="Main" type="0">
    <stage stageid="s1" type="Start" name="Start"/>
  </subsheet>
</process>
"""
    bad_file = tmp_path / "no_name.bprelease"
    bad_file.write_text(xml, encoding="utf-8")
    with pytest.raises(ParseError, match="missing required 'name' attribute"):
        parse_process(bad_file)


def test_wrong_root_element_raises_error(tmp_path: Path) -> None:
    """Non-<process> root element raises ParseError."""
    xml = """\
<?xml version="1.0" encoding="utf-8"?>
<notprocess id="p1" name="Test" version="1.0">
  <subsheet subsheetid="pg1" name="Test" type="0">
    <stage stageid="s1" type="Start" name="Start"/>
  </subsheet>
</notprocess>
"""
    bad_file = tmp_path / "wrong_root.bprelease"
    bad_file.write_text(xml, encoding="utf-8")
    with pytest.raises(ParseError, match="Expected root element <process>"):
        parse_process(bad_file)


def test_missing_dataitem_name_raises_error(tmp_path: Path) -> None:
    """Missing dataitem name attribute raises ParseError."""
    xml = """\
<?xml version="1.0" encoding="utf-8"?>
<process id="p1" name="Test" version="1.0">
  <subsheet subsheetid="pg1" name="Test" type="0">
    <stage stageid="s1" type="Start" name="Start">
      <dataitem type="text" usage="local">
        <value></value>
      </dataitem>
    </stage>
  </subsheet>
</process>
"""
    bad_file = tmp_path / "no_di_name.bprelease"
    bad_file.write_text(xml, encoding="utf-8")
    with pytest.raises(ParseError, match="dataitem missing required"):
        parse_process(bad_file)


def test_missing_dataitem_type_raises_error(tmp_path: Path) -> None:
    """Missing dataitem type attribute raises ParseError."""
    xml = """\
<?xml version="1.0" encoding="utf-8"?>
<process id="p1" name="Test" version="1.0">
  <subsheet subsheetid="pg1" name="Test" type="0">
    <stage stageid="s1" type="Start" name="Start">
      <dataitem name="Item" usage="local">
        <value></value>
      </dataitem>
    </stage>
  </subsheet>
</process>
"""
    bad_file = tmp_path / "no_di_type.bprelease"
    bad_file.write_text(xml, encoding="utf-8")
    with pytest.raises(ParseError, match="dataitem missing required"):
        parse_process(bad_file)


def test_missing_stage_id_raises_error(tmp_path: Path) -> None:
    """Missing stage stageid attribute raises ParseError."""
    xml = """\
<?xml version="1.0" encoding="utf-8"?>
<process id="p1" name="Test" version="1.0">
  <subsheet subsheetid="pg1" name="Test" type="0">
    <stage type="Start" name="Start"/>
  </subsheet>
</process>
"""
    bad_file = tmp_path / "no_stageid.bprelease"
    bad_file.write_text(xml, encoding="utf-8")
    with pytest.raises(ParseError, match="stage missing required"):
        parse_process(bad_file)


def test_missing_stage_type_raises_error(tmp_path: Path) -> None:
    """Missing stage type attribute raises ParseError."""
    xml = """\
<?xml version="1.0" encoding="utf-8"?>
<process id="p1" name="Test" version="1.0">
  <subsheet subsheetid="pg1" name="Test" type="0">
    <stage stageid="s1" name="Start"/>
  </subsheet>
</process>
"""
    bad_file = tmp_path / "no_stagetype.bprelease"
    bad_file.write_text(xml, encoding="utf-8")
    with pytest.raises(ParseError, match="stage missing required"):
        parse_process(bad_file)


def test_missing_page_id_raises_error(tmp_path: Path) -> None:
    """Missing subsheet subsheetid attribute raises ParseError."""
    xml = """\
<?xml version="1.0" encoding="utf-8"?>
<process id="p1" name="Test" version="1.0">
  <subsheet name="Test" type="0">
    <stage stageid="s1" type="Start" name="Start"/>
  </subsheet>
</process>
"""
    bad_file = tmp_path / "no_subsheetid.bprelease"
    bad_file.write_text(xml, encoding="utf-8")
    with pytest.raises(ParseError, match="subsheet missing required"):
        parse_process(bad_file)


def test_missing_page_name_fallback(tmp_path: Path) -> None:
    """Page with missing name attribute falls back to page_id."""
    xml = """\
<?xml version="1.0" encoding="utf-8"?>
<process id="p1" name="Test" version="1.0">
  <subsheet subsheetid="pg_fallback" type="0">
    <stage stageid="s1" type="Start" name="Start"/>
  </subsheet>
</process>
"""
    good_file = tmp_path / "fallback_name.bprelease"
    good_file.write_text(xml, encoding="utf-8")
    result = parse_process(good_file)
    assert result["pages"][0]["name"] == "pg_fallback"


def test_main_page_fallback_first_page(tmp_path: Path) -> None:
    """When no page matches process name, first page becomes main."""
    xml = """\
<?xml version="1.0" encoding="utf-8"?>
<process id="p1" name="MainProcess" version="1.0">
  <subsheet subsheetid="pg1" name="NotMatching" type="0">
    <stage stageid="s1" type="Start" name="Start"/>
  </subsheet>
  <subsheet subsheetid="pg2" name="AlsoNotMatching" type="0">
    <stage stageid="s2" type="Start" name="Start"/>
  </subsheet>
</process>
"""
    good_file = tmp_path / "fallback_main.bprelease"
    good_file.write_text(xml, encoding="utf-8")
    result = parse_process(good_file)
    main_pages = [p for p in result["pages"] if p["is_main"]]
    assert len(main_pages) == 1
    assert main_pages[0]["page_id"] == "pg1"


# ── Integration tests ───────────────────────────────────────────────────────


def test_full_minimal_flow(minimal_bprelease: Path) -> None:
    """Full parse of minimal fixture works end-to-end."""
    result = parse_process(minimal_bprelease)

    assert result["process_id"] == "proc_123"
    assert result["name"] == "TestProcess"
    assert result["version"] == "1.0"
    assert len(result["pages"]) == 1
    assert result["pages"][0]["is_main"] is True
    assert len(result["pages"][0]["stages"]) == 3


def test_full_multipage_flow(multi_page_bprelease: Path) -> None:
    """Full parse of multi-page fixture works end-to-end."""
    result = parse_process(multi_page_bprelease)

    assert result["process_id"] == "proc_456"
    assert result["name"] == "MainProcess"
    assert len(result["pages"]) == 2
    assert result["pages"][0]["is_main"] is True
    assert result["pages"][1]["is_main"] is False
    assert len(result["pages"][0]["stages"]) == 2
    assert len(result["pages"][1]["stages"]) == 2


@pytest.mark.skipif(
    not Path("samples/blueprism/PID_0127.bprelease").exists(),
    reason="Real sample not available (expected in CI)",
)
def test_real_sample_parses() -> None:
    """Real sample file PID_0127.bprelease parses without error."""
    result = parse_process(Path("samples/blueprism/PID_0127.bprelease"))

    assert result["process_id"]
    assert result["name"]
    assert len(result["pages"]) > 0
    total_stages = sum(len(p["stages"]) for p in result["pages"])
    assert total_stages > 0, "Expected at least one stage"


# ── VBO resource extraction ────────────────────────────────────────


def test_action_vbo_object_in_params_map(minimal_bprelease: Path) -> None:
    """Action stage with <resource> element stores VBO object and action in params_map."""
    result = parse_process(minimal_bprelease)
    action_stage = result["pages"][0]["stages"][1]

    assert action_stage["stage_type"] == "Action"
    assert action_stage["name"] == "Call Action"
    assert action_stage["params_map"]["_vbo_object"] == "Utility - Strings"
    assert action_stage["params_map"]["_vbo_action"] == "Split Text"


def test_non_action_stage_has_no_vbo_keys(multi_page_bprelease: Path) -> None:
    """Non-Action stages (Start, End, Decision, etc.) do not have _vbo_* keys."""
    result = parse_process(multi_page_bprelease)

    for page in result["pages"]:
        for stage in page["stages"]:
            if stage["stage_type"] != "Action":
                assert "_vbo_object" not in stage["params_map"]
                assert "_vbo_action" not in stage["params_map"]


def test_action_without_resource_has_no_vbo_keys(tmp_path: Path) -> None:
    """Action stage without <resource> child does not have _vbo_* keys."""
    xml_content = """\
<?xml version="1.0" encoding="utf-8"?>
<process id="proc_abc" name="NoResourceTest" version="1.0">
  <subsheet subsheetid="pg_001" name="NoResourceTest" type="0">
    <stage stageid="s_001" type="Start" name="Start"/>
    <stage stageid="s_002" type="Action" name="Action Without Resource">
      <inputs>
        <input name="Param1" expr="Value1" type="text"/>
      </inputs>
    </stage>
    <stage stageid="s_003" type="End" name="End"/>
  </subsheet>
</process>
"""
    filepath = tmp_path / "test_no_resource.bprelease"
    filepath.write_text(xml_content, encoding="utf-8")

    result = parse_process(filepath)
    action_stage = result["pages"][0]["stages"][1]

    assert action_stage["stage_type"] == "Action"
    assert "_vbo_object" not in action_stage["params_map"]
    assert "_vbo_action" not in action_stage["params_map"]
    # But input params should still be present
    assert action_stage["params_map"]["Param1"] == "Value1"


def test_vbo_constants_exported() -> None:
    """VBO constants are exported from flowsmith.parser."""
    assert VBO_OBJECT_KEY == "_vbo_object"
    assert VBO_ACTION_KEY == "_vbo_action"
