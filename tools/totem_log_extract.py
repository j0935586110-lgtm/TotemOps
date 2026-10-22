# SPDX-License-Identifier: Apache-2.0
"""Deterministic extraction of missing Minecraft mod dependencies from server crash logs."""
from __future__ import annotations

import re
from pathlib import Path

MAX_LOG_SIZE = 2 * 1024 * 1024  # 2 MiB
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")

# Pattern 1: Mod <A> requires mod <B>
P1_RE = re.compile(
    r"\bmod\s+['\"]?([a-z0-9_-]+)['\"]?\s+requires\s+mod\s+['\"]?([a-z0-9_-]+)['\"]?",
    re.IGNORECASE,
)
# Pattern 2 & 4: requires mod <B>
P2_RE = re.compile(
    r"\brequires\s+mod\s+['\"]?([a-z0-9_-]+)['\"]?",
    re.IGNORECASE,
)
# Pattern 3: Mod ID: <B>
P3_MOD_ID_RE = re.compile(
    r"\bmod\s*id\s*:\s*['\"]?([a-z0-9_-]+)['\"]?",
    re.IGNORECASE,
)


def extract_missing_dependency(log_path: Path) -> dict:
    """Deterministically extracts missing mod dependency slug from server crash log.

    Fail-closed: returns BLOCK on unreadable/binary log, REVIEW_REQUIRED on 0 or multiple candidates.
    No network requests or fuzzy matching performed.
    """
    if not isinstance(log_path, Path):
        log_path = Path(log_path)

    if log_path.is_symlink() or not log_path.is_file():
        return {"status": "BLOCK", "reason": "log_unreadable"}

    try:
        with log_path.open("rb") as f:
            raw_bytes = f.read(MAX_LOG_SIZE + 1)
        if b"\x00" in raw_bytes:
            return {"status": "BLOCK", "reason": "log_unreadable"}
        content = raw_bytes[:MAX_LOG_SIZE].decode("utf-8")
    except (UnicodeDecodeError, OSError):
        return {"status": "BLOCK", "reason": "log_unreadable"}

    lines = content.splitlines()
    matches = []

    in_missing_mandatory_block = False
    missing_unsupported_counter = 0

    for idx, raw_line in enumerate(lines):
        line_num = idx + 1
        line_lower = raw_line.lower()

        # Handle very long lines safely
        if len(raw_line) > 8192:
            if not any(k in line_lower for k in ("requires", "missing", "mod id")):
                continue

        # Check block starters
        if "missing mandatory dependencies:" in line_lower:
            in_missing_mandatory_block = True
        elif in_missing_mandatory_block and (
            raw_line.strip() == ""
            or (raw_line.startswith("[") and "missing mandatory dependencies:" not in line_lower and "requires mod" not in line_lower)
        ):
            in_missing_mandatory_block = False

        if "missing or unsupported mandatory dependencies" in line_lower:
            missing_unsupported_counter = 4  # Includes this line plus up to 3 lines after
        elif missing_unsupported_counter > 0:
            missing_unsupported_counter -= 1

        matched_on_this_line = False

        # Pattern 1: Mod <A> requires mod <B>
        for m in P1_RE.finditer(raw_line):
            b_slug = m.group(2).lower()
            if SLUG_RE.fullmatch(b_slug):
                matches.append({
                    "slug": b_slug,
                    "line": line_num,
                    "pattern": "requires_mod",
                    "source_text": raw_line.strip()[:500],
                })
                matched_on_this_line = True

        # Pattern 2: In Missing mandatory dependencies: block, requires mod <B>
        if in_missing_mandatory_block and not matched_on_this_line:
            for m in P2_RE.finditer(raw_line):
                b_slug = m.group(1).lower()
                if SLUG_RE.fullmatch(b_slug):
                    matches.append({
                        "slug": b_slug,
                        "line": line_num,
                        "pattern": "missing_mandatory_dependencies",
                        "source_text": raw_line.strip()[:500],
                    })
                    matched_on_this_line = True

        # Pattern 3 & 4: Within 3 lines after Missing or unsupported mandatory dependencies
        if missing_unsupported_counter > 0 and not matched_on_this_line:
            # Check Mod ID: <B>
            for m in P3_MOD_ID_RE.finditer(raw_line):
                b_slug = m.group(1).lower()
                if SLUG_RE.fullmatch(b_slug):
                    matches.append({
                        "slug": b_slug,
                        "line": line_num,
                        "pattern": "mod_id",
                        "source_text": raw_line.strip()[:500],
                    })
                    matched_on_this_line = True
            # Check requires mod <B>
            if not matched_on_this_line:
                for m in P2_RE.finditer(raw_line):
                    b_slug = m.group(1).lower()
                    if SLUG_RE.fullmatch(b_slug):
                        matches.append({
                            "slug": b_slug,
                            "line": line_num,
                            "pattern": "missing_or_unsupported_mandatory_dependencies",
                            "source_text": raw_line.strip()[:500],
                        })
                        matched_on_this_line = True

    # Deduplication
    unique_slugs = {}
    for m in matches:
        if m["slug"] not in unique_slugs:
            unique_slugs[m["slug"]] = m

    distinct_candidates = sorted(unique_slugs.keys())
    if len(distinct_candidates) == 1:
        first = unique_slugs[distinct_candidates[0]]
        return {
            "status": "OK",
            "project": first["slug"],
            "evidence_line": first["line"],
            "pattern": first["pattern"],
            "source_text": first["source_text"],
        }
    elif len(distinct_candidates) == 0:
        return {
            "status": "REVIEW_REQUIRED",
            "reason": "no_pattern_matched",
            "candidates": [],
        }
    else:
        return {
            "status": "REVIEW_REQUIRED",
            "reason": "ambiguous_candidates",
            "candidates": distinct_candidates,
        }
