# -*- coding: utf-8 -*-
"""
v5.1 语义向量检索模块 — 护城河补强 #1（最大短板）
- 本地中文向量模型 BAAI/bge-small-zh-v1.5（512维），HF镜像自动切换
- 懒加载：首次调用才加载模型；失败自动降级（返回None，调用方走关键词）
- memory_embeddings 表存储向量（BLOB float32）
- 余弦相似度检索 + 与关键词 BM25 混合加权召回
"""
import os
import sqlite3
import numpy as np
from pathlib import Path

# 中文向量模型名（可换更强模型）
EMBED_MODEL_NAME = os.environ.get("万忆中枢_EMBED_MODEL", "BAAI/bge-small-zh-v1.5")
# 首次下载/加载走 hf-mirror（国内可达）
if not os.environ.get("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

_model_instance = None
_model_ok = False


def _get_model():
    """懒加载 sentence-transformers 模型；失败返回 None（降级）"""
    global _model_instance, _model_ok
    if _model_ok:
        return _model_instance
    try:
        from sentence_transformers import SentenceTransformer
        _model_instance = SentenceTransformer(EMBED_MODEL_NAME)
        _model_ok = True
        return _model_instance
    except Exception as e:
        # v4.6.1 修复：MCP server 的 stdout 必须纯净，日志改走 stderr
        import sys
        sys.stderr.write(f"[vector] 向量模型不可用，降级为关键词检索: {e}\n")
        sys.stderr.flush()
        return None


def embed_text(text: str):
    """文本 → 512维归一化向量；失败返回 None"""
    model = _get_model()
    if model is None:
        return None
    try:
        text = (text or "")[:512]  # 截断，控制成本
        if not text.strip():
            return None
        vec = model.encode(text, normalize_embeddings=True)
        return np.asarray(vec, dtype=np.float32)
    except Exception:
        return None


class VectorIndex:
    """向量索引：读写 memory_embeddings 表，提供余弦检索"""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_table()

    def _init_table(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_embeddings (
                memory_id TEXT PRIMARY KEY,
                embedding BLOB NOT NULL,
                dim INTEGER NOT NULL,
                model_name TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        self.conn.commit()

    def store(self, memory_id: str, content: str):
        """写入一条记忆的向量（模型不可用则跳过，不抛异常）"""
        if not memory_id or not content:
            return
        vec = embed_text(content)
        if vec is None:
            return
        from datetime import datetime
        now = datetime.now().isoformat()
        try:
            self.conn.execute(
                "INSERT OR REPLACE INTO memory_embeddings (memory_id, embedding, dim, model_name, updated_at) VALUES (?,?,?,?,?)",
                (memory_id, vec.tobytes(), int(vec.shape[0]), EMBED_MODEL_NAME, now),
            )
            self.conn.commit()
        except Exception:
            pass

    def store_batch(self, items):
        """批量写入 [(memory_id, content), ...]"""
        for mid, content in items:
            self.store(mid, content)

    def search(self, query: str, limit: int = 20, threshold: float = 0.30):
        """查询向量 → 余弦相似度 TOP-N；返回 [(memory_id, score), ...]"""
        qv = embed_text(query)
        if qv is None:
            return []
        rows = self.conn.execute(
            "SELECT memory_id, embedding FROM memory_embeddings"
        ).fetchall()
        if not rows:
            return []
        q = np.asarray(qv, dtype=np.float32)
        scored = []
        for r in rows:
            try:
                vec = np.frombuffer(r["embedding"], dtype=np.float32)
                if vec.shape[0] != q.shape[0]:
                    continue
                sim = float(np.dot(q, vec))  # 已归一化，点积=余弦
                if sim >= threshold:
                    scored.append((r["memory_id"], sim))
            except Exception:
                continue
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

    def count(self) -> int:
        try:
            return self.conn.execute("SELECT COUNT(*) FROM memory_embeddings").fetchone()[0]
        except Exception:
            return 0

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass


def hybrid_score(kw_score: float, vec_score: float, kw_weight: float = 0.4, vec_weight: float = 0.6):
    """混合召回融合：关键词分 + 向量分加权（量纲已各自归一化）"""
    return kw_score * kw_weight + vec_score * vec_weight
