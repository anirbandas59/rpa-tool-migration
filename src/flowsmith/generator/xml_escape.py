"""XML escaping helpers for solution template rendering.

Generated PAD script (`.robin`) and the JSON metadata blobs embedded in
`customizations.xml` routinely contain raw `<`, `>` and `&` characters —
for example VBScript such as
`If ex.Message.IndexOf("DISP_E_BADINDEX")<>-1`. Injected verbatim into a
Jinja2 template they produce non-well-formed XML.

These helpers are registered as Jinja2 filters by
`flowsmith.generator.packager.SolutionPackager` so that the templates stay
declarative and every escape decision lives in one place.

Element text uses the minimal escape set (`&`, `<`, `>`), matching the
reference managed solution under
`samples/pad/Shell_PP_PID_US_171_US_PreludeLIMS_V12_1_0_0_2_managed/`,
which leaves double quotes unescaped inside `<Definition>`. Attribute
values additionally escape `"` so they are safe inside double quotes.
"""

from __future__ import annotations

from xml.sax.saxutils import escape as _sax_escape

# `xml.sax.saxutils.escape` always handles `&`, `<` and `>`; anything extra
# is supplied through the entities mapping.
_ATTR_ENTITIES = {'"': "&quot;"}


def escape_xml_text(value: object) -> str:
    """Escape a value for use as XML element text content.

    Escapes `&`, `<` and `>` only — the minimal set required for
    well-formed character data. Double and single quotes are left intact so
    embedded JSON strings stay byte-comparable with the reference solution.

    Args:
        value: Any value; non-strings are rendered with `str()`. `None`
            becomes an empty string rather than the literal "None".

    Returns:
        The escaped text, safe to place between XML tags.
    """
    if value is None:
        return ""
    return _sax_escape(str(value))


def escape_xml_attr(value: object) -> str:
    """Escape a value for use inside a double-quoted XML attribute.

    Escapes `&`, `<`, `>` and `"`.

    Args:
        value: Any value; non-strings are rendered with `str()`. `None`
            becomes an empty string rather than the literal "None".

    Returns:
        The escaped text, safe to place inside `attr="..."`.
    """
    if value is None:
        return ""
    return _sax_escape(str(value), _ATTR_ENTITIES)
