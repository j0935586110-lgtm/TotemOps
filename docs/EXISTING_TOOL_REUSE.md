# TotemOps — reuse before rebuilding Minecraft tooling

**Status:** Opt-in tool reuse, not an autonomous live-server repair service.

Goal: let an existing AI Agent reuse community tools to answer "What failed, what
should I check, and was the proposed fix actually tested?" Keep TotemOps'
independent evidence, authorization and disposable-sandbox gates. Do not create
a second general crash parser, Modrinth index, launcher, LLM harness, cloud
account, or routine support workflow.

## Decision table

| Situation | Prefer | Data handling and evidence |
| --- | --- | --- |
| Player supplies a mclo.gs URL | Agent reads the supplied link if browsing is available | Player already shared the log; provider hints, not proof |
| Private/raw latest.log; no external consent | Existing local quick diagnose / inspect, or local browser demo | Local heuristic hints only; no upload |
| Raw log; user explicitly approves third-party processing of reviewed copy | Optional mclogs-analyse plugin | mclo.gs receives content; does not create paste via this API endpoint |
| Find mod releases or dependencies | Existing modrinth-catalog plugin | Query/version/loader sent to Modrinth; candidate metadata only |
| Crash Assistant already installed | Ask player for its already-generated report | Client app with GUI, not established remotely callable API |
| Install, update, repair live server | Stop. Require owner authorization and disposable sandbox | No production writes from diagnosis |

## Entry points

Modrinth: already implemented. No new downloader or catalog index:

    python3 tools/totem_operator.py plugins run modrinth-catalog search \
      --input '{"query":"waystones","game_version":"1.21.1","loader":"neoforge","limit":1}'

Results are CANDIDATES_ONLY, NOT verified compatibility or deployment. Consult
reported required / optional / incompatible / embedded dependencies, but never
claim full pack compatibility from metadata.

mclo.gs: optional external-processing adapter. Never automatically invoke
against logs just because Agent has file access. The human log owner must first
explicitly agree to send one particular reviewed copy to the external provider.

    python3 tools/totem_operator.py plugins run mclogs-analyse analyse \
      --input '{"log_path":"/path/to/REVIEWED.log","allow_external_processing":true,"user_reviewed_log_for_secrets":true}'

- Fixed HTTPS endpoint https://api.mclo.gs/1/analyse, documented analysis without saving paste.
- Still a third-party log upload: NOT offline, private or risk-free.
- Log size capped, recognized sensitive markers blocked, no log echoed to Agent.
- Automated detection is not a complete sanitizer. Consent booleans are caller
  assertions and NOT cryptographic proof of authorization.
- No mod downloads, Java launch, world edits, background jobs or AI API keys.
- Provider failure: BLOCK, never fabricate a result.

Crash Assistant: https://github.com/KostromDan/Crash-Assistant

It is a client-side GUI/mod with its own rules, log uploads and some local
auto-fixes. We did not verify any stable headless remote API. Do not claim that
just providing the URL allows an Agent to install the mod, read client crashes,
press buttons, or run automatic repairs. Where available, compare its existing
report against other evidence; discrepancies are REVIEW_REQUIRED.

## Evidence labels and stop conditions

- LOCAL_HINT: local regex or file metadata only
- PROVIDER_HINT: external analysis and identified source, never an assured root cause
- CATALOG_CANDIDATE: Modrinth matching release metadata, not working combinations
- STAGED_ONLY: authorized sandbox downloaded and hash-checked, no Java game started
- PROTOCOL_READY: server responded to protocol, no gameplay proof
- GAMEPLAY_VERIFIED: only after real gameplay tests passed
- BLOCK / REVIEW_REQUIRED: stop; no implicit repair

Always return source, target game/loader version, evidence and limitations.
An HTTP 200 or zero problems never means "fixed". No auto-Issues, monitoring,
moderation, wallet, credentials or new paid services.

References: https://api.mclo.gs/
https://docs.modrinth.com/api/
https://docs.modrinth.com/api/operations/getprojectversions/
https://github.com/KostromDan/Crash-Assistant
