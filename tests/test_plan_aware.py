import sys
import tempfile
import time
import unittest
from pathlib import Path


REPO_DIR = Path(__file__).resolve().parents[1]
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

import app  # noqa: E402


TASK_PLAN = """# Task

## Goal

Ship the history viewer upgrade.

## Requirements

- Keep zero dependencies
- Keep evidence identifiers stable

## Plan

- [x] Extract usage
- [ ] Add briefing

## Status

完成：usage 已交付；briefing 进行中。

## Next Step

Wait for review.
"""

PROGRESS = """## Status

In progress.

## Notes

- usage panel shipped
"""


class ExtractPlanSectionsTests(unittest.TestCase):
    def test_extracts_known_sections_and_ignores_unknown(self):
        sections = app.extract_plan_sections(TASK_PLAN)
        self.assertIn("goal", sections)
        self.assertIn("plan", sections)
        self.assertIn("status", sections)
        self.assertIn("next_step", sections)
        self.assertNotIn("requirements", sections)
        self.assertIn("Ship the history viewer upgrade.", sections["goal"])
        self.assertIn("Wait for review.", sections["next_step"])

    def test_truncates_long_sections(self):
        text = "## Status\n\n" + ("word " * 4000)
        sections = app.extract_plan_sections(text)
        self.assertLessEqual(len(sections["status"]), app.PLAN_SECTION_PREVIEW_CHARS)
        self.assertTrue(sections["status"].endswith("…"))

    def test_empty_input_returns_empty(self):
        self.assertEqual(app.extract_plan_sections(""), {})
        self.assertEqual(app.extract_plan_sections(None), {})


class ScanPlanFilesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def _write(self, rel_path, content):
        path = self.root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_finds_root_plans_and_nested_conventions(self):
        self._write("task_plan.md", TASK_PLAN)
        self._write("progress.md", PROGRESS)
        self._write("plans/alpha/task_plan.md", "## Status\n\nAlpha status.\n")
        self._write("docs/session-plans/001-something.md", "## Goal\n\nDoc plan.\n")
        self._write("README.md", "# Not a plan file")

        items = app.scan_plan_files(str(self.root))
        rels = {item["rel_path"] for item in items}
        self.assertIn("task_plan.md", rels)
        self.assertIn("progress.md", rels)
        self.assertIn("plans/alpha/task_plan.md", rels)
        self.assertIn("docs/session-plans/001-something.md", rels)
        self.assertNotIn("README.md", rels)

    def test_sections_and_mtime_populated_and_sorted_desc(self):
        plan_path = self._write("task_plan.md", TASK_PLAN)
        old = time.time() - 3600
        import os
        os.utime(plan_path, (old, old))
        nested = self._write("plans/alpha/progress.md", PROGRESS)

        items = app.scan_plan_files(str(self.root))
        self.assertEqual(len(items), 2)
        by_rel = {item["rel_path"]: item for item in items}
        self.assertEqual(by_rel["task_plan.md"]["sections"]["goal"], "Ship the history viewer upgrade.")
        self.assertEqual(int(by_rel["task_plan.md"]["mtime_ms"]), int(old * 1000))
        self.assertEqual(by_rel["plans/alpha/progress.md"]["size"], nested.stat().st_size)
        self.assertGreaterEqual(items[0]["mtime_ms"], items[1]["mtime_ms"])

    def test_missing_directory_returns_empty(self):
        self.assertEqual(app.scan_plan_files(str(self.root / "nope")), [])
        self.assertEqual(app.scan_plan_files(""), [])
        self.assertEqual(app.scan_plan_files(None), [])

    def test_caps_file_count(self):
        for i in range(30):
            self._write(f"plans/p{i}/task_plan.md", "## Status\n\nx\n")
        self._write(f"plans/p{'x' * 40}/task_plan.md", "## Status\n\nextra\n")
        items = app.scan_plan_files(str(self.root))
        self.assertLessEqual(len(items), app.PLAN_SCAN_MAX_FILES)

    def test_enumeration_bounded_not_just_result_slice(self):
        # Review fix: directory enumeration itself must be capped, so far more
        # plan folders than the cap still return exactly the cap.
        for i in range(app.PLAN_SCAN_MAX_FILES + 40):
            self._write(f"plans/p{i:03d}/task_plan.md", "## Status\n\nx\n")
        items = app.scan_plan_files(str(self.root))
        self.assertEqual(len(items), app.PLAN_SCAN_MAX_FILES)

    def test_read_is_bounded_by_size_cap(self):
        # Review fix: a huge planning file must not be read in full. A unique
        # marker lives beyond the declared cap; with a bounded read it can
        # never reach the extracted sections.
        huge = "x" * (app.PLAN_FILE_MAX_CHARS + 1000)
        self._write("task_plan.md", huge + "\n## Status\n\nSECRET-BEYOND-CAP\n")
        items = app.scan_plan_files(str(self.root))
        self.assertEqual(len(items), 1)
        serialized = repr(items[0]["sections"])
        self.assertNotIn("SECRET-BEYOND-CAP", serialized)

    def test_read_volume_measured_within_bounds(self):
        # M1/A7: prove the bound with an actual read counter, not just by
        # inspecting returned sections.
        import unittest.mock as mock

        real_open = Path.open
        counter = {"bytes": 0, "opens": 0}

        def counting_open(self, *args, **kwargs):
            handle = real_open(self, *args, **kwargs)
            real_read = handle.read
            counter["opens"] += 1

            def counting_read(n=-1, *a, **k):
                data = real_read(n, *a, **k)
                counter["bytes"] += len(data)
                return data

            handle.read = counting_read
            return handle

        for i in range(3):
            self._write(f"plans/p{i}/task_plan.md", "y" * (app.PLAN_FILE_MAX_CHARS + 5000))

        with mock.patch.object(Path, "open", counting_open):
            items = app.scan_plan_files(str(self.root))

        self.assertEqual(len(items), 3)
        self.assertEqual(counter["opens"], 3)
        self.assertLessEqual(counter["bytes"], 3 * app.PLAN_FILE_MAX_CHARS)

    def test_missing_candidates_do_not_consume_real_file_quota(self):
        # M1/A7: absent files (e.g. dirs that only carry progress/findings)
        # must not eat into the returned-file cap.
        self._write("task_plan.md", TASK_PLAN)
        for i in range(79):
            self._write(f"plans/q{i:02d}/progress.md", PROGRESS)
            self._write(f"plans/q{i:02d}/findings.md", PROGRESS)
        items = app.scan_plan_files(str(self.root))
        names = [item["rel_path"] for item in items]
        self.assertEqual(len(items), app.PLAN_SCAN_MAX_FILES)
        self.assertIn("task_plan.md", names)


