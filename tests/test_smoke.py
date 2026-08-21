# -*- coding: utf-8 -*-
"""冒烟测试：CI 无模型环境下验证核心链路（模型缺失自动降级，不应失败）
运行：pytest tests/ -v
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("万忆中枢_MEMORY_DB", os.path.join(tempfile.gettempdir(), "wanyi_ci_test.db"))
os.environ.setdefault("OBSIDIAN_VAULT", "")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wanyi import WanYiCore  # noqa: E402
from wanyi.memory_core import MCP_TOOLS  # noqa: E402


@pytest.fixture()
def engine(tmp_path):
    os.environ["万忆中枢_MEMORY_DB"] = str(tmp_path / "test.db")
    return WanYiCore()


def test_tool_count(engine):
    names = {t["name"] for t in MCP_TOOLS}
    assert len(names) == 23, f"expect 23 tools, got {len(names)}"


def test_record_and_recall(engine):
    r = engine.tool_record_memory(
        content="止损纪律：亏损超过8%必须无条件卖出",
        layer="法", mem_type="principle",
    )
    assert r["status"] in ("inserted", "updated")
    resp = engine.tool_recall_memory("止损规则", limit=5)
    assert resp["results_count"] >= 1


def test_knowledge_gap(engine):
    # 完全无关查询 → 应记录知识空白（兜底记忆不算真实命中）
    resp = engine.tool_recall_memory("量子计算的原理是什么", limit=5)
    assert "knowledge_gap" in resp, "weak recall should record knowledge-gap"
    stats = engine.tool_knowledge_gap(action="stats")
    assert "元认知自检" in str(stats) or stats.get("status") == "ok"


def test_graph_auto_link(engine):
    engine.tool_record_memory(
        content="止损纪律：亏损超过8%必须无条件卖出",
        layer="法", mem_type="principle", category="交易纪律",
    )
    engine.tool_record_memory(
        content="交易纪律：单只基金仓位不超过两成",
        layer="法", mem_type="principle", category="交易纪律",
    )
    edges = engine.db.conn.execute(
        "SELECT COUNT(*) as c FROM graph_edges"
    ).fetchone()["c"]
    assert edges >= 1, "same-category edge should be auto-created"


def test_time_fields(engine):
    engine.tool_record_memory(content="2026年5月基金大跌死扛不止损亏了18%", layer="法")
    resp = engine.tool_recall_memory("认赔离场到底对不对", limit=5)
    assert resp["results_count"] >= 1
    m = resp["memories"][0]
    assert "_age_days" in m and "_time_decay" in m and "_stale" in m
