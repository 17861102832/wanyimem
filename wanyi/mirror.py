"""
只读 Markdown 镜像导出（wanyimem 护城河 #6 · 可读/可版本化）
==========================================================
把事件溯源数据库里的记忆/错题/经验/知识空白/反事实分支/跨域模式，
渲染成一份**人类可读、可 diff、可版本化**的 Markdown 镜像。
只读：不写任何库，只查询。默认按层(道/法/术)分组，顺序稳定（便于 git 版本化）。

用法（命令行）:
    wanyi-export [--db PATH] [--out PATH] [--layer 道|法|术|all]
    python -m wanyi.mirror --out memories.md --db ./memory.db

作为函数:
    from wanyi.mirror import export_markdown
    md = export_markdown("memory.db")     # 返回字符串
    export_markdown("memory.db", "memory.md")  # 同时写文件
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

LAYERS = ["道", "法", "术"]
MEM_TYPES = {
    "principle": "原则", "rule": "规则", "strategy": "策略", "fact": "事实",
    "experience": "经验", "insight": "洞见", "lesson": "教训", "pattern": "模式",
    "decision": "决策", "turn": "会话", "note": "笔记", "event": "事件",
    "checkpoint": "检查点", "progress": "进度",
}


def _read_rows(conn, sql, params=()):
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    except Exception:
        return []


def _json_list(raw):
    if not raw:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            v = json.loads(raw)
            return v if isinstance(v, list) else [v]
        except Exception:
            return [raw]
    return [raw]


def _fmt_time(t):
    return (t or "")[:19].replace("T", " ")


def export_markdown(db_path, out_path=None, layer="all") -> str:
    """渲染 Markdown 镜像；`layer` 可为 all/<单个层名>"""
    db_path = Path(db_path)
    if not db_path.exists():
        return f"# 万忆中枢 · 只读记忆镜像\n\n> 数据库不存在：`{db_path}`"
    import sqlite3
    uri = f"file:{db_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        live = _read_rows(conn, "SELECT COUNT(*) c FROM memories")
        mistakes = _read_rows(conn, "SELECT COUNT(*) c FROM mistakes")
        exps = _read_rows(conn, "SELECT COUNT(*) c FROM experiences")
        gaps = _read_rows(conn, "SELECT COUNT(*) c FROM knowledge_gaps") if _table_exists(conn, "knowledge_gaps") else []
        cfs = _read_rows(conn, "SELECT COUNT(*) c FROM counterfactual_branches") if _table_exists(conn, "counterfactual_branches") else []
        ap = _read_rows(conn, "SELECT COUNT(*) c FROM analog_patterns") if _table_exists(conn, "analog_patterns") else []
        n_live = live[0]["c"] if live else 0
        lines = []
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines.append("# 万忆中枢 · 只读记忆镜像")
        lines.append("")
        lines.append(f"> 导出时间：{ts} ｜ 数据库：`{db_path}` ｜ 只读导出（不修改存储）")
        lines.append("")
        lines.append("## 总览")
        lines.append("")
        lines.append("| 对象 | 条数 |")
        lines.append("|---|---|")
        lines.append(f"| 记忆（道/法/术） | {n_live} |")
        lines.append(f"| 错题本 | {mistakes[0]['c'] if mistakes else 0} |")
        lines.append(f"| 经验库 | {exps[0]['c'] if exps else 0} |")
        lines.append(f"| 知识空白 | {gaps[0]['c'] if gaps else 0} |")
        lines.append(f"| 反事实分支 | {cfs[0]['c'] if cfs else 0} |")
        lines.append(f"| 跨域模式 | {ap[0]['c'] if ap else 0} |")
        lines.append("")

        # 记忆主体：按 layer 分组
        mems = _read_rows(
            conn,
            "SELECT * FROM memories ORDER BY layer, COALESCE(category,''), created_at, memory_id",
        )
        by_layer = {l: [] for l in LAYERS}
        for m in mems:
            by_layer.setdefault(m.get("layer"), []).append(m)

        for l in LAYERS:
            if layer != "all" and layer != l:
                continue
            group = by_layer.get(l) or []
            lines.append(f"## {l} · 记忆（{len(group)}）")
            lines.append("")
            if not group:
                lines.append("_（空）_")
                lines.append("")
                continue
            # 按 category 再分组，保持顺序稳定
            by_cat = {}
            for m in group:
                cat = m.get("category") or "未分类"
                by_cat.setdefault(cat, []).append(m)
            for cat in sorted(by_cat):
                items = by_cat[cat]
                lines.append(f"### {cat}")
                lines.append("")
                for m in items:
                    tt = MEM_TYPES.get(m.get("mem_type") or "", m.get("mem_type") or "")
                    conf = m.get("confidence")
                    imp = m.get("importance")
                    detail = []
                    if tt:
                        detail.append(f"类型{tt}")
                    if imp is not None:
                        detail.append(f"重要度{float(imp):.2f}")
                    if conf is not None:
                        detail.append(f"置信{float(conf):.2f}")
                    if m.get("created_at"):
                        detail.append(f"建于{_fmt_time(m['created_at'])}")
                    if m.get("updated_at"):
                        detail.append(f"更新于{_fmt_time(m['updated_at'])}")
                    tags = _json_list(m.get("tags"))
                    meta = " ".join(detail)
                    prefix = f"- **[{meta}]** " if meta else "- "
                    lines.append(f"{prefix}{m.get('content','').strip()}")
                    if tags:
                        lines.append(f"  - 标签：`{'、'.join(tags)}`")
                lines.append("")

        # 错题本
        _section_errors(lines, conn)
        # 经验库
        _section_experiences(lines, conn)
        # 知识空白
        _section_gaps(lines, conn)
        # 反事实分支
        _section_counterfactual(lines, conn)
        # 跨域模式
        _section_analog(lines, conn)

        return "\n".join(lines).rstrip() + "\n"
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _table_exists(conn, name):
    try:
        return conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name=?", (name,)
        ).fetchone() is not None
    except Exception:
        return False


def _section_errors(lines, conn):
    rows = _read_rows(conn, "SELECT * FROM mistakes ORDER BY created_at DESC")
    if not rows:
        return
    lines.append("## 错题本")
    lines.append("")
    for r in rows:
        lines.append(f"- **{r.get('task_name') or '未命名'}**：{r.get('content','').strip()}")
        if r.get("lesson"):
            lines.append(f"  - 教训：{r['lesson']}")
        if r.get("pattern"):
            lines.append(f"  - 模式：`{r['pattern']}`（出现{r.get('pattern_count',1)}次）")
        lines.append("")


def _section_experiences(lines, conn):
    rows = _read_rows(conn, "SELECT * FROM experiences ORDER BY created_at DESC")
    if not rows:
        return
    lines.append("## 经验库")
    lines.append("")
    for r in rows:
        lines.append(f"- **{r.get('task_name') or '提炼'}**：{r.get('content','').strip()}")
        if r.get("source_count", 1) > 1:
            lines.append(f"  - 由 {r['source_count']} 条记忆提炼")
        lines.append("")


def _section_gaps(lines, conn):
    if not _table_exists(conn, "knowledge_gaps"):
        return
    rows = _read_rows(conn, "SELECT * FROM knowledge_gaps ORDER BY created_at DESC")
    if not rows:
        return
    lines.append("## 知识空白（元认知：知道自己不知道）")
    lines.append("")
    for r in rows:
        status = r.get("status", "open")
        mark = "🔍" if status == "open" else "✅"
        lines.append(f"- {mark} {r.get('query_text','').strip()} ｜ 被查{r.get('hit_count',0)}次 ｜ {status}")
        if r.get("filled_by"):
            lines.append(f"  - 已补：{r['filled_by']}")
        if r.get("created_at"):
            lines.append(f"  - {_fmt_time(r['created_at'])}")
        lines.append("")


def _section_counterfactual(lines, conn):
    if not _table_exists(conn, "counterfactual_branches"):
        return
    rows = _read_rows(conn, "SELECT * FROM counterfactual_branches ORDER BY created_at DESC")
    if not rows:
        return
    lines.append("## 反事实分支（护城河 #2）")
    lines.append("")
    for r in rows:
        verdict = r.get("verdict")
        emoji = {"open": "🕐", "fact_won": "✅", "counter_won": "⚠️", "neutral": "⚖️", "expired": "📦"}.get(verdict, "•")
        lines.append(f"- {emoji} **{r.get('decision_text','').strip()}** ｜ 风险{r.get('risk_level')} ｜ {verdict}")
        lines.append(f"  - 实际：{r.get('fact_path','')}")
        lines.append(f"  - 反事实：{r.get('counter_path','')}")
        if r.get("fact_outcome"):
            lines.append(f"  - 实测结果：{r['fact_outcome']}")
        if r.get("lesson_learned"):
            lines.append(f"  - 教训：{r['lesson_learned']}")
        lines.append("")


def _section_analog(lines, conn):
    if not _table_exists(conn, "analog_patterns"):
        return
    rows = _read_rows(conn, "SELECT * FROM analog_patterns ORDER BY hit_count DESC, confidence DESC")
    if not rows:
        return
    lines.append("## 跨域模式（护城河 #3）")
    lines.append("")
    for r in rows:
        domains = _json_list(r.get("domains"))
        lines.append(f"- **{r.get('abstract_name','')}**：{r.get('essence','').strip()} ｜ 命中{r.get('hit_count',0)}次 ｜ 置信{float(r.get('confidence',0.7)):.2f}")
        if domains:
            lines.append(f"  - 覆盖领域：`{'、'.join(domains)}`")
        lines.append("")


def main(argv=None):
    ap = argparse.ArgumentParser(description="wanyimem 只读 Markdown 镜像导出")
    ap.add_argument("--db", default=None, help="数据库路径（默认取 WANYI_MEMORY_DB / 万忆中枢_MEMORY_DB）")
    ap.add_argument("--out", default=None, help="输出 Markdown 文件（默认 stdout）")
    ap.add_argument("--layer", default="all", choices=["all", "道", "法", "术"], help="导出的层（默认 all）")
    args = ap.parse_args(argv)

    db = args.db
    if not db:
        from env_compat import get_env
        db = get_env("万忆中枢_MEMORY_DB", "WANYI_MEMORY_DB", "memory.db")
    md = export_markdown(db, layer=args.layer)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(md, encoding="utf-8")
        print(f"[wanyi-export] 已写出 {args.out}（{len(md)} 字符）", file=sys.stderr)
    else:
        sys.stdout.write(md)


if __name__ == "__main__":
    main()
