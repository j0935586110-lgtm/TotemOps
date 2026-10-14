# TotemOps Windows NSIS isolated installation smoke test

This folder is **test-only**, not a playable Minecraft distribution.

The NSIS setup installs just two small files: `Launch-Test.cmd` and `README-QA.txt`, and creates `TotemOps-QA-Test.lnk` on the current user's desktop.

- No Minecraft, Java, mods, updater, credentials or server IP are included.
- No administrator privilege is requested (`RequestExecutionLevel user`).
- The shortcut points to the test-only command. Exit 0 means a simulated success; exit 7 means a deliberately simulated failure when `fail.flag` exists.
- The uninstaller removes the unique QA-named shortcut and only files inside `$LOCALAPPDATA\TotemOps-QA-Install-20261014`.
- The script fails closed when this test installation or shortcut already exists, to avoid overwriting anything.
- **This is not authorization to distribute a game's client, Microsoft login or third-party mods.** It is only proof that the Windows setup and shortcut lifecycle works.

## Build on Linux using open-source NSIS

The smoke test on 2026-10-14 extracted official Ubuntu `nsis` and `nsis-common` packages into an isolated `/tmp/totem-nsis-sandbox-20261014/bin`, without changing the system's installed packages. Build with:

```sh
cd installer/qa
NSISDIR=/tmp/totem-nsis-sandbox-20261014/bin/usr/share/nsis \
  /tmp/totem-nsis-sandbox-20261014/bin/usr/bin/makensis qa-setup.nsi
```

When NSIS is installed normally: `makensis qa-setup.nsi`.

Output `TotemOps-QA-Setup.exe` is a generated testing artifact; do not check the binary into Git or upload it as an official Minecraft setup.

## Acceptance

Use an isolated Windows test account/host:
1. Verify setup SHA-256 matches the built artifact.
2. Confirm neither `TotemOps-QA-Install-20261014` nor `TotemOps-QA-Test.lnk` already exists.
3. Run setup; independently check the target files and desktop shortcut.
4. Launch via shortcut; check success marker and exit 0.
5. Place `fail.flag` in test directory; check exit 7.
6. Uninstall; **wait for async NSIS cleanup**, then independently confirm the test directory and shortcut were removed.

On the real Windows 11 test host, first attempt marked premature removal checks as FAIL. A subsequent independent read showed cleanup eventually succeeded. A bounded wait was added and the complete run passed. See `evidence/WINDOWS_NSIS_SMOKE_20261014.md`.
