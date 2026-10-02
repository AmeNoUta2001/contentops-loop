#!/usr/bin/env python3
"""补采集：为全部已发布文章拉「单篇数据卡片」(item_info) = 完读率 / 平均阅读时长 / 4 个同类排名(rank)。
背景：fetch_tt_stats.py 里 DEEP_N=12 只拉最近 12 篇 → 完读率只有 4/111 篇可用，
      而实测（2026-09-21）接口对老文同样返回完整数据 → 瓶颈是采集范围不是接口。
产出：reports/tt_snapshots/item_info_backfill.json  {item_id: {...}}
用法：python3 scripts/backfill_item_info.py [天数窗口，默认全部已发布]
"""

# ── 项目根目录（默认 ~/content-ops-loop，可用环境变量 CONTENT_OPS_ROOT 覆盖）──────
import os as _os_root
CONTENT_OPS_ROOT = _os_root.path.expanduser(
    _os_root.environ.get('CONTENT_OPS_ROOT', '~/content-ops-loop'))

import json, os, sys, time, importlib.util, datetime

ROOT = CONTENT_OPS_ROOT
# 同级模块按【脚本自身所在目录】加载
_HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("fts", os.path.join(_HERE, "fetch_tt_stats.py"))
fts = importlib.util.module_from_spec(spec); spec.loader.exec_module(fts)

snap_dir = f"{ROOT}/reports/tt_snapshots"
snaps = sorted(f for f in os.listdir(snap_dir) if f.endswith('.json') and f != 'item_info_backfill.json')
latest = json.load(open(f"{snap_dir}/{snaps[-1]}"))
arts = latest['articles']
days = int(sys.argv[1]) if len(sys.argv) > 1 else 9999
cut = time.time() - days * 86400
arts = [a for a in arts if (a.get('publish_time') or 0) >= cut and a.get('item_status') == 20]
print(f"待补 {len(arts)} 篇（快照 {snaps[-1]}）", flush=True)

out_path = f"{snap_dir}/item_info_backfill.json"
cache = json.load(open(out_path)) if os.path.exists(out_path) else {}

hit = miss = 0
for i, a in enumerate(arts, 1):
    iid = str(a['item_id'])
    old = cache.get(iid, {})
    # 已拉到过完读率/rank 的跳过（-1 = 接口暂无数据，仍重试一次以便后续更新）
    if old.get('read_complete_rate') not in (None, -1) or (old.get('ranking_data') or {}).get('click_rate_rank', -1) not in (-1, None):
        continue
    try:
        ii = fts.fetch_item_info(a['item_id'])
    except Exception as e:
        ii = None
    if ii:
        ii['title'] = a['title']; ii['fetched_at'] = datetime.datetime.now().isoformat(timespec='seconds')
        cache[iid] = ii
        ok = ii.get('read_complete_rate') not in (None, -1)
        hit += ok; miss += (not ok)
        print(f"[{i}/{len(arts)}] {'OK ' if ok else '空 '} 完读={ii.get('read_complete_rate')} 均读={ii.get('read_duration')} | {a['title'][:26]}", flush=True)
    else:
        print(f"[{i}/{len(arts)}] ERR | {a['title'][:26]}", flush=True)
    if i % 10 == 0:
        json.dump(cache, open(out_path, 'w'), ensure_ascii=False, indent=1)
    time.sleep(0.8)

json.dump(cache, open(out_path, 'w'), ensure_ascii=False, indent=1)
have = sum(1 for v in cache.values() if v.get('read_complete_rate') not in (None, -1))
print(f"DONE 缓存 {len(cache)} 条，其中完成率有效 {have} 条（本轮 新增有效 {hit} / 仍空 {miss}）", flush=True)
