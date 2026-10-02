#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""secretctl —— 项目凭据保险箱（AES-256-GCM）

设计目标：让 ~/content-ops-loop 目录**即使被完整泄露/备份/分享/推到公开仓库**，
里面的凭据也读不出来。因此：

  · 密文库  = ~/content-ops-loop/config/secrets.vault.json   （可以随便公开，里面只有密文）
  · 主密钥  = ~/.cheat-secrets/master.key （600，**在仓库之外**，绝不入库/绝不入备份分享范围）

⚠️ 保护边界（照直写）：防的是"仓库/备份/文件被拿走"，**不防**能读到你 home 目录的人。
   无人值守的 cron 需要自动解密，所以密钥只能落成文件；要更高强度请用 --passphrase 手工模式。

用法：
  secretctl init                                        # 生成主密钥 + 空库（已存在则不动）
  secretctl set <name> [--file PATH] [--note "..."]     # 值从 stdin 或文件读入并加密入库
  secretctl get <name>                                  # 打印明文（stdout，不回显到日志）
  secretctl get-file <name> OUT [--mode 600]            # 解密写到文件（用于 cookie 这类需要落盘的）
  secretctl list                                        # 只列名字与指纹
  secretctl verify                                      # 全部解密并校验指纹
  secretctl rm <name>                                   # 删除条目
  secretctl export-env                                  # 打印 export 语句（给 shell 用）
