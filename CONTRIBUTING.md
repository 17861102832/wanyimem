# Contributing

感谢你愿意为万忆中枢添砖加瓦！

## 环境准备

```bash
git clone https://github.com/zhaoxikun/wanyi-memory-core
cd wanyi-memory-core
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[test]"
```

## 测试

```bash
pytest tests/ -v
```

测试被设计为**无模型环境也能通过**（向量/精排自动降级），CI 中同样如此。

## 分支与 PR

- 主分支 `main`，功能分支命名 `feat/xxx`、修复 `fix/xxx`
- PR 标题遵循 Conventional Commits：`feat: 新增xxx` / `fix: 修复xxx`
- 合并前必须通过 CI（lint + test）

## 什么贡献欢迎

- 新的记忆工具（MCP tool），尤其是有认知科学依据的
- 检索质量改进（reranker 调参、混合权重、基准扩充）
- 更多语言的支持（目前中文优先，向量模型为 bge-small-zh）
- 文档与示例

## 什么不接受

- 引入云端依赖或遥测（项目核心承诺：全本地、零遥测）
- 破坏 append-only 事件溯源原则的"删除"功能
- 未经基准验证的"性能提升"
