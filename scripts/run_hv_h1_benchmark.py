#!/usr/bin/env python3
"""Repeatable benchmark and lifecycle runner for HV-H1 (with HV-H1.1 benchmark corrections).

Measures performance and records lifecycle facts against frozen task_plan.md HV-H1 thresholds:
- Initial Indexing:
    1k <= 10.0 s
    10k <= 90.0 s
    10k Peak RSS <= 512.0 MiB
    (Separate measurements in independent subprocesses to prevent VmHWM pollution)
- Single File Append 1024 Bytes:
    1k <= 2.0 s (parse count == 1, append bytes == 1024)
    10k <= 5.0 s (parse count == 1, append bytes == 1024)
- No-change Refresh:
    1k & 10k elapsed time, parse count == 0
- 10k 100 Queries (limit <= 100, no match, Chinese, same ts, cross-page):
    First process query <= 1.0 s (independent process CLI startup)
    100 hot queries p95 <= 250.0 ms
    Pagination stability: full pagination comparison against synthetic expected ID set,
    verifying exact count, order, zero duplicates, zero misses on fixed revision.
- Lifecycle Facts:
    Same-path replacement (including preserved mtime)
    Deletion / rotation (purging stale index from derived cache)
    Unreadable file (PermissionError) vs readable corrupted file (cannot claim fresh success)
    Source missing handling (preserves cache, raises FileNotFoundError)
    Restart recovery in independent subprocess verifying exact IDs and fields
- Process Clean Exit Check:
    Verifying main process exit code 0 and 0 surviving descendant processes in Linux /proc.
    Background I/O marked unmeasured.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

REPO_DIR = Path(__file__).resolve().parents[1]
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from history_core.reader import HistoryReader
from history_core.sources import parse_codex_session_file
from scripts.generate_synthetic_sessions import generate_session_content


def get_self_peak_rss_mib() -> float:
    """Read VmHWM from /proc/self/status on Linux using standard library."""
    try:
        with open("/proc/self/status", "r") as f:
            for line in f:
                if line.startswith("VmHWM:"):
                    kb = int(line.split()[1])
                    return round(kb / 1024.0, 2)
    except Exception:
        pass
    return 0.0


def get_ram_total_gib() -> float:
    """Read MemTotal from /proc/meminfo on Linux."""
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return round(kb / (1024.0 * 1024.0), 2)
    except Exception:
        pass
    return 0.0


def validate_bench_dir(path: Path, must_exist: bool = False, label: str = "directory") -> Path:
    """Ensures target directory is inside work/ to prevent touching caller directories."""
    original = path.absolute()
    if any(part.is_symlink() for part in (original, *original.parents)):
        raise ValueError(f"{label} symlink not allowed: {original}")
    p = original.resolve()
    repo_work = (REPO_DIR / "work" / "benchmarks").resolve()
    try:
        p.relative_to(repo_work)
    except ValueError:
        raise ValueError(f"{label} must be inside {repo_work}, got {p}")
    if must_exist and not p.exists():
        raise FileNotFoundError(f"{label} does not exist: {p}")
    return p


def safe_rmtree_work_bench(path: Path):
    """Safely removes directory only if inside work/."""
    valid_p = validate_bench_dir(path, must_exist=False, label="cache directory")
    if valid_p.exists():
        repo_work = (REPO_DIR / "work").resolve()
        if valid_p in (repo_work, repo_work / "benchmarks", REPO_DIR):
            raise ValueError(f"Refusing to remove work root or repo root: {valid_p}")
        shutil.rmtree(valid_p)


def verify_dataset_manifest(dataset_dir: Path) -> Dict[str, Any]:
    """Verifies actual session files against manifest.json."""
    dataset_dir = validate_bench_dir(dataset_dir, must_exist=True, label="dataset_dir")
    manifest_file = dataset_dir / "manifest.json"
    if not manifest_file.exists():
        raise FileNotFoundError(f"Manifest not found in {dataset_dir}")
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))

    file_hashes = []
    total_bytes = 0
    file_count = 0

    for f in dataset_dir.rglob("*.jsonl"):
        b = f.read_bytes()
        file_count += 1
        total_bytes += len(b)
        h = hashlib.sha256(b).hexdigest()
        file_hashes.append((str(f.relative_to(dataset_dir)), h, len(b)))

    digest_input = "\n".join(f"{name}:{h}" for name, h, _ in sorted(file_hashes)).encode("utf-8")
    actual_sha256 = hashlib.sha256(digest_input).hexdigest()

    match_count = (file_count == manifest["count"])
    match_bytes = (total_bytes == manifest["total_bytes"])
    match_sha256 = (actual_sha256 == manifest["dataset_sha256"])

    if not (match_count and match_bytes and match_sha256):
        raise ValueError(
            f"Dataset {dataset_dir} mismatch with manifest! "
            f"count: {file_count} vs {manifest['count']}, "
            f"bytes: {total_bytes} vs {manifest['total_bytes']}, "
            f"sha256: {actual_sha256} vs {manifest['dataset_sha256']}"
        )
    return {
        "verified": True,
        "count": file_count,
        "total_bytes": total_bytes,
        "dataset_sha256": actual_sha256,
    }


def measure_indexing_subprocess(source_dir: Path, cache_dir: Path, fresh: bool, timeout: float = 120.0) -> Dict[str, Any]:
    """Executes indexing in an independent subprocess to guarantee no VmHWM pollution."""
    source_dir = validate_bench_dir(source_dir, must_exist=True, label="source_dir")
    cache_dir = validate_bench_dir(cache_dir, must_exist=False, label="cache_dir")

    if cache_dir == source_dir or cache_dir in source_dir.parents or source_dir in cache_dir.parents:
        raise ValueError('benchmark_source_and_cache_must_be_disjoint')
    if fresh:
        safe_rmtree_work_bench(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        "-B",
        str(Path(__file__).resolve()),
        "--subproc-index",
        "--source-dir",
        str(source_dir),
        "--cache-dir",
        str(cache_dir),
    ]

    t0 = time.perf_counter()
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    wall_clock = time.perf_counter() - t0

    if proc.returncode != 0:
        raise RuntimeError(f"Subprocess indexing failed (code {proc.returncode}): {proc.stderr}")

    try:
        data = json.loads(proc.stdout.strip())
    except Exception as e:
        raise RuntimeError(f"Failed to parse subprocess indexing output: {proc.stdout}\nError: {e}")

    data["wall_clock_seconds"] = round(wall_clock, 4)
    return data


def run_indexing_subproc_worker(source_dir: Path, cache_dir: Path):
    """Subprocess entry point to perform refresh and output memory/timing."""
    t0 = time.perf_counter()
    with HistoryReader("codex", source_dir, cache_dir) as reader:
        res = reader.refresh()
    elapsed = time.perf_counter() - t0
    peak_rss = get_self_peak_rss_mib()

    out = {
        "elapsed_seconds": round(elapsed, 4),
        "peak_rss_mib": peak_rss,
        "status": res.get("status"),
    }
    print(json.dumps(out))
    sys.exit(0)


def measure_initial_indexing(source_dir: Path, cache_dir: Path, label: str) -> Dict[str, Any]:
    """Measures fresh indexing and reused indexing in separate subprocesses."""
    # 1. Fresh cache in isolated subprocess
    res_fresh = measure_indexing_subprocess(source_dir, cache_dir, fresh=True)
    # 2. Reused cache in isolated subprocess
    res_reused = measure_indexing_subprocess(source_dir, cache_dir, fresh=False)

    return {
        "label": label,
        "fresh": res_fresh,
        "reused": res_reused,
    }


def make_exact_1024_byte_append() -> bytes:
    """Constructs a valid JSONL Codex response message of exactly 1024 bytes."""
    prefix = '{"timestamp": "2026-09-02T12:00:00.000Z", "type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "'
    suffix = '"}]}}\n'
    base_len = len(prefix.encode("utf-8")) + len(suffix.encode("utf-8"))
    needed_pad = 1024 - base_len
    assert needed_pad > 0, "Base message exceeds 1024 bytes"
    padding = "A" * needed_pad
    chunk = (prefix + padding + suffix).encode("utf-8")
    assert len(chunk) == 1024, f"Chunk len is {len(chunk)}, expected 1024"
    return chunk


def measure_single_file_append(source_dir: Path, cache_dir: Path, label: str) -> Dict[str, Any]:
    """Appends exactly 1024 bytes to one session file, measures refresh time and parse count."""
    source_dir = validate_bench_dir(source_dir, must_exist=True, label="source_dir")
    cache_dir = validate_bench_dir(cache_dir, must_exist=True, label="cache_dir")

    files = sorted(source_dir.glob("session_*.jsonl"))
    if not files:
        raise ValueError(f"No session files found in {source_dir}")
    target_file = files[-1]

    with HistoryReader("codex", source_dir, cache_dir) as reader:
        reader.refresh()

        parse_calls = []
        original_parse = reader._HistoryReader__indexer._parse_file_fn

        def tracking_parser(p):
            parse_calls.append(str(p))
            return original_parse(p)

        reader._HistoryReader__indexer._parse_file_fn = tracking_parser

        append_data = make_exact_1024_byte_append()
        original_bytes = target_file.read_bytes()

        try:
            with target_file.open("ab") as f:
                f.write(append_data)

            t0 = time.perf_counter()
            reader.refresh()
            elapsed = time.perf_counter() - t0

            parsed_count = len(parse_calls)
            only_target_parsed = (parsed_count == 1 and Path(parse_calls[0]).resolve() == target_file.resolve())

            return {
                "label": label,
                "elapsed_seconds": round(elapsed, 4),
                "parse_count": parsed_count,
                "only_affected_file_parsed": only_target_parsed,
                "target_file": target_file.name,
                "append_bytes": len(append_data),
            }
        finally:
            target_file.write_bytes(original_bytes)
            reader.refresh()


def measure_no_change_refresh(source_dir: Path, cache_dir: Path, label: str) -> Dict[str, Any]:
    """Measures refresh when no files modified, ensuring parse count is 0."""
    source_dir = validate_bench_dir(source_dir, must_exist=True, label="source_dir")
    cache_dir = validate_bench_dir(cache_dir, must_exist=True, label="cache_dir")

    with HistoryReader("codex", source_dir, cache_dir) as reader:
        reader.refresh()

        parse_calls = []
        original_parse = reader._HistoryReader__indexer._parse_file_fn

        def tracking_parser(p):
            parse_calls.append(str(p))
            return original_parse(p)

        reader._HistoryReader__indexer._parse_file_fn = tracking_parser

        t0 = time.perf_counter()
        res = reader.refresh()
        elapsed = time.perf_counter() - t0

        return {
            "label": label,
            "elapsed_seconds": round(elapsed, 4),
            "parse_count": len(parse_calls),
            "status": res.get("status"),
        }


def measure_cold_first_process_query(source_dir: Path, cache_dir: Path) -> Dict[str, Any]:
    """Measures first query in a brand new process via CLI (public machine entry)."""
    source_dir = validate_bench_dir(source_dir, must_exist=True, label="source_dir")
    cache_dir = validate_bench_dir(cache_dir, must_exist=True, label="cache_dir")

    cmd = [
        sys.executable,
        "-B",
        "-m",
        "history_core",
        "--source",
        "codex",
        "--source-path",
        str(source_dir),
        "--data-dir",
        str(cache_dir),
        "search",
        "--query",
        "Unicode",
        "--limit",
        "20",
    ]
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    elapsed = time.perf_counter() - t0

    if proc.returncode != 0:
        raise RuntimeError(f"CLI search failed: {proc.stderr}")

    out = json.loads(proc.stdout)
    item_count = len(out.get("items", []))

    return {
        "elapsed_seconds": round(elapsed, 4),
        "items_returned": item_count,
        "returncode": proc.returncode,
        "description": "全新独立进程首查 (CLI process startup, not OS cold cache)",
    }


def generate_fixed_100_queries() -> List[Dict[str, Any]]:
    """Generates the fixed 100 queries specified in task_plan.md HV-H1."""
    queries = []
    # 1. No match queries (25)
    for i in range(25):
        queries.append({
            "category": "no_match",
            "query": f"NONEXISTENT_QUERY_TERM_RANDOM_{i:04d}_ZZZ",
            "limit": 20,
            "offset": 0,
        })

    # 2. Chinese queries (25)
    chinese_terms = [
        "Unicode", "工程事实", "增量索引", "数据分块", "长行测试",
        "生命周期", "验证报告", "标点符号", "系统架构", "缓存新鲜度",
        "测试日志", "堆栈输出", "倒排索引", "会话检索", "高密度",
        "边界验证", "测试", "分块", "索引", "会话",
        "Unicode测试", "架构", "日志", "新鲜度", "报告"
    ]
    for i in range(25):
        queries.append({
            "category": "chinese",
            "query": chinese_terms[i % len(chinese_terms)],
            "limit": 20,
            "offset": 0,
        })

    # 3. Same timestamp / project queries (25)
    for i in range(25):
        batch = i % 20
        queries.append({
            "category": "timestamp_project",
            "query": None,
            "project": f"/work/project-{batch:03d}",
            "limit": 25,
            "offset": 0,
        })

    # 4. Pagination queries across pages (25)
    for i in range(25):
        queries.append({
            "category": "pagination",
            "query": "数据分块",
            "limit": 20,
            "offset": i * 20,
        })

    return queries


def measure_100_queries_on_10k(source_dir: Path, cache_dir: Path) -> Dict[str, Any]:
    """Measures 100 fixed queries on 10k index and verifies full pagination against synthetic expected IDs."""
    source_dir = validate_bench_dir(source_dir, must_exist=True, label="source_dir")
    cache_dir = validate_bench_dir(cache_dir, must_exist=True, label="cache_dir")

    queries = generate_fixed_100_queries()
    latencies_ms = []
    category_latencies = {"no_match": [], "chinese": [], "timestamp_project": [], "pagination": []}

    with HistoryReader("codex", source_dir, cache_dir) as reader:
        # Warmup query
        reader.search(query="test", limit=1)

        for q in queries:
            t0 = time.perf_counter()
            res = reader.search(
                query=q.get("query"),
                limit=q.get("limit", 20),
                offset=q.get("offset", 0),
                cwd=q.get("project"),
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            latencies_ms.append(elapsed_ms)
            category_latencies[q["category"]].append(elapsed_ms)

        # Full pagination comparison against synthetic expected ID set:
        # In dataset_10k, project-005 contains exactly 50 sessions: synthetic-codex-00250 to 00299.
        # Under stable_order (ORDER BY end_ts_ms DESC, start_ts_ms DESC, id ASC), order is 00250 to 00299.
        expected_project_ids = [f"synthetic-codex-{i:05d}" for i in range(250, 300)]
        fetched_paged_ids = []
        page_size = 10
        for page_idx in range(10):  # 5 full pages + 1 empty
            p_res = reader.search(cwd="/work/project-005", limit=page_size, offset=page_idx * page_size)
            items = p_res.get("items", [])
            if not items:
                break
            for it in items:
                fetched_paged_ids.append(it["id"])

        # Also check 5 pages of query "数据分块" against single-query limit=100 reference on same revision
        ref_res = reader.search(query="数据分块", limit=100, offset=0)
        ref_ids = [it["id"] for it in ref_res.get("items", [])]

        paged_100_ids = []
        for p_idx in range(5):
            page_res = reader.search(query="数据分块", limit=20, offset=p_idx * 20)
            for it in page_res.get("items", []):
                paged_100_ids.append(it["id"])

        sorted_l = sorted(latencies_ms)
        n = len(sorted_l)
        p50 = sorted_l[int(n * 0.50)]
        p90 = sorted_l[int(n * 0.90)]
        p95 = sorted_l[int(n * 0.95)]
        p99 = sorted_l[int(n * 0.99)]

        # Determine exact correctness
        project_count_match = (len(fetched_paged_ids) == len(expected_project_ids))
        project_order_match = (fetched_paged_ids == expected_project_ids)
        project_no_duplicates = (len(fetched_paged_ids) == len(set(fetched_paged_ids)))
        project_no_misses = (set(expected_project_ids) - set(fetched_paged_ids) == set())

        paged_100_match = (len(paged_100_ids) == len(ref_ids) == 100 and paged_100_ids == ref_ids)
        paged_100_no_duplicates = (len(paged_100_ids) == len(set(paged_100_ids)) == 100)

        pagination_ok = (
            project_count_match
            and project_order_match
            and project_no_duplicates
            and project_no_misses
            and paged_100_match
            and paged_100_no_duplicates
        )

        return {
            "total_queries": n,
            "min_ms": round(sorted_l[0], 2),
            "max_ms": round(sorted_l[-1], 2),
            "avg_ms": round(sum(sorted_l) / n, 2),
            "p50_ms": round(p50, 2),
            "p90_ms": round(p90, 2),
            "p95_ms": round(p95, 2),
            "p99_ms": round(p99, 2),
            "category_avg_ms": {
                cat: round(sum(vals) / len(vals), 2) for cat, vals in category_latencies.items()
            },
            "pagination_check": {
                "total_items": len(fetched_paged_ids),
                "expected_items_count": len(expected_project_ids),
                "unique_items": len(set(fetched_paged_ids)),
                "duplicate_items": len(fetched_paged_ids) - len(set(fetched_paged_ids)),
                "missing_items": len(set(expected_project_ids) - set(fetched_paged_ids)),
                "exact_order_match": project_order_match,
                "multi_page_reference_match": paged_100_match,
                "consistent_no_duplicates": pagination_ok,
            }
        }


def records_match(actual, expected):
    """Compare complete identities and values, rejecting omissions and duplicates."""
    fields = ('id', 'cwd', 'start_ts_ms', 'end_ts_ms', 'message_count')
    def project(items):
        return sorted([tuple(item.get(key) for key in fields) for item in items], key=repr)
    return bool(expected) and len(actual) == len(expected) and project(actual) == project(expected)


def measure_lifecycle_facts(test_dir: Path) -> Dict[str, Any]:
    """Runs lifecycle tests and records concrete factual behaviors."""
    test_dir = validate_bench_dir(test_dir, must_exist=False, label="lifecycle test_dir")
    source_dir = test_dir / "lifecycle_sources"
    cache_dir = test_dir / "lifecycle_cache"
    safe_rmtree_work_bench(source_dir)
    safe_rmtree_work_bench(cache_dir)
    source_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Populate 3 initial sessions
    for i in range(3):
        content = generate_session_content(i, seed=42)
        (source_dir / f"session_{i:05d}.jsonl").write_bytes(content)

    results = {}

    with HistoryReader("codex", source_dir, cache_dir) as reader:
        reader.refresh()
        initial_items = reader.search(limit=10).get("items", [])
        results["initial_indexed_count"] = len(initial_items)

        # 1. Same-path replacement with preserved mtime
        target = source_dir / "session_00001.jsonl"
        orig_stat = target.stat()
        replacement_content = generate_session_content(888, seed=9999)
        target.write_bytes(replacement_content)
        # Explicitly preserve mtime to test mtime preservation flaw
        os.utime(target, (orig_stat.st_atime, orig_stat.st_mtime))

        try:
            reader.refresh()
            after_replace = reader.search(limit=10).get("items", [])
            replace_ids = {it["id"] for it in after_replace}
            old_removed = "synthetic-codex-00001" not in replace_ids
            new_indexed = "synthetic-codex-00888" in replace_ids
            results["same_path_replacement_preserved_mtime"] = {
                "status": "pass" if (old_removed and new_indexed) else "fail",
                "old_id_removed": old_removed,
                "new_id_indexed": new_indexed,
                "preserved_mtime": orig_stat.st_mtime,
            }
        except Exception as e:
            results["same_path_replacement_preserved_mtime"] = {
                "status": "fail",
                "error": str(e),
            }

        # 2. Deletion / rotation
        del_target = source_dir / "session_00002.jsonl"
        del_target.unlink()
        try:
            reader.refresh()
            after_delete = reader.search(limit=10).get("items", [])
            del_ids = {it["id"] for it in after_delete}
            stale_present = "synthetic-codex-00002" in del_ids

            handoff_raised_error = False
            try:
                reader.handoff("synthetic-codex-00002")
            except FileNotFoundError:
                handoff_raised_error = True
            except Exception:
                handoff_raised_error = True

            results["deletion_rotation"] = {
                "status": "fail" if stale_present else "pass",
                "stale_row_retained_in_index": stale_present,
                "handoff_fails_with_file_not_found": handoff_raised_error,
            }
        except Exception as e:
            results["deletion_rotation"] = {
                "status": "fail",
                "error": str(e),
            }

        # 3. Unreadable file (PermissionError)
        bad_perm_file = source_dir / "bad_permissions.jsonl"
        bad_perm_file.write_text('{"type":"session_meta"}\n')
        bad_perm_file.chmod(0)
        perm_error_caught = False
        try:
            reader.refresh()
        except PermissionError:
            perm_error_caught = True
        except Exception:
            perm_error_caught = False
        finally:
            bad_perm_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
            bad_perm_file.unlink()

        results["unreadable_file_permission"] = {
            "status": "pass" if perm_error_caught else "fail",
            "permission_error_caught": perm_error_caught,
        }

        # 4. Readable corrupted file (Invalid JSON / Not Fresh Success)
        bad_content_file = source_dir / "corrupted_readable.jsonl"
        bad_content_file.write_text("CORRUPTED_NOT_JSON_BINARY_GARBAGE\n{\nincomplete\n")
        corrupted_rejected = False
        try:
            reader.refresh()
        except ValueError as error:
            corrupted_rejected = str(error) == "invalid_session_file: %s" % bad_content_file
        finally:
            bad_content_file.unlink()
        reader.refresh()  # Recovery errors must fail this run.
        expected = []
        fields = ('id', 'cwd', 'start_ts_ms', 'end_ts_ms', 'message_count')
        for path in (source_dir / 'session_00000.jsonl', target):
            parsed = parse_codex_session_file(path)
            expected.append({key: parsed[key] for key in fields})
        actual = reader.search(limit=10)['items']
        recovered_after_corruption = records_match(actual, expected)
        results["readable_corrupted_file"] = {
            "corrupted_rejected_not_fresh_success": corrupted_rejected and recovered_after_corruption,
        }

        # Remove the selected source while keeping the existing reader/cache alive.
        before_rows = [tuple(row) for row in reader._HistoryReader__indexer.conn.execute('SELECT * FROM sessions ORDER BY id')]
        moved = test_dir / 'temporarily_unavailable'
        source_dir.rename(moved)
        source_missing_error = False
        try:
            reader.refresh()
        except FileNotFoundError:
            source_missing_error = True
        finally:
            moved.rename(source_dir)
        after_rows = [tuple(row) for row in reader._HistoryReader__indexer.conn.execute('SELECT * FROM sessions ORDER BY id')]
        reader.refresh()
        results['source_missing'] = {
            'file_not_found_caught': source_missing_error,
            'cache_preserved': before_rows == after_rows and records_match(reader.search(limit=10)['items'], expected),
        }

    # 6. Restart recovery in an INDEPENDENT subprocess checking exact expected IDs and fields
    # Ensure source directory has 2 known sessions (0 and replaced 888)
    cmd = [
        sys.executable,
        "-B",
        "-m",
        "history_core",
        "--source",
        "codex",
        "--source-path",
        str(source_dir),
        "--data-dir",
        str(cache_dir),
        "search",
        "--limit",
        "10",
    ]
    subproc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    if subproc.returncode != 0:
        results["restart_recovery"] = {
            "status": "fail",
            "independent_process_verified": False,
            "error": subproc.stderr,
        }
    else:
        out_data = json.loads(subproc.stdout)
        recovered_items = out_data.get("items", [])
        recovered_ids = {it["id"] for it in recovered_items}

        all_fields_ok = records_match(recovered_items, expected)
        results['restart_recovery'] = {
            'status': 'pass' if all_fields_ok else 'fail',
            'independent_process_verified': True,
            'recovered_count': len(recovered_items),
            'expected_count': len(expected),
            'recovered_ids': sorted(recovered_ids),
            'all_fields_matched': all_fields_ok,
        }

    return results


def check_cli_clean_exit(source_dir: Path, cache_dir: Path) -> Dict[str, Any]:
    """Runs CLI command in a session and verifies complete exit without surviving descendants in /proc."""
    source_dir = validate_bench_dir(source_dir, must_exist=True, label="source_dir")
    cache_dir = validate_bench_dir(cache_dir, must_exist=True, label="cache_dir")

    cmd = [
        sys.executable,
        "-B",
        "-m",
        "history_core",
        "--source",
        "codex",
        "--source-path",
        str(source_dir),
        "--data-dir",
        str(cache_dir),
        "health",
    ]
    t0 = time.perf_counter()
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    pgid = proc.pid
    stdout, stderr = proc.communicate(timeout=15)
    elapsed = time.perf_counter() - t0

    # Scan /proc for any surviving descendant processes
    surviving_children = []
    try:
        for entry in os.listdir("/proc"):
            if entry.isdigit():
                pid = int(entry)
                if pid == os.getpid() or pid == proc.pid:
                    continue
                try:
                    with open(f"/proc/{pid}/stat", "r") as f:
                        fields = f.read().split()
                        p_ppid = int(fields[3])
                        p_pgrp = int(fields[4])
                        if p_ppid == proc.pid or p_pgrp == pgid:
                            surviving_children.append(pid)
                except (FileNotFoundError, ProcessLookupError, PermissionError):
                    pass
    except Exception:
        pass

    return {
        "returncode": proc.returncode,
        "stdout": json.loads(stdout) if proc.returncode == 0 else stdout,
        "stderr": stderr,
        "elapsed_seconds": round(elapsed, 4),
        "surviving_descendants": surviving_children,
        "clean_exit": proc.returncode == 0 and len(surviving_children) == 0,
        "background_io": "unmeasured",
    }


def evaluate_thresholds(results: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Strictly evaluates measured results against task_plan.md HV-H1 frozen thresholds."""
    evaluations = []

    # 1. 1k Initial Indexing <= 10 s
    t_1k = results["benchmarks"]["indexing_1k"]["fresh"]["elapsed_seconds"]
    evaluations.append({
        "item": "初始索引耗时 (1k 会话全新缓存)",
        "threshold": "<= 10.0 s",
        "actual": f"{t_1k} s",
        "status": "pass" if t_1k <= 10.0 else "fail",
    })

    # 2. 10k Initial Indexing <= 90 s
    t_10k = results["benchmarks"]["indexing_10k"]["fresh"]["elapsed_seconds"]
    evaluations.append({
        "item": "初始索引耗时 (10k 会话全新缓存)",
        "threshold": "<= 90.0 s",
        "actual": f"{t_10k} s",
        "status": "pass" if t_10k <= 90.0 else "fail",
    })

    # 3. 10k Peak RSS <= 512 MiB
    rss_10k = results["benchmarks"]["indexing_10k"]["fresh"]["peak_rss_mib"]
    evaluations.append({
        "item": "10k 初始索引峰值 RSS (独立子进程测得)",
        "threshold": "<= 512.0 MiB",
        "actual": f"{rss_10k} MiB",
        "status": "pass" if 0 < rss_10k <= 512.0 else "fail",
    })

    # 4. Single file append 1KiB (1k) <= 2 s
    app_1k = results["benchmarks"]["single_file_append_1k"]["elapsed_seconds"]
    parse_1k = results["benchmarks"]["single_file_append_1k"]["parse_count"]
    bytes_1k = results["benchmarks"]["single_file_append_1k"].get("append_bytes", 0)
    app_1k_ok = (app_1k <= 2.0 and parse_1k == 1 and bytes_1k == 1024 and results["benchmarks"]["single_file_append_1k"].get("only_affected_file_parsed") is True)
    evaluations.append({
        "item": "单文件追加 1KiB 耗时 (1k)",
        "threshold": "<= 2.0 s (解析计数增加1, 精确1024B)",
        "actual": f"{app_1k} s (解析计数={parse_1k}, 追加字节={bytes_1k})",
        "status": "pass" if app_1k_ok else "fail",
    })

    # 5. Single file append 1KiB (10k) <= 5 s
    app_10k = results["benchmarks"]["single_file_append_10k"]["elapsed_seconds"]
    parse_10k = results["benchmarks"]["single_file_append_10k"]["parse_count"]
    bytes_10k = results["benchmarks"]["single_file_append_10k"].get("append_bytes", 0)
    app_10k_ok = (app_10k <= 5.0 and parse_10k == 1 and bytes_10k == 1024 and results["benchmarks"]["single_file_append_10k"].get("only_affected_file_parsed") is True)
    evaluations.append({
        "item": "单文件追加 1KiB 耗时 (10k)",
        "threshold": "<= 5.0 s (解析计数增加1, 精确1024B)",
        "actual": f"{app_10k} s (解析计数={parse_10k}, 追加字节={bytes_10k})",
        "status": "pass" if app_10k_ok else "fail",
    })

    # 6. No-change refresh parse count == 0
    nc_1k = results["benchmarks"]["no_change_refresh_1k"]["parse_count"]
    nc_10k = results["benchmarks"]["no_change_refresh_10k"]["parse_count"]
    evaluations.append({
        "item": "无变化 refresh 解析计数 (1k / 10k)",
        "threshold": "解析计数 == 0",
        "actual": f"1k={nc_1k}, 10k={nc_10k}",
        "status": "pass" if (nc_1k == 0 and nc_10k == 0) else "fail",
    })

    # 7. First process query <= 1 s
    cold_q = results["benchmarks"]["cold_first_process_query_10k"]["elapsed_seconds"]
    evaluations.append({
        "item": "10k 首次进程查询耗时 (全新独立进程CLI启动)",
        "threshold": "<= 1.0 s",
        "actual": f"{cold_q} s",
        "status": "pass" if cold_q <= 1.0 else "fail",
    })

    # 8. 100 hot queries p95 <= 250 ms
    p95 = results["benchmarks"]["queries_100_on_10k"]["p95_ms"]
    evaluations.append({
        "item": "10k 索引 100 次热查询 p95",
        "threshold": "<= 250.0 ms",
        "actual": f"{p95} ms",
        "status": "pass" if p95 <= 250.0 else "fail",
    })

    # 9. Pagination consistency: must match synthetic expected set, zero misses, zero duplicates, non-empty
    pag = results["benchmarks"]["queries_100_on_10k"]["pagination_check"]
    total_items = pag.get("total_items", 0)
    expected_items = pag.get("expected_items_count", 0)
    missing_items = pag.get("missing_items", 1)
    dup_items = pag.get("duplicate_items", 1)
    order_ok = pag.get("exact_order_match", False)
    multi_ref_ok = pag.get("multi_page_reference_match", False)

    pag_ok = (
        total_items > 0
        and expected_items > 0
        and total_items == expected_items
        and missing_items == 0
        and dup_items == 0
        and order_ok is True
        and multi_ref_ok is True
    )
    evaluations.append({
        "item": "全量分页对比合成预期ID集合与顺序",
        "threshold": "无漏无重复, 顺序完全一致, 跨页无裂隙",
        "actual": f"总数={total_items}/{expected_items}, 漏项={missing_items}, 重复={dup_items}, 顺序匹配={order_ok}",
        "status": "pass" if pag_ok else "fail",
    })

    # 10. Lifecycle: Same-path replacement (including preserved mtime)
    replace_res = results["lifecycle"].get("same_path_replacement_preserved_mtime", {})
    replace_ok = (replace_res.get("status") == "pass" and replace_res.get("old_id_removed") and replace_res.get("new_id_indexed"))
    evaluations.append({
        "item": "生命周期: 同路径替换更新 (含保留mtime)",
        "threshold": "正确识别替换并更新索引ID",
        "actual": f"旧ID清除且新ID入库={replace_ok}",
        "status": "pass" if replace_ok else "fail",
    })

    # 11. Lifecycle: Deletion / rotation
    del_res = results["lifecycle"].get("deletion_rotation", {})
    del_defect = del_res.get("stale_row_retained_in_index", True)
    del_ok = (del_res.get("status") == "pass" and not del_defect)
    evaluations.append({
        "item": "生命周期: 删除/轮转清理",
        "threshold": "最多一次 refresh 清理失效项",
        "actual": "残留失效行" if del_defect else "失效行已从派生索引清理",
        "status": "pass" if del_ok else "fail",
    })

    # 12. Lifecycle: Unreadable file
    unreadable_ok = results["lifecycle"].get("unreadable_file_permission", {}).get("permission_error_caught", False)
    evaluations.append({
        "item": "生命周期: 无权限文件显式拒绝",
        "threshold": "抛出 PermissionError",
        "actual": f"PermissionError捕获={unreadable_ok}",
        "status": "pass" if unreadable_ok else "fail",
    })

    # 13. Lifecycle: Readable corrupted file
    corrupt_ok = results["lifecycle"].get("readable_corrupted_file", {}).get("corrupted_rejected_not_fresh_success", False)
    evaluations.append({
        "item": "生命周期: 可读损坏文件不得默认为新鲜成功",
        "threshold": "拒绝默认为 fresh success",
        "actual": f"损坏正确拒绝={corrupt_ok}",
        "status": "pass" if corrupt_ok else "fail",
    })

    # 14. Lifecycle: Source missing
    missing = results["lifecycle"].get("source_missing", {})
    missing_ok = missing.get("file_not_found_caught", False) and missing.get("cache_preserved", False)
    evaluations.append({
        "item": "生命周期: 来源丢失显式失败",
        "threshold": "抛出 FileNotFoundError, 不误清缓存",
        "actual": f"FileNotFoundError捕获={missing_ok}",
        "status": "pass" if missing_ok else "fail",
    })

    # 15. Lifecycle: Restart recovery in independent subprocess
    restart_res = results["lifecycle"].get("restart_recovery", {})
    indep = restart_res.get("independent_process_verified", False)
    rec_count = restart_res.get("recovered_count", 0)
    all_fields = restart_res.get("all_fields_matched", False)
    restart_ok = (indep and rec_count > 0 and rec_count == restart_res.get("expected_count") and all_fields)
    evaluations.append({
        "item": "生命周期: 独立进程重启恢复与字段比对",
        "threshold": "独立进程恢复全部预期会话并精确比对字段",
        "actual": f"独立进程={indep}, 恢复会话数={rec_count}, 字段匹配={all_fields}",
        "status": "pass" if restart_ok else "fail",
    })

    # 16. Clean exit
    clean_res = results.get("clean_exit_check", {})
    clean_exit = clean_res.get("clean_exit", False)
    surv_count = len(clean_res.get("surviving_descendants", []))
    bg_io = clean_res.get("background_io", "unmeasured")
    evaluations.append({
        "item": "CLI 退出后无残留子进程 (后台I/O: unmeasured)",
        "threshold": "退出码0, 0孤儿进程, 后台I/O实测标记",
        "actual": f"clean_exit={clean_exit}, 孤儿进程数={surv_count}, 后台I/O={bg_io}",
        "status": "pass" if clean_exit and surv_count == 0 else "fail",
    })

    return evaluations


