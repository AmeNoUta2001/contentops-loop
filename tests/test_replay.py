# -*- coding: utf-8 -*-
"""JEV 离线回放 —— 时间切分与未来信息泄漏检测。

被测脚本（都是「跑起来执行」型，没有干净的纯函数可导入，故用 subprocess + fixture 输出）：
  scripts/jev_replay_dataset.py  —— 建 as-of 数据集（首日窗口：发布 >=12:00 取次日）
  scripts/jev_replay_build.py     —— 建回放单元（asof_snapshot = replay_date - 1，只用 ≤asof 的快照）
  scripts/jev_replay_analyze.py   —— 分析 + as_of 越界复核

泄漏判据：
  · 任何发布/快照日期 > as_of 的数据都不得进入该单元输入；
  · asof_snapshot >= replay_date 必须被识别为「越界」。
"""
import datetime
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# platform_time 必须等 scripts/ 挂上 sys.path 之后再导入
import platform_time   # fixture 时间戳按平台时区构造，保证跨机器一致
from _harness import REPO_ROOT, TempDirMixin, run_script


RAW_PATH = "/tmp/jev_replay_raw.jsonl"


def ts(date_str, hour):
    return int(datetime.datetime.fromisoformat("%sT%02d:00:00" % (date_str, hour))
                   .replace(tzinfo=platform_time.TZ).timestamp())


def art(iid, title, show_date, hour, show, read):
    return {"item_id": iid, "title": title, "item_status": 20,
            "publish_time": ts(show_date, hour), "show_date": show_date,
            "show": show, "read": read,
            "ctr_calc": round(read / show * 100, 2) if show else 0, "traffic": None}


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class ReplayWorkspaceMixin(TempDirMixin):
    def make_workspace(self, snapshots):
        """建一个 CONTENT_OPS_ROOT：reports/tt_snapshots + reports/jev-replay + 空 cron 输出目录。"""
        ws = self.make_tempdir("replay_ws_")
        sd = os.path.join(ws, "reports", "tt_snapshots")
        os.makedirs(sd)
        jr = os.path.join(ws, "reports", "jev-replay")
        os.makedirs(jr)
        home = os.path.join(ws, "home")
        co = os.path.join(home, ".hermes", "profiles", "poster", "cron", "output")
        for job in ("f2e5291f41da", "fdb00de0d0f0"):
            os.makedirs(os.path.join(co, job))
        for date, arts in snapshots.items():
            with open(os.path.join(sd, date + ".json"), "w", encoding="utf-8") as f:
                json.dump({"date": date, "articles": arts}, f, ensure_ascii=False)
        return ws, sd, jr, home

    def env_for(self, ws, home):
        return {"CONTENT_OPS_ROOT": ws, "HOME": home}


class ReplayDatasetTest(ReplayWorkspaceMixin, unittest.TestCase):
    """jev_replay_dataset.py：首日窗口取「发布日（<12:00）或次日（>=12:00）」的首个快照。"""

    def test_first_day_window_and_no_future(self):
        snaps = {
            "2026-04-01": [art("M", "早稿", "2026-04-01", 6, 1000, 80),
                           art("N", "晚稿", "2026-04-01", 13, 400, 30)],
            "2026-04-02": [art("M", "早稿", "2026-04-01", 6, 1200, 90),
                           art("N", "晚稿", "2026-04-01", 13, 700, 50)],
        }
        ws, sd, jr, home = self.make_workspace(snaps)
        r = run_script("jev_replay_dataset.py", env=self.env_for(ws, home))
        self.assertEqual(r.returncode, 0, r.stderr)

        data = read_json(os.path.join(jr, "asof_articles.json"))
        by_id = {row["item_id"]: row for row in data["rows"]}
        # 06:00 发布 → 首日 = 04-01 → 取 04-01 快照的 show
        self.assertEqual(by_id["M"]["firstday_asof"], "2026-04-01")
        self.assertEqual(by_id["M"]["first_show"], 1000)
        # 13:00 发布 → 首日 = 04-02 → 取 04-02 快照的 show（不是 04-01 的 400）
        self.assertEqual(by_id["N"]["firstday_asof"], "2026-04-02")
        self.assertEqual(by_id["N"]["first_show"], 700)


