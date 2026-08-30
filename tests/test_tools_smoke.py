"""23 工具全覆盖冒烟：逐个真实调用，专抓拆分/重构引入的 NameError 类回归。

策略：按函数签名自动补齐必填参数（str/int/float/bool/list/dict 各给哑元），
TypeError（参数不匹配）与业务错误（status=error）都算"到达"，只有
NameError/AttributeError/ImportError 等环境级异常才算失败。
"""
import inspect

import pytest

from wanyi import engine


@pytest.fixture(scope="module")
def core(tmp_path_factory):
    """独立临时库实例，注入 engine.ENGINE 供 _get_tool_map 绑定。"""
    db = tmp_path_factory.mktemp("wanyi_smoke") / "smoke.db"
    inst = engine.WanYiCore(db_path=str(db), session_id="pytest-smoke")
    old = engine.ENGINE
    engine.ENGINE = inst
    yield inst
    engine.ENGINE = old


_DUMMY = {
    str: "冒烟测试",
    int: 1,
    float: 0.5,
    bool: True,
    list: [],
    dict: {},
}


def _minimal_kwargs(func):
    """只为无默认值的参数生成哑元（有默认值的一律不传，走默认分支）。"""
    kwargs = {}
    for name, param in inspect.signature(func).parameters.items():
        if param.default is not inspect.Parameter.empty:
            continue
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            continue
        ann = param.annotation if param.annotation is not inspect.Parameter.empty else str
        kwargs[name] = _DUMMY.get(ann, _DUMMY[str])
    return kwargs


def test_all_23_tools_callable(core):
    assert len(engine._get_tool_map()) == 23
    failures = []
    for tool_name, handler in sorted(engine._get_tool_map().items()):
        kwargs = _minimal_kwargs(handler)
        try:
            result = handler(**kwargs)
        except TypeError as e:
            failures.append(f"{tool_name}: 签名哑元补齐失败: {e}")
        except (NameError, AttributeError, ImportError) as e:
            failures.append(f"{tool_name}: 环境级异常 {type(e).__name__}: {e}")
        except Exception:
            continue  # 业务性拒绝（如缺语义参数）属"正常到达"
        else:
            assert result is not None, f"{tool_name} 返回 None"
    assert not failures, "发现拆分/重构回归:\n" + "\n".join(failures)
