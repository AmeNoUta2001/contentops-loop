#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""头条发布链路探针（默认零写操作）。

用法：
    python3 tt_publish_probe.py --check          # 只做 CSRF preflight（HEAD，不发任何写请求）
    python3 tt_publish_probe.py --check-image    # 顺带探测图片上传端点的 CSRF（仍是 HEAD）
    python3 tt_publish_probe.py --draft-test     # ⚠️ 真正写：用 save=0 存一条草稿（需用户明确批准）

背景（2026-09-10 静态分析结论）：
- 发布：POST /mp/agw/article/publish?source=mp&type=article&aid=1231&mp_publish_ab_val={ab}，form-urlencoded
  save=1 正式发布 / save=0 保存草稿；timer_status=1 + timer_time="YYYY-MM-DD HH:mm" 表达定时
- CSRF：头名 x-secsdk-csrf-token；对同 host+pathname 发 HEAD 带 x-secsdk-csrf-request:1 + x-secsdk-csrf-version:1.2.22，
  从响应头 x-ware-csrf-token 取（逗号分隔 [code,token,maxAge,msg,sessionId]，code==0 有效）
- 图片：POST /spice/image?upload_source={src}&aid=1231&device_platform=web，multipart 字段名 image
- ⚠️ 风险代码：2222=可信浏览器校验 / 3001,3002=验证码 / 3022=账号未注册
"""
import argparse
import os
import subprocess
import sys
import exitcodes
import time

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36")
CSRF_VERSION = "1.2.22"
import sys as _sys
_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tt_cookie import cookie_path as _cookie_path

# cookie 自 2026-10-02 起走加密保险箱（scripts/secretctl.py）
BASE = "https://mp.toutiao.com"
REFERER = "https://mp.toutiao.com/profile_v4/graphic/publish"


def load_cookie():
    p = _cookie_path()
    if os.path.exists(p) and os.path.getsize(p) > 0:
        return open(p).read().strip(), p
    print("COOKIE_MISSING: 保险箱与兜底位置都没有 cookie")
    sys.exit(exitcodes.CREDENTIAL)


COOKIE, COOKIE_PATH = load_cookie()


def curl(args, timeout=30):
    """执行 curl，返回 (stdout, 响应头文本)。"""
    hdr_file = "/tmp/tt_probe_hdr.txt"
    cmd = ["curl", "-s", "--max-time", str(timeout), "-D", hdr_file] + args
    out = subprocess.run(cmd, capture_output=True, text=True).stdout
    try:
        hdrs = open(hdr_file, errors="ignore").read()
    except Exception:
        hdrs = ""
    return out, hdrs


def csrf_preflight(pathname, query=""):
    """照 secsdk 的做法取 CSRF token。只发 HEAD，不改状态。"""
    url = f"{BASE}{pathname}{query}"
    out, hdrs = curl(["-I", url,
                      "-H", f"Cookie: {COOKIE}",
                      "-H", f"User-Agent: {UA}",
                      "-H", f"Referer: {REFERER}",
                      "-H", "x-secsdk-csrf-request: 1",
                      "-H", f"x-secsdk-csrf-version: {CSRF_VERSION}"])
    token_line = ""
    for line in hdrs.splitlines():
        if line.lower().startswith("x-ware-csrf-token:"):
            token_line = line.split(":", 1)[1].strip()
    if not token_line:
        return None, out, hdrs
    parts = token_line.split(",")
    code = parts[0] if parts else "?"
    token = parts[1] if len(parts) > 1 else ""
    if code == "0" and token:
        return token, out, hdrs
    return None, out, hdrs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只做发布端点 CSRF preflight")
    ap.add_argument("--check-image", action="store_true", help="额外探图片上传端点")
    ap.add_argument("--draft-test", action="store_true", help="⚠️ 真实写：save=0 存草稿")
    args = ap.parse_args()

    print(f"[cookie] 来源={COOKIE_PATH} 长度={len(COOKIE)}（内容不输出）")
    if not COOKIE_PATH.startswith(os.path.expanduser("~")):
        print("[警告] 正在使用 /tmp 副本，重启会丢")

    results = {}
    for name, path, q in [("publish", "/mp/agw/article/publish",
                           "?source=mp&type=article&aid=1231&mp_publish_ab_val=0"),
                          ("spice_image", "/spice/image",
                           "?upload_source=mp_article&aid=1231&device_platform=web")]:
        if name == "spice_image" and not (args.check_image or args.draft_test):
            continue
        tok, out, hdrs = csrf_preflight(path, q)
        results[name] = tok
        status = [l.strip() for l in hdrs.splitlines() if l.startswith("HTTP/")]
        print(f"[{name}] CSRF token: {'取到 ✓' if tok else '未取到 ✗'} | {status[:1]}")
        if not tok:
            interesting = [l.strip() for l in hdrs.splitlines()
                           if l.lower().startswith(("x-ware-csrf", "location:", "set-cookie"))]
            for l in interesting[:3]:
                print("   ", l.split("=")[0][:60])
    return results


if __name__ == "__main__":
    main()
