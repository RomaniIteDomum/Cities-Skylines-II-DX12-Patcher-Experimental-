# Editing the patcher yourself

The Python source is the editable project. The packaged EXE is a snapshot made from that source.

## Local editing workflow

1. Open the source project folder in your text editor.
2. Edit a file and save it.
3. Close the editable patcher window if it is open, then double-click `Run Editable App.cmd` in the project folder.

The launcher uses this project's `.venv` environment, which is already prepared on the development machine. It opens the app without installing a patch or launching the game. A console stays available so a syntax error or exception is readable. Source changes take effect after restarting the app; it does not automatically reload them while running.

On another computer, create the source environment using the README first. You can also start the source directly from PowerShell in the project folder:

```powershell
.\.venv\Scripts\python.exe src\app.py
```

## Which file to edit

| File | Controls |
| --- | --- |
| `src/app.py` | Window title, labels, explanatory text, fonts, colours, sizes, layout and buttons. Search for `APP_TITLE`, `PatcherWindow` or the exact text visible in the interface. |
| `src/patcher.py` | Version label, DX12 launch arguments, compatibility classification, installation, backups and restore. Search for `VERSION` or `LAUNCH_ARGS`. |
| `src/asset_patcher.py` | The actual shader-data transformation and its integrity checks. |
| `README.md` and `docs/*.md` | Written instructions and release documentation. These are separate files, so editing the copies beside a packaged app does not require rebuilding the EXE. |

For example, change the title near the top of `src/app.py`:

```python
APP_TITLE = "My Experimental CS2 DX12 Patcher"
```

Save the file and restart the editable app. The changed title will appear. Keep the quotation marks and Python indentation intact.

Changing a label is independent of patching game data. If you change patching, backup or restore logic, run the tests on isolated fixtures before using that version on an installation.

## Sharing an edited version

Editing the source does not alter an EXE that was already built. Other users can run your source if they install its dependencies. For an updated standalone EXE, build it yourself once your edits are ready:

```powershell
.\.venv\Scripts\python.exe build_windows.py
.\.venv\Scripts\python.exe make_release.py
```

The app is placed under `dist/CS2-DX12-Patcher`; release ZIPs go under `dist/releases` by default. You do not need to rebuild while trying each individual source change. Rebuild when you want a new standalone release.

If you change the release version, keep `VERSION` in `src/patcher.py`, the release filename version in `make_release.py`, and the release notes consistent.
