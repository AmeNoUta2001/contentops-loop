# config/

## 这个目录里有什么

| 文件 | 是否入库 | 说明 |
|---|---|---|
| `vertical.json` | ✅ **入库，且是你最该改的文件** | 垂类词典 + 阈值。换赛道只改它，脚本不动 |
| `secrets.vault.json` | ❌ 默认被 gitignore | 加密密文库（AES-256-GCM）。主密钥在仓库外 `~/.cheat-secrets/master.key` |
| `tt_mp_cookies.txt` | ❌ 永不入库 | 平台登录态明文。正常也不该出现在这里（应放 `~/.cheat-secrets/`） |
| `*.env` / `.env` | ❌ 永不入库 | API key 等 |

## vertical.json

字段说明、改法、自测命令见 **README 第五节** 和 **`docs/04-换赛道-移植清单.md`**。要点：

- `families` / `motifs` 的顺序 = 优先级，从上往下第一个命中就赢 → **具体的放前面，宽泛的放后面**
- 命中 `未归类` 不是 bug，是提示该加词
- `thresholds` 里的数字是原赛道标定值，**换垂类必须重标**，不要照抄

## 建议的环境变量

```bash
# 工作区根目录（默认 ~/content-ops-loop）
export CONTENT_OPS_ROOT=~/content-ops-loop

# 你的头条号 user_id（从创作后台 URL 里取；不要再硬编码进脚本）
export TT_USER_ID=

# 自家账号昵称（benchmark 里用来把自己从外部样本池里排掉）
export SELF_ACCOUNT_NAME=

# 手机控制（可选；phone_ctl.py 用）
export PHONE_IP=

# 垂类配置文件换位置（可选；默认 <CONTENT_OPS_ROOT>/config/vertical.json）
# export VERTICAL_CONFIG=~/my-vertical.json

# 第三方 API key（可选；加密保险箱或环境变量二选一）
# export DASHSCOPE_API_KEY=

# 保险箱位置（可选）
# export CHEAT_MASTER_KEY_FILE=~/.cheat-secrets/master.key
# export CHEAT_VAULT_FILE=<CONTENT_OPS_ROOT>/config/secrets.vault.json
```

> `CHEAT_*` 这两个变量名是历史遗留命名，保持兼容不改 —— 改了会让已加密的库打不开。

## 初始化保险箱

```bash
python3 scripts/secretctl.py init
python3 scripts/secretctl.py set tt_mp_cookies --file cookie.txt
python3 scripts/secretctl.py verify
python3 scripts/secretctl.py export-env        # 打印可 source 的环境变量（小心终端 history）
```
