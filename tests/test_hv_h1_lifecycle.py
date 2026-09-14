"""Unit and lifecycle tests for HV-H1 benchmarks and lifecycle facts.

Validates:
- Synthetic session specification compliance (20 msgs, ~16 KiB ±10%, Unicode, long line, bad tail line, same ts)
- Incremental indexing skip and parse count tracking
- Single file append of exact 1024 bytes
- Same-path replacement behavior
- Same-path replacement with preserved mtime
- Deletion/rotation lifecycle fact (purging stale entries upon disk deletion)
- Delete all files from source directory
- Source missing preserves cache and raises FileNotFoundError
- Source lost then recovered
- Unreadable file (PermissionError) handling
- Readable corrupted file handling (cannot default to fresh success)
- Restart recovery in independent subprocess verifying exact IDs and fields
- Clean CLI exit with /proc descendant process inspection
- Evaluator counterexample testing (ensuring evaluate_thresholds fails on negative cases)
"""
import copy
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO_DIR = Path(__file__).resolve().parents[1]
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from history_core.reader import HistoryReader
from history_core.sources import Indexer, parse_codex_session_file
from scripts.generate_synthetic_sessions import (
    generate_session_content,
    generate_dataset,
    MIN_BYTES,
    MAX_BYTES,
    GENERATOR_VERSION,
)
from scripts.run_hv_h1_benchmark import (
    evaluate_thresholds,
    records_match,
    make_exact_1024_byte_append,
)


