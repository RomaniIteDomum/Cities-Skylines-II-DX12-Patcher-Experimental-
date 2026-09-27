"""Unit tests plus optional integration tests against privately supplied originals.

Set CS2_TEST_ORIGINALS to a folder containing the two original asset files and
their manifest.json. Generated private fixtures use a temporary directory; no
game files or shader data are shipped with these tests.
"""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import asset_patcher as ap

FIXTURE_ROOT = Path(os.environ.get('CS2_TEST_OUTPUT', str(Path(__file__).resolve().parents[2] / 'cs2-dx12-public-test-results')))
FIXTURE_ROOT.mkdir(parents=True, exist_ok=True)

def variant(renderer, value='code'):
    return {'targetRenderer': renderer, 'targetLevel': 0, 'kernels': [{'example': value}], 'constantBuffers': [], 'resourcesResolved': True}


def tree(*renderers):
    return {'m_Name': 'Synthetic', 'variants': [variant(r) for r in renderers]}


class SemanticRules(unittest.TestCase):
    def test_alias_is_deep_copy_and_retains_original_prefix(self):
        original = tree(2, 4, 2)
        before = copy.deepcopy(original)
        result = ap._expected_tree(original)
        self.assertEqual(original, before)
        self.assertEqual(result['variants'][:3], original['variants'])
        self.assertEqual([v['targetRenderer'] for v in result['variants']], [2, 4, 2, 18, 18])
        result['variants'][3]['kernels'][0]['example'] = 'changed'
        self.assertEqual(original, before)

    def test_existing_dx12_and_dx12_only_are_valid(self):
        self.assertEqual(tuple(map(len, ap._analyze_tree(tree(18), 1))), (0, 1))
        self.assertEqual(tuple(map(len, ap._analyze_tree(tree(2, 18), 1))), (1, 1))

    def test_malformed_variant_cases_are_rejected(self):
        malformed = [None, {}, {'m_Name': 'x'}, {'m_Name': 'x', 'variants': []}, tree(4)]
        for value in ('2', True, None):
            item = tree(2)
            item['variants'][0]['targetRenderer'] = value
            malformed.append(item)
        for field, value in [('targetLevel', '0'), ('kernels', []), ('kernels', [123]), ('constantBuffers', None), ('resourcesResolved', 1)]:
            item = tree(2)
            item['variants'][0][field] = value
            malformed.append(item)
        for item in malformed:
            with self.subTest(item=item), self.assertRaises(ap.PatchError):
                ap._analyze_tree(item, 1)

    def test_bundle_or_container_rejected(self):
        fake = mock.Mock(files={'container': object()})
        with mock.patch.object(ap.UnityPy, 'load', return_value=fake), self.assertRaisesRegex(ap.PatchError, 'standalone'):
            ap._load(b'not a serialized file', 'test')

    def test_truncated_or_non_unity_input_rejected(self):
        for raw in (b'', b'not a Unity asset', bytes(64)):
            with self.subTest(raw=raw), self.assertRaises(ap.PatchError):
                ap._load(raw, 'malformed file')

    def test_input_errors_use_patch_error(self):
        with tempfile.TemporaryDirectory(dir=FIXTURE_ROOT) as folder:
            source = Path(folder) / 'missing.assets'
            with self.assertRaises(ap.PatchError):
                ap.inspect_asset(source)
            with self.assertRaisesRegex(ap.PatchError, 'in place'):
                ap.patch_asset(source, source)
            target = Path(folder) / 'already-present.assets'
            target.write_bytes(b'keep')
            with self.assertRaisesRegex(ap.PatchError, 'already exists'):
                ap.patch_asset(source, target)
            self.assertEqual(target.read_bytes(), b'keep')


ORIGINALS = os.environ.get('CS2_TEST_ORIGINALS')


