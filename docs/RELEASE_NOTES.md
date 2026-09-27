# Release notes

## 0.1.2-experimental

Installation now prepares **Cities Skylines II - DX12 (Experimental)** on the Desktop and shows a clear reminder to use it or **Launch DX12**. The shortcut targets the game's executable directly with the existing DX12 arguments, working directory and game icon. It does not depend on the patcher's folder remaining in place.

Selecting Install on an already prepared game can add the shortcut without repeating the asset transformation. The utility resolves the actual Windows Desktop location, preserves unrelated links and does not take ownership of an identical link that already existed. A shortcut-creation failure produces a warning without rolling back a successful game installation; **Launch DX12** remains available.

After successful restoration, only an unchanged shortcut created by this utility is removed. Restore can also clean up an owned shortcut when there are no game-file changes to restore. Edited or pre-existing links are preserved. Isolated tests with a custom user-data directory do not touch the real Desktop.

Steam and RHI launch settings remain unchanged. Users who launch through them should add `-force-d3d12` themselves and retain borderless mode. The asset transformation and DX12 argument set are unchanged.

**Validation:** the source and packaged interface smoke checks passed at 175% scaling, and all 23 transaction/settings tests passed. Eight new cases cover shortcut ownership, isolation, already-prepared installations and nonfatal failure handling using a mocked helper.

The real Windows shortcut helper suite then passed 10 cases covering Unicode paths, stored launch properties, ownership, collisions and failure cleanup. One additional case was skipped because Windows denied symbolic-link creation privileges. All shortcut writes used temporary workspace Desktop folders; the actual Desktop was only resolved read-only, and no game was launched. The completed 0.1.1 and 0.1.0 results below remain prior evidence.

## 0.1.1-experimental

The interface is simpler: select the game, check it, then install or restore. The separate untested-build checkbox and the technical graphics-job status line have been removed, and the confirmation text is shorter.

The interface now runs the existing structural checks automatically for an unknown build. It still identifies the tested reference and displays unknown-build warnings, including when Install is selected directly; malformed or unsupported files are refused. The normal experimental-install confirmation remains. Advanced command-line installation retains the explicit `--allow-unverified` option.

The asset transformation, backups, restoration safeguards and launch arguments are unchanged. This change does not establish support for every game version.

**Validation:** the revised source and packaged interfaces passed smoke checks at 175% display scaling, with all four actions, status text and footer within the window. The removed graphics-job line is absent from Check output. All 15 transaction/settings tests passed for 0.1.1. These checks do not add a new full reference-asset or gameplay result; the 0.1.0 evidence below remains separate.

## 0.1.0-experimental

This preview replaces the earlier version-specific binary-delta delivery method with a local semantic asset transformation and a simple Windows interface. Preparing this project does not publish a release.

### Included

- Select `Cities2.exe`, then **Check**, **Install**, **Launch DX12** or **Restore**.
- Read local Unity assets and add missing DX12 aliases of existing DX11 compute-shader variants.
- Preserve original variants, existing DX12 variants and unrelated asset objects.
- Disable the two graphics-job boot settings and select borderless mode in an existing per-user launcher settings file, with backups.
- Distinguish a known reference installation from an unknown build, with structural checks and warnings rather than a universal compatibility claim.
- Keep game-derived assets and binary-delta payloads out of the release source and application archive.

### Evidence carried over from the earlier experiment

The verified reference was game 1.6.2f1 with Unity 2022.3.71f1. Its original transformation changed 106 compute-shader objects in `globalgamemanagers.assets` and 149 in `resources.assets`. Other objects and original variants were preserved.

One jobs-off DX12 run lasted **90 minutes 38 seconds after city loading**, completed nine autosaves, and ended with a user-confirmed manual exit. A later application of the earlier package reconstructed its expected asset hashes and boot settings correctly and launched the intended DX12 configuration.

These are separate observations: file reconstruction, successful startup and extended gameplay are different checks. They do not establish universal stability.

### Differences from the earlier experiment

- The installer now transforms each supported local asset rather than applying a fixed binary delta.
- The graphical interface, packaging and recovery paths are separate from the earlier package and have their own checks described below.
- The launcher omits the previous experiment's `-force-gfx-direct` flag. It uses `-force-d3d12 -timestamps -screen-fullscreen 1 -window-mode borderless`.
- Unrecognized builds may have different shaders, bindings, native plugins or runtime behavior even when their asset structure can be parsed.

No successful gameplay result for this new preview is implied until it is recorded in [TESTING.md](TESTING.md).

The new source utility has passed **28 automated tests with no skips**, including exact reconstruction of the reference assets, preservation of existing DX12 variants, transaction recovery and refusal of unsafe restore inputs.

The built Windows application then passed **11 additional checks** on isolated copies of the real reference files: dependency initialization, hidden interface/control bounds at 175% scaling, compatibility inspection, installation, prepared-state and repeat-install checks, protected restoration, custom-profile launch refusal and unknown-engine refusal. Both installed asset hashes matched the known outputs; restoration returned the files byte-for-byte. No game was launched by these tests.

The build includes Tcl/Tk script data explicitly, correcting a packaging omission found during initial testing with Python 3.14. The final executable passed its smoke tests after the correction. Clean-machine testing, complete manual UI interaction and gameplay using the minimal launch arguments remain outstanding; see [TESTING.md](TESTING.md).

### Known limitations

- Native resource-state errors seen with validation enabled have not been demonstrated to be repaired.
- The earlier stability result used no enabled in-game mods or active OptiScaler proxy.
- Forced DLAA, Neural Rendering, Smooth Motion and mod combinations are not certified by that test.
- Fullscreen transitions and Maximum Frame Latency changes need explicit regression tests.
- Game updates may invalidate compatibility or backups. Never restore an older build's files over updated files.
- Exact file hashes identify the reference files, not every official installation with the same displayed version.

This project should be labelled **experimental preview** until the stated coverage improves. It is not affiliated with or endorsed by the game's developers or publisher.
