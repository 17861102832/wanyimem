#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║          万忆中枢 v4 — 园艺师后台模块（gardener.py）            ║
║                                                                  ║
║  借鉴 KektorDB Gardener（11 检测器）+ ExpeL 提炼管道              ║
║  + Skill-Pro 技能结晶 + MemoryBank 记忆强度                      ║
║                                                                  ║
║  我们不设闸，我们养园丁。                                          ║
║  门禁是给没有上下文的系统用的，园丁是给懂主人的系统用的。          ║
║                                                                  ║
║  v1 三检测器 + 提炼管道：                                         ║
║  - 矛盾检测（contradiction）：新记忆与旧记忆冲突时标记            ║
║  - 冗余检测（redundancy）：高度相似记忆归并提示                   ║
║  - 洞见提炼（insight）：多条术级 → 法级模式 → 道级原则            ║
║  - 技能结晶（skill）：重复成功模式 ≥2 次 → 技能文件               ║
║  - 每日日志（daily log）：Obsidian 思考档案镜像                   ║
╚══════════════════════════════════════════════════════════════════╝
"""
import json
import re
from datetime import datetime
from pathlib import Path

from env_compat import get_env  # v1.1：中文优先/英文兜底

# 相似度阈值
DUP_THRESHOLD = 0.85      # 冗余检测：内容相似度
CONTRADICT_KEYWORDS = ["不对", "错了", "推翻", "更正", "不是", "相反",
                       "重新考虑", "修正", "不要再", "废掉", "弃用", "反例"]

# 结晶阈值
CRYSTALIZE_THRESHOLD = 2  # 同一模式成功 ≥2 次 → 技能候选


def now_iso() -> str:
    return datetime.now().isoformat()


class Gardener:
    """
    园艺师后台 — 挂在 WanYiCore 下（self.gardener）
    原则：全量存储不遗忘，园艺师只做"提炼/标记/暴露控制"，绝不删除
    """

    def __init__(self, db, session_id: str = "unknown", obsidian_vault: Path = None):
        self.db = db
        self.session_id = session_id
        self.obsidian_vault = obsidian_vault

    # ── 检测器 1：矛盾检测 ────────────────────────────────────────

    def detect_contradictions(self, content: str, exclude_id: str = None) -> list[dict]:
        """新内容与旧记忆的潜在矛盾检测（KektorDB contradiction detector）"""
        # 只对明确否定词触发（避免误报）
        has_negation = any(kw in content for kw in CONTRADICT_KEYWORDS)
        if not has_negation:
            return []

        # 提取内容中的核心实体/主题
        entities = self._extract_entities(content)
        contradictions = []
        for ent in entities:
            rows = self.db.conn.execute("""
                SELECT memory_id, content, layer, mem_type, confidence, updated_at
                FROM memories WHERE content LIKE ? AND memory_id != ?
                ORDER BY updated_at DESC LIMIT 5
            """, (f"%{ent}%", exclude_id or "")).fetchall()
            for r in rows:
                contradictions.append({
                    "new_content": content[:100],
                    "old_memory_id": r["memory_id"],
                    "old_content": r["content"][:100],
                    "old_layer": r["layer"],
                    "old_mem_type": r["mem_type"],
                    "old_confidence": r["confidence"],
                    "old_updated_at": r["updated_at"],
                    "suggest": "标记矛盾，交置信度仲裁（不删除任何一条）",
                })
        return contradictions

    def arbitrate_conflict(self, memory_id_a: str, memory_id_b: str) -> dict:
        """
        矛盾仲裁：不删任何一条，交给置信度系统裁决谁更可信
        规则：谁置信度高谁排前；僵持则标记"待验证"
        """
        conf_a = self.db.conn.execute(
            "SELECT confidence FROM confidence WHERE target_type='memory' AND target_id=?",
            (memory_id_a,)).fetchone()
        conf_b = self.db.conn.execute(
            "SELECT confidence FROM confidence WHERE target_type='memory' AND target_id=?",
            (memory_id_b,)).fetchone()
        score_a = conf_a["confidence"] if conf_a else 0.5
        score_b = conf_b["confidence"] if conf_b else 0.5

        # 冲突时给两者都加摩擦（降低置信度，提醒谨慎）
        verdict = "conflict_unresolved"  # v1.1：默认兜底，防止 hasattr=False 时 UnboundLocalError
        if hasattr(self.db, "confidence"):
            if abs(score_a - score_b) < 0.1:
                self.db.confidence.challenge("memory", memory_id_a, "与另一记忆冲突")
                self.db.confidence.challenge("memory", memory_id_b, "与另一记忆冲突")
                verdict = "conflict_unresolved"
            else:
                winner = memory_id_a if score_a > score_b else memory_id_b
                loser = memory_id_b if winner == memory_id_a else memory_id_a
                self.db.confidence.challenge("memory", loser, "矛盾仲裁败诉")
                self.db.confidence.validate("memory", winner, "矛盾仲裁胜出")
                verdict = f"resolved: {winner} wins"

        self.db.log_event(self.session_id, "conflict_arbitrated",
                          {"a": memory_id_a, "b": memory_id_b, "verdict": verdict},
                          scope="进化")
        return {"verdict": verdict, "score_a": score_a, "score_b": score_b}

    # ── 检测器 2：冗余检测 ────────────────────────────────────────

    def detect_redundancy(self, limit: int = 50) -> list[dict]:
        """高度相似记忆归并提示（不删除，只标记可合并）"""
        rows = self.db.conn.execute("""
            SELECT memory_id, content, layer, mem_type FROM memories
            ORDER BY created_at DESC LIMIT ?
        """, (limit,)).fetchall()
        groups = []
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                sim = self._jaccard_similarity(rows[i]["content"], rows[j]["content"])
                if sim >= DUP_THRESHOLD:
                    groups.append({
                        "a": rows[i]["memory_id"],
                        "b": rows[j]["memory_id"],
                        "similarity": round(sim, 3),
                        "suggest": "冗余记忆，可合并为一条（原两条保留）",
                    })
        return groups

    # ── 检测器 3：洞见提炼（术→法→道 管道） ──────────────────────

    def extract_insights(self, task_name: str = None) -> dict:
        """
        提炼管道（ExpeL 式）：
        1. 术级观察 → 汇总同任务/同主题 → 法级模式
        2. 法级模式多次重复 → 道级原则（写 L2/L3，不删 L1）
        """
        # 找同任务的成功/失败轨迹
        sql = """
            SELECT process_id, phase, content, outcome, task_name
            FROM process_events WHERE 1=1
        """
        params = []
        if task_name:
            sql += " AND task_name = ?"
            params.append(task_name)
        sql += " ORDER BY timestamp DESC LIMIT 100"
        rows = self.db.conn.execute(sql, params).fetchall()

        if not rows:
            return {"insights": [], "message": "暂无轨迹可提炼"}

        # 按任务聚类
        by_task = {}
        for r in rows:
            t = r["task_name"] or "未分类"
            by_task.setdefault(t, []).append(dict(r))

        insights = []
        for t, events in by_task.items():
            successes = [e for e in events if e["outcome"] == "success"]
            failures = [e for e in events if e["outcome"] == "failure"]
            if len(successes) >= 1 or len(failures) >= 1:
                insight = {
                    "task_name": t,
                    "success_count": len(successes),
                    "failure_count": len(failures),
                    "lesson_ratio": round(len(failures) / max(1, len(events)), 2),
                    "summary": f"{t}: {len(successes)}次成功 / {len(failures)}次失败"
                }
                insights.append(insight)
                # 沉淀为经验（成功路径）
                if successes:
                    self._crystallize_experience(t, successes[0]["content"])

        self.db.log_event(self.session_id, "gardener_insights",
                          {"task_count": len(by_task), "insight_count": len(insights)},
                          scope="进化")
        return {"insights": insights, "task_count": len(by_task)}

    # ── 技能结晶（通道 C） ────────────────────────────────────────

    def crystallize_skills(self, skill_dir: Path = None, threshold: int = None) -> dict:
        """
        技能结晶：同一任务成功模式 ≥2 次 → 生成全局技能文件
        借鉴 Skill-Pro 验证闸门：候选 → 实战验证 → 正式
        """
        threshold = threshold or CRYSTALIZE_THRESHOLD
        rows = self.db.conn.execute("""
            SELECT task_name, SUM(source_count) as cnt FROM experiences
            GROUP BY task_name HAVING SUM(source_count) >= ?
        """, (threshold,)).fetchall()

        if not rows:
            return {"candidates": 0, "skills_created": []}

        skills_created = []
        for r in rows:
            task = r["task_name"]
            skill_name = self._skill_name(task)
            if not skill_dir:
                skill_dir = Path(get_env("万忆中枢_SKILL_DIR", "WANYI_SKILL_DIR",
                    str(Path(__file__).parent / "skills_crystal")))
            skill_dir.mkdir(parents=True, exist_ok=True)
            skill_file = skill_dir / f"{skill_name}.md"

            # 提取该任务的经验
            exps = self.db.conn.execute("""
                SELECT content FROM experiences WHERE task_name = ? ORDER BY confidence DESC
            """, (task,)).fetchall()
            steps = "\n".join(f"{i+1}. {e['content']}" for i, e in enumerate(exps[:10]))

            content = f"""# 技能：{task}

