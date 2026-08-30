"""1.1.0 架构重组回归：memory_core 门面、模块拆分一致性与版本唯一真源。"""
from pathlib import Path

import wanyi
from wanyi import core_base, engine, transport, version


def test_facade_identity():
    """memory_core 门面必须与拆分模块共享同一实现（避免双份状态）。"""
    import wanyi.memory_core as m

    assert m.WanYiCore is engine.WanYiCore
    assert m.MemoryDB is core_base.MemoryDB
    assert m.handle_request is transport.handle_request
    assert m.main is transport.main
    assert len(m.MCP_TOOLS) == 23


def test_version_single_source():
    """版本号唯一真源 = wanyi/version.py，全链路一致。"""
    assert wanyi.__version__ == version.__version__

    engine_src = Path(engine.__file__).read_text(encoding="utf-8")
    assert '"version": __version__' in engine_src, "initialize 必须引用 version.py"
    for stale in ('"version": "1.0.2"', '"version": "5.0"'):
        assert stale not in engine_src, f"发现硬编码旧版本号: {stale}"


def test_top_level_dual_mode_import():
    """sys.path hack 下的顶层导入（hooks.py 依赖路径）必须继续可用。"""
    import subprocess
    import sys

    code = (
        "import sys, tempfile, os\n"
        "env = dict(os.environ)\n"
        "tmp = tempfile.mkdtemp(prefix='wanyi_dual_')\n"
        "env['万忆中枢_MEMORY_DB'] = os.path.join(tmp, 't.db')\n"
        "env['OBSIDIAN_VAULT'] = ''\n"
        f"sys.path.insert(0, r'{Path(wanyi.__file__).parent!s}')\n"
        "import memory_core\n"
        "assert len(memory_core.MCP_TOOLS) == 23\n"
        "from hooks import hook_load\n"
        "from project_memory import PROJECT_CONTEXT_PATH\n"
        "print('dual-mode-ok')\n"
    )

    r = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False,
        cwd=str(Path(wanyi.__file__).parent.parent), timeout=120,
    )
    assert "dual-mode-ok" in r.stdout, f"顶层双模导入失败:\n{r.stdout}\n{r.stderr}"
