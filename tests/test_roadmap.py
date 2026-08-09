#!/usr/bin/env python3
"""Tests for the roadmap.sh flattener and tracker.

Graph tests run against fixtures (offline, fast). Pass --live to additionally
validate every published roadmap against the real endpoints.

    python3 tests/test_roadmap.py
    python3 tests/test_roadmap.py --live
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import roadmap as R  # noqa: E402


def node(nid, ntype, x, y, label, w=150, h=45):
    return {
        "id": nid,
        "type": ntype,
        "position": {"x": x, "y": y},
        "style": {"width": w, "height": h},
        "data": {"label": label},
    }


def edge(src, dst):
    return {"source": src, "target": dst}


class FlattenTest(unittest.TestCase):
    def test_edges_define_topic_order(self):
        doc = {
            "nodes": [
                node("c", "topic", 0, 900, "Third"),
                node("a", "topic", 0, 0, "First"),
                node("b", "topic", 0, 450, "Second"),
            ],
            "edges": [edge("a", "b"), edge("b", "c")],
        }
        self.assertEqual(
            [s["title"] for s in R.flatten(doc)], ["First", "Second", "Third"]
        )

    def test_layout_order_when_edges_absent(self):
        doc = {
            "nodes": [
                node("c", "topic", 0, 900, "Third"),
                node("a", "topic", 0, 0, "First"),
                node("b", "topic", 0, 450, "Second"),
            ],
            "edges": [],
        }
        self.assertEqual(
            [s["title"] for s in R.flatten(doc)], ["First", "Second", "Third"]
        )

    def test_explicit_edge_wins_over_geometry(self):
        # 'Sub' sits directly under 'Near' but is wired to 'Far'.
        doc = {
            "nodes": [
                node("far", "topic", 0, 0, "Far"),
                node("near", "topic", 0, 500, "Near"),
                node("sub", "subtopic", 0, 560, "Sub"),
            ],
            "edges": [edge("far", "near"), edge("far", "sub")],
        }
        sub = [s for s in R.flatten(doc) if s["title"] == "Sub"][0]
        self.assertEqual(sub["parent"], "Far")

    def test_subtopic_falls_back_to_nearest_topic(self):
        doc = {
            "nodes": [
                node("t1", "topic", 0, 0, "Alpha"),
                node("t2", "topic", 600, 0, "Beta"),
                node("s", "subtopic", 610, 80, "Child"),
            ],
            "edges": [],
        }
        child = [s for s in R.flatten(doc) if s["title"] == "Child"][0]
        self.assertEqual(child["parent"], "Beta")

    def test_section_membership_groups_subtopics(self):
        # Two subtopics inside a section box owned by 'Owner', even though
        # 'Decoy' is vertically closer to them.
        doc = {
            "nodes": [
                node("owner", "topic", 0, 0, "Owner"),
                node("sec", "section", -10, -10, "", w=400, h=300),
                node("s1", "subtopic", 20, 100, "One"),
                node("s2", "subtopic", 20, 200, "Two"),
                node("decoy", "topic", 900, 150, "Decoy"),
            ],
            "edges": [],
        }
        steps = R.flatten(doc)
        parents = {s["title"]: s["parent"] for s in steps if s["kind"] == "subtopic"}
        self.assertEqual(parents, {"One": "Owner", "Two": "Owner"})

    def test_section_caption_becomes_group(self):
        doc = {
            "nodes": [
                node("owner", "topic", 0, 0, "Owner"),
                node("sec", "section", -10, 60, "", w=300, h=200),
                node("lbl", "label", -10, 20, "Hashing Algorithms", w=200, h=30),
                node("s1", "subtopic", 20, 100, "MD5"),
            ],
            "edges": [],
        }
        md5 = [s for s in R.flatten(doc) if s["title"] == "MD5"][0]
        self.assertEqual(md5["group"], "Hashing Algorithms")

    def test_no_node_is_dropped_and_none_duplicated(self):
        doc = {
            "nodes": [
                node("t", "topic", 0, 0, "T"),
                node("orphan", "subtopic", 5000, 5000, "Orphan"),
                node("s", "subtopic", 0, 60, "S"),
                node("blank", "subtopic", 0, 120, "   "),
                node("deco", "paragraph", 0, 200, "ignore me"),
            ],
            "edges": [],
        }
        titles = [s["title"] for s in R.flatten(doc)]
        self.assertEqual(sorted(titles), ["Orphan", "S", "T"])
        self.assertEqual(len(titles), len(set(titles)))

    def test_disjoint_components_are_all_reached(self):
        doc = {
            "nodes": [
                node("a", "topic", 0, 0, "A"),
                node("b", "topic", 0, 100, "B"),
                node("x", "topic", 0, 500, "X"),
                node("y", "topic", 0, 600, "Y"),
            ],
            "edges": [edge("a", "b"), edge("x", "y")],
        }
        self.assertEqual([s["title"] for s in R.flatten(doc)], ["A", "B", "X", "Y"])

    def test_cyclic_edges_do_not_hang_or_lose_nodes(self):
        doc = {
            "nodes": [
                node("a", "topic", 0, 0, "A"),
                node("b", "topic", 0, 100, "B"),
                node("c", "topic", 0, 200, "C"),
            ],
            "edges": [edge("a", "b"), edge("b", "c"), edge("c", "a")],
        }
        self.assertEqual(sorted(s["title"] for s in R.flatten(doc)), ["A", "B", "C"])

    def test_empty_graph(self):
        self.assertEqual(R.flatten({"nodes": [], "edges": []}), [])


class ContentTest(unittest.TestCase):
    def test_inline_resource_links_are_extracted(self):
        md = (
            "# ACID\n\nFour guarantees.\n\nVisit the following resources:\n\n"
            "- [@article@What is ACID?](https://example.com/acid)\n"
            "- [@video@ACID explained](https://example.com/vid)\n"
        )
        body, res = R.split_content(md)
        self.assertNotIn("example.com", body)
        self.assertNotIn("Visit the following", body)
        self.assertIn("Four guarantees.", body)
        self.assertEqual([r["type"] for r in res], ["article", "video"])

    def test_api_resources_merge_without_duplicates(self):
        md = "# X\n\n- [@article@Dup](https://example.com/a)\n"
        api = [{"type": "official", "title": "Dup", "url": "https://example.com/a"}]
        _, res = R.split_content(md, api)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["type"], "official")

    def test_empty_markdown(self):
        self.assertEqual(R.split_content(None), ("", []))
        self.assertEqual(R.split_content("", [{"url": "u"}])[1], [{"url": "u"}])


class ProgressTest(unittest.TestCase):
    def setUp(self):
        self.steps = [
            {"id": "a", "title": "A", "kind": "topic", "parent": None, "group": None},
            {"id": "b", "title": "B", "kind": "topic", "parent": None, "group": None},
            {"id": "c", "title": "C", "kind": "topic", "parent": None, "group": None},
        ]

    def test_skipped_does_not_count_as_done(self):
        rm = {"done": ["a"], "skipped": ["b"], "cursor": 0}
        p = R.progress_of(rm, self.steps)
        self.assertEqual((p["done"], p["skipped"], p["remaining"]), (1, 1, 2))

    def test_next_index_skips_done_and_skipped(self):
        rm = {"done": ["a"], "skipped": ["b"], "cursor": 0}
        self.assertEqual(R.next_index(rm, self.steps), 2)

    def test_next_index_none_when_exhausted(self):
        rm = {"done": ["a", "b", "c"], "skipped": [], "cursor": 0}
        self.assertIsNone(R.next_index(rm, self.steps))


class StateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._orig = (R.HOME, R.STATE_PATH, R.CACHE)
        R.HOME = self.tmp
        R.STATE_PATH = os.path.join(self.tmp, "state.json")
        R.CACHE = os.path.join(self.tmp, "cache")

    def tearDown(self):
        R.HOME, R.STATE_PATH, R.CACHE = self._orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_roundtrip(self):
        state = R.load_state()
        R.track(state, "backend")["done"].append("x")
        R.save_state(state)
        self.assertEqual(R.load_state()["roadmaps"]["backend"]["done"], ["x"])

    def test_corrupt_state_does_not_crash(self):
        os.makedirs(self.tmp, exist_ok=True)
        with open(R.STATE_PATH, "w") as f:
            f.write("{not json")
        self.assertEqual(R.load_state()["roadmaps"], {})

    def test_missing_state_returns_empty(self):
        self.assertIsNone(R.load_state()["active"])


class LiveTest(unittest.TestCase):
    """Only runs with --live. Hits roadmap.sh."""

    def test_every_published_roadmap_flattens_losslessly(self):
        failures = []
        for slug in R.KNOWN_ROADMAPS:
            try:
                doc = R.fetch_roadmap(slug)
                steps = R.flatten(doc)
                ids = [s["id"] for s in steps]
                learnable = [
                    n
                    for n in doc["nodes"]
                    if n["type"] in ("topic", "subtopic")
                    and (n.get("data") or {}).get("label", "").strip()
                ]
                if not steps:
                    failures.append("%s: no steps" % slug)
                if len(ids) != len(set(ids)):
                    failures.append("%s: duplicate ids" % slug)
                if len(steps) != len(learnable):
                    failures.append(
                        "%s: %d steps vs %d nodes" % (slug, len(steps), len(learnable))
                    )
            except Exception as exc:
                failures.append("%s: %r" % (slug, exc))
        self.assertEqual(failures, [], "\n".join(failures))


if __name__ == "__main__":
    live = "--live" in sys.argv
    if live:
        sys.argv.remove("--live")
    else:
        LiveTest.test_every_published_roadmap_flattens_losslessly = (
            unittest.skip("use --live")(
                LiveTest.test_every_published_roadmap_flattens_losslessly
            )
        )
    unittest.main(verbosity=2)
