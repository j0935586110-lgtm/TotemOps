# Contributing

We welcome reproducible Minecraft fault reports, safe parsers, tests and opt-in plugins.

- Run `python3 -m unittest discover -s tools -p 'test_*.py' -q` before proposing code.
- Default to read-only behavior. Do not mutate production worlds or automatically update modpacks.
- Label unverified conclusions as PLAN_ONLY, REVIEW_REQUIRED or BLOCK, rather than claiming a successful repair.
- Never commit credentials, private player data, unlicensed mod JARs, server world folders or unredacted production logs.
- Preserve Apache-2.0 licensing for first-party contributions while respecting all third-party licenses.
- Include tests that exercise failure paths and do not require real servers.
