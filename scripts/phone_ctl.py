#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""手机控制小工具（给人/agent 用的原子命令，专为「养号」设计）。

设计意图：把「连设备/截图/点按/停留/回挂机屏」这些机械动作收进脚本，
让 cron agent 每步只花几十个 token（而不用自己拼 adb 命令），
把 token 预算留给真正需要判断的那一步（vision 挑内容）。

用法：
    python3 phone_ctl.py prep                  # 连设备 + 插电常亮 + 醒屏解锁 + 打开头条到首页
    python3 phone_ctl.py shot [路径]           # 截图（默认 /tmp/phone_shot.png），打印路径 + 亮度均值
    python3 phone_ctl.py tap X Y               # 点击
    python3 phone_ctl.py swipe X1 Y1 X2 Y2 [ms]
    python3 phone_ctl.py back|home|idle        # 返回键 / 桌面 / 切挂机屏
    python3 phone_ctl.py dwell SECONDS         # 停留 N 秒（期间随机缓慢滑动 1-3 次，模拟阅读）
    python3 phone_ctl.py focus                 # 打印当前前台窗口
    python3 phone_ctl.py status                # 设备/电量/屏幕状态（一行 JSON）
"""
import asyncio
import json
import os
import random
import subprocess
import sys
import exitcodes
import time

IP = os.environ.get("PHONE_IP", "")
if not IP:
    print(json.dumps({"status": "phone_ip_missing",
                      "hint": "请设置环境变量 PHONE_IP=<手机IP或主机名>"}, ensure_ascii=False))
    sys.exit(exitcodes.CONFIG)
PKG = "com.ss.android.article.news"
DEFAULT_SHOT = "/tmp/phone_shot.png"


def sh(cmd, timeout=60):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    return (r.stdout + r.stderr).strip()


async def _scan(ip, lo=32768, hi=61000, conc=800, tmo=1.0):
    sem = asyncio.Semaphore(conc)
    found = []

    async def probe(p):
        async with sem:
            try:
                _, w = await asyncio.wait_for(asyncio.open_connection(ip, p), timeout=tmo)
                w.close()
                found.append(p)
            except Exception:
                pass

    tasks = [asyncio.create_task(probe(p)) for p in range(lo, hi + 1)]
    for i in range(0, len(tasks), 5000):
        await asyncio.gather(*tasks[i : i + 5000])
    return sorted(found)


def addr():
    """取一个可用的 adb 地址：已连接的 → **固定端口 5555** → 扫端口兜底。

    2026-09-10 起用 `adb tcpip 5555` 把 adbd 固化到 5555（无线调试的随机端口会漂移，
    且"无线调试"开关被关掉时 5555 往往还活着）。手机重启后 5555 会失效，那时再扫端口。
    """
    def first_device():
        for line in sh("adb devices").splitlines()[1:]:
            p = line.split()
            if len(p) >= 2 and p[1] == "device" and p[0].startswith(IP):
                return p[0]
        return None

    d = first_device()
    if d:
        return d
    sh(f"adb connect {IP}:5555")
    d = first_device()
    if d:
        return d
    for port in asyncio.run(_scan(IP)):
        sh(f"adb connect {IP}:{port}")
        d = first_device()
        if d:
            return d
    return None


A = None


def a():
    global A
    if A is None:
        A = addr()
        if not A:
            print(json.dumps({"status": "phone_offline", "ip": IP}, ensure_ascii=False))
            sys.exit(exitcodes.UPSTREAM)
    return f"adb -s {A}"


def brightness(path):
    try:
        from PIL import Image
        import numpy as np
        return round(float(np.asarray(Image.open(path).convert("L")).astype(float).mean()), 1)
    except Exception:
        return None


def keep_on():
    sh(f"{a()} shell settings put global stay_on_while_plugged_in 7")
    sh(f"{a()} shell svc power stayon true")


def wake_unlock():
    sh(f"{a()} shell input keyevent KEYCODE_WAKEUP")
    time.sleep(1)
    for _ in range(3):
        if "NotificationShade" not in sh(f"{a()} shell dumpsys window | grep mCurrentFocus"):
            return True
        sh(f"{a()} shell input swipe 540 1600 540 200 200")   # 实测有效解锁手势
        time.sleep(2)
    return False


def go_idle():
    """切到挂机屏（第3屏：纯黑壁纸 + 只有 Tailscale）。

    判别条件（2026-09-10 实测修正）：**含 `Tailscale` 且不含 `今日头条`**。
    别用"text 节点数 ≤ N"判断——挂机屏 dump 仍有 19 个 text 节点（图标标签/状态栏），
    早期用 ≤8 会导致永远判定失败。
    """
    sh(f"{a()} shell input keyevent KEYCODE_HOME")
    time.sleep(3)
    for _ in range(4):
        xml = sh(f'{a()} shell "uiautomator dump /sdcard/idle.xml >/dev/null 2>&1; cat /sdcard/idle.xml"')
        if "Tailscale" in xml and "今日头条" not in xml:
            return True
        sh(f"{a()} shell input swipe 900 1200 180 1200 300")
        time.sleep(2)
    return False


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]

    if cmd == "prep":
        keep_on()
        wake_unlock()
        sh(f"{a()} shell cmd statusbar collapse")
        sh(f'{a()} shell monkey -p {PKG} -c android.intent.category.LAUNCHER 1')
        time.sleep(10)
        sh(f"{a()} shell input tap 108 2300")   # 底部「首页」→ 推荐流
        time.sleep(6)
        print(json.dumps({"status": "ready", "addr": A,
                          "focus": sh(f"{a()} shell dumpsys window | grep mCurrentFocus")}, ensure_ascii=False))
    elif cmd == "shot":
        path = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_SHOT
        with open(path, "wb") as f:
            subprocess.run(f"{a()} exec-out screencap -p", shell=True, stdout=f, timeout=60)
        print(json.dumps({"path": path, "bytes": os.path.getsize(path), "brightness": brightness(path)},
                         ensure_ascii=False))
    elif cmd == "tap":
        sh(f"{a()} shell input tap {int(sys.argv[2])} {int(sys.argv[3])}")
        time.sleep(1.5)
        print("ok")
    elif cmd == "swipe":
        ms = sys.argv[6] if len(sys.argv) > 6 else "400"
        sh(f"{a()} shell input swipe {int(sys.argv[2])} {int(sys.argv[3])} {int(sys.argv[4])} {int(sys.argv[5])} {ms}")
        time.sleep(1.5)
        print("ok")
    elif cmd == "back":
        sh(f"{a()} shell input keyevent KEYCODE_BACK")
        time.sleep(1.5)
        print("ok")
    elif cmd == "home":
        sh(f"{a()} shell input keyevent KEYCODE_HOME")
        print("ok")
    elif cmd == "idle":
        print("ok" if go_idle() else "idle_failed")
    elif cmd == "dwell":
        secs = int(sys.argv[2]) if len(sys.argv) > 2 else 30
        # 模拟阅读：分段停留 + 随机缓慢下滑 1-3 次
        left = secs
        for _ in range(random.randint(1, 3)):
            nap = random.uniform(0.3, 0.6) * left
            time.sleep(nap)
            left -= nap
            sh(f"{a()} shell input swipe 540 1900 540 {random.randint(900, 1300)} {random.randint(300, 900)}")
        time.sleep(max(1, left))
        print("ok")
    elif cmd == "focus":
        print(sh(f"{a()} shell dumpsys window | grep mCurrentFocus"))
    elif cmd == "status":
        print(json.dumps({
            "addr": A or addr(),
            "wakefulness": sh(f"{a()} shell dumpsys power | grep -oE 'mWakefulness=[A-Za-z]+'"),
            "battery": sh(f"{a()} shell dumpsys battery | grep -E 'level|status'").replace("\n", " "),
        }, ensure_ascii=False))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
