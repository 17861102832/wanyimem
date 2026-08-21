# -*- coding: utf-8 -*-
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

from .memory_core import WanYiCore, MemoryDB  # noqa: E402
from .memory_core import (  # noqa: E402
    LAYER_DAO, LAYER_FA, LAYER_SHU,
    SPACE_GLOBAL, SPACE_PERSONAL, SPACE_PROJECT,
    PRIVACY_PUBLIC, PRIVACY_INTERNAL, PRIVACY_CONFIDENTIAL, PRIVACY_TOP_SECRET,
)

__version__ = "5.0.0"
__all__ = [
    "WanYiCore", "MemoryDB",
    "LAYER_DAO", "LAYER_FA", "LAYER_SHU",
    "SPACE_GLOBAL", "SPACE_PERSONAL", "SPACE_PROJECT",
    "PRIVACY_PUBLIC", "PRIVACY_INTERNAL", "PRIVACY_CONFIDENTIAL", "PRIVACY_TOP_SECRET",
    "__version__",
]
