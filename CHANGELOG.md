# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/) 与 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

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
