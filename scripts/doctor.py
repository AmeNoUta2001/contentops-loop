#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doctor —— 环境自检 / 工作区初始化。

    python3 scripts/doctor.py            # 只体检，不改任何东西
    python3 scripts/doctor.py --init     # 顺便把工作区目录树建出来

为什么要它：这套脚本是「数据驱动的流水线」，缺一个目录或一个外部命令就会在中途报错。
先跑一次 doctor，比对着 traceback 猜要快。
"""
import importlib
import os
import shutil
import sys
import exitcodes

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from tt_cookie import cookie_path, load_cookie
except Exception:                                            # noqa: BLE001
    cookie_path = load_cookie = None

# 项目根目录（与其余脚本同一套规则）
CONTENT_OPS_ROOT = os.path.expanduser(
    os.environ.get('CONTENT_OPS_ROOT', '~/content-ops-loop'))

DIRS = [
    'config',
    'reports',
    'reports/tt_snapshots',      # 每日数据快照（fetch_tt_stats.py 写）
    'reports/benchmark',         # 赛道基准（benchmark_store.py 写）
    'reports/same_topic',        # 同题库（same_topic_store.py 写）
    'reports/jev-replay',        # 离线回放实验产物
    'reports/nurture',           # 养号观察（可选）
    'logs',
]

BINARIES = [
    ('curl', True, '所有取数脚本靠它发请求'),
    ('adb', False, 'phone_ctl.py 需要（控制安卓手机）'),
]

MODULES = [
    ('cryptography', False, '凭据保险箱 secretctl.py / secrets_env.py'),
    ('PIL', False, 'phone_ctl.py 截图亮度（Pillow）'),
    ('numpy', False, '同上'),
]


def ok(s):
    return f"  [OK]   {s}"


def warn(s):
    return f"  [--]   {s}"


def bad(s):
    return f"  [!!]   {s}"


def main():
    do_init = '--init' in sys.argv
    print(f"ROOT = {CONTENT_OPS_ROOT}")
    print(f"python {sys.version.split()[0]}")

    print("\n[外部命令]")
    for name, required, why in BINARIES:
        found = shutil.which(name)
        if found:
            print(ok(f"{name} -> {found}"))
        else:
            print((bad if required else warn)(f"{name} 未安装 —— {why}"))

    print("\n[Python 可选依赖]")
    for mod, required, why in MODULES:
        try:
            importlib.import_module(mod)
            print(ok(f"{mod} 已安装"))
        except Exception:                                    # noqa: BLE001
            print((bad if required else warn)(f"{mod} 未安装 —— {why}"))

    print("\n[工作区目录]")
    missing = []
    for d in DIRS:
        p = os.path.join(CONTENT_OPS_ROOT, d)
        if os.path.isdir(p):
            print(ok(d))
        else:
            missing.append(d)
            print(warn(f"{d} 不存在"))
    if missing and do_init:
        for d in missing:
            os.makedirs(os.path.join(CONTENT_OPS_ROOT, d), exist_ok=True)
        print(ok(f"已创建 {len(missing)} 个目录"))
    elif missing:
        print("  -> 想一次建好：python3 scripts/doctor.py --init")

    print("\n[登录态 cookie]")
    if cookie_path is None:
        print(warn("tt_cookie 导入失败，跳过"))
    else:
        p = cookie_path() or ''
        if p and os.path.exists(p) and os.path.getsize(p) > 0:
            print(ok(f"cookie 就位（{len(load_cookie())} 字符，内容不打印）"))
        else:
            print(warn("没有可用 cookie —— 取数类脚本会直接退出并提示，属预期行为"))
            print("    写入方式见 README「凭据管理」一节（推荐存进加密保险箱）")

    problems = []
    for _n, _req, _w in BINARIES:
        if _req and not shutil.which(_n):
            problems.append(f"缺少必需命令 {_n}")
    for _m, _req, _w in MODULES:
        if _req:
            try:
                importlib.import_module(_m)
            except Exception:                                # noqa: BLE001
                problems.append(f"缺少必需依赖 {_m}")

    print("\n[数据]")
    snap_dir = os.path.join(CONTENT_OPS_ROOT, 'reports/tt_snapshots')
    n = 0
    if os.path.isdir(snap_dir):
        n = len([f for f in os.listdir(snap_dir)
                 if f.endswith('.json') and len(f) == 15])
    if n:
        print(ok(f"快照 {n} 天 —— 可以跑 first_day_metrics.py"))
    else:
        print(warn("没有快照 —— 先用 examples/ 里的合成数据体验："))
        print("    CONTENT_OPS_ROOT=examples python3 scripts/first_day_metrics.py")

    if '--strict' in sys.argv:
        if problems:
            print("\n[strict] 必需项缺失，退出码 50：")
            for _p in problems:
                print(f"  - {_p}")
            sys.exit(exitcodes.CONFIG)
        print("\n[strict] 必需项齐全")


if __name__ == '__main__':
    main()
