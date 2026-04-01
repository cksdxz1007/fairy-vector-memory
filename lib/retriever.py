"""
lib/retriever.py — Top-K 向量搜索 + 去重 + 格式化
"""
from difflib import SequenceMatcher
from datetime import datetime, timedelta, timezone
import json

from .embedder import embed_query
from .storage import search_by_date_range

LOOKBACK_DAYS = 30
TOP_K = 10
TOP_N = 5  # 去重后返回数量
SIMILARITY_THRESHOLD = 0.9  # 同日期 text 相似度阈值


def search(
    query: str,
    lookback_days: int = LOOKBACK_DAYS,
    top_k: int = TOP_K,
) -> list[dict]:
    """
    向量检索主流程：
    1. Query embedding
    2. LanceDB ANN 搜索 + 日期过滤（over-fetch 50 条）
    3. Python 去重 + 排序
    4. 返回 top-N
    """
    TZ = timezone(timedelta(hours=8))
    today = datetime.now(TZ)
    start_date = (today - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    end_date = today.strftime("%Y-%m-%d")

    # 1. Query embedding
    query_vec = embed_query(query)

    # 2. LanceDB ANN 搜索（over-fetch 50 条供去重）
    results = search_by_date_range(start_date, end_date, query_vec, limit=50)
    if not results:
        return []

    # 3. 构建 chunk 列表（解析 speakers JSON）
    chunks = []
    for row in results:
        chunk = {
            "id": row["chunk_id"],
            "date": row["date"],
            "time_start": row["time_start"],
            "time_end": row["time_end"],
            "speakers": json.loads(row["speakers"]) if row.get("speakers") else [],
            "summary": row.get("summary"),
            "text": row["text"],
            "chunk_index": row["chunk_index"],
            "_distance": row.get("_distance"),
        }
        chunks.append(chunk)

    # 4. 按 _distance 升序排序（低 = 相似度高），取 top_k
    chunks.sort(key=lambda x: x.get("_distance", float("inf")))
    top_chunks = chunks[:top_k]

    # 5. 去重：同日期内 text 相似度 > SIMILARITY_THRESHOLD → 保留 chunk_index 最大的
    deduped: list[dict] = []
    date_groups: dict[str, list[dict]] = {}
    for c in top_chunks:
        date_groups.setdefault(c["date"], []).append(c)

    for date, group in date_groups.items():
        group.sort(key=lambda x: x["chunk_index"], reverse=True)
        for chunk in group:
            is_dup = False
            for kept in deduped:
                if kept["date"] == date:
                    sim = SequenceMatcher(None, chunk["text"], kept["text"]).ratio()
                    if sim > SIMILARITY_THRESHOLD:
                        is_dup = True
                        break
            if not is_dup:
                deduped.append(chunk)

    # 6. 按 date DESC + chunk_index DESC 排序，取 top-N
    deduped.sort(key=lambda x: (x["date"], x["chunk_index"]), reverse=True)
    return deduped[:TOP_N]


def format_context(chunks: list[dict]) -> str:
    """将 chunk 列表格式化为上下文字符串。"""
    if not chunks:
        return "（未找到相关记忆）"
    lines = []
    for chunk in chunks:
        lines.append(f"[相关记忆 - {chunk['date']} {chunk['time_start']}]")
        lines.append(chunk["text"])
        lines.append("")
    return "\n".join(lines)
