"""
wanyimem 召回基准评测 — 迷你 LongMemEval（可重复、可控、不依赖外部数据集）

目的：产出真实、可复现的 Recall@5 与 MRR 数据，用于替代 README 里未经实测验证的
"Recall@5=90%"。每个查询刻意用「语义相近但关键词错开」的表述，逼出真正的语义召回，
而不是纯字符串匹配。

方法：
- 构造 15 条跨会话事实记忆集（模拟用户长期记忆）
- 14 个 query / ground-truth 对，query 与答案的关键词刻意错开
- 两种形态：
    core = 核心版（强制向量/reranker 不可用 → 纯 BM25 关键词）
    full = 完整版（bge-small-zh 向量检索 + bge-reranker-base 精排）
- Top-5 下计算：
    Recall@5 = ground truth 是否出现在前 5 条里（命中率）
    MRR      = 第一个 ground truth 的倒数排名

用法：
    python benchmark/recall_benchmark.py              # 全量（core + full，装模型较慢）
    python benchmark/recall_benchmark.py --mode core  # 只跑核心版（无需模型）
    python benchmark/recall_benchmark.py --mode full  # 只跑完整版
    python benchmark/recall_benchmark.py --no-full    # 跳过完整版（无模型环境用）
"""
import argparse
import os
import sys
import time
from pathlib import Path

