# Testing status

This document distinguishes evidence from the earlier local experiment from tests of the new semantic patcher. A blank or pending result is not a pass. Update entries only with recorded results.

## Current version: 0.1.2-experimental

This version adds a direct-to-game Desktop shortcut after installation, including an already-prepared installation, and a clearer launch reminder. Its intended ownership policy preserves pre-existing or edited links. A shortcut failure must leave successfully patched game files intact, and isolated custom-profile tests must not write to the real Desktop.

The following checks passed for 0.1.2:

- Source and packaged interface smoke checks at 175% display scaling, with all four actions, status text and footer inside the tested window bounds. Bundled dependencies initialized successfully.
- All **23 transaction/settings tests** in 1.454 seconds, including eight new shortcut-integration cases: custom-profile isolation, ownership retained through repeat installation, unowned-link preservation, nonfatal shortcut failure, edited-link preservation, ownership-record write failure, an invalid ownership record, and adding/removing only a shortcut for an already prepared installation without altering its game files.

Those integration cases used a simulated default profile and a mocked shortcut helper. They did not write to the real Desktop and do not establish that Windows created a working link.

The final Windows shortcut helper suite ran **11 tests in 12.291 seconds: 10 passed and 1 was skipped**. Real Windows shortcut creation/readback verified Unicode paths, literal/quoted arguments, working directory and game icon. Tests also covered reuse without claiming ownership, unrelated file/directory collisions, modified-link preservation, wrong-target/path/configuration refusal and cleanup after injected creation/verification failures.

The skipped case required creating a symbolic link; Windows denied that privilege (`WinError 1314`). That collision case is not recorded as a pass. The default Desktop was resolved read-only, while every shortcut write used a temporary workspace Desktop. No game was launched. A full packaged install-to-shortcut gameplay workflow and clean-machine testing remain separate validation tasks.

## 0.1.1 — interface and transaction regression

The interface now automatically applies the existing structural checks to unknown builds, while retaining build classification, warnings and the normal installation confirmation. Internal check warnings are forwarded to installation progress even when Install is selected directly. The advanced CLI still requires `--allow-unverified` for unknown-build installation. Neither path bypasses malformed/unsupported-file checks.

The removed checkbox and graphics-job status text are interface changes; the asset transformation and transaction safeguards are unchanged. The following checks passed for 0.1.1:

- Source and packaged interface smoke checks at 175% display scaling. All four action buttons, the status area and footer fit within the tested window bounds.
- Check-output verification confirming that the graphics-job status line is absent.
- All 15 transaction/settings tests.

These are UI and transaction regression results, not a new complete reference-asset test or gameplay run. The detailed 0.1.0 history below is retained as separate evidence.

## Earlier experiment — established evidence

| Check | Result | Scope |
| --- | --- | --- |
| Original asset transformation | Passed | Reference 1.6.2f1 / Unity 2022.3.71f1: 106 + 149 compute-shader objects changed; original variants and other objects preserved. |
| Native DX12 startup | Observed | Unity reported its Direct3D 12 backend; native command-submission evidence was collected during diagnosis. |
| Jobs-off mode | Observed | MultiThreaded, with a separate rendering thread and graphics jobs disabled. |
| Extended ordinary gameplay | Passed one run | One PC; 90 minutes 38 seconds loaded-city time; nine autosaves; user-confirmed responsive gameplay and manual exit. |
| Earlier package reapplied | Passed file verification and startup | Exact patched assets, jobs-off boot settings and intended DX12 startup were verified. This is not a new extended-stability result. |
| Detailed DX12 validation | Unresolved errors | An earlier jobs-off diagnostic run still reported resource-state errors. |
| Mod / OptiScaler / NR combinations | Not established by baseline | The successful baseline had no enabled in-game mods or active OptiScaler proxy. |

## 0.1.0 — source validation

For **0.1.0-experimental**, **28 automated tests passed with no skips in 32.753 seconds** on Windows using Python 3.14. The real-asset tests used private reference fixtures, which are not distributed. Transaction tests used isolated synthetic installations and fault injection. They validate recovery logic without modifying or launching the actual game.

