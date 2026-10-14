---
name: totem-ops
description: TotemOps 不死圖騰. Diagnose Minecraft crashes, inspect mods/modpacks, check dependencies, prepare Forge/NeoForge server plans, and use opt-in local plugins. For AGY, OpenCode, DSH, Hermes, OpenClaw, Codex, and Claude Code.
license: Apache-2.0
---

# TotemOps / 不死圖騰

**Start from this repo, not a guessed global installation.** This on-site TotemOps worktree is authoritative; `mc-server-ops` on GitHub is the early history and must never silently replace the current tools or workflow. Read only `README.md` (Chinese) or `README.en.md` (English) if commands below need explanation.

## First principle: reuse before writing new analyzers

Read docs/EXISTING_TOOL_REUSE.md only when the user wants Minecraft crash
diagnosis, mod versions, external log analysis, or Crash Assistant integration.
Use the already shipped modrinth-catalog plugin for official metadata.
Use local TotemOps or browser-only hints before any third-party upload.
mclo.gs POST /1/analyse is available only through opt-in mclogs-analyse plugin,
with explicit user consent to third-party processing of a reviewed log. Never
invent approval flags or silently upload private logs. Crash Assistant is
a client-side app/report, **not** a verified headless API. Do not try to operate
its UI or install it because someone pasted its URL.
Treat any upstream findings as suspected causes, never as sandbox or gameplay PASS.
No scheduled provider calls or automated issue/PR handling.

## Existing PR / official CI reuse gate

