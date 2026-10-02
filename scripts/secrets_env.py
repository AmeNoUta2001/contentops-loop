#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""secrets_env —— 脚本侧读取保险箱的极简接口（配合 secretctl.py）

优先级：环境变量 > 保险箱 > 默认值
用法：
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from secrets_env import get_secret, get_secret_file
    key = get_secret("dashscope_api_key")
    cookie_path = get_secret_file("tt_mp_cookies")   # 解密到 ~/.cheat-secrets/ 并返回路径
"""

# ── 项目根目录（默认 ~/content-ops-loop，可用环境变量 CONTENT_OPS_ROOT 覆盖）──────
import os as _os_root
CONTENT_OPS_ROOT = _os_root.path.expanduser(
    _os_root.environ.get('CONTENT_OPS_ROOT', '~/content-ops-loop'))

import base64, hashlib, json, os, sys

DEFAULT_KEY = os.path.expanduser("~/.cheat-secrets/master.key")
DEFAULT_VAULT = os.path.join(CONTENT_OPS_ROOT, 'config/secrets.vault.json')
AAD = b"cheat-content-vault-v1"


def _paths():
    return (os.environ.get("CHEAT_MASTER_KEY_FILE", DEFAULT_KEY),
            os.environ.get("CHEAT_VAULT_FILE", DEFAULT_VAULT))


def _load():
    kp, vp = _paths()
    if not (os.path.exists(kp) and os.path.exists(vp)):
        return None, None
    with open(kp, "rb") as f:
        key = base64.b64decode(f.read().strip())
    with open(vp, encoding="utf-8") as f:
        vault = json.load(f)
    return key, vault


def get_secret(name, default=None):
    """按名取明文（str）。环境变量优先：<NAME大写> 或 CHEAT_SECRET_<NAME大写>。"""
    env_name = name.upper()
    if os.environ.get(env_name):
        return os.environ[env_name]
    if os.environ.get("CHEAT_SECRET_" + env_name):
        return os.environ["CHEAT_SECRET_" + env_name]
    key, vault = _load()
    if not key:
        return default
    e = (vault.get("entries") or {}).get(name)
    if not e:
        return default
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        data = AESGCM(key).decrypt(base64.b64decode(e["nonce"]), base64.b64decode(e["ct"]), AAD)
        if hashlib.sha256(data).hexdigest()[:12] != e.get("sha256_12"):
            return default
        return data.decode("utf-8", "replace")
    except Exception:
        return default


def get_secret_file(name, subdir="~/.cheat-secrets", out_name=None):
    """把库里存的多行/二进制条目解密到 subdir/<out_name|name>（600），返回路径；失败返回 None。"""
    key, vault = _load()
    if not key:
        return None
    e = (vault.get("entries") or {}).get(name)
    if not e:
        return None
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        data = AESGCM(key).decrypt(base64.b64decode(e["nonce"]), base64.b64decode(e["ct"]), AAD)
        if hashlib.sha256(data).hexdigest()[:12] != e.get("sha256_12"):
            return None
        d = os.path.expanduser(subdir)
        os.makedirs(d, mode=0o700, exist_ok=True)
        out = os.path.join(d, out_name or name)
        fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(out, 0o600)
        return out
    except Exception:
        return None


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "check":
        kp, vp = _paths()
        print("KEY_FILE  %s exists=%s" % (kp, os.path.exists(kp)))
        print("VAULT     %s exists=%s" % (vp, os.path.exists(vp)))
        k, v = _load()
        print("entries   %s" % (list((v or {}).get("entries", {}).keys())))
        s = get_secret("dashscope_api_key")
        print("dashscope_api_key loaded=%s len=%d" % (bool(s), len(s or "")))
