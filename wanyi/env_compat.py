"""
环境变量兼容层（v1.1 新增）
─────────────────────────────────────────────────────────
背景：早期版本使用中文环境变量名（如 万忆中枢_STORE_DIR）。
中文 key 在 Windows 上可用，但在部分 MCP 客户端 / CI 容器 /
subprocess 环境存在编码兼容隐患。成熟做法是走 ASCII 别名。

本模块提供「中文优先、英文兜底」的读取函数：
  - 优先读中文名（向后兼容所有现有配置）
  - 读不到再退到 ASCII 名（WANYI_*）
  - 都读不到才用默认值

这样既保住现有用户的配置，又补上跨平台健壮性，不破坏任何行为。
"""
import os


def get_env(zh_name: str, en_name: str, default: str = "") -> str:
    """按「中文优先、英文兜底」顺序读取环境变量。

    Args:
        zh_name: 中文环境变量名（旧版，优先）
        en_name: ASCII 环境变量名（新版，兜底）
        default: 默认值

    Returns:
        命中的值；都不存在时返回 default。
    """
    val = os.environ.get(zh_name)
    if val is not None and val != "":
        return val
    val = os.environ.get(en_name)
    if val is not None and val != "":
        return val
    return default


def get_env_bool(zh_name: str, en_name: str, default: bool = False) -> bool:
    """按「中文优先、英文兜底」读取布尔环境变量（兼容 '1'/'true'/'yes'）。"""
    raw = get_env(zh_name, en_name, "")
    if raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y"}
