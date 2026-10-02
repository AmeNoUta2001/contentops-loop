#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Probe mp_provider API response: dump ALL fields of itemCounter/articleBase
to find the 展现量 (impression/show) field the script currently ignores."""
import json, subprocess, os, urllib.parse, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tt_cookie import cookie_path, load_cookie

# cookie 自 2026-10-02 起走加密保险箱（scripts/secretctl.py）
COOKIE_FILE = cookie_path()
COOKIE = load_cookie()
VISITED_UID = os.environ.get('TT_USER_ID', '')
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"

def curl(url, referer="https://mp.toutiao.com/profile_v4/manage/content/all", timeout=20):
    r = subprocess.run(
        ["curl", "-s", "--max-time", str(timeout), url,
         "-H", f"Cookie: {COOKIE}", "-H", f"User-Agent: {UA}",
         "-H", "Accept: application/json, text/plain, */*",
         "-H", "Accept-Language: zh-CN,zh;q=0.9",
         "-H", f"Referer: {referer}"],
        capture_output=True, text=True, timeout=timeout + 10)
    return r.stdout

cep = json.dumps({'category': 'mp_all', 'real_app_id': '1231', 'need_forward': 'true',
                  'offset_mode': '1', 'page_index': '1', 'status': '8', 'source': '0'}, separators=(',', ':'))
genre = json.dumps({'repost': 1, 'small_video': 1, 'toutiao_graphic': 1, 'weitoutiao': 1, 'xigua_video': 1}, separators=(',', ':'))
url = ("https://mp.toutiao.com/api/feed/mp_provider/v1/?provider_type=mp_provider&aid=13"
       "&app_name=news_article&category=mp_all&channel=&stream_api_version=88"
       f"&genre_type_switch={urllib.parse.quote(genre)}&device_platform=pc&platform_id=0"
       f"&visited_uid={VISITED_UID}&offset=0&count=3&keyword="
       f"&client_extra_params={urllib.parse.quote(cep)}&app_id=1231")

out = curl(url)
try:
    d = json.loads(out)
except Exception:
    print("JSON parse fail:", out[:300])
    raise SystemExit

if d.get('errno') not in (0, 20100):
    print("API_ERROR:", d.get('errno'), d.get('message'))
    raise SystemExit

items = d.get('data', [])
print(f"items on page: {len(items)}")
for it in items[:3]:
    cell = it.get('assembleCell', {}).get('itemCell', {})
    ab = cell.get('articleBase', {})
    cc = cell.get('itemCounter', {})
    print("=" * 60)
    print("TITLE:", ab.get('title', '')[:40])
    print("itemCounter keys:", sorted(cc.keys()))
    print("itemCounter values:", {k: v for k, v in cc.items() if v not in (0, None, '', [], {})})
    # also scan the whole item dict for any key containing show/impression/expose
    def find_keys(obj, prefix=""):
        hits = []
        if isinstance(obj, dict):
            for k, v in obj.items():
                kl = k.lower()
                if any(s in kl for s in ('show', 'impress', 'expos', 'view', 'display', 'traffic')):
                    hits.append((prefix + k, v))
                hits.extend(find_keys(v, prefix + k + "."))
        elif isinstance(obj, list) and obj:
            hits.extend(find_keys(obj[0], prefix + "[0]."))
        return hits
    print("show/impress/expos/view/traffic keys anywhere in item:")
    for k, v in find_keys(it)[:20]:
        print("  ", k, "=", v)
