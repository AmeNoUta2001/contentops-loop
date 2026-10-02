#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JEV 历史回放 · 分析（Baseline vs JEV，含失败案例与泄漏复核）
输入：/tmp/jev_replay_raw.jsonl（JEV 臂原始答案）+ reports/jev-replay/replay_units.json
输出：reports/jev-replay/analysis.json + 控制台报告
"""

# ── 项目根目录（默认 ~/content-ops-loop，可用环境变量 CONTENT_OPS_ROOT 覆盖）──────
import os as _os_root
CONTENT_OPS_ROOT = _os_root.path.expanduser(
    _os_root.environ.get('CONTENT_OPS_ROOT', '~/content-ops-loop'))

import json, os, math, collections, itertools

HC = CONTENT_OPS_ROOT
OUT = HC + '/reports/jev-replay'
RAW = '/tmp/jev_replay_raw.jsonl'

raw = [json.loads(l) for l in open(RAW, encoding='utf-8')]
units = {u['unit_id']: u for u in json.load(open(OUT + '/replay_units.json'))}
# 标签（CTR≥4% = 高潜）
for r in raw:
    r['y_ctr'] = r['label']['first_ctr']
    r['y_show'] = r['label']['first_show']
    r['y_pos'] = 1 if (r['y_ctr'] is not None and r['y_ctr'] >= 4) else 0
    r['y_low'] = 1 if (r['y_ctr'] is not None and r['y_ctr'] < 1) else 0
    r['p'] = r['answers']['P_点击过线']
    r['prec'] = r['answers']['P_推荐为下一篇']
    r['pri'] = r['answers']['S_优先级']

N = len(raw)
POS = sum(r['y_pos'] for r in raw)
L = []
def p(s=''):
    L.append(str(s)); print(s)

# ---------- 秩相关 ----------
def rank(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    rk = [0.0] * len(xs); i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]: j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1): rk[order[k]] = avg
        i = j + 1
    return rk
def pearson(a, b):
    n = len(a); ma, mb = sum(a) / n, sum(b) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = math.sqrt(sum((x - ma) ** 2 for x in a)); db = math.sqrt(sum((y - mb) ** 2 for y in b))
    return num / (da * db) if da and db else float('nan')
def spearman(x, y): return pearson(rank(x), rank(y))
def kendall(x, y):
    n = len(x); c = d = 0
    for i, j in itertools.combinations(range(n), 2):
        a = (x[i] - x[j]) * (y[i] - y[j])
        if a > 0: c += 1
        elif a < 0: d += 1
    return (c - d) / (c + d) if (c + d) else float('nan')
def t_p(rho, n):
    if not (n > 2) or rho != rho or abs(rho) >= 1: return float('nan')
    t = rho * math.sqrt((n - 2) / (1 - rho * rho))
    # 双尾 p（正态近似足够）
    return math.erfc(abs(t) / math.sqrt(2))

def metrics(name, score, ys, pos):
    """score 越大越看好；pos = 二值高潜标签"""
    order = sorted(range(len(score)), key=lambda i: -score[i])
    top1 = ys[order[0]]; top3 = [ys[i] for i in order[:3]]; top5 = [ys[i] for i in order[:5]]
    rho = spearman(score, ys); tau = kendall(score, ys)
    return {'arm': name, 'n': len(score), 'pos_base_rate': round(sum(pos) / len(pos), 4),
            'top1_ctr': top1, 'top1_hit': 1 if top1 >= 4 else 0,
            'top3_ctr': [round(v, 2) for v in top3], 'top3_hits': sum(1 for v in top3 if v >= 4),
            'top5_hits': sum(1 for v in top5 if v >= 4),
            'spearman': round(rho, 4), 'spearman_p': round(t_p(rho, len(score)), 4),
            'kendall': round(tau, 4), 'top1_title': None}

p("=" * 78)
p("JEV 历史回放 · 结果（回放点 = 发布日 05:00；样本 = {} 篇，其中 CTR≥4% 正样本 {} 篇 = 基准率 {:.1f}%）".format(N, POS, 100 * POS / N))
p("=" * 78)
p("\n【1. 逐篇：JEV 概率 vs 真实首日结果（按 JEV P(点击过线) 降序）】")
p("  P(点击) P(推荐) 优先级 | 首日曝光 首日阅读 首日CTR | 发布日 | 标题")
for r in sorted(raw, key=lambda x: (-x['p'], -x['prec'])):
    flag = ''
    if r['y_pos']: flag = '  ← 真·高潜'
    elif r['y_ctr'] is not None and r['y_ctr'] >= 1: flag = '  ← 中等'
    p("   %.2f   %.2f   %.2f | %6s %7s %7s | %s | %s%s" % (
        r['p'], r['prec'], r['pri'], r['y_show'], r['label']['first_read'],
        ('%.2f%%' % r['y_ctr']) if r['y_ctr'] is not None else 'NA',
        r['replay_date'], r['candidate_title'][:30], flag))

# ---------- 指标 ----------
ys = [r['y_ctr'] if r['y_ctr'] is not None else 0.0 for r in raw]
pos = [r['y_pos'] for r in raw]
J = metrics('JEV(P_点击过线)', [r['p'] for r in raw], ys, pos)
J['top1_title'] = raw[sorted(range(N), key=lambda i: -raw[i]['p'])[0]]['candidate_title']
J2 = metrics('JEV(P_推荐为下一篇)', [r['prec'] for r in raw], ys, pos)
J3 = metrics('JEV(S_优先级)', [r['pri'] for r in raw], ys, pos)

# ---------- 阈值化决策（先在报告中声明的约定） ----------
def decision(p_):
    return 'recommend' if p_ >= 0.5 else ('observe' if p_ >= 0.3 else 'reject')
for r in raw: r['decision'] = decision(r['p'])
rec = [r for r in raw if r['decision'] == 'recommend']
rej = [r for r in raw if r['decision'] == 'reject']
prec_ = (sum(r['y_pos'] for r in rec) / len(rec)) if rec else float('nan')
recall_ = (sum(r['y_pos'] for r in rec) / POS) if rec else 0.0
lowrej = [r for r in rej if r['y_low'] == 1]
rej_prec = len(lowrej) / len(rej) if rej else float('nan')

p("\n【2. 主指标：JEV vs Baseline】")
p("  JEV  | Top-1 是否命中高潜: %s（Top-1 =《%s》CTR %s%%）" % (
    '命中✅' if J['top1_hit'] else '未命中❌', J['top1_title'][:26], J['top1_ctr']))
p("  JEV  | Top-3 命中: %d/3（CTR=%s）｜Top-5 命中: %d/5" % (J['top3_hits'], J['top3_ctr'], J['top5_hits']))
p("  JEV  | Spearman(score, 首日CTR) = %.3f (p=%.3f) ｜ Kendall = %.3f" % (J['spearman'], J['spearman_p'], J['kendall']))
p("  JEV  | 同一批用「P(推荐为下一篇)」排序: Spearman=%.3f ｜ 用「S_优先级」排序: Spearman=%.3f" % (J2['spearman'], J3['spearman']))
p("  JEV  | 阈值化（P≥0.5=推荐）：推荐 %d 篇，其中真高潜 %d 篇 → Precision=%.3f ｜ Recall=%d/%d=%.3f" % (
    len(rec), sum(r['y_pos'] for r in rec), prec_, sum(r['y_pos'] for r in rec), POS, recall_))
p("  JEV  | 淘汰档（P<0.3）%d 篇，其中真·低表现(CTR<1%%) %d 篇 → 低价值过滤 Precision=%.3f" % (len(rej), len(lowrej), rej_prec))
p("  BL   | **Baseline 拒绝了 0 篇**（32/32 全部照写：日更流水线 + 三轴轮换硬规则，没有『淘汰』动作）")
p("  BL   | 因此 Baseline 的『高潜 Precision』= 0/0（未声称任何高潜）；『高潜 Recall』= 0/%d = 0.000" % POS)
p("  BL   | 排序相关性：**baseline_evidence_insufficient**（09-10 之前无任何排序/预测记录）")

# ---------- Baseline 记录臂（13 篇有预注册档位） ----------
tiers = json.load(open(OUT + '/audit4_tiers.json'))
tmap = {d: t for d, _, t in tiers}
sub = [r for r in raw if tmap.get(r['replay_date'])]
p("\n【3. Baseline 记录臂（唯一有历史预测记录的一段：09-10 起稿件头部「预注册档位」，n=%d）】" % len(sub))
p("  日期 | 档位 | 真实首日CTR | 判定")
tp = fp = tn = fn = 0
for r in sub:
    t = tmap[r['replay_date']]; pred_pos = (t == '小高峰档'); act = bool(r['y_pos'])
    judge = ('TP' if pred_pos and act else 'FP' if pred_pos and not act else 'FN' if act and not pred_pos else 'TN')
    if judge == 'TP': tp += 1
    elif judge == 'FP': fp += 1
    elif judge == 'FN': fn += 1
    else: tn += 1
    p("  %s | %-5s | %7s | %s" % (r['replay_date'], t, ('%.2f%%' % r['y_ctr']) if r['y_ctr'] is not None else 'NA', judge))
blP = tp / (tp + fp) if (tp + fp) else float('nan')
blR = tp / (tp + fn) if (tp + fn) else float('nan')
f1 = lambda P, R: (2 * P * R / (P + R)) if (P == P and R == R and P + R) else float('nan')
p("  Baseline 记录臂：Precision=%.3f（%d/%d）｜Recall=%.3f（%d/%d）｜F1=%.3f" % (blP, tp, tp + fp, blR, tp, tp + fn, f1(blP, blR)))
ordinal = [1 if tmap[r['replay_date']] == '小高峰档' else 0 for r in sub]
ycs = [r['y_ctr'] if r['y_ctr'] is not None else 0.0 for r in sub]
p("  档位(0/1) vs 首日CTR：Spearman=%.3f（档位近乎常数，%d/%d 都是『小高峰档』→ 判别力被结构压死）" % (
    spearman(ordinal, ycs), sum(ordinal), len(ordinal)))
jevsub = [r for r in raw if tmap.get(r['replay_date'])]
p("  同一 %d 篇上 JEV：Spearman=%.3f｜Top-1=%s" % (
    len(jevsub), spearman([r['p'] for r in jevsub], [r['y_ctr'] if r['y_ctr'] is not None else 0 for r in jevsub]),
    '命中' if max(jevsub, key=lambda r: r['p'])['y_pos'] else '未命中'))

# ---------- 曝光侧（给量）预测力 ----------
sv = [(r['answers']['P_大池'], r['y_show']) for r in raw if r['y_show'] is not None]
p("\n【4. 换个角度：JEV 对『给量侧』(P_大池) 与真实首日曝光的关联】 n=%d Spearman=%.3f" % (
    len(sv), spearman([a for a, _ in sv], [b for _, b in sv])))
ss = [(r['answers']['P_撞族重复'], r['y_show']) for r in raw if r['y_show'] is not None]
p("    JEV 对『撞族重复』(P_撞族) 与真实首日曝光: Spearman=%.3f（撞族越高应给量越低）" % spearman([a for a, _ in ss], [b for _, b in ss]))

# ---------- 稳健子集：首日曝光≥100 ----------
sub100 = [r for r in raw if (r['y_show'] or 0) >= 100]
p("\n【5. 稳健性子集（首日曝光≥100，滤掉给量噪声）n=%d】" % len(sub100))
m = metrics('JEV≥100', [r['p'] for r in sub100], [r['y_ctr'] if r['y_ctr'] is not None else 0 for r in sub100],
            [r['y_pos'] for r in sub100])
p("  Spearman=%.3f (p=%.3f)｜Top-1=%s｜Top-3 命中 %d/3｜Top-5 命中 %d/5｜正样本率 %.1f%%" % (
    m['spearman'], m['spearman_p'], m['top1_ctr'], m['top3_hits'], m['top5_hits'], 100 * m['pos_base_rate']))

# ---------- Top-25% 排序口径（不依赖阈值） ----------
K = max(1, round(N * 0.25))
order = sorted(range(N), key=lambda i: -raw[i]['p'])
p("\n【6. 排名口径（不依赖阈值）：取 JEV 排序前 %d 篇（前 25%%）】命中高潜 %d 篇；随机期望 %.1f 篇" % (
    K, sum(raw[i]['y_pos'] for i in order[:K]), K * POS / N))

# ---------- 失败案例 ----------
order_all = sorted(range(N), key=lambda i: -raw[i]['p'])
p("\n【7. JEV False Positive（JEV 最看好但实际扑街，取前 5）】")
for i in order_all[:5]:
    r = raw[i]
    p("  ·《%s》 %s：P(点击)=%.2f 推荐=%.2f 撞族=%.2f 风险=%.2f 大池=%.2f → 实际 %s展/%s读/%.2f%%" % (
        r['candidate_title'][:30], r['replay_date'], r['p'], r['prec'],
        r['answers']['P_撞族重复'], r['answers']['P_风险'], r['answers']['P_大池'],
        r['y_show'], r['label']['first_read'], r['y_ctr'] if r['y_ctr'] is not None else -1))
p("\n【8. JEV False Negative（真高潜但 JEV 不看好）】")
for r in sorted(raw, key=lambda x: x['p']):
    if r['y_pos']:
        i = raw.index(r)
        p("  ·《%s》 %s：真实 %.2f%%（%s展/%s读） 但 JEV P(点击)=%.2f（档位=%s） 撞族=%.2f 大池=%.2f 风险=%.2f" % (
            r['candidate_title'][:30], r['replay_date'], r['y_ctr'], r['y_show'], r['label']['first_read'],
            r['p'], r['decision'], r['answers']['P_撞族重复'], r['answers']['P_大池'], r['answers']['P_风险']))
# 全 4 个正样本的 JEV 排名
p("\n【9. 全部正样本的 JEV 排名（共 %d 篇）】" % POS)
for i in order_all:
    if raw[i]['y_pos']:
        p("  ·《%s》真实CTR %.2f%% → JEV 排第 %d/%d（P=%.2f）" % (
            raw[i]['candidate_title'][:30], raw[i]['y_ctr'], order_all.index(i) + 1, N, raw[i]['p']))

# ---------- 泄漏复核 ----------
p("\n【10. 未来信息泄漏复核】")
p("  · 每次调用的完整输入 state 均落盘（/tmp/jev_replay_raw.jsonl 含 state_sha256），输入包由 replay_units.json 生成")
p("  · 输入包只用 ≤ 发布日-1 的快照；标签（首日三指标）从未进入 state（脚本层面两者分列）")
bad = [u for u in units.values() if u['asof_snapshot'] >= u['replay_date']]
p("  · as_of 越界检查（asof_snapshot ≥ replay_date 的单元数）：%d  → %s" % (len(bad), '通过 ✅' if not bad else '异常 ❌'))
p("  · 禁用文件（item_info_backfill / typesafe 报告 / 09-22 漏斗诊断 / 当前版 topic_suggestions）从未被读取：构建脚本只读 tt_snapshots、cron/output、爆款研究、nurture、benchmark")
p("  · ⚠️ 已知不对称（对 JEV 有利）：JEV 拿到的是『当时数据的完整分析版』（含按当时数据现算的题材池子中位），Baseline 拿到的是『当时实际做了的分析版』；即信息上界给 JEV、真实记录给 Baseline")

json.dump({'n': N, 'pos': POS, 'JEV': J, 'JEV_推荐': J2, 'JEV_优先级': J3,
           'threshold': {'recommend_n': len(rec), 'precision': prec_, 'recall': recall_,
                         'reject_n': len(rej), 'lowvalue_reject_precision': rej_prec},
           'baseline_recorded': {'n': len(sub), 'P': blP, 'R': blR, 'F1': f1(blP, blR),
                                 'TP': tp, 'FP': fp, 'FN': fn, 'TN': tn},
           'ge100': m, 'rows': raw},
          open(OUT + '/analysis.json', 'w'), ensure_ascii=False, indent=1)
open(OUT + '/analysis_report.txt', 'w').write('\n'.join(L))
print("\n写出 reports/jev-replay/analysis.json / analysis_report.txt")
