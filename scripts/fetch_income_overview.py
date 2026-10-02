#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""头条创作后台「整体收益」页（mp.toutiao.com/profile_v4/analysis/income-overview）数据抓取。

2026-09-29 挖出接口（curl 直调，cookie 同 fetch_tt_stats.py）：
  /mp/agw/statistic/v2/toutiao_income/overview         整体概览（累计/昨日）
  /mp/agw/statistic/v2/toutiao_income/trend            逐日收益（start_date/end_date）
  /mp/agw/statistic/v2/toutiao_income/detail           逐日 vv + 千次阅读单价
  /mp/agw/statistic/v2/toutiao_income/yesterday_detail 昨日明细（含千次单价/阅读粉丝占比）
  /pgc/mp/income/income_statement_abstract             卡片口径：昨日/本月/可提现/累计
  /pgc/mp/income/realtime_withdraw_info                可提现明细（图文收益/其他收益）
单位：收益字段全部是「分」。

用法：python3 fetch_income_overview.py            # 打印 + 落盘 reports/收益概览-<日期>.json
      from fetch_income_overview import fetch, render   # 供 fetch_tt_stats.py 复用
"""
import json, urllib.request, urllib.parse, datetime, os

import sys as _sys
_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tt_cookie import cookie_path as _cookie_path
import platform_time

# cookie 自 2026-10-02 起走加密保险箱（scripts/secretctl.py）；明文不再落在 repo 内
CK_PATH = _cookie_path()
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36")
REF = "https://mp.toutiao.com/profile_v4/analysis/income-overview"
BASE = "https://mp.toutiao.com"


def _get(path, params, ck):
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        'Cookie': ck, 'User-Agent': UA,
        'Accept': 'application/json, text/plain, */*', 'Referer': REF})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode('utf-8'))


def fetch(days=30, cookie=None):
    """返回 {overview, cards, daily[], month_total_yuan, last_n_total_yuan, fetched_at}"""
    ck = cookie or open(CK_PATH).read().strip()
    today = platform_time.today_str()
    sp = {'app_id': '1231',
          'start_date': (today - datetime.timedelta(days=days)).isoformat(),
          'end_date': today.isoformat()}
    ov = _get('/mp/agw/statistic/v2/toutiao_income/overview', {'app_id': '1231'}, ck)['data']
    tr = _get('/mp/agw/statistic/v2/toutiao_income/trend', sp, ck)['data']
    dt = _get('/mp/agw/statistic/v2/toutiao_income/detail',
              dict(sp, type=1, cursor=0, count=100), ck)['data']
    try:
        cards = _get('/pgc/mp/income/income_statement_abstract', {}, ck)['data']
    except Exception:
        cards = []

    dmap = {d['date']: d.get('toutiao_income_detail', {})
            for d in dt.get('toutiao_daily_income_detail_list', [])}
    daily = []
    for d in tr.get('toutiao_daily_income_list', []):
        date = d['date']
        x = dmap.get(date, {}) or {}
        daily.append({
            'date': date,
            'income_yuan': round(d['total_income'] / 100, 2),
            'basic_yuan': round(d.get('basic_income', d['total_income']) / 100, 2),
            'subsidy_yuan': round(d.get('exclusive_subsidy_income', 0) / 100, 2),
            'vv': x.get('vv'),
            'rpm_yuan_per_1k': x.get('final_price_per_thousand_reads'),
        })
    month = today.strftime('%Y-%m')
    return {
        'fetched_at': datetime.datetime.now().isoformat(timespec='seconds'),
        'overview': ov,
        'cards': cards,
        'daily': daily,
        'month_total_yuan': round(sum(r['income_yuan'] for r in daily if r['date'].startswith(month)), 2),
        'last_n_total_yuan': round(sum(r['income_yuan'] for r in daily), 2),
    }


def render(data, tail=7):
    """紧凑文本块，供 cron 日报引用（飞书口径：只给收益与单价，不堆术语）"""
    ov, cards = data['overview'], data.get('cards') or []
    L = []
    card = {c.get('type'): c for c in cards if isinstance(c, dict)}
    canw = card.get('can_withdraw_amount', {})
    L.append("INCOME_OVERVIEW: 昨日 %.2f 元 | 本月 %.2f 元 | 累计 %.2f 元 | 可提现 %.2f 元"
             % (ov.get('yesterday_income', 0) / 100,
                (card.get('monthly_income', {}) or {}).get('total', data['month_total_yuan']),
                (card.get('total_income', {}) or {}).get('total', ov.get('total_income', 0) / 100),
                canw.get('total', canw.get('total_income', 0))))
    sd = (canw.get('settle_info', {}) or {}).get('settle_detail', {})
    if sd:
        L.append("INCOME_CANWITHDRAW_DETAIL: " + " ".join(f"{k} {v}" for k, v in sd.items()))
    L.append(f"INCOME_DAILY (近 {tail} 天 | 收益元 / 阅读量 / 千次阅读单价元)")
    for r in data['daily'][-tail:]:
        L.append("| %s | %.2f 元 | 读 %s | 单价 %s" % (r['date'], r['income_yuan'], r['vv'], r['rpm_yuan_per_1k']))
    return "\n".join(L)


def main():
    data = fetch()
    print(render(data, tail=10))
    p = os.path.expanduser('~/content-ops-loop/reports/收益概览-%s.json' % platform_time.today_str())
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(data, open(p, 'w'), ensure_ascii=False, indent=1)
    print("saved:", p)


if __name__ == '__main__':
    main()
