#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""self_track.py —— 「我方成长曲线」：每周一行，把"位置 + 成长"记成一条可画线的数据。

初心（2026-09-13 用户定调）：benchmark 的最终目的是
  ① 验证「我的账号」在中老年赛道里的**位置**；
  ② 用"位置 × 成长"评估**这一整套系统的商业价值**。
所以本脚本每周记一行：我方首日三指标 + 累计量 + 赛道分位 + 系统成本/收益。

数据源（只读）：
  reports/首日指标.json        → 我方首日三指标（按 ISO 周分桶）
  reports/tt_snapshots/*.json   → 累计展现/阅读/收益/文章数（取最新一份）
  reports/benchmark/articles.jsonl → 赛道分位（只吃 niche=on；<24h 桶 n<8 时写"样本不足"）
输出：
  reports/benchmark/我方成长曲线.md（按 ISO 周去重追加；旧行保留）
常量（人工维护）：
  累计成本 = 手填（模型 API + 服务器等，自己算一遍填进 COST_YUAN）。
"""

# ── 项目根目录（默认 ~/content-ops-loop，可用环境变量 CONTENT_OPS_ROOT 覆盖）──────
import os as _os_root
CONTENT_OPS_ROOT = _os_root.path.expanduser(
    _os_root.environ.get('CONTENT_OPS_ROOT', '~/content-ops-loop'))

import glob
import json
import os
import statistics
from datetime import datetime, timedelta

HOME = os.path.expanduser("~")
R = os.path.join(CONTENT_OPS_ROOT, 'reports')
OUT = f"{R}/benchmark/我方成长曲线.md"
COST_YUAN = 0.0           # ← 人工维护：把累计成本（模型 API + 服务器）填进来，用于算单篇成本与回收率
COST_ASOF = ""            # ← 人工维护：上面那个成本数字的截止日


def num(v):
    try:
        return float(v)
    except Exception:
        return None


def iso_week(d):
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def main():
    # 1) 我方首日指标（按周分桶）
    fd = json.load(open(f"{R}/首日指标.json", encoding="utf-8")).get("rows", [])
    wk = {}
    for r in fd:
        pd = r.get("pub_date")
        if not pd or r.get("first_show") is None:
            continue
        try:
            d = datetime.strptime(pd, "%Y-%m-%d")
        except Exception:
            continue
        wk.setdefault(iso_week(d), []).append(r)

    # 2) 累计（最新快照）
    snaps = sorted(glob.glob(f"{R}/tt_snapshots/*.json"))
    cum = {}
    if snaps:
        s = json.load(open(snaps[-1], encoding="utf-8"))
        arts = [a for a in s.get("articles", []) if int(a.get("item_id", 0) or 0) > 1e17]
        if arts:
            cum = {
                "date": s.get("date"),
                "n": len(arts),
                "show": sum(a.get("show") or 0 for a in arts),
                "read": sum(a.get("read") or 0 for a in arts),
                "income": sum((a.get("income") or {}).get("income_fen", 0) or 0 for a in arts) / 100.0,
            }

    # 3) 赛道分位（只吃同赛道 on，且 <24h 桶 n≥8 才给结论）
    rows_b = []
    bp = f"{R}/benchmark/articles.jsonl"
    if os.path.exists(bp):
        rows_b = [json.loads(l) for l in open(bp, encoding="utf-8") if l.strip()]
    on = [x for x in rows_b if x.get("niche_art") == "on"]
    fresh = [x for x in on if x.get("age_bucket") == "<24h" and x.get("show") is not None]
    ours_fd = [r["first_show"] for r in fd if r.get("first_show")]
    ours_med = int(statistics.median(ours_fd)) if ours_fd else None
    if len(fresh) >= 8 and ours_med:
        below = sum(1 for x in fresh if x["show"] < ours_med)
        pct = round(below / len(fresh) * 100)
        quantile = f"第 {pct} 分位（n={len(fresh)}）"
    else:
        quantile = f"样本不足（<24h 同赛道 n={len(fresh)}，需 ≥8）"

    # 4) 读旧表 / 写新行
    old = ""
    if os.path.exists(OUT):
        old = open(OUT, encoding="utf-8").read()
    head = ["# 我方成长曲线（每周一行 · 自动生成，勿手改）", "",
            "> 初心：回答「我们在中老年赛道的**位置**」+「这个位置**怎么变**」→ 合起来 = 这套系统的商业价值证据。",
            "> 口径：首日三指标（累计 CTR 会随时间被稀释，不用于判断健康度）；赛道分位只吃同赛道 `niche_art=on` 的 `<24h` 桶样本。",
            "> 维护：周报 cron `04112b572daf` 每周追加一行（同日重复运行会覆盖该周行，不重复堆叠）。", "",
            "| ISO周 | 当周稿件 | 首日曝光中位 | 首日CTR中位 | 首日≥100阅读占比 | 赛道分位（我方首日曝光） | 累计阅读 | 累计收益(元) | 系统累计成本(元) |",
            "|---|---:|---:|---:|---:|---|---:|---:|---:|"]
    body = []
    if old:
        for ln in old.split("\n"):
            if ln.startswith("| ") and not ln.startswith("| ISO周") and not ln.startswith("|---"):
                if not ln.startswith("| 合计"):
                    body.append(ln)
    # 每周一行（回填历史周，重复运行覆盖同周行）
    new_rows = {}
    for w in sorted(wk):
        rs = wk[w]
        shows = [r["first_show"] for r in rs]
        ctrs = [r["first_ctr"] for r in rs if r.get("first_ctr") is not None]
        ge100 = sum(1 for r in rs if (r.get("first_read") or 0) >= 100)
        new_rows[w] = (f"| {w} | {len(rs)} | {int(statistics.median(shows))} | "
                       f"{round(statistics.median(ctrs), 2) if ctrs else '—'} | "
                       f"{round(ge100 / len(rs) * 100)}% | — | — | — | — |")
    # 最新周补：分位 + 累计 + 成本
    if new_rows:
        wlar = sorted(new_rows)[-1]
        cells = new_rows[wlar].split("|")
        cells[6] = f" {quantile} "
        cells[7] = f" {cum.get('read', 0):,} " if cum else " — "
        cells[8] = f" {cum.get('income', 0):.2f} " if cum else " — "
        cells[9] = f" {COST_YUAN:.0f}（{COST_ASOF}） "
        new_rows[wlar] = "|".join(cells)
    # 合并：历史周（旧表有、本次没算的）保留
    for b in body:
        w = b.split("|")[1].strip()
        if w and w not in new_rows:
            new_rows[w] = b
    body = [new_rows[w] for w in sorted(new_rows)]
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(head + body) + "\n")

    # 5) 商业价值读数（打印，供周报引用）
    print(f"成长曲线已写：{OUT}")
    if cum:
        per_yuan = cum["read"] / (COST_YUAN / 1000) if COST_YUAN else 0
        print(f"- 累计：{cum['n']} 篇｜展现 {cum['show']:,}｜阅读 {cum['read']:,}｜收益 ¥{cum['income']:.2f}")
        if COST_YUAN:
            print(f"- 系统累计成本 ¥{COST_YUAN:.0f} → 回收率 {cum['income']/COST_YUAN*100:.1f}%｜"
                  f"单篇收益 ¥{cum['income']/max(cum['n'],1):.4f}｜单篇成本 ¥{COST_YUAN/max(cum['n'],1):.2f}｜"
                  f"每千元成本对应阅读 {per_yuan:,.0f}")
        else:
            print("- 系统累计成本未填（COST_YUAN=0）→ 跳过回收率/单篇成本；"
                  "填上之后这两行才有意义")
        if ours_med:
            print(f"- 我方首日曝光中位 {ours_med}")
    print(f"- 赛道分位：{quantile}")
    for w in sorted(wk):
        rs = wk[w]
        print(f"   {w}: {len(rs)} 篇｜首日曝光中位 {int(statistics.median([r['first_show'] for r in rs]))}｜"
              f"CTR中位 {round(statistics.median([r['first_ctr'] for r in rs if r.get('first_ctr') is not None]), 2) if any(r.get('first_ctr') is not None for r in rs) else '—'}%")


if __name__ == "__main__":
    main()
