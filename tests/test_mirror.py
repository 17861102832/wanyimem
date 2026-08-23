"""只读 Markdown 镜像导出测试（wanyimem 护城河 #6）
运行：pytest tests/test_mirror.py -v
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wanyi import WanYiCore
from wanyi.mirror import export_markdown


@pytest.fixture()
def engine(tmp_path):
    return WanYiCore(db_path=str(tmp_path / "mirror.db"), session_id="pytest")


def test_export_sections_and_content(engine, tmp_path):
    engine.tool_record_memory(content="止损纪律：亏损超过8%无条件卖出", layer="法", mem_type="principle", category="纪律")
    engine.tool_record_memory(content="买基金用定投，摊薄成本", layer="术", mem_type="strategy", category="基金")
    engine.tool_record_memory(content="敬畏市场，保住本金是第一原则", layer="道", mem_type="principle", category="心法")

    md = export_markdown(str(tmp_path / "mirror.db"))
    # 覆盖三大层标题
    assert "## 道 · 记忆" in md
    assert "## 法 · 记忆" in md
    assert "## 术 · 记忆" in md
    # 内容都在
    assert "止损纪律：亏损超过8%无条件卖出" in md
    assert "买基金用定投，摊薄成本" in md
    assert "敬畏市场，保住本金是第一原则" in md
    # 有类型元信息
    assert "类型原则" in md or "类型策略" in md
    # 总览存在
    assert "## 总览" in md
    assert "记忆（道/法/术）" in md


def test_export_layer_filter(engine, tmp_path):
    engine.tool_record_memory(content="道层的一条", layer="道", mem_type="principle")
    engine.tool_record_memory(content="术层的一条", layer="术", mem_type="note")
    md = export_markdown(str(tmp_path / "mirror.db"), layer="道")
    assert "道层的一条" in md
    assert "术层的一条" not in md


def test_export_nonexistent_db(tmp_path):
    md = export_markdown(str(tmp_path / "nope.db"))
    assert "数据库不存在" in md
