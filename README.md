# Cities: Skylines II — Experimental DX12 Patcher

A small Windows utility that prepares your existing game files for an experimental DirectX 12 configuration. Choose `Cities2.exe`, check the installation, and apply or restore the changes from a simple window.

Preview version: **0.1.2-experimental**.

**Experimental:** this is an unofficial compatibility workaround, not a guaranteed crash fix or official DX12 support. A previous version of the same asset transformation completed one roughly 90-minute gameplay test on one PC. This new utility and its simplified launch arguments still need their own gameplay validation. See [testing status](docs/TESTING.md).

## Quick start

1. Extract the entire release archive to a writable folder and open `CS2-DX12-Patcher.exe`. Save and close Cities: Skylines II.
2. Browse to your `Cities2.exe` and select **Check**. Read the compatibility result. The verified reference is game **1.6.2f1**, using **Unity 2022.3.71f1**; that is not a promise that every installation with that version label has identical files.
3. Select **Install**. Keep the backup directory it creates. Installation also creates **Cities Skylines II - DX12 (Experimental)** on your Desktop. Start the game from that shortcut or select **Launch DX12** in the patcher.

**Use the DX12 shortcut for future launches.** Preparing the files alone does not select DX12 when the game is started through another launcher. If you prefer Steam or RHI, add `-force-d3d12` to that game's launch arguments yourself and keep borderless mode selected. The patcher does not change your Steam or RHI launch settings.

Already installed an earlier preview? With the game closed, select **Install** again to add the shortcut without repatching files that are already prepared. The shortcut points directly to the game, so it continues to work if the patcher's folder is moved or removed. Keep the game's backup folder for restoration.

The patcher resolves your Windows Desktop location, including a redirected Desktop. It does not overwrite unrelated shortcuts or claim ownership of an identical shortcut that already existed. If shortcut creation fails, the successful game patch remains installed and the result explains that you can use **Launch DX12** instead.

Use **Fullscreen Window / borderless** for the initial comparison. Leave display mode and Maximum Frame Latency unchanged during the first gameplay test. To undo this utility's installation, close the game and select **Restore**.

The patcher processes files already on your computer. The release does not need to contain game assets, shader bytecode, a game executable or another copy of the game. Source and dependency details belong in the same release as any packaged application.

## Run or build from source

Use 64-bit Windows with **Python 3.14, including Tkinter**, for the tested build environment. The source uses Python 3.11+ features, but other Python versions have not been tested here. A packaged application does not require a separate Python installation. From the source folder, create an isolated environment and install the locked dependencies:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe src\app.py
```

To build the Windows application:

```powershell
.\.venv\Scripts\python.exe build_windows.py
```

The runtime dependency is UnityPy 1.25.3; the build uses PyInstaller 6.20.0. `requirements-lock.txt` records the complete build environment; `requirements.txt` and `requirements-build.txt` identify the direct runtime and build dependencies. Running the patcher does not download game files. Creating the development environment downloads the declared Python dependencies.

## Compatibility

- **Known reference:** the original and patched asset hashes recorded for the tested 1.6.2f1 installation.
- **Unknown build:** the interface checks the supported file structure automatically and reports when a build differs from the tested reference. Installation may proceed if those checks pass, after the normal experimental-install confirmation. Structural validation does not establish runtime compatibility.
- **Format scope:** the implementation targets the supported Unity 2022.3 asset structure. A new game or engine version may need code changes, new validation and a fresh gameplay test.

Malformed or unsupported assets are still refused. For advanced command-line use, installing an unknown build still requires `--allow-unverified`; that option does not bypass structural checks.

Do not carry patched assets from an older game build into an updated installation. An update can overwrite the changes or alter the data they depend on. Check the updated installation again; never force old backups over new game files.

## What changes

| File | Change |
| --- | --- |
| `Cities2_Data/globalgamemanagers.assets` | Adds missing DX12-targeted copies of existing DX11 compute-shader variants. |
| `Cities2_Data/resources.assets` | Applies the same transformation to the compute shaders in this asset file. |
| `Cities2_Data/boot.config` | Sets `gfx-enable-gfx-jobs=0` and `gfx-enable-native-gfx-jobs=0`, preserving unrelated settings. |
| The current user's existing `launcher-settings.json` | Sets only `system.display_mode` to `borderless_fullscreen`, with a backup. If the file is absent, it is left absent. |

Original variants and existing native DX12 variants are preserved. Shader bytecode and binding metadata are copied from local data; the utility does not compile replacement shaders. It verifies the transformation before installation.

The graphics-job settings apply to this installation even when it is later started with DX11. In the reference test, they selected Unity's **MultiThreaded** rendering mode without graphics jobs. A separate render thread remained active; the game was not restricted to one CPU core.

**Launch DX12** uses:

```text
-force-d3d12 -timestamps -screen-fullscreen 1 -window-mode borderless
```

The earlier experiment included `-force-gfx-direct`, although the observed mode was not Direct. This utility omits that unproven flag. The resulting minimal argument set requires its own gameplay test; matching asset output alone does not validate the changed launch path.

This utility does not install or enable mods, OptiScaler, Neural Rendering, forced DLAA, Smooth Motion or ReShade. It does not change driver settings, hardware clocks or Windows timeout settings. The game's original UI renderer remains in use.

## Backups and verification

Installation preserves the affected files before changing them. **Restore returns files to their state before this utility's installation**, which can itself include an older patch. It is not a general reset of every game modification.

Backups are kept under `CS2-DX12-Experimental-Backups` inside the selected game folder. This directory belongs to this semantic patcher; backups from an older utility are separate.

Restore removes a Desktop shortcut only when the utility created that link and the link is unchanged. Cleanup follows successful game-file restoration, or handles a shortcut-only installation when there are no game-file changes to restore. Pre-existing or subsequently edited shortcuts are preserved. Custom user-data profiles used for isolated command-line tests do not create shortcuts on your real Desktop.

Keep the transaction record and backup directory. A later game update or manual edit can make restoration unsafe; the utility must refuse to overwrite an unexpected file rather than silently replace it with an old backup.

After launching, check `Player.log` in:

```text
%USERPROFILE%\AppData\LocalLow\Colossal Order\Cities Skylines II
```

Confirm that the renderer is **Direct3D 12** and the reported rendering mode matches the intended jobs-off configuration. A launch flag, loaded DLL or responsive process alone does not prove successful rendering or usable gameplay.

## Known limits and reports

The earlier diagnostic runs reported invalid graphics-resource states. Disabling graphics jobs improved the observed stability, but the transformation does not repair native resource barriers. A normal run without the DX12 debug layer cannot establish that those validation errors are gone.

The successful reference test had no enabled in-game mods or active OptiScaler proxy. It does not validate mod combinations, Neural Rendering or all fullscreen, Alt+Tab and frame-latency transitions.

For a failure report, include the game and Unity versions, patcher version, compatibility result, actual display mode and renderer, what happened, and how long the loaded city ran. Review logs for personal information before sharing. Use the repository's bug-report form when available.

See [release notes](docs/RELEASE_NOTES.md), [test coverage](docs/TESTING.md), and the [publishing checklist](docs/PUBLISHING.md).
