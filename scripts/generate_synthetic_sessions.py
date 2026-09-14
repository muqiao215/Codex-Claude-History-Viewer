#!/usr/bin/env python3
"""Synthetic JSONL session generator for HV-H1.1 benchmarks.

Specifications:
- Version: 1.0.0
- Fixed seed (default: 20260914)
- 20 messages per session (message_count == 20)
- File size: ~16 KiB ± 10% (14,746 - 18,022 bytes)
- Contains Chinese and Unicode text
- Contains long lines (~2-3 KiB)
- Contains bad trailing lines (malformed JSON on the last line)
- Contains identical timestamps across sessions and within sessions
"""
import argparse
import hashlib
import json
from pathlib import Path
import random
import sys

GENERATOR_VERSION = "1.0.0"
DEFAULT_SEED = 20260914
MIN_BYTES = 14746   # 16 KiB - 10%
MAX_BYTES = 18022   # 16 KiB + 10%
TARGET_BYTES = 16384


def generate_session_content(session_idx: int, seed: int = DEFAULT_SEED) -> bytes:
    rng = random.Random(seed + session_idx)
    # Identical timestamps across batches: batches of 50 sessions share identical start timestamp
    batch_id = session_idx // 50
    base_ts = f"2026-09-01T{batch_id % 24:02d}:00:00.000Z"
    session_id = f"synthetic-codex-{session_idx:05d}"
    cwd = f"/work/project-{batch_id:03d}"

    lines = []
    # Session metadata header
    meta = {
        "timestamp": base_ts,
        "type": "session_meta",
        "payload": {
            "id": session_id,
            "timestamp": base_ts,
            "cwd": cwd,
        }
    }
    lines.append(json.dumps(meta, ensure_ascii=False))

    # 20 valid message items (alternating user and assistant)
    for i in range(20):
        role = "user" if i % 2 == 0 else "assistant"
        # Within session, messages 0-3 share base_ts (testing identical timestamps)
        if i < 4:
            msg_ts = base_ts
        else:
            msg_ts = f"2026-09-01T{batch_id % 24:02d}:{(i * 2) % 60:02d}:00.000Z"

        if i == 5:
            # Long line: ~2.4 KiB of trace log data
            core = (
                "【长行测试】系统索引基线测量，大量高密度日志输出：\n"
                + ("TraceStep_LogRecord_DataBlock_Entry_#0123456789_Chunk_ABCDEF_" * 42)
            )
        elif i == 10:
            # Unicode and Chinese special characters
            core = (
                "【Unicode/中文测试】🎯 状态正常 ✨ 检索准确率：100% 🗂️ 目录校验：/var/log/工程事实/验证报告.md "
                "— 特殊符号：№ § ※ ∮ ∯ ⇋ ⇌ 🔍 ⚡ 💡 🚀\n"
                + ("中文填充内容：验证分词、倒排索引与UTF-8编码一致性。" * 10)
            )
        else:
            base = f"会话 {session_idx:05d} 消息 {i + 1:02d}：验证 HistoryReader 增量索引与搜索性能，包含固定种子与生命周期测试。"
            # Sizing tuning: pad_len chosen so total file lands squarely around 16,384 bytes
            pad_len = 22 + rng.randint(-2, 2)
            core = base + ("【数据分块】" * pad_len)

        content_type = "input_text" if role == "user" else "output_text"
        msg = {
            "timestamp": msg_ts,
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": role,
                "content": [{"type": content_type, "text": core}],
            },
        }
        lines.append(json.dumps(msg, ensure_ascii=False))

    # Bad trailing line: truncated malformed JSON
    lines.append(f'{{"timestamp": "{base_ts}", "type": "response_item", "payload": {{"corrupted_trailing": true')

    content = "\n".join(lines) + "\n"
    encoded = content.encode("utf-8")

    # Assert size bounds
    if not (MIN_BYTES <= len(encoded) <= MAX_BYTES):
        raise ValueError(f"Session {session_idx} size {len(encoded)} out of bounds [{MIN_BYTES}, {MAX_BYTES}]")
    return encoded


def generate_dataset(output_dir: Path, count: int, seed: int = DEFAULT_SEED) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    total_bytes = 0
    min_len = float("inf")
    max_len = 0
    file_hashes = []

    for idx in range(count):
        file_bytes = generate_session_content(idx, seed=seed)
        file_len = len(file_bytes)
        total_bytes += file_len
        min_len = min(min_len, file_len)
        max_len = max(max_len, file_len)

        file_name = f"session_{idx:05d}.jsonl"
        file_path = output_dir / file_name
        file_path.write_bytes(file_bytes)

        h = hashlib.sha256(file_bytes).hexdigest()
        file_hashes.append((file_name, h, file_len))

    # Compute overall dataset digest: sha256 of sorted (filename + sha256)
    digest_input = "\n".join(f"{name}:{h}" for name, h, _ in sorted(file_hashes)).encode("utf-8")
    dataset_digest = hashlib.sha256(digest_input).hexdigest()

    manifest = {
        "generator_version": GENERATOR_VERSION,
        "seed": seed,
        "count": count,
        "total_bytes": total_bytes,
        "min_bytes_per_file": min_len,
        "max_bytes_per_file": max_len,
        "avg_bytes_per_file": total_bytes / count if count > 0 else 0,
        "dataset_sha256": dataset_digest,
        "target_bytes_bounds": [MIN_BYTES, MAX_BYTES],
    }

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic JSONL sessions for HV-H1.1 benchmark")
    parser.add_argument("--count", type=int, required=True, help="Number of sessions to generate (e.g. 1000 or 10000)")
    parser.add_argument("--out", type=Path, required=True, help="Target directory under work/")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Fixed random seed")
    args = parser.parse_args()

    print(f"Generating {args.count} synthetic sessions to {args.out} (seed={args.seed})...")
    manifest = generate_dataset(args.out, args.count, seed=args.seed)
    print("Generation complete:")
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
