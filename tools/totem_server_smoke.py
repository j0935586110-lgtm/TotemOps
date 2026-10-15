#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Read-only smoke PROBE of an ALREADY running disposable Docker server.

No docker run/create/start/stop, no host socket handed to an AI, no RCON,
no world writes, no client. Server boot != safe release or gameplay proof.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import subprocess
from pathlib import Path

from totem_modsync_manifest import ManifestBlocked, inspect_manifest

SAFE_CONTAINER = re.compile(r"^(?:tot-e2e-|totem-sandbox-)[a-z0-9][a-z0-9-]{2,75}$")
LOADER = re.compile(r"NeoForge mod loading, version ([0-9A-Za-z.+_-]+), for MC ([0-9.]+)")
BOOT = re.compile(r"Done \([0-9.]+s\)! For help, type")
FATAL = re.compile(r"(?:Exception in server tick loop|Failed to start the minecraft server|FATAL ERROR)",re.I)
MAX_LOG_BYTES = 3_000_000


class SmokeBlocked(ValueError):
    pass


def _docker(*args: str, timeout=12) -> str:
    try:
        result = subprocess.run(["docker", *args], capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SmokeBlocked("docker_read_only_probe_failed") from exc
    if result.returncode:
        raise SmokeBlocked("docker_probe_nonzero_exit")
    if len(result.stdout) + len(result.stderr) > MAX_LOG_BYTES:
        raise SmokeBlocked("docker_response_oversized")
    return (result.stdout + result.stderr).decode("utf-8", errors="replace")


def inspect_server(mods_dir: Path, *, sandbox_root: Path, container: str,
                   minecraft: str, neoforge: str) -> dict:
    if not SAFE_CONTAINER.fullmatch(container):
        raise SmokeBlocked("container_name_not_marked_disposable")
    root = sandbox_root
    if root.is_symlink() or not root.is_dir() or not root.name.startswith("totemops-"):
        raise SmokeBlocked("missing_disposable_sandbox_root")
    source = mods_dir
    if source.is_symlink() or not source.is_dir():
        raise SmokeBlocked("invalid_mods_path")
    resolved_root = root.resolve(strict=True)
    if source.resolve(strict=True) != resolved_root / "server" / "mods":
        raise SmokeBlocked("mods_not_in_expected_sandbox_server_path")
    if not re.fullmatch(r"1\.[0-9]+(?:\.[0-9]+)?", minecraft):
        raise SmokeBlocked("invalid_minecraft")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", neoforge):
        raise SmokeBlocked("invalid_neoforge")
    try:
        inventory = inspect_manifest(source)
    except (ManifestBlocked, OSError) as exc:
        raise SmokeBlocked("static_manifest_rejected") from exc
    if inventory["status"] == "BLOCK":
        raise SmokeBlocked("static_manifest_block")
    raw = _docker("inspect", container)
    try:
        obj = json.loads(raw)[0]
        if obj["Name"] != "/" + container or not obj["State"]["Running"]:
            raise SmokeBlocked("container_not_running")
        if obj["State"].get("Health", {}).get("Status") != "healthy":
            raise SmokeBlocked("container_not_healthy")
        if any(v for v in obj["NetworkSettings"].get("Ports", {}).values()):
            raise SmokeBlocked("published_ports_forbidden")
        networks = obj["NetworkSettings"]["Networks"]
        if not isinstance(networks, dict) or len(networks) != 1:
            raise SmokeBlocked("one_internal_network_required")
        network = next(iter(networks))
        if not network.startswith("tot-e2e-") and not network.startswith("totem-sandbox-"):
            raise SmokeBlocked("network_not_marked_disposable")
        mounts = obj["Mounts"]
        if not any(m["Destination"] == "/data" and
                   Path(m["Source"]).resolve(strict=True) == resolved_root / "server"
                   for m in mounts):
            raise SmokeBlocked("sandbox_data_mount_not_verified")
    except (KeyError, TypeError, IndexError, json.JSONDecodeError) as exc:
        raise SmokeBlocked("untrusted_docker_inspect_shape") from exc
    net = _docker("network", "inspect", network, "--format", "{{.Internal}}").strip()
    if net != "true":
        raise SmokeBlocked("docker_network_not_internal")
    logs = _docker("logs", "--tail", "2000", container, timeout=18)
    log_hash = hashlib.sha256(logs.encode("utf-8")).hexdigest()
    versions = list(LOADER.finditer(logs))
    boots = list(BOOT.finditer(logs))
    if not versions or not boots:
        raise SmokeBlocked("neoforge_or_done_marker_missing")
    latest = versions[-1]
    if (latest.group(1), latest.group(2)) != (neoforge, minecraft):
        raise SmokeBlocked("loader_version_or_game_version_mismatch")
    if not any(hit.start() > latest.start() for hit in boots):
        raise SmokeBlocked("last_loader_start_has_no_done_marker")
    if FATAL.search(logs[latest.start():]):
        raise SmokeBlocked("fatal_server_log_after_latest_loader_start")
    # Proof that the running instance discovered each input jar. Does not
    # prove its features or runtime data were correctly initialized.
    # Mod discovery precedes the "NeoForge mod loading" line. Start at
    # the end of the prior successful boot, not the loader marker itself.
    preceding_done = max((m.end() for m in boots if m.end() < latest.start()), default=0)
    current_boot_logs = logs[preceding_done:]
    absent = [f["path"] for f in inventory["files"]
              if Path(f["path"]).name not in current_boot_logs]
    if absent:
        raise SmokeBlocked("mod_discovery_log_missing")
    return {
        "schema":1,"status":"REVIEW_REQUIRED",
        "reason":"existing_disposable_server_boot_verified_not_playable",
        "probe":"read_only_existing_docker_server",
        "server_boot_smoke_verified":True,
        "static_inventory_status":inventory["status"],
        "minecraft":minecraft,"neoforge":neoforge,
        "tested_mods":[{"path":f["path"],"sha256":f["sha256"]}
                       for f in inventory["files"]],
        "docker_network_internal":True,"published_ports":0,
        "captured_server_logs_sha256":log_hash,
        "checked_at_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
        "server_started_by_this_tool":False,
        "gameplay_verified":False,"client_join_verified":False,
        "world_modified":False,"release_allowed":False,
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Read-only inspection of pre-existing disposable Minecraft server")
    p.add_argument("mods",type=Path)
    p.add_argument("--side",choices=("server","client"),required=True)
    p.add_argument("--container",required=True)
    p.add_argument("--sandbox-root",type=Path,required=True)
    p.add_argument("--minecraft",required=True)
    p.add_argument("--neoforge",required=True)
    p.add_argument("--json",action="store_true")
    a = p.parse_args(argv)
    try:
        if a.side != "server":
            raise SmokeBlocked("client_side_smoke_not_implemented")
        report = inspect_server(a.mods,sandbox_root=a.sandbox_root,container=a.container,
                                minecraft=a.minecraft,neoforge=a.neoforge)
    except (SmokeBlocked, OSError, ValueError, TypeError) as exc:
        report={"schema":1,"status":"BLOCK","reason":str(exc)[:170],
                "server_boot_smoke_verified":False,
                "gameplay_verified":False,"release_allowed":False,
                "server_started_by_this_tool":False,"world_modified":False}
    print(json.dumps(report,ensure_ascii=False,sort_keys=True,separators=(",",":")))
    return 3 if report["status"] == "REVIEW_REQUIRED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
