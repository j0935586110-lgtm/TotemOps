#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""TotemOps friend workflows. Read-only: source-based player flow and API impact.

No network, downloader, code execution, local file changes or external writes.
This is an Agent decision aid, not a functioning Minecraft launcher or CI runner.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

from totem_maintainer import MaintainerBlock, inspect

MAX_SOURCE = 512 * 1024


def source(root: Path, relative: str) -> str:
    """Read only named, bounded files inside the inspected public repo."""
    dest = root / relative
    if dest.is_symlink() or not dest.is_file():
        raise MaintainerBlock("required_source_not_regular:" + relative)
    if dest.stat().st_size > MAX_SOURCE:
        raise MaintainerBlock("required_source_too_large:" + relative)
    return dest.read_text(encoding="utf-8")


def provenance(repo_dir: str, name: str, expected: str) -> tuple[Path, dict]:
    root = Path(repo_dir).resolve()
    info = inspect(root, name)
    if info["github"] != expected:
        raise MaintainerBlock("unexpected_repository")
    if info["status"] != "PASS" or info["dirty"] or not info["head_matches_profile"]:
        raise MaintainerBlock("pinned_clean_checkout_required")
    return root, info


def barian_player_flow(repo_dir: str) -> dict:
    root, repo = provenance(repo_dir, "barian0517", "Barian0517/modsync-v2")
    main = source(root, "main.py")
    gui = source(root, "MainWindow.py")
    worker = source(root, "WorkerThread.py")
    ast.parse(main, filename="main.py")
    ast.parse(gui, filename="MainWindow.py")
    ast.parse(worker, filename="WorkerThread.py")
    auto = '"--auto" in args' in main or "'--auto' in args" in main
    locate = '"--dir"' in main or "'--dir'" in main
    # A finished QThread is not proof that downloads or hash validation passed.
    unconditional_close = (
        "window.worker.finished.connect(close_when_done)" in main
        and "app.quit" in main
        and "worker.success" not in main
        and "worker.result" not in main
    )
    unresolved_download_result = "def download_and_verify(" in worker and re.search(
        r"def download_and_verify\(.*?\n\s+return True",
        worker, flags=re.DOTALL
    ) is not None and "if not self.download_file" not in worker
    # This reports only source evidence. It does not infer the player's launcher state.
    return {
        "status": "ACTIONABLE", "verification": "STATIC_ONLY", "action": "barian_player_flow",
        "repo": repo["github"], "commit": repo["head"], "files_read": [
            "main.py", "MainWindow.py", "WorkerThread.py"
        ],
        "existing": {
            "auto_sync_flag": auto,
            "target_directory_flag": locate,
            "sync_files_and_config": "collect_download_tasks" in worker,
            "sync_gui_available": "QWidget" in gui,
        },
        "gaps": [
            {"id": "FIRST_INSTALL", "status": "NOT_VERIFIED",
             "detail": "Existing updater is not a verified one-click PCL+Forge installer",
             "next": "Use existing launcher instance export/import first; do not rebuild sync engine"},
            {"id": "SYNC_COMPLETION", "status": "STATIC_RISK" if unconditional_close else "NOT_VERIFIED",
             "detail": "Auto mode closes on worker finished without checking explicit success",
             "next": "Expose a reliable worker success/failure result before launcher pre-launch integration"},
            {"id": "DOWNLOAD_RESULT", "status": "STATIC_RISK" if unresolved_download_result else "NOT_VERIFIED",
             "detail": "Download-and-verify may return success after a failed download or hash mismatch",
             "next": "Propagate download and integrity errors to worker and process exit status"},
        ],
        "release_path": [
            "Reuse Barian's existing modsync-v2 and PCL/Forge instance",
            "Provide first-time import/install as a separate packaging deliverable",
            "Bind a reliable updater to launcher pre-launch only after failure propagation is verified",
            "A Windows GUI client and a real player login are still required to claim PLAYABLE",
        ],
        "installation_performed": False, "gui_test_performed": False,
        "remote_write": False, "player_world_touched": False,
    }


