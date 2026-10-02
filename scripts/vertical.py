#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""vertical —— 垂类配置加载器。

**换赛道只需要改 `config/vertical.json`，不用改任何脚本。**

这个文件是整套工具里唯一「装着你这个号在写什么」的地方：题材族、母题、跨垂类否决词、
赛道内外判据、以及各项阈值。分析机器（取数/首日指标/分位/同题库）全都是垂类无关的。

为什么把它外置成配置而不是留在代码里：
  · 换个赛道重写 4 个脚本 = 一定会改漏；改 1 个 JSON = 不会漏
  · 词典要能被人一句话改掉（人工复核后回填），代码里改不动
  · 词典是你自己的资产，不该锁死在别人仓库的源码里

配好后自测：
    python3 scripts/topic_taxonomy.py "你这边的真实标题1" "真实标题2"
未命中的会显示 `未归类` —— 那不是 bug，是提示你该往词典里加词了。
"""
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT_OPS_ROOT = os.path.expanduser(
    os.environ.get('CONTENT_OPS_ROOT', '~/content-ops-loop'))

CANDIDATES = [
    os.environ.get('VERTICAL_CONFIG') or '',
    os.path.join(CONTENT_OPS_ROOT, 'config/vertical.json'),
    os.path.join(_HERE, '..', 'config/vertical.json'),
]

_CACHE = None

DEFAULTS = {
    'vertical': '未命名',
    'families': [],
    'motifs': [],
    'motif_must': {},
    'off_vertical': [],
    'manual_overrides': [],
    'niche_hint': [],
    'offlike': [],
    'niche_pos': [],
    'niche_neg': [],
    'thresholds': {},
}

THRESHOLD_DEFAULTS = {
    'own_pass_ctr': 4.0,        # 自家过线：首日 CTR ≥ 这个值算「过线」
    'own_strong_ctr': 6.0,      # 「曝光低但点击率强」的判定线（高于此值 → 该重发而不是重写）
    'big_pool_show': 900,       # 首日曝光 ≥ 此值 = 大池子（押第二篇）
    'small_pool_show': 300,     # 首日曝光 < 此值 = 平台没给量
    'viral_show': 5000,         # 爆款级单篇：不进题材稳定池中位
    'min_n_quantile': 8,        # 少于此样本数不给分位结论
    'strong_kw_hits': 2,        # 关键词命中数 ≥ 此值 = high 置信
}


def config_path():
    for p in CANDIDATES:
        if p and os.path.exists(p):
            return os.path.abspath(p)
    return None


def load():
    """读垂类配置（只读一次）。找不到配置文件 → 用空配置并在 stderr 提示。"""
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    cfg = dict(DEFAULTS)
    p = config_path()
    if p:
        with open(p, encoding='utf-8') as f:
            raw = json.load(f)
        cfg.update(raw)
        cfg['_path'] = p
    else:
        import sys
        print(f"[vertical] 没找到垂类配置（找过 {CANDIDATES}）→ 分类器会全部返回「未归类」。\n"
              f"           照 config/vertical.json 写一份你自己的即可。", file=sys.stderr)
        cfg['_path'] = None
    th = dict(THRESHOLD_DEFAULTS)
    th.update(cfg.get('thresholds') or {})
    cfg['thresholds'] = th
    _CACHE = cfg
    return cfg


# ---- 便捷读取口（脚本里用这些，不要去猜 key 名）----
def families():
    return [(f['name'], list(f.get('keywords') or [])) for f in load().get('families') or []]


def motifs():
    return [(m['name'], list(m.get('keywords') or [])) for m in load().get('motifs') or []]


def motif_must():
    return dict(load().get('motif_must') or {})


def off_vertical():
    return list(load().get('off_vertical') or [])


def manual_overrides():
    out = []
    for o in load().get('manual_overrides') or []:
        out.append((o.get('title_contains', ''), o.get('motif', ''),
                    o.get('family', ''), o.get('why', '')))
    return out


def niche_hint():
    return list(load().get('niche_hint') or [])


def offlike():
    return list(load().get('offlike') or [])


def niche_pos():
    return tuple(load().get('niche_pos') or [])


def niche_neg():
    return tuple(load().get('niche_neg') or [])


def threshold(name):
    return load()['thresholds'].get(name, THRESHOLD_DEFAULTS.get(name))


def name():
    return load().get('vertical') or '未命名'


if __name__ == '__main__':
    c = load()
    print(f"配置文件 : {c['_path']}")
    print(f"垂类     : {c['vertical']}")
    print(f"题材族   : {len(c['families'])} 个 — {[f['name'] for f in c['families']]}")
    print(f"母题     : {len(c['motifs'])} 个")
    print(f"跨垂类词 : {len(c['off_vertical'])} 个")
    print(f"赛道内词 : {len(c['niche_pos'])} 个 ｜ 赛道外词: {len(c['niche_neg'])} 个")
    print(f"阈值     : {json.dumps(c['thresholds'], ensure_ascii=False)}")
