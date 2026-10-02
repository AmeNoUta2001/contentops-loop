#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""platform_time —— 统一「平台时区」，不依赖运行机器上的本地时区。

为什么必须有这个模块
--------------------
平台返回的是 Unix 时间戳。用 `datetime.datetime.fromtimestamp(ts)` 去解释它，
得到的是**运行机器本地时区**下的时间 —— 同一批数据在 UTC 机器和北京机器上会解析成不同的
日期/小时，进而改变「首日窗口」的判定，甚至把快照里的 `show_date` 算到前一天。

这会直接违背项目最核心的承诺：**同样的输入，同样的输出。**
（这个 bug 是 CI 在 UTC runner 上跑出来的：本地 CST 全绿，GitHub 上失败。）

所以：**凡是解释平台时间戳、或取「今天」用于数据归属的地方，一律走这里。**

时区可以是配置：
    CONTENTOPS_TZ_OFFSET=8      # 默认 +8（北京时间）
    CONTENTOPS_TZ_OFFSET=0      # UTC
"""
import datetime
import os
import time

try:
    OFFSET_HOURS = float(os.environ.get('CONTENTOPS_TZ_OFFSET', '8'))
except ValueError:                                              # 配错了就退回默认，别崩
    OFFSET_HOURS = 8.0

TZ = datetime.timezone(datetime.timedelta(hours=OFFSET_HOURS), name='platform')


def from_ts(ts):
    """时间戳 → 平台时区下的 datetime（替代 datetime.datetime.fromtimestamp）。"""
    try:
        return datetime.datetime.fromtimestamp(int(ts), TZ)
    except (TypeError, ValueError, OSError):
        return datetime.datetime.fromtimestamp(0, TZ)


def now():
    """平台时区下的当前时间（替代 datetime.datetime.now）。"""
    return datetime.datetime.now(TZ)


def today():
    """平台时区下的今天（替代 datetime.date.today），返回 date 对象。"""
    return now().date()


def today_str():
    """平台时区下的今天，ISO 字符串。"""
    return today().isoformat()


def date_of_ts(ts):
    """时间戳 → 平台时区下的日期字符串。"""
    return from_ts(ts).date().isoformat()


if __name__ == '__main__':
    print(f"OFFSET_HOURS = {OFFSET_HOURS}")
    print(f"now()        = {now().isoformat(timespec='seconds')}")
    print(f"today_str()  = {today_str()}")
    print(f"本机 datetime.now() = {datetime.datetime.now().isoformat(timespec='seconds')}"
          f"   ← 仅作对比，产品代码不该用它做数据归属")
