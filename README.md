# Fairy Vector Memory System

基于 `fairy-memory-update` 写入的 markdown 记忆文件，构建本地向量索引，实现按需语义检索。

## 架构

```
session JSONL (.jsonl)
       │
       ▼
fairy_memory_update.py      ← 每分钟 cron，写入 memory/*.md
       │
       ▼
memory/*.md                  ← 对话追加格式
       │
       ▼
vectorize_memories.py       ← 每天 02:00 cron，向量化
       │
       ├── lib/chunker.py   ← 解析 .md → chunk 列表
       ├── lib/embedder.py  ← OpenAI 兼容 API embedding
       └── lib/storage.py  ← LanceDB 写入
       │
       ▼
~/.lancedb/memory_chunks.lance   ← 向量数据库
       │
       ▼
search_memory.py            ← skill 触发，语义搜索
       │
       ├── lib/storage.py   ← LanceDB ANN 搜索
       ├── lib/embedder.py  ← query embedding
       └── lib/retriever.py ← 去重 + 格式化
       │
       ▼
[相关记忆 - YYYY-MM-DD HH:MM]   ← 上下文注入 LLM
```

## 依赖

- Embedding API: `http://127.0.0.1:8000/v1` (bge-m3-mlx-4bit)
- 向量数据库: LanceDB (`~/.lancedb/memory_chunks.lance`)
- Python 包: `numpy`, `lancedb`, `openai`, `pandas`

## 命令

```bash
cd ~/.openclaw/workspace/scripts/fairy-vector-memory

# 安装依赖
uv pip install numpy lancedb openai pandas

# 运行测试
.venv/bin/python -m pytest tests/

# 手动向量化
.venv/bin/python vectorize_memories.py

# 手动搜索
.venv/bin/python search_memory.py "查一下上次讨论的内容"
```

## 存储

| 路径 | 说明 |
|------|------|
| `~/.lancedb/memory_chunks.lance` | LanceDB 向量数据库 |
| `~/.openclaw/workspace/memory/YYYY-MM-DD.md` | 源记忆文件 |
| `~/.openclaw/workspace/memory/.vectorize_state.json` | 向量化状态（增量追踪） |

## chunk 格式

```json
{
  "id": "2026-03-30_2023_001",
  "date": "2026-03-30",
  "time_start": "20:23",
  "time_end": "20:28",
  "speakers": ["主人", "Fairy"],
  "text": "- [20:23] 主人：需要修复\n  『Fairy：Claude Code 发现了问题...』",
  "chunk_index": 1
}
```

## 检索流程

1. 用户 query embedding（OpenAI 兼容 API）
2. LanceDB ANN 搜索（30 天内，limit 50）
3. Python 去重（同日期 text 相似度 > 0.9 → 保留 chunk_index 最大的）
4. 取 top-5，按 date DESC + chunk_index DESC 排序
5. 格式化为 `[相关记忆 - YYYY-MM-DD HH:MM]` 输出
