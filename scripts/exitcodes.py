#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""exitcodes —— 统一的进程退出码语义。

为什么要统一：这套脚本会被 **人类 / cron / CI / agent** 四种调用者驱动。
调用者不该靠解析中文输出判断"到底成没成功"，也不该把"没数据"和"跑挂了"混为一谈。

    0   OK                  成功
   10   CREDENTIAL          缺凭据 / 登录态失效（需要人去补 cookie 或 key）
   20   UPSTREAM            上游或平台请求失败（网络、超时、5xx、接口改版）
   30   BAD_DATA            响应格式异常 / 内容损坏 / 解析不了（可能是接口变了）
   40   INSUFFICIENT_DATA   数据不足，无法计算（≠ 失败，但也不该当成成功）
   50   CONFIG              配置或环境问题（缺目录、缺可选依赖、配置写错）
   60   INTEGRITY           完整性校验失败（密文库被改动、指纹不匹配）
   64   USAGE               命令行用法错误

约定：
  · 成功一律 0；失败或"不可继续"一律非 0
  · stdout 保留机器可读的 `PREFIX:` 行（供调度器/agent 判断）
  · 人类可读的解释走 stderr 或同一行的后半段
  · 40（数据不足）刻意与 30/20 区分开：cron 可以据此选择"不告警但也不记录成功"
"""
import sys

OK = 0
CREDENTIAL = 10
UPSTREAM = 20
BAD_DATA = 30
INSUFFICIENT_DATA = 40
CONFIG = 50
INTEGRITY = 60
USAGE = 64

NAMES = {
    OK: 'OK',
    CREDENTIAL: 'CREDENTIAL',
    UPSTREAM: 'UPSTREAM',
    BAD_DATA: 'BAD_DATA',
    INSUFFICIENT_DATA: 'INSUFFICIENT_DATA',
    CONFIG: 'CONFIG',
    INTEGRITY: 'INTEGRITY',
    USAGE: 'USAGE',
}


def die(code, prefix, message):
    """打印机器可读前缀行并以指定退出码结束。"""
    print(f"{prefix}: {message}")
    sys.exit(code)


def name(code):
    return NAMES.get(code, f'UNKNOWN({code})')


if __name__ == '__main__':
    for c in sorted(NAMES):
        print(f"{c:3d}  {NAMES[c]}")
