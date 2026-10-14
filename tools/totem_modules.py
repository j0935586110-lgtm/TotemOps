#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""TotemOps opt-in modules: a small, deterministic DSH-like switchboard.

A module is not an arbitrary shell command or an LLM agent. Modules are built-in
dispatches to existing audited tools, and all optional modules default OFF.
Direct legacy CLI and standalone plugins remain backward-compatible.
"""
from __future__ import annotations
import argparse
import importlib.util
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = {
    "pack-review": {"label": "整合包發布檢查", "description": "讀取完整包與更新包、產生唯讀差異報告",
                    "command": "release inspect", "risk": "read-only"},
    "release-gate": {"label": "更新相容性驗證", "description": "檢查簽章、版本、Java、Loader 變更，不下載模組",
                     "command": "release gate", "risk": "read-only"},
    "onboarding": {"label": "新手教學檢查", "description": "比對 README 和程式 CLI 旗標",
                   "command": "onboarding inspect", "risk": "read-only"},
    "log-diagnose": {"label": "當機日誌分析", "description": "唯讀分析 Minecraft 錯誤日誌",
                     "command": "quick diagnose", "risk": "read-only"},
    "repo-review": {"label": "開發專案檢查", "description": "程式庫／CI 靜態檢查",
                    "command": "maintainer inspect", "risk": "read-only"},
    "launcher-plan": {"label": "玩家啟動器規劃", "description": "唯讀產生 Prism 啟動參數及相容性驗收清單",
                      "command": "plugins run launcher-plan inspect", "risk": "read-only"},
}
ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_CONFIG_BYTES = 8192


class ModuleBlocked(ValueError):
    pass


def _pairs(pairs):
    result = {}
    for k, v in pairs:
        if k in result:
            raise ModuleBlocked("duplicate_config_key")
        result[k] = v
    return result


def _path(path: Path, create: bool = False) -> Path:
    if path.is_symlink() or path.name in (".", "..") or not path.name.endswith(".json"):
        raise ModuleBlocked("unsafe_modules_config_path")
    parent = path.parent
    if not parent.is_dir() or parent.is_symlink():
        raise ModuleBlocked("unsafe_modules_config_parent")
    return path


def _read_config(path: Path) -> list[str]:
    _path(path)
    if not path.is_file() or path.stat().st_size > MAX_CONFIG_BYTES:
        raise ModuleBlocked("missing_or_oversized_config")
    data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs)
    if (not isinstance(data, dict) or set(data) != {"schema", "enabled"} or
            data["schema"] != 1 or type(data["schema"]) is not int or
            not isinstance(data["enabled"], list) or any(
                not isinstance(n, str) or not ID.fullmatch(n) or n not in REGISTRY
                for n in data["enabled"]) or len(set(data["enabled"])) != len(data["enabled"])):
        raise ModuleBlocked("invalid_modules_config")
    return data["enabled"]


def _atomic_save(path: Path, enabled: list[str], *, initial: bool = False):
    _path(path, create=True)
    if initial and path.exists():
        raise ModuleBlocked("config_already_exists")
    if not initial and (path.is_symlink() or not path.is_file()):
        raise ModuleBlocked("modules_config_missing")
    content = json.dumps({"schema": 1, "enabled": sorted(enabled)}, ensure_ascii=False, indent=2) + "\n"
    if len(content.encode()) > MAX_CONFIG_BYTES:
        raise ModuleBlocked("config_too_large")
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".totem-modules-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        if initial and path.exists():
            raise ModuleBlocked("config_already_exists")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def status(path: Path | None = None) -> dict:
    enabled = set(_read_config(path)) if path else set()
    return {"status": "PASS", "config": str(path) if path else None,
            "default": "all_optional_modules_off",
            "modules": [
                {"id": k, **info, "enabled": k in enabled, "requires_permission": False}
                for k, info in REGISTRY.items()
            ],
            "core_safety": "always_on",
            "legacy_cli": "unchanged",
            "plugin_exec": "still_requires_explicit_plugins_run"}


def execute(module: str, path: Path, arguments: list[str]) -> int:
    if module not in REGISTRY:
        raise ModuleBlocked("unknown_module")
    if module not in _read_config(path):
        raise ModuleBlocked("module_disabled")
    if module == "release-gate" and importlib.util.find_spec("cryptography") is None:
        raise ModuleBlocked("cryptography_dependency_missing")
    import totem_operator
    mapped = {
        "pack-review": ["release", "inspect"],
        "release-gate": ["release", "gate"],
        "onboarding": ["onboarding", "inspect"],
        "log-diagnose": ["quick", "diagnose"],
        "repo-review": ["maintainer", "inspect"],
        "launcher-plan": ["plugins", "run", "launcher-plan", "inspect"],
    }[module]
    # "plugins"/remote-control is not reachable through this switchboard.
    return totem_operator.main(mapped + arguments)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="totem-ops modules")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("list", help="Show optional modules, default disabled")
    for name in ("status", "init", "enable", "disable", "run"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--config", type=Path, required=True)
        if name in ("enable", "disable", "run"):
            cmd.add_argument("module")
        if name == "run":
            cmd.add_argument("args", nargs=argparse.REMAINDER)
    opts = parser.parse_args(argv)
    try:
        if opts.action == "list":
            result = status()
        elif opts.action == "status":
            result = status(opts.config)
        elif opts.action == "init":
            _atomic_save(opts.config, [], initial=True)
            result = status(opts.config)
        elif opts.action in ("enable", "disable"):
            if opts.module not in REGISTRY:
                raise ModuleBlocked("unknown_module")
            enabled = set(_read_config(opts.config))
            if opts.action == "enable":
                enabled.add(opts.module)
            else:
                enabled.discard(opts.module)
            _atomic_save(opts.config, sorted(enabled))
            result = status(opts.config)
        else:
            argv2 = opts.args[1:] if opts.args[:1] == ["--"] else opts.args
            return execute(opts.module, opts.config, argv2)
    except (ModuleBlocked, OSError, ValueError, UnicodeError, json.JSONDecodeError) as e:
        print(json.dumps({"status": "BLOCK", "reason": str(e)[:120],
                          "executed": False, "changes_to_world": False}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
