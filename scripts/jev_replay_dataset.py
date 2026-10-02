#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JEV 历史回放 · 数据可行性审计（第一步：建 as-of 数据集 + 统计有效样本）
产出：reports/jev-replay/asof_articles.json  （每篇：发布日/首日三指标/最新累计，全部取「当时快照」值）
      reports/jev-replay/audit2_coverage.txt
铁律：每条数值都带 as_of（来自哪一天的快照），禁止用未来快照值当历史输入。
"""

# ── 项目根目录（默认 ~/content-ops-loop，可用环境变量 CONTENT_OPS_ROOT 覆盖）──────
import os as _os_root
CONTENT_OPS_ROOT = _os_root.path.expanduser(
    _os_root.environ.get('CONTENT_OPS_ROOT', '~/content-ops-loop'))
import platform_time

import json, glob, os, datetime, collections

SD = os.path.join(CONTENT_OPS_ROOT, 'reports/tt_snapshots')
OUT = os.path.join(CONTENT_OPS_ROOT, 'reports/jev-replay')

files = sorted(f for f in glob.glob(SD + '/*.json') if os.path.basename(f)[0] == '2')
snaps = [(os.path.basename(f)[:10], json.load(open(f))['articles']) for f in files]

# 每个 item 在每份快照里的记录
series = collections.defaultdict(dict)   # item_id -> {snap_date: rec}
meta = {}
for d, arts in snaps:
    for a in arts:
        iid = a['item_id']
        series[iid][d] = a
        meta.setdefault(iid, a)

rows = []
for iid, byd in series.items():
    m = meta[iid]
    pt = m.get('publish_time')
    if not pt:
        continue
    pubs = platform_time.from_ts(pt)
    pub_date = pubs.date()
    if pubs.hour >= 12:                       # 发布晚于 12:00 → 首日口径取次日快照
        first_day = pub_date + datetime.timedelta(days=1)
    else:
        first_day = pub_date
    fd = None
    for d in sorted(byd):
        if datetime.date.fromisoformat(d) >= first_day:
            fd = (d, byd[d]); break
    rec = {
        'item_id': iid, 'title': m.get('title'), 'pub_date': str(pub_date),
        'pub_time': pubs.strftime('%H:%M'), 'firstday_asof': fd[0] if fd else None,
        'first_show': fd[1].get('show') if fd else None,
        'first_read': fd[1].get('read') if fd else None,
        'first_ctr': fd[1].get('ctr_calc') if fd else None,
        'first_digg': fd[1].get('digg') if fd else None,
        'first_comment': fd[1].get('comment') if fd else None,
        'first_repin': fd[1].get('repin') if fd else None,
        'latest_asof': snaps[-1][0],
        'latest_show': byd[snaps[-1][0]].get('show') if snaps[-1][0] in byd else None,
        'latest_read': byd[snaps[-1][0]].get('read') if snaps[-1][0] in byd else None,
        'item_status': m.get('item_status'),
        'note': 'publish before snapshot window' if str(pub_date) < snaps[0][0] else '',
    }
    if rec['first_show'] is not None and rec['first_read'] is not None:
        rec['first_ctr_calc'] = round(rec['first_read'] / rec['first_show'] * 100, 2) if rec['first_show'] else None
    rows.append(rec)

rows.sort(key=lambda r: (r['pub_date'], r['pub_time']))
json.dump({'generated': datetime.datetime.now().isoformat(timespec='seconds'),
           'snapshot_range': [snaps[0][0], snaps[-1][0]], 'rows': rows},
          open(OUT + '/asof_articles.json', 'w'), ensure_ascii=False, indent=1)

L = []
def p(s=''):
    L.append(str(s)); print(s)

p("=== JEV 回放 · 覆盖统计（快照 %s ~ %s，共 %d 份）===" % (snaps[0][0], snaps[-1][0], len(snaps)))
p("item 总数（出现在快照里的）: %d" % len(rows))
inside = [r for r in rows if snaps[0][0] <= r['pub_date'] <= snaps[-1][0]]
p("发布日在快照窗口内: %d" % len(inside))
p("发布日早于窗口（无首日数据，只有累计）: %d" % (len(rows) - len(inside)))
fd_ok = [r for r in inside if r['first_show'] is not None]
p("窗口内且有「首日曝光」数值的: %d" % len(fd_ok))
p("窗口内但缺首日曝光（发布日 < 2026-08-22，show 字段尚未采集）: %d" % (len(inside) - len(fd_ok)))
p("窗口内、有首日曝光、item_status=20(已发布): %d" % sum(1 for r in fd_ok if r['item_status'] == 20))
p()
p("=== 按发布日逐日（窗口内）===")
p("发布日 | 篇数 | 有首日曝光 | 首日曝光中位 | 首日阅读中位 | 首日CTR中位")
byd = collections.defaultdict(list)
for r in inside: byd[r['pub_date']].append(r)
import statistics
for d in sorted(byd):
    rs = byd[d]; ok = [x for x in rs if x['first_show'] is not None]
    f = lambda k: (statistics.median([x[k] for x in ok]) if ok else None)
    p("%s | %d | %d | %s | %s | %s" % (d, len(rs), len(ok), f('first_show'), f('first_read'),
      (round(statistics.median([x['first_ctr_calc'] for x in ok if x['first_ctr_calc'] is not None]), 2) if ok else None)))
p()
p("=== 首日曝光分档（有首日曝光的样本）===")
buckets = collections.Counter()
for r in fd_ok:
    s = r['first_show']
    k = '<100' if s < 100 else '100-299' if s < 300 else '300-899' if s < 900 else '>=900'
    buckets[k] += 1
for k in ['<100', '100-299', '300-899', '>=900']:
    p("  %-8s %d" % (k, buckets[k]))
p()
p("=== 首日 CTR 分档（有首日曝光的样本）===")
cb = collections.Counter()
for r in fd_ok:
    c = r['first_ctr_calc']
    if c is None: cb['missing'] += 1
    elif c >= 4: cb['>=4% (高潜标签)'] += 1
    elif c >= 1: cb['1-4%'] += 1
    else: cb['<1%'] += 1
for k, v in cb.most_common(): p("  %-18s %d" % (k, v))
p()
p("=== 同题重复发布（改题重发/同日双发）===")
t = collections.Counter(r['title'] for r in rows)
for title, n in t.most_common():
    if n > 1: p("  x%d %s" % (n, title[:45]))
dupday = collections.Counter(r['pub_date'] for r in rows)
p("  同日发布 >1 篇的日期: %s" % [(d, n) for d, n in sorted(dupday.items()) if n > 1][:20])
open(OUT + '/audit2_coverage.txt', 'w').write('\n'.join(L))
print("\n写出: reports/jev-replay/asof_articles.json, audit2_coverage.txt")
