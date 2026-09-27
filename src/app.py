"""Desktop interface and JSON command line for the experimental CS2 DX12 patcher."""

from __future__ import annotations

import argparse
import importlib
import json
import os
from pathlib import Path
import queue
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any

from patcher import Backend, PatcherError, VERSION


APP_TITLE = "Cities: Skylines II — Experimental DX12 Patcher"


def _game_path(value: str) -> Path:
    cleaned = value.strip().strip('"')
    if not cleaned:
        raise PatcherError("Choose Cities2.exe or enter its game folder first.")
    selected = Path(os.path.expandvars(cleaned)).expanduser()
    if selected.name.lower() == "cities2.exe":
        selected = selected.parent
    return selected.resolve()


def _yes_no(value: Any, *, unknown: str = "Not reported") -> str:
    if value is None:
        return unknown
    return "Yes" if value else "No"


def _friendly_check(result: dict[str, Any]) -> list[str]:
    lines = [str(result.get("message") or "Check completed."), ""]
    lines.append("Recognized tested build: " + _yes_no(result.get("knownBuild")))
    lines.append("Ready for the patcher's DX12 launch: " + _yes_no(result.get("ready")))
    display = result.get("displayMode")
    if display:
        lines.append("Saved display mode: " + str(display).replace("_", " "))
    assets = result.get("assets") or []
    if assets:
        lines.extend(["", "Game assets:"])
        for asset in assets:
            if isinstance(asset, dict):
                name = asset.get("name") or asset.get("file") or asset.get("path") or "Asset file"
                status = asset.get("status") or asset.get("state")
                if status is None and "patched" in asset:
                    status = "Patch present" if asset["patched"] else "Original / not patched"
                lines.append("  " + Path(str(name)).name + (": " + str(status) if status else ""))
            else:
                lines.append("  " + str(asset))
    warnings = result.get("warnings") or []
    if isinstance(warnings, str):
        warnings = [warnings]
    if warnings:
        lines.extend(["", "Things to review:"])
        lines.extend("  • " + str(warning) for warning in warnings)
    return lines


