# -*- coding: utf-8 -*-
"""secretctl.py —— 凭据保险箱基本行为。

覆盖：init 生成 32 字节主密钥且权限 600 / set-get 往返 / 读取不存在条目优雅失败 /
      篡改密文或指纹后 verify・get 失败 / 主密钥缺失时明确报错。

缺少 cryptography 库时整个类跳过（unittest.skipUnless）。
"""
import base64
import json
import os
import stat
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import TempDirMixin, clean_env, import_script, run_script

try:  # 与 scripts/secretctl.py 的可选依赖保持一致
    import cryptography  # noqa: F401
    HAVE_CRYPTO = True
except Exception:
    HAVE_CRYPTO = False

KEY_NAME = "master.key"
VAULT_NAME = "secrets.vault.json"


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


@unittest.skipUnless(HAVE_CRYPTO, "缺少 cryptography 库，跳过凭据保险箱测试")
class SecretctlTest(TempDirMixin, unittest.TestCase):

    def setUp(self):
        d = self.make_tempdir("vault_")
        self.key = os.path.join(d, KEY_NAME)
        self.vault = os.path.join(d, VAULT_NAME)
        self.env = clean_env(CHEAT_MASTER_KEY_FILE=self.key, CHEAT_VAULT_FILE=self.vault)

    # ---- 工具（注意别命名为 run，会覆盖 TestCase.run）----
    def _run(self, *args, **kw):
        return run_script("secretctl.py", args=list(args), env=self.env,
                          stdin=kw.get("stdin"))

    def init(self):
        r = self._run("init")
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def vault_json(self):
        with open(self.vault, encoding="utf-8") as f:
            return json.load(f)

    def write_vault_json(self, obj):
        with open(self.vault, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2, sort_keys=True)

    # ---------- 1. init：32 字节主密钥 + 权限 600 ----------
    def test_init_creates_32_byte_key_mode_600(self):
        self.init()
        self.assertTrue(os.path.exists(self.key))
        raw = read_bytes(self.key).strip()
        self.assertEqual(len(base64.b64decode(raw)), 32, "主密钥必须是 32 字节")
        mode = stat.S_IMODE(os.stat(self.key).st_mode)
        self.assertEqual(mode, 0o600, "主密钥权限应为 600，实为 %o" % mode)
        self.assertTrue(os.path.exists(self.vault))
        self.assertEqual(stat.S_IMODE(os.stat(self.vault).st_mode), 0o600)

    def test_init_is_idempotent(self):
        self._run("init")
        key_before = read_bytes(self.key)
        r = self._run("init")
        self.assertEqual(r.returncode, 0)
        self.assertIn("KEY_EXISTS", r.stdout)
        self.assertEqual(read_bytes(self.key), key_before, "已存在的主密钥不该被覆盖")

    # ---------- 2. set / get 往返 ----------
    def test_set_get_roundtrip(self):
        self.init()
        value = "sk-test-12345"
        r = self._run("set", "demo_key", stdin=value)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("SET_OK", r.stdout)

        g = self._run("get", "demo_key")
        self.assertEqual(g.returncode, 0, g.stderr)
        self.assertEqual(g.stdout, value)

        raw = self._run("get", "demo_key", "--raw")
        self.assertEqual(raw.returncode, 0)
        self.assertEqual(raw.stdout, value)

    def test_set_overwrites(self):
        self.init()
        self._run("set", "k", stdin="first")
        self._run("set", "k", stdin="second")
        self.assertEqual(self._run("get", "k").stdout, "second")

    def test_list_shows_name_not_value(self):
        self.init()
        self._run("set", "demo_key", stdin="topsecret")
        r = self._run("list")
        self.assertEqual(r.returncode, 0)
        self.assertIn("demo_key", r.stdout)
        self.assertNotIn("topsecret", r.stdout, "list 不得回显明文")

    # ---------- 3. 读取不存在条目：优雅失败（不改动、不崩溃）----------
    def test_get_missing_entry_fails_gracefully(self):
        self.init()
        before = read_bytes(self.vault)
        r = self._run("get", "no_such_entry")
        self.assertEqual(r.returncode, 2)
        self.assertIn("条目不存在", r.stderr)
        self.assertNotIn("Traceback", r.stderr, "应优雅失败而非抛栈")
        self.assertEqual(read_bytes(self.vault), before, "读取失败不得改动库")

    def test_rm_missing_entry_fails_gracefully(self):
        self.init()
        r = self._run("rm", "no_such_entry")
        self.assertEqual(r.returncode, 2)
        self.assertIn("条目不存在", r.stderr)

    # ---------- 4. 篡改密文 → GCM 完整性失败 ----------
    def test_tampered_ciphertext_fails(self):
        self.init()
        self._run("set", "demo_key", stdin="payload-x")
        v = self.vault_json()
        ct = bytearray(base64.b64decode(v["entries"]["demo_key"]["ct"]))
        ct[0] ^= 0xFF
        v["entries"]["demo_key"]["ct"] = base64.b64encode(bytes(ct)).decode()
        self.write_vault_json(v)

        ver = self._run("verify")
        self.assertNotEqual(ver.returncode, 0, "篡改后 verify 必须非 0")
        self.assertTrue(("DECRYPT_FAIL" in ver.stdout) or ("FAIL" in ver.stdout), ver.stdout)

        g = self._run("get", "demo_key")
        self.assertNotEqual(g.returncode, 0, "篡改后 get 必须失败")

    # ---------- 5. 篡改指纹 → 完整性校验失败 ----------
    def test_tampered_fingerprint_fails(self):
        self.init()
        self._run("set", "demo_key", stdin="payload-y")
        v = self.vault_json()
        v["entries"]["demo_key"]["sha256_12"] = "deadbeefcafe"
        self.write_vault_json(v)

        g = self._run("get", "demo_key")
        self.assertEqual(g.returncode, 4, g.stderr)
        self.assertIn("指纹不匹配", g.stderr)

        ver = self._run("verify")
        self.assertNotEqual(ver.returncode, 0)

    # ---------- 6. 主密钥缺失 → 明确错误 ----------
    def test_missing_master_key_errors_clearly(self):
        # 不 init：主密钥文件不存在
        r = self._run("get", "whatever")
        self.assertEqual(r.returncode, 2)
        self.assertIn("主密钥不存在", r.stderr)

    def test_malformed_master_key_errors(self):
        with open(self.key, "wb") as f:
            f.write(base64.b64encode(b"too-short"))   # 不足 32 字节
        os.chmod(self.key, 0o600)
        r = self._run("get", "whatever")
        self.assertEqual(r.returncode, 2)
        self.assertIn("主密钥", r.stderr)

    # ---------- 7. 加解密原语 ----------
    def test_enc_dec_roundtrip_and_fingerprint(self):
        secretctl = import_script("secretctl")
        key = os.urandom(32)
        entry = secretctl.enc(key, b"hello-vault")
        self.assertIn("nonce", entry)
        self.assertIn("ct", entry)
        self.assertEqual(secretctl.fp(b"hello-vault"), entry["sha256_12"])
        self.assertEqual(len(entry["sha256_12"]), 12)
        self.assertEqual(secretctl.dec(key, entry), b"hello-vault")

    def test_dec_with_wrong_key_fails(self):
        secretctl = import_script("secretctl")
        entry = secretctl.enc(os.urandom(32), b"data")
        with self.assertRaises(Exception):
            secretctl.dec(os.urandom(32), entry)


if __name__ == "__main__":
    unittest.main()
