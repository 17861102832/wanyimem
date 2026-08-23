"""
护城河全自动（AutoMoat） — 把"判断纠错护城河"从手动工具变成自动层（wanyimem 第 5 护城河）
==========================================================================================
- 反事实自动结算：settlement_date 已到且仍 open 的分支，若能从关联置信度目标推出实测结果则自动结算，
  否则**诚实**标记 expired（绝不编造赢家）——符合"召回诚实/不硬凑"的元认知理念。
- 自动巩固：睡眠巩固（衰减/增强/合并/归档）+ 园艺师深巩固（矛盾仲裁/技能结晶/每日档案）。
- 跨域类比巡检：把最近错题教训提醒为跨域模式桥接候选。
- 调度器：`AutoMoat.start(interval)` 后台线程，或 `wanyi-auto [--loop SECONDS]` CLI。
  默认不自动启动，避免把 MCP 服务器变成常驻守护；用环境变量 WANYI_AUTO_SCHEDULER=1 或显式调用开启。

用法：
    python -m wanyi.auto_moat --db memory.db
    python -m wanyi.auto_moat --db memory.db --loop 3600        # 每 1 小时跑一轮
"""
import argparse
import sys
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class AutoMoat:
    """护城河全自动编排器"""

    def __init__(self, db_path=None, session_id="auto_moat"):
        from env_compat import get_env
        if not db_path:
            db_path = get_env("万忆中枢_MEMORY_DB", "WANYI_MEMORY_DB", "memory.db")
        from wanyi.memory_core import WanYiCore
        self.db_path = Path(db_path)
        self.core = WanYiCore(db_path=str(self.db_path), session_id=session_id)

    # ── 反事实自动结算（诚实） ─────────────────────────────────
    def auto_settle_due(self, grace_days: int = 0) -> dict:
        """settlement_date 已到（含宽限期）且仍 open 的分支：
        有可推结果则自动结算，否则诚实标记 expired。"""
        conn = self.core.db.conn
        # 宽限期：settlement_date + grace_days 天之后仍没结果才自动处理（grace=0 即到期即处理）
        cutoff = (date.today() - timedelta(days=grace_days)).isoformat()
        rows = conn.execute(
            "SELECT * FROM counterfactual_branches WHERE verdict='open' AND settlement_date <= ? ORDER BY settlement_date ASC",
            (cutoff,),
        ).fetchall()
        rows = [dict(r) for r in rows]  # sqlite3.Row 不支持 .get，先转 dict
        settled, expired = [], []
        now = _now()
        for r in rows:
            bid = r["branch_id"]
            # 尝试从关联置信度目标推实测结果（若无则诚实过期）
            outcome = self._resolve_outcome(r.get("confidence_target_id"))
            if outcome:
                verdict = outcome
                lesson = f"自动结算：对照实测结果判定为 {verdict}"
                conn.execute(
                    "UPDATE counterfactual_branches SET verdict=?, settled_at=?, lesson_learned=?, updated_at=? WHERE branch_id=? AND verdict='open'",
                    (verdict, now, lesson, now, bid),
                )
                settled.append(bid)
            else:
                conn.execute(
                    "UPDATE counterfactual_branches SET verdict='expired', settled_at=?, lesson_learned=?, updated_at=? WHERE branch_id=? AND verdict='open'",
                    (now, "到期未回填实测结果，已诚实归档（避免悬而未决）", now, bid),
                )
                expired.append(bid)
        conn.commit()
        return {"settled": len(settled), "branch_ids_settled": settled,
                "expired": len(expired), "branch_ids_expired": expired}

    def _resolve_outcome(self, confidence_target_id):
        """从置信度检查目标推出实测结果；无数据返回 None（诚实过期）。
        target 以 _take 结尾通常表示"当时已采纳高危动作"→ 反事实(counter)成立；
        其它无明确数据一律 None。"""
        if not confidence_target_id:
            return
        return  # 当前无结构化实测数据，保持诚实过期；预留接入点

    # ── 自动巩固 ───────────────────────────────────────────────
    def consolidate(self) -> dict:
        sleep = {}
        gardener = {}
        try:
            sleep = self.core.db.sleep_consolidation()
        except Exception as e:
            sleep = {"error": str(e)}
        try:
            gardener = self.core.tool_gardener(action="consolidate")
        except Exception as e:
            gardener = {"error": str(e)}
        return {"sleep_consolidation": sleep, "gardener": gardener}

    # ── 跨域类比巡检 ───────────────────────────────────────────
    def bridge_analog(self, limit: int = 5) -> dict:
        """列出最该被跨域提醒的模式（按命中/置信降序），供主动搭档注入。"""
        rows = self.core.db.conn.execute(
            "SELECT * FROM analog_patterns ORDER BY hit_count DESC, confidence DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return {"count": len(rows), "patterns": [dict(r) for r in rows]}

    # ── 一轮自动 ───────────────────────────────────────────────
    def run_once(self) -> dict:
        """一轮护城河自动巡检：自动结算 → 自动巩固 → 跨域模式巡检。返回汇总。"""
        settle = self.auto_settle_due()
        cons = self.consolidate()
        analog = self.bridge_analog()
        gap_count = 0
        try:
            gap_count = self.core.db.conn.execute(
                "SELECT COUNT(*) c FROM knowledge_gaps"
            ).fetchone()["c"]
        except Exception:
            gap_count = 0
        return {
            "time": _now(),
            "auto_settle": settle,
            "consolidate": cons,
            "analog": analog,
            "knowledge_gaps": gap_count,
        }

    def close(self):
        try:
            self.core.db.conn.close()
        except Exception:
            pass


def periodic_loop(db_path, interval, stop_event):
    """后台调度线程体：每 interval 秒跑一轮 AutoMoat.run_once，日志走 stderr。"""
    while not stop_event.is_set():
        am = None
        try:
            am = AutoMoat(db_path=db_path)
            report = am.run_once()
            sys.stderr.write(f"[wanyi-auto] {_now()} 自动巡检: "
                             f"结算过期{report['auto_settle']['settled']+report['auto_settle']['expired']}条, "
                             f"知识空白{report['knowledge_gaps']}个\n")
            sys.stderr.flush()
        except Exception as e:
            sys.stderr.write(f"[wanyi-auto] 巡检失败: {e}\n")
            sys.stderr.flush()
        finally:
            if am:
                try:
                    am.close()
                except Exception:
                    pass
        stop_event.wait(interval)


def main(argv=None):
    ap = argparse.ArgumentParser(description="wanyimem 护城河全自动巡检")
    ap.add_argument("--db", default=None, help="数据库路径（默认取 WANYI_MEMORY_DB / 万忆中枢_MEMORY_DB）")
    ap.add_argument("--loop", type=int, default=0, help="若>0，按该秒数周期巡检（调度器）；否则只跑一轮")
    ap.add_argument("--once", action="store_true", help="只跑一轮（默认）")
    args = ap.parse_args(argv)

    if args.loop and args.loop > 0:
        stop = threading.Event()
        th = threading.Thread(target=periodic_loop, args=(args.db, args.loop, stop), daemon=True)
        th.start()
        sys.stderr.write(f"[wanyi-auto] 调度器已启动，每 {args.loop}s 巡检一轮（Ctrl+C 退出）\n")
        sys.stderr.flush()
        try:
            while th.is_alive():
                time.sleep(1)
        except KeyboardInterrupt:
            stop.set()
        return 0

    am = AutoMoat(db_path=args.db)
    try:
        report = am.run_once()
    finally:
        am.close()
    import json
    sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
