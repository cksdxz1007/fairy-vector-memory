#!/usr/bin/env python3
"""
search_memory.py — fairy-vector-memory 检索入口（skill 触发时调用）
接收用户 query，输出 top-5 相关记忆作为上下文。
用法: search_memory.py "<query>"
"""
import sys
from pathlib import Path

sys.path.insert(0, Path(__file__).parent.as_posix())

from lib.retriever import search, format_context


def main():
    if len(sys.argv) < 2:
        print("[search] 用法: search_memory.py <query>")
        sys.exit(1)

    query = sys.argv[1]
    results = search(query, lookback_days=30, top_k=10)
    context = format_context(results)
    print(context)


if __name__ == "__main__":
    main()
