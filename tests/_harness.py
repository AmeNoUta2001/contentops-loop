# -*- coding: utf-8 -*-
"""测试公共脚手架（纯标准库）。

职责：
  1) 把 scripts/ 挂到 sys.path —— 脚本之间用 `import exitcodes` / `import vertical`
     这种「平铺同级 import」，所以测试也必须让 scripts/ 可见。
  2) 提供 fixture 构造工具（快照 / 文章）与子进程运行工具（干净环境跑脚本看退出码）。

运行方式（**包根目录**执行）：
    python3 -m unittest discover -s tests -v
每个测试文件自己也会把 tests/ 插进 sys.path，因此该命令在 -s tests 与 -s tests -t . 下都能跑通。
"""
import datetime
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile


HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(REPO_ROOT, "scripts")
FIXTURES = os.path.join(HERE, "fixtures")
STATIC_SNAPSHOTS = os.path.join(FIXTURES, "snapshots")
PYTHON = sys.executable

if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

# platform_time 必须等 scripts/ 挂上 sys.path 之后再导入
import platform_time   # fixture 时间戳按平台时区构造，保证跨机器一致
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def import_script(name):
    """import scripts/<name>.py（scripts/ 已在 sys.path 上）。"""
    return importlib.import_module(name)


def clean_env(**overrides):
    """构造「干净」的子进程环境：去掉所有会影响脚本走向的本项目环境变量。

    overrides 里值为 None 表示显式删除该变量。
    """
    env = dict(os.environ)
    for k in ("TYPESAFE_API_KEY", "PHONE_IP", "TT_USER_ID", "VERTICAL_CONFIG",
              "CHEAT_MASTER_KEY_FILE", "CHEAT_VAULT_FILE", "CONTENT_OPS_ROOT",
              "SELF_ACCOUNT_NAME", "CHEAT_SECRET_TT_MP_COOKIES", "TT_MP_COOKIES"):
        env.pop(k, None)
    for k, v in overrides.items():
        if v is None:
            env.pop(k, None)
        else:
            env[k] = str(v)
    return env


def run_script(script, args=None, env=None, cwd=None, stdin=None, timeout=180):
    """用当前解释器以子进程方式跑 scripts/<script>，返回 CompletedProcess(text)。"""
    cmd = [PYTHON, os.path.join(SCRIPTS, script)] + list(args or [])
    return subprocess.run(
        cmd,
        cwd=cwd or REPO_ROOT,
        env=env if env is not None else clean_env(),
        capture_output=True,
        text=True,
        input=stdin,
        timeout=timeout,
    )


def ts(date_str, hour):
    """'2026-02-01', 14 → 本地时区该时刻的 epoch 秒。"""
    return int(datetime.datetime.fromisoformat("%sT%02d:00:00" % (date_str, hour))
                   .replace(tzinfo=platform_time.TZ).timestamp())


def make_article(item_id, title, show_date, hour, show, read,
                 traffic=None, status=20, ctr=None):
    """造一条最小快照文章记录（只带 build() 会用到的字段）。"""
    return {
        "item_id": str(item_id),
        "title": title,
        "item_status": status,
        "publish_time": ts(show_date, hour),
        "show_date": show_date,
        "show": show,
        "read": read,
        "ctr_calc": ctr if ctr is not None else (round(read / show * 100, 2) if show else 0),
        "traffic": traffic,
    }


def write_snapshots(dirpath, snapshots):
    """写出每日快照：snapshots = {date: [article, ...]} → <dir>/<date>.json。"""
    os.makedirs(dirpath, exist_ok=True)
    for date in snapshots:
        with open(os.path.join(dirpath, date + ".json"), "w", encoding="utf-8") as f:
            json.dump({"date": date, "articles": snapshots[date]}, f, ensure_ascii=False)
    return dirpath


class TempDirMixin(object):
    """给 TestCase 提供自动清理的临时目录。"""

    def make_tempdir(self, prefix="col_test_"):
        d = tempfile.mkdtemp(prefix=prefix)
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        return d

    def make_home(self, prefix="col_home_"):
        """造一个「干净 HOME」：无 .cheat-secrets、无 cookie、无 content-ops-loop。"""
        return self.make_tempdir(prefix)
