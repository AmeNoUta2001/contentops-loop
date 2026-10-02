# examples/ —— 合成数据（宠物垂类）

⚠️ **这里的数据是程序生成的合成数据，与任何真实账号无关。**

- 垂类：**宠物**（对应的词典在 `config/vertical.json`，也是示例）
- 目录结构刻意做成与真实运行目录一致（`examples/reports/tt_snapshots/`），
  所以可以直接拿它当 `CONTENT_OPS_ROOT` 跑通整条演示链路
- `item_id` 一律 `9` 开头的合成号段，一眼可与真实 ID 区分
- 9 天 / 37 篇，题材分布刻意做成「大池子题材曝光高、小池子题材曝光低但点击率不差」，
  用来演示诊断口径想区分的东西

跑一遍看看：

```bash
CONTENT_OPS_ROOT=examples python3 scripts/first_day_metrics.py
```

接上真实账号后，把 `CONTENT_OPS_ROOT` 指回你的工作区即可，脚本不用改。

> 生成脚本没有随仓库提供（它本身就是一次性的）。想要更多样本就多跑几天真实数据，
> 或者照 `docs/03-数据字典.md` 的 schema 自己造。