# 让 benchmark/ 下的脚本能 import 到项目包
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# 触发模型下载走 hf-mirror（国内可达）
if not os.environ.get("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"


# ── 可控事实记忆集（模拟用户跨会话积累的长期记忆） ─────────────────
# 每条：(content, layer, mem_type, category)。刻意让 query 与答案的
# 直接关键词不完全重叠，逼出「语义召回」而非纯字符串匹配。
FACTS = [
    ("止损纪律：单笔亏损超过8%必须无条件卖出，绝不追加", "法", "principle", "交易纪律"),
    ("我2021年追高新能源基金被套两年，教训是别在情绪高点追涨", "道", "principle", "交易纪律"),
    ("仓位管理：单只基金最多两成，同时最多持有5只", "法", "strategy", "交易纪律"),
    ("写小说开篇要用【黄金三行】：第一行抓眼球，第二行给悬念，第三行亮主角", "法", "strategy", "写作"),
    ("人物塑造不能只靠外貌，要写他做选择时的犹豫", "法", "principle", "写作"),
    ("Python asyncio 适合IO密集，CPU密集要用多进程或线程池", "法", "concept", "编程"),
    ("SQLite 的WAL模式能显著提升并发读写，适合本地单机工具", "法", "concept", "编程"),
    ("递归记忆：agent 的记忆系统要用事件溯源，append-only才不丢", "道", "principle", "架构"),
    ("知识空白：当系统不确定时就承认不知道，不要硬凑答案", "道", "principle", "元认知"),
    ("复盘时先看决策过程对不对，再看结果；不能只看输赢", "法", "principle", "交易纪律"),
    ("给AI喂错误示范比正确示范更有效，一次踩坑胜过十次说教", "法", "principle", "方法论"),
    ("买房和炒股都要先设好退出条件，再谈入场", "道", "principle", "决策"),
    ("跨域迁移：股市的止损失败教训，可以套用到任何高风险决策", "道", "principle", "元认知"),
    ("番茄小说的黄金三章：第一章悬念，第二章冲突，第三章亮金手指", "法", "strategy", "写作"),
    ("CPU密集任务用多进程，避免GIL限制；IO密集用asyncio", "法", "concept", "编程"),
]

# ── 查询 + 标准答案（标准答案为 FACTS 中的一段关键内容，用于判定命中） ──
QUERIES = [
    ("亏到多少就该及时止损", "亏损超过8%"),
    ("买基金最多能买几只", "最多持有5只"),
    ("小说开头怎么写才抓人", "黄金三行"),
    ("写角色要不要写他纠结", "做选择时的犹豫"),
    ("异步编程适合什么任务", "asyncio 适合IO密集"),
    ("本地数据库怎么提高并发写", "WAL模式"),
    ("记忆系统最怕什么", "事件溯源，append-only才不丢"),
    # 注意：ground-truth 必须是某条事实里的真实子串，否则该题永远无法命中（探针一致性）
    ("系统不知道答案时应该怎样", "当系统不确定时就承认不知道"),
    ("复盘该看什么", "决策过程"),
    ("怎么让AI学得更快", "一次踩坑胜过十次说教"),
    ("买房子前要先定什么", "退出条件"),
    ("股市的教训怎么用到别处", "跨域迁移"),
    ("创作时第一章要埋什么", "第一章悬念"),
    ("GIL对编程有什么影响", "多进程"),
]


def build_engine(mode: str = "full"):
    """构造引擎；core 模式强制向量/reranker 不可用"""
    if mode == "core":
        os.environ["WANYI_EMBED_MODEL"] = "this/model/does/not/exist"
        os.environ["WANYI_RERANK_MODEL"] = "this/model/does/not/exist"
    from wanyi.memory_core import WanYiCore

    eng = WanYiCore(db_path=":memory:")
    if mode == "core":
        # 强化：直接强制模块降级到关键词检索
        import wanyi.vector_memory as vm
        import wanyi.reranker as rr

        vm._model_ok = False
        vm._model_instance = None
        rr._model_ok = False
        rr._model_instance = None
    return eng


def load_facts(eng):
    for content, layer, mtype, cat in FACTS:
        eng.tool_record_memory(content=content, layer=layer, mem_type=mtype, category=cat)


def compute_metrics(eng, label: str):
    """跑所有查询，算 Recall@5 和 MRR"""
    hits = 0
    rr_sum = 0.0
    details = []
    for q, truth in QUERIES:
        resp = eng.tool_recall_memory(q, limit=5)
        mems = resp.get("memories", [])
        contents = [m.get("content", "") for m in mems]
        # 命中：Top-5 里任一记忆包含标准答案片段
        hit_pos = -1
        for i, c in enumerate(contents):
            if truth in c:
                hit_pos = i
                break
        if hit_pos >= 0:
            hits += 1
            rr_sum += 1.0 / (hit_pos + 1)
        # v1.1 修复：显示真实命中位次（1 起），未命中显示 0
        pos = hit_pos + 1 if hit_pos >= 0 else 0
        details.append((q, pos, truth[:14], hit_pos >= 0))
    n = len(QUERIES)
    return {
        "label": label,
        "n": n,
        "recall5": hits / n,
        "mrr": rr_sum / n,
        "hits": hits,
        "details": details,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["core", "full"], default=None)
    ap.add_argument("--no-full", action="store_true", help="跳过完整版（无模型环境用）")
    args = ap.parse_args()

    modes = []
    if args.mode:
        modes = [args.mode]
    else:
        modes = ["core"]
        if not args.no_full:
            modes.append("full")

    results = []
    for mode in modes:
        t0 = time.time()
        eng = build_engine(mode)
        load_facts(eng)
        m = compute_metrics(eng, mode)
        m["elapsed_s"] = round(time.time() - t0, 2)
        results.append(m)
        print(f"\n===== [{m['label']}] 共 {m['n']} 题，用时 {m['elapsed_s']}s =====")
        print(f"  Recall@5 = {m['recall5']:.3f}  ({m['hits']}/{m['n']})")
        print(f"  MRR      = {m['mrr']:.3f}")
        print("  ---- 逐题明细 (位次1=第1名) ----")
        for q, pos, t, ok in m["details"]:
            print(f"    {'✅' if ok else '❌'} top{pos:>2}  {q[:22]!r:<26} 答案:{t!r}")

    if len(results) == 2:
        c, f = results[0], results[1]
        print("\n================ 汇总对比 ================")
        print(f"  核心版 (BM25)   : Recall@5={c['recall5']:.3f}  MRR={c['mrr']:.3f}")
        print(f"  完整版 (向量+精排): Recall@5={f['recall5']:.3f}  MRR={f['mrr']:.3f}")
        print("  (完整版需 'pip install \"wanyimem[all]\"' 下载 ~1.2GB 模型)")


if __name__ == "__main__":
    main()
