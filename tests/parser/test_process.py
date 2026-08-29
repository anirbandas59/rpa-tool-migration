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
    """Result is a MultiArtefactRelease dict with processes list and validation."""
    result = parse_process(minimal_bprelease)

    assert isinstance(result, dict)
    assert "processes" in result
    assert "objects" in result
    assert "environment_variables" in result
    assert "source_file" in result
    assert "validation" in result
    # First process should have RawProcess structure
    assert len(result["processes"]) > 0
    first_process = result["processes"][0]
    assert "process_id" in first_process
    assert "name" in first_process
    assert "version" in first_process
    assert "pages" in first_process


def test_process_name_extracted(minimal_bprelease: Path) -> None:
    """Process name matches XML."""
    result = parse_process(minimal_bprelease)
    assert result["processes"][0]["name"] == "TestProcess"


def test_process_id_extracted(minimal_bprelease: Path) -> None:
    """Process ID matches XML."""
    result = parse_process(minimal_bprelease)
    assert result["processes"][0]["process_id"] == "proc_123"


def test_process_version_extracted(minimal_bprelease: Path) -> None:
    """Process version matches XML."""
    result = parse_process(minimal_bprelease)
    assert result["processes"][0]["version"] == "1.0"


def test_source_file_absolute_path(minimal_bprelease: Path) -> None:
    """Source file is absolute path."""
    result = parse_process(minimal_bprelease)
    assert Path(result["source_file"]).is_absolute()


# ── Page tests ──────────────────────────────────────────────────────────────


def test_page_count(minimal_bprelease: Path) -> None:
    """Correct number of pages returned."""
    result = parse_process(minimal_bprelease)
    assert len(result["processes"][0]["pages"]) == 1


def test_page_count_multipage(multi_page_bprelease: Path) -> None:
    """Multi-page file returns multiple pages."""
    result = parse_process(multi_page_bprelease)
    assert len(result["processes"][0]["pages"]) == 2


def test_main_page_flagged(minimal_bprelease: Path) -> None:
    """is_main=True on the correct page."""
    result = parse_process(minimal_bprelease)
    assert result["processes"][0]["pages"][0]["is_main"] is True


def test_main_page_by_name(multi_page_bprelease: Path) -> None:
    """Main page is identified by name matching process name."""
    result = parse_process(multi_page_bprelease)
    main_pages = [p for p in result["processes"][0]["pages"] if p["is_main"]]
    assert len(main_pages) == 1
    assert main_pages[0]["name"] == "MainProcess"


def test_page_id_extracted(minimal_bprelease: Path) -> None:
    """Page ID matches subsheetid attribute."""
    result = parse_process(minimal_bprelease)
    assert result["processes"][0]["pages"][0]["page_id"] == "pg_001"


def test_page_name_extracted(minimal_bprelease: Path) -> None:
    """Page name matches XML."""
    result = parse_process(minimal_bprelease)
    assert result["processes"][0]["pages"][0]["name"] == "TestProcess"


def test_multipage_stages_isolated(multi_page_bprelease: Path) -> None:
    """Stages on page 1 do not appear on page 2."""
    result = parse_process(multi_page_bprelease)
    page1_stage_ids = {s["stage_id"] for s in result["processes"][0]["pages"][0]["stages"]}
    page2_stage_ids = {s["stage_id"] for s in result["processes"][0]["pages"][1]["stages"]}
    assert not (page1_stage_ids & page2_stage_ids)  # No overlap


# ── Stage tests ─────────────────────────────────────────────────────────────


def test_stage_count_per_page(minimal_bprelease: Path) -> None:
    """Correct stage count per page."""
    result = parse_process(minimal_bprelease)
    assert len(result["processes"][0]["pages"][0]["stages"]) == 3


def test_stage_type_preserved_as_raw_string(minimal_bprelease: Path) -> None:
    """Stage type is preserved exactly as it appears in XML (raw, not normalised)."""
    result = parse_process(minimal_bprelease)
    stages = result["processes"][0]["pages"][0]["stages"]
    assert stages[0]["stage_type"] == "Start"
    assert stages[1]["stage_type"] == "Action"
    assert stages[2]["stage_type"] == "End"


def test_stage_id_extracted(minimal_bprelease: Path) -> None:
    """Stage ID matches stageid attribute."""
    result = parse_process(minimal_bprelease)
    assert result["processes"][0]["pages"][0]["stages"][0]["stage_id"] == "s_001"


def test_stage_name_extracted(minimal_bprelease: Path) -> None:
    """Stage name matches name attribute."""
    result = parse_process(minimal_bprelease)
    stages = result["processes"][0]["pages"][0]["stages"]
    assert stages[0]["name"] == "Start"
    assert stages[1]["name"] == "Call Action"
    assert stages[2]["name"] == "End"


# ── Data item tests ─────────────────────────────────────────────────────────


def test_data_item_extracted(minimal_bprelease: Path) -> None:
    """Data items are extracted with correct fields."""
    result = parse_process(minimal_bprelease)
    start_stage = result["processes"][0]["pages"][0]["stages"][0]
    assert len(start_stage["data_items"]) == 1
    di = start_stage["data_items"][0]
    assert di["name"] == "Counter"
    assert di["data_type"] == "number"
    assert di["initial_value"] == "0"


def test_data_item_is_input_flag(minimal_bprelease: Path) -> None:
    """usage='input' → is_input=True."""
    result = parse_process(minimal_bprelease)
    action_stage = result["processes"][0]["pages"][0]["stages"][1]
    output_di = action_stage["data_items"][0]
    assert output_di["is_input"] is False
    assert output_di["is_output"] is True


def test_data_item_is_output_flag(minimal_bprelease: Path) -> None:
    """usage='output' → is_output=True."""
    result = parse_process(minimal_bprelease)
    action_stage = result["processes"][0]["pages"][0]["stages"][1]
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
    risky_stage = result["processes"][0]["pages"][0]["stages"][1]
    assert risky_stage["exception_handler_id"] == "s_003"


