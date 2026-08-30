"""
万忆中枢·全量之心 (WanYi Memory Core)
永不遗忘的全量记忆系统 — 事件溯源 + 过程记忆 + 语义向量 + 精排 + 图谱 + 元认知

对外暴露 23 个 MCP 工具，同时可作为 Python 库直接调用核心引擎。
"""
import os
import sys

# 包内模块使用同目录绝对导入（from process_memory import ...），
# 这里把包目录加入 sys.path，保证 `import wanyi` 与 `python -m wanyi.memory_core` 都能解析。
if os.path.dirname(__file__) not in sys.path:
    sys.path.insert(0, os.path.dirname(__file__))

from .memory_core import (
    LAYER_DAO,
    LAYER_FA,
    LAYER_SHU,
    PRIVACY_CONFIDENTIAL,
    PRIVACY_INTERNAL,
    PRIVACY_PUBLIC,
    PRIVACY_TOP_SECRET,
    SPACE_GLOBAL,
    SPACE_PERSONAL,
    SPACE_PROJECT,
    MemoryDB,
    WanYiCore,
)

# 版本唯一真源：wanyi/version.py（pyproject.toml 动态读取此处）
from .version import __version__

__all__ = [
    "LAYER_DAO",
    "LAYER_FA",
    "LAYER_SHU",
    "PRIVACY_CONFIDENTIAL",
    "PRIVACY_INTERNAL",
    "PRIVACY_PUBLIC",
    "PRIVACY_TOP_SECRET",
    "SPACE_GLOBAL",
    "SPACE_PERSONAL",
    "SPACE_PROJECT",
    "MemoryDB",
    "WanYiCore",
    "__version__",
]
