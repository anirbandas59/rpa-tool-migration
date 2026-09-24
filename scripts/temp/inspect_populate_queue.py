"""
One-off diagnostic (training-exercise scratch script, NOT part of the flowsmith
pipeline) — dumps every stage in the 'Populate Queue' subsheet of
PID_171_US_Process_LIMS_Prelude directly from the raw .bprelease XML, including
its display geometry (x, y, width, height), so BLOCK-stage containment
(which stages sit inside which Block/try-scope rectangle) can be resolved
visually instead of guessed. bp_html_report_v3's on_exception edge list gives
every Block x every Recover on the page (a documented parser limitation, see
CLAUDE.md's Block/Recover rule) - this script exists to disambiguate that
for the specific 'Populate Queue' page using real coordinates.

Run: uv run python scripts/temp/inspect_populate_queue.py
"""

from lxml import etree

NS = "http://www.blueprism.co.uk/product/process"
BP = f"{{{NS}}}"

RELEASE_PATH = "samples/blueprism/PID_0171.bprelease"


def main() -> None:
    tree = etree.parse(RELEASE_PATH)
    root = tree.getroot()

    # Find the process element for PID_171_US_Process_LIMS_Prelude
    # (name lives as an attribute on <process>, not a child <name> element)
    proc_el = None
    for el in root.iter(f"{BP}process"):
        pname = el.get("name")
        if pname and "LIMS_Prelude" in pname:
            proc_el = el
            break
    if proc_el is None:
        print("Process not found")
        return

    # Find subsheet id for 'Populate Queue'
    target_subsheet_id = None
    for sub in proc_el.iter(f"{BP}subsheet"):
        _sid = sub.get("subsheetid") or sub.findtext(f"{BP}subsheetid")
        name_el = sub.find(f"{BP}name")
        # subsheets can appear differently; try both forms
    # subsheets are usually listed under <subsheets><subsheet subsheetid=".."><name>..
    subsheets_el = proc_el.find(f"{BP}subsheets")
    if subsheets_el is not None:
        for sub in subsheets_el.findall(f"{BP}subsheet"):
            name_el = sub.find(f"{BP}name")
            if name_el is not None and name_el.text == "Populate Queue":
                target_subsheet_id = sub.get("subsheetid")
                break

    print("Target subsheet id:", target_subsheet_id)

    stages_el = proc_el.find(f"{BP}stages")
    if stages_el is None:
        print("No stages element found")
        return

    rows = []
    for stage in stages_el.findall(f"{BP}stage"):
        subsheetid = stage.findtext(f"{BP}subsheetid")
        if target_subsheet_id and subsheetid != target_subsheet_id:
            continue
        name = stage.findtext(f"{BP}name")
        stype = stage.get("type")
        stage_id = stage.get("stageid")
        displayx = stage.findtext(f"{BP}displayx")
        displayy = stage.findtext(f"{BP}displayy")
        # Block/region stages sometimes carry width/height under a nested element
        width = stage.findtext(f"{BP}width") or stage.findtext(f"{BP}displaywidth")
        height = stage.findtext(f"{BP}height") or stage.findtext(f"{BP}displayheight")
        groupid = stage.findtext(f"{BP}groupid")
        onsuccess = stage.findtext(f"{BP}onsuccess")
        rows.append(
            {
                "id": stage_id,
                "name": name,
                "type": stype,
                "x": displayx,
                "y": displayy,
                "w": width,
                "h": height,
                "groupid": groupid,
                "onsuccess": onsuccess,
            }
        )

    for r in rows:
        print(r)


if __name__ == "__main__":
    main()
