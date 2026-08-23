"""护城河全自动（AutoMoat）测试 — 反事实诚实自动结算 + 自动层
运行：pytest tests/test_auto_moat.py -v
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wanyi import WanYiCore
from wanyi.auto_moat import AutoMoat


@pytest.fixture()
def engine(tmp_path):
    return WanYiCore(db_path=str(tmp_path / "moat.db"), session_id="pytest")


def _insert_open_branch(engine, branch_id="cf_test_1", days_ago=3):
    yesterday = (datetime.now() - timedelta(days=days_ago)).isoformat()[:10]
    now = datetime.now().isoformat(timespec="seconds")
    engine.db.conn.execute(
        """INSERT OR REPLACE INTO counterfactual_branches
        (branch_id, decision_text, decision_type, risk_level, fact_path, counter_path,
         verdict, settlement_date, created_at, updated_at, session_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (branch_id, "大涨后追涨全仓", "trade", "critical",
         "taken: 追涨全仓", "counter: 分批轻仓", "open", yesterday, now, now, "pytest"),
    )
    engine.db.conn.commit()


def test_auto_settle_expires_overdue_open(engine, tmp_path):
    # 一条已到期的 open 分支（无置信度实测数据 → 应诚实标记 expired，不编造赢家）
    _insert_open_branch(engine, "cf_expire_1", days_ago=3)
    # 一条未来到期的 open 分支（不应被结算）
    _insert_open_branch(engine, "cf_future_1", days_ago=-30)

    am = AutoMoat(db_path=str(tmp_path / "moat.db"), session_id="pytest")
    try:
        res = am.auto_settle_due()
        assert res["expired"] == 1, "应诚实过期 1 条"
        assert "cf_expire_1" in res["branch_ids_expired"]
        assert res["settled"] == 0, "无实测数据不应判定赢家"
        row = engine.db.conn.execute(
            "SELECT verdict, lesson_learned FROM counterfactual_branches WHERE branch_id='cf_expire_1'"
        ).fetchone()
        assert row["verdict"] == "expired"
        assert "诚实归档" in row["lesson_learned"]
        future = engine.db.conn.execute(
            "SELECT verdict FROM counterfactual_branches WHERE branch_id='cf_future_1'"
        ).fetchone()
        assert future["verdict"] == "open", "未来到期分支不应被动"
    finally:
        am.close()


def test_run_once_orchestrates_without_crash(engine, tmp_path):
    _insert_open_branch(engine, "cf_run_1", days_ago=1)
    engine.tool_record_memory(content="重要的一件事", layer="法", mem_type="principle")
    am = AutoMoat(db_path=str(tmp_path / "moat.db"), session_id="pytest")
    try:
        report = am.run_once()
        assert "auto_settle" in report
        assert "consolidate" in report
        assert "analog" in report
        assert "knowledge_gaps" in report
        assert report["auto_settle"]["expired"] >= 1
    finally:
        am.close()


def test_auto_settle_grace_keeper(engine, tmp_path):
    # 到期但未超过宽限期：grace_days 增大时不应再被抓到（此处验证接口存在且返回0）
    _insert_open_branch(engine, "cf_grace_1", days_ago=1)
    am = AutoMoat(db_path=str(tmp_path / "moat.db"), session_id="pytest")
    try:
        # grace_days 设很大：上个月到期的仍在阈值内（接口为未来扩展保留），本轮不应新增过期
        res = am.auto_settle_due(grace_days=1000)
        assert res["expired"] == 0, "宽限期内不应结算"
    finally:
        am.close()
