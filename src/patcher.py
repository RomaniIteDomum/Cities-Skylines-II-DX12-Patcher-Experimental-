"""Transactional, local-only CS2 DX12 preparation. No game data is distributed."""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import uuid
from functools import wraps
from datetime import datetime, timezone
from typing import Callable

from asset_patcher import inspect_asset, patch_asset, PatchError
from windows_shortcut import ensure_shortcut, remove_shortcut

VERSION = "0.1.2-experimental"
BACKUPS = "CS2-DX12-Experimental-Backups"
ASSETS = ("globalgamemanagers.assets", "resources.assets")
KNOWN_UNITY = "1DA82D19C9B19B8B923E6018F2CAAB0D416E84916EFBA02EB58DE9171B40529F"
KNOWN_ASSETS = {
    ASSETS[0]: {"5ACA9280A56B674E104C42F9B4A435FB24B6BBC2650FFB2890941D99C2F931F4", "3E0F83AE83379387525184F4240017898A5467ADCC89C11B9C1886087CC73611"},
    ASSETS[1]: {"95242B9385D43BDAAE38D797C939E080F8A9768D7F42BD4DC81D5AE74FB106A6", "3E189017AFF5E8A32543E17A9B092289C2CA4A6374818C7792BF6D913514A050"},
}
LAUNCH_ARGS = ["-force-d3d12", "-timestamps", "-screen-fullscreen", "1", "-window-mode", "borderless"]
ACTIVE = {"Prepared", "Installing", "Installed", "Failed", "Restoring", "RestoreFailed"}


class PatcherError(RuntimeError):
    pass


def mutation_locked(method):
    """One patch/restore/launch at a time, including separate app instances."""
    @wraps(method)
    def locked(*args, **kwargs):
        if os.name != "nt":
            raise PatcherError("This patcher supports Windows only.")
        from ctypes import wintypes as w
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, w.BOOL, w.LPCWSTR]
        kernel.CreateMutexW.restype = w.HANDLE
        kernel.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
        kernel.WaitForSingleObject.restype = w.DWORD
        kernel.ReleaseMutex.argtypes = [w.HANDLE]
        kernel.CloseHandle.argtypes = [w.HANDLE]
        handle = kernel.CreateMutexW(None, False, "Local\\CS2ExperimentalDX12PatcherMutationsV1")
        if not handle:
            raise PatcherError("Cannot obtain the patcher's operation lock.")
        owned = False
        try:
            result = kernel.WaitForSingleObject(handle, 0)
            if result not in (0, 0x80):
                raise PatcherError("Another patcher operation is running. Wait for it to finish and retry.")
            owned = True
            return method(*args, **kwargs)
        finally:
            if owned:
                kernel.ReleaseMutex(handle)
            kernel.CloseHandle(handle)
    return locked


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest().upper()


def byte_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value: dict) -> None:
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def unique_json(data: bytes) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise PatcherError("A settings file has duplicate keys. Resolve that ambiguity before patching.")
            result[key] = value
        return result
    try:
        result = json.loads(data.decode("utf-8-sig"), object_pairs_hook=unique)
        if not isinstance(result, dict):
            raise ValueError("Root is not an object")
        return result
    except (ValueError, UnicodeError) as exc:
        raise PatcherError("A settings or backup file is not valid UTF-8 JSON.") from exc


def boot_bytes(data: bytes) -> bytes:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeError as exc:
        raise PatcherError("boot.config is not a supported UTF-8 text file.") from exc
    newline = "\r\n" if "\r\n" in text else "\n"
    for key in ("gfx-enable-gfx-jobs", "gfx-enable-native-gfx-jobs"):
        all_keys = re.findall(r"(?m)^\s*" + re.escape(key) + r"\s*=.*$", text)
        pattern = r"(?m)^(" + re.escape(key) + r"=)[01]([ \t]*)(\r?)$"
        if len(all_keys) > 1 or (all_keys and not re.search(pattern, text)):
            raise PatcherError(f"Ambiguous or unsupported {key} entry in boot.config.")
        if all_keys:
            text = re.sub(pattern, r"\g<1>0\2\3", text)
        else:
            if text and not text.endswith(("\n", "\r")):
                text += newline
            text += key + "=0" + newline
    return (b"\xef\xbb\xbf" if data.startswith(b"\xef\xbb\xbf") else b"") + text.encode("utf-8")


