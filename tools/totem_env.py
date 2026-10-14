# SPDX-License-Identifier: Apache-2.0
"""TotemOps environmental preflight: read-only, stdlib, fail closed.

This is a capability check, NOT attestation that a VM is safe or Docker
cannot affect a host. It never executes user-supplied commands.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from pathlib import Path

STAGE_MEM_MB = 768
STAGE_DISK_MB = 2048
RUN_MEM_MB = 4096
RUN_DISK_MB = 8192
RUN_CPUS = 2
VM_TYPES = {"kvm", "qemu", "vmware", "oracle", "microsoft", "xen",
            "bhyve", "parallels", "apple", "bochs", "amazon", "google"}


def _memory_mb():
    try:
        with open("/proc/meminfo", encoding="ascii") as stream:
            fields = {k.rstrip(":"): int(v.split()[0]) for k, v in
                      (line.strip().split(":", 1) for line in stream if ":" in line)}
        free = fields.get("MemAvailable", 0) // 1024
        # Cgroups can have far less memory than the host reports.
        try:
            bound = (Path("/sys/fs/cgroup/memory.max")).read_text().strip()
            current = int((Path("/sys/fs/cgroup/memory.current")).read_text().strip())
            if bound != "max":
                free = min(free, max(0, (int(bound)-current)//(1024*1024)))
        except (ValueError, OSError):
            pass
        return max(0, free)
    except (ValueError, OSError):
        return 0


def _cpu_count():
    cpus = os.cpu_count() or 0
    try:
        quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()[:2]
        if quota != "max":
            cpus = min(cpus, int(quota) // int(period))
    except (ValueError, OSError, ZeroDivisionError):
        pass
    return max(0, cpus)


def _disk_mb(path: Path):
    try:
        s = os.statvfs(path)
        return s.f_bavail * s.f_frsize // (1024 * 1024)
    except OSError:
        return 0


def _virt_type():
    if platform.system() != "Linux":
        return "unknown"
    detect = shutil.which("systemd-detect-virt")
    if not detect:
        return "unknown"
    try:
        p = subprocess.run([detect], capture_output=True, text=True, timeout=3)
        val = p.stdout.strip().lower()
        if p.returncode == 0 and val in VM_TYPES:
            return "vm_detected"  # systemd heuristic, NOT cryptographic proof
        if p.returncode == 0 and val:
            return "container_or_other"
        if p.returncode == 1 and val == "none":
            return "physical_detected"
        return "unknown"
    except (subprocess.TimeoutExpired, OSError):
        return "unknown"


def probe_environment(sandbox_root: Path | None = None) -> dict:
    """Short bounded probes; no Docker run, writes, or network calls."""
    root = sandbox_root if sandbox_root is not None else Path.cwd()
    virt = _virt_type()
    reasons = []
    if sandbox_root is None:
        reasons.append("sandbox_not_selected")
    else:
        marker = sandbox_root / ".agy-manager-sandbox"
        if (sandbox_root.name != "agy-sandbox" or sandbox_root.is_symlink()
                or not sandbox_root.is_dir() or marker.is_symlink()
                or not marker.is_file()):
            reasons.append("sandbox_marker_not_validated")
        else:
            try:
                if marker.read_bytes() != b"AGY_TEST_SANDBOX_V1\n":
                    reasons.append("sandbox_marker_not_validated")
            except OSError:
                reasons.append("sandbox_marker_not_validated")
    docker = shutil.which("docker")
    rootless = False
    reachable = False
    if platform.system() != "Linux":
        reasons.append("linux_only_sandbox")
    if not docker:
        reasons.append("docker_missing")
    # Remote daemon resources and location may differ from those measured locally.
    if os.environ.get("DOCKER_CONTEXT", "") not in ("", "default"):
        reasons.append("docker_context_not_local")
    host = os.environ.get("DOCKER_HOST", "")
    if host and not host.startswith("unix:///run/user/") and host != "unix:///var/run/docker.sock":
        reasons.append("docker_host_remote_or_unverified")
    if docker and not reasons:
        try:
            p = subprocess.run([docker, "info", "--format", "{{json .SecurityOptions}}"],
                               capture_output=True, text=True, timeout=6)
            if p.returncode == 0:
                options = json.loads(p.stdout)
                if isinstance(options, list):
                    reachable = True
                    rootless = "name=rootless" in options
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
    if not reachable:
        reasons.append("docker_unreachable_or_unknown")
    # Do not reject an otherwise capable physical host merely because Docker
    # runs rootful. The *trusted launcher* must enforce hardened Docker flags;
    # the model itself must never receive raw host Docker/socket access.
    if virt not in ("vm_detected", "physical_detected") and not rootless:
        reasons.append("unknown_or_nested_rootful_host")
    daemon_tier = ("detected_vm" if virt == "vm_detected" else
                   "rootless_container" if rootless else "hardened_container")
    available_memory = _memory_mb()
    available_disk = _disk_mb(root)
    cpus = _cpu_count()
    stage_reasons = list(reasons)
    run_reasons = list(reasons)
    if available_memory < STAGE_MEM_MB:
        stage_reasons.append("not_enough_available_memory_for_stage")
    if available_disk < STAGE_DISK_MB:
        stage_reasons.append("not_enough_disk_for_stage")
    if available_memory < RUN_MEM_MB:
        run_reasons.append("not_enough_available_memory_for_java")
    if available_disk < RUN_DISK_MB:
        run_reasons.append("not_enough_disk_for_java")
    if cpus < RUN_CPUS:
        run_reasons.append("not_enough_cpu_for_java")
    # Generic Docker containers with 'container' virtualization are NOT VMs.
    return {
        "status": "PASS", "read_only_allowed": True,
        "machine_type": virt, "docker_reachable": reachable,
        "docker_rootless": rootless, "executor_tier": daemon_tier,
        "rootful_host_warning": bool(reachable and not rootless and virt != "vm_detected"),
        "agent_tool_sandbox_verified": False,
        "requires_hardened_docker": True,
        "memory_available_mb": available_memory,
        "disk_available_mb": available_disk, "cpu_count": cpus,
        "stage_allowed": not stage_reasons, "run_allowed": not run_reasons,
        "stage_blockers": stage_reasons[:8], "run_blockers": run_reasons[:8],
        "isolation_assurance": "heuristic_not_attestation",
        "no_actions_executed": True,
    }


def preflight(sandbox_root: Path, full_server: bool) -> dict:
    state = probe_environment(sandbox_root)
    allowed = state["run_allowed"] if full_server else state["stage_allowed"]
    blockers = state["run_blockers"] if full_server else state["stage_blockers"]
    return {"status": "ALLOW" if allowed else "BLOCK",
            "operation": "sandbox_server" if full_server else "sandbox_stage",
            "machine_type": state["machine_type"],
            "docker_rootless": state["docker_rootless"],
            "executor_tier": state["executor_tier"],
            "rootful_host_warning": state["rootful_host_warning"],
            "agent_tool_sandbox_verified": False,
            "cpu_count": state["cpu_count"],
            "memory_available_mb": state["memory_available_mb"],
            "disk_available_mb": state["disk_available_mb"],
            "blockers": blockers, "no_actions_executed": True}
