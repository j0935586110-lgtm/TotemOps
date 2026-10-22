---
name: totem-ops
description: Diagnose Forge/NeoForge modpacks, modsync-v2 risks, crash logs, fixplan recipes, closure, triage verdict, packindex, and server smoke with TotemOps compact CLI JSON.
license: Apache-2.0
---

# TotemOps skill entry

Read root `SKILL.md` (`../../../SKILL.md`), then call `./bin/totem-ops` from repo root. Root is canonical and short. Do not read the entire repo or create MCP servers.
- `triage PATH [--log LOG] [--side …] [--json]` — single verdict for closure & fixplan; `0=PASS` only means declared metadata is consistent, never claim fixed/ready to boot; without `--log` do not imply log analysis.

Treat BLOCK as refusal and REVIEW_REQUIRED/PLAN_ONLY as **unapproved / no action executed**. Never modify user worlds, configs, or publish without explicit authorization. Never treat closure or triage PASS as runtime boot proof; never skip `actions` to tell user to reinstall; unresolved_ranges are not satisfied.

Before writing patches, check upstream fixes and PR evidence with regression baseline (docs/UPSTREAM_REUSE_TRIAL_2472.md). Sandbox startup is not GAMEPLAY_VERIFIED; never claim it without client proof.