class ReplayBuildTest(ReplayWorkspaceMixin, unittest.TestCase):
    """jev_replay_build.py：asof_snapshot = replay_date-1；未来数据绝不进入输入。"""

    def _build_ws(self):
        days = ["2026-03-%02d" % d for d in range(1, 13)]
        snaps = {}
        for i, d in enumerate(days):
            nxt = days[i + 1] if i + 1 < len(days) else "2026-03-13"
            snaps[d] = [art("old", "旧稿A", "2026-03-01", 6, 500, 40),
                        art("fut", "未来稿F_%s" % d, nxt, 6, 999, 99)]
        ws, sd, jr, home = self.make_workspace(snaps)
        # 12 条候选 → prevday 都落在快照窗内（>=11 条可避开脚本尾部的 units[10] 索引）
        scorable = [{"pub_date": d, "title": "候选%s" % d,
                     "first_show": 800, "first_read": 60, "first_ctr": 7.5,
                     "first_src": "snapshot"}
                    for d in days[1:] + ["2026-03-13"]]
        with open(os.path.join(jr, "scorable_set.json"), "w", encoding="utf-8") as f:
            json.dump(scorable, f, ensure_ascii=False)
        return ws, sd, jr, home

    def test_asof_never_reaches_replay_date(self):
        ws, sd, jr, home = self._build_ws()
        r = run_script("jev_replay_build.py", env=self.env_for(ws, home))
        self.assertEqual(r.returncode, 0, r.stderr)
        units = read_json(os.path.join(jr, "replay_units.json"))
        self.assertEqual(len(units), 12)
        bad = [u for u in units if u["asof_snapshot"] >= u["replay_date"]]
        self.assertEqual(bad, [], "asof_snapshot 必须严格早于 replay_date")

    def test_future_published_article_excluded_from_input(self):
        ws, sd, jr, home = self._build_ws()
        r = run_script("jev_replay_build.py", env=self.env_for(ws, home))
        self.assertEqual(r.returncode, 0, r.stderr)
        units = read_json(os.path.join(jr, "replay_units.json"))
        # asof=2026-03-01 的单元：快照里有一篇发布日 03-02 的「未来稿」，必须被排除
        u = [x for x in units if x["asof_snapshot"] == "2026-03-01"][0]
        titles = u["self_state"]["recent14_titles"]
        self.assertIn("旧稿A", titles)
        self.assertFalse(any("未来稿" in t for t in titles),
                         "比 as_of 晚发布的数据泄漏进了输入：%r" % (titles,))
        self.assertGreaterEqual(u["self_state"]["first_asof_ok"], 1)

    def test_input_sha_deterministic(self):
        ws, sd, jr, home = self._build_ws()
        r1 = run_script("jev_replay_build.py", env=self.env_for(ws, home))
        self.assertEqual(r1.returncode, 0, r1.stderr)
        first = {u["unit_id"]: u["input_sha256"]
                 for u in read_json(os.path.join(jr, "replay_units.json"))}
        r2 = run_script("jev_replay_build.py", env=self.env_for(ws, home))
        self.assertEqual(r2.returncode, 0, r2.stderr)
        second = {u["unit_id"]: u["input_sha256"]
                  for u in read_json(os.path.join(jr, "replay_units.json"))}
        self.assertEqual(first, second)


class ReplayAnalyzeBoundaryTest(ReplayWorkspaceMixin, unittest.TestCase):
    """jev_replay_analyze.py：asof_snapshot >= replay_date 必须被识别为越界。"""

    def setUp(self):
        self._raw_backup = None
        if os.path.exists(RAW_PATH):
            with open(RAW_PATH, "rb") as f:
                self._raw_backup = f.read()

    def tearDown(self):
        if self._raw_backup is None:
            if os.path.exists(RAW_PATH):
                os.remove(RAW_PATH)
        else:
            with open(RAW_PATH, "wb") as f:
                f.write(self._raw_backup)

    def _row(self, uid, rdate):
        return {"unit_id": uid, "replay_date": rdate, "candidate_title": "标题%s" % uid,
                "label": {"first_ctr": 7.0, "first_show": 800, "first_read": 56},
                "answers": {"P_点击过线": 0.9, "P_推荐为下一篇": 0.8, "S_优先级": 3.0,
                            "P_大池": 0.5, "P_撞族重复": 0.2, "P_风险": 0.1}}

    def _run(self, asof, replay):
        ws, sd, jr, home = self.make_workspace({})
        with open(os.path.join(jr, "replay_units.json"), "w", encoding="utf-8") as f:
            json.dump([{"unit_id": "U1", "replay_date": replay, "asof_snapshot": asof}],
                      f, ensure_ascii=False)
        with open(os.path.join(jr, "audit4_tiers.json"), "w", encoding="utf-8") as f:
            json.dump([[replay, "x", "小高峰档"]], f, ensure_ascii=False)
        with open(RAW_PATH, "w", encoding="utf-8") as f:
            f.write(json.dumps(self._row("U1", replay), ensure_ascii=False) + "\n")
        r = run_script("jev_replay_analyze.py", env=self.env_for(ws, home))
        self.assertEqual(r.returncode, 0, r.stderr)
        report = read_text(os.path.join(jr, "analysis_report.txt"))
        self.assertTrue(os.path.exists(os.path.join(jr, "analysis.json")))
        return report

    def test_boundary_violation_is_flagged(self):
        report = self._run(asof="2026-03-03", replay="2026-03-03")   # asof >= replay
        line = [l for l in report.splitlines() if "越界" in l]
        self.assertEqual(len(line), 1, report[-500:])
        self.assertIn("异常", line[0])
        self.assertIn("1", line[0])

    def test_valid_asof_passes(self):
        report = self._run(asof="2026-03-02", replay="2026-03-03")   # asof < replay
        line = [l for l in report.splitlines() if "越界" in l]
        self.assertEqual(len(line), 1)
        self.assertIn("通过", line[0])


if __name__ == "__main__":
    unittest.main()
