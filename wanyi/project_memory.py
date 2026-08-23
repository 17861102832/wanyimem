#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║        万 忆 中 枢  v3 — 项目级记忆适配器                        ║
║                                                               ║
║  将「项目上下文.md」中的每个项目自动同步到万忆中枢数据库，          ║
║  实现"换一个对话也不会忘记项目状态"的跨会话记忆能力。              ║
║                                                               ║
║  v3 升级：                                                      ║
║    - 同步到三级记忆空间（项目级/个人级/全局级）                  ║
║    - 四级隐私分级（项目机密信息存机密级）                        ║
║    - 自动构建项目知识图谱（项目→技术栈→核心文件）                ║
║    - 记忆类型适配（project 类型 = 法级，60天半衰）               ║
║    - 进行中项目 = 钉住（永不衰减，保证一直在最前面）              ║
╚══════════════════════════════════════════════════════════════════╝
"""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from env_compat import get_env  # v1.1：中文优先/英文兜底
from memory_core import (
    LAYER_FA,
    LAYER_SHU,
    PRIVACY_INTERNAL,
    SESSION_ID,
    SPACE_GLOBAL,
    SPACE_PROJECT,
    WanYiCore,
    init_dirs,
    now_iso,
)

PROJECT_CONTEXT_PATH = get_env(
    "万忆中枢_PROJECT_CONTEXT",
    "WANYI_PROJECT_CONTEXT",
    str(Path.home() / ".wanyi" / "project_context.md")  # v5.0开源脱敏：默认通用路径
)


def parse_project_context(md_path: str) -> list:
    """
    解析项目上下文.md，返回项目列表
    支持格式：## 项目名 + 字段（项目路径/技术栈/核心文件/最新进展/下一步）
    """
    path = Path(md_path)
    if not path.exists():
        return []

    content = path.read_text(encoding="utf-8")
    projects = []

    # 匹配每个项目卡片（以 ## 开头）
    pattern = r'^## (.*?)\s*\n(.*?)(?=^## |\Z)'
    matches = re.findall(pattern, content, re.DOTALL | re.MULTILINE)

    for name, body in matches:
        name = name.strip()
        # 跳过非项目章节（如 "## 说明"）
        if not name or name in ["说明", "目录", "索引", "README"]:
            continue
        project = {
            "name": name,
            "body": body.strip(),
            "raw": content,
        }
        # 提取关键字段
        field_map = {
            "项目路径": "path",
            "技术栈": "tech_stack",
            "核心文件": "core_files",
            "最新进展": "progress",
            "下一步": "next_step",
            "状态": "status",
            "优先级": "priority",
        }
        for cn_field, en_field in field_map.items():
            match = re.search(rf'\*\*{cn_field}\*\*[:：]\s*(.+)', body)
            if match:
                project[en_field] = match.group(1).strip()

        projects.append(project)

    return projects


def sync_project_memory(engine: WanYiCore = None, md_path: str = None) -> dict:
    """
    将项目上下文同步到万忆中枢数据库 v3

    每个项目存三层：
    - 术级（SPACE_PROJECT）：原始项目信息，完整记录
    - 法级（SPACE_PROJECT）：项目模式/状态，高优先级
    - 图谱：自动提取技术栈、核心文件等作为节点

    进行中的项目：钉住（永不衰减）
    """
    if engine is None:
        engine = WanYiCore()

    path = md_path or PROJECT_CONTEXT_PATH
    projects = parse_project_context(path)

    synced = []
    graph_stats = {"nodes": 0, "edges": 0}

    for proj in projects:
        name = proj["name"]
        is_active = _is_project_active(proj)

        # ── 1. 术级：完整项目信息（项目空间） ─────────────
        full_content = _build_project_full_text(proj)
        r_shu = engine.db.upsert_memory(
            content=full_content,
            layer=LAYER_SHU,
            mem_type="fact",
            category="项目档案",
            space=SPACE_PROJECT,
            project=name,
            privacy=PRIVACY_INTERNAL,
            source=f"项目上下文/{name}",
            tags=["project", name] + _extract_tech_tags(proj),
            confidence=0.95,
            pinned=False,
            session_id=SESSION_ID,
            metadata={"project_name": name, **{k: v for k, v in proj.items() if k != "raw"}}
        )

        # ── 2. 法级：项目状态/模式（项目空间） ───────────
        status_content = _build_project_status_text(proj)
        r_fa = engine.db.upsert_memory(
            content=status_content,
            layer=LAYER_FA,
            mem_type="pattern",
            category="项目跟踪",
            space=SPACE_PROJECT,
            project=name,
            privacy=PRIVACY_INTERNAL,
            source=f"项目上下文/{name}_status",
            tags=["project-status", name, ("active" if is_active else "archived")],
            confidence=0.9,
            pinned=is_active,  # 进行中的项目钉住
            importance=0.8 if is_active else 0.5,
            session_id=SESSION_ID,
        )

        # ── 3. 图谱：自动构建项目节点 + 技术栈/文件节点 ──
        graph_added = _build_project_graph(engine, proj)
        graph_stats["nodes"] += graph_added.get("nodes", 0)
        graph_stats["edges"] += graph_added.get("edges", 0)

        synced.append({
            "project": name,
            "active": is_active,
            "shu_memory": r_shu["memory_id"],
            "fa_memory": r_fa["memory_id"],
            "pinned": is_active,
        })

    # 记录同步事件
    engine.db.log_event(SESSION_ID, "project_memory_synced", {
        "synced_count": len(synced),
        "active_count": sum(1 for s in synced if s["active"]),
        "graph_nodes": graph_stats["nodes"],
        "graph_edges": graph_stats["edges"],
        "source_file": str(path),
        "timestamp": now_iso()
    })

    return {
        "synced_projects": len(synced),
        "active_projects": sum(1 for s in synced if s["active"]),
        "projects": synced,
        "graph_stats": graph_stats,
        "timestamp": now_iso()
    }


def _is_project_active(proj: dict) -> bool:
    """判断项目是否处于活跃状态"""
    status = str(proj.get("status", ""))
    progress = str(proj.get("progress", ""))
    next_step = str(proj.get("next_step", ""))
    active_keywords = ["进行中", "开发中", "推进中", "活跃", "TODO", "待办", "暂停中",
                       "重构", "迭代", "v2", "v3", "升级中"]
    text = f"{status} {progress} {next_step}"
    return any(kw in text for kw in active_keywords)


def _build_project_full_text(proj: dict) -> str:
    """构建完整的项目信息文本（术级）"""
    lines = [f"【项目档案】{proj['name']}", ""]
    field_labels = [
        ("path", "项目路径"),
        ("tech_stack", "技术栈"),
        ("core_files", "核心文件"),
        ("progress", "最新进展"),
        ("next_step", "下一步"),
        ("status", "状态"),
        ("priority", "优先级"),
    ]
    for key, label in field_labels:
        if key in proj:
            lines.append(f"- **{label}**：{proj[key]}")
    lines.append("")
    lines.append("---")
    lines.append(proj.get("body", "")[:500])  # 正文前500字
    return "\n".join(lines)


def _build_project_status_text(proj: dict) -> str:
    """构建项目状态文本（法级，更精炼）"""
    name = proj["name"]
    status = proj.get("status", "未知")
    progress = proj.get("progress", "暂无")
    next_step = proj.get("next_step", "暂无")
    return (
        f"[PROJECT-STATUS] {name}\n"
        f"状态：{status}\n"
        f"进展：{progress}\n"
        f"下一步：{next_step}"
    )


def _extract_tech_tags(proj: dict) -> list:
    """从技术栈中提取标签"""
    tech = str(proj.get("tech_stack", ""))
    # 按常见分隔符拆分
    tags = []
    for sep in [",", "、", "/", "，", " "]:
        if sep in tech:
            tags = [t.strip() for t in tech.split(sep) if t.strip()]
            break
    if not tags and tech:
        tags = [tech]
    return [t.lower() for t in tags[:10]]


def _build_project_graph(engine: WanYiCore, proj: dict) -> dict:
    """
    为单个项目构建知识图谱
    节点：项目名、技术栈元素、核心文件
    边：项目 uses 技术栈, 项目 contains 核心文件
    """
    name = proj["name"]
    nodes_added = 0
    edges_added = 0

    # 项目节点
    project_node_id = engine.db.add_node(
        name=name,
        node_type="project",
        description=proj.get("progress", ""),
        layer=LAYER_FA,
        space=SPACE_PROJECT,
        importance=0.8 if _is_project_active(proj) else 0.5,
        metadata={"project_name": name, "auto_extracted": True}
    )
    nodes_added += 1

    # 技术栈节点
    tech_tags = _extract_tech_tags(proj)
    for tech in tech_tags[:10]:
        tech_node_id = engine.db.add_node(
            name=tech,
            node_type="tool",
            description=f"技术栈：{tech}",
            layer=LAYER_FA,
            space=SPACE_GLOBAL,
            importance=0.6,
            metadata={"source_project": name, "auto_extracted": True}
        )
        nodes_added += 1
        engine.db.add_edge(
            source_id=project_node_id,
            target_id=tech_node_id,
            relation="uses_tech",
            weight=0.8,
            confidence=0.9,
            metadata={"source_project": name}
        )
        edges_added += 1

    # 核心文件节点（如果有）
    core_files = proj.get("core_files", "")
    if core_files:
        files = [f.strip() for f in re.split(r'[,，、\n]', core_files) if f.strip()]
        for f in files[:5]:
            file_node_id = engine.db.add_node(
                name=f,
                node_type="file",
                description=f"核心文件：{f}",
                layer=LAYER_SHU,
                space=SPACE_PROJECT,
                importance=0.5,
                metadata={"project": name, "auto_extracted": True}
            )
            nodes_added += 1
            engine.db.add_edge(
                source_id=project_node_id,
                target_id=file_node_id,
                relation="contains_file",
                weight=0.7,
                confidence=0.8,
                metadata={"project": name}
            )
            edges_added += 1

    # 关联记忆和项目节点
    # 术级记忆关联
    try:
        row = engine.db.conn.execute(
            "SELECT memory_id FROM memories WHERE project = ? AND category = '项目档案'",
            (name,)
        ).fetchone()
        if row:
            engine.db.link_memory_to_node(row["memory_id"], project_node_id, weight=0.9)
    except Exception:
        pass

    return {"nodes": nodes_added, "edges": edges_added}


def get_active_projects(engine: WanYiCore = None) -> dict:
    """
    获取所有进行中项目（钉住的项目跟踪记忆）
    用于 HOOK-LOAD 时注入
    """
    if engine is None:
        engine = WanYiCore()

    # 从法层 + 项目空间 + 钉住 = 活跃项目
    try:
        rows = engine.db.conn.execute("""
            SELECT * FROM memories
            WHERE layer = ? AND category = '项目跟踪' AND pinned = 1
            ORDER BY importance DESC, updated_at DESC
            LIMIT 20
        """, (LAYER_FA,)).fetchall()
        active = [engine.db._row_to_dict(r) for r in rows]
    except Exception:
        active = []

    # 所有项目档案
    try:
        all_rows = engine.db.conn.execute("""
            SELECT * FROM memories
            WHERE category = '项目档案'
            ORDER BY updated_at DESC
            LIMIT 50
        """).fetchall()
        all_projects = [engine.db._row_to_dict(r) for r in all_rows]
    except Exception:
        all_projects = []

    return {
        "active": active,
        "all_projects": all_projects,
        "count_active": len(active),
        "count_all": len(all_projects),
    }


def init_project_memory() -> dict:
    """
    初始化项目级记忆（会话启动时调用）
    同步项目上下文 → SQLite → 返回注入结果
    """
    init_dirs()
    engine = WanYiCore()
    sync_result = sync_project_memory(engine)
    active_result = get_active_projects(engine)

    engine.db.conn.close()

    return {
        **sync_result,
        "active_projects": active_result
    }


# ═══════════════════════════════════════════════════════════════════
# v4 — gotchas 桥接（PROJECTMEM 式项目级记忆隐形串联）
# ═══════════════════════════════════════════════════════════════════
# 原理：跨项目只共享"抽象洞察"（gotcha），不共享原始轨迹
# gotcha 带技术栈/主题签名，新项目检测到匹配栈自动浮出
# 负迁移防护：签名不匹配绝不跨项目注入

GOTCHA_SIGNATURES = {
    "python": ["python", "django", "flask", "fastapi", "pip", "conda"],
    "node": ["node", "npm", "typescript", "react", "vite", "express"],
    "java": ["java", "spring", "maven", "gradle", "jvm"],
    "前端": ["前端", "html", "css", "javascript", "vue", "react", "ui"],
    "数据": ["数据", "数据库", "sql", "sqlite", "pandas", "excel", "csv"],
    "交易": ["交易", "基金", "股票", "策略", "仓位", "风控", "回测"],
    "写作": ["写作", "小说", "章节", "剧情", "番茄", "网文"],
    "记忆系统": ["记忆", "mcp", "插件", "中枢", "obsidian", "sqlite"],
}


def _signature_tags(content: str) -> list:
    """从内容提取技术栈/主题签名（栈检测匹配）"""
    tags = []
    low = content.lower()
    for domain, kws in GOTCHA_SIGNATURES.items():
        if any(kw in low for kw in kws):
            tags.append(domain)
    return tags


def save_gotcha(engine: WanYiCore, project: str, title: str,
                lesson: str, context: str = "") -> dict:
    """
    沉淀一条 gotcha（项目级踩坑/经验，跨项目桥接）
    存为全局级 + 法级记忆，带技术栈签名，供其他项目检测匹配浮出
    """
    sig_tags = _signature_tags(f"{title} {lesson} {context}")
    content = f"[GOTCHA] {title}：{lesson}"
    r = engine.db.upsert_memory(
        content=content,
        layer=LAYER_FA,
        mem_type="pattern",
        category="gotcha",
        space=SPACE_GLOBAL,  # 全局域：跨项目可见
        project=None,        # 不绑定单一项目（隐形串联关键）
        privacy=PRIVACY_INTERNAL,
        source=f"gotcha/{project}",
        tags=["gotcha"] + sig_tags + [project],
        confidence=0.8,
        pinned=False,
        importance=0.75,
        session_id=SESSION_ID,
        metadata={"origin_project": project, "signatures": sig_tags, "title": title}
    )
    engine.db.log_event(SESSION_ID, "gotcha_saved",
                        {"project": project, "title": title, "signatures": sig_tags},
                        scope="进化")
    return {"status": "saved", "memory_id": r["memory_id"], "signatures": sig_tags}


def find_matching_gotchas(engine: WanYiCore, project_context: str,
                          limit: int = 5) -> list:
    """
    检测项目上下文中的技术栈/主题，匹配浮出相关 gotcha
    PROJECTMEM 核心机制：新项目检测到匹配栈 → 相关教训自动浮出
    """
    sig_tags = _signature_tags(project_context)
    if not sig_tags:
        return []
    results = []
    for tag in sig_tags:
        rows = engine.db.conn.execute("""
            SELECT memory_id, content, metadata FROM memories
            WHERE category = 'gotcha' AND tags LIKE ?
            ORDER BY importance DESC LIMIT ?
        """, (f"%{tag}%", limit)).fetchall()
        for r in rows:
            meta = json.loads(r["metadata"] or "{}")
            results.append({
                "memory_id": r["memory_id"],
                "content": r["content"],
                "matched_signature": tag,
                "origin_project": meta.get("origin_project", ""),
            })
    # 去重
    seen, unique = set(), []
    for item in results:
        if item["memory_id"] not in seen:
            seen.add(item["memory_id"])
            unique.append(item)
    return unique[:limit]


def sync_gotchas_from_projects(engine: WanYiCore, md_path: str = None) -> dict:
    """从项目上下文中自动提取 gotcha（项目进展里的"教训/踩坑"字段）"""
    path = md_path or PROJECT_CONTEXT_PATH
    projects = parse_project_context(path)
    saved = []
    for proj in projects:
        name = proj["name"]
        body = proj.get("body", "")
        # 提取"教训/踩坑/经验"类字段
        for kw in ["教训", "踩坑", "经验", "坑", "注意"]:
            for match in re.finditer(rf'\*\*?{kw}[^*]*\*\*?[:：]?\s*(.+?)(?:\n|$)', body):
                lesson = match.group(1).strip()
                if len(lesson) >= 6:
                    saved.append(save_gotcha(engine, name, f"{name}-{kw}", lesson))
    return {"saved": saved, "count": len(saved)}


if __name__ == "__main__":
    result = init_project_memory()
    print(json.dumps(result, ensure_ascii=False, indent=2))
