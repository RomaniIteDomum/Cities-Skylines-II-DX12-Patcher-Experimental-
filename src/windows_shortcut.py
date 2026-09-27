"""Create a real Windows shortcut without interpolating user paths into code."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import uuid


class ShortcutError(Exception):
    """A desktop shortcut could not be prepared or verified safely."""


SHORTCUT_STEM = 'Cities Skylines II - DX12 (Experimental)'
DESCRIPTION = 'Experimental Cities: Skylines II DX12 launch. Requires the prepared DX12 configuration.'
_PS_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
try {
    $request = [Console]::In.ReadToEnd() | ConvertFrom-Json
    $shell = New-Object -ComObject WScript.Shell
    if ($request.action -ne 'desktop') {
        Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
[ComImport, Guid("00021401-0000-0000-C000-000000000046")]
internal class DX12ShellLink { }
[ComImport, Guid("000214F9-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
internal interface IDX12ShellLinkW {
    void GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder path, int count, IntPtr findData, uint flags);
    void GetIDList(out IntPtr value);
    void SetIDList(IntPtr value);
    void GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder value, int count);
    void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string value);
    void GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder value, int count);
    void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string value);
    void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder value, int count);
    void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string value);
    void GetHotkey(out short value);
    void SetHotkey(short value);
    void GetShowCmd(out int value);
    void SetShowCmd(int value);
    void GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder value, int count, out int index);
    void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string value, int index);
    void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string value, uint reserved);
    void Resolve(IntPtr hwnd, uint flags);
    void SetPath([MarshalAs(UnmanagedType.LPWStr)] string value);
}
public class DX12ShortcutInfo {
    public string target { get; set; }
    public string arguments { get; set; }
    public string workingDirectory { get; set; }
    public string icon { get; set; }
    public string description { get; set; }
}
public static class DX12ShortcutNative {
    public static void Create(string file, string target, string arguments, string directory, string description) {
        object instance = new DX12ShellLink();
        try {
            IDX12ShellLinkW link = (IDX12ShellLinkW)instance;
            link.SetPath(target);
            link.SetArguments(arguments);
            link.SetWorkingDirectory(directory);
            link.SetDescription(description);
            link.SetIconLocation(target, 0);
            ((IPersistFile)instance).Save(file, true);
        } finally { Marshal.FinalReleaseComObject(instance); }
    }
    public static DX12ShortcutInfo Read(string file) {
        object instance = new DX12ShellLink();
        try {
            ((IPersistFile)instance).Load(file, 0);
            IDX12ShellLinkW link = (IDX12ShellLinkW)instance;
            StringBuilder target = new StringBuilder(32768), args = new StringBuilder(32768), directory = new StringBuilder(32768), description = new StringBuilder(32768), icon = new StringBuilder(32768);
            int iconIndex;
            link.GetPath(target, target.Capacity, IntPtr.Zero, 4);
            link.GetArguments(args, args.Capacity);
            link.GetWorkingDirectory(directory, directory.Capacity);
            link.GetDescription(description, description.Capacity);
            link.GetIconLocation(icon, icon.Capacity, out iconIndex);
            return new DX12ShortcutInfo { target = target.ToString(), arguments = args.ToString(), workingDirectory = directory.ToString(), description = description.ToString(), icon = icon.ToString() + "," + iconIndex };
        } finally { Marshal.FinalReleaseComObject(instance); }
    }
}
'@
    }
    if ($request.action -eq 'desktop') {
        $response = @{ path = [string]$shell.SpecialFolders.Item('Desktop') }
    } elseif ($request.action -eq 'read') {
        if (-not [IO.File]::Exists([string]$request.path)) { throw 'Shortcut does not exist.' }
        # Read through the Unicode Shell Link interface. WScript.Shell's older
        # TargetPath setter can reject characters outside the active code page.
        $response = [DX12ShortcutNative]::Read([string]$request.path)
    } elseif ($request.action -eq 'create') {
        if ([IO.File]::Exists([string]$request.path) -or [IO.Directory]::Exists([string]$request.path)) { throw 'Temporary shortcut path already exists.' }
        try {
            $shortcut = $shell.CreateShortcut([string]$request.path)
            $shortcut.TargetPath = [string]$request.target
            $shortcut.Arguments = [string]$request.arguments
            $shortcut.WorkingDirectory = [string]$request.workingDirectory
            $shortcut.IconLocation = ([string]$request.target) + ',0'
            $shortcut.Description = [string]$request.description
            $shortcut.Save()
        } catch {
            if ([IO.File]::Exists([string]$request.path)) { throw }
            [DX12ShortcutNative]::Create([string]$request.path,[string]$request.target,[string]$request.arguments,[string]$request.workingDirectory,[string]$request.description)
        }
        $response = @{ saved = $true }
    } else { throw 'Unknown shortcut operation.' }
    [Console]::Out.Write(($response | ConvertTo-Json -Compress -Depth 4))
    exit 0
} catch {
    [Console]::Out.Write((@{ error = ($_.Exception.Message + ' (helper line ' + $_.InvocationInfo.ScriptLineNumber + ')') } | ConvertTo-Json -Compress))
    exit 1
}
'''


def _com(request: dict) -> dict:
    if os.name != 'nt':
        raise ShortcutError('Desktop shortcuts require Windows.')
    system_root = Path(os.environ.get('SystemRoot', r'C:\Windows'))
    powershell = system_root / 'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe'
    if not powershell.is_file():
        raise ShortcutError('Built-in Windows PowerShell was not found.')
    environment = dict(os.environ)
    # A parent PowerShell 7 process can export a module search path unsuitable
    # for Windows PowerShell 5.1. Use its standard built-in module directories.
    environment['PSModulePath'] = ';'.join((
        str(Path.home() / 'Documents' / 'WindowsPowerShell' / 'Modules'),
        str(Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'WindowsPowerShell' / 'Modules'),
        str(powershell.parent / 'Modules'),
    ))
    try:
        result = subprocess.run(
            [str(powershell), '-NoLogo', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-Command', _PS_SCRIPT],
            # ASCII JSON escapes avoid legacy Windows PowerShell console input
            # code-page conversion while preserving all Unicode path characters.
            input=json.dumps(request, ensure_ascii=True).encode('ascii'),
            capture_output=True, timeout=30, check=False,
            creationflags=subprocess.CREATE_NO_WINDOW, env=environment,
        )
        response = json.loads(result.stdout.decode('utf-8-sig'))
    except (OSError, subprocess.TimeoutExpired, UnicodeError, json.JSONDecodeError) as exc:
        raise ShortcutError(f'Windows shortcut helper failed: {exc}') from exc
    if result.returncode or not isinstance(response, dict) or 'error' in response:
        detail = response.get('error', 'invalid helper response') if isinstance(response, dict) else 'invalid helper response'
        raise ShortcutError(f'Windows shortcut helper failed: {detail}')
    return response


def _desktop_path(desktop: Path | None) -> Path:
    raw = desktop if desktop is not None else _com({'action': 'desktop'}).get('path')
    if not raw:
        raise ShortcutError('Windows did not return a Desktop folder.')
    path = Path(raw).resolve()
    if not path.is_dir():
        raise ShortcutError(f'The Desktop folder is not available: {path}')
    return path


def _same_path(left, right) -> bool:
    return os.path.normcase(os.path.abspath(str(left))) == os.path.normcase(os.path.abspath(str(right)))


def _hash(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest().upper()


def _safe_file(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return stat.S_ISREG(info.st_mode) and not path.is_symlink() and not (getattr(info, 'st_file_attributes', 0) & 0x400)


def _filename_allowed(name: str) -> bool:
    return bool(re.fullmatch(re.escape(SHORTCUT_STEM) + r'(?: - [0-9a-f]{10}(?: - (?:[2-9]|[1-9][0-9]+))?)?\.lnk', name, flags=re.IGNORECASE))


def _expected(game: Path, launch_args: list[str]) -> dict:
    game = Path(game).resolve()
    if not isinstance(launch_args, list) or not launch_args or any(not isinstance(arg, str) or '\x00' in arg or '\r' in arg or '\n' in arg for arg in launch_args):
        raise ShortcutError('Launch arguments must be a nonempty list of strings without control characters.')
    target = game / 'Cities2.exe'
    if not target.is_file():
        raise ShortcutError(f'Cities2.exe was not found in {game}.')
    return {'target': str(target), 'arguments': subprocess.list2cmdline(launch_args), 'workingDirectory': str(game)}


def _matches(actual: dict, expected: dict) -> bool:
    return _same_path(actual.get('target', ''), expected['target']) and actual.get('arguments') == expected['arguments'] and _same_path(actual.get('workingDirectory', ''), expected['workingDirectory'])


def _icon_matches(actual: dict, expected: dict) -> bool:
    icon = actual.get('icon', '')
    path, separator, index = icon.rpartition(',')
    return separator == ',' and index.strip() == '0' and _same_path(path, expected['target'])


def _record(path: Path, desktop: Path, expected: dict, created: bool) -> dict:
    return dict(expected, path=str(path), desktop=str(desktop), sha256=_hash(path), status='created' if created else 'existing', createdByPatcher=created, shortcutVersion=1)


def ensure_shortcut(game: Path, launch_args: list[str], desktop: Path | None = None) -> dict:
    """Create/reuse a verified shortcut; never overwrite another desktop item.

    Existing matching shortcuts are returned with createdByPatcher=False. Keep
    an earlier ownership record when its path/hash match this reused shortcut;
    otherwise a user's independently created shortcut must remain unowned.
    """
    expected = _expected(game, launch_args)
    desktop_path = _desktop_path(desktop)
    # Find existing matches first, even if a previously occupied base filename
    # has since become free; repeated installs should not make duplicates.
    for candidate in sorted(desktop_path.iterdir(), key=lambda item: item.name.casefold()):
        if not _filename_allowed(candidate.name) or not _safe_file(candidate):
            continue
        try:
            actual = _com({'action': 'read', 'path': str(candidate)})
            if _matches(actual, expected):
                return _record(candidate, desktop_path, expected, False)
        except ShortcutError:
            continue
    suffix = hashlib.sha256(os.path.normcase(expected['workingDirectory']).encode('utf-8')).hexdigest()[:10]
    stems = [SHORTCUT_STEM, f'{SHORTCUT_STEM} - {suffix}']
    stems.extend(f'{SHORTCUT_STEM} - {suffix} - {number}' for number in range(2, 100))
    for stem in stems:
        candidate = desktop_path / (stem + '.lnk')
        # lexists covers dangling symlinks as well as occupied files/directories.
        if os.path.lexists(candidate):
            continue
        temporary = desktop_path / ('.cs2-dx12-' + uuid.uuid4().hex + '.lnk')
        temporary_created = False
        renamed = False
        prepared_hash = None
        try:
            _com({'action': 'create', 'path': str(temporary), **expected, 'description': DESCRIPTION})
            temporary_created = True
            prepared = _com({'action': 'read', 'path': str(temporary)})
            if not _safe_file(temporary) or not _matches(prepared, expected) or not _icon_matches(prepared, expected):
                raise ShortcutError('The new shortcut failed verification.')
            prepared_hash = _hash(temporary)
            # Windows rename refuses an occupied destination, including a file
            # that appeared after our earlier collision check.
            try:
                os.rename(temporary, candidate)
                renamed = True
            except FileExistsError:
                continue
            saved = _com({'action': 'read', 'path': str(candidate)})
            if not _matches(saved, expected) or not _icon_matches(saved, expected) or _hash(candidate) != prepared_hash:
                raise ShortcutError('The saved desktop shortcut failed verification.')
            return _record(candidate, desktop_path, expected, True)
        except (ShortcutError, OSError) as exc:
            # Contain failures after the atomic rename without deleting a link
            # that somebody subsequently edited or replaced.
            if renamed and prepared_hash and _safe_file(candidate) and _hash(candidate) == prepared_hash:
                candidate.unlink()
            if isinstance(exc, ShortcutError):
                raise
            raise ShortcutError(f'Could not save the desktop shortcut: {exc}') from exc
        finally:
            # If the helper saved successfully but failed while returning its
            # response, recover only a complete shortcut with our exact target.
            if not temporary_created and _safe_file(temporary):
                try:
                    temporary_created = _matches(_com({'action': 'read', 'path': str(temporary)}), expected)
                except ShortcutError:
                    pass
            if temporary_created and _safe_file(temporary):
                temporary.unlink()
    raise ShortcutError('All available DX12 shortcut names are occupied; no desktop items were changed.')


def remove_shortcut(record: dict, game: Path, launch_args: list[str], desktop: Path | None = None) -> dict:
    """Remove only the exact owned and still-unmodified shortcut described."""
    def preserved(reason):
        return {'status': 'preserved', 'reason': reason, 'path': record.get('path') if isinstance(record, dict) else None}
    if not isinstance(record, dict) or record.get('shortcutVersion') != 1 or record.get('createdByPatcher') is not True:
        return preserved('No valid shortcut ownership record.')
    expected = _expected(game, launch_args)
    desktop_path = _desktop_path(desktop)
    if not isinstance(record.get('path'), str) or not isinstance(record.get('sha256'), str) or not re.fullmatch('[0-9a-fA-F]{64}', record['sha256']):
        return preserved('Invalid shortcut path/checksum record.')
    path = Path(record['path'])
    # Do not resolve the link itself: that could follow a malicious replacement.
    if not path.is_absolute() or not _same_path(path.parent, desktop_path) or not _same_path(record.get('desktop', ''), desktop_path) or not _filename_allowed(path.name):
        return preserved('Recorded shortcut is not an allowed name in the current Desktop folder.')
    if not _matches(record, expected):
        return preserved('Recorded shortcut belongs to a different launch configuration.')
    if not os.path.lexists(path):
        return {'status': 'missing', 'path': str(path), 'reason': 'Shortcut is already absent.'}
    if not _safe_file(path):
        return preserved('Shortcut path is a directory, link or other unsupported file type.')
    if _hash(path) != record['sha256'].upper():
        return preserved('Shortcut was modified after creation.')
    try:
        actual = _com({'action': 'read', 'path': str(path)})
    except ShortcutError:
        return preserved('Shortcut could not be verified.')
    if not _matches(actual, expected) or not _icon_matches(actual, expected):
        return preserved('Shortcut target, arguments, working directory or icon changed.')
    if not _safe_file(path) or _hash(path) != record['sha256'].upper():
        return preserved('Shortcut changed during verification.')
    try:
        path.unlink()
    except OSError as exc:
        raise ShortcutError(f'Could not remove the verified shortcut: {exc}') from exc
    return {'status': 'removed', 'path': str(path)}
