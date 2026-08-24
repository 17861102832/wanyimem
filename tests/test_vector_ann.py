"""v5.2 向量检索拆分模块测试 —— 精确 vs vec0 ANN（无模型、CI 友好）
运行：pytest tests/test_vector_ann.py -v
说明：
- 用 monkeypatch 的伪向量（带“第N只→one-hot”语义）替代真实模型，不依赖网络/模型下载。
- 若 sqlite-vec 未安装，则只验证精确路径（ANN 相关断言跳过），保证 CI 不因可选依赖失败。
"""
import re
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import wanyi.vector_memory as vm

# 探测 sqlite-vec 是否可用（可选依赖）
try:
    import sqlite_vec  # noqa
    HAS_VEC = True
except Exception:
    HAS_VEC = False


def fake_embed(text):
    """伪向量：文本含“第N只”时 → one-hot(第N维)，否则给一个基础向量（都归一化）"""
    m = re.search(r"第(\d+)只", text or "")
    if m:
        n = int(m.group(1))
        v = np.zeros(8, dtype=np.float32)
        v[n % 8] = 1.0
        return v
    v = np.zeros(8, dtype=np.float32)
    v[0] = 0.5
    v[1] = 0.5
    return v / (np.linalg.norm(v) + 1e-9)


@pytest.fixture()
def idx(tmp_path, monkeypatch):
    monkeypatch.setattr(vm, "embed_text", fake_embed)
    monkeypatch.setattr(vm, "ANN_MIN_COUNT", 3)  # 小规模也走 ANN 分支
    monkeypatch.setattr(vm, "ANN_OVERSAMPLE", 3)
    _idx = vm.VectorIndex(str(tmp_path / "vec.db"))
    yield _idx
    try:
        _idx.close()
    except Exception:
        pass


def test_exact_and_ann_agree(idx):
    # 写入 6 条
    for i in range(6):
        idx.store(f"m{i}", f"用户喜欢的是第{i}只基金，适合长期持有")
    assert idx.count() == 6
    # 精确与 ANN 影子表同步（若可用）
    if HAS_VEC:
        ann = idx.conn.execute("SELECT COUNT(*) FROM memory_ann").fetchone()[0]
        mp = idx.conn.execute("SELECT COUNT(*) FROM memory_ann_map").fetchone()[0]
        assert ann == 6 and mp == 6, "ANN 影子表应同步 6 条"
    # 查询应把“第0只”排到第一（精确路径断言，与是否启用 ANN 无关）
    res = idx.search("第0只基金", limit=3, threshold=0.0)
    assert res, "应有返回"
    assert res[0][0] == "m0", f"top1 应为 m0，实际 {[x[0] for x in res]}"


def test_ann_path_rank(idx):
    if not HAS_VEC:
        pytest.skip("sqlite-vec 未安装，跳过 ANN 路径断言")
    for i in range(6):
        idx.store(f"m{i}", f"第{i}只基金")
    qv = fake_embed("第0只基金")
    ann_res = idx._ann_search(qv, limit=3, threshold=0.0)
    assert ann_res[0][0] == "m0", f"ANN 路径 top1 应为 m0，实际 {[x[0] for x in ann_res]}"


def test_dim_change_keeps_authority(idx, monkeypatch):
    # 权威表保留全部；ANN 只索引当前维度向量（旧维度向量无法进新 dim 的 vec0）
    for i in range(6):
        idx.store(f"m{i}", f"第{i}只基金")

    def fake_embed16(text):
        m = re.search(r"第(\d+)只", text or "")
        if m:
            n = int(m.group(1))
            v = np.zeros(16, dtype=np.float32)
            v[n % 16] = 1.0
            return v
        v = np.zeros(16, dtype=np.float32)
        v[0] = 0.5
        return v / (np.linalg.norm(v) + 1e-9)

    # 换模型：用 monkeypatch.setattr，测试结束自动还原，避免污染其它用例
    monkeypatch.setattr(vm, "embed_text", fake_embed16)
    idx.store("m_new", "第3只相关")
    assert idx.count() == 7, "权威表应保留全部 7 条"
    if HAS_VEC:
        assert idx._ann_dim == 16, "ANN 维度应更新为 16"
        ann = idx.conn.execute("SELECT COUNT(*) FROM memory_ann").fetchone()[0]
        assert ann == 1, "ANN 只索引新维度向量"


def test_store_batch_embeds_once(idx, monkeypatch):
    """store_batch 应批量编码（encode 只调 1 次）且全部落库，比逐条 store 快。"""
    calls = {"encode": 0}

    class FakeModel:
        def encode(self, texts, batch_size=32, normalize_embeddings=True):
            calls["encode"] += 1
            out = []
            import re as _re
            for t in texts:
                m = _re.search(r"第(\d+)只", t or "")
                v = np.zeros(8, dtype=np.float32)
                if m:
                    v[int(m.group(1)) % 8] = 1.0
                out.append(v)
            return out

    monkeypatch.setattr(vm, "_get_model", lambda: FakeModel())
    items = [(f"b{i}", f"第{i}只基金") for i in range(8)]
    idx.store_batch(items)
    assert idx.count() == 8, "应写入全部 8 条"
    assert calls["encode"] == 1, "应一次批量编码，而非逐条"
    if HAS_VEC:
        ann = idx.conn.execute("SELECT COUNT(*) FROM memory_ann").fetchone()[0]
        assert ann == 8, "ANN 影子表应同步 8 条"
