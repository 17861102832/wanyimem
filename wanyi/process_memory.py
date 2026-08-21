#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║        万忆中枢 v4 — 过程记忆模块（process_memory.py）          ║
║                                                                  ║
║  借鉴 ExpeL 轨迹分段 + Reflexion 失败反思 + reflect 教训持久化    ║
║                                                                  ║
║  功能：                                                          ║
║  - 轨迹分段存储（规划/尝试/纠错/反思/结论）                      ║
║  - 记忆锚点机制（长程任务断点恢复，不重跑）                      ║
║  - 错题本自动沉淀（失败 → 反例条目 + 模式统计）                  ║
║  - 经验库自动沉淀（成功 → 可复用模式）                           ║
╚══════════════════════════════════════════════════════════════════╝
"""
import json
import time
import uuid
import hashlib
from datetime import datetime
from typing import List

# 轨迹阶段（ExpeL 五段式）
PHASE_PLAN = "规划"      # 任务理解与方案设计
PHASE_TRY = "尝试"       # 执行与探索
PHASE_FIX = "纠错"       # 失败修正
PHASE_REFLECT = "反思"   # 复盘总结
PHASE_CONCLUDE = "结论"  # 经验沉淀

PHASES = [PHASE_PLAN, PHASE_TRY, PHASE_FIX, PHASE_REFLECT, PHASE_CONCLUDE]

# 结果标记
OUTCOME_NEUTRAL = "neutral"
OUTCOME_SUCCESS = "success"
OUTCOME_FAILURE = "failure"


def now_iso() -> str:
    return datetime.now().isoformat()


def gen_process_id(task_name: str) -> str:
    """生成轨迹 ID（按任务名 + 时间）"""
    t = int(time.time())
    safe = task_name[:30] if task_name else "task"
    return f"PROC_{safe}_{t}"


def gen_mistake_id(task_name: str) -> str:
    t = int(time.time())
    safe = (task_name or "task")[:20]
    return f"MIST_{safe}_{t}"


def gen_experience_id(task_name: str) -> str:
    t = int(time.time())
    safe = (task_name or "task")[:20]
    return f"EXP_{safe}_{t}"


class ProcessMemory:
    """
    过程记忆管理器 — 挂在 WanYiCore 下（self.process）
    所有写操作都通过 L0 事件日志留痕（append-only 真相源）
    """

    def __init__(self, db, session_id: str = "unknown"):
        self.db = db
        self.session_id = session_id

    # ── 轨迹操作 ──────────────────────────────────────────────────

    def start_process(self, task_name: str, plan: str = "") -> dict:
        """开启一个新轨迹（任务规划阶段）"""
        process_id = gen_process_id(task_name)
        self.add_phase(process_id, task_name, PHASE_PLAN, plan or task_name)
        # 写 L0 事件
        self.db.log_event(self.session_id, "process_start",
                          {"process_id": process_id, "task_name": task_name},
                          scope="过程")
        return {"process_id": process_id, "task_name": task_name, "started": True}

    def add_phase(self, process_id: str, task_name: str, phase: str,
                  content: str, outcome: str = OUTCOME_NEUTRAL,
                  anchor: str = None, metadata: dict = None) -> dict:
        """追加一个轨迹阶段（append-only，绝不覆盖）"""
        # 计算阶段序号
        row = self.db.conn.execute(
            "SELECT COALESCE(MAX(phase_seq), 0) + 1 AS seq FROM process_events WHERE process_id = ?",
            (process_id,)
        ).fetchone()
        seq = row["seq"] if row else 1
        now = now_iso()
        meta_str = json.dumps(metadata or {}, ensure_ascii=False)

        self.db.conn.execute("""
            INSERT INTO process_events
            (process_id, task_name, phase, phase_seq, content, outcome, anchor, metadata, timestamp, session_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (process_id, task_name, phase, seq, content, outcome, anchor,
              meta_str, now, self.session_id))
        self.db.conn.commit()

        # L0 事件留痕
        self.db.log_event(self.session_id, "process_phase",
                          {"process_id": process_id, "phase": phase,
                           "seq": seq, "outcome": outcome, "task_name": task_name},
                          scope="过程")

        # 失败阶段 → 自动沉淀错题本（Reflexion 式）
        if outcome == OUTCOME_FAILURE:
            self._auto_mistake(task_name, content, process_id, phase)

        # 成功结论阶段 → 自动沉淀经验库（ExpeL 式）
        if outcome == OUTCOME_SUCCESS and phase == PHASE_CONCLUDE:
            self._auto_experience(task_name, content, process_id)

        return {"process_id": process_id, "phase": phase, "seq": seq,
                "outcome": outcome, "auto_mistake": outcome == OUTCOME_FAILURE,
                "auto_experience": (outcome == OUTCOME_SUCCESS and phase == PHASE_CONCLUDE)}

    def get_process(self, process_id: str) -> dict:
        """读取完整轨迹（按阶段顺序）"""
        rows = self.db.conn.execute("""
            SELECT * FROM process_events WHERE process_id = ?
            ORDER BY phase_seq ASC
        """, (process_id,)).fetchall()
        return {
            "process_id": process_id,
            "phases": [dict(r, metadata=json.loads(r["metadata"] or "{}")) for r in rows],
            "phase_count": len(rows),
        }

    def list_processes(self, task_name: str = None, limit: int = 20) -> List[dict]:
        """列出轨迹（可按任务筛选）"""
        sql = "SELECT DISTINCT process_id, task_name, MAX(timestamp) as last_ts FROM process_events"
        params = []
        if task_name:
            sql += " WHERE task_name = ?"
            params.append(task_name)
        sql += " GROUP BY process_id ORDER BY last_ts DESC LIMIT ?"
        params.append(limit)
        rows = self.db.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    # ── 记忆锚点机制 ──────────────────────────────────────────────

    def set_anchor(self, process_id: str, phase: str, anchor_point: str,
                   state: dict) -> dict:
        """
        在关键节点设置记忆锚点（断点恢复用）
        anchor_point: 该阶段的恢复点描述，state: 恢复所需状态
        """
        anchor_id = f"ANCHOR_{process_id[:20]}_{phase}_{int(time.time())}"
        # 存到 checkpoint 表（复用冷续传机制）
        self.db.save_checkpoint(anchor_id, process_id, f"{phase}-锚点", 0.0,
                                {"anchor_point": anchor_point, "anchor_phase": phase, **state}, self.session_id)
        # 更新 process_events 对应阶段
        self.db.conn.execute("""
            UPDATE process_events SET anchor = ? WHERE process_id = ? AND phase = ?
        """, (anchor_id, process_id, phase))
        self.db.conn.commit()
        self.db.log_event(self.session_id, "memory_anchor",
                          {"process_id": process_id, "phase": phase, "anchor_id": anchor_id},
                          scope="过程")
        return {"anchor_id": anchor_id, "process_id": process_id, "phase": phase}

    def restore_from_anchor(self, process_id: str = None, anchor_id: str = None) -> dict:
        """
        从记忆锚点恢复（解决"上下文压缩后重跑"问题）
        返回该锚点之后需要继续的阶段，以及恢复所需状态
        """
        ckpt = None
        if anchor_id:
            ckpt = self.db.load_checkpoint(anchor_id)
        elif process_id:
            # 找该轨迹最后一个锚点
            row = self.db.conn.execute("""
                SELECT anchor FROM process_events
                WHERE process_id = ? AND anchor IS NOT NULL
                ORDER BY phase_seq DESC LIMIT 1
            """, (process_id,)).fetchone()
            if row and row["anchor"]:
                ckpt = self.db.load_checkpoint(row["anchor"])

        if not ckpt:
            return {"status": "no_anchor", "message": "未找到记忆锚点，需从头开始"}

        state = ckpt.get("state", {})
        anchor_phase = state.get("anchor_phase", "")
        # 计算已完成阶段
        done_rows = self.db.conn.execute("""
            SELECT phase FROM process_events WHERE process_id = ? ORDER BY phase_seq
        """, (process_id,)).fetchall()
        done_phases = [r["phase"] for r in done_rows]
        # 锚点之后的阶段 = 剩余需要继续的（断点恢复语义）
        if anchor_phase and anchor_phase in PHASES:
            anchor_idx = PHASES.index(anchor_phase)
            remaining = PHASES[anchor_idx + 1:]
        else:
            remaining = [p for p in PHASES if p not in done_phases]

        self.db.log_event(self.session_id, "anchor_restore",
                          {"process_id": process_id, "anchor_id": ckpt["checkpoint_id"],
                           "anchor_phase": anchor_phase, "remaining": remaining},
                          scope="过程")
        return {
            "status": "restored",
            "process_id": process_id,
            "anchor_id": ckpt["checkpoint_id"],
            "anchor_phase": anchor_phase,
            "anchor_point": state.get("anchor_point", ""),
            "completed_phases": done_phases,
            "remaining_phases": remaining,
            "restore_state": state,
        }

    # ── 错题本 ────────────────────────────────────────────────────

    def _auto_mistake(self, task_name: str, content: str, process_id: str, phase: str):
        """失败阶段自动沉淀错题本（Reflexion 式：教训入情景记忆）"""
        mistake_id = gen_mistake_id(task_name)
        # 简单模式提取：从失败内容里找关键词模式（reflect 式 pattern slug）
        pattern = self._extract_pattern(content)
        # 查重 + 模式计数
        existing = self.db.conn.execute(
            "SELECT mistake_id, pattern_count FROM mistakes WHERE pattern = ? AND task_name = ?",
            (pattern, task_name)
        ).fetchone()
        if existing:
            new_count = existing["pattern_count"] + 1
            self.db.conn.execute("""
                UPDATE mistakes SET pattern_count = ?, updated_at = ?
                WHERE mistake_id = ?
            """, (new_count, now_iso(), existing["mistake_id"]))
            self.db.conn.commit()
            return {"mistake_id": existing["mistake_id"], "deduped": True, "pattern_count": new_count}

        now = now_iso()
        self.db.conn.execute("""
            INSERT INTO mistakes (mistake_id, task_name, content, lesson, pattern,
            pattern_count, confidence, status, tags, ref_process_id, created_at, updated_at, session_id)
            VALUES (?, ?, ?, ?, ?, 1, 0.5, 'open', '[]', ?, ?, ?, ?)
        """, (mistake_id, task_name, content, "", pattern, process_id, now, now, self.session_id))
        self.db.conn.commit()
        self.db.log_event(self.session_id, "mistake_recorded",
                          {"mistake_id": mistake_id, "pattern": pattern,
                           "task_name": task_name, "phase": phase},
                          scope="纠错")
        return {"mistake_id": mistake_id, "deduped": False, "pattern": pattern}

    def add_mistake_lesson(self, mistake_id: str, lesson: str):
        """补充教训（Reflexion 式反思产出）"""
        self.db.conn.execute("""
            UPDATE mistakes SET lesson = ?, updated_at = ?, status = 'learned'
            WHERE mistake_id = ?
        """, (lesson, now_iso(), mistake_id))
        self.db.conn.commit()
        self.db.log_event(self.session_id, "mistake_lesson",
                          {"mistake_id": mistake_id, "lesson": lesson}, scope="纠错")
        return {"mistake_id": mistake_id, "status": "learned"}

    def list_mistakes(self, task_name: str = None, pattern: str = None,
                      limit: int = 50) -> List[dict]:
        """错题本查询（含模式频次统计 — reflect 式）"""
        sql = "SELECT * FROM mistakes WHERE 1=1"
        params = []
        if task_name:
            sql += " AND task_name = ?"
            params.append(task_name)
        if pattern:
            sql += " AND pattern = ?"
            params.append(pattern)
        sql += " ORDER BY pattern_count DESC, created_at DESC LIMIT ?"
        params.append(limit)
        rows = self.db.conn.execute(sql, params).fetchall()
        return [dict(r, tags=json.loads(r["tags"] or "[]")) for r in rows]

    def get_error_patterns(self) -> List[dict]:
        """高频错误模式（reflect 式 get_error_patterns）"""
        rows = self.db.conn.execute("""
            SELECT pattern, COUNT(*) as count, COUNT(DISTINCT task_name) as tasks
            FROM mistakes WHERE pattern IS NOT NULL AND pattern != ''
            GROUP BY pattern ORDER BY count DESC LIMIT 20
        """).fetchall()
        return [dict(r) for r in rows]

    # ── 经验库 ────────────────────────────────────────────────────

    def _auto_experience(self, task_name: str, content: str, process_id: str):
        """成功结论自动沉淀经验库（ExpeL 式：成功路径提取复用）"""
        experience_id = gen_experience_id(task_name)
        # 查重：相同任务已有经验则更新计数
        existing = self.db.conn.execute(
            "SELECT experience_id, source_count FROM experiences WHERE task_name = ? AND content = ?",
            (task_name, content)
        ).fetchone()
        if existing:
            self.db.conn.execute("""
                UPDATE experiences SET source_count = source_count + 1, updated_at = ?
                WHERE experience_id = ?
            """, (now_iso(), existing["experience_id"]))
            self.db.conn.commit()
            return {"experience_id": existing["experience_id"], "deduped": True}

        now = now_iso()
        self.db.conn.execute("""
            INSERT INTO experiences (experience_id, task_name, content, mem_type,
            layer, confidence, source_count, tags, ref_process_ids, created_at, updated_at, session_id)
            VALUES (?, ?, ?, 'pattern', '法', 0.6, 1, '[]', ?, ?, ?, ?)
        """, (experience_id, task_name, content,
              json.dumps([process_id], ensure_ascii=False), now, now, self.session_id))
        self.db.conn.commit()
        self.db.log_event(self.session_id, "experience_recorded",
                          {"experience_id": experience_id, "task_name": task_name},
                          scope="进化")
        return {"experience_id": experience_id, "deduped": False}

    def list_experiences(self, task_name: str = None, limit: int = 50) -> List[dict]:
        """经验库查询"""
        sql = "SELECT * FROM experiences WHERE 1=1"
        params = []
        if task_name:
            sql += " AND task_name = ?"
            params.append(task_name)
        sql += " ORDER BY confidence DESC, created_at DESC LIMIT ?"
        params.append(limit)
        rows = self.db.conn.execute(sql, params).fetchall()
        return [dict(r, tags=json.loads(r["tags"] or "[]"),
                     ref_process_ids=json.loads(r["ref_process_ids"] or "[]")) for r in rows]

    # ── 工具方法 ──────────────────────────────────────────────────

    def _extract_pattern(self, content: str) -> str:
        """从失败内容提取模式 slug（reflect 式确定性模式提取）"""
        # 规则 1：常见中文错误模式
        zh_patterns = [
            ("超时", "timeout"),
            ("权限", "permission"),
            ("不存在", "not_found"),
            ("失败", "failed"),
            ("冲突", "conflict"),
            ("空", "empty"),
            ("重复", "duplicate"),
            ("溢出", "overflow"),
            ("异常", "exception"),
            ("拒绝", "denied"),
            ("无效", "invalid"),
        ]
        for kw, slug in zh_patterns:
            if kw in content:
                return slug
        # 规则 2：英文关键词
        en_patterns = [
            ("error", "error"), ("timeout", "timeout"), ("denied", "denied"),
            ("failed", "failed"), ("exception", "exception"), ("null", "null"),
            ("undefined", "undefined"), ("404", "not_found"), ("500", "server_error"),
        ]
        for kw, slug in en_patterns:
            if kw.lower() in content.lower():
                return slug
        # 规则 3：兜底 — 内容哈希
        return f"pattern_{hashlib.sha256(content.encode('utf-8')).hexdigest()[:6]}"

    def self_check(self) -> dict:
        """过程记忆模块自检"""
        counts = {
            "process_events": self.db.conn.execute("SELECT COUNT(*) FROM process_events").fetchone()[0],
            "processes": self.db.conn.execute("SELECT COUNT(DISTINCT process_id) FROM process_events").fetchone()[0],
            "mistakes": self.db.conn.execute("SELECT COUNT(*) FROM mistakes").fetchone()[0],
            "experiences": self.db.conn.execute("SELECT COUNT(*) FROM experiences").fetchone()[0],
            "anchors": self.db.conn.execute("SELECT COUNT(*) FROM task_checkpoints WHERE phase LIKE '%锚点%'").fetchone()[0],
        }
        counts["error_patterns"] = len(self.get_error_patterns())
        return counts
