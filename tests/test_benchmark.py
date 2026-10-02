# -*- coding: utf-8 -*-
"""benchmark_store.py —— 纯函数：num() / tier_of() / age_bucket() / niche_of() / quant()。

另外补测「n < min_n_quantile 不给分位」与桶内相对档 —— 这两个门实际位于
topic_taxonomy.py（rel_tier_of / tier_own），benchmark_store 只做数据归一与聚合，
所以此处从 topic_taxonomy 导入被测函数并注明。
"""
import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import import_script

bs = import_script("benchmark_store")
tax = import_script("topic_taxonomy")


class NumTest(unittest.TestCase):
    def test_wan_suffix(self):
        self.assertEqual(bs.num("2.4万"), 24000)
        self.assertEqual(bs.num("1万"), 10000)
        self.assertEqual(bs.num("1.5万"), 15000)
        self.assertEqual(bs.num("0.5万"), 5000)
        self.assertEqual(bs.num(" 2.4万 "), 24000, "应 strip 空白")

    def test_plain_numbers(self):
        self.assertEqual(bs.num("24000"), 24000)
        self.assertEqual(bs.num("1,234"), 1234, "应去掉千分位逗号")
        self.assertEqual(bs.num("12.5"), 12, "小数取整")
        self.assertEqual(bs.num(100), 100)

    def test_unavailable_is_none(self):
        for v in (None, "", "   ", "不可见", "-", "—", "abc", "万", "约2万"):
            self.assertIsNone(bs.num(v), "num(%r) 应为 None" % (v,))


class TierOfTest(unittest.TestCase):
    def test_fan_tiers(self):
        self.assertEqual(bs.tier_of("9999"), "<1万")
        self.assertEqual(bs.tier_of("10000"), "1-10万", "1万 边界")
        self.assertEqual(bs.tier_of("99999"), "1-10万")
        self.assertEqual(bs.tier_of("100000"), "≥10万", "10万 边界")
        self.assertEqual(bs.tier_of("2.4万"), "1-10万")
        self.assertEqual(bs.tier_of("0"), "<1万")

    def test_unknown_fans(self):
        self.assertEqual(bs.tier_of(None), "未知")
        self.assertEqual(bs.tier_of("不可见"), "未知")


class AgeBucketTest(unittest.TestCase):
    def setUp(self):
        self.dt = datetime.datetime(2026, 9, 20, 12, 0)

    def bucket(self, s, dt=None):
        return bs.age_bucket(s, self.dt if dt is None else dt)

    def test_hour_boundaries(self):
        self.assertEqual(self.bucket("1分钟前"), "<24h")
        self.assertEqual(self.bucket("23小时前"), "<24h")
        self.assertEqual(self.bucket("24小时前"), "1-3d", "24h 边界进 1-3d")
        self.assertEqual(self.bucket("71小时前"), "1-3d")
        self.assertEqual(self.bucket("72小时前"), "3-7d", "72h 边界进 3-7d")
        self.assertEqual(self.bucket("167小时前"), "3-7d")
        self.assertEqual(self.bucket("168小时前"), "7-30d", "168h 边界进 7-30d")
        self.assertEqual(self.bucket("719小时前"), "7-30d")
        self.assertEqual(self.bucket("720小时前"), ">30d", "720h 边界进 >30d")

    def test_day_keywords(self):
        self.assertEqual(self.bucket("昨天"), "1-3d")
        self.assertEqual(self.bucket("前天"), "1-3d")
        self.assertEqual(self.bucket("2天前"), "1-3d")
        self.assertEqual(self.bucket("3天前"), "3-7d")
        self.assertEqual(self.bucket("7天前"), "7-30d")
        self.assertEqual(self.bucket("30天前"), ">30d")
        self.assertEqual(self.bucket("刚刚"), "<24h")
        self.assertEqual(self.bucket("刚才"), "<24h")

    def test_date_strings(self):
        self.assertEqual(self.bucket("09-19"), "1-3d")
        self.assertEqual(self.bucket("2026年9月19日"), "1-3d")
        self.assertEqual(self.bucket("2026年9月20日"), "<24h")

    def test_unknown(self):
        self.assertEqual(self.bucket("乱写"), "未知")
        self.assertEqual(self.bucket(None), "未知")
        self.assertEqual(self.bucket(""), "未知")
        self.assertEqual(bs.age_bucket("1天前", None), "未知", "无采集时刻 → 未知")


