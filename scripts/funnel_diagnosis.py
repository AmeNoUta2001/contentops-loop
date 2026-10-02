#!/usr/bin/env python3
"""微层漏斗诊断（确定性规则引擎，零 API 成本）v2
分层：先走 canon「五档处置」（给量×点击），量足够时再看「留人/互动」内容层。
依据（全部来自 canon，只读不改）：
  - reports/骨架与池子-诊断框架.md ：只看首日三指标；五档处置；首日曝光=骨架新鲜度×题材池子大小×账号额度
  - reports/标题与封面机制库.md    ：标题端不住 → 24h 改题/换封重发（每篇≤1次、周≤2次）
  - skill toutiao-mp-data          ：完读/均读判断看「同类 rank」不看绝对值（用户 2026-08-24 拍板）
  - 自家实测                       ：互动率与阅读量零相关（r=-0.049）→ 互动不作独立故障，仅附注
输出：reports/漏斗诊断-<日期>.md / .json
用法：python3 scripts/funnel_diagnosis.py
"""

# ── 项目根目录（默认 ~/content-ops-loop，可用环境变量 CONTENT_OPS_ROOT 覆盖）──────
import os as _os_root
CONTENT_OPS_ROOT = _os_root.path.expanduser(
    _os_root.environ.get('CONTENT_OPS_ROOT', '~/content-ops-loop'))
import platform_time

import json, os, re, datetime, collections

ROOT = CONTENT_OPS_ROOT
R = f"{ROOT}/reports"
norm = lambda t: re.sub(r'\s+', '', t or '')

POOL_LINE, BIG_LINE = 300, 900   # 五档：<300 小池 / 300-900 中 / ≥900 大
CTR_LINE, CTR_WEAK, CTR_STRONG = 4.0, 1.0, 6.0
MIN_SHOW, MIN_READ, MIN_READ_KEEP = 100, 5, 30

# 统一故障标签（与 LLM 对照测试共用同一套）
FAULT = {'A': 'A_数据不足或给量不足', 'B': 'B_标题或封面（点击端不住）',
         'C': 'C_开头承诺兑现', 'D': 'D_正文节奏', 'E': 'E_结尾互动', 'F': 'F_健康（无明显故障）'}
NEXT = {'A_pool': '换更大池·题材', 'A_wait': '等数据够了再判', 'resend': '改题+换封面重发',
        'C': '改开头3秒', 'D': '精简中段', 'E': '加结尾钩', 'F': '什么都不改'}


def diagnose(show, read, ctr, cr=None, cr_rank=None, dur=None, itr_rank=None):
    """返回 dict：五档 / 四门 / fault(标签) / next(动作标签) / 说明"""
    show = show or 0; read = read or 0; ctr = ctr if ctr is not None else 0
    notes, susp = [], []

    # ---- 五档处置（canon）：tier 只表达「给量」----
    if show >= BIG_LINE: tier = 1
    elif show >= POOL_LINE: tier = 2
    else: tier = 3

    # ---- 四门 ----
    pool = '小' if show < POOL_LINE else ('中' if show < BIG_LINE else '大')
    click = '不可判(样本不足)' if (show < MIN_SHOW or read < MIN_READ) else (
        '端不住' if ctr < CTR_WEAK else ('偏弱' if ctr < CTR_LINE else ('过线' if ctr < CTR_STRONG else '强')))
    if read < MIN_READ_KEEP:
        keep = f'不可判（阅读{read}<30，个把人头不构成完读数据）'
    elif cr_rank in (None, -1) or cr in (None, -1, 0):
        keep = '不可判（接口无数据）'
    else:
        keep = '差' if cr_rank < 30 else ('中' if cr_rank < 60 else '好')
    if dur not in (None, -1) and dur < 40: notes.append(f'均读偏短（{dur}s）')
    inter = 'N/A' if itr_rank in (None, -1) else ('低' if itr_rank < 30 else ('中' if itr_rank < 60 else '好'))

    # ---- 归因矩阵（canon 顺序 + 测试集暴露的两处修正）----
    # 修正①：CTR 在「阅读<5」时是噪声 → 样本守卫优先于一切判断
    # 修正②：内容层（留人）可判的门槛是「阅读≥30」，不是「曝光≥900」——V13/V17 实测暴露
    if read < MIN_READ or show < MIN_SHOW:                       # 样本/给量不足优先
        fault, nxt = ('A_wait', 'A_wait') if (show < MIN_SHOW and ctr >= CTR_STRONG) else ('A_pool', 'A_pool')
        susp = ['样本不足（阅读<5 或 首日曝光<100）：此曝光下 CTR 不可信，不得据此判内容或改方向']
    elif show < POOL_LINE:                                       # 小池：给量不足优先
        if ctr >= CTR_STRONG:
            fault, nxt = 'B', 'resend'
            susp = ['平台没给量（首日<300）但点击已过 6% 线——标题不是问题，是没被分到量',
                    '24h 内改题/换封重发一次（每篇≤1次、周≤2次）']
        else:
            fault, nxt = 'A_pool', 'A_pool'
            susp = ['给量不足（小池或账号额度低）→ 下篇换更大池；此曝光下 CTR 不可信']
    elif ctr < CTR_WEAK:                                         # 有量、点击端不住
        fault, nxt = 'B', 'resend'; susp = ['有量但点击<1% → 标题为主、封面为次，24h 改题+换封重发']
    elif ctr < CTR_LINE:                                         # 有量、点击偏弱
        fault, nxt = 'B', 'resend'; susp = ['有量但点击偏弱（1-4%）→ 标题未端住，按自检 6 条加固后改题换封']
    elif read < MIN_READ_KEEP:                                   # 点击过线但人头太少，留人测不到
        fault, nxt = 'A_wait', 'A_wait'
        susp = [f'点击已过线，但阅读{read}<30，完读/均读是个把人头的噪声 → 先攒量或补数据再判']
    elif keep == '差':                                            # 内容层
        fault, nxt = 'C', 'C'; susp = ['标题把人带进来了，开头没接住（完读 rank<30）', '正文节奏次之']
    elif keep == '中' and any('均读偏短' in n for n in notes):
        fault, nxt = 'D', 'D'; susp = ['中段拖/信息密度低（完读中 + 均读<40s）']
    elif keep == '好' and inter == '低':
        fault, nxt = 'F', 'E'; susp = ['留人没问题；互动低不构成故障（自家 r=-0.049）→ 结尾钩子仅可选加分']
    elif keep.startswith('不可判'):
        fault, nxt = 'A_wait', 'A_wait'; susp = ['点击过线但留人无数据 → 先补 item_info 再判']
    else:
        fault, nxt = 'F', 'F'; susp = ['无故障']

    insufficiency = 'insufficient' if (show < MIN_SHOW or read < MIN_READ) else 'ok'
    if insufficiency == 'insufficient' and fault not in ('B',):
        susp.insert(0, '⚠️ 样本不足守卫：首日曝光<100 或 阅读<5 → 不得据此改动内容/方向')
    return {'tier': tier, 'pool': pool, 'click': click, 'keep': keep, 'inter': inter,
            'fault': FAULT[fault.split('_')[0]], 'next': NEXT.get(nxt) if nxt else '等数据够了再判',
            'susp': susp, 'notes': notes, 'insufficiency': insufficiency}