def run_benchmark(dataset_1k: Path, dataset_10k: Path, cache_base_dir: Path) -> Dict[str, Any]:
    print("=== Starting HV-H1.2 Benchmark Runner ===")
    dataset_1k = validate_bench_dir(dataset_1k, must_exist=True, label="dataset_1k")
    dataset_10k = validate_bench_dir(dataset_10k, must_exist=True, label="dataset_10k")
    cache_base_dir = validate_bench_dir(cache_base_dir, must_exist=False, label="cache_base_dir")
    for source in (dataset_1k, dataset_10k):
        if cache_base_dir == source or cache_base_dir in source.parents or source in cache_base_dir.parents:
            raise ValueError('benchmark_source_and_cache_must_be_disjoint')
    cache_base_dir.mkdir(parents=True, exist_ok=True)

    # 1. Verify datasets against manifest
    print("[0/7] Verifying dataset manifests and checksums...")
    v_1k = verify_dataset_manifest(dataset_1k)
    v_10k = verify_dataset_manifest(dataset_10k)
    if v_1k["count"] != 1000 or v_10k["count"] != 10000:
        raise ValueError("frozen_dataset_count_mismatch")
    print(f"  -> 1k: {v_1k['count']} files, {v_1k['total_bytes']} bytes, SHA match: True")
    print(f"  -> 10k: {v_10k['count']} files, {v_10k['total_bytes']} bytes, SHA match: True")

    # 2. Hardware and environment facts
    cpu_model = "unknown"
    try:
        with open("/proc/cpuinfo") as f:
            for l in f:
                if "model name" in l:
                    cpu_model = l.split(":", 1)[1].strip()
                    break
    except Exception:
        pass

    ram_gib = get_ram_total_gib()
    disk = shutil.disk_usage(".")

    git_head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    diff_bytes = subprocess.check_output(["git", "diff", "HEAD"])
    tracked_diff_sha256 = hashlib.sha256(diff_bytes).hexdigest()
    diff_stat = subprocess.check_output(["git", "diff", "--stat", "HEAD"], text=True).strip()

    untracked_digests = {}
    paths = subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard', '-z'], cwd=REPO_DIR).decode().split('\0')
    for name in paths:
        if name and Path(name).parts[0] in ('history_core', 'scripts', 'tests'):
            path = REPO_DIR / name
            if path.is_file() and not path.is_symlink():
                untracked_digests[name] = hashlib.sha256(path.read_bytes()).hexdigest()

    environment = {
        "os": platform.platform(),
        "python": platform.python_version(),
        "cpu_model": cpu_model,
        "cpu_cores_logical": os.cpu_count(),
        "ram_total_gib": ram_gib,
        "disk_free_gib": round(disk.free / (1024.0 ** 3), 2),
        "disk_total_gib": round(disk.total / (1024.0 ** 3), 2),
        "git_head": git_head,
        "tracked_diff_sha256": tracked_diff_sha256,
        "tracked_diff_stat": diff_stat,
        "untracked_code_digests": untracked_digests,
        "model_used": "unknown",  # Unqueryable external model
        "estimated_cost_token": "unknown",
    }

    # 3. Indexing measurements in isolated subprocesses
    cache_1k = cache_base_dir / "cache_1k"
    cache_10k = cache_base_dir / "cache_10k"

    print("[1/7] Measuring 1k initial indexing (isolated subprocesses)...")
    idx_1k = measure_initial_indexing(dataset_1k, cache_1k, "1k_sessions")
    print(f"  -> Fresh: {idx_1k['fresh']['elapsed_seconds']}s (RSS {idx_1k['fresh']['peak_rss_mib']} MiB), Reused: {idx_1k['reused']['elapsed_seconds']}s")

    print("[2/7] Measuring 10k initial indexing (isolated subprocesses)...")
    idx_10k = measure_initial_indexing(dataset_10k, cache_10k, "10k_sessions")
    print(f"  -> Fresh: {idx_10k['fresh']['elapsed_seconds']}s (RSS {idx_10k['fresh']['peak_rss_mib']} MiB), Reused: {idx_10k['reused']['elapsed_seconds']}s")

    print("[3/7] Measuring single file append (exact 1024B, 1k & 10k)...")
    app_1k = measure_single_file_append(dataset_1k, cache_1k, "1k_sessions")
    app_10k = measure_single_file_append(dataset_10k, cache_10k, "10k_sessions")
    print(f"  -> 1k: {app_1k['elapsed_seconds']}s (parsed={app_1k['parse_count']}, bytes={app_1k['append_bytes']})")
    print(f"  -> 10k: {app_10k['elapsed_seconds']}s (parsed={app_10k['parse_count']}, bytes={app_10k['append_bytes']})")

    print("[4/7] Measuring no-change refresh (1k & 10k)...")
    nc_1k = measure_no_change_refresh(dataset_1k, cache_1k, "1k_sessions")
    nc_10k = measure_no_change_refresh(dataset_10k, cache_10k, "10k_sessions")
    print(f"  -> 1k: {nc_1k['elapsed_seconds']}s (parsed={nc_1k['parse_count']}), 10k: {nc_10k['elapsed_seconds']}s (parsed={nc_10k['parse_count']})")

    print("[5/7] Measuring cold first process query on 10k (via CLI startup)...")
    cold_q = measure_cold_first_process_query(dataset_10k, cache_10k)
    print(f"  -> Cold CLI query: {cold_q['elapsed_seconds']}s (items={cold_q['items_returned']})")

    print("[6/7] Measuring 100 hot queries on 10k and full pagination consistency...")
    q100 = measure_100_queries_on_10k(dataset_10k, cache_10k)
    print(f"  -> 100 queries: min={q100['min_ms']}ms, avg={q100['avg_ms']}ms, p50={q100['p50_ms']}ms, p95={q100['p95_ms']}ms, max={q100['max_ms']}ms")
    print(f"  -> Pagination check: {q100['pagination_check']}")

    print("[7/7] Measuring lifecycle facts & clean exit with /proc check...")
    lifecycle_dir = cache_base_dir / "lifecycle_scratch"
    lifecycle_res = measure_lifecycle_facts(lifecycle_dir)
    clean_exit_res = check_cli_clean_exit(dataset_1k, cache_1k)
    print("  -> Lifecycle measurements complete.")

    final_results = {
        "benchmark_card": "HV-H1.2",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "environment": environment,
        "datasets": {
            "dataset_1k": v_1k,
            "dataset_10k": v_10k,
        },
        "benchmarks": {
            "indexing_1k": idx_1k,
            "indexing_10k": idx_10k,
            "single_file_append_1k": app_1k,
            "single_file_append_10k": app_10k,
            "no_change_refresh_1k": nc_1k,
            "no_change_refresh_10k": nc_10k,
            "cold_first_process_query_10k": cold_q,
            "queries_100_on_10k": q100,
        },
        "lifecycle": lifecycle_res,
        "clean_exit_check": clean_exit_res,
    }

    evaluations = evaluate_thresholds(final_results)
    final_results["evaluations"] = evaluations

    return final_results


