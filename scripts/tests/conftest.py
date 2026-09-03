"""Shared test fixtures for bp_html_report and bp_common tests."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def make_release_result():
    def _factory(processes=None, objects=None):
        processes = processes or []
        objects = objects or []

        def _wrap(artefact_type, items):
            results = []
            for item in items:
                name = item.get("name", "Test Artefact")
                pages = item.get("pages", {})
                stages = item.get("stages", [])
                stage_by_id = {s["id"]: s for s in stages}
                explicit_edges = sum(
                    1 for s in stages if s.get("onsuccess") or s.get("ontrue") or s.get("onfalse")
                )
                results.append(
                    {
                        "meta": {
                            "name": name,
                            "artefact_type": artefact_type,
                            "version": "1.0",
                            "bpversion": "7.0",
                            "runmode": None,
                            "narrative": None,
                            "published": None,
                            "groups": [],
                        },
                        "pages": pages,
                        "stages": stages,
                        "edges": [],
                        "stage_by_id": stage_by_id,
                        "stats": {
                            "pages": len(pages),
                            "parsed": len(stages),
                            "skipped": 0,
                            "explicit_edges": explicit_edges,
                            "implicit_edges": 0,
                            "total_edges": explicit_edges,
                        },
                    }
                )
            return results

        procs = _wrap("process", processes)
        objs = _wrap("object", objects)
        total_stages = sum(len(r["stages"]) for r in procs + objs)
        total_edges = sum(r["stats"]["explicit_edges"] for r in procs + objs)

        return {
            "release_meta": {
                "name": "Test Release",
                "created": "2025-01-01T00:00:00",
                "created_by": "test",
                "package_name": "Test Package",
                "package_id": "00000000",
                "declared_count": len(procs) + len(objs),
            },
            "stats": {
                "process_count": len(procs),
                "object_count": len(objs),
                "env_var_count": 0,
                "group_count": 0,
                "total_parsed_stages": total_stages,
                "total_edges": total_edges,
                "error_count": 0,
            },
            "processes": procs,
            "objects": objs,
            "environment_variables": [],
            "groups": [],
            "errors": [],
        }

    return _factory
