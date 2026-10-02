#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""凭据泄漏扫描：仓库里不该出现「凭据形状」的内容。

它只做粗筛（形状匹配），不是完整的 secret scanning —— 目的是让「不小心把一个 token 提交进去」
变成 CI 失败，而不是等 GitHub 的推送保护来救。

用法：python3 tools/scan_credentials.py
"""
import pathlib
import re
import sys

PATTERNS = [
    (r"sk-[A-Za-z0-9_\-]{16,}", "API key"),
    (r"(?i)(passport_csrf_token|ttwid=|sessionid=[A-Za-z0-9]{12,}|sid_tt=)", "session cookie"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "private key"),
    (r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}", "GitHub token"),
    (r"\bAKIA[0-9A-Z]{16}\b", "AWS access key id"),
    (r"\b100\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "tailnet address"),
]

# 不扫的目录：运行产出（本地可能有真实数据，本来就不该入库）
SKIP_DIRS = {".git", "__pycache__", "reports", "node_modules", ".venv", "venv"}
# 不扫的文件：这些检查脚本自身必然包含上面的模式字符串
SKIP_FILES = {"tools/scan_credentials.py"}


def main():
    hits = []
    scanned = 0
    for p in sorted(pathlib.Path(".").rglob("*")):
        if not p.is_file() or any(d in p.parts for d in SKIP_DIRS):
            continue
        if p.suffix in {".pyc", ".png", ".jpg", ".webp", ".gz", ".zip"}:
            continue
        if p.as_posix().lstrip("./") in SKIP_FILES:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        scanned += 1
        for rx, label in PATTERNS:
            for m in re.finditer(rx, text):
                hits.append(f"{p}: [{label}] {m.group(0)[:28]}")

    print(f"扫描 {scanned} 个文件")
    if hits:
        print("发现疑似凭据：")
        for h in hits[:40]:
            print("  " + h)
        sys.exit(1)
    print("OK: 未发现凭据形状的内容")


if __name__ == "__main__":
    main()
