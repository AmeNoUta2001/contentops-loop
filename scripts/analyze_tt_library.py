import json

d = json.load(open('/tmp/tt_final.json'))
rows = []
for k, v in d.items():
    if not isinstance(v, dict):
        continue
    read = v.get('read', 0) or 0
    rows.append({
        'title': k,
        'read': read,
        'digg': v.get('digg', 0) or 0,
        'comment': v.get('comment', 0) or 0,
        'share': v.get('share', 0) or 0,
        'cat': v.get('cat', ''),
        'kw': v.get('kw', ''),
    })

with_read = [r for r in rows if r['read'] > 0]
tuwen = [r for r in with_read if r['cat'] != '视频']
shipin = [r for r in with_read if r['cat'] == '视频']

print(f"=== 总条目 {len(rows)} / 有阅读 {len(with_read)} / 图文 {len(tuwen)} / 视频 {len(shipin)} ===\n")

print("### 图文 TOP 40 (read>0, 按阅读排序)")
for i, r in enumerate(sorted(tuwen, key=lambda x: -x['read'])[:40], 1):
    dgr = r['digg']/r['read']*100 if r['read'] else 0
    print(f"{i:2d}. [{r['cat']}|{r['kw']}] {r['title'][:44]}")
    print(f"     read={r['read']} digg={r['digg']} comment={r['comment']} 赞读比={dgr:.2f}%")

print("\n### 视频 TOP 12")
for i, r in enumerate(sorted(shipin, key=lambda x: -x['read'])[:12], 1):
    print(f"{i:2d}. [{r['kw']}] {r['title'][:44]}  read={r['read']} digg={r['digg']}")
