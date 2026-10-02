# -*- coding: utf-8 -*-
"""退出码语义 —— scripts/exitcodes.py。

用 subprocess 在「干净环境」（HOME 指向临时目录、去掉 TYPESAFE_API_KEY/PHONE_IP/cookie 等）
下验证每个脚本的退出码：凭证缺失=10 / 配置缺失=50 / 数据不足=40 / 成功=0。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import REPO_ROOT, TempDirMixin, clean_env, import_script, run_script

exitcodes = import_script("exitcodes")


class ExitcodesConstantsTest(unittest.TestCase):
    def test_values(self):
        self.assertEqual(exitcodes.OK, 0)
        self.assertEqual(exitcodes.CREDENTIAL, 10)
        self.assertEqual(exitcodes.UPSTREAM, 20)
        self.assertEqual(exitcodes.BAD_DATA, 30)
        self.assertEqual(exitcodes.INSUFFICIENT_DATA, 40)
        self.assertEqual(exitcodes.CONFIG, 50)
        self.assertEqual(exitcodes.INTEGRITY, 60)
        self.assertEqual(exitcodes.USAGE, 64)

    def test_names(self):
        self.assertEqual(exitcodes.name(10), "CREDENTIAL")
        self.assertEqual(exitcodes.name(40), "INSUFFICIENT_DATA")
        self.assertEqual(exitcodes.name(999), "UNKNOWN(999)")


class ScriptExitCodeTest(TempDirMixin, unittest.TestCase):

    def clean(self, **over):
        home = self.make_tempdir("home_")
        root = self.make_tempdir("root_")   # 空工作区：无快照、无 cookie
        kw = {"HOME": home, "CONTENT_OPS_ROOT": root}
        kw.update(over)
        return clean_env(**kw), home, root

    # ---------- 10 CREDENTIAL ----------
    def test_fetch_tt_stats_without_cookie_is_credential(self):
        env, _, _ = self.clean()
        self.assertIsNone(env.get("TYPESAFE_API_KEY"))
        r = run_script("fetch_tt_stats.py", env=env)
        self.assertEqual(r.returncode, 10, r.stdout + r.stderr)
        self.assertIn("COOKIE_EXPIRED", r.stdout)

    def test_tt_publish_probe_without_cookie_is_credential(self):
        env, _, _ = self.clean()
        r = run_script("tt_publish_probe.py", args=["--check"], env=env)
        self.assertEqual(r.returncode, 10, r.stdout + r.stderr)
        self.assertIn("COOKIE_MISSING", r.stdout)

    # ---------- 50 CONFIG ----------
    def test_phone_ctl_without_phone_ip_is_config(self):
        env, _, _ = self.clean()
        env.pop("PHONE_IP", None)
        r = run_script("phone_ctl.py", args=["status"], env=env)
        self.assertEqual(r.returncode, 50, r.stdout + r.stderr)
        self.assertIn("phone_ip_missing", r.stdout)

    def test_micro_diag_without_key_is_config(self):
        env, _, _ = self.clean()
        env.pop("TYPESAFE_API_KEY", None)
        r = run_script("micro_diag_test.py", env=env)
        self.assertEqual(r.returncode, 50, r.stdout + r.stderr)
        self.assertIn("EXTERNAL_EVAL_MISSING", r.stdout)

    # ---------- 40 INSUFFICIENT_DATA ----------
    def test_first_day_metrics_without_snapshot_is_insufficient(self):
        env, _, _ = self.clean()
        r = run_script("first_day_metrics.py", env=env)
        self.assertEqual(r.returncode, 40, r.stdout + r.stderr)
        self.assertIn("FIRSTDAY", r.stdout)

    # ---------- 0 OK ----------
    def test_first_day_metrics_with_examples_is_ok(self):
        home = self.make_tempdir("home_")
        env = clean_env(HOME=home, CONTENT_OPS_ROOT=os.path.join(REPO_ROOT, "examples"))
        r = run_script("first_day_metrics.py", env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(r.stdout.startswith("FIRSTDAY_OK"), r.stdout[:120])


if __name__ == "__main__":
    unittest.main()
