# TotemOps alpha release — scope and limits

**Release:** v0.1.0-alpha.1 (2026-10-14). Experimental tool for developers and Minecraft server owners.

### Available

- Local read-only diagnosis of logs, mod JAR metadata and modpacks.
- Optional, explicitly invoked plugins and low-token summaries.
- Bounded, owner-authorized disposable sandbox experiments and machine-readable acceptance evidence.
- Release review and signed-manifest checks; these do **not** themselves download or launch a game.

### Not proven or not supported

- Autonomous repair of arbitrary Minecraft crashes or arbitrary mod combinations.
- Production-world deployment and dependable world rollback.
- Game client installation, Microsoft login, actual Prism launches, or a real playable Setup.exe.
- Complete hard isolation of unknown plugins (plugin capability declarations are not a sandbox).
- End-to-end tests for every Agent or every friend's mod.

### Evidence labels

- One Waystones/Balm missing-dependency repair passed real NeoForge **protocol-readiness** verification, not in-game gameplay testing.
- Five other failure categories passed **synthetic-log classification** tests, not Java end-to-end repairs.
- The NSIS script under `installer/qa/` is explicitly QA-only.
- Published log metadata may have infrastructure paths or IPs redacted. Redacted public receipts are not byte-for-byte identical to original private receipts retained by the maintainer.

### Legal

This unofficial community project is not endorsed by Mojang Studios or Microsoft. Minecraft assets, third-party mods and external tools are **not** relicensed or redistributed by Apache-2.0. See `LICENSE`, `NOTICE`, `SECURITY.md` and `CONTRIBUTING.md`.
