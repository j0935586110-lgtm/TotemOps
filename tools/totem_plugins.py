# SPDX-License-Identifier: Apache-2.0
"""Small opt-in extension runner. Plugin code runs with user's OS permissions.

No background execution, no implicit plugin activation, no shell command string.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGINS = ROOT / "plugins"
NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_MANIFEST = 16384
MAX_INPUT = 16384
MAX_OUTPUT = 32768
ALLOWED_RUNNERS = {"python3", "python", "node", "bash", "sh"}


def _load(name: str) -> tuple[dict, Path]:
    if not NAME.fullmatch(name) or len(name) > 64:
        raise ValueError("invalid_plugin_name")
    root = PLUGINS.resolve()
    directory = PLUGINS / name
    if directory.is_symlink() or not directory.is_dir() or directory.resolve().parent != root:
        raise ValueError("plugin_missing_or_unsafe_path")
    path = directory / "plugin.json"
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_MANIFEST:
        raise ValueError("missing_or_invalid_plugin_manifest")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("name") != name:
        raise ValueError("invalid_plugin_manifest_name")
    cmds = data.get("commands")
    if not isinstance(cmds, list) or not cmds or any(
        not isinstance(x, str) or not NAME.fullmatch(x) for x in cmds
    ):
        raise ValueError("invalid_plugin_commands")
    entry = data.get("entry")
    if (not isinstance(entry, list) or len(entry) != 2 or
            entry[0] not in ALLOWED_RUNNERS or not isinstance(entry[1], str) or
            not re.fullmatch(r"[a-zA-Z0-9_.-]+\.(?:py|js|mjs|sh)", entry[1])):
        raise ValueError("invalid_plugin_entry")
    script = directory / entry[1]
    if script.is_symlink() or not script.is_file() or script.resolve().parent != directory.resolve():
        raise ValueError("invalid_plugin_script")
    timeout = data.get("timeout_seconds", 10)
    if type(timeout) is not int or not (1 <= timeout <= 60):
        raise ValueError("invalid_plugin_timeout")
    return data, directory


def list_plugins() -> dict:
    found, rejected = [], []
    if not PLUGINS.is_dir():
        return {"status": "PASS", "plugins": [], "rejected": []}
    for p in sorted(PLUGINS.iterdir()):
        if p.name.startswith("."):
            continue
        if not p.is_dir() or p.is_symlink():
            rejected.append({"name": p.name, "reason": "not_a_regular_plugin_directory"})
            continue
        try:
            data, _ = _load(p.name)
            found.append({"name": data["name"], "description": str(data.get("description", ""))[:160],
                          "commands": data["commands"], "capabilities": data.get("capabilities", [])})
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as err:
            rejected.append({"name": p.name, "reason": str(err)[:100]})
    return {"status": "PASS", "plugins": found, "rejected": rejected,
            "note": "Listed plugins are NOT run or automatically granted trust"}


def run_plugin(name: str, command: str, payload: str) -> dict:
    try:
        data, directory = _load(name)
        if command not in data["commands"]:
            raise ValueError("unknown_plugin_command")
        if len(payload.encode("utf-8")) > MAX_INPUT:
            raise ValueError("plugin_input_too_large")
        obj = json.loads(payload)
        if not isinstance(obj, dict):
            raise ValueError("plugin_input_must_be_json_object")
        executable = sys.executable if data["entry"][0] in ("python3", "python") else shutil.which(data["entry"][0])
        if not executable:
            raise ValueError("plugin_runtime_not_installed")
        result = subprocess.run(
            [executable, data["entry"][1], command],
            input=json.dumps(obj), text=True, capture_output=True, cwd=directory,
            timeout=data["timeout_seconds"], check=False, shell=False,
        )
        if result.returncode != 0:
            return {"status": "BLOCK", "reason": "plugin_process_failed", "exit": result.returncode,
                    "plugin": name, "trusted": False}
        if len(result.stdout.encode("utf-8")) > MAX_OUTPUT:
            return {"status": "BLOCK", "reason": "plugin_output_too_large", "plugin": name}
        output = json.loads(result.stdout)
        if not isinstance(output, dict):
            raise ValueError("plugin_output_must_be_json_object")
        # A plugin saying BLOCK must never be wrapped as a successful operation.
        if output.get("status") == "BLOCK":
            return {"status": "BLOCK", "reason": "plugin_reported_block",
                    "plugin": name, "trusted": False, "result": output}
        return {"status": "PASS", "plugin": name, "trusted": False, "source": "user_opt_in_plugin",
                "result": output}
    except subprocess.TimeoutExpired:
        return {"status": "BLOCK", "reason": "plugin_timeout", "plugin": name}
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as err:
        return {"status": "BLOCK", "reason": str(err)[:120], "plugin": name}
