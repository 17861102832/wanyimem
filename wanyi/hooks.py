#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║        万 忆 中 枢  v3 — 五齿轮·四钩子 生命周期引擎              ║
║                                                               ║
║  五齿轮（自动反思，无需用户说话）：                               ║
║    ⚙️ DECISION    → 决策日记（道级，钉住）                       ║
║    ⚙️ PATTERN     → 模式抽象（法级，60天半衰）                   ║
║    ⚙️ SKILL       → 技能建议（法级，90天半衰）                   ║
║    ⚙️ POSTMORTEM  → 撞墙复盘（法级，钉住）                       ║
║    ⚙️ MEMORY      → 知识沉淀（术→法 升降级）                     ║
║                                                               ║
║  四钩子（会话生命周期，自动触发）：                               ║
║    🔌 LOAD   → 会话启动：注入道+法 + 断点续传 + 图谱预热         ║
║    👁️ MONITOR → 任务节点：事件溯源 + 进度快照 + 实体提取         ║
║    💭 REFLECT → 任务完成：五齿轮自动反思 + 图谱自动构建          ║
║    💾 STORE   → 会话结束：汇总存档 + 睡眠巩固 + 跨会话同步       ║
║                                                               ║
║  核心设计（不可修改清单）：                                      ║
║    1. 五齿轮反思 = 自动触发，不等用户指令                        ║
║    2. 事件溯源 = append-only，绝不覆盖                          ║
║    3. 道法术三层 = 分离存储，绝不合并                            ║
║    4. 四钩子生命周期 = 一个都不能少                              ║
╚══════════════════════════════════════════════════════════════════╝
"""
import json
import os
import re
import sys
import time
from datetime import datetime
from typing import Any

# 导入核心引擎（同目录）
sys.path.insert(0, os.path.dirname(__file__))
from memory_core import (
    LAYER_DAO,
    LAYER_FA,
    LAYER_SHU,
    MEMORY_TYPES,
    PRIVACY_INTERNAL,
    SESSION_ID,
    SPACE_GLOBAL,
    SPACE_PROJECT,
    STORE_DIR,
    WanYiCore,
    init_dirs,
    now_iso,
)

# ═══════════════════════════════════════════════════════════════════
# 目录初始化
# ═══════════════════════════════════════════════════════════════════
REFLECTION_DIR = STORE_DIR / "reflections"     # 反思产物归档（人可读）
PROGRESS_DIR   = STORE_DIR / "progress"        # 进度快照备份

def _ensure_dirs():
    for d in [REFLECTION_DIR, PROGRESS_DIR]:
        d.mkdir(parents=True, exist_ok=True)

_ensure_dirs()


# ═══════════════════════════════════════════════════════════════════
# 实体提取器（启发式，用于自动构建知识图谱）
# ═══════════════════════════════════════════════════════════════════

# 常见实体类型关键词（启发式识别）
_ENTITY_PATTERNS = {
    "person":    ["我", "你", "他", "她", "用户", "兄弟"],
    "concept":   ["策略", "模式", "方法", "机制", "系统", "框架", "架构", "理论", "原则", "理念"],
    "tool":      ["插件", "工具", "MCP", "API", "函数", "脚本", "模块", "引擎"],
    "domain":    ["交易", "基金", "股票", "写作", "编程", "番茄", "小说"],
    "project":   ["项目", "万忆", "中枢", "v1", "v2", "v3"],
}

def extract_entities(text: str) -> list[dict[str, str]]:
    """
    从文本中启发式提取实体（用于自动构建知识图谱）
    返回 [{name, type, confidence}]
    """
    entities = []
    seen = set()

    # 1. 从名词短语中提取（关键词匹配 + 上下文）
    for ent_type, keywords in _ENTITY_PATTERNS.items():
        for kw in keywords:
            if kw in text:
                # 找 kw 前后的上下文组合成更完整的实体名
                idx = text.find(kw)
                # 向前找 10 个字符，提取可能的实体全称
                start = max(0, idx - 15)
                end = min(len(text), idx + len(kw) + 5)
                context = text[start:end]
                # 简单清洗
                for sep in "，。；！？、,.;!? \n\t":
                    context = context.replace(sep, "")
                if len(context) >= 2 and context not in seen:
                    seen.add(context)
                    entities.append({
                        "name": context[:20],
                        "type": ent_type,
                        "confidence": 0.6
                    })

    # 2. 提取大写英文术语（如 MCP, FTS5, RRF, LLM 等）
    for m in re.finditer(r'[A-Z][A-Z0-9]{2,}', text):
        term = m.group()
        if term not in seen and len(term) >= 2:
            seen.add(term)
            entities.append({
                "name": term,
                "type": "concept",
                "confidence": 0.8
            })

    # 3. 提取「XX法」「XX模式」「XX策略」等结构化术语
    for m in re.finditer(r'[\u4e00-\u9fff]{2,8}(?:法|模式|策略|机制|系统|框架|架构|原则)', text):
        term = m.group()
        if term not in seen:
            seen.add(term)
            entities.append({
                "name": term,
                "type": "concept",
                "confidence": 0.75
            })

    return entities[:20]  # 最多取 20 个，避免图谱膨胀


def extract_relations(text: str, entities: list[dict[str, str]]) -> list[dict[str, Any]]:
    """
    从文本中提取实体间的关系（启发式）
    返回 [{source, target, relation, weight}]
    """
    if len(entities) < 2:
        return []

    relations = []
    # 关系关键词 → 关系类型
    rel_patterns = [
        (["包含", "包括", "有", "涵盖"], "contains"),
        (["属于", "归类为", "是一种"], "instance_of"),
        (["用于", "用来", "作用是"], "used_for"),
        (["基于", "根据", "借鉴"], "based_on"),
        (["导致", "引起", "触发"], "causes"),
        (["和", "与", "及", "以及"], "related_to"),
        (["是", "为"], "is"),
    ]

    # 简单滑窗：如果两个实体出现在同一句话中，且中间有关键词，则建立关系
    sentences = re.split(r'[。！？!?\n]', text)
    for sent in sentences:
        if not sent.strip():
            continue
        sent_entities = [e for e in entities if e["name"] in sent]
        if len(sent_entities) < 2:
            continue
        # 两两组合
        for i in range(len(sent_entities)):
            for j in range(i + 1, len(sent_entities)):
                src = sent_entities[i]
                tgt = sent_entities[j]
                rel_type = "related_to"
                weight = 0.5
                # 检查是否有更具体的关系词
                for keywords, rt in rel_patterns:
                    if any(kw in sent for kw in keywords):
                        rel_type = rt
                        weight = 0.7
                        break
                relations.append({
                    "source": src["name"],
                    "target": tgt["name"],
                    "relation": rel_type,
                    "weight": weight,
                    "confidence": min(1.0, (src["confidence"] + tgt["confidence"]) / 2)
                })

    return relations[:30]


# ═══════════════════════════════════════════════════════════════════
# 辅助：统一输入格式
# ═══════════════════════════════════════════════════════════════════

def _to_dict_list(items, default_layer=LAYER_FA, default_cat=None,
                  default_type="pattern", default_space=SPACE_GLOBAL):
    """将字符串列表或dict列表统一为dict列表，补全默认字段"""
    out = []
    for item in (items or []):
        if isinstance(item, str):
            d = {
                "content": item,
                "layer": default_layer,
                "mem_type": default_type,
                "space": default_space,
            }
            if default_cat:
                d["category"] = default_cat
            out.append(d)
        elif isinstance(item, dict):
            d = dict(item)
            d.setdefault("layer", default_layer)
            d.setdefault("mem_type", default_type)
            d.setdefault("space", default_space)
            if default_cat and "category" not in d:
                d["category"] = default_cat
            out.append(d)
    return out


def _build_graph_from_memory(engine: WanYiCore, memory_id: str, content: str):
    """
    从一条记忆自动提取实体和关系，写入知识图谱
    这是让图谱自动生长的关键 —— 每存一条记忆，图谱就长一点
    """
    try:
        entities = extract_entities(content)
        if not entities:
            return 0

        relations = extract_relations(content, entities)
        node_ids = {}

        # 创建节点
        for ent in entities:
            nid = engine.db.add_node(
                name=ent["name"],
                node_type=ent["type"],
                description=f"从记忆 {memory_id} 中提取",
                layer=LAYER_FA,
                space=ent.get("space", SPACE_GLOBAL),
                importance=ent["confidence"],
                metadata={"source_memory": memory_id, "auto_extracted": True}
            )
            node_ids[ent["name"]] = nid

        # 创建边
        for rel in relations:
            src_id = node_ids.get(rel["source"])
            tgt_id = node_ids.get(rel["target"])
            if src_id and tgt_id:
                engine.db.add_edge(
                    source_id=src_id,
                    target_id=tgt_id,
                    relation=rel["relation"],
                    weight=rel["weight"],
                    confidence=rel["confidence"],
                    metadata={"source_memory": memory_id, "auto_extracted": True}
                )

        # 关联记忆和节点
        for ent_name, nid in node_ids.items():
            engine.db.link_memory_to_node(memory_id, nid, weight=0.7)

        return len(entities)

    except Exception:
        return 0  # 图谱构建失败不影响核心记忆功能


# ═══════════════════════════════════════════════════════════════════
# HOOK-LOAD：会话启动时注入道级+法级记忆 + 项目上下文 + 图谱预热
# ═══════════════════════════════════════════════════════════════════

def hook_load(engine: WanYiCore = None) -> dict:
    """
    🔌 HOOK-LOAD：会话启动钩子（自动触发，无需用户说话）

    执行顺序：
    1. 注入 L3_道 层全部钉住记忆（无条件全量，永不忘却）
    2. 注入 L2_法 层高置信度模式（四因子排序 Top-30）
    3. 加载未完成任务（断点续传，从 SQL checkpoints 读）
    4. 图谱预热：取全局最重要的 10 个节点加载到上下文
    5. 记录会话开始事件（append-only 事件溯源）

    设计哲学：
    - 记忆不限制模型，而是"滋养"模型 —— 像人一样，打开聊天框时脑子里
      已经有了一些背景知识，但模型完全可以跳出这些知识去思考
    - 道级记忆是"三观"，必须全量注入
    - 法级记忆是"工具箱"，按相关性动态加载
    - 术级记忆是"资料库"，需要时才召回
    """
    if engine is None:
        engine = WanYiCore()

    start_time = time.time()

    # ── 1. 道级（无条件全量注入，钉住的优先） ──────────────
    dao_memories = engine.db.recall(
        query="", layer=LAYER_DAO, limit=100,
        min_confidence=0.5
    )
    # 道级按重要性排序（钉住的排最前）
    dao_memories.sort(key=lambda m: (
        m.get("pinned", False),
        m.get("importance", 0),
    ), reverse=True)

    # ── 2. 法级（高置信度关键模式，四因子已排序） ──────────
    fa_memories = engine.db.recall(
        query="", layer=LAYER_FA, limit=30,
        min_confidence=0.6
    )

    # ── 3. 加载未完成任务（断点续传） ──────────────────────
    resume_tasks = _find_resume_tasks(engine)

    # ── 4. 图谱预热：全局最重要的节点 ──────────────────────
    graph_hotspots = []
    try:
        rows = engine.db.conn.execute("""
            SELECT node_id, name, node_type, importance
            FROM graph_nodes
            ORDER BY importance DESC
            LIMIT 10
        """).fetchall()
        graph_hotspots = [dict(r) for r in rows]
    except Exception:
        pass

    # ── 4.5 v4：进化锚点注入（每个聊天框都能看到真实进化） ──
    evolution_anchor = {}
    try:
        # 最近进化事件（跨会话可见的进化证据）
        recent_evo = engine.db.evolution_log(limit=10)
        # 高频错误模式（错题本，防重复犯错）
        top_patterns = engine.process.get_error_patterns()[:5]
        # 高置信经验（经验库）
        top_exps = engine.process.list_experiences(limit=5)
        # v4.1：gotcha 桥接（PROJECTMEM 式项目级记忆隐形串联）
        matching_gotchas = []
        try:
            from project_memory import find_matching_gotchas
            matching_gotchas = find_matching_gotchas(engine, "万忆中枢 记忆 mcp 插件 sqlite obsidian 交易 写作")
        except Exception:
            pass
        evolution_anchor = {
            "version_stamp": now_iso(),
            "recent_evolution_count": len(recent_evo),
            "recent_evolution": [
                {"scope": e.get("scope"), "type": e.get("event_type"),
                 "data": e.get("event_data", {})} for e in recent_evo
            ],
            "top_error_patterns": top_patterns,
            "top_experiences": [
                {"task": e.get("task_name"), "content": e.get("content"),
                 "confidence": e.get("confidence")} for e in top_exps
            ],
            "matching_gotchas": matching_gotchas,
        }
    except Exception:
        evolution_anchor = {"version_stamp": now_iso(), "error": "进化锚点加载失败"}

    # ── 5. 记录会话开始事件（append-only 事件溯源） ────────
    engine.db.log_event(SESSION_ID, "hook_load_executed", {
        "dao_injected": len(dao_memories),
        "fa_injected": len(fa_memories),
        "resume_tasks": len(resume_tasks),
        "graph_hotspots": len(graph_hotspots),
        "evolution_anchor_version": evolution_anchor.get("version_stamp"),
        "load_duration_ms": round((time.time() - start_time) * 1000),
        "timestamp": now_iso()
    })

    # 同时记录 session_start 事件（独立类型，方便统计）
    engine.db.log_event(SESSION_ID, "session_start", {
        "timestamp": now_iso(),
        "dao_count": len(dao_memories),
        "fa_count": len(fa_memories),
        "evolution_injected": len(evolution_anchor.get("recent_evolution", [])),
    })

    return {
        "hook": "HOOK-LOAD",
        "session_id": SESSION_ID,
        "injected_at": now_iso(),
        "load_duration_ms": round((time.time() - start_time) * 1000),
        "dao_memories": dao_memories,
        "fa_memories": fa_memories,
        "resume_tasks": resume_tasks,
        "graph_hotspots": graph_hotspots,
        "evolution_anchor": evolution_anchor,
        "summary": {
            "total_principles": len(dao_memories),
            "pinned_principles": sum(1 for m in dao_memories if m.get("pinned")),
            "total_patterns": len(fa_memories),
            "ready_for_trading": any(
                "交易" in str(m.get("category", ""))
                for m in dao_memories
            ),
            "has_resume": len(resume_tasks) > 0,
            "graph_size": len(graph_hotspots),
            "evolution_visible": len(evolution_anchor.get("recent_evolution", [])) > 0,
            "philosophy": "全量记忆不限制模型，而是滋养模型——道级全量注入，法级动态加载，术级按需召回"
        }
    }


def _find_resume_tasks(engine: WanYiCore) -> list:
    """
    扫描任务检查点，找出未完成的任务（断点续传）
    从 SQL task_checkpoints 表读取，不再依赖 JSONL 文件
    """
    try:
        rows = engine.db.conn.execute("""
            SELECT task_name, phase, progress_pct, state, created_at, checkpoint_id
            FROM task_checkpoints
            WHERE progress_pct < 100
            ORDER BY created_at DESC
            LIMIT 20
        """).fetchall()
        tasks = []
        seen = set()
        for r in rows:
            if r["task_name"] in seen:
                continue
            seen.add(r["task_name"])
            state = {}
            try:
                state = json.loads(r["state"]) if r["state"] else {}
            except (json.JSONDecodeError, TypeError):
                pass
            tasks.append({
                "task_name": r["task_name"],
                "phase": r["phase"],
                "progress_pct": r["progress_pct"],
                "last_checkpoint": r["checkpoint_id"],
                "last_updated": r["created_at"],
                "state": state
            })
        return tasks
    except Exception:
        return []


# ═══════════════════════════════════════════════════════════════════
# HOOK-MONITOR：任务关键节点自动存档
# ═══════════════════════════════════════════════════════════════════

def hook_monitor(
    task_name: str,
    phase: str,
    progress_pct: float,
    state: dict,
    event_tags: list = None,
    notes: str = "",
    engine: WanYiCore = None
) -> dict:
    """
    👁️ HOOK-MONITOR：任务监控钩子

    自动做的事：
    1. 保存进度快照（SQL checkpoints，支持冷续传）
    2. 记录 append-only 事件日志（SQL session_events，事件溯源）
    3. 自动从 state/notes 中提取实体，更新知识图谱
    4. 标记关键节点事件类型（decision/pattern/postmortem 等）

    设计：每次 MONITOR 都是一个事件点，永远不会被覆盖
    """
    if engine is None:
        engine = WanYiCore()

    # 1. 进度快照
    result = engine.tool_save_progress(task_name, phase, progress_pct, state)
    checkpoint_id = result["checkpoint_id"]

    # 2. 事件日志（append-only，事件溯源）
    event_tags = event_tags or []
    event_type = f"monitor/{phase}"
    event_data = {
        "task_name": task_name,
        "phase": phase,
        "progress": progress_pct,
        "checkpoint_id": checkpoint_id,
        "event_tags": event_tags,
        "notes": notes,
    }
    engine.db.log_event(SESSION_ID, event_type, event_data)

    # 同时写一条 step/done 事件，兼容自主长跑者的事件命名规范
    engine.db.log_event(SESSION_ID, "step/done", {
        "task_id": f"task_{task_name}",
        "task_name": task_name,
        "phase": phase,
        "progress": progress_pct,
        "state": state,
        "event_tags": event_tags
    })

    # 3. 从 notes + state 文本中提取实体，自动构建图谱
    graph_entities_added = 0
    if notes:
        # 将 notes 作为一条术级观察记忆存下来
        mem_result = engine.db.upsert_memory(
            content=notes,
            layer=LAYER_SHU,
            mem_type="observation",
            category=f"任务监控/{task_name}",
            space=SPACE_PROJECT,
            project=task_name,
            privacy=PRIVACY_INTERNAL,
            source="hook_monitor",
            tags=["monitor"] + event_tags,
            confidence=0.7,
            session_id=SESSION_ID,
            task_id=f"task_{task_name}"
        )
        # 自动构建图谱
        graph_entities_added = _build_graph_from_memory(engine, mem_result["memory_id"], notes)

    result["event_type"] = event_type
    result["graph_entities_added"] = graph_entities_added
    return result


# ═══════════════════════════════════════════════════════════════════
# HOOK-REFLECT：五齿轮自动反思
# ═══════════════════════════════════════════════════════════════════

def hook_reflect(
    raw_notes: str = "",
    decisions: list = None,
    patterns: list = None,
    skills: list = None,
    postmortems: list = None,
    memories: list = None,
    task_name: str = "",
    auto_extract: bool = True,
    engine: WanYiCore = None
) -> dict:
    """
    💭 HOOK-REFLECT：反思钩子 — 五齿轮标准问题

    每次任务完成自动跑一遍，无需用户说话。

    ⚙️ 齿轮1 [DECISION]   → 决策日记（道级，钉住，永不衰减）
    ⚙️ 齿轮2 [PATTERN]    → 模式抽象（法级，60天半衰）
    ⚙️ 齿轮3 [SKILL]      → 技能建议（法级，90天半衰）
    ⚙️ 齿轮4 [POSTMORTEM] → 撞墙复盘（法级，钉住，教训不能忘）
    ⚙️ 齿轮5 [MEMORY]     → 知识沉淀（术级→法级升降级机制）

    额外：
    - 自动从 raw_notes 中启发式提取反思条目
    - 自动构建知识图谱（每个齿轮的产出都关联到图谱）
    - 记录反思事件日志
    """
    if engine is None:
        engine = WanYiCore()

    results = {"五齿轮": {}, "图谱": {}, "summary": {}}
    now_str = now_iso()
    total_new_memories = 0
    total_entities_added = 0
    all_memory_ids = []

    # ── 齿轮1：决策日记（道级，钉住） ──────────────────────
    if decisions:
        gear_results = []
        for d in _to_dict_list(decisions, default_layer=LAYER_DAO,
                               default_cat="决策日记", default_type="decision"):
            choice = d.get("choice") or d.get("content", "")
            rejected = d.get("rejected", "其他方案")
            reason = d.get("reason", "")
            content = f"[DECISION] 选择了「{choice}」而非「{rejected}」，因为：{reason}"
            r = engine.db.upsert_memory(
                content=content,
                layer=LAYER_DAO,
                mem_type="decision",
                category=d.get("category", "决策日记"),
                space=d.get("space", SPACE_GLOBAL),
                project=task_name or None,
                privacy=d.get("privacy", PRIVACY_INTERNAL),
                source="hook_reflect/齿轮1-决策",
                tags=["decision", "reflection"] + (d.get("tags") or []),
                confidence=d.get("confidence", 0.85),
                pinned=True,  # 决策必须钉住，永不衰减
                session_id=SESSION_ID,
                task_id=f"task_{task_name}" if task_name else None,
                importance=d.get("importance", 0.9)
            )
            gear_results.append(r)
            all_memory_ids.append(r["memory_id"])
            # 自动构建图谱
            total_entities_added += _build_graph_from_memory(engine, r["memory_id"], content)
        results["五齿轮"]["决策日记"] = gear_results
        total_new_memories += len(gear_results)

    # ── 齿轮2：模式抽象（法级，60天半衰） ─────────────────
    if patterns:
        gear_results = []
        for p in _to_dict_list(patterns, default_layer=LAYER_FA,
                               default_cat="模式抽象", default_type="pattern"):
            content = p.get("description", p.get("content", ""))
            r = engine.db.upsert_memory(
                content=content,
                layer=LAYER_FA,
                mem_type="pattern",
                category=p.get("category", "模式抽象"),
                space=p.get("space", SPACE_GLOBAL),
                project=task_name or None,
                privacy=p.get("privacy", PRIVACY_INTERNAL),
                source="hook_reflect/齿轮2-模式",
                tags=["pattern", "reflection"] + (p.get("tags") or []),
                confidence=p.get("confidence", 0.8),
                pinned=p.get("pinned", False),
                session_id=SESSION_ID,
                task_id=f"task_{task_name}" if task_name else None,
            )
            gear_results.append(r)
            all_memory_ids.append(r["memory_id"])
            total_entities_added += _build_graph_from_memory(engine, r["memory_id"], content)
        results["五齿轮"]["模式抽象"] = gear_results
        total_new_memories += len(gear_results)

    # ── 齿轮3：技能建议（法级，90天半衰） ─────────────────
    if skills:
        gear_results = []
        for s in _to_dict_list(skills, default_layer=LAYER_FA,
                               default_cat="技能建议", default_type="strategy"):
            pain = s.get("pain", "")
            solution = s.get("solution", "")
            content = f"[SKILL-PROP] 痛点：{pain} → 建议方案：{solution}"
            r = engine.db.upsert_memory(
                content=content,
                layer=LAYER_FA,
                mem_type="strategy",
                category=s.get("category", "技能建议"),
                space=s.get("space", SPACE_GLOBAL),
                project=task_name or None,
                privacy=s.get("privacy", PRIVACY_INTERNAL),
                source="hook_reflect/齿轮3-技能",
                tags=["skill-proposal", "reflection"] + (s.get("tags") or []),
                confidence=s.get("confidence", 0.65),
                session_id=SESSION_ID,
                task_id=f"task_{task_name}" if task_name else None,
            )
            gear_results.append(r)
            all_memory_ids.append(r["memory_id"])
            total_entities_added += _build_graph_from_memory(engine, r["memory_id"], content)
        results["五齿轮"]["技能建议"] = gear_results
        total_new_memories += len(gear_results)

    # ── 齿轮4：撞墙复盘（法级，钉住 —— 教训不能忘） ───────
    if postmortems:
        gear_results = []
        for pm in _to_dict_list(postmortems, default_layer=LAYER_FA,
                                default_cat="复盘", default_type="pattern"):
            root_cause = pm.get("root_cause", "")
            prevention = pm.get("prevention", "")
            content = f"[POSTMORTEM] 根因：{root_cause} → 防护措施：{prevention}"
            r = engine.db.upsert_memory(
                content=content,
                layer=LAYER_FA,
                mem_type="pattern",
                category=pm.get("category", "复盘"),
                space=pm.get("space", SPACE_GLOBAL),
                project=task_name or None,
                privacy=pm.get("privacy", PRIVACY_INTERNAL),
                source="hook_reflect/齿轮4-复盘",
                tags=["postmortem", "reflection", "lesson"] + (pm.get("tags") or []),
                confidence=pm.get("confidence", 0.9),
                pinned=True,  # 复盘教训必须钉住
                session_id=SESSION_ID,
                task_id=f"task_{task_name}" if task_name else None,
                importance=pm.get("importance", 0.85)
            )
            gear_results.append(r)
            all_memory_ids.append(r["memory_id"])
            total_entities_added += _build_graph_from_memory(engine, r["memory_id"], content)
        results["五齿轮"]["撞墙复盘"] = gear_results
        total_new_memories += len(gear_results)

    # ── 齿轮5：知识沉淀（术级观察 → 法级模式 升降级） ────
    if memories:
        gear_results = []
        for m in _to_dict_list(memories, default_layer=LAYER_FA,
                               default_cat="知识沉淀", default_type="concept"):
            content = m.get("content", m.get("insight", ""))
            # 如果标注为 high importance 则升到法级，默认术级
            layer = m.get("layer", LAYER_SHU if m.get("is_raw") else LAYER_FA)
            r = engine.db.upsert_memory(
                content=content,
                layer=layer,
                mem_type=m.get("mem_type", "concept" if layer == LAYER_FA else "observation"),
                category=m.get("category", "知识沉淀"),
                space=m.get("space", SPACE_GLOBAL),
                project=task_name or None,
                privacy=m.get("privacy", PRIVACY_INTERNAL),
                source="hook_reflect/齿轮5-知识",
                tags=["knowledge", "reflection"] + (m.get("tags") or []),
                confidence=m.get("confidence", 0.75),
                pinned=m.get("pinned", False),
                session_id=SESSION_ID,
                task_id=f"task_{task_name}" if task_name else None,
            )
            gear_results.append(r)
            all_memory_ids.append(r["memory_id"])
            total_entities_added += _build_graph_from_memory(engine, r["memory_id"], content)
        results["五齿轮"]["知识沉淀"] = gear_results
        total_new_memories += len(gear_results)

    # ── 自动提取：从 raw_notes 启发式提取反思条目 ─────────
    auto_count = 0
    if auto_extract and raw_notes:
        auto_items = _extract_from_notes(raw_notes)
        auto_results = []
        for item in auto_items:
            r = engine.db.upsert_memory(
                content=item["content"],
                layer=item.get("layer", LAYER_FA),
                mem_type=item.get("mem_type", "pattern"),
                category=item.get("category", "反思提炼"),
                space=SPACE_GLOBAL,
                project=task_name or None,
                privacy=PRIVACY_INTERNAL,
                source="hook_reflect/自动提炼",
                tags=item.get("tags", ["auto-reflection"]),
                confidence=0.65,  # 自动提炼的置信度稍低
                session_id=SESSION_ID,
                task_id=f"task_{task_name}" if task_name else None,
            )
            auto_results.append(r)
            all_memory_ids.append(r["memory_id"])
            total_entities_added += _build_graph_from_memory(engine, r["memory_id"], item["content"])
        if auto_results:
            results["五齿轮"]["自动提炼"] = auto_results
            auto_count = len(auto_results)
            total_new_memories += auto_count

    # ── 记录反思事件 ──────────────────────────────────────
    gears_triggered = list(results["五齿轮"].keys())
    engine.db.log_event(SESSION_ID, "hook_reflect_executed", {
        "timestamp": now_str,
        "task_name": task_name,
        "gears_triggered": gears_triggered,
        "total_new_memories": total_new_memories,
        "auto_extracted": auto_count,
        "graph_entities_added": total_entities_added,
    })

    # ═══ v4：复盘自动沉淀错题本（Reflexion 式） ═══
    mistake_stats = {"recorded": 0, "patterns": 0}
    try:
        if postmortems:
            for pm in _to_dict_list(postmortems, default_layer=LAYER_FA,
                                    default_cat="复盘", default_type="pattern"):
                content = pm.get("content") or pm.get("lesson", "")
                if content:
                    # 失败/教训内容 → 错题本（自动模式提取 + 去重）
                    m = engine.process.add_phase(
                        process_id=f"PM_{task_name or 'task'}_{int(time.time())}",
                        task_name=task_name or "复盘",
                        phase="反思",
                        content=content,
                        outcome="failure"
                    )
                    if m.get("auto_mistake"):
                        mistake_stats["recorded"] += 1
        mistake_stats["patterns"] = len(engine.process.get_error_patterns())
    except Exception:
        pass
    results["错题本"] = mistake_stats

    results["图谱"] = {
        "entities_added": total_entities_added,
        "memory_node_links": len(all_memory_ids),
    }

    results["summary"] = {
        "gears_run": gears_triggered,
        "gears_count": len(gears_triggered),
        "total_new_memories": total_new_memories,
        "auto_extracted_count": auto_count,
        "graph_entities_added": total_entities_added,
        "mistakes_recorded": mistake_stats.get("recorded", 0),
        "completed_at": now_str,
        "philosophy": "五齿轮自动转，不需要人推——任务一结束，反思自动开始"
    }

    return results


def _extract_from_notes(notes: str) -> list:
    """
    从原始笔记中启发式提取反思条目（不依赖LLM）
    识别关键词 → 归类到对应齿轮
    """
    items = []
    lines = notes.split("\n")
    for line in lines:
        line = line.strip()
        if not line or len(line) < 8:
            continue

        # 决策关键词 → 齿轮1（道级）
        if any(kw in line for kw in ["选了", "决定", "改为", "放弃", "选择了", "最终用", "不用"]):
            items.append({
                "content": line,
                "layer": LAYER_DAO,
                "mem_type": "decision",
                "category": "决策日记",
                "tags": ["decision", "auto"]
            })
        # 模式/方法关键词 → 齿轮2（法级）
        elif any(kw in line for kw in ["发现", "规律", "模式", "套路", "方法", "技巧", "原来"]):
            items.append({
                "content": line,
                "layer": LAYER_FA,
                "mem_type": "pattern",
                "category": "模式抽象",
                "tags": ["pattern", "auto"]
            })
        # 踩坑/教训 → 齿轮4（法级，复盘）
        elif any(kw in line for kw in ["踩坑", "翻车", "出错", "卡住了", "教训", "bug", "问题是"]):
            items.append({
                "content": line,
                "layer": LAYER_FA,
                "mem_type": "pattern",
                "category": "复盘",
                "tags": ["postmortem", "auto"]
            })
        # 新知识 → 齿轮5（术级）
        elif any(kw in line for kw in ["学到", "才知道", "新发现", "了解到", "知道了"]):
            items.append({
                "content": line,
                "layer": LAYER_SHU,
                "mem_type": "observation",
                "category": "知识沉淀",
                "tags": ["knowledge", "auto"]
            })
    return items


# ═══════════════════════════════════════════════════════════════════
# HOOK-STORE：会话彻底结束时汇总存档
# ═══════════════════════════════════════════════════════════════════

def hook_store(
    session_summary: dict = None,
    run_sleep_consolidation: bool = False,
    engine: WanYiCore = None
) -> dict:
    """
    💾 HOOK-STORE：存储钩子（会话结束时自动触发）

    做的事：
    1. 统计本次会话新增记忆（按层/按类型）
    2. 记录会话结束事件
    3. 生成会话摘要（人可读，存到 reflections 目录）
    4. 可选：运行睡眠巩固（衰减+增强+合并）
    5. 同步到 Obsidian（由核心引擎的 _sync_to_obsidian 处理）

    设计：会话结束 ≠ 记忆结束。记忆永远在库里，只是退出活跃窗口。
    """
    if engine is None:
        engine = WanYiCore()

    now_str = now_iso()

    # 1. 统计本次会话新增记忆
    stats_by_layer = {}
    stats_by_type = {}
    new_today_count = 0

    try:
        rows = engine.db.conn.execute("""
            SELECT layer, mem_type, COUNT(*) as cnt
            FROM memories
            WHERE session_id = ?
            GROUP BY layer, mem_type
            ORDER BY cnt DESC
        """, (SESSION_ID,)).fetchall()

        for r in rows:
            layer = r["layer"]
            mem_type = r["mem_type"]
            cnt = r["cnt"]
            new_today_count += cnt
            stats_by_layer[layer] = stats_by_layer.get(layer, 0) + cnt
            stats_by_type[mem_type] = stats_by_type.get(mem_type, 0) + cnt
    except Exception:
        pass

    # 2. 记录 STORE 事件
    engine.db.log_event(SESSION_ID, "hook_store_executed", {
        "summary": session_summary,
        "new_memories_session": new_today_count,
        "by_layer": stats_by_layer,
        "by_type": stats_by_type,
        "timestamp": now_str
    })

    # 同时记录 session_end 事件
    engine.db.log_event(SESSION_ID, "session_end", {
        "timestamp": now_str,
        "new_memories": new_today_count,
        "summary": session_summary
    })

    # 3. 生成人可读的会话摘要（存 reflections 目录）
    summary_file = _write_session_summary(
        engine, new_today_count, stats_by_layer,
        stats_by_type, session_summary
    )

    # 4. 可选：睡眠巩固
    sleep_stats = None
    if run_sleep_consolidation:
        try:
            sleep_stats = engine.tool_sleep_consolidation()
        except Exception:
            pass

    # ═══ v4：会话结束时写每日思考档案（AgentMemory 式思考档案） ═══
    daily_log_stats = None
    try:
        if hasattr(engine, "gardener"):
            daily_log_stats = engine.gardener.write_daily_log()
    except Exception:
        pass

    return {
        "hook": "HOOK-STORE",
        "session_id": SESSION_ID,
        "store_completed_at": now_str,
        "new_memories_this_session": new_today_count,
        "by_layer": stats_by_layer,
        "by_type": stats_by_type,
        "summary_file": summary_file,
        "sleep_consolidation": sleep_stats,
        "daily_log": daily_log_stats,
        "philosophy": "会话会结束，但记忆永不消失——它只是沉入记忆之海，需要时浮上来"
    }


def _write_session_summary(engine: WanYiCore, total: int,
                           by_layer: dict, by_type: dict,
                           custom_summary: dict = None) -> str:
    """写一份人可读的会话摘要到 reflections 目录"""
    date_str = datetime.now().strftime("%Y%m%d")
    filename = f"{date_str}_{SESSION_ID[:8]}_会话摘要.md"
    filepath = REFLECTION_DIR / filename

    # 取几条代表性记忆
    sample_memories = []
    try:
        rows = engine.db.conn.execute("""
            SELECT content, layer, category, mem_type
            FROM memories
            WHERE session_id = ?
            ORDER BY importance DESC
            LIMIT 10
        """, (SESSION_ID,)).fetchall()
        sample_memories = [dict(r) for r in rows]
    except Exception:
        pass

    md_lines = [
        "# 万忆中枢 · 会话摘要",
        "",
        f"- **会话ID**: {SESSION_ID}",
        f"- **时间**: {now_iso()}",
        f"- **新增记忆**: {total} 条",
        "",
        "## 按层级分布",
        "",
    ]
    for layer, cnt in by_layer.items():
        md_lines.append(f"- {layer}: {cnt} 条")

    md_lines += ["", "## 按类型分布", ""]
    for mtype, cnt in sorted(by_type.items(), key=lambda x: x[1], reverse=True):
        type_info = MEMORY_TYPES.get(mtype, {})
        tname = type_info.get("name", mtype)
        md_lines.append(f"- {tname}({mtype}): {cnt} 条")

    if sample_memories:
        md_lines += ["", "## 代表性记忆", ""]
        for i, m in enumerate(sample_memories, 1):
            content = m["content"][:100] + "..." if len(m["content"]) > 100 else m["content"]
            md_lines.append(f"{i}. [{m['layer']}] {m.get('category', '未分类')} — {content}")

    if custom_summary:
        md_lines += ["", "## 自定义摘要", ""]
        for k, v in custom_summary.items():
            md_lines.append(f"- **{k}**: {v}")

    md_lines += [
        "",
        "---",
        "*由万忆中枢 v3 自动生成 · 五齿轮四钩子引擎*",
    ]

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(md_lines))
        return str(filepath)
    except Exception:
        return ""


# ═══════════════════════════════════════════════════════════════════
# 批量 Hook 执行（自动化流水线）
# ═══════════════════════════════════════════════════════════════════

def run_all_hooks(mode: str = "full", engine: WanYiCore = None, **kwargs) -> dict:
    """
    按模式执行全套 Hooks

    mode:
      - "load"    → 仅 LOAD（会话启动）
      - "store"   → 仅 STORE（会话结束）
      - "full"    → LOAD + STORE（完整生命周期，用于测试）
      - "reflect" → 仅 REFLECT（任务完成后反思）
      - "monitor" → 仅 MONITOR（任务进度上报）
      - "reflect_store" → REFLECT + STORE（任务结束+会话结束连续触发）
    """
    if engine is None:
        engine = WanYiCore()

    results = {}

    if mode in ("load", "full"):
        results["LOAD"] = hook_load(engine)

    if mode == "monitor":
        results["MONITOR"] = hook_monitor(
            task_name=kwargs.get("task_name", ""),
            phase=kwargs.get("phase", ""),
            progress_pct=kwargs.get("progress_pct", 0),
            state=kwargs.get("state", {}),
            event_tags=kwargs.get("event_tags"),
            notes=kwargs.get("notes", ""),
            engine=engine
        )

    if mode in ("reflect", "reflect_store"):
        results["REFLECT"] = hook_reflect(
            raw_notes=kwargs.get("raw_notes", ""),
            decisions=kwargs.get("decisions"),
            patterns=kwargs.get("patterns"),
            skills=kwargs.get("skills"),
            postmortems=kwargs.get("postmortems"),
            memories=kwargs.get("memories"),
            task_name=kwargs.get("task_name", ""),
            auto_extract=kwargs.get("auto_extract", True),
            engine=engine
        )

    if mode in ("store", "full", "reflect_store"):
        results["STORE"] = hook_store(
            session_summary=kwargs.get("session_summary"),
            run_sleep_consolidation=kwargs.get("run_sleep_consolidation", False),
            engine=engine
        )

    return results


# ═══════════════════════════════════════════════════════════════════
# 命令行入口（调试用）
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="万忆中枢 v3 — 五齿轮四钩子引擎")
    parser.add_argument("--mode",
                        choices=["load", "store", "full", "reflect", "monitor", "reflect_store"],
                        default="full",
                        help="执行模式")
    parser.add_argument("--task", help="任务名称（monitor/reflect 用）")
    parser.add_argument("--phase", help="任务阶段（monitor 用）")
    parser.add_argument("--progress", type=float, help="进度百分比（monitor 用）")
    parser.add_argument("--notes", help="原始笔记文本（reflect 用，自动提取五齿轮）")
    parser.add_argument("--with-sleep", action="store_true",
                        help="STORE 时运行睡眠巩固")
    parser.add_argument("--output", help="输出文件路径")
    args = parser.parse_args()

    init_dirs()
    engine = WanYiCore()

    if args.mode == "monitor" and all([args.task, args.phase, args.progress is not None]):
        result = hook_monitor(
            args.task, args.phase, args.progress, {},
            notes=args.notes or "", engine=engine
        )
    elif args.mode in ("reflect", "reflect_store"):
        result = run_all_hooks(
            args.mode, engine,
            raw_notes=args.notes or "",
            task_name=args.task or "",
            run_sleep_consolidation=args.with_sleep
        )
    else:
        result = run_all_hooks(
            args.mode, engine,
            run_sleep_consolidation=args.with_sleep
        )

    output_str = json.dumps(result, ensure_ascii=False, indent=2)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_str)
        print(f"[万忆中枢] 结果已写入: {args.output}")
    else:
        print(output_str)

    engine.db.conn.close()
