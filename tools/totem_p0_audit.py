#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""P0 bounded evidence audit; no Minecraft deployment or writes to worlds."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "evidence/totemops-five-faults-20261014.json"
EXPECTED = {
    "F1": "dependency_load_failure",
    "F2": "client_class_on_server",
    "F3": "mixin_injection_failure",
    "F4": "java_runtime_version_mismatch",
    "F5": "loader_version_incompatible",
}

def audit():
    fixture = json.loads(DATA.read_text(encoding="utf-8"))
    cases = []
    for case in fixture["cases"]:
        identifier = case["id"]
        expected = EXPECTED.get(identifier)
        if expected is None:
            raise ValueError("unknown_case")
        import tempfile
        with tempfile.TemporaryDirectory(prefix="totemops-p0-") as tmp:
            logfile = Path(tmp) / "latest.log"
            logfile.write_text(case["log"] + "\n", encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(ROOT / "tools/totem_operator.py"), "quick",
                 "diagnose", str(logfile)],
                cwd=ROOT, capture_output=True, text=True, timeout=10, check=False)
        try:
            result = json.loads(proc.stdout)
        except json.JSONDecodeError:
            result = {}
        signals = [c.get("signal") for c in result.get("clues", [])]
        passed = proc.returncode == 0 and expected in signals and result.get("confirmed_root_cause") is None
        cases.append({"id": identifier, "expected_signal": expected, "observed_signals": signals,
                      "classification_pass": passed, "verified_live_fix": False,
                      "source": "synthetic_log", "log_sha256": hashlib.sha256(
                          (case["log"] + "\n").encode()).hexdigest()})
    if len(cases) != len(EXPECTED) or {x["id"] for x in cases} != set(EXPECTED):
        raise ValueError("fixture_case_set_mismatch")
    return {"schema": 1, "project": "TotemOps", "gate": "P0_fault_diagnosis",
            "source_fixture_sha256": hashlib.sha256(DATA.read_bytes()).hexdigest(),
            "classification_pass_count": sum(c["classification_pass"] for c in cases),
            "case_count": len(cases), "live_fix_pass_count": 0,
            "live_fix_status": "NOT_TESTED_IN_THIS_RUN",
            "ready_for_unattended_production_fix": False,
            "cases": cases}

if __name__ == "__main__":
    result = audit()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    sys.exit(0 if result["classification_pass_count"] == result["case_count"] else 2)
