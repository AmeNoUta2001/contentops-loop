# -*- coding: utf-8 -*-
"""仓库卫生：确保「仓库里该有的文件」不会被 .gitignore 静默排除。

为什么要有这个测试
------------------
曾经 `.gitignore` 里两条过宽的规则造成了真实事故：

  · `reports/`（缺前导斜杠）→ 匹配任意层级 → 把自带合成数据集
    `examples/reports/tt_snapshots/*.json` 9 个文件全忽略掉了；
  · `*secret*` → 匹配任意路径含该词的文件 → 把 `scripts/secretctl.py`、
    `scripts/secrets_env.py`、`tests/test_secretctl.py` 三个**源码/测试**文件忽略掉了。

后果很难看：本地 120 个测试全绿，push 之后 CI 三个 Python 版本全红，
而且 README 里那条「零凭据 demo」命令对新克隆的人根本不成立 —— 数据集没进仓库。

这类错误不会报错、不会有提示，只会安静地少几个文件。
所以用一个测试把它顶住：**只要有任何本该入库的文件被 ignore 规则吃掉，CI 立刻失败。**

本地不在 git 仓库里（或没装 git）时跳过，不影响离线跑测试。
"""
import os
import shutil
import subprocess
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

# 这些是「故意不入库」的东西，被忽略属于正常
ALLOWED_IGNORED_DIRS = ('reports', 'logs', '.git', '__pycache__', '.venv', 'venv')
ALLOWED_IGNORED_SUFFIX = (
    '.pyc', '.pyo', '.log', '.env', '.key', '.pem', '.p12', '.jks',
)
ALLOWED_IGNORED_NAMES = (
    '.env', 'secrets.vault.json', '.DS_Store',
)


def _git(*args):
    return subprocess.run(['git'] + list(args), cwd=REPO,
                          capture_output=True, text=True)


class IgnoreRulesDoNotSwallowRepoFiles(unittest.TestCase):

    def setUp(self):
        if not shutil.which('git'):
            self.skipTest('未安装 git')
        if _git('rev-parse', '--git-dir').returncode != 0:
            self.skipTest('不在 git 仓库内（离线跑测试时正常）')

    def test_no_required_file_is_gitignored(self):
        """遍历工作区，凡是不在「故意忽略」白名单里的文件，都不该被 ignore 规则命中。"""
        candidates = []
        for dirpath, dirnames, filenames in os.walk(REPO):
            dirnames[:] = [d for d in dirnames if d not in ALLOWED_IGNORED_DIRS]
            for f in filenames:
                if f.endswith(ALLOWED_IGNORED_SUFFIX) or f in ALLOWED_IGNORED_NAMES:
                    continue
                rel = os.path.relpath(os.path.join(dirpath, f), REPO)
                candidates.append(rel.replace(os.sep, '/'))

        self.assertTrue(candidates, '工作区里没扫到任何文件，测试本身可能写错了')

        # 一次问完：--stdin + -v 会回「文件:行:规则:路径」，只对命中的输出
        r = subprocess.run(['git', 'check-ignore', '-v', '--stdin'],
                           cwd=REPO, capture_output=True, text=True,
                           input='\n'.join(candidates))
        hit = [l for l in r.stdout.split('\n') if l.strip()]

        if hit:
            detail = '\n'.join('  ' + h for h in hit)
            self.fail(
                f"有 {len(hit)} 个本该入库的文件被 .gitignore 排除了 —— "
                f"clone 之后它们不存在：\n{detail}\n"
                f"修法：把过宽的规则改精确（例如 `reports/` → `/reports/`，"
                f"并避免 `*secret*` 这类任意位置通配）。"
            )

    def test_demo_dataset_is_not_ignored(self):
        """README 的零凭据 demo 依赖这批合成快照；它们必须能进仓库。"""
        snaps = os.path.join(REPO, 'examples', 'reports', 'tt_snapshots')
        self.assertTrue(os.path.isdir(snaps), 'examples/ 合成数据集目录不见了')
        names = sorted(f for f in os.listdir(snaps) if f.endswith('.json'))
        self.assertEqual(len(names), 9, f'合成快照数量变了：{names}')
        r = subprocess.run(['git', 'check-ignore', '--stdin'], cwd=REPO,
                           capture_output=True, text=True,
                           input='\n'.join(f'examples/reports/tt_snapshots/{n}' for n in names))
        self.assertEqual(r.stdout.strip(), '',
                         f'demo 数据集被 .gitignore 排除了：{r.stdout.strip()}')

    def test_credential_module_files_are_not_ignored(self):
        """凭据保险箱是源码，必须入库（它们不含任何真实凭据）。"""
        must_be_tracked = [
            'scripts/secretctl.py',
            'scripts/secrets_env.py',
            'scripts/tt_cookie.py',
            'tests/test_secretctl.py',
        ]
        r = subprocess.run(['git', 'check-ignore', '--stdin'], cwd=REPO,
                           capture_output=True, text=True,
                           input='\n'.join(must_be_tracked))
        self.assertEqual(r.stdout.strip(), '',
                         f'这些源码/测试被 ignore 规则吃掉了：{r.stdout.strip()}')


if __name__ == '__main__':
    unittest.main()