| Area | Result and scope |
| --- | --- |
| Reference reconstruction | Passed for both original assets: exact expected patched SHA-256 values and 106 + 149 changed compute-shader objects. Original files remained unchanged. |
| Structural preservation | Passed: unrelated object corruption and changed original variants are detected. A fixture containing a deliberately different existing DX12 variant preserved it exactly. |
| Repeated transformation | Passed: already prepared assets produce no duplicate variants or unnecessary output; repeated installation makes no extra backup. |
| Unsupported / malformed input | Passed: malformed variants, containers, truncated data, unsupported Unity version, absent compute shaders and uncovered shader types are refused. |
| Source changes and failed output | Passed: a source altered during preparation is detected before output is written; an output-write failure leaves the source unchanged. |
| Unknown-build opt-in | Passed at backend level: an unrecognized build without acknowledgement is refused before creating a backup. Structural validation remains independent. |
| Install / restore | Passed on isolated fixtures: all four target files install and restore byte-exactly. A staging failure leaves inputs unchanged. |
| Failure recovery | Passed: failure after the first replacement rolls completed changes back; an interrupted mixed-state transaction can be restored. |
| Unsafe restoration | Passed: a modified target, corrupted backup or changed engine identity is refused before any restoration. |
| Process and concurrency safeguards | Passed: a simulated running-game result prevents writes; a real second process holding the mutation mutex prevents concurrent installation. |
| Settings edits | Passed: UTF-8 BOM, line endings and unrelated values are preserved; missing boot flags are added; duplicate or unsupported boot values and duplicate JSON keys are refused. |
| Custom test profile | Passed: a custom user-data folder cannot be used to launch the real game. |
| Source dependency / interface smoke | Passed for 0.1.0: dependencies import and a hidden Tk window initializes with the real backend, four action buttons and its safe defaults. This is not a full interactive visual review. |

Tests can be run from the source folder:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Real-asset tests require a private fixture directory supplied through `CS2_TEST_ORIGINALS`. Without those local fixtures, those tests are skipped rather than treated as passes. Do not commit or distribute the fixtures.

## 0.1.0 — packaged Windows application

The built **CS2-DX12-Patcher.exe passed 11 additional checks** using isolated copies of the real reference files and separate test settings. No game was launched. These tests ran on the development PC; they are not a clean-machine or gameplay test.

| Packaged check | Result |
| --- | --- |
| Dependency self-test and hidden full interface | Passed. Bundled dependencies initialized, and interface/control bounds were checked at 175% display scaling. |
| Original compatibility check | Passed. The reference input was recognized. |
| Installation and prepared-state check | Passed. All four planned files were installed; both generated asset hashes matched the known outputs. |
| Repeat installation | Passed. The prepared installation produced a no-op. |
| Later edit / restoration | Passed. A later edit caused restore to refuse without partial changes; a valid restore returned the files byte-for-byte to their originals. |
| Custom user-data launch | Passed. Launch from a test profile was refused. |
| Unknown engine | Passed. Check reported the unknown engine; installation without acknowledgement was refused without patching. |

The Windows build explicitly includes the Tcl/Tk script data required by its bundled Python 3.14 runtime. This corrected a packaging omission exposed during the first executable smoke test. The final packaged checks above passed after that correction.

## Still to validate

- The packaged executable on a clean Windows machine without the development environment.
- Full manual interaction with progress/error dialogs. Hidden interface checks do not cover every real user interaction.
- Game and user settings on separate volumes; absent launcher-settings handling in an end-to-end transaction.
- Gameplay using this preview's minimal launch arguments, including actual renderer/mode, working UI and autosave completions.
- Display transitions, Alt+Tab and Maximum Frame Latency changes, recorded separately from ordinary gameplay.
- Additional official installations and GPUs. Successful structural checks do not establish runtime compatibility.

The earlier 90-minute gameplay result does not validate this new executable or its changed launch arguments.

## How to record a gameplay test

Record the patcher revision, exact game and Unity versions, known/unknown compatibility classification, install result, actual command line and the renderer/mode reported in `Player.log`. Note the display mode and whether mods, injectors or overlays were active.

Start elapsed gameplay time when the city finishes loading, not when the process starts. Record completed autosaves and verify that the camera and interface actually respond. Distinguish a normal exit, a hang that stays open, a forced termination and a self-closing crash.

Test the unmodified comparison and patched configuration with other variables held steady. Do not infer that a setting caused a failure merely because it changed near the same time. Keep ordinary gameplay tests separate from deliberate graphics-setting and display-mode transitions.

Preserve relevant logs before another launch overwrites them. Store private evidence outside the public source tree; publish only a redacted result summary. Avoid saving over an important city during an experimental test.

## Launch-path distinction

The older successful experiment included `-force-gfx-direct`, but the observed mode was MultiThreaded. This preview intentionally omits that flag. Therefore byte-identical asset reconstruction is necessary evidence for matching the transformation, but is not by itself evidence of equivalent launch behavior or gameplay stability.
