#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Tiny read-only Modrinth lookup plugin: official API, capped to four requests.

Output is candidate metadata, NEVER a guarantee that mods work together.
No server, no cache database, no downloads, no private log uploads.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://api.modrinth.com/v2"
LOADER = {"fabric", "forge", "neoforge", "quilt"}
MAX_RESULTS = 3


def _fetch(url: str):
    request = urllib.request.Request(
        url, headers={"User-Agent": "TotemOps/0.1 (on-demand open-source metadata query)",
                      "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=7) as response:
        if response.status != 200:
            raise ValueError("upstream_response_not_ok")
        raw = response.read(300_001)
    if len(raw) > 300_000:
        raise ValueError("metadata_response_too_large")
    return json.loads(raw)


def search(payload: dict):
    query = payload.get("query", "")
    version = payload.get("game_version", "")
    loader = payload.get("loader", "")
    requested = payload.get("limit", 3)
    if (not isinstance(query, str) or not 2 <= len(query.strip()) <= 80
            or not isinstance(version, str)
            or not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", version)
            or loader not in LOADER
            or type(requested) is not int or not 1 <= requested <= MAX_RESULTS):
        return {"status": "BLOCK", "reason": "invalid_query_version_loader_or_limit"}
    facets = [["project_type:mod"], [f"categories:{loader}"], [f"versions:{version}"]]
    params = urllib.parse.urlencode({
        "query": query.strip(), "facets": json.dumps(facets, separators=(",", ":")),
        "limit": requested,
    })
    candidates = []
    warnings = []
    try:
        data = _fetch(BASE + "/search?" + params)
        hits = data["hits"] if isinstance(data, dict) else []
        if not isinstance(hits, list):
            raise ValueError("invalid_catalog_search_response")
        for h in hits[:requested]:
            project_id = h.get("project_id", "")
            if not isinstance(project_id, str) or not re.fullmatch(r"[A-Za-z0-9]{6,20}", project_id):
                warnings.append("invalid_project_id")
                continue
            vers_params = urllib.parse.urlencode({
                "loaders": json.dumps([loader]), "game_versions": json.dumps([version]),
                "include_changelog": "false",
            })
            try:
                versions = _fetch(BASE + "/project/" + project_id + "/version?" + vers_params)
                if not isinstance(versions, list):
                    raise ValueError("invalid_version_response")
            except (ValueError, urllib.error.URLError, TimeoutError, OSError) as exc:
                warnings.append("version_lookup_failed_" + type(exc).__name__)
                continue
            matching = [v for v in versions if isinstance(v, dict)
                        and version in v.get("game_versions", []) and loader in v.get("loaders", [])]
            if not matching:
                continue
            recent = max(matching, key=lambda x: str(x.get("date_published", "")))
            dependencies = [
                {"project_id": d.get("project_id"), "type": d.get("dependency_type"),
                 "version_id": d.get("version_id")}
                for d in recent.get("dependencies", [])[:16] if isinstance(d, dict)
            ]
            candidates.append({
                "title": str(h.get("title", ""))[:110], "project_id": project_id,
                "url": "https://modrinth.com/mod/" + project_id,
                "version_id": recent.get("id"),
                "version": recent.get("version_number"),
                "published_at": recent.get("date_published"),
                "environment": h.get("environment", "unknown"),
                "dependencies": dependencies,
                "evidence": "official_modrinth_version_metadata",
            })
    except (urllib.error.URLError, ValueError, TimeoutError, OSError, KeyError) as exc:
        return {"status": "BLOCK", "reason": "modrinth_api_unavailable_or_invalid",
                "error_type": type(exc).__name__, "no_results_fabricated": True}
    return {
        "status": "PARTIAL_CANDIDATES" if warnings else "CANDIDATES_ONLY",
        "query": query.strip(), "game_version": version, "loader": loader,
        "candidates": candidates, "warnings": warnings,
        "requests_maximum": 1 + requested, "verified_compatible_together": False,
        "downloaded": False, "sandbox_tested": False,
        "source": "https://api.modrinth.com/v2/",
    }


def main():
    if len(sys.argv) != 2 or sys.argv[1] != "search":
        print(json.dumps({"status": "BLOCK", "reason": "command_not_supported"}))
        return 2
    try:
        raw = sys.stdin.read(8193)
        if len(raw) > 8192:
            raise ValueError("input_too_large")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("input_must_be_json_object")
        result = search(data)
    except (ValueError, TypeError):
        result = {"status": "BLOCK", "reason": "invalid_input"}
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 2 if result["status"] == "BLOCK" else 0


if __name__ == "__main__":
    sys.exit(main())
