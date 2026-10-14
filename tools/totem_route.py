# SPDX-License-Identifier: Apache-2.0
"""No-daemon sandbox routing policy: local first, opt-in cloud plans only.

This module NEVER connects to a cloud provider, sends files, or starts containers.
Credentials and quota are provider responsibilities, not LLM assertions.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from totem_env import probe_environment

SUPPORTED = {"modal", "e2b", "daytona", "github-actions"}
TASKS = {"stage", "server"}
PUBLIC_SCOPES = {"public-mods", "redacted-logs"}
MAX_CONFIG_BYTES = 16384
MAX_PROVIDERS = 8


class RouteRejected(ValueError):
    pass


def load_providers(path: Path | None) -> list[dict]:
    if path is None:
        return []
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_CONFIG_BYTES:
        raise RouteRejected("invalid_provider_registry")
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema") != 1 or not isinstance(document.get("providers"), list):
        raise RouteRejected("invalid_provider_schema")
    providers = document["providers"]
    if len(providers) > MAX_PROVIDERS:
        raise RouteRejected("too_many_providers")
    seen = set()
    for item in providers:
        if not isinstance(item, dict) or item.get("id") not in SUPPORTED or item["id"] in seen:
            raise RouteRejected("invalid_or_duplicate_provider")
        seen.add(item["id"])
        if type(item.get("enabled")) is not bool:
            raise RouteRejected("enabled_must_be_boolean")
        if not isinstance(item.get("tasks"), list) or any(t not in TASKS for t in item["tasks"]):
            raise RouteRejected("invalid_provider_tasks")
        for key in ("memory_mb", "disk_mb"):
            if type(item.get(key)) is not int or not 0 <= item[key] <= 1048576:
                raise RouteRejected("invalid_provider_capability")
        # The provider may add real quota/status checking in an opt-in adapter,
        # but local routing must never infer that a free tier still exists.
    return providers


def route(task: str, sandbox_root: Path | None, providers: list[dict],
          allow_cloud: bool = False, payload_scope: str = "unspecified",
          max_cloud_usd: float = 0.0) -> dict:
    if task not in TASKS or payload_scope not in (*PUBLIC_SCOPES, "private-world", "unspecified"):
        raise RouteRejected("invalid_route_request")
    if not isinstance(max_cloud_usd, (int, float)) or not 0 <= max_cloud_usd <= 100:
        raise RouteRejected("invalid_budget")
    env = probe_environment(sandbox_root)
    ready = env["stage_allowed"] if task == "stage" else env["run_allowed"]
    report = {"schema": 1, "task": task, "status": "LOCAL" if ready else "BLOCK",
              "selected": "local" if ready else None,
              "local_blockers": [] if ready else (env["stage_blockers"] if task == "stage" else env["run_blockers"]),
              "cloud_candidates": [], "cloud_execution_performed": False,
              "credentials_sent": False, "payload_uploaded": False}
    if ready:
        return report
    if not allow_cloud:
        report["reason"] = "cloud_not_opted_in"
        return report
    if payload_scope not in PUBLIC_SCOPES:
        report["reason"] = "payload_not_approved_for_cloud"
        return report
    if max_cloud_usd == 0:
        # Trial credits are NOT an API-enforced zero-bill guarantee.
        report["reason"] = "cloud_spend_cap_not_configured"
        return report
    for item in providers:
        if not item["enabled"] or task not in item["tasks"]:
            continue
        if task == "server" and (item["memory_mb"] < 4096 or item["disk_mb"] < 8192):
            continue
        if task == "stage" and (item["memory_mb"] < 768 or item["disk_mb"] < 2048):
            continue
        report["cloud_candidates"].append({"id": item["id"], "status": "UNVERIFIED",
                                           "capacity_mb": item["memory_mb"],
                                           "requested_budget_limit_usd": round(max_cloud_usd, 2),
                                           "provider_billing_cap_enforced": False})
    if report["cloud_candidates"]:
        report["status"] = "CLOUD_PREFLIGHT_REQUIRED"
        report["reason"] = "provider_credentials_quota_price_and_network_not_verified"
    else:
        report["reason"] = "no_eligible_enabled_provider"
    return report
