# -*- coding: utf-8 -*-
"""first_day_metrics.py —— 首日窗口 / traffic 优先 / 去重 / 爆款剔除 / 确定性。

被测单元：scripts/first_day_metrics.py 的 build()（纯读快照，无网络）。
测试手法：把模块的 SNAP_DIR 指到临时快照目录（或 tests/fixtures/snapshots），
          build() 之后恢复，避免相互污染。
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import (STATIC_SNAPSHOTS, TempDirMixin, import_script,
                      make_article, write_snapshots)

fdm = import_script("first_day_metrics")


def traffic_daily(rows):
    return {"daily": [{"date": d, "impression": imp, "read": rd} for d, imp, rd in rows]}


class FirstDayMetricsTest(TempDirMixin, unittest.TestCase):

    # ---------- 通用脚手架 ----------
    def build_from(self, snapshots):
        d = write_snapshots(os.path.join(self.make_tempdir(), "snaps"), snapshots)
        return self.build_dir(d)

    def build_dir(self, dirpath):
        old = fdm.SNAP_DIR
        fdm.SNAP_DIR = dirpath
        self.addCleanup(setattr, fdm, "SNAP_DIR", old)
        return fdm.build()

    def row(self, out, title):
        hit = [r for r in out["rows"] if r["title"] == title]
        self.assertEqual(len(hit), 1, "标题 %r 应恰好出现一行，实得 %d" % (title, len(hit)))
        return hit[0]

    def pool(self, out, topic):
        hit = [p for p in out["pool"] if p["topic"] == topic]
        self.assertEqual(len(hit), 1, "题材 %r 应恰好一个池子条目，实得 %d" % (topic, len(hit)))
        return hit[0]

    # ---------- 1. 首日窗口：发布早于/晚于 12:00 ----------
    def test_window_before_noon_uses_pubdate_snapshot(self):
        """发布时刻 <=12:00 → 首日窗口取发布当日快照。"""
        snaps = {
            "2026-03-01": [
                make_article("1", "早稿猫", "2026-03-01", 8, 500, 25),
                make_article("2", "正午猫", "2026-03-01", 12, 700, 35),
                make_article("3", "午后猫", "2026-03-01", 13, 800, 40),
                make_article("4", "晚稿猫", "2026-03-01", 14, 600, 30),
            ],
            "2026-03-02": [
                make_article("1", "早稿猫", "2026-03-01", 8, 900, 45),
                make_article("2", "正午猫", "2026-03-01", 12, 1100, 55),
                make_article("3", "午后猫", "2026-03-01", 13, 1200, 60),
                make_article("4", "晚稿猫", "2026-03-01", 14, 1000, 50),
            ],
        }
        out = self.build_from(snaps)
        # hour 8：取发布当日
        self.assertEqual(self.row(out, "早稿猫")["first_show"], 500)
        self.assertEqual(self.row(out, "早稿猫")["src"], "快照2026-03-01")
        # hour 12 恰好不满足 `> 12` → 仍是发布当日（边界）
        self.assertEqual(self.row(out, "正午猫")["first_show"], 700)
        self.assertEqual(self.row(out, "正午猫")["src"], "快照2026-03-01")

    def test_window_after_noon_uses_next_day_snapshot(self):
        """发布时刻 >12:00 → 首日窗口取次日快照（d1 = pub_date + 1）。"""
        snaps = {
            "2026-03-01": [
                make_article("3", "午后猫", "2026-03-01", 13, 800, 40),
                make_article("4", "晚稿猫", "2026-03-01", 14, 600, 30),
            ],
            "2026-03-02": [
                make_article("3", "午后猫", "2026-03-01", 13, 1200, 60),
                make_article("4", "晚稿猫", "2026-03-01", 14, 1000, 50),
            ],
        }
        out = self.build_from(snaps)
        self.assertEqual(self.row(out, "午后猫")["first_show"], 1200)
        self.assertEqual(self.row(out, "午后猫")["src"], "快照2026-03-02")
        self.assertEqual(self.row(out, "晚稿猫")["first_show"], 1000)
        self.assertEqual(self.row(out, "晚稿猫")["src"], "快照2026-03-02")

    # ---------- 2. traffic.daily 优先于快照累计值 ----------
    def test_traffic_daily_preferred_over_snapshot(self):
        a = make_article("1", "有流量的猫", "2026-04-01", 8, 500, 25,
                         traffic=traffic_daily([("2026-04-01", 777, 50)]))
        out = self.build_from({"2026-04-01": [a]})
        r = self.row(out, "有流量的猫")
        self.assertEqual(r["first_show"], 777, "首日曝光应取 traffic.daily，而不是快照累计 500")
        self.assertEqual(r["first_read"], 50)
        self.assertEqual(r["src"], "traffic")
        self.assertEqual(r["total_show"], 500, "累计展仍来自快照")

    def test_traffic_falls_back_to_first_daily_row(self):
        """traffic.daily 里没有发布日那行 → 退用首条，src 标记 'traffic首条'。"""
        a = make_article("1", "错日流量的猫", "2026-04-02", 8, 600, 30,
                         traffic=traffic_daily([("2026-04-01", 111, 9)]))
        out = self.build_from({"2026-04-02": [a]})
        r = self.row(out, "错日流量的猫")
        self.assertEqual(r["first_show"], 111)
        self.assertEqual(r["src"], "traffic首条")

    # ---------- 3. 按标题去重，保留累计展现更大的那条 ----------
    def test_dedup_by_title_keeps_larger_show(self):
        snaps = {"2026-05-01": [
            make_article("a", "重复标题猫", "2026-05-01", 8, 100, 5),
            make_article("b", "重复标题猫", "2026-05-01", 8, 900, 45),
            make_article("c", "另一篇猫", "2026-05-01", 8, 50, 3),
        ]}
        out = self.build_from(snaps)
        r = self.row(out, "重复标题猫")   # row() 已断言只剩一行
        self.assertEqual(r["first_show"], 900, "应保留累计展现更大的第 b 条")
        self.assertEqual(r["total_show"], 900)
        self.assertEqual(len(out["rows"]), 2, "去重后应只剩 2 篇")

    def test_article_status_not_20_is_dropped_in_dedup(self):
        """非「已发布」(item_status!=20) 的条目不参与去重池。"""
        snaps = {"2026-05-02": [
            make_article("a", "草稿猫", "2026-05-02", 8, 999, 99, status=10),
            make_article("b", "已发猫", "2026-05-02", 8, 100, 5),
        ]}
        out = self.build_from(snaps)
        titles = {r["title"] for r in out["rows"]}
        self.assertIn("已发猫", titles)
        self.assertNotIn("草稿猫", titles)

    # ---------- 4. 爆款（首日曝光 >= viral_show）被排除出稳定池中位 ----------
    def test_viral_excluded_from_stable_median(self):
        snaps = {"2026-06-01": [
            make_article("1", "猫甲", "2026-06-01", 8, 400, 20),
            make_article("2", "猫乙", "2026-06-01", 8, 600, 30),
            make_article("3", "猫丙", "2026-06-01", 8, 6000, 300),  # >= viral_show(5000)
        ]}
        out = self.build_from(snaps)
        p = self.pool(out, "养猫日常")
        self.assertEqual(p["n"], 3)
        self.assertEqual(p["n_stable"], 2, "爆款不应计入稳定池")
        self.assertEqual(p["med_first_show"], 600, "含爆款中位（[400,600,6000] 中位=600）")
        self.assertEqual(p["med_first_show_stable"], 500, "剔爆款中位（[400,600] 中位=500）")
        self.assertEqual(p["risk"], "含爆款")

    def test_all_viral_topic_flagged_pollution(self):
        snaps = {"2026-06-02": [
            make_article("1", "猫甲", "2026-06-02", 8, 6000, 300),
            make_article("2", "猫乙", "2026-06-02", 8, 7000, 350),
        ]}
        out = self.build_from(snaps)
        p = self.pool(out, "养猫日常")
        self.assertEqual(p["n_stable"], 0)
        self.assertIsNone(p["med_first_show_stable"], "稳定池为空 → 不给稳定中位")
        self.assertEqual(p["risk"], "爆款污染")

    # ---------- 5. 确定性：同一输入两次结果一致 ----------
    def test_same_input_twice_is_identical(self):
        snaps = {
            "2026-07-01": [make_article("1", "猫甲", "2026-07-01", 14, 500, 25)],
            "2026-07-02": [make_article("1", "猫甲", "2026-07-01", 14, 800, 40),
                           make_article("2", "猫乙", "2026-07-02", 8, 900, 50)],
        }
        d = write_snapshots(os.path.join(self.make_tempdir(), "snaps"), snaps)
        old = fdm.SNAP_DIR
        fdm.SNAP_DIR = d
        self.addCleanup(setattr, fdm, "SNAP_DIR", old)
        first = json.dumps(fdm.build(), ensure_ascii=False, sort_keys=True)
        second = json.dumps(fdm.build(), ensure_ascii=False, sort_keys=True)
        self.assertEqual(first, second)

    def test_static_fixture_is_deterministic(self):
        a = json.dumps(self.build_dir(STATIC_SNAPSHOTS), ensure_ascii=False, sort_keys=True)
        b = json.dumps(self.build_dir(STATIC_SNAPSHOTS), ensure_ascii=False, sort_keys=True)
        self.assertEqual(a, b)

    # ---------- 6. 静态 fixture 的整段行为 ----------
    def test_static_fixture_expected_rows(self):
        out = self.build_dir(STATIC_SNAPSHOTS)
        self.assertEqual(out["date"], "2026-02-03")
        self.assertEqual(len(out["rows"]), 6)

        r1 = self.row(out, "橘猫半夜踩脸睡不好")
        self.assertEqual((r1["first_show"], r1["src"]), (350, "traffic"))

        # 14:00 发布 → 首日窗口取次日（2026-02-02 快照 = 520）
        r2 = self.row(out, "猫砂要这样选才对")
        self.assertEqual((r2["first_show"], r2["src"]), (520, "快照2026-02-02"))

        r3 = self.row(out, "猫粮换牌子终于肯吃")
        self.assertEqual((r3["first_show"], r3["src"]), (200, "快照2026-02-01"))

        # 两个同标题条目 → 去重成一条，取show大的 300
        r5 = self.row(out, "遛狗它突然不肯走")
        self.assertEqual(r5["first_show"], 300)

        # 养狗日常：300 与 6000（爆款）→ 稳定中位 300，含爆款中位 3150
        pdog = self.pool(out, "养狗日常")
        self.assertEqual((pdog["n"], pdog["n_stable"]), (2, 1))
        self.assertEqual(pdog["med_first_show_stable"], 300)
        self.assertEqual(pdog["med_first_show"], 3150.0)
        self.assertEqual(pdog["risk"], "含爆款")

        # 养猫日常：三篇都非爆款，稳定中位 350
        pcat = self.pool(out, "养猫日常")
        self.assertEqual(pcat["med_first_show_stable"], 350)

    def test_config_thresholds_loaded(self):
        """viral_show / own_pass_ctr 来自 config/vertical.json（默认宠物垂类）。"""
        self.assertEqual(fdm.VIRAL_SHOW, 5000)
        self.assertEqual(fdm.PASS_CTR, 4.0)

    def test_render_has_ok_header_and_pool_table(self):
        text = fdm.render(self.build_dir(STATIC_SNAPSHOTS))
        self.assertTrue(text.startswith("FIRSTDAY_OK"))
        self.assertIn("题材池子表", text)


if __name__ == "__main__":
    unittest.main()
