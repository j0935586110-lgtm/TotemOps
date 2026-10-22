---
name: totem-ops
description: Use for Minecraft Forge/NeoForge modpack checks, modsync-v2 publishing preflight, server crash logs, deterministic fix plans, and disposable server smoke checks. Run deterministic TotemOps CLI to obtain compact JSON before proposing a fix.
license: Apache-2.0
compatibility: Python 3.11+; an authorized existing disposable Docker test server is required only for smoke.
---

# TotemOps / 不死圖騰 — compact agent workflow

This file is the human-readable canonical workflow. Claude Code discovers `.claude/skills/totem-ops/SKILL.md`; Google Antigravity (agy) discovers `.agents/skills/totem-ops/SKILL.md`. **A root-level SKILL.md alone is not auto-discovery.**

## First response: do not read all source files

In the cloned TotemOps repository root, run exactly ONE matching diagnostic command:

- Modpack or modsync-v2 release: `./bin/totem-ops manifest PATH --json --summary`. For Barian's source folders `mods`, `clientmods`, `needmods`, pass the **publishing root** and add `--layout modsync-v2`.
- Server crash triage: `./bin/totem-ops crash LATEST.LOG --json` (short deterministic suspected causes; the log must already exist locally).
- Server crash fixplan: `./bin/totem-ops fixplan LATEST.LOG --json` (deterministic read-only repair recipes for 9 crash signals; exit 3 = PLAN_ONLY / NO_RECIPE / REVIEW_REQUIRED, no changes made).
- Existing disposable server boot: `./bin/totem-ops smoke SANDBOX/server/mods --side server --sandbox-root SANDBOX --container tot-e2e-TEST --minecraft 1.21.1 --neoforge 21.1.259 --json`. This **inspects only an already running isolated Docker server**, not a fresh server or client gameplay.

If a command is unavailable or the path is unknown, report it; do not make up machine access or results. Use `./bin/totem-ops <command> --help` for actual flags. The CLI is the source of diagnostics, not its own evidence of gameplay.

## Parse result and act safely

1. Parse **stdout as JSON**, collect exit code and tool error separately. For `manifest`/`smoke`: `2=BLOCK`, `3=REVIEW_REQUIRED`. For `fixplan`: `2=BLOCK`, `3=PLAN_ONLY` / `NO_RECIPE` / `REVIEW_REQUIRED` (neither executes any action; exit 0 is unused). **Exit 3 is an expected result, not success for publishing.** `crash` can exit 0 but all root causes remain suspected.
2. Read `status`, `reason`, `top_findings` or `clues`, `checks_not_run`, `release_allowed`. The report is evidence, not a repair instruction. Never treat `UNKNOWN` client/server classification as safe. No Java/Maven version solver or in-game join is implied.
3. Provide a brief **RESULT / EVIDENCE / BLOCKER / NEXT** report. Only when evidence needs drill-down, request full `manifest --json` and filter locally; do **not** paste hundreds of entries or raw player/server logs into the chat.
4. Agent may propose a patch and its tests. **Never modify production worlds, playerdata, kubejs/config, friend's repos, modsync API, or release assets without explicit owner authorization.** Use disposable worktrees and backups for authorized changes. Never bypass a BLOCK using an unrestricted shell command, auto-publish, or automatically upgrade mods.
5. If underlying program errors, explain the error and stop. Fail closed, do not invent a success receipt.

For rare advanced workflows only, consult `README.md`, `docs/MODSYNC_V2_PUBLISH_PREFLIGHT_20261015.md`, or `docs/SERVER_SMOKE_READONLY_20261015.md`.

No MCP server, model API, cloud billing, J1, or third-party Python dependency is required for the local CLI entrypoints (smoke uses an existing authorized Docker CLI/test container).
