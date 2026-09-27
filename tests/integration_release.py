"""Optional private-fixture release test. Copies inputs; never launches the game."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest().upper()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--exe', required=True, type=Path)
    parser.add_argument('--game-source', required=True, type=Path)
    parser.add_argument('--original-assets', required=True, type=Path)
    parser.add_argument('--original-boot', required=True, type=Path)
    parser.add_argument('--scratch', required=True, type=Path)
    args = parser.parse_args()
    scratch = args.scratch.resolve()
    if scratch.exists():
        raise RuntimeError('Choose a new scratch directory; existing contents will never be deleted.')
    scratch.mkdir(parents=True)
    game, user = scratch / 'game', scratch / 'profile'
    (game / 'Cities2_Data/Managed').mkdir(parents=True)
    user.mkdir()
    for name in ('Cities2.exe', 'UnityPlayer.dll', 'Cities2_Data/Managed/Game.dll'):
        shutil.copyfile(args.game_source / name, game / name)
    for name in ('globalgamemanagers.assets', 'resources.assets'):
        shutil.copyfile(args.original_assets / name, game / 'Cities2_Data' / name)
    shutil.copyfile(args.original_boot, game / 'Cities2_Data/boot.config')
    (user / 'launcher-settings.json').write_bytes(b'{"system": {"display_mode": "fullscreen", "other": 123}, "untouched": true}\r\n')
    files = [game / 'Cities2_Data' / n for n in ('globalgamemanagers.assets', 'resources.assets', 'boot.config')] + [user / 'launcher-settings.json']
    original = {str(f): sha(f) for f in files}
    results = []

    def run(label, action=None, extras=(), expected=True):
        output = scratch / (label + '.json')
        cmd = [str(args.exe.resolve())]
        if action:
            cmd += ['--action', action, '--game', str(game), '--user-data', str(user)]
        cmd += [*extras, '--output', str(output)]
        result = subprocess.run(cmd, timeout=180, capture_output=True)
        if not output.exists():
            raise AssertionError(f'{label}: no JSON; return code {result.returncode}; stderr {result.stderr!r}')
        data = json.loads(output.read_text(encoding='utf-8'))
        assert data['ok'] == expected, (label, data)
        assert result.returncode == (0 if expected else 1), (label, result.returncode)
        results.append({'case': label, 'passed': True})
        return data

    run('packaged-self-test', extras=['--self-test'])
    run('packaged-ui-smoke', extras=['--ui-smoke'])
    check = run('original-check', 'check')
    assert check['knownBuild'] and not check['ready']
    install = run('install', 'install')
    assert len(install['changedFiles']) == 4
    assert sha(files[0]) == '3E0F83AE83379387525184F4240017898A5467ADCC89C11B9C1886087CC73611'
    assert sha(files[1]) == '3E189017AFF5E8A32543E17A9B092289C2CA4A6374818C7792BF6D913514A050'
    assert run('prepared-check', 'check')['ready']
    assert run('repeat-install-no-op', 'install')['changedFiles'] == []
    installed_boot = files[2].read_bytes()
    installed_hashes = {str(f): sha(f) for f in files}
    files[2].write_bytes(installed_boot + b'# later edit\r\n')
    run('restore-refuses-later-edit', 'restore', expected=False)
    assert all(sha(f) == installed_hashes[str(f)] for f in files if f != files[2])
    files[2].write_bytes(installed_boot)
    run('restore', 'restore')
    assert {str(f): sha(f) for f in files} == original
    run('custom-profile-launch-refused', 'launch', expected=False)
    with (game / 'UnityPlayer.dll').open('ab') as f:
        f.write(b'UNTESTED-FIXTURE')
    assert not run('unknown-engine-check', 'check')['knownBuild']
    run('unknown-engine-install-refused', 'install', expected=False)
    assert {str(f): sha(f) for f in files} == original
    (scratch / 'results.json').write_text(json.dumps({'passed': True, 'cases': results, 'gameLaunched': False}, indent=2))
    print(json.dumps({'passed': True, 'cases': len(results), 'gameLaunched': False}))


if __name__ == '__main__':
    main()
