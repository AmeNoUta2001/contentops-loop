#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""schema 契约测试：用自带的最小 JSON Schema 子集校验器，校验真实产出。

零第三方依赖（项目铁律：requirements.txt 不装 jsonschema，本机也没有 pytest）——
因此这里自己实现一个只认这几个关键字的校验器：
    type / properties / required / items / enum / additionalProperties
type 支持字符串或字符串数组（数组用于表达 ["object","null"] 这类可空字段）。
校验器返回「错误信息列表」，空列表 = 合格。

测试内容：
  1. examples/reports/tt_snapshots/*.json 的每一份真实快照都符合 snapshot.schema.json；
  2. 现场跑 scripts/first_day_metrics.py --json <临时文件>（CONTENT_OPS_ROOT=examples）得到
     的真实 JSON 符合 first_day_metrics.schema.json；
  3. 故意构造的坏数据（缺必填字段 / 类型错误 / 枚举越界）必须被判不合格 ——
     证明校验器本身有效，而不是永远返回 True。

运行（包根目录）：
    python3 -m unittest discover -s tests -v
"""
import glob
import json
import os
import subprocess
import sys
import tempfile
import unittest

# ---- 路径处理（tests/ 之外还要找到 scripts/ 与 schemas/，discover 时 tests/ 会被加进 sys.path）----
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, os.path.join(ROOT, 'scripts')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

SCHEMA_DIR = os.path.join(ROOT, 'schemas')
EXAMPLES = os.path.join(ROOT, 'examples')
SNAP_DIR = os.path.join(EXAMPLES, 'reports', 'tt_snapshots')
FIRSTDAY_SCRIPT = os.path.join(ROOT, 'scripts', 'first_day_metrics.py')

JSON_TYPES = ('object', 'array', 'string', 'number', 'integer', 'boolean', 'null')


# ══════════════════════════════ 最小 JSON Schema 子集校验器 ══════════════════════════════
def _type_ok(value, type_name):
    """单个 JSON 类型判定。注意：bool 是 int 的子类，必须显式排除。"""
    if type_name == 'object':
        return isinstance(value, dict)
    if type_name == 'array':
        return isinstance(value, list)
    if type_name == 'string':
        return isinstance(value, str)
    if type_name == 'boolean':
        return isinstance(value, bool)
    if type_name == 'null':
        return value is None
    if type_name == 'integer':
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == 'number':
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    raise ValueError('校验器不支持的类型名: %r' % (type_name,))


def _enum_eq(a, b):
    """enum 比较：区分 bool 与 0/1，其余按 == （JSON 里 1 与 1.0 视为相等）。"""
    if isinstance(a, bool) != isinstance(b, bool):
        return False
    return a == b


def validate(instance, schema, path='$'):
    """返回错误字符串列表（[] = 通过）。只支持约定的关键字子集。"""
    errors = []
    if not isinstance(schema, dict):
        return errors

    # enum（先于 type 判断，保证枚举越界能被单独报出）
    if 'enum' in schema and isinstance(schema['enum'], list):
        if not any(_enum_eq(instance, e) for e in schema['enum']):
            errors.append('%s: 值 %r 不在 enum %r 中' % (path, instance, schema['enum']))

    # type：类型不符时后续关键字不再有意义，直接返回
    if 'type' in schema:
        t = schema['type']
        allowed = t if isinstance(t, list) else [t]
        if not any(_type_ok(instance, name) for name in allowed):
            errors.append('%s: 期望类型 %s，实际 %s（值=%r）'
                          % (path, allowed if isinstance(t, list) else t,
                             type(instance).__name__, instance))
            return errors

    if isinstance(instance, dict):
        # required
        for key in schema.get('required') or []:
            if key not in instance:
                errors.append('%s: 缺少必填字段 %r' % (path, key))
        # properties
        props = schema.get('properties')
        if isinstance(props, dict):
            for key, sub in props.items():
                if key in instance:
                    errors.extend(validate(instance[key], sub, '%s.%s' % (path, key)))
            # additionalProperties=false → 出现未声明的键即报错
            if schema.get('additionalProperties') is False:
                for key in instance:
                    if key not in props:
                        errors.append('%s: 出现未声明字段 %r（additionalProperties=false）'
                                      % (path, key))

    if isinstance(instance, list) and 'items' in schema and isinstance(schema['items'], dict):
        for i, item in enumerate(instance):
            errors.extend(validate(item, schema['items'], '%s[%d]' % (path, i)))

    return errors


def is_valid(instance, schema):
    return not validate(instance, schema)


# ══════════════════════════════ 测试 ══════════════════════════════
def _load_schema(name):
    with open(os.path.join(SCHEMA_DIR, name), encoding='utf-8') as f:
        return json.load(f)


def _snapshot_files():
    return sorted(glob.glob(os.path.join(SNAP_DIR, '*.json')))


class ValidatorSelfTest(unittest.TestCase):
    """先证明校验器不是永远返回 True。"""

    def test_validator_rejects_missing_required(self):
        schema = {'type': 'object', 'properties': {'a': {'type': 'integer'}}, 'required': ['a', 'b']}
        errs = validate({'a': 1}, schema)
        self.assertTrue(errs, '缺必填字段必须被报错')
        self.assertTrue(any('b' in e for e in errs))

    def test_validator_rejects_wrong_type(self):
        schema = {'type': 'object', 'properties': {'a': {'type': 'integer'}}}
        self.assertTrue(validate({'a': 'not-an-int'}, schema))
        self.assertFalse(validate({'a': 3}, schema))

    def test_validator_rejects_bool_as_integer(self):
        schema = {'type': 'integer'}
        self.assertTrue(validate(True, schema), 'bool 不能冒充 integer')
        self.assertFalse(validate(5, schema))

    def test_validator_nullable_type_list(self):
        schema = {'type': ['object', 'null']}
        self.assertTrue(is_valid(None, schema))
        self.assertTrue(is_valid({}, schema))
        self.assertTrue(validate([], schema))

    def test_validator_enum_and_additional_properties(self):
        schema = {'type': 'object', 'properties': {'r': {'type': 'string', 'enum': ['', 'A']}},
                  'additionalProperties': False}
        self.assertTrue(is_valid({'r': 'A'}, schema))
        self.assertTrue(validate({'r': 'Z'}, schema))
        self.assertTrue(validate({'r': 'A', 'x': 1}, schema))

    def test_validator_items(self):
        schema = {'type': 'array', 'items': {'type': 'integer'}}
        self.assertFalse(validate([1, 2, 3], schema, '$'))
        self.assertTrue(validate([1, 'x'], schema, '$'))


class SnapshotSchemaTest(unittest.TestCase):
    """9 份真实快照必须全部符合 snapshot.schema.json。"""

    def setUp(self):
        self.schema = _load_schema('snapshot.schema.json')
        self.files = _snapshot_files()

    def test_examples_exist(self):
        self.assertEqual(len(self.files), 9,
                         '期望 examples/reports/tt_snapshots 下有 9 份真实快照，实际 %d 份' % len(self.files))

    def test_every_snapshot_validates(self):
        failures = {}
        for path in self.files:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
            errs = validate(data, self.schema)
            if errs:
                failures[os.path.basename(path)] = errs[:8]
        self.assertFalse(failures, '以下快照未通过 schema 校验:\n%s'
                         % json.dumps(failures, ensure_ascii=False, indent=2))


class FirstDayMetricsSchemaTest(unittest.TestCase):
    """现场运行 first_day_metrics.py 的真实输出必须符合 schema。"""

    @classmethod
    def setUpClass(cls):
        cls.schema = _load_schema('first_day_metrics.schema.json')
        cls._tmpdir = tempfile.TemporaryDirectory(prefix='fdm_schema_')
        cls.out_path = os.path.join(cls._tmpdir.name, 'first_day.json')
        env = dict(os.environ, CONTENT_OPS_ROOT=EXAMPLES)
        proc = subprocess.run(
            [sys.executable, FIRSTDAY_SCRIPT, '--json', cls.out_path],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
        cls.proc = proc
        if proc.returncode != 0:
            # 脚本在样本不足时用专用退出码；这里必须拿到可校验的 JSON
            raise AssertionError(
                'first_day_metrics.py 非零退出 rc=%s\nSTDOUT:\n%s\nSTDERR:\n%s'
                % (proc.returncode, proc.stdout, proc.stderr))
        with open(cls.out_path, encoding='utf-8') as f:
            cls.data = json.load(f)

    @classmethod
    def tearDownClass(cls):
        cls._tmpdir.cleanup()

    def test_script_ran_on_examples(self):
        self.assertEqual(self.data['date'], '2026-01-13')
        self.assertGreater(len(self.data['rows']), 0, '真实样本应产出至少一行首日指标')

    def test_output_validates(self):
        errs = validate(self.data, self.schema)
        self.assertFalse(errs, 'first_day_metrics 真实输出未通过 schema:\n%s'
                         % '\n'.join(errs[:20]))


class BadDataRejectionTest(unittest.TestCase):
    """坏数据必须被判不合格（对真实 schema，不是玩具 schema）。"""

    def setUp(self):
        self.snap_schema = _load_schema('snapshot.schema.json')
        self.fd_schema = _load_schema('first_day_metrics.schema.json')
        with open(_snapshot_files()[-1], encoding='utf-8') as f:
            self.good_snap = json.load(f)

    def _first_day_good(self):
        # 直接用真实脚本产出，作为「好数据」基线
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, 'd.json')
            subprocess.run([sys.executable, FIRSTDAY_SCRIPT, '--json', p],
                           cwd=ROOT, env=dict(os.environ, CONTENT_OPS_ROOT=EXAMPLES),
                           capture_output=True, text=True, timeout=120)
            with open(p, encoding='utf-8') as f:
                return json.load(f)

    # ---- snapshot 坏数据 ----
    def test_snapshot_missing_required_field(self):
        import copy
        bad = copy.deepcopy(self.good_snap)
        del bad['articles'][0]['title']
        errs = validate(bad, self.snap_schema)
        self.assertTrue(errs, '缺 article.title 应报错')
        self.assertTrue(any('title' in e for e in errs))

    def test_snapshot_wrong_type(self):
        import copy
        bad = copy.deepcopy(self.good_snap)
        bad['articles'][0]['read'] = 'many'      # integer → string
        self.assertTrue(validate(bad, self.snap_schema))

    def test_snapshot_nested_wrong_type(self):
        import copy
        bad = copy.deepcopy(self.good_snap)
        art = next(a for a in bad['articles'] if isinstance(a.get('traffic'), dict) and a['traffic'].get('daily'))
        art['traffic']['daily'][0]['impression'] = ['not', 'a', 'number']
        self.assertTrue(validate(bad, self.snap_schema))

    def test_snapshot_bad_top_level(self):
        import copy
        bad = copy.deepcopy(self.good_snap)
        del bad['articles']
        bad['extra'] = 1
        self.assertTrue(validate(bad, self.snap_schema))

    # ---- first_day_metrics 坏数据 ----
    def test_first_day_missing_required(self):
        import copy
        good = self._first_day_good()
        bad = copy.deepcopy(good)
        del bad['summary']['n']
        errs = validate(bad, self.fd_schema)
        self.assertTrue(any('n' in e for e in errs))

    def test_first_day_wrong_type(self):
        import copy
        bad = copy.deepcopy(self._first_day_good())
        bad['rows'][0]['first_show'] = 'abc'     # [integer,null] → string
        self.assertTrue(validate(bad, self.fd_schema))

    def test_first_day_bad_enum(self):
        import copy
        bad = copy.deepcopy(self._first_day_good())
        bad['pool'][0]['risk'] = '火星词'          # 不在 enum 内
        self.assertTrue(validate(bad, self.fd_schema))

    def test_good_data_still_passes(self):
        """对照组：同一份好数据必须是合格的，否则上面的断言没有意义。"""
        self.assertFalse(validate(self.good_snap, self.snap_schema))
        self.assertFalse(validate(self._first_day_good(), self.fd_schema))


if __name__ == '__main__':
    unittest.main(verbosity=2)