> 由万忆中枢园艺师自动结晶（候选级，经实战验证后升为正式）
> 来源：{r['cnt']} 次成功经验

## 适用场景
{task}

## 执行步骤
{steps}

## 验证闸门
- [ ] 候选级（已生成）
- [ ] 实战验证 ≥1 次
- [ ] 升为正式级
"""
            skill_file.write_text(content, encoding="utf-8")
            skills_created.append({"task": task, "file": str(skill_file),
                                   "source_count": r["cnt"]})

        self.db.log_event(self.session_id, "gardener_skills",
                          {"created": len(skills_created)}, scope="进化")
        return {"candidates": len(rows), "skills_created": skills_created}

    # ── 每日日志镜像（AgentMemory 式思考档案） ────────────────────

    def write_daily_log(self) -> dict:
        """生成/更新 Obsidian 思考档案（YYYY-MM-DD.md），每日深巩固后调用"""
        if not self.obsidian_vault:
            return {"status": "no_vault", "message": "未配置 Obsidian 仓库"}
        today = datetime.now().strftime("%Y-%m-%d")
        daily_dir = self.obsidian_vault / "思考档案"
        daily_dir.mkdir(parents=True, exist_ok=True)
        daily_file = daily_dir / f"{today}.md"

        # 收集今天的进化事件
        today_str = today + "T"
        events = self.db.conn.execute("""
            SELECT event_type, event_data, scope, timestamp FROM session_events
            WHERE timestamp LIKE ? AND scope IN ('决策','纠错','进化','过程')
            ORDER BY timestamp ASC LIMIT 100
        """, (f"{today_str}%",)).fetchall()

        # 收集今天新增的记忆
        memories = self.db.conn.execute("""
            SELECT content, layer, mem_type, importance FROM memories
            WHERE created_at LIKE ? ORDER BY created_at DESC LIMIT 20
        """, (f"{today_str}%",)).fetchall()

        lines = [f"# 思考档案 {today}", "",
                 f"> 由万忆中枢园艺师自动生成 · {now_iso()}",
                 "", "## 今日进化事件", ""]
        if events:
            for e in events[:50]:
                data = json.loads(e["event_data"] or "{}")
                lines.append(f"- [{e['scope']}] {e['event_type']} — {json.dumps(data, ensure_ascii=False)[:120]}")
        else:
            lines.append("- （今日暂无进化事件）")

        lines += ["", "## 今日新记忆", ""]
        if memories:
            for m in memories[:20]:
                lines.append(f"- [{m['layer']}/{m['mem_type']}·重要{m['importance']}] {m['content'][:80]}")
        else:
            lines.append("- （今日暂无新记忆）")

        daily_file.write_text("\n".join(lines), encoding="utf-8")
        self.db.log_event(self.session_id, "daily_log_written",
                          {"file": str(daily_file)}, scope="系统")
        return {"status": "written", "file": str(daily_file),
                "events": len(events), "memories": len(memories)}

    # ── 深巩固（Gardener 主循环） ─────────────────────────────────

    def deep_consolidation(self, run_skills: bool = True,
                           write_log: bool = True) -> dict:
        """园艺师深巩固：全库巡检（轻巩固的强化版，每日触发）"""
        result = {
            "insights": self.extract_insights(),
            "redundancy": self.detect_redundancy(),
            "skills": self.crystallize_skills() if run_skills else {"candidates": 0},
            "daily_log": self.write_daily_log() if write_log else {"status": "skipped"},
        }
        # 汇总统计
        result["stats"] = self.self_check()
        self.db.log_event(self.session_id, "deep_consolidation",
                          {"insights": len(result["insights"].get("insights", [])),
                           "redundancy": len(result["redundancy"]),
                           "skills": len(result["skills"].get("skills_created", []))},
                          scope="进化")
        return result

    # ── 工具方法 ──────────────────────────────────────────────────

    def _crystallize_experience(self, task_name: str, content: str):
        """成功路径沉淀到经验库（带置信度初始化）"""
        try:
            exp = self.db.conn.execute(
                "SELECT experience_id FROM experiences WHERE task_name = ? AND content = ?",
                (task_name, content)).fetchone()
            if not exp:
                eid = f"EXP_{task_name[:20]}_{int(datetime.now().timestamp())}"
                self.db.conn.execute("""
                    INSERT INTO experiences (experience_id, task_name, content, mem_type,
                    layer, confidence, source_count, tags, ref_process_ids, created_at, updated_at, session_id)
                    VALUES (?, ?, ?, 'pattern', '法', 0.6, 1, '[]', '[]', ?, ?, ?)
                """, (eid, task_name, content, now_iso(), now_iso(), self.session_id))
                self.db.conn.commit()
                if hasattr(self.db, "confidence"):
                    self.db.confidence.init_entry("experience", eid, 0.6)
        except Exception:
            pass

    def _extract_entities(self, content: str) -> list[str]:
        """启发式实体提取（名词性短语，供矛盾检测匹配）"""
        # 中文实体：2-6 字连续中文片段（简单启发式）
        parts = re.findall(r"[\u4e00-\u9fff]{2,6}", content)
        # 去重 + 过滤停用词
        stopwords = {"我们", "你们", "他们", "这个", "那个", "一个", "就是",
                     "不是", "因为", "所以", "可以", "需要", "没有", "已经"}
        seen = set()
        result = []
        for p in parts:
            if p not in stopwords and p not in seen:
                seen.add(p)
                result.append(p)
            if len(result) >= 5:
                break
        return result

    def _jaccard_similarity(self, a: str, b: str) -> float:
        """Jaccard 相似度（字符 2-gram）"""
        if not a or not b:
            return 0.0
        def grams(s):
            return {s[i:i+2] for i in range(len(s) - 1)}
        ga, gb = grams(a), grams(b)
        if not ga or not gb:
            return 0.0
        return len(ga & gb) / len(ga | gb)

    def _skill_name(self, task_name: str) -> str:
        """任务名 → 技能文件名（清洗非法字符）"""
        cleaned = re.sub(r'[\\/:*?"<>|]', "_", task_name).strip()
        return cleaned[:40] if cleaned else "unnamed"

    def self_check(self) -> dict:
        # v1.1：contradiction 候选改为实际巡检近期含否定词记忆（原先传空串恒为 0，自检静默失效）
        cand = 0
        try:
            recent = self.db.conn.execute("""
                SELECT memory_id, content FROM memories
                ORDER BY updated_at DESC LIMIT 30
            """).fetchall()
            for r in recent:
                if (any(kw in (r["content"] or "") for kw in CONTRADICT_KEYWORDS)
                        and self.detect_contradictions(r["content"], exclude_id=r["memory_id"])):
                    cand += 1
        except Exception:
            cand = 0
        return {
            "contradiction_candidates": cand,
            "redundancy_pairs": len(self.detect_redundancy()),
            "insights": len(self.extract_insights().get("insights", [])),
            "last_deep_consolidation": self.db.conn.execute("""
                SELECT MAX(timestamp) as ts FROM session_events WHERE event_type = 'deep_consolidation'
            """).fetchone()["ts"],
        }


