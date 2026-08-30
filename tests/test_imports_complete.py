"""模块全局名完整性守卫（1.1.0 新增）。

用 symtable 做作用域感知分析：任何模块"被引用但模块级未绑定"的全局名
（如拆分遗漏的 import）都会在此被拦下，而不是运行到某条冷路径才 NameError。
"""
import builtins
import symtable
from pathlib import Path

from wanyi import core_base, engine, transport

_BUILTINS = set(dir(builtins)) | {
    "__name__", "__file__", "__doc__", "__package__", "__debug__",
    "__spec__", "__loader__", "__builtins__", "__annotations__", "__cached__",
}


def _needed_globals(src: str) -> set:
    st = symtable.symtable(src, "check.py", "exec")
    need = set()
    for s in st.get_symbols():
        if s.is_referenced() and not (s.is_assigned() or s.is_imported()):
            need.add(s.get_name())

    def walk(t):
        for ch in t.get_children():
            for s in ch.get_symbols():
                if s.is_referenced() and s.is_global() and not s.is_local() and not s.is_free():
                    need.add(s.get_name())
            walk(ch)

    walk(st)
    return need - _BUILTINS


def _module_bindings(src: str) -> set:
    st = symtable.symtable(src, "check.py", "exec")
    return {s.get_name() for s in st.get_symbols()
            if s.is_assigned() or s.is_imported()}


def test_no_missing_module_globals():
    """core_base / engine / transport 三个模块不得有缺失的全局名。"""
    problems = []
    for mod in (core_base, engine, transport):
        src = Path(mod.__file__).read_text(encoding="utf-8")
        missing = sorted(_needed_globals(src) - _module_bindings(src))
        if missing:
            problems.append(f"{mod.__name__}: {missing}")
    assert not problems, "发现未绑定的全局名（拆分/重构遗漏）:\n" + "\n".join(problems)
