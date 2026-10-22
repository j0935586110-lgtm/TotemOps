#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Thin, provider-neutral Minecraft CLI.

Offline reads by default. User-opted sandbox mode may download approved
Modrinth artifacts and launch a disposable Docker server; never a live world.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from mc_oss_bridge import doctor, plan, status
from mc_package_inspector import InputBlocked, inspect_log, inspect_path
from totem_repair_recipes import build_fixplan, format_human_plan


def _get_git_branch() -> str:
    for candidate in [Path.cwd(), Path(__file__).resolve().parent.parent]:
        try:
            proc = subprocess.run(["git", "-C", str(candidate), "rev-parse", "--abbrev-ref", "HEAD"],
                                  capture_output=True, text=True, timeout=5)
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip()
        except Exception:
            pass
    return "unknown"


def _check_receipt_path_safety(p: Path) -> None:
    if not p.is_absolute():
        raise ValueError("receipt_path_rejected")
    if p.is_symlink() or os.path.islink(p):
        raise ValueError("receipt_path_rejected")
    norm_p = os.path.abspath(str(p))
    forbidden_prefixes = ("/etc", "/usr", "/boot", "/sys", "/proc", "/dev", "/bin", "/sbin", "/lib", "/lib64")
    for pref in forbidden_prefixes:
        if norm_p == pref or norm_p.startswith(pref + "/"):
            raise ValueError("receipt_path_rejected")
    try:
        home_ssh = os.path.abspath(str(Path.home() / ".ssh"))
    except (RuntimeError, OSError):
        home_ssh = None
    if home_ssh and (norm_p == home_ssh or norm_p.startswith(home_ssh + "/")):
        raise ValueError("receipt_path_rejected")
    curr = p.parent
    while curr != curr.parent:
        if curr.is_symlink() or os.path.islink(curr):
            raise ValueError("receipt_path_rejected")
        if curr.exists():
            break
        curr = curr.parent


