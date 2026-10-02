#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""benchmark_store.py —— 赛道基准子系统：把零散的作者主页采集归一成样本池数据 + 分位数。

数据来源（只读）：
  ~/content-ops-loop/reports/nurture/authors.jsonl        养号会话的作者主页探针
  ~/content-ops-loop/reports/nurture/赚钱博主/*.json       赚钱博主探针（搜名字进来）
  ~/content-ops-loop/reports/benchmark/手动补录.jsonl      人工/一次性补录（同 schema）
  ~/content-ops-loop/reports/首日指标.json                 我方（第0号样本）首日三指标
输出（覆盖）：
  ~/content-ops-loop/reports/benchmark/accounts.jsonl     每账号一行
  ~/content-ops-loop/reports/benchmark/articles.jsonl     每篇文章一行
  ~/content-ops-loop/reports/benchmark/基准快照.md         分层分位数 + 我方分位（周报引用它）

口径纪律（照 decision_sources.md 抗污染五条 + 原文诚实纪律）：
  - 只说公开可见数据；缺失 = null，"不可见" 不反推、不补齐
  - 年龄分桶（采集时刻距发布）：<24h / 1-3d / 3-7d / 7-30d / >30d / 未知
  - 分位数只在样本数 ≥8 的桶里给；全量样本 <20 篇时不给精确排名
  - 不判断对方是否 AI/团队/买量；不把公开数据当后台数据
"""

# ── 项目根目录（默认 ~/content-ops-loop，可用环境变量 CONTENT_OPS_ROOT 覆盖）──────
import os as _os_root
CONTENT_OPS_ROOT = _os_root.path.expanduser(
    _os_root.environ.get('CONTENT_OPS_ROOT', '~/content-ops-loop'))

import glob
import json
import os
import re
import statistics
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from topic_taxonomy import classify as _classify          # 同题库归类（2026-09-22 用户拍板：入库即归类）

# 采集来源 → collected_via（同题对照的分母只认 homepage / own 这类「完整清单」来源）
VIA_MAP = {"养号-作者主页": "homepage", "赚钱博主探针": "probe", "同赛道搜索-触发文章": "search",
           "手动补录-9/12真机": "manual"}


def via_of(source):
    s = str(source or "")
    if s in VIA_MAP:
        return VIA_MAP[s]
    if s.startswith("同赛道搜索"):
        return "search"
    if s.startswith("手动补录"):
        return "manual"
    if s.startswith("养号"):
        return "homepage"
    return "other"

HOME = os.path.expanduser("~")
R = os.path.join(CONTENT_OPS_ROOT, 'reports')
NUR = f"{R}/nurture"
OUT = f"{R}/benchmark"
OUR_FIRSTDAY = f"{R}/首日指标.json"

# 第0号样本 = 我们自己（我的账号），不进入外部样本池（web 探针偶遇会把它也抓进来，须过滤）
SELF = {os.environ.get('SELF_ACCOUNT_NAME', '我的账号')}

import sys as _sys
_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vertical as _vertical          # 赛道内/外判据词表来自 config/vertical.json


def num(v):
    """'2.4万' → 24000；None/'' → None"""
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    if not s or s in ("不可见", "-", "—"):
        return None
    m = re.match(r"^(\d+(?:\.\d+)?)万$", s)
    if m:
        return int(float(m.group(1)) * 10000)
    try:
        return int(float(s))
    except Exception:
        return None


def tier_of(fans):
    n = num(fans)
    if n is None:
        return "未知"
    if n < 10000:
        return "<1万"
    if n < 100000:
        return "1-10万"
    return "≥10万"


# ---- 赛道判据（2026-09-13 用户要求：发现池只收同赛道，跨赛道没意义）----
# 判定口径：拿该账号「主页可见作品标题」算情感/家庭/晚年题材的占比。
#   ≥0.5 → on（进分位）｜0.25-0.5 → mixed（单独列，不进分位）｜<0.25 → off（排除，保留数据作对照）
#   无文章数据 → unknown（无法判定，不进分位）
NICHE_POS = _vertical.niche_pos()
NICHE_NEG = _vertical.niche_neg()



PLACEHOLDER_RE = __import__("re").compile(r"^[（(][^）)]{0,8}[）)]$")


def _useful_title(t):
    if not t:
        return False
    t = str(t).strip()
    return len(t) >= 6 and not PLACEHOLDER_RE.match(t)


def niche_of(titles):
    """→ (niche, pos_hits, n)  niche ∈ on/mixed/off/unknown

    2026-09-13 细化：无同赛道词时再分两种情况——
      命中跨赛道词（科技/历史/财经/悬疑…）→ **off**（明确非赛道）
      既不同赛道也不跨赛道（泛鸡汤/不明）→ **unknown**（不硬判，进待观察）
    """
    ts = [t for t in titles if _useful_title(t)]
    if not ts:
        return "unknown", 0, 0
    pos = sum(1 for t in ts if any(w in t for w in NICHE_POS) and not any(w in t for w in NICHE_NEG))
    neg = sum(1 for t in ts if any(w in t for w in NICHE_NEG) and not any(w in t for w in NICHE_POS))
    r = pos / len(ts)
    if r >= 0.5:
        return "on", pos, len(ts)
    if r >= 0.25:
        return "mixed", pos, len(ts)
    if neg == 0:
        return "unknown", pos, len(ts)      # 判定不出 = 不冒充结论
    return "off", pos, len(ts)


MONTHS = {"01": 1, "02": 2, "03": 3, "04": 4, "05": 5, "06": 6, "07": 7, "08": 8, "09": 9, "10": 10, "11": 11, "12": 12}


def age_bucket(ago, collect_dt):
    """按「采集时刻 − 发布时间」分桶。认不出返回 '未知'。"""
    if not ago or not collect_dt:
        return "未知"
    s = str(ago).strip()
    m = re.match(r"^(\d+)分钟前$", s)
    if m:
        d = timedelta(minutes=int(m.group(1)))
    elif re.match(r"^(\d+)小时前$", s):
        d = timedelta(hours=int(re.match(r"^(\d+)小时前$", s).group(1)))
    elif re.match(r"^(\d+)天前$", s):
        d = timedelta(days=int(re.match(r"^(\d+)天前$", s).group(1)))
    elif s in ("刚刚", "刚才"):
        d = timedelta(minutes=1)
    elif s == "昨天":
        d = timedelta(days=1)
    elif s == "前天":
        d = timedelta(days=2)
    else:
        m = re.match(r"^(\d{1,2})-(\d{1,2})(?:\s+(\d{1,2}):(\d{2}))?$", s)
        if m:
            mo, day = int(m.group(1)), int(m.group(2))
            y = collect_dt.year
            try:
                pub = datetime(y, mo, day, tzinfo=collect_dt.tzinfo)
            except ValueError:
                return "未知"
            if pub > collect_dt:                      # 跨年
                pub = pub.replace(year=y - 1)
            d = collect_dt - pub
        else:
            m = re.match(r"^(\d{4})年(\d{1,2})月(\d{1,2})日$", s)
            if m:
                pub = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=collect_dt.tzinfo)
                d = collect_dt - pub
            else:
                return "未知"
    h = d.total_seconds() / 3600
    if h < 24:
        return "<24h"
    if h < 72:
        return "1-3d"
    if h < 168:
        return "3-7d"
    if h < 720:
        return "7-30d"
    return ">30d"


def parse_stamp(st):
    """'2026-09-12_2151' / '2026-09-12 21:51' → datetime"""
    if not st:
        return None
    for fmt in ("%Y-%m-%d_%H%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(st)[:16], fmt)
        except Exception:
            continue
    return None


def load_sources():
    """→ (accounts[list], articles[list])"""
    accounts, articles = [], []
    # 1) 养号会话的作者主页探针
    p = f"{NUR}/authors.jsonl"
    if os.path.exists(p):
        for ln in open(p, encoding="utf-8"):
            ln = ln.strip()
            if not ln:
                continue
            try:
                d = json.loads(ln)
            except Exception:
                continue
            accounts.append({"name": d.get("author"), "fans": d.get("fans"), "liked": d.get("liked"),
                             "tag": d.get("tag"), "source": "养号-作者主页",
                             "seen_at": d.get("seen_at") or d.get("stamp"), "stamp": d.get("stamp")})
            for w in d.get("works", []):
                articles.append({"account": d.get("author"), "title": w.get("title"),
                                 "show": num(w.get("show")), "read": num(w.get("read")),
                                 "ago": w.get("ago"), "tag": w.get("tag"), "pinned": w.get("pinned"),
                                 "source": "养号-作者主页", "stamp": d.get("stamp"),
                                 "seen_at": d.get("seen_at")})
    # 2) 赚钱博主探针
    for f in sorted(glob.glob(f"{NUR}/赚钱博主/*.json")):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        accounts.append({"name": d.get("resolved_author") or d.get("queried"), "fans": d.get("fans"),
                         "liked": d.get("liked"), "tag": d.get("tag"), "source": "赚钱博主探针",
                         "seen_at": d.get("seen_at"), "queried": d.get("queried"),
                         "match": d.get("match")})
        for w in d.get("works", []):
            articles.append({"account": d.get("resolved_author") or d.get("queried"), "title": w.get("title"),
                             "show": num(w.get("show")), "read": num(w.get("read")),
                             "ago": w.get("ago"), "tag": w.get("tag"), "pinned": w.get("pinned"),
                             "source": "赚钱博主探针", "seen_at": d.get("seen_at")})
    # 2.5) 同赛道关键词发现（2026-09-13 新增：从同赛道文章进作者主页，题材证据自带）
    for f in sorted(glob.glob(f"{NUR}/发现/*.json")):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        accounts.append({"name": d.get("resolved_author") or d.get("kw"), "fans": d.get("fans"),
                         "liked": d.get("liked"), "tag": d.get("tag"),
                         "source": f"同赛道搜索「{d.get('kw')}」", "seen_at": d.get("seen_at")})
        for w in d.get("works", []):
            articles.append({"account": d.get("resolved_author") or d.get("kw"), "title": w.get("title"),
                             "show": num(w.get("show")), "read": num(w.get("read")),
                             "ago": w.get("ago"), "tag": w.get("tag"), "pinned": w.get("pinned"),
                             "source": f"同赛道搜索「{d.get('kw')}」", "seen_at": d.get("seen_at")})
        # 触发链的文章标题也算一条证据（题材来自文章本身，而非主页卡片）
        if d.get("result_title"):
            articles.append({"account": d.get("resolved_author") or d.get("kw"),
                             "title": d.get("result_title"), "show": None, "read": None,
                             "ago": None, "source": "同赛道搜索-触发文章", "seen_at": d.get("seen_at")})

    # 3) 手动补录
    p = f"{OUT}/手动补录.jsonl"
    if os.path.exists(p):
        for ln in open(p, encoding="utf-8"):
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            try:
                d = json.loads(ln)
            except Exception:
                continue
            accounts.append({"name": d.get("name"), "fans": d.get("fans"), "liked": d.get("liked"),
                             "tag": d.get("tag"), "source": d.get("source", "手动补录"),
                             "seen_at": d.get("seen_at", ""),
                             "niche_manual": d.get("niche_manual"), "niche_basis": d.get("niche_basis")})
            for w in d.get("works", []):
                articles.append({"account": d.get("name"), "title": w.get("title"),
                                 "show": num(w.get("show")), "read": num(w.get("read")),
                                 "ago": w.get("ago"), "source": d.get("source", "手动补录"),
                                 "seen_at": d.get("seen_at", "")})
    return accounts, articles


def dedupe(accounts, articles):
    acc = {}
    for a in accounts:
        if not a.get("name") or a.get("name") in SELF:
            continue
        k = a["name"]
        if k not in acc or str(a.get("seen_at") or "") >= str(acc[k].get("seen_at") or ""):
            acc[k] = a
    art = {}
    for x in articles:
        if not x.get("title") or not x.get("account") or x.get("account") in SELF:
            continue
        k = (x["account"], x["title"])
        if k not in art or str(x.get("seen_at") or "") >= str(art[k].get("seen_at") or ""):
            art[k] = x
    return list(acc.values()), list(art.values())


def quant(vals, q):
    vals = sorted(vals)
    if not vals:
        return None
    i = max(0, min(len(vals) - 1, int(round((len(vals) - 1) * q))))
    return vals[i]


PANEL = f"{NUR}/关注博主.txt"


def panel_cleanup(accounts):
    """跟踪组自动清理（2026-09-13 用户选 1：留一轮名单探针，自动判定+移出跨赛道）。

    规则（机械规则，不涉及方向 → 不需要周会）：
      niche=off/mixed → 移出（原因：跨赛道/偏出）
      niche=unknown 且 已有 ≥1 篇可读标题 → 留观（下轮再判）
      niche=unknown 且 完全无标题（只采到粉丝数）→ 留观（还没采到内容）
      niche=on → 保留
    只改「名字行」，保留 # 注释块；改前备份到 关注博主.txt.bak-<日期>。
    """
    if not os.path.exists(PANEL):
        return []
    names = [ln.strip() for ln in open(PANEL, encoding="utf-8") if ln.strip() and not ln.strip().startswith("#")]
    nic = {a["name"]: a.get("niche") for a in accounts}
    drop = [n for n in names if nic.get(n) in ("off", "mixed")]
    if not drop:
        return []
    keep = [n for n in names if n not in drop]
    bak = f"{PANEL}.bak-{datetime.now().strftime('%Y%m%d')}"
    with open(PANEL, encoding="utf-8") as f:
        raw = f.read()
    if not os.path.exists(bak):
        with open(bak, "w", encoding="utf-8") as f:
            f.write(raw)
    head = [ln for ln in raw.split("\n") if ln.strip().startswith("#") or not ln.strip()]
    with open(PANEL, "w", encoding="utf-8") as f:
        f.write("\n".join(head + keep) + "\n")
    # 审计：记到发现池
    fp = f"{OUT}/发现池.md"
    if os.path.exists(fp):
        with open(fp, "a", encoding="utf-8") as f:
            f.write(f"\n### {datetime.now().strftime('%Y-%m-%d')} 自动移出跟踪组（赛道闸门）\n")
            for n in drop:
                f.write(f"- {n}（niche={nic.get(n)}）→ 保留在发现池作对照，不再回访\n")
    return drop


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--clean-panel", action="store_true", help="按赛道判定自动清理跟踪组（周报 cron 用）")
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    accounts, articles = dedupe(*load_sources())

    # 补 age 桶 + CTR + 分层
    for a in accounts:
        a["tier"] = tier_of(a.get("fans"))
        a["fans_num"] = num(a.get("fans"))
        a["liked_num"] = num(a.get("liked"))
    titles_by_name = {}
    for x in articles:
        titles_by_name.setdefault(x["account"], []).append(x.get("title"))
    for a in accounts:
        nic, pos, n = niche_of(titles_by_name.get(a["name"], []))
        if a.get("niche_manual"):          # 人工判定优先（必须带 basis）
            nic = a["niche_manual"]
            a["niche_note"] = f"人工判定：{a.get('niche_basis') or '未写依据'}"
        a["niche"], a["niche_pos_hits"], a["niche_n"] = nic, pos, n
    tier_by_name = {a["name"]: a["tier"] for a in accounts}
    niche_by_name = {a["name"]: a.get("niche", "unknown") for a in accounts}
    for x in articles:
        x["niche"] = niche_by_name.get(x["account"], "unknown")
        # 文章级判定：标题命中同赛道词且不命中跨赛道词 → 该篇可计入分位（2026-09-13）
        _t = x.get("title") or ""
        x["niche_art"] = "on" if (any(w in _t for w in NICHE_POS) and not any(w in _t for w in NICHE_NEG)) else "off"
    for x in articles:
        x["tier"] = tier_by_name.get(x["account"], "未知")
        x["ctr"] = round(x["read"] / x["show"] * 100, 2) if x.get("show") and x.get("read") else None
        x["age_bucket"] = age_bucket(x.get("ago"), parse_stamp(x.get("seen_at") or x.get("stamp")))
        # ---- 入库即归类（2026-09-22 用户拍板：不专门去找，只加一个判定）----
        _c = _classify(x.get("title"))
        x["collected_via"] = via_of(x.get("source"))
        x["denominator_eligible"] = x["collected_via"] in ("homepage", "homepage-device", "homepage-via-search")
        x["topic_family"] = _c["topic_family"]
        x["motif"] = _c["motif"]
        x["motif_kw"] = _c["motif_kw"]
        x["topic_conf"] = _c["confidence"]

    with open(f"{OUT}/accounts.jsonl", "w", encoding="utf-8") as f:
        for a in sorted(accounts, key=lambda z: -(z.get("fans_num") or 0)):
            f.write(json.dumps(a, ensure_ascii=False) + "\n")
    with open(f"{OUT}/articles.jsonl", "w", encoding="utf-8") as f:
        for x in sorted(articles, key=lambda z: (z["age_bucket"], -(z.get("read") or 0))):
            f.write(json.dumps(x, ensure_ascii=False) + "\n")

    # ---- 统计 ----
    def stats(rows):
        reads = [r["read"] for r in rows if r.get("read") is not None]
        shows = [r["show"] for r in rows if r.get("show") is not None]
        ctrs = [r["ctr"] for r in rows if r.get("ctr") is not None]
        if not reads:
            return None
        return {
            "n": len(rows), "n_read": len(reads),
            "read_p25": quant(reads, .25), "read_p50": int(statistics.median(reads)),
            "read_p75": quant(reads, .75), "read_p90": quant(reads, .90), "read_max": max(reads),
            "show_p50": int(statistics.median(shows)) if shows else None,
            "ctr_p50": round(statistics.median(ctrs), 2) if ctrs else None,
            "ge100": round(sum(1 for v in reads if v >= 100) / len(reads) * 100, 1),
            "ge1000": round(sum(1 for v in reads if v >= 1000) / len(reads) * 100, 1),
        }

    # 我方（第0号样本）：首日三指标
    ours = None
    if os.path.exists(OUR_FIRSTDAY):
        try:
            d = json.load(open(OUR_FIRSTDAY, encoding="utf-8"))
            rows = d.get("rows", [])
            fs = [r["first_show"] for r in rows if r.get("first_show")]
            fr = [r["first_read"] for r in rows if r.get("first_read") is not None]
            fc = [r["first_ctr"] for r in rows if r.get("first_ctr") is not None and r.get("first_show")]
            ours = {"n": len(rows), "first_show_p50": int(statistics.median(fs)) if fs else None,
                    "first_read_p50": int(statistics.median(fr)) if fr else None,
                    "first_ctr_p50": round(statistics.median(fc), 2) if fc else None,
                    "first_show_p90": quant(fs, .90) if fs else None}
        except Exception:
            ours = None

    lines = ["# 赛道基准快照（自动生成，勿手改）", "",
             f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
             f"- 样本池：**{len(accounts)} 个账号 / {len(articles)} 篇文章**（公开可见口径）", ""]
    lines += ["## 一、按粉丝档（全部样本）", "",
              "| 粉丝档 | 账号数 | 文章数 | 阅读P25 | 阅读中位 | 阅读P75 | P90 | 展现中位 | CTR中位 | ≥100占比 | ≥1000占比 |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    on_articles = [x for x in articles if x.get("niche_art") == "on"]
    for t in ("<1万", "1-10万", "≥10万", "未知"):
        rows = [x for x in on_articles if x["tier"] == t]
        s = stats(rows)
        if not s:
            continue
        lines.append(f"| {t} | {len(set(r['account'] for r in rows))} | {s['n']} | {s['read_p25']} | {s['read_p50']} | "
                     f"{s['read_p75']} | {s['read_p90']} | {s['show_p50']} | {s['ctr_p50']} | {s['ge100']}% | {s['ge1000']}% |")
    lines += ["", "## 二、按「文章年龄」（同一时间窗口才可比）", "",
              "| 年龄桶 | 文章数 | 展现中位 | 阅读中位 | P75 | CTR中位 |",
              "|---|---:|---:|---:|---:|---:|"]
    for b in ("<24h", "1-3d", "3-7d", "7-30d", ">30d", "未知"):
        rows = [x for x in on_articles if x["age_bucket"] == b]
        s = stats(rows)
        if not s:
            continue
        lines.append(f"| {b} | {s['n']} | {s['show_p50']} | {s['read_p50']} | {s['read_p75']} | {s['ctr_p50']} |")
    if ours:
        lines += ["", "## 三、我方（第 0 号样本「我的账号」）与外部对照", "",
                  f"- 我方首日曝光中位 **{ours['first_show_p50']}**｜首日阅读中位 {ours['first_read_p50']}"
                  f"｜首日CTR中位 {ours['first_ctr_p50']}%｜首日曝光P90 {ours['first_show_p90']}（n={ours['n']}）",
                  "- **对照口径**：我方是「首日（≈24h）」数据，只能与上表 **<24h 桶** 比；其它桶是累计值，不可直接比。"]
        rows = [x for x in on_articles if x["age_bucket"] == "<24h" and x.get("show") is not None]
        if len(rows) >= 8:
            shows = sorted(x["show"] for x in rows)
            below = sum(1 for v in shows if v < (ours["first_show_p50"] or 0))
            lines.append(f"- <24h 桶 n={len(shows)}：我方首日曝光中位 {ours['first_show_p50']} 落在第 "
                         f"**{round(below / len(shows) * 100)} 分位**（同桶中位 {int(statistics.median(shows))}）")
        else:
            lines.append(f"- <24h 桶只有 n={len(rows)} 篇 → **不给分位结论**（诚实纪律：样本 <8 不给分位）。"
                         f"同桶中位 {int(statistics.median([x['show'] for x in rows])) if rows else '—'}（参考值，不作结论）")
    off = [a for a in accounts if a.get("niche") in ("off", "mixed")]
    unk = [a for a in accounts if a.get("niche") == "unknown"]
    lines += ["", "## 三·五、赛道过滤（2026-09-13 用户要求：只收同赛道）", "",
              f"- 全部 {len(accounts)} 个账号中：**同赛道 on {len([a for a in accounts if a.get('niche')=='on'])} 个**"
              f"｜偏出 mixed {len([a for a in accounts if a.get('niche')=='mixed'])} 个"
              f"｜非赛道 off {len([a for a in accounts if a.get('niche')=='off'])} 个"
              f"｜无法判定 {len(unk)} 个",
              f"- ⚠️ **分位只统计「文章级同赛道」的 {len(on_articles)} 篇**（占全部 {len(articles)} 篇）——"
              "判定用**标题**（混发账号的跨赛道文章不再混进来）；"
              "mixed/off/unknown 一律**排除在分位外**（数据保留作对照，不进结论）。"]
    if off or unk:
        lines.append("- 被排除的账号：")
        for a in off + unk:
            lines.append(f"  - {a['name']}（{a.get('niche')}｜题材命中 {a.get('niche_pos_hits')}/{a.get('niche_n')}）")
    lines += ["", "## 四、数据质量与限制（照诚实纪律）",
              "- 分位数仅在样本 ≥8 时给；全量样本 <20 篇不给精确排名",
              "- 外部为公开可见数据（作者主页卡片的展现/阅读），**不等价**于后台数据",
              "- 缺失一律 null，**不反推**（不得用点赞反推阅读、用评论反推 CTR）",
              "- 主页不显示数据的账号（多为微头条为主）只记题材，不参与分位计算",
              "- 赛道判定只看「主页可见作品标题」，非深入阅读；账号混发时按占比判 on/mixed/off"]

    md = "\n".join(lines) + "\n"
    with open(f"{OUT}/基准快照.md", "w", encoding="utf-8") as f:
        f.write(md)
    if args.clean_panel:
        dropped = panel_cleanup(accounts)
        if dropped:
            print(f"[跟踪组自动清理] 移出 {len(dropped)} 个跨赛道号：{dropped}")
        else:
            print("[跟踪组自动清理] 无需移出")
    print(f"OK accounts={len(accounts)} articles={len(articles)} → {OUT}/accounts.jsonl, articles.jsonl, 基准快照.md")
    print()
    print(md)


if __name__ == "__main__":
    main()
