# -*- coding: utf-8 -*-
"""诊断逻辑 —— scripts/funnel_diagnosis.py 的五档/样本守卫规则引擎。

diagnose() 是可导入的纯函数，直接单元测试；
另有 1 条 subprocess 集成测试：用 fixture 数据跑完整脚本，验证「数据不足必须走样本不足」。
（first_day_metrics.py 本身没有五档判定 —— 五档处置在 funnel_diagnosis.py。）
"""
import datetime
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import REPO_ROOT, TempDirMixin, import_script, run_script

fd = import_script("funnel_diagnosis")

FAULT_A = "A_数据不足或给量不足"
FAULT_B = "B_标题或封面（点击端不住）"
FAULT_C = "C_开头承诺兑现"
FAULT_D = "D_正文节奏"
FAULT_F = "F_健康（无明显故障）"


class DiagnoseUnitTest(unittest.TestCase):

    # ---------- 样本守卫：数据不足时任一下结论而不是硬判内容 ----------
    def test_insufficient_read_goes_a_pool(self):
        d = fd.diagnose(show=50, read=2, ctr=1.0)
        self.assertEqual(d["insufficiency"], "insufficient")
        self.assertEqual(d["fault"], FAULT_A)
        self.assertIn(d["next"], ("换更大池·题材", "等数据够了再判"))

    def test_insufficient_show_with_strong_ctr_goes_a_wait(self):
        # 曝光<100 但 CTR 已过 6% → 不该重发，等数据
        d = fd.diagnose(show=50, read=2, ctr=7.0)
        self.assertEqual(d["insufficiency"], "insufficient")
        self.assertEqual(d["fault"], FAULT_A)
        self.assertEqual(d["next"], "等数据够了再判")

    def test_insufficient_show_only_still_guarded(self):
        d = fd.diagnose(show=90, read=10, ctr=20.0)
        self.assertEqual(d["insufficiency"], "insufficient")
        self.assertEqual(d["fault"], FAULT_A)

    def test_sample_guard_note_injected(self):
        d = fd.diagnose(show=50, read=2, ctr=1.0)
        self.assertTrue(any("样本不足守卫" in s for s in d["susp"]),
                        d["susp"])

    # ---------- 五档 tier 只表达「给量」----------
    def test_tier_by_show(self):
        self.assertEqual(fd.diagnose(show=1000, read=100, ctr=7.0)["tier"], 1)
        self.assertEqual(fd.diagnose(show=500, read=50, ctr=7.0)["tier"], 2)
        self.assertEqual(fd.diagnose(show=200, read=30, ctr=7.0)["tier"], 3)
        self.assertEqual(fd.diagnose(show=900, read=90, ctr=7.0)["tier"], 1, "900 边界算大池")
        self.assertEqual(fd.diagnose(show=300, read=30, ctr=7.0)["tier"], 2, "300 边界算中池")

    def test_pool_boundaries(self):
        self.assertEqual(fd.diagnose(show=200, read=30, ctr=7.0)["pool"], "小")
        self.assertEqual(fd.diagnose(show=300, read=30, ctr=7.0)["pool"], "中")
        self.assertEqual(fd.diagnose(show=900, read=90, ctr=7.0)["pool"], "大")

    # ---------- 给量门 / 点击门 ----------
    def test_small_pool_but_strong_ctr_resend(self):
        d = fd.diagnose(show=200, read=30, ctr=7.0)
        self.assertEqual(d["fault"], FAULT_B)
        self.assertEqual(d["next"], "改题+换封面重发")
        self.assertEqual(d["click"], "强")

    def test_small_pool_weak_ctr_is_pool_problem(self):
        d = fd.diagnose(show=200, read=20, ctr=2.0)
        self.assertEqual(d["fault"], FAULT_A)
        self.assertEqual(d["next"], "换更大池·题材")

    def test_mid_pool_ctr_dead(self):
        d = fd.diagnose(show=500, read=50, ctr=0.5)
        self.assertEqual(d["fault"], FAULT_B)
        self.assertEqual(d["click"], "端不住")

    def test_mid_pool_ctr_weak(self):
        d = fd.diagnose(show=500, read=50, ctr=2.0)
        self.assertEqual(d["fault"], FAULT_B)
        self.assertEqual(d["click"], "偏弱")

    # ---------- 点击过线但人头不够 → 仍不判内容 ----------
    def test_click_passed_but_reads_few_is_a_wait(self):
        d = fd.diagnose(show=400, read=10, ctr=5.0)
        self.assertEqual(d["fault"], FAULT_A)
        self.assertEqual(d["next"], "等数据够了再判")

    # ---------- 内容层（要有量 + 点击过线 + 阅读>=30）----------
    def test_content_layer_keep_bad_is_c(self):
        d = fd.diagnose(show=1000, read=100, ctr=5.0, cr=0.5, cr_rank=20, dur=60, itr_rank=70)
        self.assertEqual(d["fault"], FAULT_C)
        self.assertEqual(d["next"], "改开头3秒")

    def test_content_layer_mid_keep_short_dur_is_d(self):
        d = fd.diagnose(show=1000, read=100, ctr=5.0, cr=0.5, cr_rank=45, dur=30, itr_rank=70)
        self.assertEqual(d["fault"], FAULT_D)
        self.assertEqual(d["next"], "精简中段")

    def test_healthy_article_is_f(self):
        d = fd.diagnose(show=1000, read=100, ctr=7.0, cr=0.5, cr_rank=70, dur=60, itr_rank=70)
        self.assertEqual(d["fault"], FAULT_F)
        self.assertEqual(d["next"], "什么都不改")

    def test_low_interaction_is_not_a_fault(self):
        # 互动低不单列为故障；留人好 → F，仅可选加结尾钩
        d = fd.diagnose(show=1000, read=100, ctr=5.0, cr=0.5, cr_rank=70, dur=60, itr_rank=10)
        self.assertEqual(d["fault"], FAULT_F)

    def test_returned_schema(self):
        d = fd.diagnose(show=1000, read=100, ctr=5.0)
        for k in ("tier", "pool", "click", "keep", "inter", "fault", "next",
                  "susp", "notes", "insufficiency"):
            self.assertIn(k, d)

    def test_deterministic(self):
        args = dict(show=1000, read=100, ctr=5.0, cr=0.5, cr_rank=45, dur=30, itr_rank=70)
        self.assertEqual(fd.diagnose(**args), fd.diagnose(**args))


