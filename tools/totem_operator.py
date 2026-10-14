#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""TotemOps — 不死圖騰. Stable entrypoint; existing Minecraft tools stay reusable."""
from __future__ import annotations

import argparse
import json
import sys

import mc_operator
from totem_plugins import list_plugins, run_plugin


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ("modules", "module"):
        from totem_modules import main as modules_main
        return modules_main(args[1:])
    if args and args[0] == "onboarding":
        if len(args) < 2 or args[1] != "inspect":
            print("usage: totem-ops onboarding inspect --repo-dir PATH [--entry main.py] [--readme README.md]")
            return 2
        from totem_onboarding import main as onboarding_main
        return onboarding_main(args[2:])
    if args and args[0] == "release":
        if len(args) > 1 and args[1] == "gate":
            from totem_release_gate import main as gate_main
            return gate_main(args[2:])
        if len(args) < 2 or args[1] != "inspect":
            print("usage: totem-ops release inspect --pack PACK.zip [--update UPDATE.zip] OR release gate --help")
            return 2
        from totem_release import main as release_main
        return release_main(args[2:])
    if args and args[0] == "friend-flow":
        from totem_friend_flows import main as friend_flow_main
        return friend_flow_main(args[1:])
    if args and args[0] == "maintainer":
        from totem_maintainer import main as maintainer_main
        return maintainer_main(args[1:])
    if args and args[0] in ("plugins", "plugin"):
        parser = argparse.ArgumentParser(prog="totem-ops plugins")
        sub = parser.add_subparsers(dest="action", required=True)
        sub.add_parser("list", help="List opt-in extensions, does not execute them")
        run = sub.add_parser("run", help="Explicitly invoke code from a trusted plugin")
        run.add_argument("name")
        run.add_argument("command")
        run.add_argument("--input", default="{}", help="JSON object, not a shell command")
        options = parser.parse_args(args[1:])
        result = list_plugins() if options.action == "list" else run_plugin(
            options.name, options.command, options.input
        )
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
        return 2 if result["status"] == "BLOCK" else 0
    if args and args[0] == "quick":
        # Token-economical, read-only, bounded JSON for weaker coding agents.
        from pathlib import Path
        from mc_package_inspector import InputBlocked
        parser = argparse.ArgumentParser(prog="totem-ops quick")
        parser.add_argument("task", choices=("inspect", "diagnose"))
        parser.add_argument("path")
        opts = parser.parse_args(args[1:])
        try:
            if opts.task == "diagnose":
                raw = mc_operator.diagnose(Path(opts.path))
                summary = {"status": raw["status"], "confirmed_root_cause": None,
                           "log_sha256": raw["log_sha256"],
                           "clues": [{"line": x["line"], "signal": x["signal"],
                                      "status": x["status"]}
                                     for x in raw["clues"][:3]],
                           "next": "Needs source evidence and authorized reproduction"}
            else:
                raw = mc_operator.summarize_package(Path(opts.path))
                summary = {"status": raw["status"], "analyzed": raw["analyzed"],
                           "mods": [{"id": str(x["id"])[:50], "loader": str(x["loader"])[:20]}
                                    for x in raw["mods"][:3]],
                           "findings": [{"kind": str(x.get("kind", ""))[:48]}
                                        for x in raw["findings"][:3]],
                           "truncated": len(raw["mods"]) > 3 or len(raw["findings"]) > 3,
                           "verified_compatible": False}
        except (InputBlocked, ValueError, OSError) as err:
            summary = {"status": "BLOCK", "reason": type(err).__name__}
        print(json.dumps(summary, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
        return 2 if summary["status"] == "BLOCK" else 0
    if args and args[0] == "route":
        from pathlib import Path
        from totem_route import load_providers, route, RouteRejected
        parser = argparse.ArgumentParser(prog="totem-ops route")
        parser.add_argument("task", choices=("stage", "server"))
        parser.add_argument("--sandbox-root")
        parser.add_argument("--providers", help="Operator-owned JSON registry, not a model prompt")
        parser.add_argument("--allow-cloud", action="store_true")
        parser.add_argument("--payload-scope", default="unspecified",
                            choices=("unspecified", "public-mods", "redacted-logs", "private-world"))
        parser.add_argument("--max-cloud-usd", type=float, default=0.0)
        opts = parser.parse_args(args[1:])
        try:
            output = route(opts.task, Path(opts.sandbox_root) if opts.sandbox_root else None,
                           load_providers(Path(opts.providers) if opts.providers else None),
                           opts.allow_cloud, opts.payload_scope, opts.max_cloud_usd)
        except (RouteRejected, ValueError, KeyError, OSError) as e:
            output = {"status": "BLOCK", "reason": str(e)[:120],
                      "cloud_execution_performed": False, "payload_uploaded": False}
        print(json.dumps(output, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
        return 0 if output["status"] in ("LOCAL", "CLOUD_PREFLIGHT_REQUIRED") else 2
    if args and args[0] == "preflight":
        from pathlib import Path
        from totem_env import probe_environment
        parser = argparse.ArgumentParser(prog="totem-ops preflight")
        parser.add_argument("--sandbox-root", default=None)
        opts = parser.parse_args(args[1:])
        state = probe_environment(Path(opts.sandbox_root) if opts.sandbox_root else None)
        print(json.dumps(state, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
        return 0
    if args and args[0] == "cas":
        from pathlib import Path
        from totem_cas import CASRejected, import_receipt, restore_receipt, verify_receipt, stats
        cli = argparse.ArgumentParser(prog="totem-ops cas")
        subs = cli.add_subparsers(dest="action", required=True)
        for task in ("import", "restore", "verify", "stats"):
            s = subs.add_parser(task)
            s.add_argument("--sandbox-root", required=True)
            if task != "stats":
                s.add_argument("--receipt", required=True, help="A prior STAGED_ONLY JSON receipt")
            if task == "import":
                s.add_argument("--source", required=True, help="Existing read-only JAR directory in sandbox")
            elif task == "restore":
                s.add_argument("--destination", required=True, help="New empty sandbox mods folder")
                s.add_argument("--previous-download-seconds", type=float, default=None)
        options = cli.parse_args(args[1:])
        try:
            root = Path(options.sandbox_root)
            receipt = None
            if options.action != "stats":
                receipt_path = Path(options.receipt)
                if (receipt_path.is_symlink() or not receipt_path.is_file()
                        or receipt_path.stat().st_size > 65536):
                    raise CASRejected("invalid_receipt_file")
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            if options.action == "import":
                output = import_receipt(root, Path(options.source), receipt)
            elif options.action == "restore":
                output = restore_receipt(root, Path(options.destination), receipt,
                                         options.previous_download_seconds)
            elif options.action == "verify":
                output = verify_receipt(root, receipt)
            else:
                output = stats(root)
        except (CASRejected, OSError, ValueError, TypeError, KeyError) as exc:
            output = {"status": "BLOCK", "reason": str(exc)[:140]}
        print(json.dumps(output, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
        return 2 if output["status"] in ("BLOCK", "MISS") else 0
    if args and args[0] == "runtime-seed":
        import subprocess
        from pathlib import Path
        from totem_runtime_seed import create_seed, SeedRejected
        p = argparse.ArgumentParser(prog="totem-ops runtime-seed")
        p.add_argument("action", choices=("create",))
        p.add_argument("--source", required=True, help="Read-only existing NeoForge /data directory")
        p.add_argument("--sandbox-root", required=True, help="Owner-created marked agy-sandbox")
        p.add_argument("--seed-dir", required=True, help="New sanitized loader seed inside sandbox")
        p.add_argument("--game-version", required=True)
        p.add_argument("--loader-version", required=True)
        p.add_argument("--image-id", default=None, help="Optional exact cached Docker sha256 image ID")
        opt = p.parse_args(args[1:])
        root = Path(opt.sandbox_root)
        if (root.name != "agy-sandbox" or root.is_symlink()
                or not (root / ".agy-manager-sandbox").is_file()
                or (root / ".agy-manager-sandbox").read_text() != "AGY_TEST_SANDBOX_V1\n"):
            outcome = {"status": "BLOCK", "reason": "sandbox_marker_required"}
        else:
            try:
                image_id = opt.image_id
                if not image_id:
                    cmd = subprocess.run(["docker", "image", "inspect",
                                          "itzg/minecraft-server:java21",
                                          "--format", "{{.Id}}"],
                                         capture_output=True, text=True, timeout=10)
                    if cmd.returncode != 0:
                        raise SeedRejected("docker_image_not_available")
                    image_id = cmd.stdout.strip()
                outcome = create_seed(Path(opt.source), Path(opt.seed_dir), root,
                                      opt.game_version, opt.loader_version, image_id)
            except (SeedRejected, OSError, subprocess.TimeoutExpired, ValueError) as error:
                outcome = {"status": "BLOCK", "reason": str(error)[:150]}
        print(json.dumps(outcome, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
        return 2 if outcome["status"] == "BLOCK" else 0
    if args and args[0] in ("-h", "--help"):
        print("TotemOps 不死圖騰 | Minecraft assistant")
        print("Usage: totem-ops <doctor|inspect|diagnose|plan|plan-deploy|status|solve-and-verify|runtime-seed|cas|preflight|quick|route|maintainer|friend-flow|plugins>")
        print("       totem-ops plugins list | totem-ops plugins run NAME COMMAND --input '{}'")
        print("       totem-ops <command> --help")
        return 0
    return mc_operator.main(args)


if __name__ == "__main__":
    sys.exit(main())