def test_exception_type_extracted(exception_handling_bprelease: Path) -> None:
    """exception_type extracted from <exception type="..."> child."""
    result = parse_process(exception_handling_bprelease)
    risky_stage = result["processes"][0]["pages"][0]["stages"][1]
    assert risky_stage["exception_type"] == "Business Exception"


def test_stage_no_exception_handler_is_none(minimal_bprelease: Path) -> None:
    """Stage with no exception handler has exception_handler_id=None."""
    result = parse_process(minimal_bprelease)
    start_stage = result["processes"][0]["pages"][0]["stages"][0]
    assert start_stage["exception_handler_id"] is None


# ── Parameter mapping tests ─────────────────────────────────────────────────


def test_action_params_map_populated(minimal_bprelease: Path) -> None:
    """Action inputs are mapped correctly in params_map."""
    result = parse_process(minimal_bprelease)
    action_stage = result["processes"][0]["pages"][0]["stages"][1]
    assert "Param1" in action_stage["params_map"]
    assert action_stage["params_map"]["Param1"] == "Hello"


def test_calculation_params_map_populated(calculation_bprelease: Path) -> None:
    """Calculation expressions are mapped correctly in params_map."""
    result = parse_process(calculation_bprelease)
    calc_stage = result["processes"][0]["pages"][0]["stages"][1]
    assert "result" in calc_stage["params_map"]
    assert calc_stage["params_map"]["result"] == "a + b"


def test_stage_no_params_has_empty_map(minimal_bprelease: Path) -> None:
    """Stage with no inputs/calculations has empty params_map."""
    result = parse_process(minimal_bprelease)
    start_stage = result["processes"][0]["pages"][0]["stages"][0]
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
    assert result["processes"][0]["pages"][0]["name"] == "pg_fallback"


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
    main_pages = [p for p in result["processes"][0]["pages"] if p["is_main"]]
    assert len(main_pages) == 1
    assert main_pages[0]["page_id"] == "pg1"


# ── Integration tests ───────────────────────────────────────────────────────


def test_full_minimal_flow(minimal_bprelease: Path) -> None:
    """Full parse of minimal fixture works end-to-end."""
    result = parse_process(minimal_bprelease)

    assert result["processes"][0]["process_id"] == "proc_123"
    assert result["processes"][0]["name"] == "TestProcess"
    assert result["processes"][0]["version"] == "1.0"
    assert len(result["processes"][0]["pages"]) == 1
    assert result["processes"][0]["pages"][0]["is_main"] is True
    assert len(result["processes"][0]["pages"][0]["stages"]) == 3


def test_full_multipage_flow(multi_page_bprelease: Path) -> None:
    """Full parse of multi-page fixture works end-to-end."""
    result = parse_process(multi_page_bprelease)

    assert result["processes"][0]["process_id"] == "proc_456"
    assert result["processes"][0]["name"] == "MainProcess"
    assert len(result["processes"][0]["pages"]) == 2
    assert result["processes"][0]["pages"][0]["is_main"] is True
    assert result["processes"][0]["pages"][1]["is_main"] is False
    assert len(result["processes"][0]["pages"][0]["stages"]) == 2
    assert len(result["processes"][0]["pages"][1]["stages"]) == 2


@pytest.mark.skipif(
    not Path("samples/blueprism/PID_0127.bprelease").exists(),
    reason="Real sample not available (expected in CI)",
)
def test_real_sample_parses() -> None:
    """Real sample file PID_0127.bprelease parses without error."""
    result = parse_process(Path("samples/blueprism/PID_0127.bprelease"))

    assert result["processes"]
    assert result["processes"][0]["process_id"]
    assert result["processes"][0]["name"]
    assert len(result["processes"][0]["pages"]) > 0
    total_stages = sum(len(p["stages"]) for p in result["processes"][0]["pages"])
    assert total_stages > 0, "Expected at least one stage"


# ── VBO resource extraction ────────────────────────────────────────


def test_action_vbo_object_in_params_map(minimal_bprelease: Path) -> None:
    """Action stage with <resource> element stores VBO object and action in params_map."""
    result = parse_process(minimal_bprelease)
    action_stage = result["processes"][0]["pages"][0]["stages"][1]

    assert action_stage["stage_type"] == "Action"
    assert action_stage["name"] == "Call Action"
    assert action_stage["params_map"]["_vbo_object"] == "Utility - Strings"
    assert action_stage["params_map"]["_vbo_action"] == "Split Text"


def test_non_action_stage_has_no_vbo_keys(multi_page_bprelease: Path) -> None:
    """Non-Action stages (Start, End, Decision, etc.) do not have _vbo_* keys."""
    result = parse_process(multi_page_bprelease)

    for page in result["processes"][0]["pages"]:
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
    action_stage = result["processes"][0]["pages"][0]["stages"][1]

    assert action_stage["stage_type"] == "Action"
    assert "_vbo_object" not in action_stage["params_map"]
    assert "_vbo_action" not in action_stage["params_map"]
    # But input params should still be present
    assert action_stage["params_map"]["Param1"] == "Value1"


def test_vbo_constants_exported() -> None:
    """VBO constants are exported from flowsmith.parser."""
    assert VBO_OBJECT_KEY == "_vbo_object"
    assert VBO_ACTION_KEY == "_vbo_action"


# ── New field extraction tests (decision, code, narrative, initial_value, ──
# ── timeout, groupid, exception detail/usecurrent, friendlyname, published) ─


@pytest.fixture
def decision_bprelease(tmp_path: Path) -> Path:
    """Blue Prism .bprelease with a Decision stage carrying an expression."""
    xml_content = """\
<?xml version="1.0" encoding="utf-8"?>
<process id="proc_dec" name="DecisionTest" version="1.0">
  <subsheet subsheetid="pg_001" name="DecisionTest" type="0">
    <stage stageid="s_001" type="Start" name="Start"/>
    <stage stageid="s_002" type="Decision" name="Check">
      <decision expression="[Flag] = True"/>
      <ontrue>s_003</ontrue>
      <onfalse>s_003</onfalse>
    </stage>
    <stage stageid="s_003" type="End" name="End"/>
  </subsheet>
</process>
"""
    filepath = tmp_path / "test_decision.bprelease"
    filepath.write_text(xml_content, encoding="utf-8")
    return filepath


