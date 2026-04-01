#!/usr/bin/env python3
"""
vectorize_memories.py — fairy-vector-memory 向量化入口（定时任务每天 02:00 调用）
扫描 memory/ 目录下所有 2026-*.md 文件，增量处理新增/变更的文件。
"""
import json
import sys
from pathlib import Path

# 确保 lib 在 path（支持 .venv/bin/python 直接调用）
sys.path.insert(0, Path(__file__).parent.as_posix())

from lib.storage import init_db, upsert_chunks
from lib.chunker import parse_memory_file
from lib.embedder import embed_texts

MEMORY_DIR = Path("~/.openclaw/workspace/memory").expanduser()
STATE_FILE = MEMORY_DIR / ".vectorize_state.json"


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"mtimes": {}}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def main():
    init_db()
    state = load_state()
    mtimes = state.get("mtimes", {})

    files = sorted(MEMORY_DIR.glob("2026-*.md"))
    processed: list[str] = []

    for filepath in files:
        date = filepath.stem  # "2026-03-30"
        current_mtime = str(filepath.stat().st_mtime)

        if date in mtimes and mtimes[date] == current_mtime:
            print(f"[skip] {date} — 无变化")
            continue

        print(f"[vectorize] {date}")
        chunks = parse_memory_file(filepath, date)

        if not chunks:
            print(f"       ⚠️  无对话块")
            mtimes[date] = current_mtime
            processed.append(date)
            continue

        texts = [c["text"] for c in chunks]
        vectors = embed_texts(texts)
        upsert_chunks(chunks, vectors)

        mtimes[date] = current_mtime
        processed.append(date)
        print(f"       ✅ {len(chunks)} chunks 向量化完成")

    if processed:
        state["mtimes"] = mtimes
        save_state(state)
        print(f"[done] 已处理: {', '.join(processed)}")
    else:
        print("[done] 无新文件需要处理")


if __name__ == "__main__":
    main()
