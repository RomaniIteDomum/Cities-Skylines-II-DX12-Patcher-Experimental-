# Publishing on GitHub

GitHub is the recommended home: keep readable source and issue reports in a public repository, and distribute the ready-to-run Windows ZIP through Releases.

## First release

1. Create a repository such as `cs2-dx12-patcher` and upload the contents of the source archive. The project uses the MIT license for its original code and documentation; dependency notices apply separately.
2. Create a release tagged `v0.1.2-experimental` and mark it as a **pre-release**. Use the text in `RELEASE_NOTES.md` as a starting point.
3. Attach the Windows application ZIP and its SHA-256 file. Link the source revision used for the build. Users should download the Windows ZIP, rather than GitHub's automatically generated source archive, unless they want to build it themselves.
4. Keep the README's quick start prominent, including the reminder to use the installed DX12 Desktop shortcut or Launch DX12. Enable Issues; the repository already includes a bug-report form.

Suggested description: **Experimental DX12 compatibility patcher for Cities: Skylines II. Applies changes locally with backups and restore. Windows / Unity 2022.3 format scope; compatibility and stability are not guaranteed.**

The release contains application code and runtime dependencies. Game assets, shader bytecode, executable files from the game, the earlier binary-delta payloads, saves and private diagnostic logs must stay out of the repository and download.

The current package was built and tested locally. Before advertising broad support, test the portable ZIP on clean Windows and record a gameplay run with this utility's actual launch arguments. The reference files came from one manual installation; matching version text does not establish that all official installations have the same files. See `TESTING.md` for the precise evidence.

## Game updates

An update may overwrite the patch or make it unnecessary. The semantic patcher uses each new installation's own assets, but a changed layout or runtime behavior can still require code changes and a new release. The interface automatically checks an unknown build's supported structure and retains its warning; that is not a compatibility guarantee. Advanced CLI installation still requires `--allow-unverified` for an unknown build.

Inspect the updated installation, check that intended changes are preserved, and repeat install/restore and gameplay tests before adding a support claim. Never restore an older build's assets over an updated game.

## Useful issue reports

Request game and Unity versions, patcher version, Check results, display mode, active mods/injectors, the last action before failure and relevant log excerpts. Ask people to remove personal paths and account identifiers. Do not request whole game folders, asset uploads or memory dumps through the public issue form.

Keep ordinary-play stability results separate from Alt+Tab, display-mode and Maximum Frame Latency tests. Preserve evidence of failures before another launch overwrites the logs.