def main():
    snap_dir = f"{R}/tt_snapshots"
    snap_f = sorted(f for f in os.listdir(snap_dir) if f.endswith('.json') and not f.startswith('item_info'))[-1]
    snap = json.load(open(f"{snap_dir}/{snap_f}"))
    by_title = {}
    for a in snap['articles']:
        by_title[norm(a['title'])] = a          # 同名重复发布 → 取最新一条
    back = {}
    p = f"{snap_dir}/item_info_backfill.json"
    if os.path.exists(p): back = json.load(open(p))
    first = json.load(open(f"{R}/首日指标.json"))

    rows = []
    for r in first['rows']:
        a = by_title.get(norm(r['title']), {})
        ii = back.get(str(a.get('item_id', '')), {})
        rd = ii.get('ranking_data') or {}
        d = diagnose(r.get('first_show'), r.get('first_read'), r.get('first_ctr'),
                     ii.get('read_complete_rate'), rd.get('read_complete_rate_rank'),
                     ii.get('read_duration'), rd.get('interaction_rate_rank'))
        rows.append({'date': r['pub_date'], 'title': r['title'], 'show': r.get('first_show'),
                     'read': r.get('first_read'), 'ctr': r.get('first_ctr'),
                     'cr': ii.get('read_complete_rate'), 'cr_rank': rd.get('read_complete_rate_rank'),
                     'dur': ii.get('read_duration'), 'itr_rank': rd.get('interaction_rate_rank'),
                     **d})

    today = platform_time.today_str()
    json.dump({'date': today, 'rows': rows}, open(f"{R}/漏斗诊断-{today}.json", 'w'), ensure_ascii=False, indent=1)
    cnt = collections.Counter(x['fault'] for x in rows)
    tier_cnt = collections.Counter(x['tier'] for x in rows)
    L = [f"# 微层漏斗诊断（规则引擎 v2）· {today}\n",
         f"输入：首日曝光/阅读/CTR ＋ 完读率·均读·同类rank（backfill 缓存）｜共 {len(rows)} 篇\n",
         "分层：样本守卫（阅读<5 或 曝光<100 不下结论）→ 给量门（<300 优先判给量不足，除非 CTR≥6% 改题换封重发）→ 点击门（<1% 端不住 / 1-4% 偏弱）→ 点击过线且阅读≥30 才判内容层（完读 rank / 均读）\n",
         "## 给量档分布（档=首日曝光）\n", "| 档 | 含义 | 篇数 |", "|---|---|---|",
         f"| 1 | 首日≥900（有量，可判内容层） | {tier_cnt.get(1,0)} |",
         f"| 2 | 首日 300-900（能判点击，判不了留人） | {tier_cnt.get(2,0)} |",
         f"| 3 | 首日<300（平台没给量优先） | {tier_cnt.get(3,0)} |",
         "\n## 故障标签分布\n", "| 标签 | 篇数 |", "|---|---|"]
    for k, v in cnt.most_common(): L.append(f"| {k} | {v} |")
    L += ["\n## 逐篇\n", "| 日期 | 首日曝光 | 阅读 | CTR | 完读(rank) | 均读 | 档 | 主故障 | 下一篇动作 | 标题 |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for x in sorted(rows, key=lambda z: z['date'], reverse=True):
        L.append(f"| {x['date']} | {x['show']} | {x['read']} | {x['ctr']}% | {x['cr']}({x['cr_rank']}) | {x['dur']} | {x['tier']} | {x['fault']} | {x['next']} | {x['title']} |")
    L += ["\n> ⛔ 硬纪律：本表只出「单篇故障假设 + 下一篇实验」，**不得**据单篇数据改动方向（宏观层唯一出口=周日「方向合并」cron）。"]
    open(f"{R}/漏斗诊断-{today}.md", 'w').write("\n".join(L))
    print("\n".join(L[:12]))
    print(f"...共 {len(rows)} 篇 → {R}/漏斗诊断-{today}.md")


if __name__ == "__main__":
    main()