def display_bytes(data: bytes) -> bytes:
    parsed = unique_json(data)
    if not isinstance(parsed.get("system"), dict) or not isinstance(parsed["system"].get("display_mode"), str):
        raise PatcherError("launcher-settings.json has an unsupported display setting. No changes made.")
    text = data.decode("utf-8-sig")
    pattern = r'"display_mode"(\s*:\s*)"[^"\\]*"'
    if len(re.findall(pattern, text)) != 1:
        raise PatcherError("Ambiguous display_mode entries in launcher-settings.json.")
    text = re.sub(pattern, r'"display_mode"\1"borderless_fullscreen"', text)
    result = (b"\xef\xbb\xbf" if data.startswith(b"\xef\xbb\xbf") else b"") + text.encode("utf-8")
    expected = json.loads(json.dumps(parsed))
    expected["system"]["display_mode"] = "borderless_fullscreen"
    if unique_json(result) != expected:
        raise PatcherError("The display-mode edit changed unexpected settings.")
    return result


def cities_processes() -> list[dict]:
    """Inspect processes without a shell, debugger attachment or process mutation."""
    if os.name != "nt":
        raise PatcherError("This patcher supports Windows only.")
    from ctypes import wintypes as w
    class Entry(ctypes.Structure):
        _fields_ = [("dwSize", w.DWORD), ("cntUsage", w.DWORD), ("th32ProcessID", w.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", w.DWORD),
                    ("cntThreads", w.DWORD), ("th32ParentProcessID", w.DWORD),
                    ("pcPriClassBase", w.LONG), ("dwFlags", w.DWORD), ("szExeFile", w.WCHAR * 260)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = w.HANDLE
    kernel.Process32FirstW.argtypes = [w.HANDLE, ctypes.POINTER(Entry)]
    kernel.Process32NextW.argtypes = [w.HANDLE, ctypes.POINTER(Entry)]
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenProcess.restype = w.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
    kernel.CloseHandle.argtypes = [w.HANDLE]
    handle = kernel.CreateToolhelp32Snapshot(2, 0)
    if handle == ctypes.c_void_p(-1).value:
        raise PatcherError("Cannot check whether the game is running. Close it and retry.")
    result = []
    try:
        entry = Entry()
        entry.dwSize = ctypes.sizeof(entry)
        success = kernel.Process32FirstW(handle, ctypes.byref(entry))
        while success:
            if entry.szExeFile.lower() == "cities2.exe":
                path = None
                process = kernel.OpenProcess(0x1000, False, entry.th32ProcessID)
                if process:
                    try:
                        buf, size = ctypes.create_unicode_buffer(32768), w.DWORD(32768)
                        if kernel.QueryFullProcessImageNameW(process, 0, buf, ctypes.byref(size)):
                            path = buf.value
                    finally:
                        kernel.CloseHandle(process)
                result.append({"pid": entry.th32ProcessID, "path": path})
            success = kernel.Process32NextW(handle, ctypes.byref(entry))
        # ERROR_NO_MORE_FILES is expected after a completed enumeration.
        if ctypes.get_last_error() not in (0, 18):
            raise PatcherError("Process enumeration could not be completed safely.")
    finally:
        kernel.CloseHandle(handle)
    return result


class Backend:
    def __init__(self, game: Path, user_data: Path | None = None, progress: Callable[[str], None] | None = None):
        raw = Path(str(game).strip().strip('"')).expanduser()
        if raw.name.lower() == "cities2.exe":
            raw = raw.parent
        self.game = raw.resolve()
        self.default_user = (Path.home() / "AppData/LocalLow/Colossal Order/Cities Skylines II").resolve()
        self.user = Path(user_data).resolve() if user_data is not None else self.default_user
        self.progress = progress or (lambda message: None)
        self.paths = {name: self.game / "Cities2_Data" / name for name in ASSETS}
        self.paths["boot.config"] = self.game / "Cities2_Data/boot.config"
        self.paths["launcher-settings.json"] = self.user / "launcher-settings.json"
        self.backups = self.game / BACKUPS

    def _safe_path(self, path: Path, root: Path) -> None:
        # Do not follow redirected individual game files outside the selected installation.
        if path.resolve() != path.absolute() or not path.resolve().is_relative_to(root):
            raise PatcherError(f"Redirected file paths are not supported: {path.name}")

    def _validate(self):
        for name in ("Cities2.exe", "UnityPlayer.dll", "Cities2_Data/Managed/Game.dll", "Cities2_Data/boot.config", *["Cities2_Data/" + n for n in ASSETS]):
            path = self.game / name
            self._safe_path(path, self.game)
            if not path.is_file():
                raise PatcherError("Select the Cities: Skylines II folder containing Cities2.exe, Cities2_Data and UnityPlayer.dll.")
        self._safe_path(self.backups, self.game)
        self._safe_path(self.paths["launcher-settings.json"], self.user)

    def _closed(self):
        for process in cities_processes():
            if not process["path"] or Path(process["path"]).resolve() == self.game / "Cities2.exe" or self.user == self.default_user:
                raise PatcherError("Save and close Cities: Skylines II before installing, restoring or launching another instance.")

    def _identity(self):
        return {n: file_hash(self.game / n) for n in ("Cities2.exe", "UnityPlayer.dll", "Cities2_Data/Managed/Game.dll")}

    def _active(self):
        if not self.backups.exists():
            return None
        self._safe_path(self.backups, self.game)
        for directory in sorted(self.backups.iterdir(), reverse=True):
            if not directory.is_dir():
                continue
            self._safe_path(directory, self.game)
            record = directory / "transaction.json"
            if record.exists():
                self._safe_path(record, self.game)
                state = unique_json(record.read_bytes())
                if state.get("status") in ACTIVE:
                    return directory, state
        return None

    def _after_install(self, result: dict) -> dict:
        """The convenience shortcut cannot turn a successful patch into failure."""
        if self.user != self.default_user:
            result["desktopShortcut"] = {"status": "skipped", "reason": "Isolated user-data folder"}
            return result
        try:
            self._safe_path(self.backups, self.game)
            self.backups.mkdir(exist_ok=True)
            ledger = self.backups / "desktop-shortcut.json"
            self._safe_path(ledger, self.game)
            previous = unique_json(ledger.read_bytes()) if ledger.exists() else None
            if previous is not None and (previous.get("format") != 1 or previous.get("game") != str(self.game)):
                raise PatcherError("Shortcut ownership record belongs to a different installation.")
            self.progress("Creating the DX12 desktop shortcut…")
            shortcut = ensure_shortcut(self.game, LAUNCH_ARGS)
            if shortcut.get("createdByPatcher"):
                try:
                    write_json(ledger, {"format": 1, "game": str(self.game), "shortcut": shortcut})
                except Exception:
                    # Avoid leaving an untracked link when ownership cannot be recorded.
                    remove_shortcut(shortcut, self.game, LAUNCH_ARGS)
                    raise
            elif previous and previous.get("game") == str(self.game):
                owned = previous.get("shortcut", {})
                if owned.get("createdByPatcher") and owned.get("path") == shortcut.get("path") and owned.get("sha256") == shortcut.get("sha256"):
                    shortcut = {**owned, "status": "existing"}
            result["desktopShortcut"] = shortcut
            result["message"] = "DX12 setup is ready. Use the DX12 desktop shortcut to play."
            self.progress("Desktop shortcut: " + shortcut["path"])
        except Exception as exc:
            result.setdefault("warnings", []).append("The game setup succeeded, but the desktop shortcut could not be created: " + str(exc) + ". Use Launch DX12, or add -force-d3d12 to your launcher's arguments.")
        return result

    def _after_restore(self, result: dict) -> dict:
        if self.user != self.default_user:
            return result
        try:
            ledger = self.backups / "desktop-shortcut.json"
            self._safe_path(ledger, self.game)
            if not ledger.exists():
                return result
            saved = unique_json(ledger.read_bytes())
            if saved.get("format") != 1 or saved.get("game") != str(self.game):
                raise PatcherError("Shortcut ownership record belongs to a different installation.")
            removal = remove_shortcut(saved.get("shortcut", {}), self.game, LAUNCH_ARGS)
            result["desktopShortcut"] = removal
            if removal["status"] in ("removed", "missing"):
                ledger.unlink()
                self.progress("The desktop shortcut created by this patcher has been removed.")
            else:
                result.setdefault("warnings", []).append("The desktop shortcut was left unchanged: " + removal.get("reason", "It no longer matches the patcher's original shortcut.") + ". Do not use its DX12 launch arguments after restoring the game.")
        except Exception as exc:
            result.setdefault("warnings", []).append("Game restoration completed, but the desktop shortcut could not be cleaned up: " + str(exc))
        return result

    def check(self) -> dict:
        self._validate()
        assets = []
        for name in ASSETS:
            self.progress(f"Inspecting {name}…")
            try:
                asset = inspect_asset(self.paths[name])
            except PatchError as exc:
                raise PatcherError(str(exc)) from exc
            current_hash = file_hash(self.paths[name])
            if asset["sourceSha256"] != current_hash:
                raise PatcherError("An asset changed during inspection. Close any game updater and retry.")
            asset.update(name=name, sha256=current_hash)
            assets.append(asset)
        if len({a["unityVersion"] for a in assets}) != 1:
            raise PatcherError("The two assets come from different Unity versions. Repair the installation before patching.")
        known = file_hash(self.game / "UnityPlayer.dll") == KNOWN_UNITY and all(a["sha256"] in KNOWN_ASSETS[a["name"]] for a in assets)
        original_boot = self.paths["boot.config"].read_bytes()
        jobs_off = boot_bytes(original_boot) == original_boot
        display = None
        launcher = self.paths["launcher-settings.json"]
        if launcher.exists():
            data = launcher.read_bytes()
            display_bytes(data)  # Validate before any transaction starts.
            display = unique_json(data)["system"]["display_mode"]
        warnings = []
        if not known:
            warnings.append("Untested build: its asset or engine hashes differ from the tested installation. Structural checks are not proof of runtime compatibility.")
        present = [name for name in ("dxgi.dll", "version.dll", "winmm.dll", "d3d12.dll", "dinput8.dll") if (self.game / name).exists()]
        if present:
            warnings.append("Existing proxy DLLs were found and will be left unchanged: " + ", ".join(present) + ". Their compatibility is not verified.")
        active = self._active()
        if active and active[1]["status"] != "Installed":
            warnings.append("An unfinished transaction exists. Use Restore before installing again.")
        ready = all(a["needsAliasCount"] == 0 for a in assets) and jobs_off and display in (None, "borderless_fullscreen")
        return {"version": VERSION, "knownBuild": known, "assets": assets, "ready": ready,
                "graphicsJobsOff": jobs_off, "displayMode": display, "warnings": warnings,
                "message": "DX12 preparation is present." if ready else "Files can be prepared for the experimental DX12 test.",
                "launchArguments": LAUNCH_ARGS}

    def _replace(self, source: Path, target: Path, before: str, after: str):
        self._closed()
        if file_hash(target) != before or file_hash(source) != after:
            raise PatcherError(f"{target.name} changed during preparation. Stopped to protect your files.")
        temp = target.with_name(".cs2-dx12-" + uuid.uuid4().hex + ".tmp")
        try:
            shutil.copyfile(source, temp)
            with temp.open("rb+") as stream:
                stream.flush()
                os.fsync(stream.fileno())
            if file_hash(temp) != after or file_hash(target) != before:
                raise PatcherError("A file changed before replacement. No further files will be replaced.")
            self._closed()
            os.replace(temp, target)
            if file_hash(target) != after:
                raise PatcherError("File verification after replacement failed. Keep the backups.")
        finally:
            temp.unlink(missing_ok=True)

    @mutation_locked
    def install(self, allow_unverified: bool = False) -> dict:
        self._validate()
        self._closed()
        active = self._active()
        if active and active[1]["status"] != "Installed":
            raise PatcherError("An unfinished installation needs recovery. Choose Restore first.")
        check = self.check()
        for warning in check["warnings"]:
            self.progress(warning)
        if not check["knownBuild"] and not allow_unverified:
            raise PatcherError("This build has not been tested. Review Check; command-line installation requires --allow-unverified for this experimental transformation.")
        if check["ready"]:
            return self._after_install({"message": "Already prepared. No game files changed and no extra game backup created.", "changedFiles": []})
        if active:
            raise PatcherError("A previous installation is still active. Restore it before applying a different file state.")
        total = sum(self.paths[n].stat().st_size for n in ASSETS)
        if shutil.disk_usage(self.game).free < total * 5 + 100_000_000:
            raise PatcherError("Not enough free space for verified staging and backups. Free at least 2 GB on the game drive and retry.")
        identity = self._identity()
        # Retain hashes from inspection so a game update cannot silently enter the transaction.
        before_hashes = {a["name"]: a["sha256"] for a in check["assets"]}
        for name in ("boot.config", "launcher-settings.json"):
            if self.paths[name].exists():
                before_hashes[name] = file_hash(self.paths[name])
        transaction = self.backups / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8])
        stage, backup = transaction / "prepared", transaction / "before"
        stage.mkdir(parents=True)
        backup.mkdir()
        state = {"format": 1, "patcherVersion": VERSION, "status": "Preparing", "createdAt": now(),
                 "game": str(self.game), "userData": str(self.user), "identity": identity,
                 "knownBuild": check["knownBuild"], "files": []}
        record = transaction / "transaction.json"
        write_json(record, state)
        try:
            for name in ASSETS:
                if file_hash(self.paths[name]) != before_hashes[name]:
                    raise PatcherError("Game assets changed during inspection. Close any updater and retry.")
                result = patch_asset(self.paths[name], stage / name, self.progress)
                if result["beforeSha256"] != before_hashes[name]:
                    raise PatcherError("An asset changed while staging the patch. No installation performed.")
                if result["outputWritten"]:
                    state["files"].append({"name": name, "before": before_hashes[name], "after": file_hash(stage / name)})
            for name, editor in (("boot.config", boot_bytes), ("launcher-settings.json", display_bytes)):
                target = self.paths[name]
                if not target.exists():
                    continue
                original = target.read_bytes()
                if byte_hash(original) != before_hashes[name]:
                    raise PatcherError("Settings changed during preparation. Close the launcher and retry.")
                prepared = editor(original)
                if prepared != original:
                    (stage / name).write_bytes(prepared)
                    state["files"].append({"name": name, "before": byte_hash(original), "after": byte_hash(prepared)})
            for file in state["files"]:
                self.progress("Backing up " + file["name"] + "…")
                shutil.copyfile(self.paths[file["name"]], backup / file["name"])
                if file_hash(backup / file["name"]) != file["before"]:
                    raise PatcherError("An original changed during backup. No installation performed.")
            if identity != self._identity():
                raise PatcherError("The game updated during preparation. No installation performed.")
            state["status"] = "Prepared"
            write_json(record, state)
            self._closed()
            state["status"] = "Installing"
            write_json(record, state)
            for file in state["files"]:
                self.progress("Installing " + file["name"] + "…")
                self._replace(stage / file["name"], self.paths[file["name"]], file["before"], file["after"])
            state.update(status="Installed", completedAt=now())
            write_json(record, state)
            return self._after_install({"message": "Installed. Use Launch DX12 to start a borderless test. Keep the backup folder to restore later.",
                    "changedFiles": [f["name"] for f in state["files"]], "backup": str(transaction)})
        except Exception as exc:
            if state["status"] in ("Preparing", "Prepared"):
                state.update(status="PreparationFailed", error=str(exc))
                write_json(record, state)
            else:
                problems = []
                for file in reversed(state["files"]):
                    try:
                        target = self.paths[file["name"]]
                        if file_hash(target) == file["after"]:
                            self._replace(backup / file["name"], target, file["after"], file["before"])
                        elif file_hash(target) != file["before"]:
                            problems.append(file["name"] + " changed externally")
                    except Exception as rollback_exc:
                        problems.append(str(rollback_exc))
                state.update(status="Failed" if problems else "RolledBack", error=str(exc), rollbackProblems=problems)
                write_json(record, state)
                if problems:
                    raise PatcherError("Installation stopped; recovery is incomplete. Close the game and choose Restore. Keep the backup folder. " + str(exc)) from exc
            raise PatcherError("Installation stopped: " + str(exc)) from exc

    @mutation_locked
    def restore(self) -> dict:
        self._validate()
        self._closed()
        active = self._active()
        if not active:
            return self._after_restore({"message": "No active backup from this patcher. Earlier patches must be restored with their own backups.", "changedFiles": []})
        transaction, state = active
        if state.get("format") != 1 or state.get("game") != str(self.game) or state.get("userData") != str(self.user):
            raise PatcherError("The backup belongs to another installation or Windows profile. Nothing restored.")
        if state.get("identity") != self._identity():
            raise PatcherError("The game executable, engine or game code changed after installation. Do not restore old files over an updated game; repair the current version instead.")
        files = state.get("files")
        if not isinstance(files, list) or not files or len(files) > 4:
            raise PatcherError("Invalid backup record. Nothing restored.")
        seen = set()
        for file in files:
            name = file.get("name")
            if name not in self.paths or name in seen:
                raise PatcherError("Unrecognized or duplicate backup target. Nothing restored.")
            seen.add(name)
            backup = transaction / "before" / name
            self._safe_path(backup, self.game)
            if not backup.is_file() or file_hash(backup) != file.get("before"):
                raise PatcherError("A backup is missing or damaged. Nothing restored.")
            if not self.paths[name].is_file() or file_hash(self.paths[name]) not in (file.get("before"), file.get("after")):
                raise PatcherError(f"{name} changed after installation. Restore will not overwrite later edits or game updates.")
        state["status"] = "Restoring"
        record = transaction / "transaction.json"
        write_json(record, state)
        try:
            for file in reversed(files):
                name = file["name"]
                if file_hash(self.paths[name]) == file["before"]:
                    continue
                self.progress("Restoring " + name + "…")
                self._replace(transaction / "before" / name, self.paths[name], file["after"], file["before"])
            state.update(status="Restored", restoredAt=now())
            write_json(record, state)
        except Exception as exc:
            state.update(status="RestoreFailed", error=str(exc))
            write_json(record, state)
            raise PatcherError("Restore stopped. Keep the backups and resolve the reported issue, then retry Restore: " + str(exc)) from exc
        return self._after_restore({"message": "Restored the exact pre-installation files. Start the game normally for its default graphics API. Any earlier patch or your own DX12 launch arguments remain your responsibility.", "changedFiles": [f["name"] for f in files]})

    @mutation_locked
    def launch(self) -> dict:
        self._validate()
        self._closed()
        if self.user != self.default_user:
            raise PatcherError("Launch is disabled for a custom test user-data folder.")
        active = self._active()
        if active and active[1]["status"] != "Installed":
            raise PatcherError("Restore the unfinished transaction before launching.")
        check = self.check()
        if not check["ready"]:
            raise PatcherError("The files are not prepared or borderless mode changed. Run Check and review the settings before launching.")
        subprocess.Popen([str(self.game / "Cities2.exe"), *LAUNCH_ARGS], cwd=self.game, close_fds=True)
        return {"message": "DX12 launch requested. Confirm Direct3D 12 and MultiThreaded in Player.log; keep display mode and frame latency unchanged for the first test."}