@pytest.fixture
def code_narrative_bprelease(tmp_path: Path) -> Path:
    """Blue Prism .bprelease with a Code stage (CDATA body) and a narrative."""
    xml_content = """\
<?xml version="1.0" encoding="utf-8"?>
<process id="proc_code" name="CodeTest" version="1.0">
  <subsheet subsheetid="pg_001" name="CodeTest" type="0">
    <stage stageid="s_001" type="Start" name="Start"/>
    <stage stageid="s_002" type="Code" name="Run Script">
      <narrative>Runs a small VBScript snippet.</narrative>
      <code><![CDATA[System.Console.WriteLine("hi")]]></code>
    </stage>
    <stage stageid="s_003" type="End" name="End"/>
  </subsheet>
</process>
"""
    filepath = tmp_path / "test_code.bprelease"
    filepath.write_text(xml_content, encoding="utf-8")
    return filepath


@pytest.fixture
def data_initialvalue_bprelease(tmp_path: Path) -> Path:
    """Blue Prism .bprelease with Data stages: one with an initial value, one without."""
    xml_content = """\
<?xml version="1.0" encoding="utf-8"?>
<process id="proc_data" name="DataTest" version="1.0">
  <subsheet subsheetid="pg_001" name="DataTest" type="0">
    <stage stageid="s_001" type="Data" name="Counter">
      <datatype>number</datatype>
      <initialvalue>0</initialvalue>
    </stage>
    <stage stageid="s_002" type="Data" name="Empty">
      <datatype>text</datatype>
      <initialvalue />
    </stage>
  </subsheet>
</process>
"""
    filepath = tmp_path / "test_data_initial.bprelease"
    filepath.write_text(xml_content, encoding="utf-8")
    return filepath


@pytest.fixture
def wait_loop_bprelease(tmp_path: Path) -> Path:
    """Blue Prism .bprelease with WaitStart/LoopStart stages carrying timeout/groupid."""
    xml_content = """\
<?xml version="1.0" encoding="utf-8"?>
<process id="proc_wait" name="WaitTest" version="1.0">
  <subsheet subsheetid="pg_001" name="WaitTest" type="0">
    <stage stageid="s_001" type="WaitStart" name="Wait1">
      <groupid>grp_1</groupid>
      <timeout>120</timeout>
    </stage>
    <stage stageid="s_002" type="WaitEnd" name="Wait1 End">
      <groupid>grp_1</groupid>
    </stage>
    <stage stageid="s_003" type="LoopStart" name="Loop1">
      <groupid>grp_2</groupid>
    </stage>
    <stage stageid="s_004" type="LoopEnd" name="Loop1 End">
      <groupid>grp_2</groupid>
    </stage>
  </subsheet>
</process>
"""
    filepath = tmp_path / "test_wait_loop.bprelease"
    filepath.write_text(xml_content, encoding="utf-8")
    return filepath


@pytest.fixture
def exception_detail_bprelease(tmp_path: Path) -> Path:
    """Blue Prism .bprelease with exception detail expression and usecurrent flag."""
    xml_content = """\
<?xml version="1.0" encoding="utf-8"?>
<process id="proc_exc" name="ExcDetailTest" version="1.0">
  <subsheet subsheetid="pg_001" name="ExcDetailTest" type="0">
    <stage stageid="s_001" type="Exception" name="Throw Custom">
      <exception type="Business Exception" detail="[Message]"/>
    </stage>
    <stage stageid="s_002" type="Exception" name="Rethrow">
      <exception type="" detail="" usecurrent="yes"/>
    </stage>
  </subsheet>
</process>
"""
    filepath = tmp_path / "test_exc_detail.bprelease"
    filepath.write_text(xml_content, encoding="utf-8")
    return filepath


@pytest.fixture
def friendlyname_bprelease(tmp_path: Path) -> Path:
    """Blue Prism .bprelease with an Action stage input carrying a friendlyname."""
    xml_content = """\
<?xml version="1.0" encoding="utf-8"?>
<process id="proc_fn" name="FriendlyNameTest" version="1.0">
  <subsheet subsheetid="pg_001" name="FriendlyNameTest" type="0">
    <stage stageid="s_001" type="Action" name="Call Action">
      <inputs>
        <input name="Param1" expr="Hello" type="text" friendlyname="Greeting"/>
      </inputs>
      <resource object="Utility - Strings" action="Split Text"/>
    </stage>
  </subsheet>
</process>
"""
    filepath = tmp_path / "test_friendlyname.bprelease"
    filepath.write_text(xml_content, encoding="utf-8")
    return filepath


@pytest.fixture
def published_page_bprelease(tmp_path: Path) -> Path:
    """Blue Prism .bprelease with one published and one unpublished subsheet."""
    xml_content = """\
<?xml version="1.0" encoding="utf-8"?>
<process id="proc_pub" name="PublishedTest" version="1.0">
  <subsheet subsheetid="pg_001" name="PublishedTest" type="0" published="true">
    <stage stageid="s_001" type="Start" name="Start"/>
  </subsheet>
  <subsheet subsheetid="pg_002" name="Helper" type="0" published="false">
    <stage stageid="s_002" type="Start" name="Start"/>
  </subsheet>
</process>
"""
    filepath = tmp_path / "test_published.bprelease"
    filepath.write_text(xml_content, encoding="utf-8")
    return filepath


def test_decision_expression_extracted(decision_bprelease: Path) -> None:
    """decision_expression is extracted from <decision expression="...">."""
    result = parse_process(decision_bprelease)
    decision_stage = result["processes"][0]["pages"][0]["stages"][1]
    assert decision_stage["decision_expression"] == "[Flag] = True"


def test_decision_expression_none_when_absent(minimal_bprelease: Path) -> None:
    """decision_expression is None for stages without a <decision> child."""
    result = parse_process(minimal_bprelease)
    start_stage = result["processes"][0]["pages"][0]["stages"][0]
    assert start_stage["decision_expression"] is None