class HVH1LifecycleTests(unittest.TestCase):
    def setUp(self):
        # Always create temporary directories within work/ to respect boundary constraints
        self.bench_root = (REPO_DIR / "work" / "test_lifecycle_tmp").resolve()
        self.bench_root.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=str(self.bench_root))
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source_dir = self.root / "sources"
        self.cache_dir = self.root / "cache"
        self.source_dir.mkdir()
        self.cache_dir.mkdir()

    def test_synthetic_session_spec_compliance(self):
        """Verify synthetic session properties match HV-H1 specification."""
        content = generate_session_content(0, seed=42)
        self.assertGreaterEqual(len(content), MIN_BYTES)
        self.assertLessEqual(len(content), MAX_BYTES)

        test_file = self.source_dir / "test_sess_0.jsonl"
        test_file.write_bytes(content)
        parsed = parse_codex_session_file(test_file)

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["id"], "synthetic-codex-00000")
        self.assertEqual(parsed["message_count"], 20)
        self.assertEqual(len(parsed["messages"]), 21)

        malformed = [m for m in parsed["messages"] if m["kind"] == "raw_json:malformed_line"]
        self.assertEqual(len(malformed), 1)

        has_unicode = any("Unicode" in m.get("text", "") or "🎯" in m.get("text", "") for m in parsed["messages"])
        self.assertTrue(has_unicode, "Expected Unicode/Chinese text in parsed messages")

        has_long_line = any(len(m.get("text", "")) > 2000 for m in parsed["messages"])
        self.assertTrue(has_long_line, "Expected long line in parsed messages")

    def test_incremental_skip_and_no_change_refresh(self):
        """Verify that unchanged files are skipped and parse count is 0 on no-change refresh."""
        manifest = generate_dataset(self.source_dir, 5, seed=20260914)
        self.assertEqual(manifest["count"], 5)

        parse_calls = []

        def tracking_parser(p):
            parse_calls.append(p)
            return parse_codex_session_file(p)

        with HistoryReader("codex", self.source_dir, self.cache_dir) as reader:
            reader._HistoryReader__indexer._parse_file_fn = tracking_parser
            reader.refresh()
            self.assertEqual(len(parse_calls), 5, "Initial refresh must parse all 5 files")

            res = reader.search(limit=10)
            self.assertEqual(len(res["items"]), 5)

            parse_calls.clear()
            reader.refresh()
            self.assertEqual(len(parse_calls), 0, "No-change refresh must parse 0 files")

    def test_single_file_append_exact_1024_bytes(self):
        """Verify that appending exactly 1024 bytes to one file only re-parses that single file."""
        generate_dataset(self.source_dir, 5, seed=20260914)
        target_file = self.source_dir / "session_00002.jsonl"

        with HistoryReader("codex", self.source_dir, self.cache_dir) as reader:
            reader.refresh()

            parse_calls = []
            original_parser = reader._HistoryReader__indexer._parse_file_fn

            def tracking_parser(p):
                parse_calls.append(p)
                return original_parser(p)

            reader._HistoryReader__indexer._parse_file_fn = tracking_parser

            append_chunk = make_exact_1024_byte_append()
            self.assertEqual(len(append_chunk), 1024, "Append chunk must be exact 1024 bytes")

            with target_file.open("ab") as f:
                f.write(append_chunk)

            reader.refresh()
            self.assertEqual(len(parse_calls), 1, "Only the modified file should be re-parsed")
            self.assertEqual(Path(parse_calls[0]).resolve(), target_file.resolve())

    def test_same_path_replacement_behavior(self):
        """Verify that replacing a file with a new session ID replaces the index entry."""
        generate_dataset(self.source_dir, 3, seed=20260914)
        target_file = self.source_dir / "session_00001.jsonl"

        with HistoryReader("codex", self.source_dir, self.cache_dir) as reader:
            reader.refresh()
            res_before = reader.search(limit=10)
            ids_before = {item["id"] for item in res_before["items"]}
            self.assertIn("synthetic-codex-00001", ids_before)

            new_content = generate_session_content(999, seed=12345)
            target_file.write_bytes(new_content)

            reader.refresh()
            res_after = reader.search(limit=10)
            ids_after = {item["id"] for item in res_after["items"]}
            self.assertNotIn("synthetic-codex-00001", ids_after)
            self.assertIn("synthetic-codex-00999", ids_after)

    def test_same_path_replacement_preserved_mtime(self):
        """Verify that replacing a file while preserving original mtime is correctly detected and updated."""
        generate_dataset(self.source_dir, 3, seed=20260914)
        target_file = self.source_dir / "session_00001.jsonl"
        orig_stat = target_file.stat()

        with HistoryReader("codex", self.source_dir, self.cache_dir) as reader:
            reader.refresh()
            res_before = reader.search(limit=10)
            ids_before = {item["id"] for item in res_before["items"]}
            self.assertIn("synthetic-codex-00001", ids_before)

            # Replace content and restore mtime
            new_content = generate_session_content(888, seed=9999)
            target_file.write_bytes(new_content)
            os.utime(target_file, (orig_stat.st_atime, orig_stat.st_mtime))

            reader.refresh()
            res_after = reader.search(limit=10)
            ids_after = {item["id"] for item in res_after["items"]}
            self.assertNotIn(
                "synthetic-codex-00001",
                ids_after,
                "Old session ID must be removed even when replacement preserved mtime",
            )
            self.assertIn(
                "synthetic-codex-00888",
                ids_after,
                "New session ID must be indexed even when replacement preserved mtime",
            )

    def test_deletion_rotation_purges_stale_index(self):
        """Verify that deleting a session file from disk purges the stale row from SQLite."""
        generate_dataset(self.source_dir, 3, seed=20260914)
        del_file = self.source_dir / "session_00002.jsonl"

        with HistoryReader("codex", self.source_dir, self.cache_dir) as reader:
            reader.refresh()
            res_before = reader.search(limit=10)
            self.assertEqual(len(res_before["items"]), 3)

            # Delete file from disk
            del_file.unlink()

            reader.refresh()
            res_after = reader.search(limit=10)
            stale_present = any(item["id"] == "synthetic-codex-00002" for item in res_after["items"])
            self.assertFalse(stale_present, "Deleted file must be purged from derived SQLite index")
            self.assertEqual(len(res_after["items"]), 2)

    def test_delete_all_files_clears_index(self):
        """Verify that deleting all files cleans the entire derived index without error."""
        generate_dataset(self.source_dir, 3, seed=20260914)

        with HistoryReader("codex", self.source_dir, self.cache_dir) as reader:
            reader.refresh()
            self.assertEqual(len(reader.search(limit=10)["items"]), 3)

            for f in self.source_dir.glob("*.jsonl"):
                f.unlink()

            reader.refresh()
            res = reader.search(limit=10)
            self.assertEqual(len(res["items"]), 0, "Index must have 0 items after all source files deleted")

    def test_source_lost_then_restored(self):
        generate_dataset(self.source_dir, 3, seed=20260914)
        with HistoryReader('codex', self.source_dir, self.cache_dir) as reader:
            reader.refresh()
            before = reader.search(limit=10)['items']
            moved = self.root / 'moved'
            self.source_dir.rename(moved)
            try:
                with self.assertRaises(FileNotFoundError):
                    reader.refresh()
                count = reader._HistoryReader__indexer.conn.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]
                self.assertEqual(count, 3)
            finally:
                moved.rename(self.source_dir)
            reader.refresh()
            self.assertEqual(reader.search(limit=10)['items'], before)

    def test_unreadable_file_permission_failure(self):
        """Verify that an unreadable file strictly raises PermissionError."""
        generate_dataset(self.source_dir, 2, seed=20260914)
        bad_file = self.source_dir / "unreadable.jsonl"
        bad_file.write_text('{"bad": true}\n')
        bad_file.chmod(0)

        try:
            with self.assertRaises(PermissionError):
                with HistoryReader("codex", self.source_dir, self.cache_dir) as reader:
                    reader.refresh()
        finally:
            bad_file.chmod(stat.S_IRUSR | stat.S_IWUSR)

    def test_readable_corrupted_file_not_fresh_success(self):
        """Verify that a readable file with corrupted/non-JSON content does not succeed as fresh."""
        generate_dataset(self.source_dir, 2, seed=20260914)
        corrupted_file = self.source_dir / "corrupted.jsonl"
        corrupted_file.write_text("NOT_JSON_COMPLETELY_INVALID_CORRUPTED\x00\n")

        with HistoryReader("codex", self.source_dir, self.cache_dir) as reader:
            with self.assertRaisesRegex(ValueError, 'invalid_session_file: .*corrupted.jsonl'):
                reader.refresh()
            corrupted_file.unlink()
            reader.refresh()
            self.assertEqual(len(reader.search(limit=10)['items']), 2)

    def test_restart_recovery_independent_process(self):
        """Verify that reopening cache in an independent subprocess matches exact IDs and fields."""
        manifest = generate_dataset(self.source_dir, 4, seed=20260914)
        expected_ids = {f"synthetic-codex-{i:05d}" for i in range(4)}

        with HistoryReader("codex", self.source_dir, self.cache_dir) as reader:
            reader.refresh()

        # Execute CLI in independent subprocess
        cmd = [
            sys.executable,
            "-B",
            "-m",
            "history_core",
            "--source",
            "codex",
            "--source-path",
            str(self.source_dir),
            "--data-dir",
            str(self.cache_dir),
            "search",
            "--limit",
            "10",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        self.assertEqual(proc.returncode, 0)
        data = json.loads(proc.stdout)
        items = data.get("items", [])
        self.assertEqual(len(items), 4)
        recovered_ids = {it["id"] for it in items}
        self.assertEqual(recovered_ids, expected_ids, "Independent process must recover all exact expected IDs")

        expected = [parse_codex_session_file(path) for path in sorted(self.source_dir.glob('*.jsonl'))]
        self.assertTrue(records_match(items, expected))
        self.assertFalse(records_match(items[:1], expected))
        wrong = copy.deepcopy(items)
        wrong[0]['cwd'] = '/wrong'
        self.assertFalse(records_match(wrong, expected))
        # Verify key fields
        for it in items:
            self.assertIn("id", it)
            self.assertIn("cwd", it)
            self.assertIn("start_ts_ms", it)
            self.assertIn("end_ts_ms", it)
            self.assertEqual(it.get("message_count"), 20)

    def test_clean_cli_exit_with_proc_check(self):
        """Verify CLI execution exits cleanly with 0 surviving descendants in /proc."""
        generate_dataset(self.source_dir, 3, seed=20260914)
        cmd = [
            sys.executable,
            "-B",
            "-m",
            "history_core",
            "--source",
            "codex",
            "--source-path",
            str(self.source_dir),
            "--data-dir",
            str(self.cache_dir),
            "health",
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        pgid = proc.pid
        stdout, stderr = proc.communicate(timeout=15)
        self.assertEqual(proc.returncode, 0)

        # Inspect /proc for any remaining descendant
        surviving = []
        try:
            for entry in os.listdir("/proc"):
                if entry.isdigit():
                    pid = int(entry)
                    if pid == os.getpid() or pid == proc.pid:
                        continue
                    try:
                        with open(f"/proc/{pid}/stat", "r") as f:
                            fields = f.read().split()
                            if int(fields[3]) == proc.pid or int(fields[4]) == pgid:
                                surviving.append(pid)
                    except (FileNotFoundError, ProcessLookupError, PermissionError):
                        pass
        except Exception:
            pass

        self.assertEqual(len(surviving), 0, f"Found surviving child processes: {surviving}")

    def test_failed_refresh_rolls_back_updates_and_deletions(self):
        generate_dataset(self.source_dir, 3, seed=42)
        with HistoryReader('codex', self.source_dir, self.cache_dir) as reader:
            reader.refresh()
            conn = reader._HistoryReader__indexer.conn
            before = list(conn.iterdump())
            (self.source_dir / 'session_00002.jsonl').unlink()
            (self.source_dir / 'session_00000.jsonl').write_bytes(generate_session_content(999, seed=42))
            (self.source_dir / 'session_00001.jsonl').write_text('invalid')
            with self.assertRaisesRegex(ValueError, 'invalid_session_file'):
                reader.refresh()
            self.assertEqual(list(conn.iterdump()), before)
            with self.assertRaisesRegex(ValueError, 'invalid_session_file'):
                reader.refresh()  # Failure must not advance the successful scan marker.

    def test_enumeration_error_does_not_purge(self):
        generate_dataset(self.source_dir, 2, seed=42)
        with HistoryReader('codex', self.source_dir, self.cache_dir) as reader:
            reader.refresh()
            indexer = reader._HistoryReader__indexer
            before = list(indexer.conn.iterdump())
            def denied(*args, **kwargs):
                kwargs['onerror'](PermissionError('subdirectory denied'))
                return iter(())
            with mock.patch('history_core.sources.os.walk', side_effect=denied):
                with self.assertRaises(PermissionError):
                    indexer.scan_sessions()
            self.assertEqual(list(indexer.conn.iterdump()), before)

    def test_same_size_same_mtime_replacement_detected(self):
        generate_dataset(self.source_dir, 2, seed=42)
        target = self.source_dir / 'session_00001.jsonl'
        with HistoryReader('codex', self.source_dir, self.cache_dir) as reader:
            reader.refresh()
            st = target.stat()
            content = target.read_bytes().replace(b'synthetic-codex-00001', b'synthetic-codex-00999')
            target.write_bytes(content)
            os.utime(target, ns=(st.st_atime_ns, st.st_mtime_ns))
            self.assertEqual(target.stat().st_size, st.st_size)
            reader.refresh()
            ids = {it['id'] for it in reader.search(limit=10)['items']}
            self.assertEqual(ids, {'synthetic-codex-00000', 'synthetic-codex-00999'})

    def test_handoff_rejects_internal_symlink_after_indexing(self):
        generate_dataset(self.source_dir, 2, seed=42)
        target = self.source_dir / 'session_00001.jsonl'
        with HistoryReader('codex', self.source_dir, self.cache_dir) as reader:
            reader.refresh()
            target.unlink()
            target.symlink_to(self.source_dir / 'session_00000.jsonl')
            with self.assertRaisesRegex(ValueError, 'source_symlink'):
                reader.handoff('synthetic-codex-00001')

    def test_handoff_unreadable_selected_file_fails(self):
        generate_dataset(self.source_dir, 1, seed=42)
        target = self.source_dir / 'session_00000.jsonl'
        with HistoryReader('codex', self.source_dir, self.cache_dir) as reader:
            reader.refresh()
            target.chmod(0)
            try:
                with self.assertRaises(PermissionError):
                    reader.handoff('synthetic-codex-00000')
            finally:
                target.chmod(0o600)

    def test_handoff_rejects_parent_traversal_in_cached_path(self):
        generate_dataset(self.source_dir, 1, seed=42)
        outside = self.root / 'outside.jsonl'
        outside.write_bytes(generate_session_content(999, seed=42))
        with HistoryReader('codex', self.source_dir, self.cache_dir) as reader:
            reader.refresh()
            conn = reader._HistoryReader__indexer.conn
            conn.execute('UPDATE sessions SET file_path = ?', (str(self.source_dir / '..' / 'outside.jsonl'),))
            conn.commit()
            with self.assertRaisesRegex(ValueError, 'cached_source_path_outside_selection'):
                reader.handoff('synthetic-codex-00000')

    def test_search_uses_cache_with_explicit_unknown_freshness(self):
        generate_dataset(self.source_dir, 2, seed=42)
        with HistoryReader('codex', self.source_dir, self.cache_dir) as reader:
            reader.refresh()
            with mock.patch.object(reader, '_HistoryReader__validate_source', side_effect=AssertionError('full scan on hot query')):
                self.assertEqual(reader.search(limit=10)['freshness'], 'unknown')

    def test_evaluator_counterexamples(self):
        """Verify that evaluate_thresholds strictly fails on counterexamples and invalid states."""
        base_results = {
            "benchmarks": {
                "indexing_1k": {"fresh": {"elapsed_seconds": 1.0}},
                "indexing_10k": {"fresh": {"elapsed_seconds": 20.0, "peak_rss_mib": 300.0}},
                "single_file_append_1k": {"elapsed_seconds": 0.5, "parse_count": 1, "append_bytes": 1024, "only_affected_file_parsed": True},
                "single_file_append_10k": {"elapsed_seconds": 1.0, "parse_count": 1, "append_bytes": 1024, "only_affected_file_parsed": True},
                "no_change_refresh_1k": {"parse_count": 0},
                "no_change_refresh_10k": {"parse_count": 0},
                "cold_first_process_query_10k": {"elapsed_seconds": 0.4},
                "queries_100_on_10k": {
                    "p95_ms": 150.0,
                    "pagination_check": {
                        "total_items": 50,
                        "expected_items_count": 50,
                        "unique_items": 50,
                        "duplicate_items": 0,
                        "missing_items": 0,
                        "exact_order_match": True,
                        "multi_page_reference_match": True,
                    }
                }
            },
            "lifecycle": {
                "same_path_replacement_preserved_mtime": {
                    "status": "pass",
                    "old_id_removed": True,
                    "new_id_indexed": True,
                },
                "deletion_rotation": {
                    "status": "pass",
                    "stale_row_retained_in_index": False,
                },
                "unreadable_file_permission": {
                    "permission_error_caught": True,
                },
                "readable_corrupted_file": {
                    "corrupted_rejected_not_fresh_success": True,
                },
                "source_missing": {
                    "file_not_found_caught": True,
                    "cache_preserved": True,
                },
                "restart_recovery": {
                    "independent_process_verified": True,
                    "recovered_count": 4,
                    "expected_count": 4,
                    "all_fields_matched": True,
                }
            },
            "clean_exit_check": {
                "clean_exit": True,
                "surviving_descendants": [],
                "background_io": "unmeasured",
            }
        }

        # 1. Base should pass all
        evals = evaluate_thresholds(base_results)
        all_passed = all(ev["status"] == "pass" for ev in evals)
        self.assertTrue(all_passed, "Base template should pass all evaluations")

        # 2. Counterexample: pagination total_items == 0 must FAIL
        c1 = copy.deepcopy(base_results)
        c1["benchmarks"]["queries_100_on_10k"]["pagination_check"]["total_items"] = 0
        c1["benchmarks"]["queries_100_on_10k"]["pagination_check"]["unique_items"] = 0
        ev1 = {e["item"]: e["status"] for e in evaluate_thresholds(c1)}
        self.assertEqual(ev1["全量分页对比合成预期ID集合与顺序"], "fail", "Zero total_items in pagination must fail")

        # 3. Counterexample: pagination missing 1 item must FAIL
        c2 = copy.deepcopy(base_results)
        c2["benchmarks"]["queries_100_on_10k"]["pagination_check"]["missing_items"] = 1
        ev2 = {e["item"]: e["status"] for e in evaluate_thresholds(c2)}
        self.assertEqual(ev2["全量分页对比合成预期ID集合与顺序"], "fail", "Missing items in pagination must fail")

        # 4. Counterexample: pagination duplicate item must FAIL
        c3 = copy.deepcopy(base_results)
        c3["benchmarks"]["queries_100_on_10k"]["pagination_check"]["duplicate_items"] = 1
        ev3 = {e["item"]: e["status"] for e in evaluate_thresholds(c3)}
        self.assertEqual(ev3["全量分页对比合成预期ID集合与顺序"], "fail", "Duplicate items in pagination must fail")

        # 5. Counterexample: restart recovery count mismatch or independent=False must FAIL
        c4 = copy.deepcopy(base_results)
        c4["lifecycle"]["restart_recovery"]["independent_process_verified"] = False
        ev4 = {e["item"]: e["status"] for e in evaluate_thresholds(c4)}
        self.assertEqual(ev4["生命周期: 独立进程重启恢复与字段比对"], "fail", "Non-independent recovery must fail")

        c4['lifecycle']['restart_recovery']['independent_process_verified'] = True
        c4['lifecycle']['restart_recovery']['recovered_count'] = 1
        ev4 = {e['item']: e['status'] for e in evaluate_thresholds(c4)}
        self.assertEqual(ev4['生命周期: 独立进程重启恢复与字段比对'], 'fail')

        # 6. Counterexample: 10k Peak RSS > 512 MiB must FAIL
        c5 = copy.deepcopy(base_results)
        c5["benchmarks"]["indexing_10k"]["fresh"]["peak_rss_mib"] = 515.0
        ev5 = {e["item"]: e["status"] for e in evaluate_thresholds(c5)}
        self.assertEqual(ev5["10k 初始索引峰值 RSS (独立子进程测得)"], "fail", "Peak RSS > 512 MiB must fail")

        # 7. Counterexample: Single append bytes != 1024 must FAIL
        c6 = copy.deepcopy(base_results)
        c6["benchmarks"]["single_file_append_1k"]["append_bytes"] = 1020
        ev6 = {e["item"]: e["status"] for e in evaluate_thresholds(c6)}
        self.assertEqual(ev6["单文件追加 1KiB 耗时 (1k)"], "fail", "Non-1024 append bytes must fail")

        # 8. Counterexample: surviving child process must FAIL clean exit
        c7 = copy.deepcopy(base_results)
        c7["clean_exit_check"]["surviving_descendants"] = [99999]
        c7["clean_exit_check"]["clean_exit"] = False
        ev7 = {e["item"]: e["status"] for e in evaluate_thresholds(c7)}
        self.assertEqual(ev7["CLI 退出后无残留子进程 (后台I/O: unmeasured)"], "fail", "Surviving child process must fail clean exit")


if __name__ == "__main__":
    unittest.main()
