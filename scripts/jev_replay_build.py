#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JEV 历史回放 · 输入包构建（as-of 严格版）

回放点 T = 该篇发布日的 05:00（写作 cron 决策时刻）。此时「当时理论可获得」的信息只有：
  1) 截至 T-1 20:00 的自家快照（reports/tt_snapshots/<T-1>.json）
  2) 当时在效力的规则文本（cron 输出里当次 Prompt 段，按日期取）
  3) T-1 晚间复盘给出的候选池（cron/output/fdb00de0d0f0 的 Response）
  4) 五源中「该源数据起始日 ≤ T-1」的部分

铁律：
  - 禁止读取 T-1 之后任何快照值 / 任何 T 之后产出的报告
  - 候选自身的首日结果绝不出现在输入里（它正是要预测的标签）
  - 每条数值带 as_of 来源标注；缺失就写 missing，不估算
产出：reports/jev-replay/replay_units.json
"""

# ── 项目根目录（默认 ~/content-ops-loop，可用环境变量 CONTENT_OPS_ROOT 覆盖）──────
import os as _os_root
CONTENT_OPS_ROOT = _os_root.path.expanduser(
    _os_root.environ.get('CONTENT_OPS_ROOT', '~/content-ops-loop'))
import platform_time

import sys as _sys
_sys.path.insert(0, _os_root.path.dirname(_os_root.path.abspath(__file__)))
import vertical as _vertical

import json, os, re, glob, datetime, collections, statistics, hashlib

HC = CONTENT_OPS_ROOT
SD = HC + '/reports/tt_snapshots'
CO = os.path.expanduser('~/.hermes/profiles/poster/cron/output')
OUT = HC + '/reports/jev-replay'

# ---------- 1. 快照（按日期升序） ----------
files = sorted(f for f in glob.glob(SD + '/*.json') if os.path.basename(f)[0] == '2')
SNAP = {os.path.basename(f)[:10]: json.load(open(f))['articles'] for f in files}
SNAP_DATES = sorted(SNAP)

TOPIC_RULES = _vertical.families()      # 垂类词典来自 config/vertical.json（换赛道改那里）


def topic(t):
    for n, kws in TOPIC_RULES:
        for k in kws:
            if k in t: return n
    return '其他'
def clean(t): return re.sub(r'\s+', '', t or '')
def prevday(d): return (datetime.date.fromisoformat(d) - datetime.timedelta(days=1)).isoformat()

# ---------- 2. 自家 as-of 指标 ----------
def pub_date_of(rec):
    return platform_time.from_ts(rec['publish_time']).date().isoformat()

def self_state(asof):
    """返回 asof 那天 20:00 能看到的自家状态（含首日三指标，仅当首日快照 ≤ asof）"""
    arts = SNAP[asof]
    rows, seen_t = [], set()
    for a in arts:
        if not a.get('publish_time'): continue
        pd_ = pub_date_of(a)
        if pd_ > asof: continue                      # 未来稿不出现
        t = clean(a['title'])
        if t.startswith('#') or '荣誉' in t or '幸运签' in t: continue   # 非文章
        if t in seen_t: continue                     # 同题 API 重复行只留一条
        seen_t.add(t)
        tr = a.get('traffic') or {}
        daily = {x['date']: x for x in (tr.get('daily') or [])}
        rows.append({'d': pd_, 't': t, 'id': a['item_id'],
                     'show': a.get('show'), 'read': a.get('read'),
                     'daily_row': daily.get(pd_), 'ctr': a.get('ctr_calc')})
    rows.sort(key=lambda r: r['d'])
    # 首日三指标（仅用 ≤asof 的快照；show 字段 08-22 起才有；traffic.daily 同日行可补）
    first = {}
    for r in rows:
        iid = r['id']
        vals = []
        for d in SNAP_DATES:
            if d > asof: continue
            for a in SNAP[d]:
                if a['item_id'] == iid:
                    if a.get('show') is not None:
                        vals.append((d, a['show'], a['read']))
                    break
        if vals:
            d0, s0, r0 = vals[0]
            first[iid] = {'asof': d0, 'show': s0, 'read': r0,
                          'ctr': round(r0 / s0 * 100, 2) if s0 else None, 'src': 'snapshot'}
        elif r['daily_row'] and r['daily_row'].get('impression') is not None:
            d0 = r['daily_row']
            first[iid] = {'asof': r['d'], 'show': d0['impression'], 'read': d0.get('read'),
                          'ctr': round((d0.get('read') or 0) / d0['impression'] * 100, 2) if d0['impression'] else None,
                          'src': 'traffic.daily'}
    recent = rows[-8:]
    lines = []
    for r in recent:
        f = first.get(r['id'])
        fd = f"{r['d']}｜{topic(r['t'])}｜{r['t'][:26]}"
        if f:
            fd += f"｜首日曝光{f['show']}·首日阅读{f['read']}·首日CTR{f['ctr']}%"
        else:
            fd += f"｜（首日曝光当时未采集，累计阅读{r['read']}）"
        lines.append(fd)
    # 近 14 天过线率 / 近 5 篇首日曝光中位
    r14 = rows[-14:]
    rf = [first[r['id']] for r in r14 if r['id'] in first]
    over = sum(1 for f in rf if (f['ctr'] or 0) >= 4)
    r5 = [first[r['id']] for r in rows[-5:] if r['id'] in first]
    med = statistics.median([f['show'] for f in r5]) if r5 else None
    if med is None:
        med_txt = '当时后台首日曝光字段未采集，只能看累计阅读（近5篇累计阅读中位 %s）' % (
            statistics.median([r['read'] or 0 for r in rows[-5:]]))
    else:
        med_txt = str(int(med))
    pools = collections.defaultdict(list)
    for r in rows:
        f = first.get(r['id'])
        if f and f['show'] is not None: pools[topic(r['t'])].append(f)
    pool_txt = []
    for k, v in sorted(pools.items(), key=lambda kv: -statistics.median([x['show'] for x in kv[1]])):
        if len(v) >= 2:
            pool_txt.append(f"{k} n={len(v)} 首日曝光中位{int(statistics.median([x['show'] for x in v]))} 首日CTR中位{round(statistics.median([x['ctr'] or 0 for x in v]),2)}%")
    return {'recent_lines': lines, 'recent14_titles': [r['t'][:30] for r in r14],
            'over14': f"{over}/{len(rf)}" if rf else '当时无首日数据',
            'med5': med, 'med5_txt': med_txt,
            'pools': pool_txt[:6], 'n_total': len(rows), 'first_asof_ok': len(first)}

# ---------- 3. 规则文本 as-of（从当天 cron Prompt 复原） ----------
KEYPAT = re.compile(r'(三轴|轮换|结构族|内核|池子|爆款族|冷却|闸门|标题质检|标题自检|主题级去重|给量|首日|决策门|停更|预注册|纪律|禁用|禁止|纪律|KPI|五档|骨架)')
SKIPPAT = re.compile(r'(微信|公众号|百家号|转发|搜一搜|草稿箱|百家)')
def rules_asof(day):
    """day = 回放点当天；取该日写作+复盘 cron 输出的 Prompt，抽规则行（截断）"""
    out = []
    for job, tag in (('f2e5291f41da', '写作'), ('fdb00de0d0f0', '复盘')):
        cand = sorted(f for f in os.listdir(os.path.join(CO, job)) if f.startswith(day))
        if not cand: continue
        txt = open(os.path.join(CO, job, cand[0]), encoding='utf-8').read()
        p = txt.split('## Prompt')[-1].split('## Script Output')[0] if '## Prompt' in txt else txt
        lines = [l.strip() for l in p.split('\n')
                 if len(l.strip()) > 8 and KEYPAT.search(l) and not SKIPPAT.search(l)]
        seen, keep = set(), []
        for l in lines:
            k = l[:40]
            if k in seen: continue
            seen.add(k); keep.append(l[:170])
        if keep:
            out.append(f"[{tag}cron{day}当时的规则摘录] " + " ／ ".join(keep[:8]))
    return out

# ---------- 4. 候选池 as-of（T-1 复盘输出） ----------
def pool_asof(day):
    y = prevday(day)
    got, src = [], []
    for j, tag in (('fdb00de0d0f0', 'T-1复盘'),):
        for dd in (y, prevday(y)):
            for f in sorted(os.listdir(os.path.join(CO, j))):
                if f.startswith(dd):
                    txt = open(os.path.join(CO, j, f), encoding='utf-8').read()
                    resp = txt.split('## Response')[-1] if '## Response' in txt else ''
                    for t in re.findall(r'《([^》]{6,60})》', resp):
                        if t not in got:
                            got.append(t); src.append(f"{tag}{dd}")
    return got[:6], src[:6]

# ---------- 5. 五源 as-of ----------
def sources_asof(day):
    y = prevday(day)
    ds = []
    f2 = sorted(glob.glob(HC + '/reports/爆款研究-2*.md'))
    f2 = [f for f in f2 if re.search(r'(2026-\d\d-\d\d)', os.path.basename(f)) and re.search(r'(2026-\d\d-\d\d)', os.path.basename(f)).group(1) <= y]
    if f2:
        last = f2[-1]
        d = re.search(r'(2026-\d\d-\d\d)', os.path.basename(last)).group(1)
        txt = open(last, encoding='utf-8').read()
        heads = re.findall(r'^#+ *(.{4,40})$', txt, re.M)[:6]
        ds.append(f"S2 爆款研究({d})：章节={' / '.join(heads)}")
    nu = sorted(glob.glob(HC + '/reports/nurture/2*.md'))
    nu = [f for f in nu if os.path.basename(f)[:10] <= y]
    if nu:
        last = nu[-1]
        txt = open(last, encoding='utf-8').read()
        titles = re.findall(r'《([^》]{8,45})》', txt)[:8]
        ds.append(f"S3 养号观察({os.path.basename(last)[:10]})：推荐流标题({' | '.join(titles)})")
    mb = sorted(glob.glob(HC + '/reports/nurture/赚钱博主/*.json'))
    mb = [f for f in mb if os.path.basename(f)[:10] <= y]
    if mb:
        ds.append(f"S4 赚钱博主探针({os.path.basename(mb[-1])[:10]})：累计{len(mb)}份账号卡（粉丝/赛道 on-off/mixed）")
    w = sorted(glob.glob(HC + '/reports/benchmark/周报-*.md'))
    w = [f for f in w if re.search(r'(2026-)?W(\d\d)', os.path.basename(f))]
    if w and y >= '2026-09-13':
        ds.append(f"S5 赛道基准({os.path.basename(w[-1])})：竞品同赛道文章样本（按文章年龄桶比，n<8 不给分位）")
    if not ds:
        ds.append("（五源自 T 起均无可用数据：仅自家 S1）")
    return ds

# ---------- 6. 组装 ----------
scorable = json.load(open(OUT + '/scorable_set.json'))
units = []
for r in scorable:
    day = r['pub_date']; y = prevday(day)
    if y not in SNAP:
        print('SKIP(no snapshot)', day); continue
    ss = self_state(y)
    pool, psrc = pool_asof(day)
    u = {
        'unit_id': f"{day}|{clean(r['title'])[:18]}",
        'replay_date': day, 'replay_time': f"{day} 05:00",
        'asof_snapshot': y, 'candidate_title': clean(r['title']),
        'candidate_topic': topic(clean(r['title'])),
        'pool_asof': pool, 'pool_src': psrc,
        'self_state': ss,
        'sources': sources_asof(day),
        'rules': rules_asof(day),
        'label_first_show': r['first_show'], 'label_first_read': r['first_read'],
        'label_first_ctr': r['first_ctr'], 'label_src': r['first_src'],
    }
    raw = json.dumps(u, ensure_ascii=False, sort_keys=True)
    u['input_sha256'] = hashlib.sha256(raw.encode()).hexdigest()[:16]
    units.append(u)

json.dump(units, open(OUT + '/replay_units.json', 'w'), ensure_ascii=False, indent=1)
print("replay units:", len(units))
# 展示一个样本大小与内容
u = units[10]
print("\n=== 样本（%s）===" % u['unit_id'])
for k in ('replay_time', 'asof_snapshot', 'candidate_title', 'candidate_topic', 'pool_asof'):
    print(k, '=', u[k])
print('self_state.med5 =', u['self_state']['med5'], '| over14 =', u['self_state']['over14'])
print('rules[0][:300] =', (u['rules'][0][:300] if u['rules'] else 'NONE'))
print('sources =', u['sources'])
print('bytes =', len(json.dumps(u, ensure_ascii=False)))
