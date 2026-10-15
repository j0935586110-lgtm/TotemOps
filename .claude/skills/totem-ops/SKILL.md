---
name: totem-ops
description: Diagnose Minecraft Forge/NeoForge modpack problems, modsync-v2 update release risks, server crash logs, and isolated server startup with TotemOps compact CLI JSON. Load before attempting to modify Minecraft mods or worlds.
license: Apache-2.0
---

# TotemOps skill entry

Read the repository root `SKILL.md` (relative to this file: `../../../SKILL.md`), then call the matching `./bin/totem-ops` command from the repository root. The root document is canonical and deliberately short. Do not read the entire repo, load all docs, or create an MCP server.

Treat BLOCK as refusal and REVIEW_REQUIRED as **not approved**. Never modify user worlds, player files, configs, or publish a modpack without explicit authorization.

Before writing any repair patch, compare released upstream fixes and existing Issue / PR evidence and record the regression baseline. See docs/UPSTREAM_REUSE_TRIAL_2472.md. A unit test or sandbox startup is not GAMEPLAY_VERIFIED; never claim GAMEPLAY_VERIFIED without the actual client interaction evidence.