@unittest.skipUnless(ORIGINALS, 'Private original fixtures were not provided')
class RealAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.originals = Path(ORIGINALS)
        cls.manifest = json.loads((cls.originals / 'manifest.json').read_text(encoding='utf-8-sig'))
        cls.temp = tempfile.TemporaryDirectory(prefix='cs2-semantic-patch-tests-', dir=FIXTURE_ROOT)
        cls.root = Path(cls.temp.name)
        cls.original = (cls.originals / 'globalgamemanagers.assets').read_bytes()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def fixture(self, name, edit):
        _env, asset, objects = ap._load(self.original, 'private test source')
        edit(asset, objects)
        path = self.root / name
        path.write_bytes(asset.save())
        return path

    def test_known_originals_reproduce_expected_patched_hashes(self):
        for item in self.manifest['files']:
            with self.subTest(asset=item['name']):
                source = self.originals / item['name']
                target = self.root / (item['name'] + '.patched')
                events = []
                result = ap.patch_asset(source, target, events.append)
                self.assertTrue(result['outputWritten'])
                self.assertEqual(result['beforeSha256'], item['originalSha256'])
                self.assertEqual(result['afterSha256'], item['patchedSha256'])
                self.assertEqual(target.stat().st_size, item['patchedBytes'])
                self.assertEqual(result['changedShaderCount'], 106 if item['name'].startswith('global') else 149)
                self.assertEqual(result['outputDx12CoveredShaderCount'], result['computeShaderCount'])
                self.assertTrue(any('Verifying' in event for event in events))
                inspected = ap.inspect_asset(target)
                self.assertEqual(inspected['status'], 'already_supported')
                no_rewrite = self.root / (item['name'] + '.unnecessary-output')
                again = ap.patch_asset(target, no_rewrite)
                self.assertFalse(again['outputWritten'])
                self.assertEqual(again['changedShaderCount'], 0)
                self.assertFalse(no_rewrite.exists())
                self.assertEqual(ap._sha(source.read_bytes()), item['originalSha256'])

    def test_partial_existing_dx12_is_preserved_exactly(self):
        changed_existing = {}
        def edit(asset, objects):
            obj = next(o for o in objects.values() if o.type.name == 'ComputeShader')
            original = obj.read_typetree()
            # Deliberately distinct existing DX12 metadata must NOT be replaced
            # by an alias, even when it does not match the DX11 variant.
            replacement = ap._expected_tree(original)
            replacement['variants'][-1]['targetLevel'] = 123
            obj.save_typetree(replacement)
            changed_existing['id'] = obj.path_id
        source = self.fixture('partial.assets', edit)
        source_bytes = source.read_bytes()
        _env, _asset, old_objects = ap._load(source_bytes, 'partial')
        preserved_id = changed_existing['id']
        original_raw = old_objects[preserved_id].get_raw_data()
        target = self.root / 'partial.patched'
        result = ap.patch_asset(source, target)
        self.assertEqual(result['existingDx12Count'], 1)
        self.assertEqual(result['changedShaderCount'], 105)
        _env, _asset, new_objects = ap._load(target.read_bytes(), 'partial output')
        self.assertEqual(new_objects[preserved_id].get_raw_data(), original_raw)

    def test_unsupported_version_no_compute_and_uncovered_shader_rejected(self):
        cases = []
        def older(asset, objects):
            asset.unity_version = '2021.3.1f1'
        cases.append(('older.assets', older, 'unsupported'))
        def no_compute(asset, objects):
            asset.objects = {key: value for key, value in objects.items() if value.type.name != 'ComputeShader'}
        cases.append(('no-compute.assets', no_compute, 'no ComputeShader'))
        def uncovered(asset, objects):
            obj = next(o for o in objects.values() if o.type.name == 'ComputeShader')
            value = obj.read_typetree()
            for entry in value['variants']:
                entry['targetRenderer'] = 4
            obj.save_typetree(value)
        cases.append(('uncovered.assets', uncovered, 'neither DX11 nor DX12'))
        for name, edit, error in cases:
            with self.subTest(case=name):
                source = self.fixture(name, edit)
                target = self.root / (name + '.out')
                with self.assertRaisesRegex(ap.PatchError, error):
                    ap.patch_asset(source, target)
                self.assertFalse(target.exists())

    def test_verification_detects_unmodified_object_corruption(self):
        _env, asset, objects = ap._load(self.original, 'original')
        _info, trees = ap._inspect_loaded(asset, objects)
        obj = next(o for o in objects.values() if o.type.name != 'ComputeShader' and o.byte_size > 0)
        corrupted = bytearray(self.original)
        corrupted[obj.byte_start] ^= 1
        with self.assertRaisesRegex(ap.PatchError, 'unmodified object'):
            ap._verify_output(self.original, bytes(corrupted), asset, objects, trees, set())

    def test_verification_detects_changed_original_variant(self):
        _env, asset, objects = ap._load(self.original, 'original')
        _info, trees = ap._inspect_loaded(asset, objects)
        obj = next(o for o in objects.values() if o.type.name == 'ComputeShader')
        bad = ap._expected_tree(trees[obj.path_id])
        bad['variants'][0]['targetLevel'] += 1
        obj.save_typetree(bad)
        with self.assertRaisesRegex(ap.PatchError, 'exact appended DX12 aliases'):
            ap._verify_output(self.original, asset.save(), asset, objects, trees, {obj.path_id})

    def test_changed_source_detected_before_output_is_written(self):
        source = self.root / 'source-change.assets'
        source.write_bytes(self.original)
        target = self.root / 'source-change.out'
        def change_source(message):
            if message.startswith('Verifying'):
                with source.open('r+b') as stream:
                    stream.seek(100)
                    old = stream.read(1)
                    stream.seek(100)
                    stream.write(bytes((old[0] ^ 1,)))
        with self.assertRaisesRegex(ap.PatchError, 'Source asset changed'):
            ap.patch_asset(source, target, change_source)
        self.assertFalse(target.exists())

    def test_write_failure_does_not_replace_source(self):
        source = self.originals / 'globalgamemanagers.assets'
        before = ap._sha(source.read_bytes())
        obstructed = self.root / 'not-a-directory'
        obstructed.write_bytes(b'keep this unrelated file')
        with self.assertRaisesRegex(ap.PatchError, 'Cannot write verified output'):
            ap.patch_asset(source, obstructed / 'output.assets')
        self.assertEqual(ap._sha(source.read_bytes()), before)
        self.assertEqual(obstructed.read_bytes(), b'keep this unrelated file')


if __name__ == '__main__':
    unittest.main(verbosity=2)
