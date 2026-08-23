"""
wanyimem × LongMemEval 公开记忆基准检索评测

用途：让 wanyimem 在公开、社区认可的 LongMemEval 上拿到「官方同口径」的
      session-level 检索召回指标（Recall@K / MRR），用于和 EverOS 等公开对拍。

数据：HuggingFace `xiaowu0162/longmemeval-cleaned`
      - longmemeval_oracle.json : 仅证据会话（最快验证）
      - longmemeval_s_cleaned.json : ~40 sessions / 115k tokens
      - longmemeval_m_cleaned.json : ~500 sessions（规模大）
     官方检索评测惯例：跳过 30 条 abstention 实例（question_id 以 _abs 结尾）。

口径：本脚本走「session 粒度」——把每条 turn 作为一条记忆写入，
      并在 content 前缀内嵌 `[[sid:xxx]]` 标记；召回后用正则还原 session，
      判断 `answer_session_ids`（证据会话）是否出现在 Top-K 命中的会话集合里。

用法：
    python benchmark/longmemeval_run.py --data longmemeval_s_cleaned.json --mode core --max-samples 100
    python benchmark/longmemeval_run.py --data longmemeval_s_cleaned.json --mode full --max-samples 100
    python benchmark/longmemeval_run.py --data longmemeval_oracle.json --mode full   # 全部（600 条含候选）
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

if not os.environ.get("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

DATA_DIR = Path(REPO) / "benchmark" / "_longmemeval_data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

HF_FILES = {
    "longmemeval_oracle.json": "longmemeval_oracle.json",
    "longmemeval_s_cleaned.json": "longmemeval_s_cleaned.json",
    "longmemeval_m_cleaned.json": "longmemeval_m_cleaned.json",
}
HF_BASE = "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main"


def _hf_base() -> str:
    ep = os.environ.get("HF_ENDPOINT", "https://huggingface.co").rstrip("/")
    return f"{ep}/datasets/xiaowu0162/longmemeval-cleaned/resolve/main"


def download(name: str) -> Path:
    """若本地无数据则从 HF（镜像）下载"""
    fp = DATA_DIR / name
    if fp.exists() and fp.stat().st_size > 1000:
        return fp
    url = f"{_hf_base()}/{HF_FILES[name]}"
    print(f"[download] {url}")
    import urllib.request
    urllib.request.urlretrieve(url, fp)
    return fp


def load_instances(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


SESSION_TAG = re.compile(r"\[\[sid:([^\]]+)\]\]")


def write_instance(eng, inst):
    """把一个实例的全部 haystack_sessions 按 turn 写入 wanyimem"""
    sid_to_mem = {}
    for si, sid in enumerate(inst.get("haystack_session_ids", [])):
        s = inst["haystack_sessions"][si]
        for turn in s:
            role = turn.get("role", "user")
            content = turn.get("content", "")
            if not content:
                continue
            tagged = f"[[sid:{sid}]] {role}: {content}"
            eng.tool_record_memory(content=tagged, layer="法", mem_type="turn")
            sid_to_mem.setdefault(sid, 0)
    return sid_to_mem


def recall_sessions(eng, question, k=5):
    resp = eng.tool_recall_memory(question, limit=k)
    mems = resp.get("memories", []) or resp.get("results", [])
    hit_sids = []
    for m in mems:
        c = m.get("content", "")
        m2 = SESSION_TAG.search(c)
        if m2:
            hit_sids.append(m2.group(1))
    return hit_sids


def evaluate(eng, instances, max_samples=None, k=5, skip_abstention=True):
    rr_sum = 0.0
    hits = 0
    n = 0
    lat = []
    detailed = []
    for inst in instances:
        qid = inst.get("question_id", "")
        if skip_abstention and qid.endswith("_abs"):
            continue
        if max_samples and n >= max_samples:
            break
        answer_sids = set(inst.get("answer_session_ids", []))
        if not answer_sids:
            continue
        t0 = time.time()
        write_instance(eng, inst)
        hit_sids = recall_sessions(eng, inst.get("question", ""), k=k)
        lat.append((time.time() - t0))
        # 命中：任一证据会话出现在 top-K 命中的会话集合里
        rec = set(hit_sids)
        if rec & answer_sids:
            hits += 1
            # MRR：第一个被命中的证据会话的排名
            rank = -1
            for i, sid in enumerate(hit_sids):
                if sid in answer_sids:
                    rank = i + 1
                    break
            rr_sum += 1.0 / rank if rank > 0 else 0
        n += 1
        detailed.append((qid, inst.get("question", "")[:40], bool(rec & answer_sids)))
    recall = hits / n if n else 0.0
    mrr = rr_sum / n if n else 0.0
    avg_lat = sum(lat) / len(lat) if lat else 0.0
    return {"n": n, "recall@k": recall, "mrr": mrr, "hits": hits,
            "avg_write_recall_s": avg_lat, "detailed": detailed}


def build_engine(mode):
    if mode == "core":
        os.environ["WANYI_EMBED_MODEL"] = "this/model/does/not/exist"
        os.environ["WANYI_RERANK_MODEL"] = "this/model/does/not/exist"
    else:
        # 公开英文基准：用多语言模型（中英通吃）才能公平
        os.environ.setdefault("WANYI_EMBED_MODEL", "BAAI/bge-m3")
        os.environ.setdefault("WANYI_RERANK_MODEL", "BAAI/bge-reranker-v2-m3")
    from wanyi.memory_core import WanYiCore
    eng = WanYiCore(db_path=":memory:")
    if mode == "core":
        import wanyi.vector_memory as vm
        import wanyi.reranker as rr
        vm._model_ok = False; vm._model_instance = None
        rr._model_ok = False; rr._model_instance = None
    return eng


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="longmemeval_s_cleaned.json",
                    choices=list(HF_FILES.keys()))
    ap.add_argument("--mode", choices=["core", "full"], default="full")
    ap.add_argument("--max-samples", type=int, default=None)
    ap.add_argument("--k", type=int, default=5,
                    help="Top-K；调 10 / 20 看 Recall@K 曲线")
    args = ap.parse_args()

    path = download(args.data)
    instances = load_instances(path)
    print(f"[data] {path.name} | 实例数 {len(instances)} | mode={args.mode} k={args.k}")

    eng = build_engine(args.mode)
    res = evaluate(eng, instances, max_samples=args.max_samples, k=args.k)
    print("\n=== LongMemEval 检索结果（session 粒度）===")
    print(f"  样本数 n   = {res['n']}")
    print(f"  Recall@{args.k} = {res['recall@k']:.4f}  ({res['hits']}/{res['n']})")
    print(f"  MRR        = {res['mrr']:.4f}")
    print(f"  平均写入+召回耗时 = {res['avg_write_recall_s']:.3f}s/条")
    print("  ---- 前 15 条明细 ----")
    for qid, q, ok in res["detailed"][:15]:
        print(f"    {'✅' if ok else '❌'} {qid:<40} {q!r}")


if __name__ == "__main__":
    main()