def write_receipt(receipt_path: Path, result: dict, exit_code: int) -> None:
    _check_receipt_path_safety(receipt_path)
    receipt_data = dict(result)
    receipt_data["receipt_schema"] = 1
    receipt_data["created_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    receipt_data["exit_code"] = exit_code
    receipt_data["branch"] = _get_git_branch()

    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    temp_file = tempfile.NamedTemporaryFile("w", dir=receipt_path.parent, delete=False, encoding="utf-8")
    temp_name = temp_file.name
    try:
        json.dump(receipt_data, temp_file, ensure_ascii=False, indent=2)
        temp_file.flush()
        os.fsync(temp_file.fileno())
        temp_file.close()
        os.replace(temp_name, receipt_path)
    except Exception:
        if os.path.exists(temp_name):
            try:
                os.unlink(temp_name)
            except OSError:
                pass
        raise


def compute_exit_code(result: dict, require_verified: bool = False, is_solve_and_verify: bool = True) -> int:
    status = result.get("status")
    code = result.get("code")
    if is_solve_and_verify:
        if require_verified:
            return 0 if status == "VERIFIED_ON_SANDBOX" else 4
        if status == "VERIFIED_ON_SANDBOX":
            return 0
        if status == "BLOCK" or code == "BLOCK":
            return 2
        if status in ("PLAN_ONLY", "STAGED_ONLY"):
            return 3
        return 5
    return 2 if status == "BLOCK" or code == "BLOCK" else 0


def summarize_package(path: Path) -> dict:
    result = inspect_path(path)
    return {
        "status": result["status"],
        "analyzed": result["files_analyzed"],
        "rejected": result["files_rejected"][:8],
        "mods": [
            {"file": p["file"], "id": m["id"], "version": m["version"], "loader": m["loader"]}
            for p in result["packages"] for m in p["mods"]
        ][:50],
        "findings": result["findings"][:20],
        "maintenance": "UNKNOWN_NOT_CHECKED_ONLINE",
        "not_verified": ["target_runtime_compatibility", "actual_server_install"],
    }


def diagnose(path: Path) -> dict:
    report = inspect_log(path)
    hints = []
    for signal in report["signals"][:12]:
        kind = signal["kind"]
        hints.append({
            "line": signal["line"],
            "signal": kind,
            "status": "SUSPECTED",
            "next": (
                "Compare missing class to installed dependencies and mod versions"
                if kind == "missing_class"
                else "Review runtime memory/Java limits and recent changes"
                if kind == "out_of_memory"
                else "Correlate stack trace and changes with installed mods"
            ),
        })
    return {
        "status": "PASS",
        "confirmed_root_cause": None,
        "log_sha256": report["file_sha256"],
        "clues": hints,
        "omitted_signals": max(0, len(report["signals"]) - len(hints)),
        "next_step": "Check installed mod manifest, then reproduce in disposable test server",
    }


def plan_deploy(version: str, loader: str, memory: str, port: int) -> dict:
    if not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", version):
        return {"status": "BLOCK", "reason": "invalid_minecraft_version"}
    if loader not in {"VANILLA", "FORGE", "NEOFORGE"}:
        return {"status": "BLOCK", "reason": "unsupported_loader"}
    if not re.fullmatch(r"(?:[1-9]|[12][0-9]|3[0-2])G", memory):
        return {"status": "BLOCK", "reason": "memory_outside_local_policy_1_to_32G"}
    if not 1024 <= port <= 65535:
        return {"status": "BLOCK", "reason": "invalid_port"}
    # This is a generated proposal, not a deployed server.
    compose = (
        "services:\n"
        "  minecraft:\n"
        "    image: itzg/minecraft-server:java21\n"
        "    environment:\n"
        '      EULA: "TRUE"\n'
        f'      TYPE: "{loader}"\n'
        f'      VERSION: "{version}"\n'
        f'      MEMORY: "{memory}"\n'
        "    ports:\n"
        f'      - "{port}:25565"\n'
        "    volumes:\n"
        "      - ./data:/data\n"
    )
    return {
        "status": "PLAN_ONLY",
        "compose": compose,
        "preconditions": [
            "User accepts Mojang EULA",
            "Docker Compose available, suitable RAM, and free port",
            "Validate exact loader and mod versions; EULA acknowledgment belongs to user",
            "Run only in an isolated test environment first",
        ],
        "deployed": False,
    }



def solve_and_verify(log: Path, project: str | None, game_version: str | None,
                     loader: str | None, sandbox_root: Path | None,
                     execute_sandbox: bool = False, max_wait: int = 210,
                     version_id: str | None = None, stage_only: bool = False,
                     expected_receipt: Path | None = None,
                     local_cache: Path | None = None,
                     loader_version: str | None = None, loader_seed: Path | None = None,
                     cold_baseline_seconds: float = 0,
                     cas_enabled: bool = False,
                     receipt_out: Path | None = None,
                     require_verified: bool = False,
                     infer_project: bool = False,
                     reuse_runtime: bool = False) -> dict:
    """One user-invoked flow. Never change a live server or infer a Modrinth ID."""
    import hashlib
    import os
    import shutil
    import subprocess
    import tempfile
    import time
    import uuid
    from totem_local_cache import (LocalCacheRejected, clone_if_faster,
                                   discover_verified_cache)
    from totem_runtime_seed import prepare_seed, SeedRejected
    from totem_cas import (CASRejected, restore_receipt as cas_restore,
                           import_receipt as cas_import)

    started_at = time.monotonic()
    overall_deadline = started_at + max_wait

    def server_signals(container_name: str) -> dict:
        # Return bounded Boolean facts, never expose raw Minecraft logs/tokens.
        try:
            p = subprocess.run(["docker", "logs", "--tail", "50", container_name],
                               capture_output=True, text=True, timeout=7)
            log_tail = (p.stdout + p.stderr)[-16000:]
            return {"readable": p.returncode == 0,
                    "neoforge_loaded": "NeoForge mod loading" in log_tail,
                    "world_initialization_seen": "No existing world data" in log_tail,
                    "protocol_done_logged": bool(re.search(r"Done \([\d.]+s\)! For help", log_tail)),
                    "java_oom_seen": "OutOfMemoryError" in log_tail}
        except (subprocess.TimeoutExpired, OSError):
            return {"readable": False}

    evidence = diagnose(log)
    result = {
        "status": "PLAN_ONLY", "on_demand": True,
        "confirmed_root_cause": evidence["confirmed_root_cause"],
        "clues": evidence["clues"], "log_sha256": evidence["log_sha256"],
        "sandbox_verified": False, "production_modified": False,
        "protected_zone_mounted": False, "write_scope": "ephemeral_managed_modrinth_only",
        "stage": "diagnosed",
        "recipe_schema": 1, "tool_version": "totemops-p0",
    }
    if receipt_out is not None:
        try:
            _check_receipt_path_safety(receipt_out)
        except ValueError:
            return {"status": "BLOCK", "reason": "receipt_path_rejected"}

    if infer_project:
        from totem_log_extract import extract_missing_dependency
        extraction = extract_missing_dependency(log)
        if not project:
            if extraction.get("status") == "OK":
                project = extraction["project"]
                result["project_inference"] = extraction
            else:
                return {
                    **result,
                    "status": "BLOCK",
                    "reason": "ambiguous_project_inference",
                    "project_inference": extraction,
                    "candidates": extraction.get("candidates", []),
                }
        else:
            result["project_inference"] = extraction

    if not (project and game_version and loader):
        result["reason"] = "project_game_version_and_loader_required_for_download"
        result["next_step"] = "Choose an actual Modrinth project and target versions"
        return result
    if not re.fullmatch(r"[A-Za-z0-9_-]{2,64}", project):
        return {"status": "BLOCK", "reason": "invalid_modrinth_project"}
    if not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", game_version):
        return {"status": "BLOCK", "reason": "invalid_game_version"}
    if loader not in ("forge", "neoforge", "fabric", "quilt"):
        return {"status": "BLOCK", "reason": "invalid_loader"}
    if version_id is not None and not re.fullmatch(r"[A-Za-z0-9_-]{6,64}", version_id):
        return {"status": "BLOCK", "reason": "invalid_version_id"}
    if stage_only and not execute_sandbox:
        return {"status": "BLOCK", "reason": "stage_only_requires_execute_sandbox"}
    if local_cache is not None and expected_receipt is None:
        return {"status": "BLOCK", "reason": "local_cache_requires_stage_receipt"}
    if loader_version is not None and not re.fullmatch(r"\d+(?:\.\d+){2,3}", loader_version):
        return {"status": "BLOCK", "reason": "invalid_loader_version"}
    if loader_seed is not None and (loader != "neoforge" or loader_version is None):
        return {"status": "BLOCK", "reason": "loader_seed_requires_pinned_neoforge"}
    if cold_baseline_seconds < 0 or cold_baseline_seconds > 3600:
        return {"status": "BLOCK", "reason": "invalid_cold_baseline_seconds"}
    if not 30 <= max_wait <= 360:
        return {"status": "BLOCK", "reason": "invalid_timeout"}
    expected_hashes = None
    if expected_receipt is not None:
        if (expected_receipt.is_symlink() or not expected_receipt.is_file()
                or expected_receipt.stat().st_size > 65536):
            return {"status": "BLOCK", "reason": "invalid_expected_receipt"}
        raw = expected_receipt.read_bytes()
        try:
            past = json.loads(raw)
            if (past["status"] != "STAGED_ONLY" or
                    (past["candidate"]["project"], past["candidate"]["version_id"],
                     past["candidate"]["game_version"], past["candidate"]["loader"])
                    != (project, version_id, game_version, loader)):
                raise ValueError("expected_receipt_target_mismatch")
            expected_hashes = {x["name"]: x["sha256"] for x in past["staged_jars"]}
            if (not expected_hashes or len(expected_hashes) != len(past["staged_jars"])
                    or any(not re.fullmatch(r"[a-f0-9]{64}", v) for v in expected_hashes.values())):
                raise ValueError("expected_receipt_invalid_hashes")
            result["expected_receipt_sha256"] = hashlib.sha256(raw).hexdigest()
        except (KeyError, ValueError, TypeError):
            return {"status": "BLOCK", "reason": "invalid_or_mismatched_expected_receipt"}
    result["candidate"] = {"project": project, "game_version": game_version,
                           "loader": loader, "version_id": version_id,
                           "source": "explicit_user_selection"}
    result["existing_tool"] = "mc-image-helper modrinth"
    result["dependency_option"] = "REQUIRED"
    result["stage"] = "candidate_selected"
    if not execute_sandbox:
        result["reason"] = "sandbox_not_requested"
        result["next_step"] = "Use --execute-sandbox with an owner-created agy-sandbox directory and marker"
        return result
    if sandbox_root is None or sandbox_root.is_symlink() or sandbox_root.name != "agy-sandbox":
        return {**result, "status": "BLOCK", "reason": "sandbox_root_not_allowlisted"}
    protected_names = {
        "world", "world_nether", "world_the_end", "kubejs", "config",
        "playerdata", "datapacks", "resourcepacks", "saves", "plugins",
    }
    # Never mount a subfolder from the real world or local custom files.
    if any(part.lower() in protected_names or part.lower().startswith("barian_")
           for part in sandbox_root.resolve().parts):
        return {**result, "status": "BLOCK", "reason": "sandbox_inside_protected_zone"}
    marker = sandbox_root / ".agy-manager-sandbox"
    if not sandbox_root.is_dir() or marker.is_symlink() or not marker.is_file():
        return {**result, "status": "BLOCK", "reason": "sandbox_marker_missing"}
    if marker.read_text(encoding="utf-8") != "AGY_TEST_SANDBOX_V1\n":
        return {**result, "status": "BLOCK", "reason": "sandbox_marker_invalid"}
    # Machine capability gate: a model cannot bypass this merely by asking to run.
    from totem_env import preflight
    gate = preflight(sandbox_root, full_server=not stage_only)
    result["environment_preflight"] = gate
    if gate["status"] != "ALLOW":
        return {**result, "status": "BLOCK", "reason": "environment_not_approved",
                "blockers": gate["blockers"]}
    # Docker must already exist; do not auto-install or auto-pull images.
    if not shutil.which("docker"):
        return {**result, "status": "BLOCK", "reason": "docker_not_installed"}
    image = "itzg/minecraft-server:java21"
    try:
        probe = subprocess.run(["docker", "image", "inspect", image, "--format", "{{.Id}}"],
                               stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=12)
    except (subprocess.TimeoutExpired, OSError):
        return {**result, "status": "BLOCK", "reason": "docker_image_inspection_failed"}
    if probe.returncode != 0:
        return {**result, "status": "BLOCK", "reason": "docker_image_not_cached"}
    result["docker_image_digest"] = probe.stdout.strip()
    result["docker_image_tag"] = image
    with tempfile.TemporaryDirectory(prefix="agy-run-", dir=sandbox_root) as tmp:
        run_dir = Path(tmp)
        (run_dir / "data" / "mods").mkdir(parents=True)
        container = "agy-sandbox-" + uuid.uuid4().hex[:12]
        result["stage"] = "downloading_into_ephemeral_managed_zone"
        helper = [
            "docker", "run", "--rm", "--pull", "never", "--network", "bridge",
            "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--pids-limit", "128",
            "--tmpfs", "/tmp:rw,nosuid,nodev,size=256m",
            "--memory", "768m", "--cpus", "1.5", "--user", f"{__import__('os').getuid()}:{__import__('os').getgid()}",
            # mc-image-helper creates a mods/ subfolder under --output-directory.
            "--mount", f"type=bind,src={run_dir / 'data'},dst=/staging",
            "--entrypoint", "mc-image-helper", image,
            "modrinth", f"--game-version={game_version}", f"--loader={loader}",
            f"--projects={project}:{version_id}" if version_id else f"--projects={project}",
            "--download-dependencies=REQUIRED",
            "--output-directory=/staging",
        ]
        result["replay"] = {
            "project": project, "version_id": version_id, "game_version": game_version,
            "loader": loader, "helper": "mc-image-helper modrinth",
            "download_dependencies": "REQUIRED", "docker_image_digest": result["docker_image_digest"],
        }
        copied_locally = False
        if cas_enabled and expected_hashes is not None:
            try:
                cached = cas_restore(sandbox_root, run_dir / "data" / "mods", past,
                                     past.get("download_seconds"))
            except CASRejected as error:
                return {**result, "status": "BLOCK", "reason": "cas_invalid",
                        "detail": str(error)[:120]}
            result["cas_lookup"] = cached
            if cached["status"] == "CAS_RESTORED":
                copied_locally = True
                result["artifact_source"] = "sha256_cas"
                result["download_seconds"] = 0
                result["download_exit_code"] = None
        source = local_cache
        if not copied_locally and expected_hashes is not None and source is None:
            source = discover_verified_cache(sandbox_root, expected_hashes)
        if source is not None and not copied_locally:
            try:
                reuse = clone_if_faster(source, sandbox_root, run_dir / "data" / "mods",
                                        expected_hashes, past.get("download_seconds"))
            except LocalCacheRejected as error:
                return {**result, "status": "BLOCK", "reason": str(error)}
            result["reuse_decision"] = reuse
            if reuse["decision"] == "LOCAL_COPY":
                copied_locally = True
                result["artifact_source"] = "verified_local_cache"
                result["download_seconds"] = 0
                result["download_exit_code"] = None
        if not copied_locally:
            result["artifact_source"] = "modrinth_download"
            download_started = time.monotonic()
            remaining = overall_deadline - download_started
            if remaining <= 1:
                return {**result, "status": "BLOCK", "reason": "total_budget_exhausted_before_download"}
            try:
                downloaded = subprocess.run(helper, stdin=subprocess.DEVNULL,
                                            capture_output=True, timeout=min(remaining, 180))
            except subprocess.TimeoutExpired:
                return {**result, "status": "BLOCK", "reason": "dependency_download_timeout"}
            result["download_seconds"] = round(time.monotonic() - download_started, 3)
            result["download_exit_code"] = downloaded.returncode
            if downloaded.returncode != 0:
                return {**result, "status": "BLOCK", "reason": "dependency_downloader_failed",
                        "exit_code": downloaded.returncode}
        jars = list((run_dir / "data" / "mods").glob("*.jar"))
        if not jars:
            return {**result, "status": "BLOCK", "reason": "download_produced_no_jar"}
        inventory = inspect_path(run_dir / "data" / "mods")
        if inventory["status"] != "PASS":
            return {**result, "status": "BLOCK", "reason": "downloaded_metadata_not_verified",
                    "file_count": len(jars)}
        # Never treat a successful download as proof of a compatible modpack.
        if any(item["kind"] in {"duplicate_mod_id", "declared_incompatible",
                                 "mixed_mod_loaders"} for item in inventory["findings"]):
            return {**result, "status": "BLOCK", "reason": "declared_mod_conflict"}
        if any(mod["loader"] != loader for package in inventory["packages"]
               for mod in package["mods"]):
            return {**result, "status": "BLOCK", "reason": "downloaded_loader_mismatch"}
        result["staged_jars"] = sorted([{
            "name": p["file"], "sha256": p["sha256"],
            "mods": [{"id": m["id"], "version": m["version"], "loader": m["loader"]}
                     for m in p["mods"][:8]],
        } for p in inventory["packages"][:40]], key=lambda x: x["name"])
        result["staged_count"] = len(jars)
        if expected_hashes is not None:
            actual_hashes = {x["name"]: x["sha256"] for x in result["staged_jars"]}
            if actual_hashes != expected_hashes:
                return {**result, "status": "BLOCK", "reason": "artifact_sha256_drift",
                        "expected_files": sorted(expected_hashes),
                        "actual_files": sorted(actual_hashes)}
            result["receipt_match"] = True
        result["dependency_findings"] = inventory["findings"][:20]
        if cas_enabled:
            try:
                saved = cas_import(sandbox_root, run_dir / "data" / "mods",
                                   {**result, "status": "STAGED_ONLY"})
            except CASRejected as error:
                return {**result, "status": "BLOCK", "reason": "cas_import_failed",
                        "detail": str(error)[:120]}
            result["cas_store"] = saved
        result["total_seconds"] = round(time.monotonic() - started_at, 3)
        if stage_only:
            return {**result, "status": "STAGED_ONLY",
                    "stage": "downloaded_and_inspected", "sandbox_verified": False,
                    "next_step": "Run the same pinned selection in sandbox server mode"}
        runtime_reuse_info = None
        if reuse_runtime and loader == "neoforge":
            from totem_runtime_seed import prepare_seed, SeedRejected
            target_seed = None
            effective_loader_version = loader_version
            if loader_version:
                target_seed = sandbox_root / "runtime-seed" / f"neoforge-{loader_version}"
            else:
                rt_dir = sandbox_root / "runtime-seed"
                if rt_dir.is_dir() and not rt_dir.is_symlink():
                    for child in sorted(rt_dir.iterdir()):
                        if child.is_dir() and not child.is_symlink() and child.name.startswith("neoforge-"):
                            m_file = child / "totemops-runtime-seed.json"
                            if m_file.is_file() and not m_file.is_symlink():
                                try:
                                    m_data = json.loads(m_file.read_text(encoding="utf-8"))
                                    if m_data.get("game_version") == game_version and m_data.get("type") == "NEOFORGE":
                                        target_seed = child
                                        effective_loader_version = m_data.get("loader_version")
                                        break
                                except Exception:
                                    pass

            if target_seed is not None and target_seed.is_dir():
                try:
                    reuse_prep = prepare_seed(
                        target_seed, run_dir / "data", sandbox_root,
                        game_version, effective_loader_version,
                        result["docker_image_digest"],
                        cold_baseline_seconds
                    )
                except SeedRejected as exc:
                    return {**result, "status": "BLOCK",
                            "reason": "runtime_seed_invalid", "detail": str(exc)[:100]}

                if reuse_prep.get("status") == "LOCAL_LOADER_CLONE":
                    runtime_reuse_info = {
                        "decision": "REUSED",
                        "path": str(target_seed),
                        "loader_version": str(effective_loader_version),
                    }
                else:
                    runtime_reuse_info = {
                        "decision": "MISSING",
                        "path": str(target_seed),
                        "loader_version": str(effective_loader_version or "unknown"),
                    }
            else:
                missing_path = target_seed if target_seed else (sandbox_root / "runtime-seed" / f"neoforge-{loader_version or 'unknown'}")
                runtime_reuse_info = {
                    "decision": "MISSING",
                    "path": str(missing_path),
                    "loader_version": str(loader_version or "unknown"),
                }
            result["runtime_reuse"] = runtime_reuse_info
        elif loader == "neoforge" and loader_version:
            seed = loader_seed if loader_seed is not None else (
                sandbox_root / "loader-seeds" / f"neoforge-{game_version}-{loader_version}")
            try:
                reuse_runtime = prepare_seed(seed, run_dir / "data", sandbox_root,
                                             game_version, loader_version,
                                             result["docker_image_digest"],
                                             cold_baseline_seconds)
            except SeedRejected as exc:
                return {**result, "status": "BLOCK",
                        "reason": "runtime_seed_invalid", "detail": str(exc)[:100]}
            result["runtime_reuse"] = reuse_runtime
        result["stage"] = "ephemeral_server_starting"
        # Deliberately no -p: isolated Docker container does not expose a server on the host.
        active_loader_version = loader_version or (effective_loader_version if (reuse_runtime and runtime_reuse_info and runtime_reuse_info.get("decision") == "REUSED") else None)
        container_cmd = [
            "docker", "run", "-d", "--rm", "--pull", "never", "--name", container,
            "--network", "bridge", "--memory", "3g", "--cpus", "2",
            "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--tmpfs", "/tmp:rw,nosuid,nodev,size=256m",
            "--tmpfs", "/run:rw,nosuid,nodev,size=64m",
            "--tmpfs", "/var/tmp:rw,nosuid,nodev,size=64m",
            "--pids-limit", "256", "--label", "totemops.sandbox=true",
            "--user", f"{os.getuid()}:{os.getgid()}",
            "--mount", f"type=bind,src={run_dir / 'data'},dst=/data",
            "-e", "EULA=TRUE", "-e", f"TYPE={loader.upper()}",
            "-e", f"VERSION={game_version}", "-e", "MEMORY=2G",
            "-e", "SKIP_NSSWITCH_CONF=TRUE", "-e", "SKIP_CHOWN_DATA=TRUE",
            "-e", "VIEW_DISTANCE=3", "-e", "SIMULATION_DISTANCE=3",
            "-e", "LEVEL_TYPE=FLAT",
            *(["-e", f"NEOFORGE_VERSION={active_loader_version}"]
              if loader == "neoforge" and active_loader_version else []),
            image,
        ]
        started = False
        attempted_start = False
        try:
            remaining = overall_deadline - time.monotonic()
            if remaining <= 1:
                return {**result, "status": "BLOCK", "reason": "total_budget_exhausted_before_server"}
            attempted_start = True
            try:
                process = subprocess.run(container_cmd, stdin=subprocess.DEVNULL,
                                         capture_output=True, timeout=min(25, remaining))
            except (subprocess.TimeoutExpired, OSError):
                return {**result, "status": "BLOCK", "reason": "sandbox_container_start_timeout_or_error",
                        "total_seconds": round(time.monotonic() - started_at, 3)}
            if process.returncode != 0:
                return {**result, "status": "BLOCK", "reason": "sandbox_container_start_failed",
                        "exit_code": process.returncode,
                        "total_seconds": round(time.monotonic() - started_at, 3)}
            started = True
            while time.monotonic() < overall_deadline:
                try:
                    monitor = subprocess.run(
                        ["docker", "exec", container, "mc-monitor", "status",
                         "-host", "127.0.0.1", "-port", "25565", "-json", "-timeout", "3s"],
                        stdin=subprocess.DEVNULL, capture_output=True, text=True,
                        timeout=min(10, max(1, overall_deadline - time.monotonic())))
                except (subprocess.TimeoutExpired, OSError):
                    return {**result, "status": "BLOCK", "reason": "monitor_unreachable_or_timed_out",
                            "total_seconds": round(time.monotonic() - started_at, 3)}
                if monitor.returncode == 0:
                    try:
                        data = json.loads(monitor.stdout)
                        server = data.get("server_info") if isinstance(data, dict) else None
                        version = server.get("version") if isinstance(server, dict) else None
                        if (isinstance(version, dict)
                                and version.get("name") == game_version
                                and type(version.get("protocol")) is int):
                            result["status"] = "VERIFIED_ON_SANDBOX"
                            result["sandbox_verified"] = True
                            result["stage"] = "minecraft_protocol_ready"
                            result["tested_game_version"] = game_version
                            result["total_seconds"] = round(time.monotonic() - started_at, 3)
                            result["next_step"] = "Owner reviews exact mod versions and feature-level tests"

                            if reuse_runtime and loader == "neoforge" and runtime_reuse_info and runtime_reuse_info.get("decision") == "MISSING":
                                from totem_runtime_seed import create_seed, SeedRejected
                                stored_version = loader_version
                                if not stored_version:
                                    installer_manifest = run_dir / "data" / ".neoforge-manifest.json"
                                    if installer_manifest.is_file() and not installer_manifest.is_symlink():
                                        try:
                                            m_data = json.loads(installer_manifest.read_text(encoding="utf-8"))
                                            stored_version = m_data.get("forgeVersion")
                                        except Exception:
                                            pass
                                if stored_version:
                                    dest_seed = sandbox_root / "runtime-seed" / f"neoforge-{stored_version}"
                                    if not dest_seed.exists() and not dest_seed.is_symlink():
                                        try:
                                            create_seed(
                                                run_dir / "data", dest_seed, sandbox_root,
                                                game_version, stored_version,
                                                result["docker_image_digest"]
                                            )
                                            result["runtime_reuse"] = {
                                                "decision": "STORED",
                                                "path": str(dest_seed),
                                                "loader_version": str(stored_version),
                                            }
                                        except (SeedRejected, OSError):
                                            pass

                            return result
                    except ValueError:
                        pass
                # Container exited? Stop waiting; only report the cause, not raw log or tokens.
                try:
                    running = subprocess.run(
                        ["docker", "inspect", "-f", "{{.State.Running}}", container],
                        stdin=subprocess.DEVNULL, capture_output=True, text=True,
                        timeout=min(10, max(1, overall_deadline - time.monotonic())))
                except (subprocess.TimeoutExpired, OSError):
                    return {**result, "status": "BLOCK", "reason": "container_state_unavailable",
                            "total_seconds": round(time.monotonic() - started_at, 3)}
                if running.returncode != 0 or running.stdout.strip() != "true":
                    return {**result, "status": "BLOCK", "reason": "sandbox_server_exited",
                            "server_signals": server_signals(container),
                            "total_seconds": round(time.monotonic() - started_at, 3)}
                time.sleep(4)
            return {**result, "status": "BLOCK", "reason": "sandbox_readiness_timeout",
                    "server_signals": server_signals(container),
                    "total_seconds": round(time.monotonic() - started_at, 3)}
        finally:
            if attempted_start:
                if started:
                    try:
                        subprocess.run(["docker", "stop", "--timeout", "10", container],
                                       stdin=subprocess.DEVNULL, capture_output=True, timeout=15)
                    except (subprocess.TimeoutExpired, OSError):
                        pass  # The force-remove attempt still follows.
                try:
                    subprocess.run(["docker", "rm", "--force", container],
                                   stdin=subprocess.DEVNULL, capture_output=True, timeout=10)
                except (subprocess.TimeoutExpired, OSError):
                    pass  # Report orphan risk separately to host operator.



def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Minecraft manager thin CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    for cmd in ("inspect", "diagnose"):
        sub.add_parser(cmd).add_argument("path")
    fp = sub.add_parser(
        "fixplan",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exit codes:
  0 = Unused (fixplan never represents a verified fix)
  2 = BLOCK (safety gate blocked, invalid argument, or broken catalog)
  3 = PLAN_ONLY, NO_RECIPE, or REVIEW_REQUIRED (no actions executed)
""",
    )
    fp.add_argument("path")
    fp.add_argument("--json", action="store_true", help="Emit JSON output for agents")
    s = sub.add_parser("status")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=25565)
    p = sub.add_parser("plan")
    p.add_argument("task", choices=("modpack-versioning", "modrinth-dependencies",
                                    "client-sync", "server-status", "server-control"))
    d = sub.add_parser("plan-deploy")
    d.add_argument("--version", required=True)
    d.add_argument("--loader", choices=("VANILLA", "FORGE", "NEOFORGE"), required=True)
    d.add_argument("--memory", required=True)
    d.add_argument("--port", type=int, default=25565)
    v = sub.add_parser(
        "solve-and-verify",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exit codes:
  0 = VERIFIED_ON_SANDBOX (successful server verification)
  2 = BLOCK (safety gate blocked, invalid argument, or policy violation)
  3 = PLAN_ONLY or STAGED_ONLY (operation planned or staged, but not verified)
  4 = Required verification not achieved (--require-verified given and status != VERIFIED_ON_SANDBOX)
  5 = Other (execution attempted but verification was not achieved)
"""
    )
    v.add_argument("--log", required=True)
    v.add_argument("--project", default=None, help="Explicitly selected Modrinth ID/slug")
    v.add_argument("--game-version", default=None)
    v.add_argument("--loader", choices=("forge", "neoforge", "fabric", "quilt"))
    v.add_argument("--sandbox-root", default=None)
    v.add_argument("--execute-sandbox", action="store_true",
                   help="Explicitly opt in to ephemeral Docker test; never deploy live")
    v.add_argument("--max-wait", type=int, default=210)
    v.add_argument("--version-id", default=None, help="Pin an exact Modrinth version ID")
    v.add_argument("--stage-only", action="store_true", help="Download/inspect only; skip expensive server boot")
    v.add_argument("--expected-receipt", default=None,
                   help="Require exact staged JAR filenames/SHA-256 from a previous JSON receipt")
    v.add_argument("--local-cache", default=None,
                   help="Optional already-downloaded JAR folder inside marked sandbox; auto-discovers if omitted")
    v.add_argument("--loader-version", default=None,
                   help="Pin NeoForge loader version, e.g. 21.1.259")
    v.add_argument("--loader-seed", default=None,
                   help="Optional verified local NeoForge runtime seed; discover from sandbox by default")
    v.add_argument("--cold-baseline-seconds", type=float, default=0.0,
                   help="Actual prior cold install duration for local-vs-download comparison")
    v.add_argument("--cas", action="store_true",
                   help="Opt in to persistent SHA-256 deduplicated JAR cache inside marked sandbox")
    v.add_argument("--require-verified", action="store_true",
                   help="Require VERIFIED_ON_SANDBOX; exits with code 4 if verification is not achieved")
    v.add_argument("--receipt-out", default=None,
                   help="Write atomic JSON execution receipt to an absolute path")
    v.add_argument("--infer-project", action="store_true",
                   help="Infer missing dependency Modrinth project deterministically from log")
    v.add_argument("--reuse-runtime", action="store_true",
                   help="Reuse validated local NeoForge runtime seed from sandbox across runs")
    sub.add_parser("sync-publish")
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            result = doctor()
        elif args.command == "inspect":
            result = summarize_package(Path(args.path))
        elif args.command == "diagnose":
            result = diagnose(Path(args.path))
        elif args.command == "fixplan":
            result = build_fixplan(Path(args.path))
        elif args.command == "status":
            result = status(args.host, args.port)
        elif args.command == "plan":
            result = plan(args.task)
        elif args.command == "plan-deploy":
            result = plan_deploy(args.version, args.loader, args.memory, args.port)
        elif args.command == "solve-and-verify":
            receipt_out_path = Path(args.receipt_out) if args.receipt_out else None
            result = solve_and_verify(Path(args.log), args.project, args.game_version,
                                      args.loader, Path(args.sandbox_root) if args.sandbox_root else None,
                                      args.execute_sandbox, args.max_wait, args.version_id,
                                      args.stage_only,
                                      Path(args.expected_receipt) if args.expected_receipt else None,
                                      Path(args.local_cache) if args.local_cache else None,
                                      args.loader_version,
                                      Path(args.loader_seed) if args.loader_seed else None,
                                      args.cold_baseline_seconds, args.cas,
                                      receipt_out=receipt_out_path,
                                      require_verified=args.require_verified,
                                      infer_project=args.infer_project,
                                      reuse_runtime=args.reuse_runtime)
        else:
            result = {
                "status": "BLOCK",
                "reason": "sync_backend_contract_not_verified",
                "action": "no_network_request_sent",
            }
    except (InputBlocked, OSError, ValueError, TypeError) as err:
        result = {"status": "BLOCK", "reason": str(err)[:120]}

    require_verified = getattr(args, "require_verified", False)
    is_solve_and_verify = (getattr(args, "command", None) == "solve-and-verify")
    if getattr(args, "command", None) == "fixplan":
        exit_code = 2 if (result.get("status") == "BLOCK" or result.get("code") == "BLOCK") else 3
    else:
        exit_code = compute_exit_code(result, require_verified=require_verified, is_solve_and_verify=is_solve_and_verify)

    receipt_out_arg = getattr(args, "receipt_out", None)
    if receipt_out_arg and result.get("reason") != "receipt_path_rejected":
        try:
            write_receipt(Path(receipt_out_arg), result, exit_code)
        except ValueError:
            result = {"status": "BLOCK", "reason": "receipt_path_rejected"}
            exit_code = compute_exit_code(result, require_verified=require_verified, is_solve_and_verify=is_solve_and_verify)

    if getattr(args, "command", None) == "fixplan" and not getattr(args, "json", False):
        print(format_human_plan(result))
        return exit_code

    print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
