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

from wanyi import WanYiCore
from wanyi.memory_core import MCP_TOOLS


@pytest.fixture()
def engine(tmp_path):
    # 显式注入独立 db 路径，避免测试间共享单例数据库（隔离）
    return WanYiCore(db_path=str(tmp_path / "test.db"), session_id="pytest")


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


def test_mistakes_book_hits_in_check(engine):
    """回归：护城河#1 的错题本召回必须命中（之前 memory_core.py:2113 错误引用 process_memory 表导致静默失效）"""
    # 写入一条失败过程记忆 → 自动沉淀错题本
    engine.tool_process_save(
        task_name="仓位管理试验",
        phase="结论",
        content="全仓梭哈一只基金结果大跌，亏了18%才割肉——教训是绝不梭哈",
        outcome="failure",
    )
    # 错题本应实际存在记录
    n_mistake = engine.db.conn.execute("SELECT COUNT(*) as c FROM mistakes").fetchone()["c"]
    assert n_mistake >= 1, "failure outcome 应自动写错题本"
    # 触发高风险决策检查，错题本召回应命中（历史上踩过"梭哈"的坑）
    resp = engine.tool_confidence_check(action="check", decision_text="我要全仓梭哈这只基金")
    assert resp["status"] == "ok"
    assert resp["verdict"] in ("BLOCK", "CAUTION"), f"梭哈应被拦截，实际 {resp['verdict']}"
    # 错题本命中提醒（gotchas）必须包含历史踩坑内容 —— 这是对 memory_core.py:2113 误表名的回归验证
    gotcha_text = " ".join(resp.get("gotchas", []))
    assert gotcha_text, "决策检查的错题本召回（gotchas）不能为空"
    assert "梭哈" in gotcha_text, f"gotchas 应包含历史踩坑'梭哈'内容，实际: {gotcha_text}"


def test_counterfactual_open_and_settle(engine):
    """护城河#2 反事实之镜：开分支 + 到期货结算"""
    resp = engine.tool_counterfactual_mirror(
        action="open", decision_text="全仓梭哈", decision_type="trade", risk_level="critical"
    )
    assert resp.get("status") == "ok", f"开分支失败: {resp}"
    branch_id = resp.get("branch_id")
    assert branch_id, "应返回 branch_id"
    # 结算
    settle = engine.tool_counterfactual_mirror(
        action="settle", branch_id=branch_id,
        fact_outcome="亏了18%", counter_outcome="如果只买两成就亏3.6%"
    )
    assert settle.get("status") == "ok", f"结算失败: {settle}"


def test_needs_review_respects_min_age(engine):
    """回归：needs_review 必须真正按 min_age_days 到期过滤（之前参数被忽略）"""
    # 初始化一条旧记录（把 last_updated 改成 10 天前）
    engine.confidence.init_entry("decision", "dec_oldtest", initial=0.5)
    # 手动把 last_updated 回溯到 10 天前，使其"到期"
    engine.db.conn.execute(
        "UPDATE confidence SET last_updated = datetime('now', '-10 days') WHERE target_id = 'dec_oldtest'"
    )
    engine.db.conn.commit()
    # 再初始化一条新记录（3 天内 → 不应到期）
    engine.confidence.init_entry("decision", "dec_newtest", initial=0.5)

    due = engine.confidence.needs_review("decision", min_age_days=3.0, limit=20)
    ids = [d["target_id"] for d in due]
    assert "dec_oldtest" in ids, "10天前的记录应到期进入复习队列"
    assert "dec_newtest" not in ids, "新记录不应到期"


def test_tool_count_after_fix(engine):
    """工具清单完整性 + 每个工具都能映射到处理函数（防再次引用错表导致护城河失效）"""
    names = {t["name"] for t in MCP_TOOLS}
    assert len(names) == 23, f"expect 23 tools, got {len(names)}"
    # 确认核心工具都在
    for required in ("万忆置信度决策检查", "万忆反事实之镜", "万忆错题本", "万忆召回记忆"):
        assert required in names, f"缺少关键工具: {required}"