class DiagnosisIntegrationTest(TempDirMixin, unittest.TestCase):
    """用 fixture 数据在干净环境跑整个脚本，验证输出与「样本不足」纪律。"""

    def test_low_data_rows_marked_insufficient_not_content_fault(self):
        root = self.make_tempdir("fd_root_")
        snap_dir = os.path.join(root, "reports", "tt_snapshots")
        os.makedirs(snap_dir)
        snap = {"date": "2026-08-01", "articles": [
            {"item_id": "1", "title": "低数据猫", "item_status": 20, "publish_time": 0,
             "show": 50, "read": 2},
            {"item_id": "2", "title": "大池猫稿", "item_status": 20, "publish_time": 0,
             "show": 1000, "read": 100},
        ]}
        with open(os.path.join(snap_dir, "2026-08-01.json"), "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False)
        first = {"rows": [
            {"pub_date": "2026-08-01", "title": "低数据猫",
             "first_show": 50, "first_read": 2, "first_ctr": 4.0},
            {"pub_date": "2026-08-01", "title": "大池猫稿",
             "first_show": 1000, "first_read": 100, "first_ctr": 7.0},
        ]}
        with open(os.path.join(root, "reports", "首日指标.json"), "w", encoding="utf-8") as f:
            json.dump(first, f, ensure_ascii=False)
        r = run_script("funnel_diagnosis.py", env={"CONTENT_OPS_ROOT": root})
        self.assertEqual(r.returncode, 0, r.stderr)

        report = os.path.join(
            root, "reports", "漏斗诊断-%s.md" % datetime.date.today().isoformat())
        self.assertTrue(os.path.exists(report), "应产出诊断报告")
        with open(report, encoding="utf-8") as f:
            text = f.read()
        self.assertIn(FAULT_A, text)

        low_row = [ln for ln in text.splitlines() if "低数据猫" in ln]
        self.assertEqual(len(low_row), 1)
        # 低数据 + 阅读<5 → 必须落 A 档，绝不能给出 C/D 这类内容层结论
        self.assertIn(FAULT_A, low_row[0])
        self.assertNotIn(FAULT_C, low_row[0])
        self.assertNotIn(FAULT_D, low_row[0])


if __name__ == "__main__":
    unittest.main()
