# 万忆中枢·全量之心 (WanYi Memory Core)

**永不遗忘的全量记忆系统** — 为 AI 智能体打造的事件溯源长期记忆：过程记忆、错题本、经验结晶、置信度决策拦截、反事实平行分支、跨域类比桥接、轨迹回放、主动搭档、语义向量检索、reranker 精排、记忆图谱、时序衰减、元认知知识空白。本地优先的 MCP Server，23 个工具开箱即用。**你的数据永远不出你的电脑。**

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![License](https://img.shields.io/badge/License-MIT-green)
![Version](https://img.shields.io/badge/version-1.0.3-orange)
![MCP](https://img.shields.io/badge/MCP-server-purple)
[![CI](https://github.com/17861102832/wanyimem/actions/workflows/ci.yml/badge.svg)](https://github.com/17861102832/wanyimem/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/wanyimem)](https://pypi.org/project/wanyimem/)
[![Live Demo](https://img.shields.io/badge/Live-Demo-00d4aa)](https://cdn.jsdelivr.net/gh/17861102832/wanyimem@main/docs/demo.html)

> 🎬 **在线演示（Live Demo）**：[交互式演示页](https://cdn.jsdelivr.net/gh/17861102832/wanyimem@main/docs/demo.html) · [源码 `docs/demo.html`](https://github.com/17861102832/wanyimem/blob/main/docs/demo.html)

---

## 为什么做这个

大模型的记忆是"失忆"的：换一个聊天框，偏好、教训、经验全部蒸发。市面上的记忆系统要么存云端（隐私风险）、要么要重基础设施、要么只有关键词检索（语义召回缺失）。

万忆中枢是**本地优先、全量存储、自动进化**的记忆系统：

- **事件溯源** — append-only WAL 是唯一真相源，永不删除；衰减只影响检索排序
- **语义召回** — BM25 关键词 + 本地中文向量模型（BAAI/bge-small-zh-v1.5）+ reranker 精排（BAAI/bge-reranker-base）+ 知识图谱扩展 + 显性时序衰减，四通道混合。其中向量检索本身也是**混合**的：低于 `ANN_MIN_COUNT` 走全表精确余弦，超过则用 `sqlite-vec` 最近邻**预筛**+精确重排——规模化下既提速又不牺牲召回质量。
- **元认知** — 召回结果弱时系统诚实承认并记录知识空白，绝不硬凑答案
- **决策护栏** — 高风险动作（全仓梭哈/追涨/不止损/删库/强推）触发置信度拦截 + 自动开立反事实分支：让你亲眼看见"如果当时听劝会怎样"
- **零参与进化** — 不用喊"记住这个"，系统自动判断该存什么、夜间巩固、每周轨迹回放

## 安装

```bash
pip install wanyimem            # 核心
pip install "wanyimem[all]"     # 含向量 & 精排模型 + sqlite-vec ANN（仅要 ANN 用 [ann]）
```

需要 Python 3.10+。模型（向量 ~95MB、精排 ~1.1GB）首次使用时自动从 HuggingFace 下载；国内用户设置 `HF_ENDPOINT=https://hf-mirror.com` 走镜像。

> PyPI 版本发布前，也可以直接从 GitHub 安装（代码与 PyPI 包一致）：
>
> ```bash
> pip install "git+https://github.com/17861102832/wanyimem.git"
> ```

## 快速开始（MCP）

把以下配置加进你的 `mcp.json`（Claude Desktop / Cursor / Trae 等）：

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

> 环境变量 key 支持「中文优先、英文兜底」：新版用 `WANYI_STORE_DIR`（推荐，跳平台更稳），旧版中文名 `万忆中枢_STORE_DIR` 同样兼容。
> 裸 `python` 依赖 PATH 可能启动失败，建议用解释器绝对路径，或 `pip install wanyimem` 后直接用 `"command": "wanyi"`。

之后任意智能体都能调用 23 个工具：

```text
万忆记录见闻 → "2026年5月基金大跌时我死扛不止损，亏了18%才割肉。"
万忆召回记忆 → query "认赔离场到底对不对"   # 零关键词重合也能语义命中
万忆置信度决策检查 → "我要全仓梭哈"          # 置信度不足时 BLOCK + 亮历史错题
```

## 快速开始（Python 库）

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

## 能力清单

| 领域 | 能力 |
|---|---|
| 存储 | SQLite + append-only 事件日志；道/法/术三层半衰期 |
| 检索 | 关键词 BM25 + 向量（bge-small-zh）+ reranker 精排（bge-reranker-base）+ 图谱扩展 + 时序衰减字段 |
| 元认知 | 知识空白自动记录、stats 自检、"诚实承认不知道" |
| 护栏 | 置信度决策拦截、反事实分支自动开立与到期结算、跨域类比桥接 |
| 主动 | LOAD 自动生成今日简报、到期分支提醒、每周轨迹回放、风险关键词告警 |
| 进化 | 错题本、经验结晶、夜间睡眠巩固、进化查询 |
| 隐私 | 全本地运行、零遥测、无云端依赖 |

基准 — 可复现的迷你 LongMemEval（14 条「关键词刻意错开」的跨会话事实查询，运行 `python benchmark/recall_benchmark.py` 复现）：

| 版本 | Recall@5 | MRR |
|---|---|---|
| 核心版（仅 BM25 + 知识图谱，无模型） | **1.000** (14/14) | **0.857** |
| 完整版（bge-small-zh 向量 + bge-reranker-base 精排） | **1.000** (14/14) | **0.857** |

每个查询都故意用与答案**不同的关键词**表述（如 `本地数据库怎么提高并发写` → `WAL模式`、`记忆系统最怕什么` → `事件溯源`），因此 14/14 反映的是真正的**语义**召回，而非字符串匹配。知识图谱通道（核心版可用、无需模型）已把纯 BM25 拉平到此水平；向量 + 精排路径在更大规模的语义扩展场景才更显优势（"pip install wanyimem[all]" 下载模型后生效）。

## 文档

- [中文安装与使用指南](docs/INSTALL_CN.md)
- [示例 MCP 配置](examples/mcp.example.json)

## 贡献与安全

见 [CONTRIBUTING.md](CONTRIBUTING.md)。漏洞请通过 [SECURITY.md](SECURITY.md) 私密上报。

## 许可证

[MIT](LICENSE) © 2026 Zhao Xikun
