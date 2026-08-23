# WanYi Memory Core 万忆中枢

**永不遗忘的全量记忆系统** — Event-sourced long-term memory for AI agents: process memory, mistake books, experience crystallization, confidence-based decision blocking, counterfactual branches, cross-domain analogy, trajectory replay, proactive partner, semantic vector retrieval, reranker, memory graph, time decay and metacognitive knowledge-gaps. Ships as a local-first MCP server with 23 tools. Your data never leaves your machine.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![License](https://img.shields.io/badge/License-MIT-green)
![Version](https://img.shields.io/badge/version-1.0.3-orange)
![MCP](https://img.shields.io/badge/MCP-server-purple)
[![CI](https://github.com/17861102832/wanyimem/actions/workflows/ci.yml/badge.svg)](https://github.com/17861102832/wanyimem/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/wanyimem)](https://pypi.org/project/wanyimem/)
[![Live Demo](https://img.shields.io/badge/Live-Demo-00d4aa)](https://cdn.jsdelivr.net/gh/17861102832/wanyimem@main/docs/demo.html)

> 🎬 **Live Demo**: [交互式演示页](https://cdn.jsdelivr.net/gh/17861102832/wanyimem@main/docs/demo.html) · [源码 `docs/demo.html`](https://github.com/17861102832/wanyimem/blob/main/docs/demo.html)

---

## Why this is different

Most memory systems store your data in the cloud, need a heavy dependency stack, or only do keyword
search. **wanyimem is local-first, single-file SQLite, and installs with one dependency (numpy).**

| | wanyimem | typical memory server |
|---|---|---|
| Data | **never leaves your machine** (zero telemetry) | cloud / SaaS |
| Infra | **SQLite single file**, no separate vector DB | Qdrant / Neo4j / Postgres |
| Defaults | **shadows the agent**, blocks high-risk actions, opens counterfactual branches | stores & retrieves |
| Resources | **runs on 2-core / 2GB** | heavier |
| Evolves | **zero-participation** (learns from your mistakes automatically) | manual "remember this" |

**23 MCP tools, open source (MIT), Python 3.10+, `pip install wanyimem`.**

---

## Why

LLM agents forget. Every chat window is amnesia: preferences, lessons, and hard-won experience evaporate when the session ends.

WanYi Memory Core is a **local-first, full-quantity, self-evolving memory system**:

- **Event sourcing** — an append-only WAL is the single source of truth. Nothing is ever deleted; decay only affects retrieval ranking.
- **Semantic recall** — hybrid retrieval: BM25 keywords + local Chinese embedding (BAAI/bge-small-zh-v1.5) + reranker (BAAI/bge-reranker-base) + knowledge-graph expansion + explicit time decay.
- **Metacognition** — when recall is weak, the system admits it and records a knowledge-gap instead of hallucinating an answer.
- **Decision guardrails** — high-risk actions (all-in, revenge-trading, force-push, rm -rf) trigger confidence-based blocking with counterfactual branches: you see what would have happened *if you had listened*.
- **Zero-participation evolution** — no need to say "remember this"; the system decides what to store, consolidates overnight, and surfaces weekly trajectory reviews.

## Install

```bash
pip install wanyimem            # core
pip install "wanyimem[all]"     # + vector & reranker models deps
```

Requires Python 3.10+. Models (embedding ~95MB, reranker ~1.1GB) are downloaded on first use from HuggingFace; set `HF_ENDPOINT=https://hf-mirror.com` if you are in mainland China.

> Before the PyPI release lands, you can also install directly from GitHub (identical code):
>
> ```bash
> pip install "git+https://github.com/17861102832/wanyimem.git"
> ```

## Quick Start (MCP)

Add to your `mcp.json` (Claude Desktop, Cursor, Trae, etc.):

```json
{
  "mcpServers": {
    "wanyi": {
      "command": "python",
      "args": ["-m", "wanyi.memory_core"],
      "env": {
        "WANYI_STORE_DIR": "C:/path/to/your/memory"
      }
    }
  }
}
```

> Env keys are "Chinese-first, ASCII-fallback": the new `WANYI_STORE_DIR` (recommended, more portable) and the legacy `万忆中枢_STORE_DIR` both work. Bare `python` depends on PATH and may fail; prefer an absolute interpreter path, or `pip install wanyimem` then use `"command": "wanyi"`.

Then any agent can call the 23 tools, e.g.:

```text
万忆记录见闻 → "2026年5月基金大跌时我死扛不止损，亏了18%才割肉。"
万忆召回记忆 → query "认赔离场到底对不对"   # semantic match even with zero shared keywords
万忆置信度决策检查 → "我要全仓梭哈"          # BLOCK if confidence is low, with historical mistakes
```

## Quick Start (Library)

```python
from wanyi import WanYiCore

engine = WanYiCore()
engine.tool_record_memory(
    content="止损纪律：亏损超过8%必须无条件卖出",
    layer="法", mem_type="principle",
)
resp = engine.tool_recall_memory("认赔离场到底对不对", limit=5)
for m in resp["memories"]:
    print(m["content"], m.get("_rerank_score"))
```

## Features

| Area | Capability |
|---|---|
| Storage | SQLite + append-only event WAL; 道/法/术 three-layer half-lives |
| Retrieval | Keyword BM25 + vector (bge-small-zh) + reranker (bge-reranker-base) + graph expansion + time-decay fields |
| Metacognition | knowledge-gap auto-record, `stats` self-check, honest "I don't know" |
| Guardrails | confidence-based decision blocking, counterfactual branches with auto-settlement, cross-domain analogy bridging |
| Proactivity | daily brief on LOAD, due-branch reminders, weekly trajectory replay, risk-keyword alert |
| Growth | mistake book, experience crystallization, overnight consolidation, evolution queries |
| Privacy | fully local, zero telemetry, no cloud dependency |

Benchmark — reproducible mini LongMemEval (14 keyword-mismatched cross-session fact queries, run via `python benchmark/recall_benchmark.py`):

| Version | Recall@5 | MRR |
|---|---|---|
| Core (keyword BM25 + knowledge-graph, no models) | **1.000** (14/14) | **0.857** |
| Full (bge-small-zh vector + bge-reranker-base rerank) | **1.000** (14/14) | **0.857** |

Every query is intentionally phrased with *different keywords* than its answer (e.g. `本地数据库怎么提高并发写` → `WAL模式`, `记忆系统最怕什么` → `事件溯源`), so 14/14 reflects genuine **semantic** recall, not string matching. The knowledge-graph channel (active in the core, model-free) already lifts BM25 to parity here; the vector + reranker path shows its edge on larger-scale semantic expansion ("pip install wanyimem[all]" downloads the models).

## Docs

- [中文安装与使用指南](docs/INSTALL_CN.md)
- [README 中文版](README.zh-CN.md)
- [示例 MCP 配置](examples/mcp.example.json)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Report vulnerabilities privately via [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE) © 2026 Zhao Xikun
