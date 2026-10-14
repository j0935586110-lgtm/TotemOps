#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Static, opt-in Minecraft client launcher planner (never executes launchers)."""
from __future__ import annotations

import json
import re
import sys
from urllib.parse import urlsplit

INSTANCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
DNS_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
SYNC_MODES = {"none", "existing-modsync", "packwiz", "automodpack"}
KEYS = {"schema", "launcher", "instance_id", "server_address", "sync_mode", "sync_feed"}


def blocked(reason):
    return {"status": "BLOCK", "reason": reason, "launch_argv": None,
            "game_launched": False, "download_performed": False,
            "configuration_written": False}


def validate_address(address):
    if not isinstance(address, str) or len(address) > 253 or not address:
        return False
    host, sep, port = address.partition(":")
    if sep and (not port.isdecimal() or not 1 <= int(port) <= 65535):
        return False
    if not host or host.endswith(".") or any(
        not DNS_LABEL.fullmatch(part) for part in host.split(".")
    ):
        return False
    return True


def plan(request):
    if not isinstance(request, dict) or set(request) - KEYS:
        return blocked("unknown_input_fields")
    if request.get("schema") != 1 or type(request.get("schema")) is not int:
        return blocked("unsupported_input_schema")
    if request.get("launcher") != "prism":
        return blocked("unsupported_launcher_needs_independent_validation")
    instance = request.get("instance_id")
    if (not isinstance(instance, str) or not INSTANCE.fullmatch(instance) or
            ".." in instance or instance.endswith(".")):
        return blocked("unsafe_instance_id")
    mode = request.get("sync_mode")
    if not isinstance(mode, str) or mode not in SYNC_MODES:
        return blocked("unsupported_sync_mode")
    address = request.get("server_address")
    if address is not None and not validate_address(address):
        return blocked("unsafe_server_address")

    feed = request.get("sync_feed")
    if feed is not None:
        if mode not in ("existing-modsync", "packwiz") or not isinstance(feed, str):
            return blocked("unexpected_sync_feed")
        if len(feed) > 1024 or any(c.isspace() for c in feed):
            return blocked("invalid_sync_feed")
        try:
            url = urlsplit(feed)
            if (url.scheme != "https" or not url.hostname or url.username or
                    url.password or url.port not in (None, 443) or url.fragment or
                    "\\" in url.path or not url.path.startswith("/") or
                    any(p in (".", "..") for p in url.path.split("/"))):
                return blocked("untrusted_sync_feed")
        except ValueError:
            return blocked("untrusted_sync_feed")
    args = ["prismlauncher", "--launch", instance]
    if address:
        args.extend(["--server", address])
    requirements = ["prism_installed", "instance_exists", "java_configured",
                    "valid_microsoft_login", "client_gameplay_test"]
    if address is None:
        requirements.append("server_address_required_for_direct_join")
    if mode == "existing-modsync":
        requirements.extend(["owner_approved_https_manifest",
                             "verified_download_integrity",
                             "signed_release_gate_ready",
                             "prelaunch_failure_blocks_game",
                             "existing_modsync_runtime_test"])
    elif mode == "packwiz":
        requirements.extend(["owner_approved_packwiz_feed",
                             "verified_packwiz_prelaunch_hook",
                             "prelaunch_failure_blocks_game"])
    elif mode == "automodpack":
        requirements.extend(["owner_approval_to_install_both_sides",
                             "game_loader_compatibility_confirmed",
                             "server_and_client_identity_check",
                             "version_migration_sandbox_test"])
    else:
        requirements.append("no_automatic_mod_sync_configured")
    # No shell string / executable invocation; existing updater is never bypassed.
    return {"status": "REVIEW_REQUIRED", "reason": "static_plan_only",
            "launcher": "prism", "sync_mode": mode,
            "launch_argv": args, "required_verifications": requirements,
            "game_launched": False, "download_performed": False,
            "configuration_written": False, "compatible": "UNVERIFIED"}


def main():
    if len(sys.argv) != 2 or sys.argv[1] != "inspect":
        print(json.dumps(blocked("unsupported_command")))
        return 0
    try:
        request = json.load(sys.stdin)
        answer = plan(request)
    except (ValueError, UnicodeError, TypeError, json.JSONDecodeError):
        answer = blocked("invalid_json_input")
    print(json.dumps(answer, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