class PatcherWindow:
    def __init__(self, root: tk.Tk, initial_game: str = "") -> None:
        self.root = root
        self.busy = False
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.controls: list[ttk.Widget] = []
        self.action_buttons: dict[str, ttk.Button] = {}
        self.game = tk.StringVar(value=initial_game)
        self.status = tk.StringVar(value="Choose your game, then click Check.")
        self.poll_id: str | None = None

        root.title(APP_TITLE)
        root.protocol("WM_DELETE_WINDOW", self.close)
        style = ttk.Style(root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Title.TLabel", font=("Segoe UI", 19, "bold"))
        style.configure("Subtitle.TLabel", font=("Segoe UI", 10))
        style.configure("Step.TLabel", font=("Segoe UI", 10))
        style.configure("Status.TLabel", font=("Segoe UI", 10, "bold"))
        root.option_add("*Font", ("Segoe UI", 10))
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)

        outer = ttk.Frame(root, padding=24)
        self.outer = outer
        outer.grid(row=0, column=0, sticky="nsew")
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(6, weight=1)
        ttk.Label(outer, text="Cities: Skylines II", style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(outer, text="Experimental DX12 patcher  ·  " + VERSION, style="Subtitle.TLabel").grid(
            row=1, column=0, sticky="w", pady=(2, 15)
        )

        banner = tk.Label(
            outer,
            text="EXPERIMENTAL  •  Unofficial compatibility patch. Stability is not guaranteed.\n"
            "Keep a separate copy of important saves. Restore is available for this tool's changes.",
            anchor="w", justify="left", background="#FFF3CD", foreground="#674C00",
            padx=13, pady=11, wraplength=770,
        )
        banner.grid(row=2, column=0, sticky="ew", pady=(0, 15))

        steps = ttk.Label(
            outer, style="Step.TLabel", justify="left", wraplength=790,
            text="1. Close the game and select Cities2.exe.   2. Check the installation.\n"
            "3. Install the patch.   4. Play using the new DX12 desktop shortcut.",
        )
        steps.grid(row=3, column=0, sticky="ew", pady=(0, 14))

        chooser = ttk.LabelFrame(outer, text="Game location", padding=12)
        chooser.grid(row=4, column=0, sticky="ew")
        chooser.columnconfigure(0, weight=1)
        self.path_entry = ttk.Entry(chooser, textvariable=self.game)
        self.path_entry.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        browse = ttk.Button(chooser, text="Browse…", command=self.browse)
        browse.grid(row=0, column=1)
        ttk.Label(chooser, text="Select Cities2.exe, or paste the folder containing it.").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(7, 0)
        )
        self.controls.extend([self.path_entry, browse])

        actions = ttk.Frame(outer)
        actions.grid(row=5, column=0, sticky="ew", pady=(14, 14))
        for column, (action, label) in enumerate(
            [("check", "Check"), ("install", "Install"),
             ("launch", "Launch DX12"), ("restore", "Restore")]
        ):
            actions.columnconfigure(column, weight=1)
            button = ttk.Button(actions, text=label, command=lambda a=action: self.start(a))
            button.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 8, 0))
            self.action_buttons[action] = button
            self.controls.append(button)

        details = ttk.LabelFrame(outer, text="Progress and details", padding=8)
        details.grid(row=6, column=0, sticky="nsew")
        details.rowconfigure(0, weight=1)
        details.columnconfigure(0, weight=1)
        self.log = tk.Text(
            details, height=11, width=70, wrap="word", state="disabled",
            relief="flat", background="#FAFAFA", foreground="#202020",
            font=("Segoe UI", 10), padx=9, pady=8,
        )
        self.log.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(details, orient="vertical", command=self.log.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scrollbar.set)

        self.progress = ttk.Progressbar(outer, mode="indeterminate")
        self.progress.grid(row=7, column=0, sticky="ew", pady=(12, 7))
        status = ttk.Label(outer, textvariable=self.status, style="Status.TLabel", wraplength=790)
        self.status_label = status
        status.grid(row=8, column=0, sticky="ew")
        footer = ttk.Label(
            outer, text="Use the DX12 desktop shortcut or Launch DX12. For Steam or another launcher, add -force-d3d12 to its launch arguments.",
            wraplength=790,
        )
        footer.grid(row=9, column=0, sticky="ew", pady=(10, 0))
        self.footer = footer
        wrapped_labels = (banner, steps, status, footer)

        def resize_text(event: tk.Event[Any]) -> None:
            width = max(200, event.width - 76)
            for label in wrapped_labels:
                label.configure(wraplength=width)

        outer.bind("<Configure>", resize_text)
        self.append("Nothing has been changed. Check inspects the installation without changing game files.")
        self._fit_window(wrapped_labels)
        self.poll_id = root.after(80, self.poll)

    def _fit_window(self, wrapped_labels: tuple[tk.Widget, ...]) -> None:
        """Fit point-sized text at the current DPI before the window is shown."""
        scale = max(1.0, self.root.winfo_fpixels("1i") / 96.0)
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        if os.name == "nt":
            try:
                import ctypes
                from ctypes import wintypes
                area = wintypes.RECT()
                if ctypes.windll.user32.SystemParametersInfoW(48, 0, ctypes.byref(area), 0):
                    screen_width = area.right - area.left
                    screen_height = area.bottom - area.top
            except (AttributeError, OSError):
                pass
        available_width = max(400, screen_width - round(48 * scale))
        available_height = max(400, screen_height - round(64 * scale))
        width = min(round(880 * scale), available_width)
        for label in wrapped_labels:
            label.configure(wraplength=max(200, width - 76))
        self.root.update_idletasks()
        if self.root.winfo_reqheight() > available_height:
            self.log.configure(height=4)
            self.root.update_idletasks()
        height = min(max(round(670 * scale), self.root.winfo_reqheight()), available_height)
        self.window_size = (width, height)
        self.root.geometry(f"{width}x{height}")
        self.root.minsize(width, min(height, self.root.winfo_reqheight()))

    def append(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", str(text) + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def browse(self) -> None:
        choice = filedialog.askopenfilename(
            parent=self.root, title="Select your Cities: Skylines II executable",
            filetypes=[("Cities: Skylines II", "Cities2.exe"), ("Executable files", "*.exe")],
        )
        if choice:
            self.game.set(str(_game_path(choice)))
            self.status.set("Game selected. Click Check to inspect it.")

    def set_busy(self, active: bool) -> None:
        self.busy = active
        for control in self.controls:
            control.configure(state="disabled" if active else "normal")
        if active:
            self.progress.start(12)
        else:
            self.progress.stop()

    def start(self, action: str) -> None:
        if self.busy:
            return
        try:
            game = _game_path(self.game.get())
        except (PatcherError, OSError, ValueError) as error:
            messagebox.showerror("Choose the game", str(error), parent=self.root)
            return
        if action == "install":
            consent = messagebox.askokcancel(
                "Review the experimental changes",
                "Install the experimental DX12 setup in:\n" + str(game) + "\n\n"
                "The tool will check your game files, back up the files it changes, "
                "prepare the game for DX12 in borderless mode, and create a DX12 desktop shortcut.\n\n"
                "This is a workaround, not an official game update. Close Cities: Skylines II "
                "before continuing. Your city saves will not be edited.\n\n"
                "Continue with installation?",
                parent=self.root, icon="warning", default="cancel",
            )
            if not consent:
                return
        elif action == "restore":
            consent = messagebox.askokcancel(
                "Restore the backed-up configuration",
                "Restore the originals backed up by this tool for:\n" + str(game) + "\n\n"
                "This restores the files and settings backed up by this tool. "
                "It also removes its unchanged DX12 desktop shortcut. "
                "Close Cities: Skylines II first. City saves are not edited.\n\n"
                "Continue with restoration?",
                parent=self.root, icon="warning", default="cancel",
            )
            if not consent:
                return
        self.game.set(str(game))
        self.set_busy(True)
        titles = {"check": "Checking installation…", "install": "Installing…",
                  "restore": "Restoring…", "launch": "Preparing DX12 launch…"}
        self.status.set(titles[action])
        self.append("\n" + titles[action])

        def work() -> None:
            try:
                backend = Backend(game, progress=lambda text: self.events.put(("log", str(text))))
                if action == "install":
                    # The normal experimental-install confirmation covers the
                    # local transformation. Supported-format checks still run;
                    # users do not need to select an engine/version option.
                    result = backend.install(allow_unverified=True)
                else:
                    result = getattr(backend, action)()
                self.events.put(("result", (action, result)))
            except Exception as error:
                self.events.put(("error", str(error) or type(error).__name__))
            finally:
                self.events.put(("idle", None))

        threading.Thread(target=work, name="CS2PatcherWorker", daemon=False).start()

    def poll(self) -> None:
        try:
            while True:
                kind, data = self.events.get_nowait()
                if kind == "log":
                    self.append(data)
                elif kind == "result":
                    action, result = data
                    if action == "check":
                        for line in _friendly_check(result):
                            self.append(line)
                        self.status.set("Check complete. Review the details above.")
                    else:
                        message = str(result.get("message") or "Completed.")
                        self.append(message)
                        self.status.set(message)
                        if action == "install":
                            self.append("To play in DX12, use the DX12 desktop shortcut or Launch DX12. Other launchers need -force-d3d12 in their launch arguments.")
                        warnings = result.get("warnings") or []
                        if isinstance(warnings, str):
                            warnings = [warnings]
                        for warning in warnings:
                            self.append("Review: " + str(warning))
                elif kind == "error":
                    self.append("Could not complete the action: " + data)
                    self.status.set("Action stopped. Review the details above.")
                    messagebox.showerror("Action could not be completed", data, parent=self.root)
                elif kind == "idle":
                    self.set_busy(False)
        except queue.Empty:
            pass
        self.poll_id = self.root.after(80, self.poll)

    def close(self) -> None:
        if self.busy:
            messagebox.showinfo(
                "Please let the current action finish",
                "The current action is still running. Keep this window open until it finishes "
                "so file changes and backups can complete safely.", parent=self.root,
            )
            return
        if self.poll_id is not None:
            self.root.after_cancel(self.poll_id)
        self.root.destroy()


def _enable_dpi_awareness() -> None:
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass


def _self_test(*, full_ui: bool) -> dict[str, Any]:
    dependencies: dict[str, str] = {}
    for module_name in ("UnityPy", "lz4.block", "brotli", "texture2ddecoder"):
        module = importlib.import_module(module_name)
        dependencies[module_name] = str(getattr(module, "__version__", "import OK"))
    _enable_dpi_awareness()
    root = tk.Tk()
    root.withdraw()
    try:
        dependencies["Tk"] = str(root.tk.call("info", "patchlevel"))
        result: dict[str, Any] = {"ok": True, "dependencies": dependencies,
                                  "message": "Dependencies and hidden Tk window checked. No game files were accessed."}
        if full_ui:
            window = PatcherWindow(root)
            root.update_idletasks()
            if set(window.action_buttons) != {"check", "install", "launch", "restore"}:
                raise RuntimeError("The interface is missing an action button.")
            if window.busy:
                raise RuntimeError("The interface did not start in its safe default state.")
            if any(str(button.cget("state")) == "disabled" for button in window.action_buttons.values()):
                raise RuntimeError("The interface actions are unexpectedly disabled.")
            result["buttons"] = {action: button.cget("text") for action, button in window.action_buttons.items()}
            width, height = window.window_size
            # A withdrawn top-level does not allocate its grid. Give its child
            # frame the same explicit space so layout is checked without mapping
            # a visible window or taking focus from another application.
            window.outer.grid_forget()
            window.outer.place(x=0, y=0, width=width, height=height)
            root.update_idletasks()
            checked = list(window.action_buttons.values()) + [window.status_label, window.footer]
            for widget in checked:
                x, y = 0, 0
                parent: tk.Widget = widget
                while parent is not window.outer:
                    x += parent.winfo_x()
                    y += parent.winfo_y()
                    parent = parent.master
                if (x < 0 or y < 0 or x + widget.winfo_width() > width
                        or y + widget.winfo_height() > height
                        or widget.winfo_width() < widget.winfo_reqwidth()
                        or widget.winfo_height() < widget.winfo_reqheight()):
                    raise RuntimeError("An action, status message or footer would be clipped at this display scale.")
            result["layout"] = {"windowWidth": width, "windowHeight": height,
                                "screenWidth": root.winfo_screenwidth(), "screenHeight": root.winfo_screenheight(),
                                "tkScaling": float(root.tk.call("tk", "scaling")),
                                "actionsStatusFooterWithinBounds": True}
            result["message"] = "Hidden interface and safe defaults checked. No game files were accessed."
            if window.poll_id:
                root.after_cancel(window.poll_id)
        return result
    finally:
        root.destroy()


def _write_json(payload: dict[str, Any], output: str | None) -> None:
    rendered = json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n"
    if output:
        target = Path(output).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                             prefix=target.name + ".", suffix=".tmp", delete=False) as stream:
                temporary = stream.name
                stream.write(rendered)
            os.replace(temporary, target)
        finally:
            if temporary is not None and os.path.exists(temporary):
                os.unlink(temporary)
    if sys.stdout is not None:
        try:
            sys.stdout.write(rendered)
            sys.stdout.flush()
        except (OSError, UnicodeError):
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=APP_TITLE)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--action", choices=("check", "install", "restore", "launch"))
    mode.add_argument("--self-test", action="store_true", help="Check packaged dependencies and Tk; do not access a game")
    mode.add_argument("--ui-smoke", action="store_true", help="Build and inspect a hidden interface; do not access a game")
    parser.add_argument("--game", metavar="PATH", help="Game folder or Cities2.exe")
    parser.add_argument("--user-data", metavar="PATH", help="Explicit user-data folder for check/install/restore only")
    parser.add_argument("--allow-unverified", action="store_true", help="Allow an untested Unity 2022.3 build during install")
    parser.add_argument("--output", metavar="PATH", help="Write a JSON result file (also works in a windowed executable)")
    args = parser.parse_args(argv)
    if args.action or args.self_test or args.ui_smoke:
        try:
            if args.self_test or args.ui_smoke:
                result = _self_test(full_ui=args.ui_smoke)
            else:
                if not args.game:
                    raise PatcherError("--game is required with --action.")
                if args.action == "launch" and args.user_data:
                    raise PatcherError("Launch uses the game's real user-data location. Do not pass --user-data for a production launch.")
                logs: list[str] = []
                backend = Backend(_game_path(args.game),
                                  user_data=Path(args.user_data).expanduser().resolve() if args.user_data else None,
                                  progress=logs.append)
                if args.action == "install":
                    result = backend.install(allow_unverified=args.allow_unverified)
                else:
                    result = getattr(backend, args.action)()
                result = {**result, "ok": True, "action": args.action, "progress": logs}
            _write_json(result, args.output)
            return 0
        except Exception as error:
            payload = {"ok": False, "action": args.action, "message": str(error), "errorType": type(error).__name__}
            try:
                _write_json(payload, args.output)
            except OSError:
                if sys.stderr is not None:
                    sys.stderr.write(json.dumps(payload, default=str) + "\n")
            return 1
    if args.user_data or args.allow_unverified or args.output:
        parser.error("--user-data, --allow-unverified, and --output require --action or a self-test mode.")
    _enable_dpi_awareness()
    root = tk.Tk()
    root.withdraw()
    PatcherWindow(root, initial_game=args.game or "")
    root.deiconify()
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
