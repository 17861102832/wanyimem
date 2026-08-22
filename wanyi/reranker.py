"""
v5.2 语义精排模块 — 护城河补强 #2（召回质量再上一台阶）
- 本地中文重排模型 BAAI/bge-reranker-base（CrossEncoder），HF镜像自动切换
- 懒加载：首次调用才加载；失败自动降级（返回 None，调用方跳过精排）
- 混合召回（关键词+向量）后对 Top-N 精排，直接输出相关性分数
"""
import os
import sys

# 中文重排模型名（可换更强模型，如 bge-reranker-v2-m3）
RERANK_MODEL_NAME = os.environ.get("万忆中枢_RERANK_MODEL", "BAAI/bge-reranker-base")
# 首次下载/加载走 hf-mirror（国内可达）
if not os.environ.get("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

_model_instance = None
_model_ok = False


def _get_model():
    """懒加载 CrossEncoder；失败返回 None（降级）"""
    global _model_instance, _model_ok
    if _model_ok:
        return _model_instance
    try:
        from sentence_transformers import CrossEncoder
        _model_instance = CrossEncoder(RERANK_MODEL_NAME)
        _model_ok = True
        return _model_instance
    except Exception as e:
        # MCP server 的 stdout 必须纯净，日志走 stderr
        sys.stderr.write(f"[reranker] 精排模型不可用，跳过精排阶段: {e}\n")
        sys.stderr.flush()
        return None


def rerank(query: str, docs: list, top_k: int = None):
    """
    对 docs 按相关性精排。
    docs: [(memory_id, content), ...]
    返回: [(memory_id, rerank_score), ...] 按分数降序；模型不可用返回 None
    """
    if not docs:
        return None
    model = _get_model()
    if model is None:
        return None
    try:
        pairs = [(query[:512], (content or "")[:512]) for _, content in docs]
        scores = model.predict(pairs, show_progress_bar=False)
        scored = []
        for (mid, _), s in zip(docs, scores):
            try:
                scored.append((mid, float(s)))
            except Exception:
                continue
        scored.sort(key=lambda x: x[1], reverse=True)
        if top_k and top_k > 0:
            scored = scored[:top_k]
        return scored
    except Exception as e:
        sys.stderr.write(f"[reranker] 精排执行失败，跳过: {e}\n")
        sys.stderr.flush()
        return None


def rerank_available() -> bool:
    """模型是否已加载成功（供 stats 自检用）"""
    return _model_ok