def yuan_api_impact(api_dir: str, updater_dir: str, barian_dir: str, changed: list[str]) -> dict:
    api_root, api = provenance(api_dir, "chyuaner", "chyuaner/php-minecraft-server-info")
    client_root, client = provenance(updater_dir, "chyuaner", "chyuaner/python-minecraft-mods-sync")
    barian_root, barian = provenance(barian_dir, "barian0517", "Barian0517/modsync-v2")
    routes = source(api_root, "public/mods.php")
    model = source(api_root, "src/McModUtils/Mod.php")
    yuan_client = source(client_root, "src/mcmods_sync/server.py")
    yuan_config = source(client_root, "src/mcmods_sync/config.py")
    barian_client = source(barian_root, "WorkerThread.py")
    barian_main = source(barian_root, "main.py")
    ast.parse(yuan_client, filename="server.py")
    ast.parse(yuan_config, filename="config.py")
    ast.parse(barian_client, filename="WorkerThread.py")
    ast.parse(barian_main, filename="main.py")

    # Contract evidence from their current checked-out source; no live HTTP calls.
    producer = {
        "mods_route": "'mods' => 'common'" in routes and "$group->get(''" in routes,
        "zip_route": "$group->get('/zip'" in routes,
        "mods_response": '"mods"' in routes or "'mods'" in routes,
        "sha1": '"sha1"' in model,
        "download_url": '"downloadUrl"' in model,
    }
    consumer = {
        "requests_mods_json": "'mods/?type=json'" in yuan_client or '"mods/?type=json"' in yuan_client,
        "reads_mods": 'data.get("mods")' in yuan_client,
        "reads_sha1": 'mod.get("sha1"' in yuan_client,
        "reads_download_url": 'mod.get("downloadUrl")' in yuan_client,
    }
    barian_contract = {
        "different_default_base": "modapi.barian.moe" in barian_main,
        "uses_config_names": "/config_names?json=1" in barian_client,
        "uses_folder_json": "/{folder}/?json=1" in barian_client,
    }
    impact_paths = (
        "public/mods.php", "src/McModUtils/Mod.php",
        "src/McModUtils/Mods.php", "src/App/ResponseFormatter.php"
    )
    normalized = []
    for path in changed:
        if (not isinstance(path, str) or len(path) > 180
                or path.startswith("/") or "\\" in path
                or ".." in Path(path).parts or not re.fullmatch(r"[A-Za-z0-9_./-]+",path)):
            raise MaintainerBlock("invalid_changed_path")
        if path not in normalized:
            normalized.append(path)
    affects_contract = any(p in impact_paths for p in normalized)
    established = all(producer.values()) and all(consumer.values())
    return {
        "status": "ACTIONABLE" if affects_contract else "NO_KNOWN_SYNC_CONTRACT_CHANGE",
        "verification": "STATIC_ONLY", "action": "yuan_api_impact",
        "producer_repo": api["github"], "producer_commit": api["head"],
        "yuan_updater_repo": client["github"], "yuan_updater_commit": client["head"],
        "barian_updater_repo": barian["github"], "barian_updater_commit": barian["head"],
        "changed_paths": normalized, "api_contract": producer,
        "yuan_consumer_contract": consumer, "barian_consumer_contract": barian_contract,
        "relationships": [
            {"consumer": "chyuaner/python-minecraft-mods-sync",
             "status": "SOURCE_CONTRACT_MATCH" if established else "NEEDS_REVIEW",
             "affected": affects_contract,
             "reason": "The client reads mods, sha1 and downloadUrl from the API family",
             "next": "Use existing client to test /mods/?type=json and fallback paths against a mock API"},
            {"consumer": "Barian0517/modsync-v2",
             "status": "DIFFERENT_DEFAULT_API",
             "affected": "UNKNOWN",
             "reason": "Barian defaults to modapi.barian.moe and /config_names plus per-folder JSON",
             "next": "Do not claim impact without confirmed deployment or route mapping"},
        ],
        "real_api_called": False, "clients_launched": False, "remote_write": False,
    }


def main(argv=None) -> int:
    cli = argparse.ArgumentParser(prog="totem-ops friend-flow",
                                  description="Source-based help for two friends; no install or remote writes")
    sub = cli.add_subparsers(dest="task", required=True)
    bar = sub.add_parser("barian-player", help="Inventory player's actual auto-update and first-launch gaps")
    bar.add_argument("--repo-dir", required=True)
    impact = sub.add_parser("yuan-impact", help="Trace public API to player-sync client dependencies")
    impact.add_argument("--api-dir", required=True)
    impact.add_argument("--updater-dir", required=True)
    impact.add_argument("--barian-dir", required=True)
    impact.add_argument("--changed-file", action="append", required=True)
    args = cli.parse_args(argv)
    try:
        if args.task == "barian-player":
            result = barian_player_flow(args.repo_dir)
        else:
            result = yuan_api_impact(args.api_dir, args.updater_dir, args.barian_dir,
                                     args.changed_file)
    except (MaintainerBlock, ValueError, SyntaxError, UnicodeError, OSError, KeyError,
            TypeError, TimeoutError) as exc:
        result = {"status": "BLOCK", "reason": str(exc)[:200],
                  "remote_write": False, "installation_performed": False}
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))
    return 2 if result["status"] == "BLOCK" else 0


if __name__ == "__main__":
    sys.exit(main())
