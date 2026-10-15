# TotemOps minimal Agent Skills — 2026-10-15

## Scope

Decision: **use Skills plus the existing 3 CLI commands, no MCP server yet.**

Root `SKILL.md` is the human-readable canonical workflow, **not an auto-discovered skill by itself**. Compatible discovery entrypoints in this repository:

- Claude Code: `.claude/skills/totem-ops/SKILL.md`
- Google Antigravity / AGY: `.agents/skills/totem-ops/SKILL.md`

Each has a YAML `name`/`description` header and a tiny reference to the root; `AGENTS.md` and `CLAUDE.md` are short auto-read bootstraps. Whether a skill activates for an individual task depends on each host's discovery, task relevance, trust/permission settings and project checkout. A pasted GitHub URL in a generic chat is **not** a guaranteed repository mount or authorized shell.

## Measured, not promised

Read on the J1 development worktree, not from an LLM estimate:

- Prior AGY `.agents/skills/totem-ops/SKILL.md`: **8,427 bytes**.
- Short AGY / Claude discovery entry: **753 bytes each**; canonical root workflow **3,254 bytes**, only read when relevant.
- Synthetic **80 valid NeoForge JARs**: `manifest --json` stdout **31,927 bytes**; `manifest --json --summary` stdout **571 bytes**: **98.21% fewer stdout bytes**. Both return **REVIEW_REQUIRED / exit 3**; both remain non-publishable. `--summary` returns counts, up to three finding kinds and rejection reasons, not hundreds of JAR records, with the SHA-256 of the full JSON for integrity cross-reference.
- Byte savings indicate smaller material potentially injected into Agent context; **not a measured total token reduction** across Claude/AGY models. Host prompts, retries, cache behavior and later drill-down can change totals.

## Safety and deployment

A skill is a workflow hint, not execution authorization or an OS sandbox. The default diagnostic is read-only. The Agent may offer a fix, but must obtain owner approval and use a separate authorized test sandbox. Static manifests or existing-server boot reports cannot prove mod gameplay, publishing eligibility or client/server Java class compatibility.

The repository still needs to be cloned/opened in each Agent workspace; only the two standard discovery paths are auto-load candidates. The three commands are ordinary CLI invocations and do not depend on installing any MCP server or paid model.

No external GitHub push, automatic user installation or real-world production mutation was performed by this skill-only change.
