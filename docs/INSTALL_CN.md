# 中文安装与使用指南

## 环境要求

- Python 3.10+（推荐 3.12）
- Windows / macOS / Linux 均可

## 一、安装

```bash
pip install "wanyimem[all]"
```

`[all]` 会安装向量与精排所需的 `sentence-transformers`。仅想先试核心功能可以只装 `wanyimem`（无模型时自动降级为关键词检索，功能不崩）。

### 国内加速

模型默认从 HuggingFace 下载，国内可设置镜像：

```bash
# Windows PowerShell
$env:HF_ENDPOINT = "https://hf-mirror.com"
# macOS / Linux
export HF_ENDPOINT=https://hf-mirror.com
```

模型首次使用自动下载：向量模型 `BAAI/bge-small-zh-v1.5`（约 95MB），精排模型 `BAAI/bge-reranker-base`（约 1.1GB）。

## 二、接入 MCP

在客户端（Claude Desktop / Cursor / Trae / 任意 MCP 客户端）的 `mcp.json` 添加：

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

`WANYI_STORE_DIR` 是记忆库目录（SQLite + 事件日志），请务必指向**你自己的私有目录**，不要提交到任何仓库。

> **兼容旧写法**：环境变量 key 支持「中文优先、英文兜底」。既可用新推荐的 `WANYI_STORE_DIR`，也可用旧的中文名 `万忆中枢_STORE_DIR`，两者填任一个即可；都填时以中文为准。

> **启动命令建议**：裸 `python` 依赖 PATH，部分机器是 `python3` 或解释器不在 PATH，可能启动失败。更稳的两种方式：
> - 用解释器绝对路径。Windows 常见：`"command": "C:/Python312/python.exe"`
> - 先 `pip install wanyimem`，完成后直接用 console 入口 `"command": "wanyi"`

## 三、23 个工具速览

| 工具 | 用途 |
|---|---|
| 万忆触发LOAD钩子 | 会话启动注入历史记忆（第一动作） |
| 万忆记录见闻 | 写入记忆（自动同步语义向量 + 图谱建边） |
| 万忆召回记忆 | 四通道混合召回（关键词+向量+图谱+时序）+ reranker 精排 |
| 万忆置信度决策检查 | 高风险决策拦截（全仓/梭哈/删库等） |
| 万忆反事实之镜 | 反事实分支开立与到期结算 |
| 万忆跨域桥接 | 跨领域教训类比 |
| 万忆轨迹回放 | 决策生涯时间线复盘 |
| 万忆主动搭档 | 今日简报/主动体检/周复盘 |
| 万忆知识空白 | 元认知：查看/关闭知识空白 |
| 万忆过程存档 | 五阶段过程记忆 |
| 万忆错题本 / 万忆经验库 | 反例与成功模式 |
| ... | 共 23 个，`tools/list` 可查看全部 |

## 四、常见问题

**Q: 不装模型能用吗？** 能。向量/精排/图谱自动降级，仅关键词检索可用，不影响核心记忆功能。

**Q: 记忆存在哪？** 全部在本地 `万忆中枢_STORE_DIR` 下的 SQLite 文件中，零云端依赖、零遥测。

**Q: 模型下载慢/失败？** 设置 `HF_ENDPOINT=https://hf-mirror.com` 后重试。