class FilterPlanFilesForWindowTests(unittest.TestCase):
    def test_keeps_files_within_margin(self):
        day = 86_400_000
        items = [
            {"rel_path": "a.md", "mtime_ms": 10 * day},
            {"rel_path": "b.md", "mtime_ms": 40 * day},
        ]
        kept = app.filter_plan_files_for_window(items, start_ms=15 * day, end_ms=20 * day)
        self.assertEqual([item["rel_path"] for item in kept], ["a.md"])

    def test_no_window_keeps_everything(self):
        items = [{"rel_path": "a.md", "mtime_ms": 1}]
        self.assertEqual(len(app.filter_plan_files_for_window(items)), 1)


class SessionPlanWindowTests(unittest.TestCase):
    def test_session_metadata_window_filters_plans(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        project = root / "project"
        project.mkdir(parents=True)

        plan_path = project / "task_plan.md"
        plan_path.write_text(TASK_PLAN, encoding="utf-8")

        sessions_dir = root / "sessions"
        sessions_dir.mkdir()
        (root / "data").mkdir()
        indexer = app.Indexer(
            sessions_dir=sessions_dir,
            data_dir=root / "data",
            source="codex",
            db_filename="index.sqlite",
            parse_file_fn=lambda _: None,
            parser_version=1,
            recall_db_path=None,
        )
        self.addCleanup(indexer.conn.close)

        # Session window: 2026-09-01 .. 2026-09-02; plan mtime: 2026-09-01.
        window_start = 1_788_259_200_000  # 2026-09-01T00:00:00Z
        window_end = 1_788_345_600_000    # 2026-09-02T00:00:00Z
        with indexer.lock:
            indexer.conn.execute(
                """
                INSERT INTO sessions
                (id, file_path, start_ts_ms, end_ts_ms, cwd, title, message_count,
                 mtime, search_blob, parser_version, pinned)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("sess-1", str(root / "none.jsonl"), window_start, window_end,
                 str(project), "Plan-aware session", 1, 0.0, "", 1, 0),
            )

        import os
        os.utime(plan_path, (window_start / 1000, window_start / 1000))
        meta = indexer.get_session_metadata("sess-1")
        self.assertEqual(meta["cwd"], str(project))
        items = app.filter_plan_files_for_window(
            app.scan_plan_files(meta["cwd"]), meta["start_ts_ms"], meta["end_ts_ms"]
        )
        self.assertEqual([item["name"] for item in items], ["task_plan.md"])

        # A plan far outside the session window must be filtered out.
        import os
        far = window_start / 1000 - 90 * 86_400
        os.utime(plan_path, (far, far))
        items_far = app.filter_plan_files_for_window(
            app.scan_plan_files(meta["cwd"]), meta["start_ts_ms"], meta["end_ts_ms"]
        )
        self.assertEqual(items_far, [])


if __name__ == "__main__":
    unittest.main()
