#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tt_cookie —— 头条后台 cookie 的统一取用口（2026-10-02 起）

背景：明文 cookie 原先放在仓库内（~/content-ops-loop/config/tt_mp_cookies.txt），
一旦仓库被泄露/备份/分享就等于把登录态送出去。现在改为：
  ① 优先读**仓库外**的运行副本 ~/.cheat-secrets/tt_mp_cookies.txt（600）
  ② 没有就自动从加密保险箱 config/secrets.vault.json 解密一份出来（scripts/secretctl.py）
  ③ 兜底才用老路径与 /tmp（兼容用户 F12 手贴的老流程）

用法：
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from tt_cookie import cookie_path, load_cookie
"""

# ── 项目根目录（默认 ~/content-ops-loop，可用环境变量 CONTENT_OPS_ROOT 覆盖）──────
import os as _os_root
CONTENT_OPS_ROOT = _os_root.path.expanduser(
    _os_root.environ.get('CONTENT_OPS_ROOT', '~/content-ops-loop'))

import os
import sys

RUNTIME = os.path.expanduser("~/.cheat-secrets/tt_mp_cookies.txt")
LEGACY = os.path.join(CONTENT_OPS_ROOT, 'config/tt_mp_cookies.txt')
TMP = "/tmp/tt_mp_cookies.txt"


def _nonempty(p):
    return bool(p) and os.path.exists(p) and os.path.getsize(p) > 0


def cookie_path():
    if _nonempty(RUNTIME):
        return RUNTIME
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from secrets_env import get_secret_file
        p = get_secret_file("tt_mp_cookies", out_name="tt_mp_cookies.txt")
        if _nonempty(p):
            return p
    except Exception:
        pass
    for p in (LEGACY, TMP):
        if _nonempty(p):
            return p
    return RUNTIME


def load_cookie():
    p = cookie_path()
    with open(p, encoding="utf-8", errors="replace") as f:
        return f.read().strip()


if __name__ == "__main__":
    p = cookie_path()
    ck = load_cookie() if _nonempty(p) else ""
    print("COOKIE_PATH %s" % p)
    print("COOKIE_LEN %d" % len(ck))