**Before developing any requested crash or feature patch**, inspect the
target's official releases, upstream Issue discussion, open **and merged
PRs**, published fixes and existing regression tests. Choose a compatible
upstream solution before creating a new implementation. A related open PR
is not a merged/released fix; record its version, commit and CI provenance.
First run the project's own CI setup tasks in a disposable worktree, then
verify the unmodified baseline and add failure-reproducing targeted tests.
Do not trust a generic green test suite to prove a specific bug was fixed.
A BUILD or upstream CI PASS is not GAMEPLAY_VERIFIED for a different Minecraft
version; require matching-version behavior testing before claiming a repair.
Use current Agent's Git/GitHub tools; do not install a separate crawler.
This is on demand only and creates no monitoring or Issue backlog.
The reproducible case is docs/UPSTREAM_REUSE_TRIAL_2472.md (Issue #2472,
upstream PR #3331, 1.21.1 baseline vs 26.2/JDK25 PR).

## AGY native Plugin install and reversible first use

The same repository contains AGY root `plugin.json` and the adapter Skill
`skills/totem-ops/SKILL.md`. Use AGY's built-in Plugin manager: install by
GitHub repository URL, verify with `agy plugin list --json`, and revert via
`agy plugin uninstall totem-ops`. Do not claim that merely pasting a URL
in every chat automatically triggers an install. See `docs/AGY_FIRST_RUN.md`.
For user-requested features, start from an upstream equivalent before
editing code; patch only a sandbox/authorized fork, test, give a reversible
diff and obtain separate permission before touching production.
REA is only an optional authorized investigator for unavailable source.

## CLI quick start
## CLI quick start

**Minecraft release helper:** `.agents/skills/minecraft-release/SKILL.md`; `python3 tools/totem_operator.py release inspect --pack PACK.zip [--update UPDATE.zip]`. Read-only packaging audit, owner approval required for any optional-mod policy or deletion; `REVIEW_REQUIRED` is not launch/install/approval PASS.

Optional friend-project development Skill: `.agents/skills/minecraft-repo-maintainer/SKILL.md` and `python3 tools/totem_operator.py maintainer profiles`. Use the existing AGY/OpenCode Agent for coding; the TotemOps facade performs deterministic read-only provenance/CI inspection. Never assume STATIC_ONLY means build/test passed.


- `python3 tools/totem_operator.py preflight --sandbox-root <marked/agy-sandbox>` — read-only host/resource gate; physical rootful Docker is eligible only via hardened restricted container; nested unknown rootful Docker stays BLOCK. This does **not** verify the Agent tool sandbox.
- `python3 tools/totem_operator.py quick diagnose <latest.log>` or `quick inspect <mods>` — tiny JSON for lower-capability models (top 3 findings), never raw log dump
- `python3 tools/totem_operator.py route stage|server --providers examples/cloud-providers.example.json` — local-first routing PLAN only, cloud disabled by default; do not send files or assume free quota exists
- `python3 tools/totem_operator.py --help`
- `python3 tools/totem_operator.py doctor` — inspect available tools
- `python3 tools/totem_operator.py inspect <mod.jar|mods-directory|modpack.mrpack>` — dependency and conflict hints from local metadata
- `python3 tools/totem_operator.py diagnose <latest.log>` — bounded logs, **suspected** causes only
- `python3 tools/totem_operator.py plan-deploy --version 1.21.1 --loader NEOFORGE --memory 8G` — draft, no deployment
- `python3 tools/totem_operator.py solve-and-verify --log <latest.log> --project <modrinth-slug> --game-version 1.21.1 --loader neoforge` — **PLAN_ONLY** by default
- Add `--version-id <exact-modrinth-version>` to pin the selected root mod. Add `--stage-only --execute-sandbox --sandbox-root <authorized/agy-sandbox>` to download and inspect required dependencies *without launching Java*, giving SHA-256 and pinned-image replay evidence. Add `--expected-receipt <prior-stage-json>` when rerunning: compare every staged filename and SHA-256 to the earlier artifact set; mismatch becomes `BLOCK/artifact_sha256_drift`. Status `STAGED_ONLY` is **not** a Minecraft server boot PASS.
- `python3 tools/totem_operator.py runtime-seed create --source <trusted-neo-data> --sandbox-root <marked/agy-sandbox> --seed-dir <marked/agy-sandbox/loader-seeds/neoforge-1.21.1-21.1.259> --game-version 1.21.1 --loader-version 21.1.259` — one-time sanitized loader cache, excludes world/mods/config.
- Add `--loader-version 21.1.259 --cold-baseline-seconds <measured-seconds>` to the on-demand full sandbox run to compare local runtime copy vs install, matching loader/image ID; real warm boot is **NOT YET VERIFIED**.
- `python3 tools/totem_operator.py cas stats --sandbox-root <marked/agy-sandbox>` — inspect persisted content-addressable blob usage; no daemon or database
- `python3 tools/totem_operator.py cas import --sandbox-root <marked/agy-sandbox> --source <sandbox/pack/mods> --receipt <stage-json>` — verify and deduplicate JARs under SHA-256 blobs, using an existing `STAGED_ONLY` receipt
- `python3 tools/totem_operator.py cas verify --sandbox-root <marked/agy-sandbox> --receipt <stage-json>` — rehash blobs; `cas restore ... --destination <empty/sandbox/mods>` independently copies files, fail-closed on hash mismatch
- Add explicit `--cas` to `solve-and-verify` for opt-in CAS lookup before download and CAS import after successful staging; cache does not prove loader compatibility or Minecraft E2E
- `python3 tools/totem_operator.py plugins list` — list local opt-in plugins
- `python3 tools/totem_operator.py plugins run modrinth-catalog search --input '{"query":"voice chat","game_version":"1.21.1","loader":"neoforge","limit":2}'` — on-demand official Modrinth **candidates**, NOT tested compatibility or an installation
- `python3 tools/totem_operator.py plugins run example-info about` — run a specifically requested trusted plugin

Linux/macOS shorthand: `./bin/totem-ops`; Windows: `bin\totem-ops.cmd`.

## Developer freedom / 插件自由

- Plugins are independent subfolders `plugins/<name>/` with `plugin.json` and an executable adapter (Python, Node, shell); JSON in/stdout out. No automatic invocation. User-owned plugins are **not sandboxed** by this CLI: they run with the invoking OS account's rights; install only trusted plugins.
- For extra capability use an adapter plugin instead of editing core. Keep language and runtime independence.
- The owner can edit local plans, tools, or plugins. The Agent should show real command output, not overclaim E2E correctness.

## Operational boundaries

- Read-only metadata by default. Never auto-update mods, run an untrusted JAR on the host, or silently publish to a friend's repository.
- Real `world/`, `kubejs/`, `config/`, private mods and player data are protected; only an explicitly authorized disposable sandbox may download/modify managed third-party dependencies.
- `solve-and-verify --execute-sandbox` requires explicit user action, a dedicated marked sandbox and preinstalled Docker image. Positive Minecraft status means only protocol readiness, not tested gameplay or full dependency compatibility.
- Unknown provenance/maintenance status is UNKNOWN, not discontinued. `required_not_in_supplied_set` is not proof a dependency is missing from a running server.
- Ask before modifying production or publishing. Back up user data for authorized change, never treat an arbitrary "approved" flag as permission.
- Return RESULT / EVIDENCE / BLOCKER / NEXT in Traditional Chinese if the user writes Chinese; otherwise match user language.

Only this `SKILL.md` is authoritative. `AGENTS.md`, `CLAUDE.md`, and localized READMEs are lightweight entrypoints. Never duplicate separate implementations per Agent.
