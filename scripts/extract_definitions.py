"""Extract the plain Robin source of each Desktop Flow <Workflow><Definition> from a
Power Platform managed-solution customizations.xml, and write one .robin.txt per flow.

The <Definition> element content is XML-entity-escaped (&quot; &amp; ...) around a
*JSON-encoded string literal* (opening/closing double-quote, \\r\\n / \\' / \\" escapes) -
NOT plain XML-escaped source text. Decoding is therefore two steps: html.unescape() to
undo the XML-entity layer, then json.loads() to undo the JSON-string layer and recover the
real newlines/quotes. A naive str.replace('\\\\r\\\\n', '\\n') on the html-unescaped text
looks plausible but silently mis-decodes embedded quotes/backslashes - use json.loads().

Cloud Flows (Type=1, Category=5) store their definition out-of-line instead, referenced by
<JsonFileName> pointing at Workflows/<Name>-<GUID>.json (a plain Logic-App-schema JSON file,
readable directly with json.load - no unescape/decode step needed).

Usage: python extract_definitions.py <path-to-customizations.xml> <output-dir>
"""

import html
import json
import os
import re
import sys

WORKFLOW_RE = re.compile(r"<Workflow\b[^>]*>.*?</Workflow>", re.DOTALL)
NAME_RE = re.compile(r'Name="([^"]*)"')
DEFINITION_RE = re.compile(r"<Definition>(?:<!\[CDATA\[(.*?)\]\]>|(.*?))</Definition>", re.DOTALL)


def extract(customizations_xml_path: str, out_dir: str) -> None:
    with open(customizations_xml_path, encoding="utf-8", errors="replace") as f:
        content = f.read()

    os.makedirs(out_dir, exist_ok=True)

    for match in WORKFLOW_RE.finditer(content):
        block = match.group(0)
        name_match = NAME_RE.search(block)
        name = name_match.group(1) if name_match else "unknown"

        def_match = DEFINITION_RE.search(block)
        if not def_match:
            continue  # Cloud Flow - see <JsonFileName> instead, no inline Definition

        raw = def_match.group(1) if def_match.group(1) is not None else def_match.group(2)
        unescaped = html.unescape(raw)
        text = json.loads(unescaped)  # the JSON-string-decode step - do not skip

        safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
        out_path = os.path.join(out_dir, f"{safe_name}.robin.txt")
        with open(out_path, "w", encoding="utf-8") as out:
            out.write(text)
        print(f"{name}: {len(text)} chars, {text.count(chr(10)) + 1} lines -> {out_path}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python extract_definitions.py <customizations.xml> <output-dir>")
        sys.exit(1)
    extract(sys.argv[1], sys.argv[2])
