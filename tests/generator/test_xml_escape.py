"""Tests for XML escaping helpers used by solution templates."""

from __future__ import annotations

from lxml import etree

from flowsmith.generator.xml_escape import escape_xml_attr, escape_xml_text


class TestEscapeXmlText:
    """Tests for escape_xml_text()."""

    def test_escapes_ampersand_lt_gt(self) -> None:
        """The three mandatory character-data entities are escaped."""
        assert escape_xml_text("a & b < c > d") == "a &amp; b &lt; c &gt; d"

    def test_leaves_quotes_intact(self) -> None:
        """Quotes stay raw so embedded JSON matches the reference solution."""
        assert escape_xml_text("\"quoted\" and 'single'") == "\"quoted\" and 'single'"

    def test_escapes_real_vbscript_comparison(self) -> None:
        """A `<>` VBScript inequality no longer opens a bogus element."""
        source = 'If ex.Message.IndexOf("DISP_E_BADINDEX")<>-1 Then'
        escaped = escape_xml_text(source)
        assert "&lt;&gt;" in escaped
        assert "<" not in escaped

    def test_escaped_text_round_trips_through_lxml(self) -> None:
        """Escaped text parses back to the original string."""
        source = 'a < b & c > d "e"'
        parsed = etree.fromstring(f"<Definition>{escape_xml_text(source)}</Definition>")
        assert parsed.text == source

    def test_none_becomes_empty_string(self) -> None:
        """None renders as empty text, never the literal 'None'."""
        assert escape_xml_text(None) == ""

    def test_non_string_is_stringified(self) -> None:
        """Non-string values are rendered with str()."""
        assert escape_xml_text(42) == "42"

    def test_already_escaped_entity_is_double_escaped(self) -> None:
        """Escaping is not idempotent — callers must escape exactly once."""
        assert escape_xml_text("&amp;") == "&amp;amp;"


class TestEscapeXmlAttr:
    """Tests for escape_xml_attr()."""

    def test_escapes_double_quote(self) -> None:
        """Double quotes are escaped so the attribute delimiter survives."""
        assert escape_xml_attr('say "hi"') == "say &quot;hi&quot;"

    def test_escapes_ampersand_lt_gt(self) -> None:
        """The three mandatory entities are escaped in attributes too."""
        assert escape_xml_attr("a & b < c > d") == "a &amp; b &lt; c &gt; d"

    def test_escaped_attribute_round_trips_through_lxml(self) -> None:
        """Escaped attribute values parse back to the original string."""
        source = 'Page "A" & <B>'
        parsed = etree.fromstring(f'<Workflow Name="{escape_xml_attr(source)}" />')
        assert parsed.get("Name") == source

    def test_none_becomes_empty_string(self) -> None:
        """None renders as an empty attribute value."""
        assert escape_xml_attr(None) == ""
