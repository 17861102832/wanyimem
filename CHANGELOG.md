# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/) 与 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [1.0.4] - 2026-08-24

### Added（向量大规模检索提速 — sqlite-vec 轻量 ANN）

- **混合检索策略**：`vector_memory.py` 升级为「small 精确 / large ANN」双路径。
  - 记忆规模 < `ANN_MIN_COUNT`（默认 2000）→ 全表精确余弦（正确性优先，量级小够用）。
  - 规模 ≥ 阈值且 `sqlite-vec` 可用 → `vec0` 近似最近邻**预筛**（`k = limit*3+5`）+ 用完整 embedding **精确重排**（既提速又保准）。
  - `sqlite-vec` 未安装 → 自动回退纯精确，**完全向后兼容**。
- **可选依赖**：新增 `wanyimem[ann]`（`sqlite-vec>=0.1.6`），并并入 `wanyimem[all]`。
- **正确性保障**：`memory_embeddings` 仍是权威真值表（精确通道始终可用）；vec0 只是影子索引。换模型/维度变化时自动重建 vec0 表并从权威表重灌当前维度向量，维度不匹配的旧向量不进 ANN（精确不受影响）。
- **测试**：新增 `tests/test_vector_ann.py`（3 个用例，伪向量 monkeypatch，无需模型/网络；sqlite-vec 缺失时仅跳过 ANN 断言），现有 13 个冒烟用例全部通过（合计 16 passed）。

> 回应社区对「向量全表载入内存暴力检索」的顾虑：wanyimem 默认小规模用精确、大规模用 ANN 预筛+精确重排，兼顾召回质量与扩展性。

## [1.0.3] - 2026-08-23

### Fixed（记忆图谱"记录→查询"恒为空 — 实弹功能验证发现）

- **图谱挂接缺一环**：`auto_graph_link()` 只创建了 `graph_nodes`（记忆节点）+ `graph_edges`（语义/同类边），却**没有把记忆挂接到它自己的节点**（`memory_node_links`）。而 `tool_graph_search` 恰恰靠 `memory_node_links` JOIN 取记忆——对用户来说效果是「记录了几条记忆，搜图谱永远返回 0」，被外部跑分误判为"图谱能力不足/需向量积累"。修复：建节点后即 `link_memory_to_node(memory_id, self_id)`，让「记录→查图谱」立刻可用。
- **回归测试**：新增 `test_graph_search_after_record`，锁定该路径。

### Benchmark（首次公开可复现实测数据）

用可控、可重复的迷你 LongMemEval 评测脚本替换 README 里未经实测的 "Recall@5=90%"（`benchmark/recall_benchmark.py`）。14 条查询全部刻意用与答案**不同关键词**的表述，逼出真实语义召回：

| 版本 | Recall@5 | MRR |
|---|---|---|
| 核心版（BM25 + 知识图谱，无模型） | **1.000** (14/14) | **0.857** |
| 完整版（bge-small-zh 向量 + bge-reranker-base 精排） | **1.000** (14/14) | **0.857** |

> 注：本次图谱挂接修复同时提升了核心版召回（MRR 0.845 → 0.857），使无模型的 BM25+图谱通道在此基准下与完整版持平；向量+精排的优势在更大规模语义扩展场景才更显著。

- 修复基准脚本 2 处自身缺陷：初始 ground truth `诚实承认不知道` 不是任何事实的子串（该题永不可命中）；逐题明细误用 `len(contents)` 显示位次（恒为 top5），已改为真实命中位次。
- 完整版能在线加载（`embed ok dim=512, rerank score=[0.047]`），"pip install wanyimem[all]" 路径真实可用。

### Tests（13 通过 / 新增 1）

- 新增 `test_graph_search_after_record`：记录带 category 的记忆后用内容关键词搜图谱，断言至少命中 1 条。

## [1.0.2] - 2026-08-23

### Fixed（召回诚实性 — 实弹跑分反馈）

- **无匹配的非空查询不再硬凑结果**：`recall()` 原兜底路径不论输入是「空查询」还是「完全无关的非空查询」都返回最近记忆并标记 `_fallback`，导致无关查询（如 `xyzabc`）也返回 5 条假关联结果、误导用户。已区分两者——**空查询**（`hook_load` 道/法级注入用）仍按时间倒序返回 `_fallback` 记忆；**无匹配的非空查询**诚实返回空列表并触发知识空白（"绝不硬凑答案"的元认知理念落地）。
- **工具数量核实**：实测 MCP 协议 `tools/list` 返回 **23 个工具**，且 23 个全部能映射到 handler（无 "Tool not found"）。此前一份外部跑分报告称"实际 21 个"系误判（读的可能是旧插件版代码）。

### Tests（12 通过）

- 强化 `test_knowledge_gap`：无关查询必须返回 0 条真实命中 + 记录知识空白（回归验证 recall 兜底诚实性）

