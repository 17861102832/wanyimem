#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║          万忆中枢 v4 — 认知置信度模块（confidence.py）          ║
║                                                                  ║
║  借鉴 KektorDB 三分量模型 + FSRS 稳定性曲线                      ║
║                                                                  ║
║  置信度 = 共识度(40%) + 稳定性(30%) + 摩擦度(30%)                ║
║  - 共识度 Consensus：被验证的次数（多源一致 → 高）               ║
║  - 稳定性 Stability：随时间/复习衰减，FSRS 间隔后恢复            ║
║  - 摩擦度 Friction：被质疑/矛盾次数（冲突 → 降置信）             ║
║                                                                  ║
║  只做检索排序和复习调度，绝不用于删除（全量存储不遗忘）           ║
╚══════════════════════════════════════════════════════════════════╝
"""
import json
import math
from datetime import datetime
from typing import List

# 三分量权重（KektorDB 公式）
W_CONSENSUS = 0.40
W_STABILITY = 0.30
W_FRICTION = 0.30

# FSRS 参数（简化版）
FSRS_RETENTION = 0.9          # 目标记忆保持率
FSRS_FIRST_INTERVAL = 1.0     # 首次复习间隔（天）


def now_iso() -> str:
    return datetime.now().isoformat()


class Confidence:
    """
    认知置信度管理器 — 挂在 WanYiCore 下（self.confidence）
    可作用于：记忆(memory) / 错题(mistake) / 经验(experience)
    """

    def __init__(self, db, session_id: str = "unknown"):
        self.db = db
        self.session_id = session_id

    # ── 核心计算 ──────────────────────────────────────────────────

    def compute(self, consensus: float, stability: float, friction: float) -> float:
        """三分量加权合成（KektorDB 公式）"""
        return max(0.0, min(1.0,
            W_CONSENSUS * consensus + W_STABILITY * stability + W_FRICTION * (1.0 - friction)))

    def fsrs_stability(self, s_prev: float, elapsed_days: float, recall_success: bool) -> float:
        """
        FSRS 稳定性更新：复习成功 → S 增长；间隔过久或失败 → S 衰减
        简化公式：S' = S * (1 + delta) 或 S * decay
        """
        if recall_success:
            # 成功复习：间隔增长系数（越久没复习越应该涨，前提是还记得）
            delta = min(1.5, elapsed_days / 7.0)
            return s_prev * (1.0 + delta)
        else:
            # 失败复习：稳定性骤降
            return s_prev * 0.5

    # ── 数据操作 ──────────────────────────────────────────────────

    def init_entry(self, target_type: str, target_id: str,
                   initial: float = 0.5) -> dict:
        """初始化一条置信度记录"""
        self.db.conn.execute("""
            INSERT OR IGNORE INTO confidence
            (target_type, target_id, consensus, stability, friction, confidence,
             validations, contradictions, last_updated, metadata)
            VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?, '{}')
        """, (target_type, target_id, initial, initial, initial,
              self.compute(initial, initial, initial), now_iso()))
        self.db.conn.commit()
        return self.get(target_type, target_id)

    def validate(self, target_type: str, target_id: str,
                 source: str = "user") -> dict:
        """
        验证一次（正面证据）：共识度 +，摩擦度 -，稳定性小升
        触发：用户确认、多源一致、实战成功
        """
        self.init_entry(target_type, target_id)
        row = self.db.conn.execute(
            "SELECT * FROM confidence WHERE target_type = ? AND target_id = ?",
            (target_type, target_id)
        ).fetchone()
        consensus = min(1.0, row["consensus"] + 0.15)
        friction = max(0.0, row["friction"] - 0.05)
        stability = min(1.0, row["stability"] + 0.05)
        validations = row["validations"] + 1
        final = self.compute(consensus, stability, friction)
        self._update(target_type, target_id, consensus, stability, friction,
                     final, validations, row["contradictions"],
                     {"last_action": "validate", "source": source})
        return self._emit("confidence_validated", target_type, target_id,
                          {"delta": round(final - row["confidence"], 3), "new": round(final, 3)})

    def challenge(self, target_type: str, target_id: str,
                  reason: str = "") -> dict:
        """
        质疑一次（反面证据）：摩擦度 +，共识度 -，稳定性小降
        触发：用户否定、矛盾证据、实战失败
        """
        self.init_entry(target_type, target_id)
        row = self.db.conn.execute(
            "SELECT * FROM confidence WHERE target_type = ? AND target_id = ?",
            (target_type, target_id)
        ).fetchone()
        consensus = max(0.0, row["consensus"] - 0.15)
        friction = min(1.0, row["friction"] + 0.20)
        stability = max(0.0, row["stability"] - 0.05)
        contradictions = row["contradictions"] + 1
        final = self.compute(consensus, stability, friction)
        self._update(target_type, target_id, consensus, stability, friction,
                     final, row["validations"], contradictions,
                     {"last_action": "challenge", "reason": reason})
        return self._emit("confidence_challenged", target_type, target_id,
                          {"delta": round(final - row["confidence"], 3), "new": round(final, 3)})

    def review(self, target_type: str, target_id: str,
               recall_success: bool, elapsed_days: float = 1.0) -> dict:
        """
        FSRS 复习调度：园艺师后台定时调用
        成功 → 稳定性涨 + 共识微涨；失败 → 稳定性降 + 摩擦微升
        """
        self.init_entry(target_type, target_id)
        row = self.db.conn.execute(
            "SELECT * FROM confidence WHERE target_type = ? AND target_id = ?",
            (target_type, target_id)
        ).fetchone()
        new_stability = self.fsrs_stability(row["stability"], elapsed_days, recall_success)
        if recall_success:
            consensus = min(1.0, row["consensus"] + 0.05)
            friction = row["friction"]
        else:
            consensus = row["consensus"]
            friction = min(1.0, row["friction"] + 0.10)
        final = self.compute(consensus, new_stability, friction)
        self._update(target_type, target_id, consensus, new_stability, friction,
                     final, row["validations"], row["contradictions"],
                     {"last_action": "review", "recall_success": recall_success,
                      "elapsed_days": elapsed_days})
        return self._emit("confidence_reviewed", target_type, target_id,
                          {"recall_success": recall_success, "new": round(final, 3)})

    def get(self, target_type: str, target_id: str) -> dict:
        row = self.db.conn.execute(
            "SELECT * FROM confidence WHERE target_type = ? AND target_id = ?",
            (target_type, target_id)
        ).fetchone()
        if not row:
            return {"target_type": target_type, "target_id": target_id,
                    "confidence": 0.5, "consensus": 0.5, "stability": 0.5,
                    "friction": 0.5, "validations": 0, "contradictions": 0,
                    "exists": False}
        d = dict(row)
        d["metadata"] = json.loads(d["metadata"] or "{}")
        d["exists"] = True
        return d

    def _update(self, target_type: str, target_id: str, consensus: float,
                stability: float, friction: float, final: float,
                validations: int, contradictions: int, metadata: dict):
        self.db.conn.execute("""
            UPDATE confidence SET consensus=?, stability=?, friction=?,
            confidence=?, validations=?, contradictions=?, last_updated=?, metadata=?
            WHERE target_type=? AND target_id=?
        """, (consensus, stability, friction, final, validations, contradictions,
              now_iso(), json.dumps(metadata, ensure_ascii=False),
              target_type, target_id))
        self.db.conn.commit()

    def _emit(self, event_type: str, target_type: str, target_id: str, data: dict) -> dict:
        self.db.log_event(self.session_id, event_type,
                          {"target_type": target_type, "target_id": target_id, **data},
                          scope="进化")
        return {"target_type": target_type, "target_id": target_id, **data}

    # ── 聚合查询 ──────────────────────────────────────────────────

    def rank_by_confidence(self, target_type: str, limit: int = 20) -> List[dict]:
        """按置信度排序（检索排序用，不删除）"""
        rows = self.db.conn.execute("""
            SELECT * FROM confidence WHERE target_type = ?
            ORDER BY confidence DESC LIMIT ?
        """, (target_type, limit)).fetchall()
        return [dict(r) for r in rows]

    def needs_review(self, target_type: str, min_age_days: float = 3.0,
                     limit: int = 20) -> List[dict]:
        """FSRS 到期复习队列（园艺师调用）"""
        rows = self.db.conn.execute("""
            SELECT * FROM confidence WHERE target_type = ?
            ORDER BY last_updated ASC LIMIT ?
        """, (target_type, limit)).fetchall()
        return [dict(r) for r in rows]

    def self_check(self) -> dict:
        return {
            "total": self.db.conn.execute("SELECT COUNT(*) FROM confidence").fetchone()[0],
            "high": self.db.conn.execute(
                "SELECT COUNT(*) FROM confidence WHERE confidence >= 0.7").fetchone()[0],
            "low": self.db.conn.execute(
                "SELECT COUNT(*) FROM confidence WHERE confidence <= 0.3").fetchone()[0],
        }
