# -*- coding: utf-8 -*-
"""可移植性：同一份数据在任何本机时区下必须得到同样的结论。

背景
----
平台返回 Unix 时间戳；用 `datetime.datetime.fromtimestamp()` 解释它，
拿到的是**运行机器本地时区**下的日期/小时。同样的数据在 UTC 机器和北京机器上会算出不同的
「首日窗口」，甚至把日期归到前一天 —— 直接违背项目「同样输入同样输出」的承诺。

这个 bug 正是 CI 在 UTC runner 上跑出来的（本地 CST 全绿，GitHub 三个版本里两个失败）。
所以这里用一个测试把它顶住：**用不同 TZ 启动子进程，比对输出必须逐字节相同。**

本地没有子进程能力时不会失败；但它必须真的执行，不能是空壳。
"""
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SCRIPTS = os.path.join(REPO, 'scripts')
sys.path.insert(0, SCRIPTS)

import platform_time  # noqa: E402

TIMEZONES = ['Asia/Shanghai', 'UTC', 'America/New_York', 'Pacific/Kiritimati']


def _run(args, tz, extra_env=None):
    env = dict(os.environ, TZ=tz)
    if extra_env:
        env.update(extra_env)
    return subprocess.run([sys.executable] + args, cwd=REPO, env=env,
                          capture_output=True, text=True, timeout=300)


class PlatformTimezoneIsUsed(unittest.TestCase):

    def test_platform_tz_does_not_depend_on_host_tz(self):
        """platform_time 解释时间戳时用的是固定偏移，与 TZ 环境变量无关。"""
        offsets = set()
        for tz in TIMEZONES:
            r = _run(['scripts/platform_time.py'], tz)
            self.assertEqual(r.returncode, 0, r.stderr)
            offsets.add(r.stdout.split('\n')[0])
        self.assertEqual(len(offsets), 1,
                         f'platform_time 的输出随本机时区变了：{offsets}')

    def test_demo_output_is_identical_across_timezones(self):
        """README 里那条 demo 命令的输出必须与机器时区无关。"""
        outputs = {}
        for tz in TIMEZONES:
            r = _run(['scripts/first_day_metrics.py'], tz,
                     {'CONTENT_OPS_ROOT': os.path.join(REPO, 'examples')})
            self.assertEqual(r.returncode, 0,
                             f'TZ={tz} 时 demo 失败：{r.stdout[-300:]}{r.stderr[-300:]}')
            outputs[tz] = r.stdout
        distinct = set(outputs.values())
        self.assertEqual(len(distinct), 1,
                         'demo 输出随机器时区变化了 —— 说明有地方仍在用本机本地时区。\n'
                         + '\n'.join(f'  TZ={tz}: {o.splitlines()[0][:70]}'
                                     for tz, o in outputs.items()))

    def test_fixture_timestamps_are_built_in_platform_tz(self):
        """fixture 的时间戳按平台时区构造，而不是按运行机器本地时区。"""
        # 08:00 平台时间必须是「早稿」（窗口取当日）
        early = platform_time.from_ts(
            int(__import__('datetime').datetime.fromisoformat('2026-02-01T08:00:00')
                .replace(tzinfo=platform_time.TZ).timestamp()))
        self.assertEqual(early.hour, 8)
        self.assertEqual(early.date().isoformat(), '2026-02-01')


if __name__ == '__main__':
    unittest.main()
