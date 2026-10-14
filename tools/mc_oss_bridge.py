#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Read-only AGY integration boundary for established Minecraft open-source CLIs.

Only routes known safe CLI operations. Does not install, update, reboot or edit.
AGY uses the project skill for approval and error handling. Python stdlib only.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PINNED_MONITOR = ROOT / ".local-tools/mc-monitor/1.18.3/mc-monitor"
PINNED_PACKWIZ = ROOT / ".local-tools/packwiz/bin/packwiz"
MAX_OUTPUT = 16384


def _binary(name: str) -> str | None:
    pinned = {"mc-monitor": PINNED_MONITOR, "packwiz": PINNED_PACKWIZ}.get(name)
    if pinned is not None and pinned.is_file() and pinned.stat().st_mode & 0o111:
        return str(pinned)
    return shutil.which(name)


def _run(argv: list[str], timeout: int = 12) -> dict:
    try:
        result = subprocess.run(
            argv, shell=False, stdin=subprocess.DEVNULL, capture_output=True,
            text=True, timeout=timeout, check=False,
        )
        return {
            "exit": result.returncode,
            "stdout": result.stdout[:MAX_OUTPUT],
            "stderr": result.stderr[:MAX_OUTPUT],
            "output_truncated": len(result.stdout) > MAX_OUTPUT or len(result.stderr) > MAX_OUTPUT,
        }
    except subprocess.TimeoutExpired:
        return {"exit": None, "stdout": "", "stderr": "tool_timeout", "output_truncated": False}
    except OSError as err:
        return {"exit": None, "stdout": "", "stderr": type(err).__name__, "output_truncated": False}


def doctor() -> dict:
    result = {"mode": "read_only", "tools": {}}
    for tool in ("mc-monitor", "packwiz", "mc-image-helper"):
        path = _binary(tool)
        result["tools"][tool] = {
            "available": path is not None, "path": path,
            "note": "version pinned locally" if path and str(path).startswith(str(ROOT / ".local-tools")) else "external or missing",
        }
    result["tools"]["AutoModpack"] = {
        "available": False,
        "path": None,
        "note": "client/server opt-in Forge/NeoForge mod, not installed by this bridge",
    }
    result["tools"]["MCSManager"] = {
        "available": False,
        "path": None,
        "note": "optional HTTP API integration; no instance configured",
    }
    return result


def status(host: str, port: int) -> dict:
    """Live protocol status only, not TCP-port-open approximation."""
    if host not in ("127.0.0.1", "localhost", "::1"):
        return {"ok": False, "code": "BLOCK", "reason": "target_not_allowlisted",
                "detail": "Only an explicitly selected local sandbox target is permitted."}
    if not 1 <= port <= 65535:
        return {"ok": False, "code": "BLOCK", "reason": "invalid_port"}
    monitor = _binary("mc-monitor")
    if not monitor:
        return {"ok": False, "code": "BLOCK", "reason": "mc_monitor_missing"}
    argv = [monitor, "status", "-host", host, "-port", str(port), "-json", "-timeout", "4s"]
    run = _run(argv, timeout=9)
    if run["exit"] is None:
        return {"ok": False, "code": "BLOCK", "reason": run["stderr"], "command": argv,
                "exit": None, "readback": run}
    if run["exit"] != 0:
        return {"ok": True, "code": "PASS", "probe_completed": True, "healthy": False,
                "command": argv, "exit": run["exit"], "readback": run}
    try:
        parsed = json.loads(run["stdout"])
        if not isinstance(parsed, dict):
            raise ValueError("expected object")
    except (ValueError, TypeError):
        return {"ok": False, "code": "BLOCK", "reason": "invalid_status_json",
                "command": argv, "exit": run["exit"], "readback": run}
    return {"ok": True, "code": "PASS", "probe_completed": True, "healthy": True,
            "command": argv, "exit": run["exit"], "data": parsed, "readback": run}


def plan(task: str) -> dict:
    """Suggest an existing tool without reimplementing resolver/installer."""
    recipes = {
        "modpack-versioning": ("packwiz", "Git/TOML index, locked pack changes and export"),
        "modrinth-dependencies": ("mc-image-helper", "native modrinth -download-dependencies REQUIRED"),
        "client-sync": ("AutoModpack", "clients opt in to trusted server-managed modpack"),
        "server-status": ("mc-monitor", "actual Minecraft protocol ping"),
        "server-control": ("MCSManager", "existing panel API only, with owner authorization"),
    }
    tool, reason = recipes[task]
    capability = doctor()["tools"][tool]
    return {"ok": True, "code": "PLAN_ONLY", "task": task, "recommended_tool": tool,
            "reason": reason, "available_here": capability["available"],
            "next_step": "configure existing tool + sandbox test; no mutation was attempted",
            "changes": [], "requires_approval_for_production": True}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AGY Minecraft OSS bridge (read-only)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    p_status = sub.add_parser("status")
    p_status.add_argument("--host", default="127.0.0.1")
    p_status.add_argument("--port", type=int, default=25565)
    p_plan = sub.add_parser("plan")
    p_plan.add_argument("task", choices=[
        "modpack-versioning", "modrinth-dependencies", "client-sync",
        "server-status", "server-control",
    ])
    args = parser.parse_args(argv)
    if args.command == "doctor":
        result = doctor()
    elif args.command == "status":
        result = status(args.host, args.port)
    else:
        result = plan(args.task)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("ok", True) else 2


if __name__ == "__main__":
    sys.exit(main())
