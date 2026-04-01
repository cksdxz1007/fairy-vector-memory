"""
lib/storage.py — LanceDB storage for memory_chunks
向量以 LanceDB native Vector 列存储，替代 SQLite BLOB。
"""
import lancedb
from lancedb.pydantic import LanceModel, Vector
import json
import numpy as np
from pathlib import Path
from typing import Optional  # noqa: F401

LANCE_DB_PATH = Path("~/.lancedb").expanduser()
TABLE_NAME = "memory_chunks"


class MemoryChunk(LanceModel):
    chunk_id: str
    date: str
    time_start: str
    time_end: Optional[str]
    speakers: str  # JSON string
    summary: Optional[str]
    text: str
    chunk_index: int
    vector: Vector(1024)


def get_db():
    return lancedb.connect(LANCE_DB_PATH)


def init_db():
    """创建表（幂等调用）"""
    db = get_db()
    if TABLE_NAME not in db.table_names():
        db.create_table(TABLE_NAME, schema=MemoryChunk, mode="create")


def _chunk_to_row(chunk: dict, vector: np.ndarray) -> dict:
    return {
        "chunk_id": chunk["id"],
        "date": chunk["date"],
        "time_start": chunk["time_start"],
        "time_end": chunk.get("time_end"),
        "speakers": json.dumps(chunk["speakers"], ensure_ascii=False),
        "summary": chunk.get("summary"),
        "text": chunk["text"],
        "chunk_index": chunk["chunk_index"],
        "vector": vector.tolist(),
    }


def upsert_chunks(chunks: list[dict], vectors: list[np.ndarray]):
    """批量 upsert chunks + vectors（merge_insert 语义）"""
    db = get_db()
    table = db[TABLE_NAME]
    rows = [_chunk_to_row(c, v) for c, v in zip(chunks, vectors)]
    table.merge_insert("chunk_id") \
        .when_matched_update_all() \
        .when_not_matched_insert_all() \
        .execute(rows)


def search_by_date_range(
    start_date: str,
    end_date: str,
    query_vector: np.ndarray,
    limit: int = 50,
) -> list[dict]:
    """ANN 搜索 + 日期过滤，返回 LanceDB result dicts"""
    db = get_db()
    table = db[TABLE_NAME]
    results = (
        table.search(query_vector.tolist())
            .where(f"date >= '{start_date}' AND date <= '{end_date}'")
            .limit(limit)
            .to_pandas()
    )
    return results.to_dict("records")