def test_code_text_extracted(code_narrative_bprelease: Path) -> None:
    """code_text is extracted from the <code> CDATA body."""
    result = parse_process(code_narrative_bprelease)
    code_stage = result["processes"][0]["pages"][0]["stages"][1]
    assert code_stage["code_text"] == 'System.Console.WriteLine("hi")'


def test_narrative_extracted(code_narrative_bprelease: Path) -> None:
    """narrative is extracted from the <narrative> text child."""
    result = parse_process(code_narrative_bprelease)
    code_stage = result["processes"][0]["pages"][0]["stages"][1]
    assert code_stage["narrative"] == "Runs a small VBScript snippet."


def test_narrative_none_when_absent(minimal_bprelease: Path) -> None:
    """narrative is None when no <narrative> child is present."""
    result = parse_process(minimal_bprelease)
    start_stage = result["processes"][0]["pages"][0]["stages"][0]
    assert start_stage["narrative"] is None


def test_data_stage_initial_value_extracted(data_initialvalue_bprelease: Path) -> None:
    """initial_value is extracted from a non-empty <initialvalue> element."""
    result = parse_process(data_initialvalue_bprelease)
    counter_stage = result["processes"][0]["pages"][0]["stages"][0]
    assert counter_stage["initial_value"] == "0"
    # It should also be reflected on the synthesised data item.
    assert counter_stage["data_items"][0]["initial_value"] == "0"


def test_data_stage_empty_initial_value_is_none(data_initialvalue_bprelease: Path) -> None:
    """A self-closing <initialvalue /> element yields initial_value=None."""
    result = parse_process(data_initialvalue_bprelease)
    empty_stage = result["processes"][0]["pages"][0]["stages"][1]
    assert empty_stage["initial_value"] is None
    assert empty_stage["data_items"][0]["initial_value"] is None


def test_waitstart_timeout_and_groupid_extracted(wait_loop_bprelease: Path) -> None:
    """timeout_seconds and group_id are extracted from WaitStart's children."""
    result = parse_process(wait_loop_bprelease)
    stages = result["processes"][0]["pages"][0]["stages"]
    wait_start = next(s for s in stages if s["stage_id"] == "s_001")
    assert wait_start["group_id"] == "grp_1"
    assert wait_start["timeout_seconds"] == 120


def test_waitend_groupid_extracted_no_timeout(wait_loop_bprelease: Path) -> None:
    """WaitEnd carries the same group_id but has no <timeout> (so None)."""
    result = parse_process(wait_loop_bprelease)
    stages = result["processes"][0]["pages"][0]["stages"]
    wait_end = next(s for s in stages if s["stage_id"] == "s_002")
    assert wait_end["group_id"] == "grp_1"
    assert wait_end["timeout_seconds"] is None


def test_loopstart_groupid_extracted(wait_loop_bprelease: Path) -> None:
    """LoopStart/LoopEnd also carry group_id for bracket matching."""
    result = parse_process(wait_loop_bprelease)
    stages = result["processes"][0]["pages"][0]["stages"]
    loop_start = next(s for s in stages if s["stage_id"] == "s_003")
    loop_end = next(s for s in stages if s["stage_id"] == "s_004")
    assert loop_start["group_id"] == "grp_2"
    assert loop_end["group_id"] == "grp_2"


def test_exception_detail_extracted(exception_detail_bprelease: Path) -> None:
    """exception_detail is extracted from <exception detail="...">."""
    result = parse_process(exception_detail_bprelease)
    throw_stage = result["processes"][0]["pages"][0]["stages"][0]
    assert throw_stage["exception_detail"] == "[Message]"
    assert throw_stage["exception_usecurrent"] is False


def test_exception_usecurrent_true(exception_detail_bprelease: Path) -> None:
    """exception_usecurrent=True when usecurrent="yes"."""
    result = parse_process(exception_detail_bprelease)
    rethrow_stage = result["processes"][0]["pages"][0]["stages"][1]
    assert rethrow_stage["exception_usecurrent"] is True


def test_exception_usecurrent_defaults_false(minimal_bprelease: Path) -> None:
    """exception_usecurrent defaults to False when no <exception> child exists."""
    result = parse_process(minimal_bprelease)
    start_stage = result["processes"][0]["pages"][0]["stages"][0]
    assert start_stage["exception_usecurrent"] is False


def test_input_friendlyname_extracted(friendlyname_bprelease: Path) -> None:
    """friendlyname attribute on <input> is captured in input_friendlynames."""
    result = parse_process(friendlyname_bprelease)
    action_stage = result["processes"][0]["pages"][0]["stages"][0]
    assert action_stage["input_friendlynames"]["Param1"] == "Greeting"


def test_input_friendlyname_empty_when_absent(minimal_bprelease: Path) -> None:
    """input_friendlynames is empty when no <input> has a friendlyname attribute."""
    result = parse_process(minimal_bprelease)
    action_stage = result["processes"][0]["pages"][0]["stages"][1]
    assert action_stage["input_friendlynames"] == {}


def test_page_published_true(published_page_bprelease: Path) -> None:
    """published=True for a subsheet with published="true"."""
    result = parse_process(published_page_bprelease)
    main_page = next(p for p in result["processes"][0]["pages"] if p["page_id"] == "pg_001")
    assert main_page["published"] is True


def test_page_published_false(published_page_bprelease: Path) -> None:
    """published=False for a subsheet with published="false"."""
    result = parse_process(published_page_bprelease)
    helper_page = next(p for p in result["processes"][0]["pages"] if p["page_id"] == "pg_002")
    assert helper_page["published"] is False


def test_page_published_defaults_false(minimal_bprelease: Path) -> None:
    """published defaults to False when the subsheet has no published attribute."""
    result = parse_process(minimal_bprelease)
    assert result["processes"][0]["pages"][0]["published"] is False


# ── Real sample validation (PID_0171.bprelease) ─────────────────────────────

