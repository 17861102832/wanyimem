# WanYi Memory Core 万忆中枢

**永不遗忘的全量记忆系统** — Event-sourced long-term memory for AI agents: process memory, mistake books, experience crystallization, confidence-based decision blocking, counterfactual branches, cross-domain analogy, trajectory replay, proactive partner, semantic vector retrieval, reranker, memory graph, time decay and metacognitive knowledge-gaps. Ships as a local-first MCP server with 23 tools. Your data never leaves your machine.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![License](https://img.shields.io/badge/License-MIT-green)
![Version](https://img.shields.io/badge/version-1.0.0-orange)
![MCP](https://img.shields.io/badge/MCP-server-purple)

---

## Why

LLM agents forget. Every chat window is amnesia: preferences, lessons, and hard-won experience evaporate when the session ends. Existing memory systems either store in the cloud (privacy risk), require heavy infrastructure, or only do keyword search (missing semantic recall).

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

## Quick Start (MCP)

Add to your `mcp.json` (Claude Desktop, Cursor, Trae, etc.):

```json
{
  "mcpServers": {
    "wanyi": {
      "command": "python",
      "args": ["-m", "wanyi.memory_core"],
      "env": {
        "万忆中枢_STORE_DIR": "C:/path/to/your/memory"
      }
    }
  }
}
```

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

Benchmark (mini LongMemEval, cross-session fact recall, 10 cases): **Recall@5 = 90%, MRR = 0.900**.

## Docs

- [中文安装与使用指南](docs/INSTALL_CN.md)
- [README 中文版](README.zh-CN.md)
- [示例 MCP 配置](examples/mcp.example.json)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Report vulnerabilities privately via [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE) © 2026 Zhao Xikun
