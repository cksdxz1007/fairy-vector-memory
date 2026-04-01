"""
lib/embedder.py — OpenAI 兼容 API embedding 封装
bge-m3 向量已 L2-normalized，cosine similarity = dot product。
"""
from openai import OpenAI
import numpy as np

MODEL_NAME = "bge-m3-mlx-4bit"
EMBEDDING_URL = "http://127.0.0.1:8000/v1"
DIM = 1024  # bge-m3 输出维度

_client = OpenAI(base_url=EMBEDDING_URL, api_key="not-needed")


def embed_texts(texts: list[str]) -> list[np.ndarray]:
    """
    批量 embedding，返回 float32 numpy 数组列表。
    通过 OpenAI 兼容 API 的 /v1/embeddings 端点。
    """
    resp = _client.embeddings.create(model=MODEL_NAME, input=texts)
    vectors = []
    for item in resp.data:
        vec = np.array(item.embedding, dtype=np.float32)
        # 维度校验
        if vec.shape[0] != DIM:
            raise ValueError(f"Unexpected embedding dimension: {vec.shape[0]}, expected {DIM}")
        vectors.append(vec)
    return vectors


def embed_query(query: str) -> np.ndarray:
    """query embedding，返回单个向量。"""
    resp = _client.embeddings.create(model=MODEL_NAME, input=[query])
    vec = np.array(resp.data[0].embedding, dtype=np.float32)
    if vec.shape[0] != DIM:
        raise ValueError(f"Unexpected embedding dimension: {vec.shape[0]}, expected {DIM}")
    return vec
