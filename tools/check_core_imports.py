#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CI 用的「内核不得顶层 import 第三方库」检查（稳健版）。

上一版的两个 bug：
  · 直接用 sys.stdlib_module_names —— 3.10+ 才有，3.9 上 AttributeError；
  · 兜底只扫标准库目录 —— 但 C 扩展模块（math、_socket…）住在 <stdlib>/lib-dynload/，
    于是 3.9 上把 math 误判成第三方库。
两个都是「CI 专用脚本没在全部目标版本上跑过」造成的，所以这个文件必须能被本地逐个版本执行。
"""
import ast
import os
import pathlib
import sys
import sysconfig

OPTIONAL = {"PIL", "numpy", "cryptography"}
LOCAL_PKG_DIR = "scripts"


def _scan_dir(d):
    """扫一个目录，收集顶层模块/包名。"""
    out = set()
    if not d or not os.path.isdir(d):
        return out
    for entry in os.listdir(d):
        full = os.path.join(d, entry)
        if entry.endswith(".py"):
            out.add(entry[:-3])
        elif os.path.isdir(full):
            if os.path.exists(os.path.join(full, "__init__.py")):
                out.add(entry)
        elif "." in entry:                      # 扩展模块：math.cpython-39-x86_64-linux-gnu.so
            out.add(entry.split(".")[0])
    return out


def stdlib_names():
    """尽量完整地收集标准库顶层名 —— 跨 3.9 ~ 3.12 都成立。"""
    names = set(getattr(sys, "stdlib_module_names", ()))   # 3.10+ 直接给
    names |= set(sys.builtin_module_names)                 # 编译进解释器的（sys、builtins…）
    paths = sysconfig.get_paths()
    names |= _scan_dir(paths.get("stdlib"))
    names |= _scan_dir(paths.get("platstdlib"))
    # ⚠️ C 扩展（math 等）在这里，3.9 上漏了它就会误报
    for base in {paths.get("stdlib"), paths.get("platstdlib")}:
        names |= _scan_dir(os.path.join(base or "", "lib-dynload"))
    names.discard("")
    return names


def is_stdlib_by_location(name):
    """兜底：模块文件就在标准库前缀下（且不在 site-packages 里）→ 算标准库。"""
    try:
        import importlib.util
        spec = importlib.util.find_spec(name)
    except (ImportError, ValueError, AttributeError):
        return False
    if spec is None:
        return False
    if getattr(spec, "origin", None) in (None, "built-in", "frozen"):
        return True
    origin = os.path.abspath(spec.origin)
    if "site-packages" in origin or "dist-packages" in origin:
        return False
    for base in {sysconfig.get_paths().get("stdlib"), sysconfig.get_paths().get("platstdlib")}:
        if base and origin.startswith(os.path.abspath(base)):
            return True
    return False


def main():
    stdlib = stdlib_names()
    bad = []
    checked = 0
    for path in sorted(pathlib.Path(LOCAL_PKG_DIR).glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:                       # 只看模块级 import
            names = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module.split(".")[0]]
            for n in names:
                checked += 1
                if n in stdlib or n in OPTIONAL:
                    continue
                if pathlib.Path(LOCAL_PKG_DIR, n + ".py").exists():      # 仓库内同级模块
                    continue
                if is_stdlib_by_location(n):
                    continue
                bad.append(f"{path}: top-level import of third-party module {n!r}")
    if bad:
        print("\n".join(bad))
        print(f"\npython {sys.version.split()[0]}: 发现 {len(bad)} 个第三方顶层 import")
        sys.exit(1)
    print(f"OK: python {sys.version.split()[0]} — 内核 {checked} 个顶层 import 全部是"
          f"标准库/仓库内模块（stdlib 名单 {len(stdlib)} 个）")


if __name__ == "__main__":
    main()
