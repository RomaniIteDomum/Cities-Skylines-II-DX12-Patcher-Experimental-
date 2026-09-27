"""Build a portable Windows folder; never reads a game installation."""
from pathlib import Path
import importlib.metadata as metadata
import json
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parent


def tkinter_data(release):
    # Python 3.14's Tcl 9 distribution stores its scripts in ZIP files.
    # PyInstaller 6.20 finds the DLLs but may miss these zipfs script roots.
    for prefix, target in (('tcl_library/', '_tcl_data'), ('tk_library/', '_tk_data')):
        destination = release / '_internal' / target
        if not (destination / ('init.tcl' if target == '_tcl_data' else 'tk.tcl')).exists():
            found = False
            for archive in (Path(sys.base_prefix) / 'tcl').glob('*.zip'):
                with zipfile.ZipFile(archive) as bundle:
                    for name in bundle.namelist():
                        if not name.startswith(prefix) or name.endswith('/'):
                            continue
                        relative = Path(name[len(prefix):])
                        if relative.is_absolute() or '..' in relative.parts:
                            raise RuntimeError('Invalid Tcl runtime archive member.')
                        output = destination / relative
                        output.parent.mkdir(parents=True, exist_ok=True)
                        output.write_bytes(bundle.read(name))
                        found = True
            if not found:
                raise RuntimeError('Missing Tcl/Tk script data in the packaged app: ' + target)


def notices(destination):
    destination.mkdir(parents=True, exist_ok=True)
    index = []
    for dist in sorted(metadata.distributions(), key=lambda d: d.metadata['Name'].lower()):
        name = dist.metadata['Name']
        if name.lower() == 'pip':
            continue
        target = destination / name
        target.mkdir(exist_ok=True)
        entry = {'name': name, 'version': dist.version,
                 'licenseExpression': dist.metadata.get('License-Expression'),
                 'license': dist.metadata.get('License'),
                 'urls': dist.metadata.get_all('Project-URL', [])}
        index.append(entry)
        (target / 'METADATA.txt').write_text(dist.read_text('METADATA') or dist.read_text('PKG-INFO') or json.dumps(entry, indent=2), encoding='utf-8')
        for item in dist.files or []:
            lower = str(item).lower()
            if any(token in Path(lower).name for token in ('license', 'copying', 'notice', 'copyright')):
                source = Path(dist.locate_file(item))
                if source.is_file():
                    # Flatten only the distribution-relative prefix; do not expose build paths.
                    name_on_disk = str(item).replace('/', '__').replace('\\', '__').replace('..', '_')
                    shutil.copyfile(source, target / name_on_disk)
    python_license = Path(sys.base_prefix) / 'LICENSE.txt'
    if not python_license.exists():
        python_license = Path(sys.base_prefix) / 'LICENSE'
    if not python_license.exists():
        raise RuntimeError('Cannot locate Python runtime license.')
    shutil.copyfile(python_license, destination / 'PYTHON-LICENSE.txt')
    tcl = Path(sys.base_prefix) / 'tcl'
    for family in tcl.glob('*'):
        if family.is_dir():
            for source in family.glob('license*'):
                if source.is_file():
                    shutil.copyfile(source, destination / (family.name + '-' + source.name))
    for archive in tcl.glob('*.zip'):
        with zipfile.ZipFile(archive) as bundle:
            for name in bundle.namelist():
                if Path(name).name.lower() == 'license.terms':
                    (destination / (archive.stem + '-license.terms')).write_bytes(bundle.read(name))
    (destination / 'DEPENDENCIES.json').write_text(json.dumps(index, indent=2), encoding='utf-8')
    (destination / 'README.txt').write_text(
        'Third-party notices for bundled dependencies. Their own license terms apply.\n'
        'Some metadata also describes build-time dependencies, which may not be shipped at runtime.\n'
        'The patcher includes no Cities: Skylines II assets, shader bytecode, executable or engine DLL.\n', encoding='utf-8')


def main():
    if sys.platform != 'win32':
        raise SystemExit('Build the Windows release on Windows with 64-bit Python 3.14.')
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--noupx',
                    '--onedir', '--windowed', '--name', 'CS2-DX12-Patcher',
                    '--paths', str(ROOT / 'src'), '--collect-all', 'UnityPy',
                    '--collect-all', 'tpk_ar', '--collect-data', 'archspec',
                    '--copy-metadata', 'UnityPy',
                    '--distpath', str(ROOT / 'dist'), '--workpath', str(ROOT / 'build'),
                    '--specpath', str(ROOT / 'build'), str(ROOT / 'src/app.py')], cwd=ROOT, check=True)
    release = ROOT / 'dist/CS2-DX12-Patcher'
    tkinter_data(release)
    for name in ('README.md', 'LICENSE', 'requirements-lock.txt'):
        shutil.copyfile(ROOT / name, release / name)
    shutil.copytree(ROOT / 'docs', release / 'docs', dirs_exist_ok=True)
    notices(release / 'THIRD-PARTY-NOTICES')
    print(release)


if __name__ == '__main__':
    main()