def main():
    parser = argparse.ArgumentParser(description="HV-H1 Benchmark Runner")
    parser.add_argument("--dataset-1k", type=Path, default=Path("work/benchmarks/dataset_1k"))
    parser.add_argument("--dataset-10k", type=Path, default=Path("work/benchmarks/dataset_10k"))
    parser.add_argument("--cache-dir", type=Path, default=Path("work/benchmarks/cache"))
    parser.add_argument("--json-out", type=Path, default=Path("work/benchmarks/results_h11.json"))
    parser.add_argument("--subproc-index", action="store_true", help="Internal subprocess worker for indexing")
    parser.add_argument("--source-dir", type=Path, help="Internal subprocess worker source dir")
    args = parser.parse_args()

    if args.subproc_index:
        if not args.source_dir or not args.cache_dir:
            sys.exit(1)
        run_indexing_subproc_worker(args.source_dir, args.cache_dir)

    results = run_benchmark(args.dataset_1k, args.dataset_10k, args.cache_dir)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n=== HV-H1 Evaluation Summary ===")
    for ev in results["evaluations"]:
        print(f"[{ev['status'].upper():4s}] {ev['item']:40s} | 门槛: {ev['threshold']:30s} | 实测: {ev['actual']}")

    print(f"\nJSON results written to {args.json_out}")
    if any(ev["status"] != "pass" for ev in results["evaluations"]):
        sys.exit(1)


if __name__ == "__main__":
    main()
