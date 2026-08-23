# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/) 与 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

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