## [1.0.1] - 2026-08-23

### Changed（可移植性增强 + 文档同步）

- **环境变量兼容层**：新增 `env_compat.py`，所有配置项支持「中文优先、英文兜底」双 key。旧中文 key（`万忆中枢_STORE_DIR`）完全兼容，新增 ASCII 别名（`WANYI_STORE_DIR` / `WANYI_MEMORY_DB` / `WANYI_USER_PROFILE` / `WANYI_TRADING_ANCHOR` / `WANYI_INDEX` / `WANYI_SKILL_DIR` / `WANYI_PROJECT_CONTEXT` / `WANYI_EMBED_MODEL` / `WANYI_RERANK_MODEL`），提升跨平台/CI/客户端兼容性，不破坏任何现有配置
- **文档更新**：`README.md` / `README.zh-CN.md` / `docs/INSTALL_CN.md` / `examples/mcp.example.json` 同步改用推荐的新写法，并补充「绝对路径解释器 / `wanyi` console 入口」更稳的启动方式说明

### Fixed（4 处真实 bug + 1 处参数未生效，全量审查第三轮）

- **`gardener.arbitrate_conflict` UnboundLocalError（Warning）**：`verdict` 只在 `if hasattr(self.db, "confidence"):` 为 True 的分支赋值。当 `Gardener` 用未挂载 `confidence` 的裸 db 实例化时，第 109/112 行引用未赋值变量抛 `UnboundLocalError`。已加默认兜底值 `verdict = "conflict_unresolved"`。
- **`confidence.needs_review` 时区偏差（Warning）**：`last_updated` 由 `now_iso()`（本地、无时区）写入，但 SQL 用 `julianday('now')`（UTC）比较，导致中国时区**复习到期判定系统性偏晚约 8 小时**。比较端已改用 `julianday('now','localtime')` 对齐（不改写入格式，避免影响所有时间戳）。
- **记忆锚点恢复丢失 `process_id`（Info）**：只传 `anchor_id` 调 `restore_from_anchor` 时，因 `set_anchor` 未把 `process_id` 存入 checkpoint state，导致返回 `process_id=None`、`completed_phases` 恒空。`set_anchor` 的 state 已补存 `process_id`，恢复时优先从 state 取回。
- **自检 `contradiction_candidates` 恒为 0（Info，静默失效）**：`self_check` 传空字符串 `""` 给 `detect_contradictions`，因该函数先检查否定词、空串恒 `[]`，导致该自检指标永远为 0。已改为实际巡检近期 30 条含否定词记忆。
- **`recall` 的 `min_confidence` 参数从未生效**：空查询兜底路径（`hook_load` 道/法级注入走的正是这条）不按置信度过滤，导致 `min_confidence=0.5/0.6` 形同虚设。兜底路径已补按 `min_confidence` 过滤。

### Tests（9 → 12）

- 新增 `test_restore_anchor_recovers_process_id`（锚点恢复 process_id 回归）
- 新增 `test_arbitrate_conflict_no_unbound_local`（矛盾仲裁不抛 UnboundLocalError 回归）
- 新增 `test_min_confidence_fallback_filter`（空查询兜底按置信度过滤回归）

## [1.0.0] - 2026-08-22

### Added（首发全量功能，源自内部 v5.0 五轮迭代）

- **事件溯源记忆**：append-only WAL 为唯一事实源，永不删除，衰减只影响检索排序
- **过程记忆**：自动沉淀会话过程中的决策、模式、教训与经验
- **错题本**：高风险决策（全仓梭哈/追涨/不止损/删库/强推）自动记录为错题
- **置信度决策拦截**：模型/向量不可用时静默降级；高风险动作触发置信度检查，BLOCK/CAUTION 时自动开立反事实平行分支
- **跨域类比桥接**：跨领域教训互相提醒（gotcha）
- **决策轨迹回放**：决策生涯一眼回放、定期复盘
- **主动搭档**：自动简报 / 体检 / 周复盘，不等用户开口
- **语义召回**：BM25 关键词 + 本地中文向量（BAAI/bge-small-zh-v1.5）+ reranker 精排（BAAI/bge-reranker-base）+ 记忆关系图谱 + 时序衰减，四通道混合
- **元认知知识空白**：召回弱时诚实承认并记录知识空白，不硬凑答案
- **园艺师后台**：记忆整合、去重、夜间巩固
- **23 个 MCP 工具**：所有聊天框全局可用，`python -m wanyi.memory_core` 一键启动

### Security

- 本地优先：数据默认不出机器；`.gitignore` 红线排除记忆库/数据库/密钥
- Secret scanning / Push protection 已开启

### CI

- GitHub Actions：ruff lint + pytest × Python 3.10/3.11/3.12 全绿
- PyPI 自动发布 workflow（trusted publishing）就绪
