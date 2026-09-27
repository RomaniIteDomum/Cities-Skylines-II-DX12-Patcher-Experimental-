"""Create audited source and Windows ZIPs without including private fixtures."""
import argparse
import hashlib
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parent
VERSION = '0.1.2-experimental'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest().upper()


def archive(target, entries):
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for source, relative in sorted(entries, key=lambda x: str(x[1])):
            bundle.write(source, str(relative).replace('\\', '/'))
    with zipfile.ZipFile(target) as bundle:
        if bundle.testzip() is not None:
            raise RuntimeError('ZIP integrity check failed.')
    target.with_suffix(target.suffix + '.sha256').write_text(f'{sha(target)}  {target.name}\n', encoding='ascii')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/releases')
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    binary = ROOT / 'dist/CS2-DX12-Patcher'
    if not (binary / 'CS2-DX12-Patcher.exe').is_file():
        raise RuntimeError('Run build_windows.py first.')
    # Documentation can change after a build when validation is recorded.
    for name in ('README.md', 'LICENSE', 'requirements-lock.txt'):
        shutil.copyfile(ROOT / name, binary / name)
    shutil.copytree(ROOT / 'docs', binary / 'docs', dirs_exist_ok=True)
    entries = [(p, Path('CS2-DX12-Patcher') / p.relative_to(binary)) for p in binary.rglob('*') if p.is_file() and p.name != 'SHA256SUMS.txt']
    forbidden = {'.assets', '.cok', '.log', '.dx12', '.dmp'}
    if any(p.suffix.lower() in forbidden or p.name in {'UnityPlayer.dll', 'Cities2.exe', 'game-folder.txt', 'transaction.json'} for p, _ in entries):
        raise RuntimeError('Private or game data found in the release folder.')
    sums = '\n'.join(sha(p) + '  ' + str(r.relative_to('CS2-DX12-Patcher')).replace('\\', '/') for p, r in sorted(entries, key=lambda x: str(x[1]))) + '\n'
    (binary / 'SHA256SUMS.txt').write_text(sums, encoding='utf-8')
    entries.append((binary / 'SHA256SUMS.txt', Path('CS2-DX12-Patcher/SHA256SUMS.txt')))
    archive(output / f'CS2-DX12-Patcher-{VERSION}-Windows-x64.zip', entries)
    # Explicit allowlist prevents accidental publication of build paths, logs or assets.
    source_files = [ROOT / name for name in ('.gitignore', 'README.md', 'LICENSE', 'requirements.txt', 'requirements-build.txt', 'requirements-lock.txt', 'build_windows.py', 'make_release.py', 'Run Editable App.cmd')]
    for folder in ('src', 'tests', 'docs', '.github'):
        source_files.extend(p for p in (ROOT / folder).rglob('*') if p.is_file() and p.suffix in ('.py', '.md', '.yml', '.yaml'))
    archive(output / f'CS2-DX12-Patcher-{VERSION}-Source.zip', [(p, Path('CS2-DX12-Patcher-Source') / p.relative_to(ROOT)) for p in source_files])
    for artifact in output.glob(f'*{VERSION}*.zip'):
        print(f'{artifact.name}: {artifact.stat().st_size} bytes; SHA256 {sha(artifact)}')


if __name__ == '__main__':
    main()
