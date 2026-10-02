#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""首日三指标 + 题材池子表

背景：累计 CTR 被平台「保养滴灌」污染（第2天起每天只给 100-260 曝光、CTR≈0），
会把好文章稀释成 0.05%。真指标只有三个：
    首日曝光（= 平台给的第一轮测试批次量，即「池子」）
    首日阅读
    首日CTR（= 骨架新鲜度的手感，实测拿到批次的稿全在 7-12%）

诊断模型（三因子相乘）：
    首日曝光 = 骨架新鲜度 × 题材池子大小 × 账号当时的分配额度
    · 骨架旧 → 首日曝光 70-150（同质化去重，连测都不给）
    · 池子小 → 首日曝光 300-600，CTR 正常也涨不上去

数据源：~/content-ops-loop/reports/tt_snapshots/*.json（每日快照，含每篇 show/read + 最近12篇的
        traffic.daily 逐日曝光/阅读）。首日口径：发布当日快照（发布晚于 12:00 则取次日）。

用法：
    python3 first_day_metrics.py            # 打印报告（供 cron 注入 / 人读）
    python3 first_day_metrics.py --json out.json   # 同时落盘结构化结果
"""

# ── 项目根目录（默认 ~/content-ops-loop，可用环境变量 CONTENT_OPS_ROOT 覆盖）──────
import os as _os_root
CONTENT_OPS_ROOT = _os_root.path.expanduser(
    _os_root.environ.get('CONTENT_OPS_ROOT', '~/content-ops-loop'))
import platform_time

import datetime
import glob
import json
import os
import re
import statistics
import sys
import exitcodes

SNAP_DIR = os.path.join(CONTENT_OPS_ROOT, 'reports/tt_snapshots')

# ---------------- 垂类词典：来自 config/vertical.json（换赛道改那里）----------------
import vertical as _vertical
TOPIC_RULES = _vertical.families()
VIRAL_SHOW = int(_vertical.threshold('viral_show'))       # 爆款级单篇：不进稳定池中位
PASS_CTR = float(_vertical.threshold('own_pass_ctr'))     # 过线值
STRONG_CTR = float(_vertical.threshold('own_strong_ctr'))
if not TOPIC_RULES:
    print("[first_day_metrics] 垂类词典是空的（config/vertical.json）→ 所有题材会归到「其他」",
          file=sys.stderr)


def topic_of(title):
    for name, kws in TOPIC_RULES:
        for k in kws:
            if k in title:
                return name
    return '其他'


def load_snapshots():
    snaps = []
    for p in sorted(glob.glob(os.path.join(SNAP_DIR, '*.json'))):
        date = os.path.basename(p)[:-5]
        # 只认 YYYY-MM-DD 命名的每日快照；排除 item_info_backfill.json 等非快照文件
        # （否则 backfill 会被当成「最新快照」→ 首日指标/题材池子表整体算空，2026-09-22~24 曾连续 3 天踩坑）
        if not re.match(r'^\d{4}-\d{2}-\d{2}$', date):
            continue
        try:
            with open(p, encoding='utf-8') as f:
                d = json.load(f)
        except Exception:
            continue
        snaps.append((date, d.get('articles') or []))
    return snaps


def median(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 2) if xs else None


def build():
    snaps = load_snapshots()
    if not snaps:
        return None
    latest_date, latest = snaps[-1]
    # item_id -> {snap_date: (show, read)}
    hist = {}
    for sdate, arts in snaps:
        for a in arts:
            iid = str(a.get('item_id'))
            hist.setdefault(iid, {})[sdate] = (a.get('show') or 0, a.get('read') or 0)

    # 去重：同名条目（文章 + 微头条镜像，发布时间相差 <2 分钟）保留累计展现更大的那条
    dedup = {}
    for a in latest:
        if a.get('item_status') != 20:
            continue
        title = (a.get('title') or '').strip()
        prev = dedup.get(title)
        if prev is None or (a.get('show') or 0) > (prev.get('show') or 0):
            dedup[title] = a
    latest = list(dedup.values())

    earliest_snap = snaps[0][0]

    rows = []
    for a in latest:
        iid = str(a.get('item_id'))
        title = (a.get('title') or '').strip()
        pub_date = a.get('show_date') or ''
        if not pub_date or pub_date < earliest_snap:
            continue  # 快照史之前发布 → 无法还原首日
        try:
            pub_hour = platform_time.from_ts(a.get('publish_time') or 0).hour
        except Exception:
            pub_hour = 8
        d1 = pub_date
        if pub_hour > 12:  # 发布晚于 12:00 → 首日窗口取次日
            try:
                d1 = (datetime.date.fromisoformat(pub_date) + datetime.timedelta(days=1)).isoformat()
            except Exception:
                pass
        f_show = f_read = None
        src = ''
        # ① 最优：traffic.daily 里发布日那条（平台官方口径）
        tr = a.get('traffic') or {}
        daily = tr.get('daily') if isinstance(tr, dict) else None
        if daily:
            for dd in daily:
                if dd.get('date') == pub_date:
                    f_show, f_read, src = dd.get('impression'), dd.get('read'), 'traffic'
                    break
            if src != 'traffic' and daily:
                dd = daily[0]
                f_show, f_read, src = dd.get('impression'), dd.get('read'), 'traffic首条'
        # ② 次优：发布日/次日快照里的 show/read（d1 为 0 则顺延到首个非零快照）
        if src == '':
            h = hist.get(iid, {})
            later = sorted(k for k in h if k >= pub_date)
            pick = None
            if d1 in h and h[d1][0]:
                pick = d1
            else:
                for k in later:
                    if h[k][0]:
                        pick = k
                        break
            if pick:
                f_show, f_read = h[pick]
                src = f'快照{pick}' + ('' if pick <= d1 else '(后续)')
        if src == '':
            continue
        ctr1 = round(f_read / f_show * 100, 2) if f_show else 0
        rows.append({
            'pub_date': pub_date, 'title': title, 'topic': topic_of(title),
            'first_show': f_show, 'first_read': f_read, 'first_ctr': ctr1,
            'total_show': a.get('show') or 0, 'total_read': a.get('read') or 0,
            'total_ctr': a.get('ctr_calc') or 0, 'src': src,
        })
    rows.sort(key=lambda r: r['pub_date'], reverse=True)

    out = {'date': latest_date, 'rows': rows}

    # 题材池子表
    by_topic = {}
    for r in rows:
        if r['first_ctr'] is None or r['first_show'] is None:
            continue
        by_topic.setdefault(r['topic'], []).append(r)
    pool = []
    for t, rs in by_topic.items():
        shows = sorted(r['first_show'] for r in rs)
        # 剔爆款污染：首日曝光 ≥5000 的爆款级样本不参与「稳定池」中位（单篇爆款会把题材池子虚高，
        # 实测：某题材首日曝光中位被单篇爆款抬到 5 位数，剔除后该题材只剩个位数样本）
        stable = [r for r in rs if r['first_show'] < VIRAL_SHOW]
        risk = '爆款污染' if (len(stable) != len(rs) and not stable) else (
            '含爆款' if len(stable) != len(rs) else '')
        for r in rs:
            if r['first_show'] >= VIRAL_SHOW:
                risk = '爆款污染' if not stable else '含爆款'
        pool.append({
            'topic': t, 'n': len(rs), 'n_stable': len(stable),
            'med_first_show': median([r['first_show'] for r in rs]),
            'med_first_show_stable': median([r['first_show'] for r in stable]),
            'med_first_read': median([r['first_read'] for r in rs]),
            'med_first_ctr': median([r['first_ctr'] for r in rs]),
            'risk': risk or ('单篇' if len(rs) == 1 else ''),
        })
    pool.sort(key=lambda x: -(x['med_first_show_stable'] if x['med_first_show_stable'] is not None else (x['med_first_show'] or 0)))
    out['pool'] = pool

    # 汇总
    recent5 = rows[:5]
    last30 = [r for r in rows
              if r['pub_date'] >= (datetime.date.fromisoformat(latest_date) - datetime.timedelta(days=30)).isoformat()]
    last14 = [r for r in rows
              if r['pub_date'] >= (datetime.date.fromisoformat(latest_date) - datetime.timedelta(days=14)).isoformat()]
    out['summary'] = {
        'n': len(rows),
        'med5_first_show': median([r['first_show'] for r in recent5]),
        'med30_first_show': median([r['first_show'] for r in last30]),
        'med5_first_ctr': median([r['first_ctr'] for r in recent5]),
        'med30_first_ctr': median([r['first_ctr'] for r in last30]),
        'pass14_rate': (round(sum(1 for r in last14 if r['first_ctr'] >= PASS_CTR) / len(last14) * 100, 1) if last14 else None),
        'ctr6_count': sum(1 for r in last14 if r['first_ctr'] >= 6),
        'n14': len(last14),
    }
    return out


def render(out, max_rows=24):
    if not out:
        return 'FIRSTDAY: 无快照数据'
    L = []
    s = out['summary']
    L.append(f"FIRSTDAY_OK (口径=首日曝光/首日阅读/首日CTR；快照 {out['date']}，可比样本 {s['n']} 篇)")
    L.append(f"近5篇首日曝光中位 {s['med5_first_show']}｜近30天中位 {s['med30_first_show']}"
             f"｜近5篇首日CTR中位 {s['med5_first_ctr']}%｜近30天 {s['med30_first_ctr']}%"
             f"｜近14天CTR≥4%过线率 {s['pass14_rate']}%（{s['n14']}篇）")
    L.append("首日三指标明细（新→旧）：")
    L.append("口径提示：有 traffic 逐日数据的篇用平台官方日桶（首选）；其余用「发布当日 20:00 快照」的累计值"
             "＝首日全量的下限（实测：同一篇的快照值可能只有 traffic 首日桶的一半左右）。不要用累计展/累计CTR 判断健康度。")
    L.append("| 发布 | 题材 | 标题 | 首日曝光 | 首日阅读 | 首日CTR | 累计展 | 累计读 | 累计CTR |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for r in out['rows'][:max_rows]:
        L.append(f"| {r['pub_date']} | {r['topic']} | {r['title'][:26]} | {r['first_show']} | {r['first_read']}"
                 f" | {r['first_ctr']}% | {r['total_show']} | {r['total_read']} | {r['total_ctr']}% |")
    L.append("题材池子表（按「剔爆款后首日曝光中位」降序 = 池子大小序；爆款级单篇 ≥5000 不参与稳定池中位）：")
    L.append("| 题材 | 篇数 | 首日曝光中位(剔爆款) | 首日曝光中位(含爆款) | 首日阅读中位 | 首日CTR中位 | 备注 |")
    L.append("|---|---|---|---|---|---|---|")
    for p in out['pool']:
        L.append(f"| {p['topic']} | {p['n']} | {p['med_first_show_stable']} | {p['med_first_show']} "
                 f"| {p['med_first_read']} | {p['med_first_ctr']}% | {p.get('risk') or ''} |")
    return '\n'.join(L)


def main():
    out = build()
    print(render(out))
    if '--json' in sys.argv:
        i = sys.argv.index('--json')
        path = sys.argv[i + 1] if len(sys.argv) > i + 1 else os.path.join(SNAP_DIR, 'first_day.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print(f"JSON: {path}")
    if not out or not out.get('rows'):
        # 没有可比样本 = 数据不足。刻意区别于成功(0)与失败(20/30)：
        # cron / CI 可以据此「不告警、也不记为成功」。
        sys.exit(exitcodes.INSUFFICIENT_DATA)


if __name__ == '__main__':
    main()