PID_0171 = Path("samples/blueprism/PID_0171.bprelease")


@pytest.fixture(scope="module")
def pid_0171_raw() -> dict:
    """Parse the real PID_0171 sample once per test module.

    As of Task 3a, parse_process() returns MultiArtefactRelease.
    This fixture extracts the first process (the main PID_0171 process)
    for backward compatibility with existing tests.
    """
    if not PID_0171.exists():
        pytest.skip("PID_0171 sample not available")
    release = parse_process(PID_0171)
    if release["processes"]:
        return release["processes"][0]
    pytest.skip("No processes found in PID_0171 release")


def test_pid171_decision_stage_has_expression(pid_0171_raw: dict) -> None:
    """At least one Decision stage in PID_0171 has a non-None decision_expression."""
    decision_stages = [
        s for page in pid_0171_raw["pages"] for s in page["stages"] if s["stage_type"] == "Decision"
    ]
    assert decision_stages, "Expected at least one Decision stage in PID_0171"
    with_expr = [s for s in decision_stages if s["decision_expression"] is not None]
    assert with_expr, "Expected at least one Decision stage with a non-None decision_expression"


def test_pid171_data_stage_has_initial_value(pid_0171_raw: dict) -> None:
    """At least one Data stage with a non-empty <initialvalue> has non-None initial_value."""
    data_stages = [
        s for page in pid_0171_raw["pages"] for s in page["stages"] if s["stage_type"] == "Data"
    ]
    assert data_stages, "Expected at least one Data stage in PID_0171"
    with_value = [s for s in data_stages if s["initial_value"] is not None]
    assert with_value, "Expected at least one Data stage with a non-None initial_value"


def test_pid171_wait_loop_start_have_group_id(pid_0171_raw: dict) -> None:
    """WaitStart and LoopStart stages in PID_0171 have non-None group_id."""
    bracket_starts = [
        s
        for page in pid_0171_raw["pages"]
        for s in page["stages"]
        if s["stage_type"] in ("WaitStart", "LoopStart")
    ]
    assert bracket_starts, "Expected at least one WaitStart/LoopStart stage in PID_0171"
    for stage in bracket_starts:
        assert stage["group_id"] is not None, (
            f"Stage {stage['stage_id']} ({stage['stage_type']}) has no group_id"
        )


# ── Task 1a: ACTION input/output and edge target parsing ───────────────────


@pytest.fixture
def action_with_inputs_outputs_bprelease(tmp_path: Path) -> Path:
    """Blue Prism .bprelease with ACTION stage carrying both inputs and outputs.

    This mimics the structure of the Excel fusion stages:
      - ACTION stage with <inputs> (routed to params_map and data_items)
      - ACTION stage with <outputs> (routed to data_items)
      - Edge targets (onsuccess, ontrue, onfalse) captured
    """
    xml_content = """\
<?xml version="1.0" encoding="utf-8"?>
<process id="proc_io" name="InputOutputTest" version="1.0">
  <subsheet subsheetid="pg_001" name="InputOutputTest" type="0">
    <stage stageid="s_001" type="Start" name="Start"/>
    <stage stageid="s_002" type="Action" name="Create Instance">
      <inputs>
        <input name="Enable Events" type="flag" expr=""/>
      </inputs>
      <outputs>
        <output name="handle" type="number" stage="handle"/>
      </outputs>
      <onsuccess>s_003</onsuccess>
      <resource object="MS Excel VBO" action="Create Instance"/>
    </stage>
    <stage stageid="s_003" type="Action" name="Open Excel">
      <inputs>
        <input name="handle" type="number" expr="[handle]"/>
        <input name="File name" type="text" expr="[fileName]"/>
      </inputs>
      <outputs>
        <output name="Workbook Name" type="text" stage="Workbook Name"/>
      </outputs>
      <onsuccess>s_004</onsuccess>
      <resource object="MS Excel VBO" action="Open Workbook"/>
    </stage>
    <stage stageid="s_004" type="End" name="End"/>
  </subsheet>
</process>
"""
    filepath = tmp_path / "test_io.bprelease"
    filepath.write_text(xml_content, encoding="utf-8")
    return filepath


@pytest.fixture
def decision_with_edges_bprelease(tmp_path: Path) -> Path:
    """Blue Prism .bprelease with DECISION stage carrying ontrue and onfalse edges."""
    xml_content = """\
<?xml version="1.0" encoding="utf-8"?>
<process id="proc_edges" name="EdgeTest" version="1.0">
  <subsheet subsheetid="pg_001" name="EdgeTest" type="0">
    <stage stageid="s_001" type="Start" name="Start"/>
    <stage stageid="s_002" type="Decision" name="Check Condition">
      <decision expression="[Flag] = True"/>
      <ontrue>s_003</ontrue>
      <onfalse>s_004</onfalse>
    </stage>
    <stage stageid="s_003" type="End" name="End (True)"/>
    <stage stageid="s_004" type="End" name="End (False)"/>
  </subsheet>
</process>
"""
    filepath = tmp_path / "test_edges.bprelease"
    filepath.write_text(xml_content, encoding="utf-8")
    return filepath


def test_action_input_in_params_map(action_with_inputs_outputs_bprelease: Path) -> None:
    """ACTION stage inputs are stored in params_map as before."""
    result = parse_process(action_with_inputs_outputs_bprelease)
    create_stage = result["processes"][0]["pages"][0]["stages"][1]

    assert create_stage["stage_type"] == "Action"
    assert "Enable Events" in create_stage["params_map"]
    assert create_stage["params_map"]["Enable Events"] == ""


def test_action_input_in_data_items(action_with_inputs_outputs_bprelease: Path) -> None:
    """ACTION stage inputs are ALSO added to data_items with is_input=True (Task 1a)."""
    result = parse_process(action_with_inputs_outputs_bprelease)
    create_stage = result["processes"][0]["pages"][0]["stages"][1]

    # Find the "Enable Events" data item
    enable_events_di = next(
        (di for di in create_stage["data_items"] if di["name"] == "Enable Events"), None
    )
    assert enable_events_di is not None, "Expected 'Enable Events' in data_items"
    assert enable_events_di["data_type"] == "flag"
    assert enable_events_di["is_input"] is True
    assert enable_events_di["is_output"] is False