class NicheOfTest(unittest.TestCase):
    def test_on(self):
        ts = ["猫猫猫猫猫猫", "狗狗狗狗狗狗", "宠物宠物宠物", "猫粮猫粮猫粮", "狗粮狗粮狗粮"]
        niche, pos, n = bs.niche_of(ts)
        self.assertEqual((niche, pos, n), ("on", 5, 5))

    def test_mixed(self):
        ts = ["猫猫猫猫猫猫", "狗狗狗狗狗狗", "今天天气真好啊", "随便写点东西啊", "无关内容标题"]
        niche, pos, n = bs.niche_of(ts)
        self.assertEqual(niche, "mixed")
        self.assertEqual(pos, 2)

    def test_off_when_cross_vertical_evidence(self):
        ts = ["股价大涨了吗", "芯片行业观察", "财经早知道啊"]
        niche, pos, n = bs.niche_of(ts)
        self.assertEqual((niche, pos, n), ("off", 0, 3))

    def test_unknown_when_no_evidence_either_way(self):
        ts = ["今天天气真好呀", "随便写点东西呀", "生活记录一下", "日常碎碎念啊", "周末去哪玩呢"]
        self.assertEqual(bs.niche_of(ts)[0], "unknown")

    def test_title_with_both_pos_and_neg_counts_as_neither(self):
        # 「猫」是赛道内词，「股价」是赛道外词；同一条标题两个都命中 → 既不算 pos 也不算 neg
        self.assertEqual(bs.niche_of(["猫和股价都涨了"]), ("unknown", 0, 1))

    def test_empty_titles(self):
        self.assertEqual(bs.niche_of([]), ("unknown", 0, 0))
        self.assertEqual(bs.niche_of(["猫", "（置顶）"]), ("unknown", 0, 0),
                         "过短/占位标题应被过滤")


class QuantTest(unittest.TestCase):
    def test_empty(self):
        self.assertIsNone(bs.quant([], 0.5))

    def test_endpoints(self):
        self.assertEqual(bs.quant([1, 2, 3], 0.0), 1)
        self.assertEqual(bs.quant([1, 2, 3], 1.0), 3)


class MinNQuantileGateTest(unittest.TestCase):
    """n < min_n_quantile → 不给分位结论（诚实纪律）。"""

    def test_below_min_n_is_insufficient(self):
        min_n = int(tax._vertical.threshold("min_n_quantile"))
        self.assertGreaterEqual(min_n, 1)
        vals = list(range(1, min_n + 1))          # 恰好 min_n 个
        self.assertNotEqual(tax.rel_tier_of(1, vals), "样本不足")
        self.assertEqual(tax.rel_tier_of(1, vals[:-1]), "样本不足",
                         "样本 < %d 时必须返回「样本不足」" % min_n)

    def test_relative_tiers_within_bucket(self):
        vals = [10, 20, 30, 40, 50, 60, 70, 80]
        self.assertEqual(tax.rel_tier_of(60, vals), "前25%")
        self.assertEqual(tax.rel_tier_of(59, vals), "中50%")
        self.assertEqual(tax.rel_tier_of(30, vals), "中50%")
        self.assertEqual(tax.rel_tier_of(29, vals), "后25%")
        self.assertEqual(tax.rel_tier_of(None, vals), "无数据")

    def test_tier_own_by_first_ctr(self):
        self.assertEqual(tax.tier_own(5.0), "高")
        self.assertEqual(tax.tier_own(4.0), "高")
        self.assertEqual(tax.tier_own(2.0), "中")
        self.assertEqual(tax.tier_own(0.5), "低")
        self.assertEqual(tax.tier_own(None), "无数据")


if __name__ == "__main__":
    unittest.main()
