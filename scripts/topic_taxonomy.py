#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同题材判定 · 统一分类器（题材族 + 母题）

用途：给「同题对照」提供可复核的归类口径。所有归类都是**确定性关键词规则**，
不调用 LLM（保证可审计、可回溯改阈值）。未命中 = `未归类`，**不硬猜**。

两个层级：
  topic_family 题材族（粗）——沿用 canon 族名，用于池子/分位分析
  motif        母题（细）——同题对照的基本单位，例如「半夜折腾」「老宠临终照顾」

字段纪律：每条归类都带 matched_kw 与 confidence，供人工抽查复核。
"""
import re
import sys

# ---------------- 垂类词典：全部来自 config/vertical.json ----------------
# ⚠️ 换赛道只需要改那个 JSON，不用动这个文件。
import vertical as _vertical

_V = _vertical.load()

FAMILY_RULES = _vertical.families()                  # [(题材族, [关键词])]
MOTIF_RULES = _vertical.motifs()                     # [(母题, [关键词])]，顺序 = 优先级
OFF_NICHE = _vertical.off_vertical()                 # 命中即判「跨赛道（不计入）」
MUST = _vertical.motif_must()                        # {母题: [必须同时命中的词]}
MANUAL_OVERRIDES = _vertical.manual_overrides()      # [(标题子串, 母题, 题材族, 原因)]
STRONG = int(_vertical.threshold('strong_kw_hits'))

if not FAMILY_RULES and not MOTIF_RULES:
    print("[topic_taxonomy] 垂类词典是空的（config/vertical.json 没读进来）→ "
          "所有标题都会判成「未归类」。先跑 scripts/vertical.py 看看读到没有。",
          file=sys.stderr)


def _norm(t):
    return re.sub(r'\s+', '', str(t or ''))

def classify(title):
    """→ dict(topic_family, family_kw, motif, motif_kw, confidence)"""
    t = _norm(title)
    for substr, motif, fam, why in MANUAL_OVERRIDES:
        if substr in t:
            return {'topic_family': fam, 'family_kw': [why], 'motif': motif,
                    'motif_kw': ['人工订正:' + substr], 'confidence': 'high'}
    for k in OFF_NICHE:
        if k in t:
            return {'topic_family': '跨赛道', 'family_kw': [k], 'motif': '跨赛道（不计入）',
                    'motif_kw': [k], 'confidence': 'high'}
    fam, fkw = '其他', []
    for name, kws in FAMILY_RULES:
        hit = [k for k in kws if k in t]
        if hit:
            fam, fkw = name, hit
            break
    best, bkw, bscore = '未归类', [], (0, 0)
    for name, kws in MOTIF_RULES:
        hit = [k for k in kws if k in t]
        if not hit:
            continue
        need = MUST.get(name)
        if need and not any(k in t for k in need):
            continue                      # AND 组不满足 → 不认这一条（防泛词误吃）
        # 打分：命中词数优先，并列时用「命中词总长度」比具体度（长词更具体，如"猫砂怎么选" > "猫"）
        score = (len(hit), sum(len(k) for k in hit))
        if score > bscore:
            best, bkw, bscore = name, hit, score
    conf = 'high' if len(bkw) >= STRONG else ('low' if bkw else 'none')
    return {'topic_family': fam, 'family_kw': fkw, 'motif': best,
            'motif_kw': bkw, 'confidence': conf}


# ---------------- 表现分档 ----------------
# 关键实测（2026-09-22，665 篇主页元数据）：各年龄桶的阅读分布差异极大且整体很低
#   <24h P50=1 P66=3 ｜ 1-3d P50=10 P66=33 ｜ 7-30d P50=99 P66=436 ｜ >30d P50=267 P66=731
# ⇒ 用「拍脑袋的绝对阈值」一定会定错档（初版阈值 100/1000 直接被数据否掉）。
# 因此：外部样本只用**桶内相对档**，且档位在报告期现算（不落库，避免样本增长后档位过期）。
AGE_BUCKETS = ['<24h', '1-3d', '3-7d', '7-30d', '>30d', '未知']
TIER_VERSION = 'rel-v1（桶内相对档：前25%/中50%/后25%，只在「主页来源」样本内算）'


def rel_tier_of(read, bucket_values):
    """在**同一年龄桶**的样本内算相对档（外部样本口径；绝对阅读量必须随行输出）"""
    if read is None:
        return '无数据'
    v = sorted(x for x in bucket_values if isinstance(x, (int, float)))
    n = len(v)
    if n < int(_vertical.threshold('min_n_quantile')):   # 样本太少不给分位结论
        return '样本不足'
    import bisect
    lo = v[int(0.25 * n)]
    hi = v[int(0.75 * (n - 1))]
    if read >= hi:
        return '前25%'
    if read < lo:
        return '后25%'
    return '中50%'


def tier_own(first_ctr):
    """自家账号用首日 CTR 定档（过线值来自 vertical.thresholds.own_pass_ctr；
    绝对口径，因为自家有展现与首日数据）"""
    if first_ctr is None:
        return '无数据'
    if first_ctr >= float(_vertical.threshold('own_pass_ctr')):
        return '高'
    if first_ctr >= 1:
        return '中'
    return '低'


if __name__ == '__main__':
    import sys
    for t in (sys.argv[1:] or ['我家橘猫半夜踩脸，一夜没睡好',
                               '新猫进门第七天，旧猫终于肯跟它一起睡了',
                               '老得走不动那阵子，我每天抱它下楼晒太阳']):
        print(t, '→', classify(t))
