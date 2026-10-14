# TotemOps / 不死圖騰 — project agent entry

This repository is an Apache-2.0 Minecraft assistant, not a self-updating server manager.
**Source of truth:** this public repository is the current TotemOps project. Historical mc-server-ops code must not replace its CLI or safety gates. Do not publish, deploy or operate on someone else's server without the owner's explicit authorization.
**Canonical skill:** `.agents/skills/totem-ops/SKILL.md`.
**Chinese user manual:** `README.md`. **English:** `README.en.md`.

For authorized development of friends' public Minecraft repos, load `.agents/skills/minecraft-repo-maintainer/SKILL.md` on demand, then run `python3 tools/totem_operator.py maintainer profiles|inspect`. This is a read-only project-aware facade; do not use it as proof that a Gradle build or GUI client ran. Profiles are in `profiles/`.

For smaller/weaker models: prefer the read-only `totem-ops quick diagnose|inspect` and `totem-ops preflight` initially. When available, run agent Shell/file tools in a Hermes Docker backend or OpenClaw sandbox.mode=all session sandbox, with no host Docker socket or writable private world mount. Never call Docker directly to bypass a `BLOCK`. The CLI environmental gate is authoritative for sandbox execution, but not for arbitrary shell commands. Host approval and OS isolation are independent requirements.

When asked to diagnose, inspect, plan, deploy, or extend TotemOps:
1. Read the canonical skill on demand, then call `python3 tools/totem_operator.py --help` and the relevant CLI subcommand. Do not load all history documents.
2. Choose existing tools and opt-in plugins before writing a new downloader, profiler, mod solver or server manager.
3. Never confuse PLAN_ONLY/unit tests with successfully deploying or reproducing a Minecraft server.
4. No background mod upgrades; respect protected world/, kubejs/, private mods, player files. Only test real changes in user-authorized disposable sandbox.
5. For a requested extension, add a plugin under plugins/ with JSON I/O; keep core stable.
6. Run focused tests and report what passed, what was blocked and what is unverified. No push/publish without owner authorization.

Cloud fallback is opt-in **planning only**: use `python3 tools/totem_operator.py route server --providers examples/cloud-providers.example.json`. Never imply that a cloud sandbox was started from a `CLOUD_PREFLIGHT_REQUIRED` reply. Never upload private worlds, keys or player data. Pi uses the same canonical skill with `--skill`; its host bash must be disabled or sandboxed by the Pi runtime.

Project CLI: `python3 tools/totem_operator.py doctor`.
Do not require J1, ChatGPT, or any paid account to run the local CLI.