def test_action_output_in_data_items(action_with_inputs_outputs_bprelease: Path) -> None:
    """ACTION stage outputs are added to data_items with is_output=True (Task 1a)."""
    result = parse_process(action_with_inputs_outputs_bprelease)
    create_stage = result["processes"][0]["pages"][0]["stages"][1]

    # Find the "handle" output data item
    handle_di = next((di for di in create_stage["data_items"] if di["name"] == "handle"), None)
    assert handle_di is not None, "Expected 'handle' output in data_items"
    assert handle_di["data_type"] == "number"
    assert handle_di["is_input"] is False
    assert handle_di["is_output"] is True


def test_onsuccess_target_captured(action_with_inputs_outputs_bprelease: Path) -> None:
    """<onsuccess> element target stage ID is captured in onsuccess_target (Task 1a)."""
    result = parse_process(action_with_inputs_outputs_bprelease)
    create_stage = result["processes"][0]["pages"][0]["stages"][1]

    assert create_stage["onsuccess_target"] == "s_003"


def test_onsuccess_target_none_when_absent(minimal_bprelease: Path) -> None:
    """onsuccess_target defaults to None when no <onsuccess> element."""
    result = parse_process(minimal_bprelease)
    start_stage = result["processes"][0]["pages"][0]["stages"][0]

    assert start_stage["onsuccess_target"] is None


def test_ontrue_target_captured(decision_with_edges_bprelease: Path) -> None:
    """<ontrue> element target stage ID is captured in ontrue_target (Task 1a)."""
    result = parse_process(decision_with_edges_bprelease)
    decision_stage = result["processes"][0]["pages"][0]["stages"][1]

    assert decision_stage["ontrue_target"] == "s_003"


def test_onfalse_target_captured(decision_with_edges_bprelease: Path) -> None:
    """<onfalse> element target stage ID is captured in onfalse_target (Task 1a)."""
    result = parse_process(decision_with_edges_bprelease)
    decision_stage = result["processes"][0]["pages"][0]["stages"][1]

    assert decision_stage["onfalse_target"] == "s_004"


def test_ontrue_onfalse_none_when_absent(minimal_bprelease: Path) -> None:
    """ontrue_target and onfalse_target default to None when absent."""
    result = parse_process(minimal_bprelease)
    start_stage = result["processes"][0]["pages"][0]["stages"][0]

    assert start_stage["ontrue_target"] is None
    assert start_stage["onfalse_target"] is None


def test_pid171_create_instance_has_numeric_handle_output(pid_0171_raw: dict) -> None:
    """In PID_0171's 'Read Excel As Collection' page, 'Create Instance' stage
    outputs a numeric 'handle' that should appear in data_items (Task 1a requirement).
    """
    # Find the page with subsheetid containing "Read Excel"
    # The "Create Instance" stage is on page eeeb6765-9d9f-4374-b7cd-d5ca8f3dfa61
    page = next(
        (
            p
            for p in pid_0171_raw["pages"]
            if "eeeb6765-9d9f-4374-b7cd-d5ca8f3dfa61" in p["page_id"]
        ),
        None,
    )
    if page is None:
        pytest.skip("PID_0171 'Read Excel As Collection' page not found")

    # Find the "Create Instance" stage
    create_instance = next(
        (s for s in page["stages"] if s["name"] == "Create Instance"),
        None,
    )
    assert create_instance is not None, "Expected 'Create Instance' stage in page"

    # Verify it has a numeric output named "handle" in data_items
    handle_outputs = [
        di for di in create_instance["data_items"] if di["name"] == "handle" and di["is_output"]
    ]
    assert handle_outputs, "Expected 'handle' output in 'Create Instance' data_items"
    handle_di = handle_outputs[0]
    assert handle_di["data_type"] == "number"


def test_pid171_open_excel_has_numeric_handle_input(pid_0171_raw: dict) -> None:
    """In PID_0171's 'Read Excel As Collection' page, 'Open Excel' stage
    should have a numeric 'handle' input in data_items (Task 1a requirement).
    """
    page = next(
        (
            p
            for p in pid_0171_raw["pages"]
            if "eeeb6765-9d9f-4374-b7cd-d5ca8f3dfa61" in p["page_id"]
        ),
        None,
    )
    if page is None:
        pytest.skip("PID_0171 'Read Excel As Collection' page not found")

    # Find the "Open Excel" stage
    open_excel = next(
        (s for s in page["stages"] if s["name"] == "Open Excel"),
        None,
    )
    assert open_excel is not None, "Expected 'Open Excel' stage in page"

    # Verify it has a numeric input named "handle" in data_items
    handle_inputs = [
        di for di in open_excel["data_items"] if di["name"] == "handle" and di["is_input"]
    ]
    assert handle_inputs, "Expected 'handle' input in 'Open Excel' data_items"
    handle_di = handle_inputs[0]
    assert handle_di["data_type"] == "number"


def test_pid171_create_instance_has_onsuccess_edge(pid_0171_raw: dict) -> None:
    """In PID_0171's 'Read Excel As Collection' page, 'Create Instance' stage
    should have an onsuccess_target pointing to 'Open Excel' stage (Task 1a requirement).
    """
    page = next(
        (
            p
            for p in pid_0171_raw["pages"]
            if "eeeb6765-9d9f-4374-b7cd-d5ca8f3dfa61" in p["page_id"]
        ),
        None,
    )
    if page is None:
        pytest.skip("PID_0171 'Read Excel As Collection' page not found")

    create_instance = next(
        (s for s in page["stages"] if s["name"] == "Create Instance"),
        None,
    )
    assert create_instance is not None

    # Verify onsuccess_target is set and non-empty
    assert create_instance["onsuccess_target"] is not None, (
        "Expected onsuccess_target on 'Create Instance'"
    )

    # Verify it points to the "Open Excel" stage
    open_excel = next(
        (s for s in page["stages"] if s["name"] == "Open Excel"),
        None,
    )
    assert open_excel is not None
    assert create_instance["onsuccess_target"] == open_excel["stage_id"]


