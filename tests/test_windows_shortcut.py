"""Real COM integration tests isolated to a temporary workspace Desktop."""
import copy
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import windows_shortcut as ws


ROOT = Path(__file__).resolve().parents[2] / 'cs2-dx12-public-test-results'
ROOT.mkdir(parents=True, exist_ok=True)
ARGS = ['-force-d3d12', '-timestamps', '-screen-fullscreen', '1', '-window-mode', 'borderless']


@unittest.skipUnless(os.name == 'nt', 'Requires Windows WScript.Shell COM')
class ShortcutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='shortcut-test-', dir=ROOT)
        self.root = Path(self.temp.name)
        self.desktop = self.root / "Desktop O'Brien $() ü"
        self.desktop.mkdir()
        self.game = self.root / "Game O'Brien & $() 中文"
        self.game.mkdir()
        # Never executed. All public calls point to this explicit fake game and
        # explicit isolated Desktop, never the real user Desktop.
        (self.game / 'Cities2.exe').write_bytes(b'not an executable')

    def tearDown(self):
        self.temp.cleanup()

    def create(self):
        return ws.ensure_shortcut(self.game, ARGS, self.desktop)

    def test_default_desktop_resolved_read_only(self):
        desktop = ws._desktop_path(None)
        self.assertTrue(desktop.is_absolute())
        self.assertTrue(desktop.is_dir())
        self.assertNotEqual(desktop, self.desktop)

    def test_real_shortcut_roundtrip_unicode_literal_paths_and_quoted_arguments(self):
        args = ARGS + ['literal argument with spaces', '$()', "O'Brien"]
        result = ws.ensure_shortcut(self.game, args, self.desktop)
        self.assertEqual(result['status'], 'created')
        self.assertTrue(result['createdByPatcher'])
        link = Path(result['path'])
        self.assertEqual(link.name, ws.SHORTCUT_STEM + '.lnk')
        actual = ws._com({'action': 'read', 'path': str(link)})
        self.assertTrue(ws._same_path(actual['target'], self.game / 'Cities2.exe'))
        self.assertTrue(ws._same_path(actual['workingDirectory'], self.game))
        self.assertEqual(actual['arguments'], subprocess.list2cmdline(args))
        self.assertIn('Experimental', actual['description'])
        self.assertIn('Cities2.exe', actual['icon'])
        self.assertEqual(link.read_bytes()[:4], b'L\x00\x00\x00')
        self.assertEqual(sorted(p.name for p in self.desktop.iterdir()), [link.name])
        self.assertEqual((self.game / 'Cities2.exe').read_bytes(), b'not an executable')
        self.assertEqual(ws.remove_shortcut(result, self.game, args, self.desktop)['status'], 'removed')
        self.assertFalse(link.exists())

    def test_reuse_does_not_claim_ownership_or_duplicate(self):
        first = self.create()
        second = self.create()
        self.assertEqual(second['status'], 'existing')
        self.assertFalse(second['createdByPatcher'])
        self.assertEqual(first['path'], second['path'])
        self.assertEqual(first['sha256'], second['sha256'])
        self.assertEqual(len(list(self.desktop.iterdir())), 1)
        self.assertEqual(ws.remove_shortcut(second, self.game, ARGS, self.desktop)['status'], 'preserved')
        self.assertEqual(ws.remove_shortcut(first, self.game, ARGS, self.desktop)['status'], 'removed')
        self.assertEqual(ws.remove_shortcut(first, self.game, ARGS, self.desktop)['status'], 'missing')

    def test_unrelated_valid_shortcut_collision_preserved_and_stable_suffix_reused(self):
        other = self.root / 'Other Game'
        other.mkdir()
        (other / 'Cities2.exe').write_bytes(b'unrelated')
        foreign = ws.ensure_shortcut(other, ARGS, self.desktop)
        foreign_bytes = Path(foreign['path']).read_bytes()
        own = self.create()
        self.assertNotEqual(own['path'], foreign['path'])
        self.assertEqual(Path(foreign['path']).read_bytes(), foreign_bytes)
        # Even after base name becomes vacant, the prior matching suffixed
        # shortcut is found and reused instead of creating a duplicate.
        ws.remove_shortcut(foreign, other, ARGS, self.desktop)
        again = self.create()
        self.assertEqual(again['path'], own['path'])
        self.assertEqual(len(list(self.desktop.iterdir())), 1)

    def test_directory_and_invalid_file_collisions_are_not_overwritten(self):
        base = self.desktop / (ws.SHORTCUT_STEM + '.lnk')
        base.mkdir()
        suffix = hashlib.sha256(os.path.normcase(str(self.game.resolve())).encode('utf-8')).hexdigest()[:10]
        occupied = self.desktop / (ws.SHORTCUT_STEM + ' - ' + suffix + '.lnk')
        occupied.write_bytes(b'keep unrelated file')
        own = self.create()
        self.assertTrue(own['path'].endswith(' - 2.lnk'))
        self.assertTrue(base.is_dir())
        self.assertEqual(occupied.read_bytes(), b'keep unrelated file')
        self.assertEqual(ws.remove_shortcut(own, self.game, ARGS, self.desktop)['status'], 'removed')

    def test_modified_link_preserved(self):
        record = self.create()
        link = Path(record['path'])
        with link.open('ab') as stream:
            stream.write(b'user changed')
        changed = link.read_bytes()
        result = ws.remove_shortcut(record, self.game, ARGS, self.desktop)
        self.assertEqual(result['status'], 'preserved')
        self.assertIn('modified', result['reason'])
        self.assertEqual(link.read_bytes(), changed)

    def test_failure_after_rename_cleans_only_unchanged_created_shortcut(self):
        original_com = ws._com
        def failing_final_read(request):
            if request['action'] == 'read' and Path(request['path']).name == ws.SHORTCUT_STEM + '.lnk':
                raise ws.ShortcutError('Injected post-rename verification failure')
            return original_com(request)
        with mock.patch.object(ws, '_com', side_effect=failing_final_read):
            with self.assertRaisesRegex(ws.ShortcutError, 'Injected'):
                self.create()
        self.assertEqual(list(self.desktop.iterdir()), [])

    def test_helper_response_failure_cleans_verified_temporary_shortcut(self):
        original_com = ws._com
        def fail_after_create(request):
            result = original_com(request)
            if request['action'] == 'create':
                raise ws.ShortcutError('Injected helper response failure')
            return result
        with mock.patch.object(ws, '_com', side_effect=fail_after_create):
            with self.assertRaisesRegex(ws.ShortcutError, 'Injected'):
                self.create()
        self.assertEqual(list(self.desktop.iterdir()), [])

    def test_wrong_target_preserved_even_when_record_hash_matches(self):
        record = self.create()
        link = Path(record['path'])
        link.unlink()
        other = self.root / 'Different executable.exe'
        other.write_bytes(b'not executed')
        ws._com({'action': 'create', 'path': str(link), 'target': str(other), 'arguments': record['arguments'], 'workingDirectory': record['workingDirectory'], 'description': 'replacement'})
        record['sha256'] = ws._hash(link)
        result = ws.remove_shortcut(record, self.game, ARGS, self.desktop)
        self.assertEqual(result['status'], 'preserved')
        self.assertIn('target', result['reason'])
        self.assertTrue(link.exists())

    def test_other_desktop_path_and_name_and_configuration_preserved(self):
        record = self.create()
        another_desktop = self.root / 'Another Desktop'
        another_desktop.mkdir()
        self.assertEqual(ws.remove_shortcut(record, self.game, ARGS, another_desktop)['status'], 'preserved')
        self.assertEqual(ws.remove_shortcut(record, self.game, ARGS + ['-different'], self.desktop)['status'], 'preserved')
        unrelated = self.desktop / 'Unrelated shortcut.lnk'
        unrelated.write_bytes(Path(record['path']).read_bytes())
        fake_record = copy.deepcopy(record)
        fake_record['path'] = str(unrelated)
        self.assertEqual(ws.remove_shortcut(fake_record, self.game, ARGS, self.desktop)['status'], 'preserved')
        self.assertTrue(unrelated.exists())
        self.assertTrue(Path(record['path']).exists())

    def test_symlink_collision_is_preserved(self):
        original = self.root / 'keep-this-file'
        original.write_bytes(b'untouched')
        base = self.desktop / (ws.SHORTCUT_STEM + '.lnk')
        try:
            base.symlink_to(original)
        except OSError as exc:
            self.skipTest(f'Creating symbolic links is unavailable: {exc}')
        own = self.create()
        self.assertNotEqual(own['path'], str(base))
        self.assertTrue(base.is_symlink())
        self.assertEqual(original.read_bytes(), b'untouched')


if __name__ == '__main__':
    unittest.main(verbosity=2)
