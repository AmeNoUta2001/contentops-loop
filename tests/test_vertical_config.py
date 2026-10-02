# -*- coding: utf-8 -*-
"""vertical.py —— 垂类配置加载器。

覆盖：能读到 config/vertical.json / thresholds 覆盖默认值 / 配置缺失时返回空词表并提示而非崩溃 /
      VERTICAL_CONFIG 与 CONTENT_OPS_ROOT 都能改配置位置 / 环境变量优先级。

手法：vertical 用模块级 _CACHE 缓存且 CANDIDATES 在 import 时按环境变量算出，
      因此临时改环境变量后必须 importlib.reload 才会生效；tearDown 里恢复环境并再 reload。
"""
import contextlib
import importlib
import io
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import (REPO_ROOT, SCRIPTS, TempDirMixin, clean_env,
                      import_script, run_script)

vertical = import_script("vertical")

ENV_KEYS = ("VERTICAL_CONFIG", "CONTENT_OPS_ROOT")

MINI_CONFIG = {
    "vertical": "自定义垂类",
    "families": [{"name": "自定义族", "keywords": ["甲", "乙"]}],
    "motifs": [{"name": "自定义母题", "keywords": ["丙"]}],
    "off_vertical": ["客串词"],
    "niche_pos": ["甲"],
    "niche_neg": ["客串词"],
    "thresholds": {"own_pass_ctr": 9.9},
}


class VerticalConfigTest(TempDirMixin, unittest.TestCase):

    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in ENV_KEYS}
        for k in ENV_KEYS:
            os.environ.pop(k, None)
        importlib.reload(vertical)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        importlib.reload(vertical)   # 清 _CACHE，把模块恢复到原始环境

    def write_config(self, path_or_dir, cfg, in_config_subdir=False):
        d = path_or_dir
        if in_config_subdir:
            d = os.path.join(path_or_dir, "config")
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "vertical.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False)
        return p

    # ---------- 1. 能读到仓库自带的 config/vertical.json ----------
    def test_reads_repo_config_by_default(self):
        p = vertical.config_path()
        self.assertIsNotNone(p, "没读到配置（CANDIDATES=%r）" % (vertical.CANDIDATES,))
        self.assertEqual(os.path.abspath(p),
                         os.path.join(REPO_ROOT, "config", "vertical.json"))
        self.assertTrue(os.path.exists(p))
        self.assertNotEqual(vertical.name(), "未命名")
        self.assertTrue(vertical.families(), "题材族不该为空")
        self.assertTrue(vertical.motifs(), "母题不该为空")

    # ---------- 2. thresholds 覆盖默认值，缺失项回落默认 ----------
    def test_thresholds_override_and_fallback(self):
        cfg = dict(MINI_CONFIG)
        p = self.write_config(self.make_tempdir(), cfg)
        os.environ["VERTICAL_CONFIG"] = p
        importlib.reload(vertical)

        self.assertEqual(vertical.threshold("own_pass_ctr"), 9.9, "配置应覆盖默认")
        # 不在配置里的阈值 → 回落 THRESHOLD_DEFAULTS
        self.assertEqual(vertical.threshold("min_n_quantile"), 8)
        self.assertEqual(vertical.threshold("big_pool_show"), 900)
        self.assertEqual(vertical.threshold("strong_kw_hits"), 2)
        # 完全未知的名字 → None（不抛）
        self.assertIsNone(vertical.threshold("完全不存在的阈值"))

    def test_repo_config_thresholds_present(self):
        for k in ("viral_show", "own_pass_ctr", "min_n_quantile", "strong_kw_hits"):
            self.assertIsNotNone(vertical.threshold(k), "%s 应有值" % k)

    # ---------- 3. 配置缺失：空词表 + 提示，而不是崩溃 ----------
    def test_missing_config_returns_empty_with_hint(self):
        # 注意：环境变量改不掉「scripts/../config」这个仓库内兜底路径，
        # 所以直接清空候选列表来构造「哪都找不到配置」的分支。
        vertical.CANDIDATES = [os.path.join(self.make_tempdir(), "nope.json")]
        vertical._CACHE = None
        self.assertIsNone(vertical.config_path())

        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            fams = vertical.families()
        self.assertEqual(fams, [])
        self.assertEqual(vertical.motifs(), [])
        self.assertEqual(vertical.motif_must(), {})
        self.assertEqual(vertical.off_vertical(), [])
        self.assertEqual(vertical.name(), "未命名")
        self.assertIn("没找到垂类配置", err.getvalue())

    def test_missing_config_threshold_still_default(self):
        vertical.CANDIDATES = [os.path.join(self.make_tempdir(), "nope.json")]
        vertical._CACHE = None
        # 即使没有配置文件，阈值仍回落默认（不崩）
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(vertical.threshold("viral_show"), 5000)
            self.assertEqual(vertical.threshold("min_n_quantile"), 8)

    # ---------- 4. VERTICAL_CONFIG 改位置并压过 CONTENT_OPS_ROOT ----------
    def test_vertical_config_env_changes_location(self):
        p = self.write_config(self.make_tempdir(), MINI_CONFIG)
        os.environ["VERTICAL_CONFIG"] = p
        importlib.reload(vertical)
        self.assertEqual(os.path.abspath(vertical.config_path()), os.path.abspath(p))
        self.assertEqual(vertical.name(), "自定义垂类")
        self.assertEqual(vertical.families(), [("自定义族", ["甲", "乙"])])

    def test_vertical_config_takes_precedence_over_root(self):
        p = self.write_config(self.make_tempdir(), MINI_CONFIG)
        other_root = self.make_tempdir()
        self.write_config(other_root, {"vertical": "根目录那份"}, in_config_subdir=True)
        os.environ["VERTICAL_CONFIG"] = p
        os.environ["CONTENT_OPS_ROOT"] = other_root
        importlib.reload(vertical)
        self.assertEqual(os.path.abspath(vertical.config_path()), os.path.abspath(p))
        self.assertEqual(vertical.name(), "自定义垂类")

    # ---------- 5. CONTENT_OPS_ROOT 改位置 ----------
    def test_content_ops_root_env_changes_location(self):
        root = self.make_tempdir()
        p = self.write_config(root, MINI_CONFIG, in_config_subdir=True)
        os.environ["CONTENT_OPS_ROOT"] = root
        importlib.reload(vertical)
        self.assertEqual(os.path.abspath(vertical.config_path()), os.path.abspath(p))
        self.assertEqual(vertical.name(), "自定义垂类")

    # ---------- 6. 干净子进程里验证环境变量确实生效 ----------
    def test_env_var_in_fresh_interpreter(self):
        p = self.write_config(self.make_tempdir(), MINI_CONFIG)
        code = ("import sys; sys.path.insert(0, %r); import vertical as v; "
                "print(v.config_path()); print(v.name()); print(v.threshold('own_pass_ctr'))"
                % SCRIPTS)
        env = clean_env(VERTICAL_CONFIG=p, PYTHONPATH=SCRIPTS)
        import subprocess
        r = subprocess.run([sys.executable, "-c", code], env=env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout.splitlines()
        self.assertEqual(os.path.abspath(out[0]), os.path.abspath(p))
        self.assertEqual(out[1], "自定义垂类")
        self.assertEqual(out[2], "9.9")


if __name__ == "__main__":
    unittest.main()