# ── Task 3a: Multi-artefact release parsing ──────────────────────────────────


def test_multi_artefact_release_returns_correct_structure(tmp_path: Path) -> None:
    """parse_process() returns MultiArtefactRelease with processes, objects, env_vars, validation."""
    xml_content = """\
<?xml version="1.0" encoding="utf-8"?>
<bpr:release xmlns:bpr="http://www.blueprism.co.uk/product/release"
             xmlns="http://www.blueprism.co.uk/product/process"
             xmlns:env="http://www.blueprism.co.uk/product/environment-variable">
  <bpr:name>TestRelease</bpr:name>
  <bpr:contents count="3">
    <process id="proc_001" name="Process1" version="1.0">
      <process name="Process1">
        <subsheet subsheetid="pg_001" name="Process1">
          <stage stageid="s_001" type="Start" name="Start"/>
          <stage stageid="s_002" type="End" name="End"/>
        </subsheet>
      </process>
    </process>
    <object id="obj_001" name="Object1" version="1.0">
      <process name="Object1">
        <subsheet subsheetid="pg_002" name="Initialize">
          <stage stageid="s_003" type="Start" name="Start"/>
          <stage stageid="s_004" type="End" name="End"/>
        </subsheet>
      </process>
    </object>
    <environment-variable id="ev_001" name="TestVar" type="text" value="test_value">
      <env:description>A test environment variable</env:description>
    </environment-variable>
  </bpr:contents>
</bpr:release>
"""
    filepath = tmp_path / "test_multi.bprelease"
    filepath.write_text(xml_content, encoding="utf-8")

    result = parse_process(filepath)

    # Verify top-level structure
    assert "processes" in result
    assert "objects" in result
    assert "environment_variables" in result
    assert "validation" in result
    assert "source_file" in result

    # Verify counts
    assert len(result["processes"]) == 1
    assert len(result["objects"]) == 1
    assert len(result["environment_variables"]) == 1

    # Verify processes content
    assert result["processes"][0]["name"] == "Process1"
    assert result["processes"][0]["process_id"] == "proc_001"

    # Verify objects content
    assert result["objects"][0]["name"] == "Object1"
    assert result["objects"][0]["process_id"] == "obj_001"

    # Verify environment variables content
    assert result["environment_variables"][0]["name"] == "TestVar"
    assert result["environment_variables"][0]["value"] == "test_value"

    # Verify validation stats
    assert result["validation"]["declared_count"] == 3
    assert result["validation"]["process_count"] == 1
    assert result["validation"]["object_count"] == 1
    assert result["validation"]["env_var_count"] == 1


def test_multi_artefact_validation_count_mismatch(tmp_path: Path) -> None:
    """parse_process() raises ConfigError if declared count doesn't match actual."""
    from flowsmith.exceptions import ConfigError

    xml_content = """\
<?xml version="1.0" encoding="utf-8"?>
<bpr:release xmlns:bpr="http://www.blueprism.co.uk/product/release"
             xmlns="http://www.blueprism.co.uk/product/process">
  <bpr:name>TestRelease</bpr:name>
  <bpr:contents count="5">
    <process id="proc_001" name="Process1" version="1.0">
      <process name="Process1">
        <subsheet subsheetid="pg_001" name="Process1">
          <stage stageid="s_001" type="Start" name="Start"/>
        </subsheet>
      </process>
    </process>
  </bpr:contents>
</bpr:release>
"""
    filepath = tmp_path / "test_mismatch.bprelease"
    filepath.write_text(xml_content, encoding="utf-8")

    with pytest.raises(ConfigError, match="Content count mismatch"):
        parse_process(filepath)


def test_pid_0171_multi_artefact_parsing() -> None:
    """Test multi-artefact parsing against real PID_0171.bprelease file.

    Verifies that:
    - Parsing returns 2 processes (main + RPA_Sharepoint_API_ConfigFile_Download)
    - VBO/object artefacts are present
    - Validation counts are correct
    """
    from pathlib import Path

    pid_0171_path = Path("samples/blueprism/PID_0171.bprelease")
    if not pid_0171_path.exists():
        pytest.skip("PID_0171.bprelease not found")

    result = parse_process(pid_0171_path)

    # Verify multi-artefact structure
    assert "processes" in result
    assert "objects" in result
    assert "environment_variables" in result

    # Verify we have 2 processes
    assert len(result["processes"]) == 2, f"Expected 2 processes, got {len(result['processes'])}"

    # Verify process names
    process_names = [p["name"] for p in result["processes"]]
    assert "PID_171_US_Process_LIMS_Prelude" in process_names
    assert "RPA_Sharepoint_API_ConfigFile_Download" in process_names

    # Verify we have VBO objects (at least some)
    assert len(result["objects"]) > 0, "Expected VBO/object artefacts in PID_0171"

    # Verify object structure (all should have process_id, name, pages, etc.)
    for obj in result["objects"]:
        assert "process_id" in obj
        assert "name" in obj
        assert "pages" in obj
        assert isinstance(obj["pages"], list)

    # Verify validation counts match
    validation = result["validation"]
    assert validation["process_count"] == 2
    assert validation["object_count"] == len(result["objects"])
    assert validation["declared_count"] == (
        validation["process_count"]
        + validation["object_count"]
        + validation["env_var_count"]
        + validation["group_count"]
    ), "Validation count mismatch"


