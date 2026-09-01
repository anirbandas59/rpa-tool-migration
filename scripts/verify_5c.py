"""Verify Task 5c control flow in generated Performer output."""

import re
import tempfile
from pathlib import Path

from flowsmith.ast.builder import build_ast
from flowsmith.engine import create_annotator
from flowsmith.generator.pad import PADGenerator
from flowsmith.parser import parse_process

raw = parse_process(Path("samples/blueprism/PID_0171.bprelease"))
process = build_ast(raw)
create_annotator().annotate_process(process)
gen = PADGenerator()

with tempfile.TemporaryDirectory() as tmp:
    files = gen.generate_process(process, Path(tmp))
    perf = next((f for f in files if "Performer" in f.name), None)
    content = perf.read_text(encoding="utf-8")

lines = content.splitlines()

print("=== Control flow around lines 338-350 ===")
for i, line in enumerate(lines, 1):
    if 338 <= i <= 352:
        print(f"{i:4}: {line}")

print()
print("=== Skip-GOTO analysis ===")
completed_pos = content.index("LABEL 'Mark Item As Completed'")
exception_pos = content.index("LABEL 'Mark Item As Exception'")
between = content[completed_pos:exception_pos]
print("Between Completed and Exception labels:")
for ln in between.splitlines():
    print(" ", repr(ln))

print()
print("=== Label positions ===")
reset_pos = content.index("LABEL 'Work end'")
print(f"LABEL 'Mark Item As Completed' at char: {completed_pos}")
print(f"LABEL 'Mark Item As Exception' at char: {exception_pos}")
print(f"LABEL 'Work end' at char: {reset_pos}")
print(f"reset > exception? {reset_pos > exception_pos}")

print()
print("=== GOTO target inside Completed section ===")
goto_match = re.search(r"GOTO '([^']+)'", between)
if goto_match:
    target = goto_match.group(1)
    print(f"Found GOTO targeting: {target!r}")
    print(f"  Correct (Work end)? {target == 'Work end'}")
    print(f"  Wrong no-op (Mark Item As Exception)? {target == 'Mark Item As Exception'}")
else:
    print("NO GOTO found in Completed section - BUG!")

print()
print("=== Depth tracking for CALL 'Mark Exception' ===")
depth = 0
for i, line in enumerate(lines, 1):
    stripped = line.strip()
    if stripped.startswith("BLOCK '"):
        depth += 1
    if stripped == "END":
        depth = max(0, depth - 1)
    if "CALL 'Mark Exception'" in stripped:
        print(f"Line {i}, depth={depth}: {line!r}")

print()
print("=== Happy-path trace summary ===")
print("CALL 'Mark Complete' -> GOTO 'Work end' -> LABEL 'Work end' (skips exception section)")
print("=== Error-path trace summary ===")
print(
    "IF flg_ErrorOccurred -> GOTO 'Mark Item As Exception' -> CALL 'Mark Exception' -> falls through to LABEL 'Work end'"
)