"""

# ── 项目根目录（默认 ~/content-ops-loop，可用环境变量 CONTENT_OPS_ROOT 覆盖）──────
import os as _os_root
CONTENT_OPS_ROOT = _os_root.path.expanduser(
    _os_root.environ.get('CONTENT_OPS_ROOT', '~/content-ops-loop'))

import argparse, base64, getpass, hashlib, json, os, stat, sys, datetime

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:
    print("需要 cryptography 库：python3 -m pip install cryptography", file=sys.stderr)
    sys.exit(3)

DEFAULT_KEY = os.path.expanduser("~/.cheat-secrets/master.key")
DEFAULT_VAULT = os.path.join(CONTENT_OPS_ROOT, 'config/secrets.vault.json')
AAD = b"cheat-content-vault-v1"


def key_path():
    return os.environ.get("CHEAT_MASTER_KEY_FILE", DEFAULT_KEY)


def vault_path():
    return os.environ.get("CHEAT_VAULT_FILE", DEFAULT_VAULT)


def _ensure_parent(path, mode=0o700):
    d = os.path.dirname(os.path.abspath(path))
    if d and not os.path.isdir(d):
        os.makedirs(d, mode=mode, exist_ok=True)


def load_key():
    p = key_path()
    if not os.path.exists(p):
        print("VAULT_ERR: 主密钥不存在（先跑 secretctl init）：%s" % p, file=sys.stderr)
        sys.exit(2)
    raw = open(p, "rb").read().strip()
    key = base64.b64decode(raw)
    if len(key) != 32:
        print("VAULT_ERR: 主密钥长度异常（应为 32 字节）", file=sys.stderr)
        sys.exit(2)
    return key


def load_vault():
    p = vault_path()
    if not os.path.exists(p):
        return {"version": 1, "cipher": "AES-256-GCM", "entries": {}}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save_vault(v):
    p = vault_path()
    _ensure_parent(p)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(v, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, p)
    os.chmod(p, 0o600)


def fp(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:12]


def enc(key: bytes, data: bytes) -> dict:
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, data, AAD)
    return {"nonce": base64.b64encode(nonce).decode(),
            "ct": base64.b64encode(ct).decode(),
            "sha256_12": fp(data)}


def dec(key: bytes, entry: dict) -> bytes:
    nonce = base64.b64decode(entry["nonce"])
    ct = base64.b64decode(entry["ct"])
    return AESGCM(key).decrypt(nonce, ct, AAD)


def cmd_init(args):
    kp = key_path()
    if os.path.exists(kp):
        print("KEY_EXISTS %s (未改动)" % kp)
    else:
        _ensure_parent(kp)
        key = os.urandom(32)
        fd = os.open(kp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(base64.b64encode(key) + b"\n")
        print("KEY_CREATED %s (600)" % kp)
    v = load_vault()
    save_vault(v)
    print("VAULT %s entries=%d" % (vault_path(), len(v.get("entries", {}))))


def cmd_set(args):
    if args.file:
        data = open(args.file, "rb").read()
    else:
        data = sys.stdin.buffer.read()
    while data.endswith(b"\n") or data.endswith(b"\r"):
        data = data[:-1]
    if not data:
        print("VAULT_ERR: 空值，拒绝写入", file=sys.stderr)
        sys.exit(2)
    key = load_key()
    v = load_vault()
    e = enc(key, data)
    e["len"] = len(data)
    e["updated"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    if args.note:
        e["note"] = args.note
    v.setdefault("entries", {})[args.name] = e
    save_vault(v)
    print("SET_OK %s len=%d fp=%s" % (args.name, len(data), e["sha256_12"]))


def cmd_get(args):
    key = load_key()
    v = load_vault()
    e = v.get("entries", {}).get(args.name)
    if not e:
        print("VAULT_ERR: 条目不存在：%s" % args.name, file=sys.stderr)
        sys.exit(2)
    data = dec(key, e)
    if fp(data) != e.get("sha256_12"):
        print("VAULT_ERR: 指纹不匹配（库被改过？）", file=sys.stderr)
        sys.exit(4)
    if args.raw:
        sys.stdout.buffer.write(data)
    else:
        sys.stdout.write(data.decode("utf-8", "replace"))


def cmd_get_file(args):
    key = load_key()
    v = load_vault()
    e = v.get("entries", {}).get(args.name)
    if not e:
        print("VAULT_ERR: 条目不存在：%s" % args.name, file=sys.stderr)
        sys.exit(2)
    data = dec(key, e)
    out = os.path.expanduser(args.out)
    _ensure_parent(out, 0o700)
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.chmod(out, int(args.mode, 8))
    print("GET_FILE_OK %s len=%d mode=%s" % (out, len(data), args.mode))


def cmd_list(args):
    v = load_vault()
    ents = v.get("entries", {})
    print("VAULT %s  entries=%d" % (vault_path(), len(ents)))
    for name in sorted(ents):
        e = ents[name]
        print("  %-28s len=%-6s fp=%s  updated=%s" % (name, e.get("len", "?"), e.get("sha256_12", "?"), e.get("updated", "?")))


def cmd_verify(args):
    key = load_key()
    v = load_vault()
    bad = 0
    for name, e in sorted(v.get("entries", {}).items()):
        try:
            data = dec(key, e)
            ok = fp(data) == e.get("sha256_12")
        except Exception as ex:
            data, ok = b"", False
            print("  %-28s DECRYPT_FAIL %s" % (name, repr(ex)[:60]))
            bad += 1
            continue
        print("  %-28s %s len=%d" % (name, "OK" if ok else "FP_MISMATCH", len(data)))
        if not ok:
            bad += 1
    print("VERIFY %s (%d/%d)" % ("PASS" if bad == 0 else "FAIL", len(v.get("entries", {})) - bad, len(v.get("entries", {}))))
    sys.exit(1 if bad else 0)


def cmd_rm(args):
    v = load_vault()
    if args.name in v.get("entries", {}):
        del v["entries"][args.name]
        save_vault(v)
        print("RM_OK %s" % args.name)
    else:
        print("VAULT_ERR: 条目不存在：%s" % args.name, file=sys.stderr)
        sys.exit(2)


def cmd_export_env(args):
    key = load_key()
    v = load_vault()
    for name, e in sorted(v.get("entries", {}).items()):
        data = dec(key, e)
        if b"\n" in data or b"\x00" in data:
            continue  # 多行/二进制条目不导出为环境变量
        print("export %s=%s" % (name.upper(), json.dumps(data.decode("utf-8", "replace"))))


def main():
    ap = argparse.ArgumentParser(description="cheat-content 凭据保险箱")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    p = sub.add_parser("set"); p.add_argument("name"); p.add_argument("--file"); p.add_argument("--note"); p.set_defaults(func=cmd_set)
    p = sub.add_parser("get"); p.add_argument("name"); p.add_argument("--raw", action="store_true"); p.set_defaults(func=cmd_get)
    p = sub.add_parser("get-file"); p.add_argument("name"); p.add_argument("out"); p.add_argument("--mode", default="600"); p.set_defaults(func=cmd_get_file)
    p = sub.add_parser("list"); p.set_defaults(func=cmd_list)
    p = sub.add_parser("verify"); p.set_defaults(func=cmd_verify)
    p = sub.add_parser("rm"); p.add_argument("name"); p.set_defaults(func=cmd_rm)
    p = sub.add_parser("export-env"); p.set_defaults(func=cmd_export_env)
    ap.set_defaults(func=None)
    args = ap.parse_args()
    fn = getattr(args, "func", None)
    if fn is None:
        fn = {"init": cmd_init, "list": cmd_list, "verify": cmd_verify, "export-env": cmd_export_env}[args.cmd]
    fn(args)


if __name__ == "__main__":
    main()
