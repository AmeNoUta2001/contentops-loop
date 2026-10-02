#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""头条创作后台数据自动拉取 v4（cron 版，全量分页）
- /api/feed/mp_provider/v1/ 全量翻页（offset 分页，70+ 条全拿到）
- 每篇基础统计（读/赞/评/藏）直接从列表接口取，零额外请求
- 最近 N 篇已发布文章：traffic_analyse（CTR/趋势）+ user_property（画像）
- 快照存 ~/content-ops-loop/reports/tt_snapshots/YYYY-MM-DD.json
输出：COOKIE_OK/COOKIE_EXPIRED + 已发布文章明细 + PORTRAIT 画像行
"""

# ── 项目根目录（默认 ~/content-ops-loop，可用环境变量 CONTENT_OPS_ROOT 覆盖）──────
import os as _os_root
CONTENT_OPS_ROOT = _os_root.path.expanduser(
    _os_root.environ.get('CONTENT_OPS_ROOT', '~/content-ops-loop'))
import platform_time

import json, subprocess, sys, time, datetime, os, urllib.parse
import exitcodes

# cookie 自 2026-10-02 起走加密保险箱（content-ops-loop/scripts/tt_cookie.py → secretctl.py）；
# 明文不再落在 repo 内，仓库外运行副本 ~/.cheat-secrets/tt_mp_cookies.txt（600）
# 注意：tt_cookie/secrets_env 这两个模块住在 content-ops-loop/scripts/ 下（本文件在 profile 目录里）
_CC_SCRIPTS = os.path.dirname(os.path.abspath(__file__))   # 同级模块始终在脚本旁
for _p in (os.path.dirname(os.path.abspath(__file__)), _CC_SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from tt_cookie import cookie_path as _tt_cookie_path, load_cookie as _tt_load_cookie

COOKIE_FILE = _tt_cookie_path()
if not (os.path.exists(COOKIE_FILE) and os.path.getsize(COOKIE_FILE) > 0):
    print("COOKIE_EXPIRED: 保险箱与兜底位置都没有 cookie（需重新贴 cookie 入库）")
    sys.exit(exitcodes.CREDENTIAL)
SNAP_DIR = os.path.join(CONTENT_OPS_ROOT, 'reports/tt_snapshots')
VISITED_UID = os.environ.get('TT_USER_ID', '')  # 头条号 user_id
DEEP_N = 12  # 最近 N 篇拉深度数据
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"


def load_cookie():
    if not os.path.exists(COOKIE_FILE):
        print("COOKIE_EXPIRED: cookie 文件不存在"); sys.exit(exitcodes.CREDENTIAL)
    with open(COOKIE_FILE) as f:
        c = f.read().strip()
    if not c:
        print("COOKIE_EXPIRED: cookie 文件为空"); sys.exit(exitcodes.CREDENTIAL)
    return c


COOKIE = load_cookie()


def curl(url, referer="https://mp.toutiao.com/profile_v4/manage/content/all", timeout=20):
    r = subprocess.run(
        ["curl", "-s", "--max-time", str(timeout), url,
         "-H", f"Cookie: {COOKIE}", "-H", f"User-Agent: {UA}",
         "-H", "Accept: application/json, text/plain, */*",
         "-H", "Accept-Language: zh-CN,zh;q=0.9",
         "-H", f"Referer: {referer}"],
        capture_output=True, text=True, timeout=timeout + 10)
    return r.stdout


def fetch_all_articles():
    """新接口全量分页（2026-08-23 修复：count=10 小页 offset 翻页会元素漂移漏项，
    老班长篇曾被漏掉；改为 count=100 一页拿全，has_more 才继续翻页兜底）"""
    seen = {}
    offset = 0
    for page in range(30):
        cep = json.dumps({'category': 'mp_all', 'real_app_id': '1231', 'need_forward': 'true',
                          'offset_mode': '1', 'page_index': str(page + 1), 'status': '8', 'source': '0'},
                         separators=(',', ':'))
        genre = json.dumps({'repost': 1, 'small_video': 1, 'toutiao_graphic': 1, 'weitoutiao': 1, 'xigua_video': 1},
                           separators=(',', ':'))
        url = ("https://mp.toutiao.com/api/feed/mp_provider/v1/?provider_type=mp_provider&aid=13"
               "&app_name=news_article&category=mp_all&channel=&stream_api_version=88"
               f"&genre_type_switch={urllib.parse.quote(genre)}&device_platform=pc&platform_id=0"
               f"&visited_uid={VISITED_UID}&offset={offset}&count=100&keyword="
               f"&client_extra_params={urllib.parse.quote(cep)}&app_id=1231")
        out = curl(url)
        try:
            d = json.loads(out)
        except Exception:
            print(f"page {page} 解析失败: {out[:150]}")
            break
        if 'user not login' in str(d.get('message', '')).lower():
            print("COOKIE_EXPIRED:", d.get('message'))
            sys.exit(exitcodes.CREDENTIAL)
        if d.get('errno') not in (0, 20100):
            print(f"API_ERROR errno={d.get('errno')} msg={d.get('message')}")
            sys.exit(exitcodes.UPSTREAM)
        items = d.get('data', [])
        for it in items:
            cell = it.get('assembleCell', {}).get('itemCell', {})
            ab = cell.get('articleBase', {})
            cc = cell.get('itemCounter', {})
            gid = ab.get('gidStr')
            if not gid or gid in seen:
                continue
            seen[gid] = {
                'item_id': gid,
                'title': ab.get('title', ''),
                'item_status': ab.get('itemStatus'),
                'publish_time': ab.get('publishTime', 0),
                'create_time': ab.get('createTime', 0),
                'read': cc.get('readCount', 0),
                'show': cc.get('showCount', 0),  # 展现量（2026-08-22 实测：列表接口自带，低阅读文也可用）
                'digg': cc.get('diggCount', 0),
                'comment': cc.get('commentCount', 0),
                'repin': cc.get('repinCount', 0),
            }
        if not d.get('has_more'):
            break
        offset += 100
        time.sleep(0.5)
    return list(seen.values())


def fetch_property(item_id):
    url = f"https://mp.toutiao.com/mp/agw/statistic/v2/item/user_property?item_id={item_id}&type=1&app_id=1231"
    out = curl(url, referer="https://mp.toutiao.com/profile_v4/graphic/articles")
    try:
        d = json.loads(out)
        if d.get('code') != 0:
            return None
        p = d.get('user_property_data', {})
        return {'age': p.get('fansage', {}), 'gender': p.get('fansgender', {}),
                'device': p.get('fansdevice', {}), 'province': p.get('fansprovince', {})}
    except Exception:
        return None


def fetch_item_info(item_id):
    """单篇数据卡片接口（2026-08-24 挖出）：返回 item_stat.ranking_data（read_complete_rate_rank 等
    rank 字段）+ consume_detail（read_complete_rate/read_duration/click_rate 官方口径）。
    rank 语义：如 read_complete_rate_rank=52 表示完读率超过 52% 同类作品（判断完读好坏看 rank，
    不要看绝对完读率数字主观臆断）。"""
    url = f"https://mp.toutiao.com/mp/agw/statistic/v2/item/info?item_id={item_id}&type=1&app_id=1231"
    out = curl(url, referer="https://mp.toutiao.com/profile_v4/graphic/articles")
    try:
        d = json.loads(out)
        if d.get('code') != 0:
            return None
        st = d.get('item_data', {}).get('item_stat', {})
        cd = st.get('consume_detail', {})
        return {
            'ranking_data': st.get('ranking_data', {}),
            'read_complete_rate': cd.get('read_complete_rate'),
            'read_duration': cd.get('read_duration'),
            'click_rate_official': cd.get('click_rate'),
        }
    except Exception:
        return None


def fetch_traffic(item_id, from_date, to_date):
    url = (f"https://mp.toutiao.com/mp/agw/statistic/v2/item/traffic_analyse"
           f"?from={from_date}&to={to_date}&item_id={item_id}&platform=%E5%85%A8%E9%83%A8&type=1&app_id=1231")
    out = curl(url, referer="https://mp.toutiao.com/profile_v4/graphic/articles")
    try:
        d = json.loads(out)
        if d.get('code') != 0:
            return None
        ts = d.get('total_stat', {})
        cd = ts.get('consume_detail', {})
        days = []
        for ds in d.get('daily_stats', []):
            c = ds.get('consume_data', {})
            days.append({'date': ds.get('date'), 'impression': c.get('impression_count'), 'read': c.get('go_detail_count')})
        return {'click_rate': cd.get('click_rate'), 'daily': days}
    except Exception:
        return None


def fetch_income(start_date, end_date):
    """单篇收益列表（2026-08-31 挖出）：article_income 接口返回窗口内全部文章的累计收益。
    收益单位=分（88 分 = 0.88 元）。用于算千次阅读单价（RPM），判断文章流量"值不值钱"。
    ⚠️ 单价与读者结构有关（一条未经充分验证的假设：读者性别比例会影响广告出价）。
    这条要自己算，别用平均值估 —— 同一阅读量下不同读者结构，收益可以差一个量级。
    """
    url = (f"https://mp.toutiao.com/mp/agw/statistic/v2/toutiao_income/article_income"
           f"?type=1&cursor=0&count=100&start_date={start_date}&end_date={end_date}&app_id=1231")
    out = curl(url, referer="https://mp.toutiao.com/profile_v4/analysis/new-income-advertisement")
    try:
        d = json.loads(out)
        if d.get('code') != 0:
            return {}
        res = {}
        for a in d.get('data', {}).get('toutiao_article_income', []):
            inc = a.get('income_data', {})
            total = inc.get('total_income', {}).get('amount', '0')
            share = inc.get('share_income', {}).get('amount', '0')
            res[a.get('item_id')] = {
                'income_fen': int(total or 0),
                'share_income_fen': int(share or 0),
            }
        return res
    except Exception:
        return {}


def main():
    today = platform_time.today_str()
    articles = fetch_all_articles()
    print(f"TOTAL_ARTICLES: {len(articles)}")

    published = [a for a in articles if a['item_status'] == 20]
    published.sort(key=lambda x: -(x['publish_time'] or 0))
    print(f"PUBLISHED: {len(published)}")

    results = []
    deep = published[:DEEP_N]
    # 收益：拉近 35 天窗口（覆盖所有在榜文章的累计收益），挂到每篇上
    incomes = fetch_income((platform_time.today_str() - datetime.timedelta(days=35)).isoformat(), today)
    for a in published:
        show = platform_time.from_ts(a['publish_time']).date().isoformat() if a['publish_time'] else ''
        a['show_date'] = show
        # CTR = 阅读/展现，列表接口自带 showCount，全部文章可算（低阅读文不再依赖 traffic 接口）
        a['ctr_calc'] = round(a['read'] / a['show'] * 100, 2) if a['show'] else 0
        inc = incomes.get(a['item_id'])
        if inc:
            a['income'] = inc
            # 千次阅读单价 RPM = 收益(分) / 阅读 × 1000 → 元/千读（×10/读）
            a['income_rpm'] = round(inc['income_fen'] * 10 / a['read'], 4) if a['read'] else 0
        traffic = prop = item_info = None
        if a in deep:
            if a['read'] >= 30:
                traffic = fetch_traffic(a['item_id'], show, today)
            prop = fetch_property(a['item_id'])
            item_info = fetch_item_info(a['item_id'])
            time.sleep(0.5)
        a['traffic'] = traffic
        a['property'] = prop
        a['item_info'] = item_info
        results.append(a)

    os.makedirs(SNAP_DIR, exist_ok=True)
    snap_path = os.path.join(SNAP_DIR, f"{today}.json")
    # ⚠️ 防空覆盖（2026-08-23 实测：接口偶发瞬时返回空 data，若直接覆盖会把当天快照冲成空）
    # 已发布数为 0 且快照文件已存在 → 不覆盖，保留旧数据，输出警告
    if len(published) == 0 and os.path.exists(snap_path):
        with open(snap_path, encoding='utf-8') as _f:
            _old = json.load(_f)
        if _old.get('articles'):
            print(f"WARN: API 返回 0 篇（瞬时空响应），保留旧快照 {snap_path}（{len(_old['articles'])} 篇）")
            # 仍输出 COOKIE_OK 但注明 0，让 agent 知道本次是空响应
            print("EMPTY_RESPONSE: 接口返回 0 篇，快照未覆盖")
            sys.exit(exitcodes.BAD_DATA)
    with open(snap_path, 'w', encoding='utf-8') as f:
        json.dump({'date': today, 'articles': results}, f, ensure_ascii=False, indent=1)

    print("COOKIE_OK")
    print(f"SNAPSHOT: {snap_path}")
    print(f"PUBLISHED_COUNT: {len(published)}")
    for a in results:
        ctr = f"{a['traffic']['click_rate']*100:.1f}%" if a['traffic'] and a['traffic'].get('click_rate') else "-"
        ctr_calc = f"{a['ctr_calc']}%" if a['show'] else "-"
        rank = ""
        if a.get('item_info') and a['item_info'].get('ranking_data'):
            rd = a['item_info']['ranking_data']
            rank = f" 完读rank{rd.get('read_complete_rate_rank', '-')} CTRrank{rd.get('click_rate_rank', '-')} 完读{a['item_info'].get('read_complete_rate', '-')}"
        inc_str = ""
        if a.get('income'):
            inc_str = f" 收益{a['income']['income_fen']/100:.2f}元 单价{a['income_rpm']}元/千读"
        print(f"| {a['title']} | {a['show_date']} | 展{a['show']} 读{a['read']} CTR{ctr_calc} (traffic{ctr}) 赞{a['digg']} 评{a['comment']} 藏{a['repin']}{rank}{inc_str}")
    for a in results[:DEEP_N]:
        p = a.get('property')
        if p and p.get('age'):
            total = sum(p['age'].values())
            over50 = p['age'].get('>50', 0)
            g = p.get('gender', {})
            g_total = g.get('女', 0) + g.get('男', 0)
            g_f = round(g.get('女', 0) / g_total * 100, 1) if g_total else 0
            print(f"PORTRAIT | {a['title'][:20]} | 样本{total} 50+占比{round(over50/total*100,1)}% 女{g_f}%")

    # 首日三指标 + 题材池子表（2026-09-12 新增；失败绝不影响主流程）
    try:
        print_first_day()
    except Exception as e:
        print(f"FIRSTDAY_ERROR: {e}")

    # 整体收益（收益分析-概览页，2026-09-29 新增；失败绝不影响主流程）
    try:
        print_income_overview()
    except Exception as e:
        print(f"INCOME_OVERVIEW_ERROR: {e}")


def print_income_overview():
    """整体收益：昨日/本月/累计/可提现 + 近 7 天「收益/阅读量/千次阅读单价」
    实现见 ~/content-ops-loop/scripts/fetch_income_overview.py（复用同一 cookie）。"""
    import importlib.util
    mod_path = os.path.join(CONTENT_OPS_ROOT, 'scripts/fetch_income_overview.py')
    if not os.path.exists(mod_path):
        print("INCOME_OVERVIEW: 跳过（未找到 fetch_income_overview.py）")
        return
    spec = importlib.util.spec_from_file_location('fetch_income_overview', mod_path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    data = m.fetch()
    print(m.render(data, tail=7))
    p = os.path.expanduser('~/content-ops-loop/reports/收益概览-%s.json' % platform_time.today_str())
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"INCOME_OVERVIEW_FILE: {p}")


def print_first_day():
    """首日三指标 + 题材池子表（2026-09-12 用户拍板的新复盘口径，见 content-ops-loop/scripts/first_day_metrics.py）"""
    import importlib.util
    mod_path = os.path.join(CONTENT_OPS_ROOT, 'scripts/first_day_metrics.py')
    if not os.path.exists(mod_path):
        print("FIRSTDAY: 跳过（未找到 first_day_metrics.py）")
        return
    spec = importlib.util.spec_from_file_location('first_day_metrics', mod_path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    out = m.build()
    text = m.render(out)
    print(text)
    rep_dir = os.path.join(CONTENT_OPS_ROOT, 'reports')
    try:
        with open(os.path.join(rep_dir, '首日指标.json'), 'w', encoding='utf-8') as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        with open(os.path.join(rep_dir, '题材池子表.md'), 'w', encoding='utf-8') as f:
            f.write(text + '\n')
        print("FIRSTDAY_FILES: ~/content-ops-loop/reports/首日指标.json + 题材池子表.md 已更新")
    except Exception as e:
        print(f"FIRSTDAY_FILES_ERROR: {e}")


if __name__ == "__main__":
    main()
