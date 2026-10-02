#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JEV 历史回放 · 执行臂（盲判）

- 只吃 replay_units.json 里已封装的 as-of 信息（构建期已做泄漏过滤）
- 每次调用前把完整 state 与 hash 落盘（/tmp/jev_replay_raw.jsonl，可中断续跑）
- JEV API 只支持 noul(概率) / score(序数) 两类题型，没有开放文本题 → 协议的
  evidence / counter_evidence / reasoning 等文本字段无法由 JEV 产出（如实记录）

用法：python3 scripts/jev_replay_run.py [--limit N] [--dry]
"""

# ── 项目根目录（默认 ~/content-ops-loop，可用环境变量 CONTENT_OPS_ROOT 覆盖）──────
import os as _os_root
CONTENT_OPS_ROOT = _os_root.path.expanduser(
    _os_root.environ.get('CONTENT_OPS_ROOT', '~/content-ops-loop'))

import json, os, sys, time, hashlib, urllib.request

HC = CONTENT_OPS_ROOT
OUT = HC + '/reports/jev-replay'
RAW = '/tmp/jev_replay_raw.jsonl'
URL = 'https://api.typesafe.ai/v1/systemone'
KEY = [l.split('=', 1)[1].strip() for l in open(os.path.expanduser('~/.hermes/profiles/poster/.env'))
       if l.startswith('TYPESAFE_API_KEY=')][0]

NOUL = {
 'P_点击过线': '这篇候选发布后，首日点击率能达到或超过账号自己定的过线线（首日CTR≥4%）——即成为账号近两周里罕见的高点击篇',
 'P_推荐为下一篇': '这个账号应该把这篇候选推荐为下一篇就写（而不是淘汰或再观察）',
 'P_大池': '这个题材属于账号历史数据里的大池（平台愿意给较可观的首日曝光），而不是小池',
 'P_撞族重复': '它与账号最近两周已发的标题在题材或真相内核上明显重复/撞车，属于该淘汰或该再观察的类型',
 'P_风险': '这篇候选存在明显内容或合规风险（虚构官方表态、老人当众难堪、靠藏物藏秘密制造悬念、绝对化表述等）',
}
SCORE = {
 'S_优先级': ({'criteria': ['淘汰', '排后面观察', '正常排期', '优先写']}, 0),
 'S_把握': ({'criteria': ['低', '中', '高']}, 0),
}

def build_state(u):
    ss = u['self_state']
    L = []
    L.append("【身份】你是头条号「我的账号」的主编助手。账号定位：中老年情感向图文，头条单平台，日更 1 篇，靠阅读量赚广告分成。")
    L.append(f"【当前时点】{u['replay_time']}（现在要为今天这一篇做选题判断；下面所有数据都是此刻之前已经发生的）")
    L.append(f"【自家账号状态（截至 {u['asof_snapshot']} 20:00 后台数据）】累计已发 {ss['n_total']} 篇。"
             f"近 14 篇里首日点击率过 4% 的有 {ss['over14']}；近 5 篇首日曝光中位数 {ss['med5_txt']}。")
    L.append("【近 8 篇逐篇（发布日｜题材｜标题｜首日三指标）】\n - " + "\n - ".join(ss['recent_lines']))
    L.append("【近 14 篇标题清单（用于判断是否撞题材/撞内核）】" + " ； ".join(ss['recent14_titles']))
    if ss['pools']:
        L.append("【题材池子（同一题材的篇数/首日曝光中位/首日CTR中位，按池子大小降序）】" + " ； ".join(ss['pools']))
    L.append("【当时在各采集源上已到手的信息（五源）】\n - " + "\n - ".join(u['sources']))
    if u['rules']:
        L.append("【当时这个账号正在执行的规则（从当天任务原文复原）】\n - " + "\n - ".join(u['rules']))
    if u['pool_asof']:
        L.append("【当时系统里已记录在册的其它候选（供参照）】" + " ； ".join(u['pool_asof']))
    L.append(f"【待你判断的候选】《{u['candidate_title']}》（题材归类：{u['candidate_topic']}）")
    L.append("【要求】只做选题判断，不要重写标题、不要写正文、不要做配图或发布时段建议。")
    return "\n".join(L)

def ask(state, timeout=120):
    qs = {k: {"type": "noul", "instructions": v} for k, v in NOUL.items()}
    for k, (spec, _) in SCORE.items():
        qs[k] = {"type": "score", "instructions": k.replace('S_', ''), "criteria": spec['criteria']}
    body = {"state": state, "model": "jev-latest", "questions": qs}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json"})
    r = json.load(urllib.request.urlopen(req, timeout=timeout))
    a = r['answers']
    out = {k: a[k]['noul'] for k in NOUL}
    for k in SCORE:
        out[k] = a[k].get('score')
        out[k + '_conf'] = a[k].get('confidence')
        out[k + '_probs'] = a[k].get('probabilities')
    return out, r.get('usage', {})

def main():
    limit = None; dry = False
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == '--limit': limit = int(args[i + 1])
        if a == '--dry': dry = True
    units = json.load(open(OUT + '/replay_units.json'))
    done = set()
    if os.path.exists(RAW):
        for l in open(RAW, encoding='utf-8'):
            try: done.add(json.loads(l)['unit_id'])
            except Exception: pass
    todo = [u for u in units if u['unit_id'] not in done]
    if limit: todo = todo[:limit]
    print(f"总 {len(units)} 单元，已完成 {len(done)}，本次待跑 {len(todo)}")
    if dry:
        print(build_state(units[0]))
        return
    tin = tout = 0
    with open(RAW, 'a', encoding='utf-8') as f:
        for i, u in enumerate(todo, 1):
            state = build_state(u)
            h = hashlib.sha256(state.encode()).hexdigest()[:16]
            try:
                ans, usage = ask(state)
                tin += usage.get('input_tokens', 0); tout += usage.get('output_tokens', 0)
                rec = {'unit_id': u['unit_id'], 'replay_date': u['replay_date'],
                       'candidate_title': u['candidate_title'], 'candidate_topic': u['candidate_topic'],
                       'state_sha256': h, 'state_chars': len(state), 'answers': ans, 'usage': usage,
                       'label': {'first_show': u['label_first_show'], 'first_read': u['label_first_read'],
                                 'first_ctr': u['label_first_ctr'], 'src': u['label_src']},
                       'ran_at': time.strftime('%Y-%m-%d %H:%M:%S')}
                f.write(json.dumps(rec, ensure_ascii=False) + "\n"); f.flush()
                print(f"[{i}/{len(todo)}] ok {u['replay_date']} P点击={ans['P_点击过线']:.2f} "
                      f"推荐={ans['P_推荐为下一篇']:.2f} 优先级={ans['S_优先级']} | {u['candidate_title'][:20]}", flush=True)
            except Exception as e:
                print(f"[{i}/{len(todo)}] ERR {str(e)[:100]} | {u['candidate_title'][:20]}", flush=True)
            time.sleep(0.2)
    print(f"DONE（本轮 tokens in={tin} out={tout}）→ {RAW}")

if __name__ == '__main__':
    main()
