#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同题库 · 周卡（每周发给用户看的飞书卡片 + 累计曲线一行）

用户 2026-09-22：「待复核文件每周以飞书消息卡片发我看，积少成多，雪球越滚越大，
账号在平台上的定位越来越清晰」。

产出：
  reports/same_topic/周卡-<YYYY-MM-DD>.md      （飞书消息正文，≤20 行，手机优先）
  reports/same_topic/累计曲线.md               （每周追加一行：雪球有多大）
用法：python3 scripts/same_topic_weekly.py           # 打印卡片正文（供 cron 直投）
"""

# ── 项目根目录（默认 ~/content-ops-loop，可用环境变量 CONTENT_OPS_ROOT 覆盖）──────
import os as _os_root
CONTENT_OPS_ROOT = _os_root.path.expanduser(
    _os_root.environ.get('CONTENT_OPS_ROOT', '~/content-ops-loop'))
import platform_time

import sys as _sys
_sys.path.insert(0, _os_root.path.dirname(_os_root.path.abspath(__file__)))
import vertical as _vertical

import json, os, random, datetime, collections, statistics, sys

HC = CONTENT_OPS_ROOT
OUT = f'{HC}/reports/same_topic'
today = platform_time.today_str()
iso_week = today.isocalendar()

rows = [json.loads(l) for l in open(f'{OUT}/works.jsonl', encoding='utf-8')]
den = [r for r in rows if r['denominator_eligible']]
cls = [r for r in rows if r['motif'] not in ('未归类', '跨赛道（不计入）')]
own = [r for r in rows if r['is_own']]
own_fd = [r for r in own if r.get('ctr') is not None]
fam = collections.Counter(r['topic_family'] for r in cls)

# 过门母题（n>=8 且跨账号>=3，只看分母可用 + 非自家）
ext = [r for r in den if not r['is_own'] and isinstance(r['read'], (int, float))]
g = collections.defaultdict(list)
for r in ext:
    g[r['motif']].append(r)
gated = []
for m, v in g.items():
    if m in ('未归类', '跨赛道（不计入）'):
        continue
    accs = len(set(x['account'] for x in v))
    if len(v) >= 8 and accs >= 3:
        med = int(statistics.median([x['read'] for x in v]))
        gated.append((m, len(v), accs, med))
gated.sort(key=lambda x: -x[1])

# 距过门最近（差 1-3 篇）的母题 —— 告诉用户"下周最可能变成结论的"
near = sorted([(m, len(v), MIN_N - len(v), len(set(x['account'] for x in v)))
               for m, v in g.items()
               if m not in ('未归类', '跨赛道（不计入）') and MIN_N - 3 <= len(v) < MIN_N],
              key=lambda x: -x[1])[:3]

# 抽样：**给用户看的 10 条要挑有用的**（不是随机丢垃圾让他审）
#   ① 像本赛道但没归类的 → 请他给正确母题（最有价值）
#   ② 只命中 1 个词的（低置信）→ 请他确认归类对不对
#   ③ 跨赛道否决词可能误杀的（账号在赛道内、却被判跨赛道）
#   ④ 纯抽查 2 条（正常归类，防"只看异常"）
# 垂类相关词表来自 config/vertical.json（换赛道改那里）
NICHE_HINT = _vertical.niche_hint()
OFFLIKE = _vertical.offlike()
MIN_N = int(_vertical.threshold('min_n_quantile'))

def like_niche(t):
    return any(k in t for k in NICHE_HINT) and not any(k in t for k in OFFLIKE)

uncl = [r for r in rows if r['motif'] == '未归类' and like_niche(r['title'])]
lowconf = [r for r in rows if r['confidence'] == 'low' and r['motif'] not in ('未归类', '跨赛道（不计入）')]
misveto = [r for r in rows if r['motif'] == '跨赛道（不计入）' and r['acct_niche'] in ('on', 'own') and like_niche(r['title'])]
normal = [r for r in rows if r['motif'] not in ('未归类', '跨赛道（不计入）') and r['confidence'] == 'high']

random.seed(int(today.strftime('%Y%W')))
def take(pool, k):
    pool = [r for r in pool if r['title'] not in _seen]
    _seen.update(r['title'] for r in pool[:k])
    return random.sample(pool, min(k, len(pool)))

_seen = set()
pick_uncl = take(uncl, 5)
pick_low = take(lowconf, 2)
pick_veto = take(misveto, 1)
pick_norm = take(normal, 2)
pick_norm = pick_norm + take(normal, max(0, 8 - (len(pick_uncl) + len(pick_low) + len(pick_veto) + len(pick_norm))))
pick = [('待归类', pick_uncl), ('确认归类', pick_low), ('否决词误杀?', pick_veto), ('抽查', pick_norm)]

# 累计曲线：本周一行（同周重复运行则覆盖当周行）
cp = f'{OUT}/累计曲线.md'
lines = []
if os.path.exists(cp):
    lines = [l for l in open(cp, encoding='utf-8').read().split('\n') if l.strip()]
hdr = ['# 同题库 · 累计曲线（每周一行）', '',
       '| 周 | 日期 | 统一库 | 可进分母 | 已归类母题 | 过门母题 | 自家篇数 |',
       '|---|---|---:|---:|---:|---:|---:|']
body = [l for l in lines if l.startswith('| ') and not l.startswith('| 周') and not l.startswith('|---')]
body = [l for l in body if f'| W{iso_week[1]:02d} ' not in l]
body.append(f"| W{iso_week[1]:02d} | {today.isoformat()} | {len(rows)} | {len(den)} | {len(cls)} | {len(gated)} | {len(own_fd)} |")
# ⚠️ 保留表格外的注记行（如「> W39 首卡基线」）——否则每次重跑会把历史基线注记吃掉（2026-09-27 修）
notes = [l for l in lines if l.startswith('>')]
open(cp, 'w', encoding='utf-8').write('\n'.join(hdr + body + notes) + '\n')
prev = body[-2] if len(body) > 1 else None
def delta(i):
    if not prev:
        return ''
    try:
        a = int(prev.split('|')[i].strip()); b = int(body[-1].split('|')[i].strip())
        return f'（本周 +{b-a}）' if b != a else '（+0）'
    except Exception:
        return ''

# ---------- 卡片正文（手机优先：要你做的事放第一行） ----------
L = []
L.append(f'🔍 同题库周卡 W{iso_week[1]:02d}（{today.isoformat()}）')
L.append('')
L.append(f'👉 要你做的事：看下面 {sum(len(x[1]) for x in pick)} 条归类，错的回我一条就行（例：3 错→护工视角）')
L.append('')
L.append(f'📊 雪球：统一库 {len(rows)} 条{delta(2)}｜可进分母 {len(den)} 条{delta(3)}｜已归类 {len(cls)} 条{delta(4)}')
L.append(f'　过门的母题 {len(gated)} 个{delta(5)}｜自家累计 {len(own_fd)} 篇（有首日CTR的）')
if gated:
    L.append('　已能读分布的母题：' + '、'.join(f'{m}(n={n})' for m, n, a, med in gated[:5]))
else:
    L.append('　已能读分布的母题：暂无（还没到 n≥8 且跨账号≥3）')
if near:
    L.append('　离过门最近的：' + '、'.join(f'{m}(n={n}，差{k})' for m, n, k, a in near))
L.append('')
L.append('🧾 本周待你过目（标题 → 归类）')
i = 0
for label, lst in pick:
    if not lst:
        continue
    L.append(f'【{label}】')
    for r in lst:
        i += 1
        L.append(f'{i}. {r["title"][:28]} → {r["motif"]}（{r["collected_via"]}）')
L.append('')
L.append('⛔ 提醒：这些分布是「观察窗口内的表现」，**不是成功率**；n<8 或跨账号<3 的母题不给结论。')
L.append('📄 详情：~/content-ops-loop/reports/same_topic/同题对照表.md')
card = '\n'.join(L)
open(f'{OUT}/周卡-{today.isoformat()}.md', 'w', encoding='utf-8').write(card)

# 待复核文件同步（与卡片同一批，便于回填）
R = ['# 归类抽样复核（本次审批批）', '',
     f'生成 {datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}｜直接把"对/错 + 正确母题"回填本文件即可', '']
i = 0
for label, lst in pick:
    for r in lst:
        i += 1
        R.append(f'- [ ] {i}. [{label}] {r["title"][:56]}')
        R.append(f'      归类：{r["topic_family"]} / **{r["motif"]}**（命中 {r["motif_kw"] or "无"}，置信 {r["confidence"]}）｜来源 {r["collected_via"]}｜阅读 {r["read"]}')
open(f'{OUT}/待复核-{today.isoformat()}.md', 'w', encoding='utf-8').write('\n'.join(R))

print(card)
