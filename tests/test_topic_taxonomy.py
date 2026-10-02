# -*- coding: utf-8 -*-
"""topic_taxonomy.py —— 确定性题材分类器。

覆盖：题材族首个命中优先 / off_vertical 否决 / motif_must(AND) / manual_overrides 最高优先 /
      置信度按命中词数 / 未命中必须「未归类」不硬猜。

注：代码里的实际优先级是 manual_overrides → off_vertical → 题材族 → 母题，
    **不是** off_vertical 绝对优先（人工订正压过一切）。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import import_script

tax = import_script("topic_taxonomy")


class TaxonomyTest(unittest.TestCase):

    KEYS = {"topic_family", "family_kw", "motif", "motif_kw", "confidence"}

    def test_returns_full_schema(self):
        got = tax.classify("随便什么标题")
        self.assertEqual(set(got), self.KEYS)

    # ---------- 题材族：顺序 = 优先级，首个命中就赢 ----------
    def test_family_first_match_wins(self):
        # 同时含「绝育」(宠物健康, 配置里排第一) 与「猫」(养猫日常, 排第七)
        got = tax.classify("绝育后的猫")
        self.assertEqual(got["topic_family"], "宠物健康")
        self.assertEqual(got["family_kw"], ["绝育"])

    def test_family_later_rule_hits_when_earlier_miss(self):
        got = tax.classify("猫砂要这样选")
        self.assertEqual(got["topic_family"], "养猫日常")
        self.assertEqual(set(got["family_kw"]), {"猫", "猫砂"})

    # ---------- off_vertical：命中即判跨赛道，压过题材族/母题 ----------
    def test_off_vertical_vetoes_family_and_motif(self):
        got = tax.classify("猫粮股价大涨")   # 有「猫粮」，也有「股价」(off_vertical)
        self.assertEqual(got["topic_family"], "跨赛道")
        self.assertEqual(got["motif"], "跨赛道（不计入）")
        self.assertEqual(got["confidence"], "high")

    def test_off_vertical_second_word(self):
        got = tax.classify("亚运会金牌拿了多少")
        self.assertEqual(got["topic_family"], "跨赛道")
        self.assertEqual(got["family_kw"], ["亚运"])

    # ---------- manual_overrides：优先级最高（高于 off_vertical）----------
    def test_manual_override_beats_everything(self):
        # 标题同时含 off_vertical 词「股价」和人工订正子串「某明星的猫」
        got = tax.classify("股价跌了，某明星的猫上热搜")
        self.assertEqual(got["topic_family"], "跨垂类")
        self.assertEqual(got["motif"], "跨垂类（不计入）")
        self.assertEqual(got["confidence"], "high")
        self.assertTrue(got["motif_kw"][0].startswith("人工订正:"),
                        "人工订正应留痕，实得 %r" % (got["motif_kw"],))

    # ---------- motif_must：AND 组不满足 → 不认该母题 ----------
    def test_motif_must_blocks_when_and_group_unsatisfied(self):
        # 「喂多了」是「宠物减肥」母题词，但 AND 组 {胖,减肥,体重} 一个都没命中 → 不认
        got = tax.classify("给猫喂多了吐了")
        self.assertNotEqual(got["motif"], "宠物减肥")
        self.assertEqual(got["motif"], "未归类")
        self.assertEqual(got["motif_kw"], [])

    def test_motif_must_passes_when_and_group_satisfied(self):
        got = tax.classify("猫太胖了怎么办")   # 命中「太胖」，AND 组的「胖」也在
        self.assertEqual(got["motif"], "宠物减肥")
        self.assertIn("太胖", got["motif_kw"])

    # ---------- 置信度按命中词数（>= strong_kw_hits 为 high）----------
    def test_confidence_high_when_hits_ge_strong(self):
        self.assertEqual(tax.STRONG, 2)
        got = tax.classify("半夜跑酷停不下来")
        self.assertEqual(got["motif"], "半夜折腾")
        self.assertEqual(sorted(got["motif_kw"]), sorted(["半夜", "跑酷"]))
        self.assertGreaterEqual(len(got["motif_kw"]), tax.STRONG)
        self.assertEqual(got["confidence"], "high")

    def test_confidence_low_when_single_hit(self):
        got = tax.classify("半夜睡不着")
        self.assertEqual(got["motif"], "半夜折腾")
        self.assertEqual(got["motif_kw"], ["半夜"])
        self.assertEqual(got["confidence"], "low")

    # ---------- 未命中：必须「未归类」而不是硬猜 ----------
    def test_no_match_is_unclassified_not_guessed(self):
        got = tax.classify("今天天气不错适合出门")
        self.assertEqual(got["topic_family"], "其他")
        self.assertEqual(got["family_kw"], [])
        self.assertEqual(got["motif"], "未归类")
        self.assertEqual(got["motif_kw"], [])
        self.assertEqual(got["confidence"], "none")

    def test_family_hit_but_motif_still_unclassified(self):
        got = tax.classify("猫砂要这样选才对")
        self.assertEqual(got["topic_family"], "养猫日常")   # 族命中
        self.assertEqual(got["motif"], "未归类")             # 母题不硬猜

    def test_whitespace_normalized(self):
        self.assertEqual(tax.classify("猫 砂 要 选"),
                         tax.classify("猫砂要选"))

    def test_empty_title_is_unclassified(self):
        for t in (None, "", "   "):
            got = tax.classify(t)
            self.assertEqual(got["motif"], "未归类")
            self.assertEqual(got["confidence"], "none")

    def test_deterministic(self):
        t = "绝育后的猫半夜踩脸"
        self.assertEqual(tax.classify(t), tax.classify(t))


if __name__ == "__main__":
    unittest.main()
