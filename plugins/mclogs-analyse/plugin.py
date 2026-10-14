#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Optional mclo.gs POST /1/analyse adapter. NOT a persistent paste.

Exits fail-closed. Requires two explicit switches and a small local log file.
No automatic calls, credentials, server administration, or raw log in stdout.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ENDPOINT = "https://api.mclo.gs/1/analyse"
MAX_BYTES = 1_000_000
MAX_LINES = 10_000
MAX_OUTPUT_PROBLEMS = 5
MAX_RESPONSE_BYTES = 250_000
# Conservative stop signs. Not a promise that every secret can be detected.
SENSITIVE = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|(?:Authorization\s*:\s*(?:Bearer|Basic)\s+\S+)"
    r"|(?:\b(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)\s*[:=]\s*\S+)"
    r"|(?:https://(?:discord(?:app)?\.com)/api/webhooks/)"
    r"|(?:\b(?:\d{1,3}\.){3}\d{1,3}\b)"
    r"|(?:\b(?:\d{1,3}\.){3}\d{1,3}:\d{2,5}\b)",
    re.IGNORECASE,
)


def _read_log(path_value: str) -> str:
    if not isinstance(path_value, str) or not path_value or len(path_value) > 4096:
        raise ValueError("invalid_log_path")
    path = Path(path_value).expanduser()
    if path.is_symlink() or path.suffix.lower() not in (".log", ".txt"):
        raise ValueError("not_a_regular_log_or_symlink")
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError("log_missing_or_too_large")
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES or b"\x00" in raw:
        raise ValueError("log_too_large_or_binary")
    try:
        log = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("log_not_utf8") from exc
    if log.count("\n") > MAX_LINES:
        raise ValueError("too_many_log_lines")
    if not log.strip():
        raise ValueError("empty_log")
    if SENSITIVE.search(log):
        raise ValueError("sensitive_data_marker_found_review_and_redact_locally")
    return log


def _call_mclogs(log: str) -> dict:
    # Only the hard-coded HTTPS endpoint is ever contacted; no URL in input.
    body = json.dumps({"content": log}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        ENDPOINT, data=body, method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json",
                 "User-Agent": "j0935586110-lgtm/TotemOps/0.1 (opt-in analysis)"},
    )
    # Do not follow upstream redirects with a body containing private data.
    class RejectRedirects(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise ValueError("redirect_blocked")

    opener = urllib.request.build_opener(RejectRedirects())
    with opener.open(request, timeout=12) as response:
        if response.status != 200 or response.geturl() != ENDPOINT:
            raise ValueError("unexpected_http_status_or_redirect")
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("analysis_response_too_large")
    data = json.loads(raw)
    if not isinstance(data, dict) or not isinstance(data.get("analysis"), dict):
        raise ValueError("invalid_analysis_response")
    return data


def analyse(payload: dict) -> dict:
    if (payload.get("allow_external_processing") is not True
            or payload.get("user_reviewed_log_for_secrets") is not True):
        return {"status": "BLOCK", "reason": "explicit_opt_in_and_local_secret_review_required",
                "external_request_sent": False}
    try:
        log = _read_log(payload.get("log_path"))
    except (OSError, ValueError) as exc:
        return {"status": "BLOCK", "reason": str(exc)[:110], "external_request_sent": False}
    try:
        data = _call_mclogs(log)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
        return {"status": "BLOCK", "reason": "external_analysis_unavailable_or_untrusted",
                "error_type": type(exc).__name__, "external_request_sent": "unknown"}
    findings = []
    problems = data["analysis"].get("problems", [])
    if not isinstance(problems, list):
        return {"status": "BLOCK", "reason": "invalid_problems_response", "external_request_sent": True}
    for p in problems[:MAX_OUTPUT_PROBLEMS]:
        if not isinstance(p, dict):
            continue
        entry = p.get("entry") if isinstance(p.get("entry"), dict) else {}
        lines = entry.get("lines") if isinstance(entry.get("lines"), list) else []
        # Never relay the raw log or entry.lines text into Agent context.
        evidence_lines = [int(x["number"]) for x in lines[:4]
                          if isinstance(x, dict) and isinstance(x.get("number"), int)
                          and 0 <= x["number"] <= MAX_LINES]
        description = str(p.get("message", ""))[:220]
        if SENSITIVE.search(description):
            description = "[redacted: potentially sensitive upstream text]"
        findings.append({
            "message": description,
            "count": p.get("counter") if isinstance(p.get("counter"), int) else None,
            "evidence_line_numbers": evidence_lines,
            "source": "mclo.gs_analysis",
            "verified_root_cause": False,
        })
    return {
        "status": "ANALYSIS_HINTS_ONLY",
        "provider": "mclo.gs",
        "endpoint": ENDPOINT,
        "external_request_sent": True,
        "saved_as_public_paste": False,
        "third_party_received_log": True,
        "problem_count_returned": len(problems),
        "problems": findings,
        "verified_root_cause": False,
        "modified_files": False,
        "needs_independent_verification": True,
        "notice": "Data was sent to mclo.gs. POST /1/analyse is documented as analysis without creating a saved paste; it is NOT an offline/privacy guarantee.",
    }


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] != "analyse":
        print(json.dumps({"status": "BLOCK", "reason": "unsupported_command"}))
        return 2
    try:
        raw = sys.stdin.read(8193)
        if len(raw) > 8192:
            raise ValueError("input_too_large")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("input_must_be_object")
        result = analyse(payload)
    except (ValueError, TypeError) as exc:
        result = {"status": "BLOCK", "reason": str(exc)[:100], "external_request_sent": False}
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 2 if result["status"] == "BLOCK" else 0


if __name__ == "__main__":
    sys.exit(main())
