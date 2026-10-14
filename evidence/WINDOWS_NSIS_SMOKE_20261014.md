# Windows 11 NSIS / Desktop shortcut smoke test — 2026-10-14

## Scope

**TEST-ONLY** Windows installer; no game assets, no Java, no real updater, no Microsoft authentication or production server access. Executed on authorized `desktop-jne4fna-bdb6` Win11 using signed J1 shell, not editing a friend's system or world.

Source files: `installer/qa/qa-setup.nsi`, `Launch-Test.cmd`, `README-QA.txt`.

Build: Ubuntu 24.04 isolated NSIS 3.09 (extracted from Ubuntu packages into `/tmp/totem-nsis-sandbox-20261014`, without system-wide installation). PE32 Windows Setup.exe 102248 bytes, SHA-256 `ac88ca97e3472cb1cc4e4a65325c184837335e29ebd4b9f87cd842bd94382dc2`.

Transferred to the pre-existing isolated Windows test downloads directory:
`C:\TotemOps-Test-20261014\downloads\TotemOps-QA-Setup.exe`; SHA-256 checked again on Windows before execution.

## First attempt and honest failure analysis

A PowerShell `.ps1` test harness was blocked by Windows Execution Policy (UnauthorizedAccess). **No Execution Policy change or bypass was attempted**. Switched to a native `.cmd` harness.

First CMD run:
```text
HASH=PASS
SETUP_EXIT=0
SHORTCUT_CREATED=PASS
LAUNCHER_STUB_INSTALLED=PASS
SHORTCUT_INVOKED=PASS
SUCCESS_EXIT=0
FAILURE_EXIT=7
UNINSTALL_EXIT=0
SHORTCUT_REMOVED=FAIL
TEST_DIR_REMOVED=FAIL
QA_OVERALL=FAIL
```
Independent later readback confirmed both had already disappeared. The asynchronous NSIS uninstaller did cleanup after its initial process exit; first check was too early. Corrected harness to wait a bounded time for both paths to become absent.

## Final full rerun

Executed `cmd.exe /d /c "C:\TotemOps-Test-20261014\downloads\TotemOps-QA-Run.cmd"` with no system policy adjustments:

```text
QA_INSTALL_ONLY=TRUE
MINECRAFT_LAUNCHED=FALSE
HASH=PASS
SETUP_EXIT=0
SHORTCUT_CREATED=PASS
LAUNCHER_STUB_INSTALLED=PASS
SHORTCUT_INVOKED=PASS
SUCCESS_EXIT=0
FAILURE_EXIT=7
UNINSTALL_EXIT=0
SHORTCUT_REMOVED=PASS
TEST_DIR_REMOVED=PASS
QA_OVERALL=PASS
```

Everything was confined to the test installer directory / unique QA desktop shortcut; the installed test objects were removed. Existing PCL/MC8 directories were not touched.

## Not demonstrated

- Installation of HMCL, Minecraft, Forge/NeoForge, Java or mods.
- Safe automatic update on any friend's actual HTTP/HTTPS source, signature validation of downloaded JAR bytes, fail-closed behavior of a **real** game's launcher.
- Game login, playable game client, automatic server join, signed Windows SmartScreen reputation.
- Real players or distribution rights.

Next full product test must wait for a legally distributable launcher and trusted published update endpoint, use a disposable Win11 game instance, then assert the real post-conditions separately.
