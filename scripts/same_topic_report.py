#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同题库 · 对照表生成（每个母题：爆/平/败 分布 + 结论门 + 待复核抽样）

纪律（写入文件头，任何人读表前先看）：
  1. 分母只用 `denominator_eligible=1` 的样本（主页/自己后台这类**完整清单**来源）；
     推荐流/搜索/探针来源一律只作题材观察，不进分母（它们天然是平台正在推的 = 幸存者）。
  2. 外部样本只有**累计阅读**（网页版无展现）→ 必须同文章年龄桶比；且只用
     **桶内相对档**（前25%/中50%/后25%），n<8 不给档（沿用自家铁律）。
  3. 读法：这是「观察窗口内的表现分布」，**不是成功率/概率**。同题差异分不清
     内容 vs 账号权重 vs 发布时段 vs 平台批次。
  4. 抽样复核：每次生成随机抽 10 条归类，交人工核（落在 待复核-<日期>.md）。

输出：
  reports/same_topic/同题对照表.md
  reports/same_topic/待复核-<日期>.md
  reports/same_topic/对照数据.json
"""

# ── 项目根目录（默认 ~/content-ops-loop，可用环境变量 CONTENT_OPS_ROOT 覆盖）──────
import os as _os_root
CONTENT_OPS_ROOT = _os_root.path.expanduser(
    _os_root.environ.get('CONTENT_OPS_ROOT', '~/content-ops-loop'))
import platform_time

import json, os, glob, random, collections, statistics, datetime, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from topic_taxonomy import rel_tier_of, TIER_VERSION, AGE_BUCKETS   # noqa

HC = CONTENT_OPS_ROOT
OUT = f'{HC}/reports/same_topic'
MIN_N = 8                       # 沿用自家铁律：n<8 不给分位/不给档结论

rows = [json.loads(l) for l in open(f'{OUT}/works.jsonl', encoding='utf-8')]

# ---------- 自家账号（绝对口径：首日 CTR） ----------
own = collections.defaultdict(list)
for r in rows:
    if r['is_own'] and r.get('ctr') is not None:
        own[r['motif']].append(r)

# ---------- 外部：分母可用样本，按桶算相对档 ----------
ext = [r for r in rows if (not r['is_own']) and r['denominator_eligible'] and isinstance(r['read'], (int, float))]
ext_by_bucket = collections.defaultdict(list)
for r in ext:
    ext_by_bucket[r['age_bucket']].append(r['read'])
for r in ext:
    r['tier_rel'] = rel_tier_of(r['read'], ext_by_bucket[r['age_bucket']])

# 交叉账号门：一个母题只由 1-2 个号贡献时，得到的是"账号方差"不是"题材分布"
def gate_of(n, accs):
    if n < MIN_N:
        return f'⚠️ 样本不足(n={n}，还差 {MIN_N-n})'
    if accs < 3:
        return f'⚠️ 只来自 {accs} 个号 → 账号方差，不可读'
    return '✅ 可读分布'


import datetime as _dt
watch = [r for r in rows if (not r['is_own']) and not r['denominator_eligible'] and isinstance(r['read'], (int, float))]

motifs = sorted(set([r['motif'] for r in rows]) - {'未归类', '跨赛道（不计入）'},
                key=lambda m: -len([x for x in ext if x['motif'] == m]))

L = []
ad = L.append
ad('# 同题对照表（同题库 v1）')
ad(f'\n生成 {datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}｜数据源 `reports/same_topic/works.jsonl`（{len(rows)} 条）｜分档口径 `{TIER_VERSION}`\n')
ad('## 读这张表之前必须知道的三件事\n')
ad('1. **这不是"成功率"**。它是「观察窗口内的表现分布」。同题 A 好 B 差，分不清是内容差异、账号权重、发布时段还是平台批次。')
ad('2. **分母只用完整清单来源**（进他人主页 / 自己后台）：%d 条。推荐流/搜索/探针来的 %d 条**不进分母**——那些是平台正在推的，是幸存者。' % (len(ext), len(watch)))
ad('3. **外部样本没有展现量**（网页版只能看到累计阅读）→ 只能同**文章年龄桶**比，且只用桶内相对档（前25%%/中50%%/后25%%）；n<%d 一律写"样本不足"。\n' % MIN_N)
ad('> 自家账号（我的账号）是唯一有**展现+首日CTR**的一列，故它的档位用绝对口径（首日CTR≥4%过线）。\n')

ad('## 一、母题 × 表现分布（外部样本，桶内相对档）\n')
ad('| 母题 | 主页来源 n | 前25% | 中50% | 后25% | 中位阅读 | 跨账号数 | 结论门 |')
ad('|---|---:|---:|---:|---:|---:|---:|---|')
data = {}
for m in motifs:
    v = [r for r in ext if r['motif'] == m]
    n = len(v)
    d = collections.Counter(r['tier_rel'] for r in v)
    med = int(statistics.median([r['read'] for r in v])) if v else None
    accs = len(set(r['account'] for r in v))
    gate = gate_of(n, accs)
    ad(f"| {m} | {n} | {d.get('前25%',0)} | {d.get('中50%',0)} | {d.get('后25%',0)} | {med if med is not None else '-'} | {accs} | {gate} |")
    data[m] = {'ext_n': n, 'ext_tiers': dict(d), 'ext_median_read': med, 'accounts': accs}

ad('\n## 二、自家账号：同母题的首日三指标（绝对口径，最干净的一侧）\n')
ad('| 母题 | n | 首日CTR中位 | 过线(≥4%) | 首日曝光中位 | 首日阅读中位 | 结论门 |')
ad('|---|---:|---:|---:|---:|---:|---|')
for m in sorted(set(list(own.keys())), key=lambda m: -len(own[m])):
    v = own[m]
    if len(v) < 2:
        continue
    ctrs = [r['ctr'] for r in v]
    ad(f"| {m} | {len(v)} | {round(statistics.median(ctrs),2)}% | {sum(1 for c in ctrs if c>=4)} | "
       f"{int(statistics.median([r['first_show'] for r in v if r['first_show'] is not None])) if any(r['first_show'] is not None for r in v) else '-'} | "
       f"{int(statistics.median([r['first_read'] for r in v if r['first_read'] is not None])) if any(r['first_read'] is not None for r in v) else '-'} | "
       f"{'✅' if len(v)>=MIN_N else f'⚠️ n={len(v)}'} |")
    data[m] = data.get(m, {})
    data[m].update({'own_n': len(v), 'own_ctr_med': round(statistics.median(ctrs), 2),
                    'own_over4': sum(1 for c in ctrs if c >= 4)})

ad('\n## 三、"爆/平/败"三档的原始样本（供人眼看，别只看汇总）\n')
for m in motifs[:12]:
    v = [r for r in ext if r['motif'] == m]
    if len(v) < MIN_N:
        continue
    hi = sorted([r for r in v if r['tier_rel'] == '前25%'], key=lambda r: -(r['read'] or 0))[:3]
    lo = sorted([r for r in v if r['tier_rel'] == '后25%'], key=lambda r: (r['read'] or 0))[:3]
    ad(f'**{m}**（n={len(v)}，中位阅读 {int(statistics.median([r["read"] for r in v]))}）')
    for tag, lst in (('高', hi), ('低', lo)):
        for r in lst:
            ad(f'  - [{tag}] {r["read"]} 阅读｜{r["age_bucket"]}｜{r["account"]}｜{r["title"][:46]}')
    ad('')

ad('\n## 四、数据质量与限制（每次生成必带）\n')
ad('| 项 | 现状 |')
ad('|---|---|')
ad(f'| 统一库体量 | {len(rows)} 条（去重后）；可进分母 {len(ext)} 条 |')
ad(f'| 来源结构 | ' + '、'.join(f'{k}:{v}' for k, v in collections.Counter(r["collected_via"] for r in rows).most_common()) + ' |')
ad(f'| 未归类 | {len([r for r in rows if r["motif"]=="未归类"])} 条（见 `未归类.csv`；含大量跨赛道新闻号，需靠账户赛道标签排除） |')
ad(f'| 覆盖度最大的母题 | ' + '、'.join(f'{m}({len([x for x in ext if x["motif"]==m])})' for m in motifs[:5]) + ' |')
ad('| 已知偏差 | ①幸存者偏差（分母已尽量只用完整清单来源）②来源偏差（发现池来自推荐流偶遇）③形式偏差（只有图文卡片带阅读）④年龄桶偏差 |')
ad('| 采集速度 | 随性积累，不专门补采（用户 2026-09-22 拍板）→ **短期只能出"分布"，不能出"结论"** |')

open(f'{OUT}/同题对照表.md', 'w', encoding='utf-8').write('\n'.join(L))
json.dump({'generated': datetime.datetime.now().isoformat(timespec='seconds'),
           'n_rows': len(rows), 'n_ext_denominator': len(ext), 'motifs': data},
          open(f'{OUT}/对照数据.json', 'w'), ensure_ascii=False, indent=1)

# ---------- 抽样复核（每周人工看 10 条） ----------
random.seed(int(platform_time.today_str().strftime('%Y%m%d')))
pick = random.sample(rows, min(10, len(rows)))
R = ['# 归类抽样复核（给人工看 10 条）', '',
     f'生成 {datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}｜复核后把"对/错"回填本文件即可（错的下次改词典）', '']
for r in pick:
    R.append(f"- [ ] {r['title'][:52]}")
    R.append(f"      归类：{r['topic_family']} / **{r['motif']}**（命中 {r['motif_kw'] or '无'}，置信 {r['confidence']}）｜来源 {r['collected_via']}｜阅读 {r['read']}")
open(f'{OUT}/待复核-{platform_time.today_str()}.md', 'w', encoding='utf-8').write('\n'.join(R))

print('\n'.join(L))
print(f"\n→ {OUT}/同题对照表.md、待复核-{platform_time.today_str()}.md、对照数据.json")
