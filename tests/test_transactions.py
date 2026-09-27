"""Transaction tests use tiny synthetic assets; real assets are never distributed."""
import json
import os
from pathlib import Path
import sys
import tempfile
import subprocess
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import patcher as p


def inspect_fake(path):
    return dict(unityVersion='2022.3.71f1', needsAliasCount=int(not path.read_bytes().endswith(b'|DX12')),
                computeShaderCount=1, sourceSha256=p.file_hash(path), existingDx12Count=int(path.read_bytes().endswith(b'|DX12')))


def patch_fake(source, target, progress):
    data = source.read_bytes()
    if data.endswith(b'|DX12'):
        return {'outputWritten': False, 'beforeSha256': p.byte_hash(data)}
    target.write_bytes(data + b'|DX12')
    return {'outputWritten': True, 'beforeSha256': p.byte_hash(data)}


@unittest.skipUnless(os.name == 'nt', 'Windows mutation mutex')
class Transactions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.game, self.user = self.root / 'game', self.root / 'profile'
        (self.game / 'Cities2_Data/Managed').mkdir(parents=True)
        self.user.mkdir()
        for name in ('Cities2.exe', 'UnityPlayer.dll', 'Cities2_Data/Managed/Game.dll'):
            (self.game / name).write_bytes(b'fixture ' + name.encode())
        for name in p.ASSETS:
            (self.game / 'Cities2_Data' / name).write_bytes(b'original ' + name.encode())
        (self.game / 'Cities2_Data/boot.config').write_bytes(b'\xef\xbb\xbfgfx-enable-gfx-jobs=1\r\ngfx-enable-native-gfx-jobs=1  \nother=value\r\n')
        (self.user / 'launcher-settings.json').write_bytes(b'{"system": {"display_mode": "fullscreen", "other": 4}}\n')
        self.backend = p.Backend(self.game, self.user)
        self.original = {name: path.read_bytes() for name, path in self.backend.paths.items()}
        self.mocks = [patch.object(p, 'inspect_asset', inspect_fake), patch.object(p, 'patch_asset', patch_fake), patch.object(p, 'cities_processes', return_value=[])]
        for mock in self.mocks:
            mock.start()

    def tearDown(self):
        for mock in reversed(self.mocks):
            mock.stop()
        self.temp.cleanup()

    def assert_original(self):
        self.assertEqual(self.original, {name: path.read_bytes() for name, path in self.backend.paths.items()})

    def test_install_idempotent_and_byte_exact_restore(self):
        result = self.backend.install(True)
        self.assertEqual(len(result['changedFiles']), 4)
        self.assertTrue(self.backend.check()['ready'])
        self.assertEqual(self.backend.install(True)['changedFiles'], [])
        self.assertEqual(len(list(self.backend.backups.iterdir())), 1)
        self.backend.restore()
        self.assert_original()

    def test_unverified_requires_opt_in_and_makes_no_backup(self):
        with self.assertRaisesRegex(p.PatcherError, 'not been tested'):
            self.backend.install()
        self.assertFalse(self.backend.backups.exists())
        self.assert_original()

    def test_running_game_guard_before_any_write(self):
        with patch.object(p, 'cities_processes', return_value=[{'path': str(self.game / 'Cities2.exe')}]):
            with self.assertRaisesRegex(p.PatcherError, 'Save and close'):
                self.backend.install(True)
        self.assertFalse(self.backend.backups.exists())
        self.assert_original()

    def test_staging_failure_never_modifies_inputs(self):
        def failure(source, target, progress):
            if source.name == p.ASSETS[1]:
                raise p.PatchError('injected validation failure')
            return patch_fake(source, target, progress)
        with patch.object(p, 'patch_asset', failure):
            with self.assertRaisesRegex(p.PatcherError, 'validation failure'):
                self.backend.install(True)
        self.assert_original()
        self.assertIsNone(self.backend._active())

    def test_replacement_failure_rolls_back_completed_changes(self):
        original_replace = self.backend._replace
        failed = False
        def failure(source, target, before, after):
            nonlocal failed
            if target.name == p.ASSETS[1] and not failed:
                failed = True
                raise OSError('injected replacement failure')
            return original_replace(source, target, before, after)
        with patch.object(self.backend, '_replace', failure):
            with self.assertRaisesRegex(p.PatcherError, 'replacement failure'):
                self.backend.install(True)
        self.assert_original()

    def test_modified_target_prevents_partial_restore(self):
        self.backend.install(True)
        self.backend.paths['boot.config'].write_bytes(b'user changed it')
        before_restore = {n: x.read_bytes() for n, x in self.backend.paths.items()}
        with self.assertRaisesRegex(p.PatcherError, 'changed after'):
            self.backend.restore()
        self.assertEqual(before_restore, {n: x.read_bytes() for n, x in self.backend.paths.items()})

    def test_corrupt_backup_prevents_any_restore(self):
        result = self.backend.install(True)
        (Path(result['backup']) / 'before' / p.ASSETS[0]).write_bytes(b'corrupt')
        with self.assertRaisesRegex(p.PatcherError, 'damaged'):
            self.backend.restore()
        self.assertTrue(self.backend.check()['ready'])

    def test_engine_update_refuses_old_restore(self):
        self.backend.install(True)
        (self.game / 'UnityPlayer.dll').write_bytes(b'new engine')
        with self.assertRaisesRegex(p.PatcherError, 'changed after'):
            self.backend.restore()
        self.assertTrue(self.backend.check()['ready'])

    def test_interrupted_transaction_can_restore_mixed_state(self):
        result = self.backend.install(True)
        transaction = Path(result['backup'])
        record = transaction / 'transaction.json'
        state = json.loads(record.read_text())
        state['status'] = 'Installing'
        p.write_json(record, state)
        name = p.ASSETS[0]
        self.backend.paths[name].write_bytes(self.original[name])
        with self.assertRaisesRegex(p.PatcherError, 'unfinished'):
            self.backend.install(True)
        self.backend.restore()
        self.assert_original()

    def test_custom_profile_cannot_launch(self):
        with self.assertRaisesRegex(p.PatcherError, 'custom test'):
            self.backend.launch()

    def shortcut_record(self, owned=True):
        return dict(path=str(self.root / 'fake-desktop' / 'DX12.lnk'), sha256='A' * 64,
                    status='created' if owned else 'existing', createdByPatcher=owned)

    def test_custom_profile_never_touches_desktop(self):
        with patch.object(p, 'ensure_shortcut') as create, patch.object(p, 'remove_shortcut') as remove:
            result = self.backend.install(True)
            self.assertEqual(result['desktopShortcut']['status'], 'skipped')
            self.backend.restore()
            create.assert_not_called()
            remove.assert_not_called()

    def test_shortcut_ownership_survives_repeat_install_and_restore(self):
        self.backend.default_user = self.user  # Mock helper: never the actual Desktop.
        owned, reused = self.shortcut_record(), self.shortcut_record(False)
        with patch.object(p, 'ensure_shortcut', side_effect=[owned, reused]) as create:
            self.backend.install(True)
            result = self.backend.install(True)
        self.assertEqual(create.call_count, 2)
        self.assertEqual(result['changedFiles'], [])
        self.assertTrue(result['desktopShortcut']['createdByPatcher'])
        self.assertEqual(len([item for item in self.backend.backups.iterdir() if item.is_dir()]), 1)
        ledger = self.backend.backups / 'desktop-shortcut.json'
        self.assertEqual(json.loads(ledger.read_text())['shortcut'], owned)
        def remove_after_restore(record, game, args):
            self.assert_original()
            self.assertEqual(record, owned)
            return {'status': 'removed'}
        with patch.object(p, 'remove_shortcut', side_effect=remove_after_restore):
            result = self.backend.restore()
        self.assertEqual(result['desktopShortcut']['status'], 'removed')
        self.assertFalse(ledger.exists())

    def test_identical_user_shortcut_is_never_claimed_or_removed(self):
        self.backend.default_user = self.user
        with patch.object(p, 'ensure_shortcut', return_value=self.shortcut_record(False)):
            self.backend.install(True)
        self.assertFalse((self.backend.backups / 'desktop-shortcut.json').exists())
        with patch.object(p, 'remove_shortcut') as remove:
            self.backend.restore()
            remove.assert_not_called()
        self.assert_original()

    def test_prepared_install_adds_and_restores_only_shortcut(self):
        for name in p.ASSETS:
            path = self.backend.paths[name]
            path.write_bytes(path.read_bytes() + b'|DX12')
        boot = self.backend.paths['boot.config']
        boot.write_bytes(p.boot_bytes(boot.read_bytes()))
        launcher = self.backend.paths['launcher-settings.json']
        launcher.write_bytes(p.display_bytes(launcher.read_bytes()))
        prepared = {name: path.read_bytes() for name, path in self.backend.paths.items()}
        self.backend.default_user = self.user
        with patch.object(p, 'ensure_shortcut', return_value=self.shortcut_record()):
            result = self.backend.install(True)
        self.assertEqual(result['changedFiles'], [])
        self.assertIsNone(self.backend._active())
        with patch.object(p, 'remove_shortcut', return_value={'status': 'removed'}) as remove:
            self.backend.restore()
            remove.assert_called_once()
        self.assertEqual(prepared, {name: path.read_bytes() for name, path in self.backend.paths.items()})
        self.assertFalse((self.backend.backups / 'desktop-shortcut.json').exists())

    def test_shortcut_failure_leaves_successful_game_install_intact(self):
        self.backend.default_user = self.user
        with patch.object(p, 'ensure_shortcut', side_effect=OSError('Desktop unavailable')):
            result = self.backend.install(True)
        self.assertTrue(self.backend.check()['ready'])
        self.assertEqual(self.backend._active()[1]['status'], 'Installed')
        self.assertIn('Desktop unavailable', result['warnings'][0])
        self.assertIn('-force-d3d12', result['warnings'][0])

    def test_modified_shortcut_is_preserved_when_game_restored(self):
        self.backend.default_user = self.user
        with patch.object(p, 'ensure_shortcut', return_value=self.shortcut_record()):
            self.backend.install(True)
        with patch.object(p, 'remove_shortcut', return_value={'status': 'preserved', 'reason': 'Shortcut modified'}):
            result = self.backend.restore()
        self.assert_original()
        self.assertTrue((self.backend.backups / 'desktop-shortcut.json').exists())
        self.assertIn('Shortcut modified', result['warnings'][0])

    def test_shortcut_ledger_failure_removes_new_link_without_rolling_back_game(self):
        self.backend.default_user = self.user
        original_write = p.write_json
        def fail_ledger(path, data):
            if path.name == 'desktop-shortcut.json':
                raise OSError('ownership record failure')
            original_write(path, data)
        owned = self.shortcut_record()
        with patch.object(p, 'ensure_shortcut', return_value=owned), patch.object(p, 'remove_shortcut', return_value={'status': 'removed'}) as remove, patch.object(p, 'write_json', side_effect=fail_ledger):
            result = self.backend.install(True)
        remove.assert_called_once_with(owned, self.game, p.LAUNCH_ARGS)
        self.assertTrue(self.backend.check()['ready'])
        self.assertEqual(self.backend._active()[1]['status'], 'Installed')
        self.assertIn('ownership record failure', result['warnings'][0])

    def test_invalid_ownership_ledger_is_preserved(self):
        self.backend.install(True)
        self.backend.default_user = self.user
        ledger = self.backend.backups / 'desktop-shortcut.json'
        data = {'format': 9, 'game': str(self.game), 'shortcut': self.shortcut_record()}
        p.write_json(ledger, data)
        with patch.object(p, 'ensure_shortcut') as create:
            result = self.backend.install(True)
        create.assert_not_called()
        self.assertEqual(json.loads(ledger.read_text()), data)
        self.assertIn('ownership record', result['warnings'][0])

    def test_separate_process_mutex_refuses_concurrent_install(self):
        marker = self.root / 'lock-acquired'
        code = "import sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);import patcher;\n@patcher.mutation_locked\ndef hold():\n Path(sys.argv[2]).write_text('locked');sys.stdin.readline()\nhold()"
        child = subprocess.Popen([sys.executable, '-c', code, str(Path(p.__file__).parent), str(marker)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 8
            while not marker.exists() and child.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertTrue(marker.exists(), 'Second-process mutex setup failed')
            with self.assertRaisesRegex(p.PatcherError, 'Another patcher operation'):
                self.backend.install(True)
            self.assert_original()
            self.assertFalse(self.backend.backups.exists())
        finally:
            child.communicate('\n', timeout=10)


class SettingsEdits(unittest.TestCase):
    def test_preserve_encoding_and_unrelated_boot_values(self):
        data = b'\xef\xbb\xbfx=1\r\ngfx-enable-gfx-jobs=1  \r\ngfx-enable-native-gfx-jobs=1\ny=2'
        self.assertEqual(p.boot_bytes(data), data.replace(b'jobs=1', b'jobs=0'))

    def test_duplicate_or_unrecognized_boot_values_refused(self):
        for data in (b'gfx-enable-gfx-jobs=1\ngfx-enable-gfx-jobs=0\n', b'gfx-enable-gfx-jobs=maybe\n'):
            with self.assertRaises(p.PatcherError):
                p.boot_bytes(data)

    def test_missing_boot_flags_added_without_dropping_existing(self):
        self.assertEqual(p.boot_bytes(b'other=1'), b'other=1\ngfx-enable-gfx-jobs=0\ngfx-enable-native-gfx-jobs=0\n')

    def test_display_edit_exact_and_duplicate_json_refused(self):
        data = b'\xef\xbb\xbf{"system": {"display_mode" : "fullscreen", "x": 3}}\r\n'
        self.assertEqual(p.display_bytes(data), data.replace(b'"fullscreen"', b'"borderless_fullscreen"'))
        with self.assertRaises(p.PatcherError):
            p.display_bytes(b'{"system":{"display_mode":"a","display_mode":"b"}}')


if __name__ == '__main__':
    unittest.main()
