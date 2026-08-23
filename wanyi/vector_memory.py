"""
v5.2 语义向量检索模块 — 护城河补强 #1（最大短板）+ 向量大规模检索提速
- 本地向量模型 BAAI/bge-small-zh-v1.5（512维），HF镜像自动切换（可用 WANYI_EMBED_MODEL 覆盖）
- 懒加载：首次调用才加载模型；失败自动降级（返回None，调用方走关键词）
- memory_embeddings 表存储向量（BLOB float32）【权威真值，始终保留】
- 检索混合策略：
    · 规模 < ANN_MIN_COUNT  → 精确全表余弦（正确性优先，量级小够用）
    · 规模 ≥ ANN_MIN_COUNT  → sqlite-vec vec0 ANN 预筛 + 精确重排（提速且保准）
  sqlite-vec 不可用 → 自动回退到纯精确（完全向后兼容）。
- 与 BM25 关键词混合加权召回：hybrid_score()
"""
import os
import sqlite3
from pathlib import Path

import numpy as np
from env_compat import get_env  # v1.1：中文优先/英文兜底

# 中文向量模型名（可换更强模型）
EMBED_MODEL_NAME = get_env("万忆中枢_EMBED_MODEL", "WANYI_EMBED_MODEL", "BAAI/bge-small-zh-v1.5")
# 首次下载/加载走 hf-mirror（国内可达）
if not os.environ.get("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

# ── ANN 阈值与预筛倍数 ────────────────────────────────────────────
ANN_MIN_COUNT = 2000      # 超过该规模才启用 ANN 预筛；否则精确
ANN_OVERSAMPLE = 3        # ANN 预筛候选数 = limit * ANN_OVERSAMPLE + 5，之后精确重排

_model_instance = None
_model_ok = False


def _sqlite_vec():
    """探测 sqlite-vec 是否可用；可用返回 module，否则 None"""
    try:
        import sqlite_vec
        return sqlite_vec
    except Exception:
        return None


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
    """文本 → 归一化向量；失败返回 None"""
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
    """向量索引：读写 memory_embeddings 表 + 可选的 vec0 ANN 影子表，提供余弦检索"""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_table()
        # sqlite-vec 探测（只在需要时加载扩展）
        self._vec_mod = _sqlite_vec()
        self._vec_loaded = False     # 当前连接是否已 enable_load_extension
        self._ann_ready = False      # vec0 影子表是否已建好
        self._ann_dim = None         # 当前影子表向量维度

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

    # ── ANN（sqlite-vec）影子表管理 ───────────────────────────────

    def _load_vec(self) -> bool:
        """尝试加载 sqlite-vec 扩展到当前连接；成功返回 True"""
        if self._vec_mod is None:
            return False
        try:
            if not self._vec_loaded:
                self.conn.enable_load_extension(True)
                self._vec_mod.load(self.conn)
                self._vec_loaded = True
            return True
        except Exception:
            return False

    def _ensure_ann(self, dim: int):
        """按维度确保 vec0 影子表存在；维度变化时重建并从 memory_embeddings 重建数据"""
        if not self._load_vec():
            self._ann_ready = False
            return
        if self._ann_ready and self._ann_dim == dim:
            return
        # 映射表（保存 vec0 分配的 rowid ↔ memory_id）
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS memory_ann_map (rowid INTEGER PRIMARY KEY, memory_id TEXT UNIQUE)"
        )
        try:
            meta = self.conn.execute(
                "SELECT v FROM memory_ann_meta WHERE k='dim'"
            ).fetchone() if self._table_exists("memory_ann_meta") else None
            cur_dim = int(meta["v"]) if meta else None
        except Exception:
            cur_dim = None

        if self._table_exists("memory_ann"):
            if cur_dim == dim:
                self._ann_ready = True
                self._ann_dim = dim
                return
            # 维度变化 → 重建
            self.conn.execute("DROP TABLE memory_ann")
            self.conn.execute("DROP TABLE IF EXISTS memory_ann_map")

        # 建 vec0 影子表（distance_metric=cosine -> distance = 1 - cosine_sim）
        self.conn.execute(
            f"CREATE VIRTUAL TABLE memory_ann USING vec0(embedding float[{dim}] distance_metric=cosine)"
        )
        # 维度变化重建分支可能已 DROP 掉映射表，这里重建
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS memory_ann_map (rowid INTEGER PRIMARY KEY, memory_id TEXT UNIQUE)"
        )
        self.conn.execute("CREATE TABLE IF NOT EXISTS memory_ann_meta (k TEXT PRIMARY KEY, v TEXT)")
        self.conn.execute(
            "INSERT OR REPLACE INTO memory_ann_meta (k, v) VALUES ('dim', ?)", (str(dim),)
        )
        self._ann_ready = True
        self._ann_dim = dim
        self.conn.commit()
        # 从 memory_embeddings 重建影子表（若原有向量）
        self._rebuild_ann_from_exact()

    def _table_exists(self, name: str) -> bool:
        try:
            return self.conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type IN ('table','virtual') AND name=?", (name,)
            ).fetchone() is not None
        except Exception:
            return False

    def _rebuild_ann_from_exact(self):
        """把 memory_embeddings 里的向量全部镜像进 vec0 影子表（维度变化/重建后调用）"""
        if not self._ann_ready:
            return
        try:
            rows = self.conn.execute(
                "SELECT memory_id, embedding FROM memory_embeddings"
            ).fetchall()
            for r in rows:
                vec = np.frombuffer(r["embedding"], dtype=np.float32)
                if vec.shape[0] != self._ann_dim:
                    continue
                cur = self.conn.execute(
                    "INSERT INTO memory_ann(embedding) VALUES (?)", (vec.tobytes(),)
                )
                rid = cur.lastrowid
                self.conn.execute(
                    "INSERT OR REPLACE INTO memory_ann_map(rowid, memory_id) VALUES (?,?)",
                    (rid, r["memory_id"]),
                )
            self.conn.commit()
        except Exception:
            self.conn.rollback()

    # ── 写入 ──────────────────────────────────────────────────────

    def store(self, memory_id: str, content: str):
        """写入一条记忆的向量（模型不可用则跳过，不抛异常）"""
        if not memory_id or not content:
            return
        vec = embed_text(content)
        if vec is None:
            return
        dim = int(vec.shape[0])
        from datetime import datetime
        now = datetime.now().isoformat()
        try:
            self.conn.execute(
                "INSERT OR REPLACE INTO memory_embeddings (memory_id, embedding, dim, model_name, updated_at) VALUES (?,?,?,?,?)",
                (memory_id, vec.tobytes(), dim, EMBED_MODEL_NAME, now),
            )
            self.conn.commit()
        except Exception:
            return
        # 镜像进 ANN 影子表（失败不影响精确通道）
        self._mirror_to_ann(memory_id, vec, dim)

    def _mirror_to_ann(self, memory_id: str, vec, dim: int):
        if not self._load_vec():
            return
        try:
            self._ensure_ann(dim)
            if not self._ann_ready:
                return
            # 旧映射删除（若存在）
            old = self.conn.execute(
                "SELECT rowid FROM memory_ann_map WHERE memory_id=?", (memory_id,)
            ).fetchone()
            if old:
                self.conn.execute("DELETE FROM memory_ann WHERE rowid=?", (old[0],))
                self.conn.execute("DELETE FROM memory_ann_map WHERE rowid=?", (old[0],))
            cur = self.conn.execute(
                "INSERT INTO memory_ann(embedding) VALUES (?)", (vec.tobytes(),)
            )
            rid = cur.lastrowid
            self.conn.execute(
                "INSERT OR REPLACE INTO memory_ann_map(rowid, memory_id) VALUES (?,?)",
                (rid, memory_id),
            )
            self.conn.commit()
        except Exception:
            try:
                self.conn.rollback()
            except Exception:
                pass

    def store_batch(self, items):
        """批量写入 [(memory_id, content), ...]"""
        for mid, content in items:
            self.store(mid, content)

    # ── 检索 ──────────────────────────────────────────────────────

    def search(self, query: str, limit: int = 20, threshold: float = 0.30):
        """查询向量 → 余弦相似度 TOP-N；返回 [(memory_id, score), ...]
        规模小走精确；规模大且可用则 ANN 预筛 + 精确重排。"""
        qv = embed_text(query)
        if qv is None:
            return []
        cnt = self.count()
        use_ann = False
        if self._ann_ready and self._vec_mod is not None and cnt >= ANN_MIN_COUNT:
            use_ann = self._load_vec() and self._ann_dim == int(qv.shape[0])
        if use_ann:
            return self._ann_search(qv, limit, threshold)
        return self._exact_search(qv, limit, threshold)

    def _exact_search(self, qv, limit, threshold):
        """全表精确余弦（correctness-first；小规模/降级路径）"""
        rows = self.conn.execute(
            "SELECT memory_id, embedding FROM memory_embeddings"
        ).fetchall()
        if not rows:
            return []
        scored = []
        for r in rows:
            try:
                vec = np.frombuffer(r["embedding"], dtype=np.float32)
                if vec.shape[0] != qv.shape[0]:
                    continue
                sim = float(np.dot(qv, vec))  # 已归一化，点积=余弦
                if sim >= threshold:
                    scored.append((r["memory_id"], sim))
            except Exception:
                continue
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

    def _ann_search(self, qv, limit, threshold):
        """vec0 ANN 预筛（k = limit*oversample+5）→ 用完整 embedding 精确重排"""
        try:
            q = qv.tobytes()
            knn = limit * ANN_OVERSAMPLE + 5
            rows = self.conn.execute(
                "SELECT map.memory_id, emb.embedding, ann.distance "
                "FROM memory_ann ann "
                "JOIN memory_ann_map map ON map.rowid = ann.rowid "
                "JOIN memory_embeddings emb ON emb.memory_id = map.memory_id "
                "WHERE ann.embedding MATCH ? AND k = ? ORDER BY ann.distance",
                (q, knn),
            ).fetchall()
            scored = []
            for r in rows:
                vec = np.frombuffer(r["embedding"], dtype=np.float32)
                if vec.shape[0] != qv.shape[0]:
                    continue
                sim = float(np.dot(qv, vec))  # 精确余弦
                if sim >= threshold:
                    scored.append((r["memory_id"], sim))
            scored.sort(key=lambda x: x[1], reverse=True)
            return scored[:limit]
        except Exception:
            # ANN 查询异常 → 回退精确
            return self._exact_search(qv, limit, threshold)

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
