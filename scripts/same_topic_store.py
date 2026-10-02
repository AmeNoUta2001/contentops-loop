#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同题库 · 归类入库（把**已经采到的**所有文章/作品统一归类落盘）

设计原则（用户 2026-09-22 拍板：不特意去找，只加入库判定）：
  1. **不新增任何采集动作**。本脚本只读已有落盘数据，归类后写一份统一库。
  2. 每条记录都带 `collected_via`。同题对照的**分母只允许 homepage / own 两类来源**，
     推荐流(feed)/搜索(search)/探针(probe) 来源只用于"题材观察"，不进分母
     —— 因为这些来源天然是平台正在推的内容，是幸存者。
  3. 归类为确定性关键词规则（`topic_taxonomy.py`），带 matched_kw 与原置信度，可人工复核。
  4. 幂等：每次全量重建 works.jsonl（源文件是只增的）。

输出：
  reports/same_topic/works.jsonl       一行一篇（统一库）
  reports/same_topic/未归类.csv         需要人工/后续补词典的标题
  reports/same_topic/入库摘要.md        本次入库统计 + 来源分布（供复核）
"""

# ── 项目根目录（默认 ~/content-ops-loop，可用环境变量 CONTENT_OPS_ROOT 覆盖）──────
import os as _os_root
CONTENT_OPS_ROOT = _os_root.path.expanduser(
    _os_root.environ.get('CONTENT_OPS_ROOT', '~/content-ops-loop'))
import platform_time

import json, os, glob, re, hashlib, collections, datetime, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from topic_taxonomy import classify, tier_own, AGE_BUCKETS          # noqa
from benchmark_store import age_bucket, parse_stamp                  # noqa

HC = CONTENT_OPS_ROOT
OUT = f'{HC}/reports/same_topic'
NUR = f'{HC}/reports/nurture'
BEN = f'{HC}/reports/benchmark'
os.makedirs(OUT, exist_ok=True)

# 来源归一（分母可用 = CLEAN_SOURCES）
SRC_MAP = {
    '养号-作者主页': 'homepage',
    '赚钱博主探针': 'probe',
    '同赛道搜索-触发文章': 'search',
    '手动补录-9/12真机': 'manual',
}
def via_of_benchmark(source):
    s = str(source or '')
    if s in SRC_MAP:
        return SRC_MAP[s]
    if s.startswith('同赛道搜索'):
        return 'search'
    if s.startswith('手动补录'):
        return 'manual'
    return 'other'

CLEAN_SOURCES = {'homepage', 'homepage-device', 'homepage-via-search', 'own'}
ACTION_LOG = {'homepage', 'homepage-device', 'homepage-via-search', 'own'}   # 来自"进主页/自己后台"这类完整清单动作


def norm_title(t):
    t = re.sub(r'\s+', '', str(t or '')).strip()
    # 网页版卡片带 UI 词/话题标签前缀（'展开'、'#媒体原创…'）→ 清洗后再归类
    t = re.sub(r'^#[^#]{0,12}#', '', t)
    for w in ('展开', '收起', '全文', '点击查看', '查看全文', '#媒体原创'):
        t = t.replace(w, '')
    return t.strip()


def num(v):
    if isinstance(v, (int, float)):
        return v
    return None


def row(account, title, *, read=None, show=None, ago=None, pub_iso=None, age=None,
        via='other', is_own=0, seen_at=None, stamp=None, extra=None, ctr=None,
        first_read=None, first_show=None, pinned=False):
    t = norm_title(title)
    c = classify(t)
    r = {
        'row_id': hashlib.md5(f'{account}|{t}'.encode()).hexdigest()[:12],
        'account': account, 'is_own': is_own, 'title': t,
        'collected_via': via, 'denominator_eligible': 1 if via in ACTION_LOG else 0,
        'read': read, 'show': show, 'first_read': first_read, 'first_show': first_show, 'ctr': ctr,
        'ago': ago, 'pub_iso': pub_iso, 'age_bucket': age or '未知',
        'seen_at': seen_at, 'stamp': stamp, 'pinned': 1 if pinned else 0,
        'topic_family': c['topic_family'], 'family_kw': c['family_kw'],
        'motif': c['motif'], 'motif_kw': c['motif_kw'], 'confidence': c['confidence'],
        'tier_own': tier_own(ctr) if is_own else None,
        'times_seen': 1,
    }
    if extra:
        r.update(extra)
    return r


def merge(rows, r):
    """同一 (account,title) 合并：阅读取最大、保留有展现的、记出现次数"""
    key = r['row_id']
    if key not in rows:
        rows[key] = r
        return
    a = rows[key]
    a['times_seen'] += 1
    for k in ('read', 'show', 'first_read', 'first_show', 'ctr'):
        if (r.get(k) is not None) and ((a.get(k) is None) or (isinstance(r[k], (int, float)) and isinstance(a.get(k), (int, float)) and r[k] > a[k])):
            a[k] = r[k]
    # 来源优先级：能进分母的来源优先保留
    if r.get('denominator_eligible') and not a.get('denominator_eligible'):
        a['collected_via'] = r['collected_via']; a['denominator_eligible'] = 1
    if r.get('age_bucket') != '未知' and a.get('age_bucket') == '未知':
        a['age_bucket'] = r['age_bucket']
    if r.get('seen_at') and (not a.get('seen_at') or r['seen_at'] > a['seen_at']):
        a['seen_at'] = r['seen_at']; a['stamp'] = r.get('stamp') or a.get('stamp')
    if a.get('pinned') is None:
        a['pinned'] = r['pinned']


def main():
    rows = {}

    # ---- 1) 养号/探针：作者主页 dump（干净来源，含该号多篇作品） ----
    n_dump = n_work = 0
    p = f'{NUR}/authors.jsonl'
    if os.path.exists(p):
        for ln in open(p, encoding='utf-8'):
            try:
                d = json.loads(ln)
            except Exception:
                continue
            n_dump += 1
            acc = d.get('author') or d.get('name') or '?'
            ch = d.get('channel')
            via = {'web': 'homepage', 'web-watch': 'homepage',
                   'web-niche': 'homepage-via-search'}.get(ch, 'homepage-device')
            if d.get('collected_via'):           # 新写入的 dump 自带来源字段，优先
                via = d['collected_via']
            stamp = d.get('stamp'); seen = d.get('seen_at')
            cdt = parse_stamp(seen) or parse_stamp(stamp)
            for w in (d.get('works') or []):
                t = norm_title(w.get('title'))
                if len(t) < 6:
                    continue
                n_work += 1
                ago = w.get('ago')
                merge(rows, row(acc, t, read=num(w.get('read')), show=num(w.get('show')),
                                ago=ago, pub_iso=w.get('pub_iso'),
                                age=age_bucket(ago, cdt) if cdt else '未知',
                                via=via, seen_at=seen, stamp=stamp, pinned=w.get('pinned')))

    # ---- 2) 基准库（已归一化：来源更细，含搜索/探针） ----
    n_bench = 0
    p = f'{BEN}/articles.jsonl'
    if os.path.exists(p):
        for ln in open(p, encoding='utf-8'):
            ln = ln.strip()
            if not ln:
                continue
            try:
                d = json.loads(ln)
            except Exception:
                continue
            t = norm_title(d.get('title'))
            if len(t) < 6:
                continue
            n_bench += 1
            via = via_of_benchmark(d.get('source'))
            if via == 'other' and d.get('source', '').startswith('养号'):
                via = 'homepage'
            merge(rows, row(d.get('account') or '?', t, read=num(d.get('read')), show=num(d.get('show')),
                            ago=d.get('ago'), age=d.get('age_bucket'),
                            via=via, seen_at=d.get('seen_at'), stamp=d.get('stamp'),
                            pinned=d.get('pinned')))

    # ---- 3) 自家账号（口径最干净：有展现+首日三指标） ----
    n_own = 0
    snaps = sorted(f for f in glob.glob(f'{HC}/reports/tt_snapshots/*.json')
                   if os.path.basename(f)[0] == '2')
    firstmap = {}
    fp = f'{HC}/reports/jev-replay/asof_articles_merged.json'
    if os.path.exists(fp):
        for r in json.load(open(fp)):
            firstmap[r['item_id']] = r
    if snaps:
        latest = json.load(open(snaps[-1]))['articles']
        for a in latest:
            t = norm_title(a.get('title'))
            if len(t) < 6 or t.startswith('#'):
                continue
            f = firstmap.get(a['item_id'], {})
            n_own += 1
            merge(rows, row(os.environ.get('SELF_ACCOUNT_NAME', '我的账号'), t, read=num(a.get('read')), show=num(a.get('show')),
                            ctr=f.get('first_ctr'), first_read=f.get('first_read'),
                            first_show=f.get('first_show'),
                            ago='', age='<24h' if f else '未知',
                            via='own', is_own=1, seen_at=snaps[-1][:10],
                            stamp=os.path.basename(snaps[-1])[:10],
                            extra={'pub_date': str(platform_time.from_ts(a['publish_time']).date()) if a.get('publish_time') else None,
                                   'has_firstday': 1 if f.get('first_show') is not None else 0}))

    all_rows = sorted(rows.values(), key=lambda r: (r['topic_family'] != '其他', r['motif'], -(r['read'] or 0)))

    # ---- 4) 挂账号赛道标签（off/mixed 的样本不得进同题分母） ----
    niche = {}
    ap = f'{BEN}/accounts.jsonl'
    if os.path.exists(ap):
        for ln in open(ap, encoding='utf-8'):
            try:
                a = json.loads(ln)
            except Exception:
                continue
            niche[a.get('name')] = a.get('niche') or 'unknown'
    for r in all_rows:
        r['acct_niche'] = 'own' if r['is_own'] else niche.get(r['account'], 'unknown')
        if r['acct_niche'] in ('off',):
            r['denominator_eligible'] = 0        # 跨赛道样本一律不进分母
    with open(f'{OUT}/works.jsonl', 'w', encoding='utf-8') as f:
        for r in all_rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')

    # 未归类清单（含来源，便于判断是词典缺词还是本就是跨赛道内容）
    with open(f'{OUT}/未归类.csv', 'w', encoding='utf-8') as f:
        f.write('collected_via,account,read,age_bucket,title\n')
        for r in all_rows:
            if r['motif'] == '未归类':
                f.write(f"{r['collected_via']},{r['account']},{r['read']},{r['age_bucket']},\"{r['title'][:60]}\"\n")

    # 摘要
    via_cnt = collections.Counter(r['collected_via'] for r in all_rows)
    fam_cnt = collections.Counter(r['topic_family'] for r in all_rows)
    motif_cnt = collections.Counter(r['motif'] for r in all_rows)
    clean = [r for r in all_rows if r['denominator_eligible']]
    L = []
    ad = L.append
    ad('# 同题库 · 入库摘要')
    ad(f'\n生成 {datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}｜统一库 = `reports/same_topic/works.jsonl`\n')
    ad(f'- 源：authors.jsonl dump {n_dump} 次（作品 {n_work} 行）、benchmark/articles {n_bench} 行、自家 {n_own} 篇')
    ad(f'- **去重后独立记录 {len(all_rows)} 条**（同一账号同标题合并，`times_seen` 记出现次数）')
    ad(f'- 其中**可进分母**（主页/自己后台来源）{len(clean)} 条 = {100*len(clean)/max(1,len(all_rows)):.0f}%')
    ad(f'- 未归类 {motif_cnt["未归类"]} 条（清单见 `未归类.csv`）\n')
    ad('## 来源分布（决定谁能进分母）')
    ad('| collected_via | 条数 | 可进分母 |')
    ad('|---|---:|---:|')
    for k, v in via_cnt.most_common():
        ad(f'| {k} | {v} | {"✅" if k in ACTION_LOG else "❌ 只作题材观察"} |')
    ad('\n## 题材族分布（全部）')
    for k, v in fam_cnt.most_common():
        ad(f'- {k}: {v}')
    ad('\n## 母题分布 TOP20')
    for k, v in motif_cnt.most_common(20):
        ad(f'- {k}: {v}')
    open(f'{OUT}/入库摘要.md', 'w', encoding='utf-8').write('\n'.join(L))
    print('\n'.join(L))
    print(f'\n→ {OUT}/works.jsonl / 未归类.csv / 入库摘要.md')


if __name__ == '__main__':
    main()