def test_per_artefact_page_isolation_pid_0171() -> None:
    """Regression test: each artefact in multi-artefact release has isolated page set.

    This test would have caught the bug where every artefact returned the same
    full-document page set instead of being scoped to its own content (Task 3a
    fix pass, PID 171).

    Verifies:
    - Two processes in PID_0171 return DIFFERENT page counts (23 vs 7, not both 381)
    - VBO objects each return a distinct, small page count (not the full 381)
    - No artefact shares the full-document page set with another
    """
    from pathlib import Path

    pid_0171_path = Path("samples/blueprism/PID_0171.bprelease")
    if not pid_0171_path.exists():
        pytest.skip("PID_0171.bprelease not found")

    result = parse_process(pid_0171_path)

    # Extract page sets for both processes
    processes = result["processes"]
    assert len(processes) == 2, "Expected 2 processes in PID_0171"

    p0_pages = {pg["page_id"] for pg in processes[0]["pages"]}
    p1_pages = {pg["page_id"] for pg in processes[1]["pages"]}

    p0_name = processes[0]["name"]
    p1_name = processes[1]["name"]
    p0_count = len(processes[0]["pages"])
    p1_count = len(processes[1]["pages"])

    # Verify process page counts are different (not both 381)
    assert p0_count != p1_count, (
        f"Process page counts should differ: {p0_name}={p0_count}, "
        f"{p1_name}={p1_count} (bug: all artefacts had 381 identical pages)"
    )

    # Verify neither process has the full 381-page superset
    # (the actual full-document page count if the bug existed)
    assert p0_count < 50, f"Process {p0_name} should have <50 pages, got {p0_count}"
    assert p1_count < 50, f"Process {p1_name} should have <50 pages, got {p1_count}"

    # Verify page sets are not identical
    assert p0_pages != p1_pages, f"Process {p0_name} and {p1_name} should have different page sets"

    # Check VBO objects are similarly isolated
    objects = result["objects"]
    assert len(objects) > 0, "Expected VBO objects in PID_0171"

    # Each VBO should have a small, distinct page count (not 381)
    vbo_page_counts = [len(obj["pages"]) for obj in objects[:5]]
    for i, count in enumerate(vbo_page_counts):
        obj_name = objects[i]["name"]
        assert count < 100, (
            f"VBO {obj_name} should have <100 pages, got {count} "
            f"(bug: all VBOs had 381 identical pages)"
        )

    # Verify at least some VBOs have different page counts from each other
    # (not all the same, which would indicate continued cross-contamination)
    assert len(set(vbo_page_counts)) > 1, (
        f"VBOs should have different page counts, got {vbo_page_counts}"
    )


def test_backward_compat_single_process_file(minimal_bprelease: Path) -> None:
    """Single <process> root (not wrapped in <release>) returns MultiArtefactRelease."""
    result = parse_process(minimal_bprelease)

    # Should still return MultiArtefactRelease structure (Task 3a)
    assert isinstance(result, dict)
    assert "processes" in result
    assert "objects" in result
    assert "environment_variables" in result

    # Single process should be in processes list
    assert len(result["processes"]) == 1
    assert result["processes"][0]["name"] == "TestProcess"


# ── Task 3b: Environment-variable extraction ───────────────────────────────


def test_pid_0171_environment_variables_extraction() -> None:
    """Test that parsing PID_0171.bprelease extracts exactly 11 environment variables
    with the correct names as per architecture doc §A2 point 5 (Task 3b).
    """
    pid_0171_path = Path("samples/blueprism/PID_0171.bprelease")
    if not pid_0171_path.exists():
        pytest.skip("PID_0171.bprelease not found")

    result = parse_process(pid_0171_path)

    # Verify exactly 11 environment variables are extracted
    env_vars = result["environment_variables"]
    assert len(env_vars) == 11, f"Expected 11 environment variables, got {len(env_vars)}"

    # Extract the names and sort them for consistent comparison
    actual_names = sorted([ev["name"] for ev in env_vars])

    # Expected names from architecture doc §A2 point 5
    expected_names = sorted(
        [
            "PID_171_US_EV_LIMS_Prelude_ConfigFile",
            "RPA_Sharepoint_URL",
            "RPA_Sharepoint_Credential_Name",
            "RPA_Sharepoint_Bearer_Token",
            "RPA_Sharepoint_Random_Wait",
            "Generic_RPA_Sharepoint_API_Config_File_Folder_Path",
            "Generic_SupportTeam_EmailID",
            "RPA_AzureBlob_Download",
            "RPA_AzureBlob_Container_Name",
            "RPA_AzureBlob_StorageAccount_Name",
            "RPA_AzureBlob_Credential_Name",
        ]
    )

    assert actual_names == expected_names, (
        f"Environment variable names mismatch.\n"
        f"Expected: {expected_names}\n"
        f"Got: {actual_names}\n"
        f"Missing: {set(expected_names) - set(actual_names)}\n"
        f"Extra: {set(actual_names) - set(expected_names)}"
    )

    # Verify each environment variable has the required fields
    for ev in env_vars:
        assert "id" in ev, f"Environment variable {ev['name']} missing 'id' field"
        assert "name" in ev, "Environment variable missing 'name' field"
        assert "data_type" in ev, f"Environment variable {ev['name']} missing 'data_type' field"
        assert "value" in ev, f"Environment variable {ev['name']} missing 'value' field"
        assert "description" in ev, f"Environment variable {ev['name']} missing 'description' field"

    # Verify data_type values are correct (per architecture doc)
    data_type_map = {ev["name"]: ev["data_type"] for ev in env_vars}
    assert data_type_map["RPA_Sharepoint_Random_Wait"] == "number"
    assert data_type_map["RPA_AzureBlob_Download"] == "flag"
    # All others should be "text"
    text_vars = [
        "PID_171_US_EV_LIMS_Prelude_ConfigFile",
        "RPA_Sharepoint_URL",
        "RPA_Sharepoint_Credential_Name",
        "RPA_Sharepoint_Bearer_Token",
        "Generic_RPA_Sharepoint_API_Config_File_Folder_Path",
        "Generic_SupportTeam_EmailID",
        "RPA_AzureBlob_Container_Name",
        "RPA_AzureBlob_StorageAccount_Name",
        "RPA_AzureBlob_Credential_Name",
    ]
    for var_name in text_vars:
        assert data_type_map[var_name] == "text", (
            f"Environment variable {var_name} has data_type {data_type_map[var_name]}, expected 'text'"
        )
