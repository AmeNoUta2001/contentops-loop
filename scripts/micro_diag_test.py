#!/usr/bin/env python3
"""微层诊断对照测试（规则引擎 vs TypeSafe/Jev）
三臂：
  A) 合成样例集 20 条（答案先定，来自 canon）——测准确率 + 安全性（不许推方向/不许误归因互动）
  B) 自家真实稿「有量档」6 条——测引擎与 LLM 的一致性（真实稿无金标准，只测一致率）
  C) 自家真实稿「数据不足档」8 条——测安全守卫：会不会在小样本上编出内容故障
产出：/tmp/micro_diag_test.jsonl + reports/微层诊断-对照测试-<日期>.md
用法：python3 scripts/micro_diag_test.py
"""

# ── 项目根目录（默认 ~/content-ops-loop，可用环境变量 CONTENT_OPS_ROOT 覆盖）──────
import os as _os_root
CONTENT_OPS_ROOT = _os_root.path.expanduser(
    _os_root.environ.get('CONTENT_OPS_ROOT', '~/content-ops-loop'))
import platform_time

import json, os, sys, time, datetime, importlib.util, urllib.request
import exitcodes

# 外部评估器是【可选】的：没配 key 就优雅退出，而不是 import 阶段 KeyError。
# 确定性核心（metrics / taxonomy / benchmark / diagnosis / replay 框架）不依赖它。
KEY = os.environ.get('TYPESAFE_API_KEY', '')
if not KEY:
    print('EXTERNAL_EVAL_MISSING: 未配置 TYPESAFE_API_KEY —— 本脚本是「规则引擎 vs LLM」'
          '对照实验，属可选集成，确定性核心不受影响（见 README · Optional integrations）')
    sys.exit(exitcodes.CONFIG)
URL = "https://api.typesafe.ai/v1/systemone"
ROOT = CONTENT_OPS_ROOT; R = f"{ROOT}/reports"
OUT = '/tmp/micro_diag_test.jsonl'

# 同级模块按【脚本自身所在目录】加载 —— 否则仓库克隆到任意路径都会找不到
_HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("fd", os.path.join(_HERE, "funnel_diagnosis.py"))
fd = importlib.util.module_from_spec(spec); spec.loader.exec_module(fd)

FAULTS = ["A_数据不足或给量不足", "B_标题或封面（点击端不住）", "C_开头承诺兑现",
          "D_正文节奏", "E_结尾互动", "F_健康（无明显故障）"]
NEXTS = ["改题+换封面重发", "换更大池·题材", "改开头3秒", "精简中段", "加结尾钩",
         "什么都不改", "等数据够了再判"]
QS = {
 "fault": {"type": "choice", "instructions": "按数据漏斗，这篇稿的**主故障**是哪一类？规则：先看给量（首日曝光<300=平台没给量），再看点击（CTR<1%=标题端不住），只有拿到量且点击过线才轮到内容层（完读差=开头没接住，完读中+均读<40s=正文节奏）",
           "criteria": {f: (f.split('_',1)[1] if '_' in f else f) for f in FAULTS}},
 "next": {"type": "choice", "instructions": "下一篇该做的**具体实验/动作**是哪一个",
          "criteria": {n: n for n in NEXTS}},
 "change_direction": {"type": "noul", "instructions": "结论里建议改动账号方向、换题材赛道或推翻现有方向"},
 "blame_interaction": {"type": "noul", "instructions": "把互动率低（点赞评论收藏少）当作这篇稿的**主要**故障"},
}

def ask(show, read, ctr, cr, cr_rank, dur, itr_rank, digg=None, comment=None, repin=None):
    state = (f"展现：{show}\nCTR：{ctr}%\n阅读量：{read}\n完读率：{cr}（同类排名 rank {cr_rank}，rank=超过同类作品的百分比，-1 表示无数据）\n"
             f"平均阅读时长：{dur}秒\n互动同类排名 rank：{itr_rank}\n评论：{comment}\n收藏：{repin}")
    body = {"state": state, "model": "jev-latest", "questions": QS}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json"})
    r = json.load(urllib.request.urlopen(req, timeout=90))
    a = r["answers"]
    return {'fault': a['fault']['choice'], 'fault_conf': a['fault'].get('confidence'),
            'next': a['next']['choice'], 'change_direction': a['change_direction']['noul'],
            'blame_interaction': a['blame_interaction']['noul']}, r['usage']

# ---------- 组装三臂 ----------
vigs = json.load(open(f"{R}/微层诊断-测试集-v1.json"))
tasks = []
for v in vigs:
    eng = fd.diagnose(v['show'], v['read'], v['ctr'], v['cr'], v['cr_rank'], v['dur'], v['itr_rank'])
    tasks.append({'arm': 'A_合成', 'id': v['id'], 'note': v['note'], **{k: v[k] for k in
                  ('show','read','ctr','cr','cr_rank','dur','itr_rank')},
                  'key_fault': v['key_fault'], 'key_next': v['key_next'],
                  'eng_fault': eng['fault'], 'eng_next': eng['next']})

diag = json.load(open(f"{R}/漏斗诊断-{platform_time.today_str()}.json"))
rows = diag['rows']
have = [r for r in rows if r['fault'] != 'A_数据不足或给量不足'][:6]
lack = [r for r in rows if r['fault'] == 'A_数据不足或给量不足']
lack = lack[:4] + lack[-4:]
for r in have + lack:
    tasks.append({'arm': 'B_真实有量' if r in have else 'C_真实数据不足', 'id': r['date'], 'title': r['title'],
                  'show': r['show'], 'read': r['read'], 'ctr': r['ctr'], 'cr': r['cr'], 'cr_rank': r['cr_rank'],
                  'dur': r['dur'], 'itr_rank': r['itr_rank'], 'digg': r.get('digg'), 'comment': r.get('comment'),
                  'repin': r.get('repin'), 'eng_fault': r['fault'], 'eng_next': r['next']})

done = set()
if os.path.exists(OUT):
    for l in open(OUT):
        try: done.add(json.loads(l)['id'] + json.loads(l)['arm'])
        except Exception: pass

print(f"共 {len(tasks)} 条（合成 {sum(1 for t in tasks if t['arm']=='A_合成')} / 真实有量 {len(have)} / 真实数据不足 {len(lack)}），已完成 {len(done)}", flush=True)
tout_in = tout_out = 0
with open(OUT, 'a') as f:
    for i, t in enumerate(tasks, 1):
        if t['id'] + t['arm'] in done: continue
        try:
            ans, u = ask(t['show'], t['read'], t['ctr'], t['cr'], t['cr_rank'], t['dur'], t['itr_rank'],
                         t.get('digg'), t.get('comment'), t.get('repin'))
            tout_in += u['input_tokens']; tout_out += u['output_tokens']
            f.write(json.dumps({**t, **ans}, ensure_ascii=False) + "\n"); f.flush()
            print(f"[{i}/{len(tasks)}] {t['id']} 引擎={t['eng_fault'][:2]} Jev={ans['fault'][:2]} | next Jev={ans['next']}", flush=True)
        except Exception as e:
            print(f"[{i}/{len(tasks)}] ERR {str(e)[:80]}", flush=True)
        time.sleep(0.2)
print(f"DONE tokens in={tout_in} out={tout_out}", flush=True)
