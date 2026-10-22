#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""TotemOps offline dependency closure and compatibility verifier.

Strictly bounded, read-only analysis using declared package metadata.
No network calls, no Java execution, no unverified Maven resolution guessing.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    from mc_package_inspector import ENGINE_IDS, InputBlocked, inspect_path
except ImportError:
    from tools.mc_package_inspector import ENGINE_IDS, InputBlocked, inspect_path

CLOSURE_SCHEMA = "totemops.closure/1"
NOT_VERIFIED_CHECKS = [
    "remote_availability",
    "runtime_resolution",
    "maven_full_semantics",
    "actual_server_boot",
]


def _parse_version(v_str: str) -> tuple[tuple[int, ...], str | None]:
    v = v_str.strip()
    if not v or v == "UNKNOWN":
        return ((), "UNKNOWN" if v == "UNKNOWN" else None)
    if v.startswith(("v", "V")) and len(v) > 1 and v[1].isdigit():
        v = v[1:]
    m = re.match(r"^(\d+(?:\.\d+)*)(.*)$", v)
    if not m:
        return ((), v)
    num_part = m.group(1)
    suffix = m.group(2).strip() or None
    segments = tuple(int(x) for x in num_part.split("."))
    return (segments, suffix)


def _compare_tuples(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    max_len = max(len(a), len(b))
    a_pad = a + (0,) * (max_len - len(a))
    b_pad = b + (0,) * (max_len - len(b))
    if a_pad < b_pad:
        return -1
    elif a_pad > b_pad:
        return 1
    return 0


def evaluate_version_range(supplied_ver: str, v_range: str) -> tuple[str, str, str]:
    """Evaluates whether supplied_ver satisfies v_range.

    Returns (result, reason, note).
    result is one of: "PASS", "MISMATCH", "UNRESOLVED".
    """
    if supplied_ver == "UNKNOWN" or not supplied_ver:
        return ("UNRESOLVED", "supplied_version_unknown", "")

    sup_parts, sup_suffix = _parse_version(supplied_ver)
    if not sup_parts:
        return ("UNRESOLVED", "supplied_version_not_numeric", f"raw:{supplied_ver}")
    if sup_suffix:
        return ("UNRESOLVED", "non_numeric_version_suffix", f"supplied_version_has_suffix:{sup_suffix}")

    v_range = v_range.strip()
    # Unbounded
    if not v_range or v_range == "*":
        return ("PASS", "", "")

    # Wildcard trailing 1.20.x or 1.20.*
    m_wild = re.match(r"^(\d+(?:\.\d+)*)\.([xX\*])(.*)$", v_range)
    if m_wild:
        prefix_str = m_wild.group(1)
        extra = m_wild.group(3).strip()
        if extra:
            return ("UNRESOLVED", "range_not_evaluable", f"wildcard_has_suffix:{extra}")
        prefix_parts = tuple(int(x) for x in prefix_str.split("."))
        if len(sup_parts) < len(prefix_parts):
            sup_padded = sup_parts + (0,) * (len(prefix_parts) - len(sup_parts))
        else:
            sup_padded = sup_parts[:len(prefix_parts)]
        if sup_padded == prefix_parts:
            return ("PASS", "", "")
        return ("MISMATCH", "declared_range_not_satisfied", "")

    # Maven bracket notation: [1.20,1.21), [1.20], (1.20,), (,2.0], etc.
    if v_range.startswith(("[", "(")) and v_range.endswith(("]", ")")):
        if v_range.startswith("[") and v_range.endswith("]") and "," not in v_range:
            inner = v_range[1:-1].strip()
            req_parts, req_suffix = _parse_version(inner)
            if not req_parts or req_suffix:
                return ("UNRESOLVED", "range_not_evaluable", f"exact_bracket_invalid:{inner}")
            if _compare_tuples(sup_parts, req_parts) == 0:
                return ("PASS", "", "")
            return ("MISMATCH", "declared_range_not_satisfied", "")

        m_bracket = re.match(r"^([\[\(])([^,]*),([^,\)]*)([\]\)])$", v_range)
        if not m_bracket:
            return ("UNRESOLVED", "range_not_evaluable", f"malformed_bracket:{v_range}")
        left_delim, lower_str, upper_str, right_delim = m_bracket.groups()
        lower_str = lower_str.strip()
        upper_str = upper_str.strip()

        if lower_str:
            low_parts, low_suffix = _parse_version(lower_str)
            if not low_parts or low_suffix:
                return ("UNRESOLVED", "range_not_evaluable", f"lower_bound_invalid:{lower_str}")
            cmp_low = _compare_tuples(sup_parts, low_parts)
            if left_delim == "[" and cmp_low < 0:
                return ("MISMATCH", "declared_range_not_satisfied", "")
            if left_delim == "(" and cmp_low <= 0:
                return ("MISMATCH", "declared_range_not_satisfied", "")

        if upper_str:
            up_parts, up_suffix = _parse_version(upper_str)
            if not up_parts or up_suffix:
                return ("UNRESOLVED", "range_not_evaluable", f"upper_bound_invalid:{upper_str}")
            cmp_up = _compare_tuples(sup_parts, up_parts)
            if right_delim == "]" and cmp_up > 0:
                return ("MISMATCH", "declared_range_not_satisfied", "")
            if right_delim == ")" and cmp_up >= 0:
                return ("MISMATCH", "declared_range_not_satisfied", "")

        return ("PASS", "", "")

    # Comparison operators >=, >, <=, <, ==, = (can be comma separated)
    if any(v_range.startswith(op) for op in (">=", "<=", ">", "<", "==", "=")) or (
        "," in v_range and any(op in v_range for op in (">=", "<=", ">", "<", "==", "="))
    ):
        parts = [p.strip() for p in v_range.split(",") if p.strip()]
        for p in parts:
            m_op = re.match(r"^(>=|<=|>|<|==|=)\s*(.+)$", p)
            if not m_op:
                return ("UNRESOLVED", "range_not_evaluable", f"invalid_comparison:{p}")
            op, val_str = m_op.groups()
            req_parts, req_suffix = _parse_version(val_str.strip())
            if not req_parts or req_suffix:
                return ("UNRESOLVED", "range_not_evaluable", f"comparison_val_invalid:{val_str}")
            cmp_val = _compare_tuples(sup_parts, req_parts)
            if op == ">=" and cmp_val < 0:
                return ("MISMATCH", "declared_range_not_satisfied", "")
            elif op == ">" and cmp_val <= 0:
                return ("MISMATCH", "declared_range_not_satisfied", "")
            elif op == "<=" and cmp_val > 0:
                return ("MISMATCH", "declared_range_not_satisfied", "")
            elif op == "<" and cmp_val >= 0:
                return ("MISMATCH", "declared_range_not_satisfied", "")
            elif (op == "==" or op == "=") and cmp_val != 0:
                return ("MISMATCH", "declared_range_not_satisfied", "")
        return ("PASS", "", "")

    # Exact numeric version e.g. "21.1.0"
    req_parts, req_suffix = _parse_version(v_range)
    if req_parts and not req_suffix and not any(c in v_range for c in "~^!|"):
        if _compare_tuples(sup_parts, req_parts) == 0:
            return ("PASS", "", "")
        return ("MISMATCH", "declared_range_not_satisfied", "")

    return ("UNRESOLVED", "range_not_evaluable", f"unsupported_syntax:{v_range}")


def check_closure(path: Path | str, side: str = "both") -> dict:
    side = side.lower().strip()
    if side not in ("both", "client", "server"):
        side = "both"

    if not isinstance(path, Path):
        path = Path(path)

    if path.is_symlink():
        return {
            "schema": CLOSURE_SCHEMA,
            "mode": "offline_read_only",
            "verified_scope": "declared_metadata_only",
            "side": side,
            "status": "BLOCK",
            "reason": "symlink_not_allowed",
            "supplied": {"count": 0, "mods": []},
            "missing": [],
            "version_mismatch": [],
            "incompatible_pairs": [],
            "unresolved_ranges": [],
            "findings_reused": [],
            "not_verified": NOT_VERIFIED_CHECKS,
            "next_step": "輸入路徑不得為符號連結",
        }

    if not path.exists():
        return {
            "schema": CLOSURE_SCHEMA,
            "mode": "offline_read_only",
            "verified_scope": "declared_metadata_only",
            "side": side,
            "status": "BLOCK",
            "reason": "path_not_found",
            "supplied": {"count": 0, "mods": []},
            "missing": [],
            "version_mismatch": [],
            "incompatible_pairs": [],
            "unresolved_ranges": [],
            "findings_reused": [],
            "not_verified": NOT_VERIFIED_CHECKS,
            "next_step": "請確認輸入路徑是否存在",
        }

    try:
        inspection = inspect_path(path)
    except (InputBlocked, OSError, ValueError, TypeError) as exc:
        reason_str = str(exc)[:80]
        # Privacy: strip any directory / path fragments from reason
        if "/" in reason_str or "\\" in reason_str:
            reason_str = "input_blocked_invalid_package"
        return {
            "schema": CLOSURE_SCHEMA,
            "mode": "offline_read_only",
            "verified_scope": "declared_metadata_only",
            "side": side,
            "status": "BLOCK",
            "reason": reason_str,
            "supplied": {"count": 0, "mods": []},
            "missing": [],
            "version_mismatch": [],
            "incompatible_pairs": [],
            "unresolved_ranges": [],
            "findings_reused": [],
            "not_verified": NOT_VERIFIED_CHECKS,
            "next_step": "請確認輸入路徑是否為有效的模組檔案或資料夾",
        }

    outputs = inspection.get("packages", [])
    if not outputs or inspection.get("status") == "BLOCK":
        reason_str = "no_supported_packages"
        if inspection.get("files_rejected"):
            reason_str = inspection["files_rejected"][0].get("reason", "rejected")[:60]
            if "/" in reason_str or "\\" in reason_str:
                reason_str = "rejected_package_format"
        return {
            "schema": CLOSURE_SCHEMA,
            "mode": "offline_read_only",
            "verified_scope": "declared_metadata_only",
            "side": side,
            "status": "BLOCK",
            "reason": reason_str,
            "supplied": {"count": 0, "mods": []},
            "missing": [],
            "version_mismatch": [],
            "incompatible_pairs": [],
            "unresolved_ranges": [],
            "findings_reused": [],
            "not_verified": NOT_VERIFIED_CHECKS,
            "next_step": "請確認資料夾內包含有效的模組檔案",
        }

    # Extract supplied mods
    supplied_list = []
    seen_supplied = set()
    for pkg in outputs:
        fname = pkg.get("file", "")
        for m in pkg.get("mods", []):
            mod_id = m.get("id", "")
            ver = str(m.get("version", "UNKNOWN"))
            key = (mod_id.casefold(), fname, ver)
            if key not in seen_supplied:
                seen_supplied.add(key)
                supplied_list.append({"file": fname, "id": mod_id, "version": ver})

        for e in pkg.get("dependencies", []):
            if e.get("type") == "embedded":
                emb_id = e.get("to", "")
                if emb_id and not any(s["id"].casefold() == emb_id.casefold() for s in supplied_list):
                    emb_ver = str(e.get("version_range", "")).strip() or "UNKNOWN"
                    supplied_list.append({"file": fname, "id": emb_id, "version": emb_ver})

    # Sort supplied deterministically
    supplied_list.sort(key=lambda x: (x["id"].casefold(), x["file"], x["version"]))

    # Index supplied mods by casefolded ID
    supplied_map: dict[str, list[dict]] = {}
    for sm in supplied_list:
        supplied_map.setdefault(sm["id"].casefold(), []).append(sm)

    # Reused structural findings
    findings_reused = sorted(list({
        f["kind"] for f in inspection.get("findings", [])
        if f.get("kind") not in ("declared_incompatible", "required_not_in_supplied_set")
    }))

    # Side filtering setup
    if side == "server":
        allowed_sides = {"BOTH", "SERVER", "UNKNOWN"}
    elif side == "client":
        allowed_sides = {"BOTH", "CLIENT", "UNKNOWN"}
    else:
        allowed_sides = {"BOTH", "CLIENT", "SERVER", "UNKNOWN"}

    missing_map: dict[str, dict] = {}
    version_mismatch_map: dict[str, dict] = {}
    incompatible_pairs: list[dict] = []
    unresolved_ranges: list[dict] = []

    for pkg in outputs:
        for edge in pkg.get("dependencies", []):
            from_mod = edge.get("from", "")
            target = edge.get("to", "")
            if not target:
                continue

            dep_type = str(edge.get("type", "unknown")).lower().strip()
            edge_side = str(edge.get("side", "UNKNOWN")).upper().strip() or "UNKNOWN"
            v_range = str(edge.get("version_range", "")).strip()
            target_lower = target.casefold()

            # Side filter check
            if edge_side not in allowed_sides:
                continue

            # Incompatible handling
            if dep_type == "incompatible":
                if target_lower in supplied_map:
                    incompatible_pairs.append({
                        "from": from_mod,
                        "to": target,
                        "version_range": v_range,
                    })
                continue

            # Optional / embedded / discouraged are not missing
            if dep_type != "required":
                continue

            # Engine dependencies (minecraft, forge, neoforge, etc.)
            if target_lower in ENGINE_IDS:
                continue

            # Missing dependency
            if target_lower not in supplied_map:
                node = missing_map.setdefault(target_lower, {
                    "to": target,
                    "required_by": set(),
                    "version_ranges": set(),
                    "sides": set(),
                })
                node["required_by"].add(from_mod)
                node["version_ranges"].add(v_range)
                node["sides"].add(edge_side)
                continue

            # Supplied: verify version range against supplied versions
            sup_entries = supplied_map[target_lower]
            for sup in sup_entries:
                sup_ver = sup["version"]
                eval_res, eval_reason, eval_note = evaluate_version_range(sup_ver, v_range)
                if eval_res == "UNRESOLVED":
                    unres_item = {
                        "from": from_mod,
                        "to": target,
                        "version_range": v_range,
                        "reason": eval_reason,
                    }
                    if eval_note:
                        unres_item["note"] = eval_note
                    unresolved_ranges.append(unres_item)
                elif eval_res == "MISMATCH":
                    node = version_mismatch_map.setdefault(target_lower, {
                        "to": target,
                        "supplied_version": sup_ver,
                        "required_by": set(),
                        "version_ranges": set(),
                    })
                    node["required_by"].add(from_mod)
                    node["version_ranges"].add(v_range)

    # Format missing
    missing_list = []
    for k in sorted(missing_map.keys()):
        m = missing_map[k]
        sides = m["sides"]
        if "BOTH" in sides or ("SERVER" in sides and "CLIENT" in sides):
            agg_side = "BOTH"
        elif "SERVER" in sides:
            agg_side = "SERVER"
        elif "CLIENT" in sides:
            agg_side = "CLIENT"
        else:
            agg_side = "UNKNOWN"

        vranges = sorted(list(m["version_ranges"])) if m["version_ranges"] else [""]
        missing_list.append({
            "to": m["to"],
            "required_by": sorted(list(m["required_by"])),
            "version_ranges": vranges,
            "side": agg_side,
            "reason": "not_in_supplied_set",
        })
    missing_list.sort(key=lambda x: x["to"].casefold())

    # Format version_mismatch
    version_mismatch_list = []
    for k in sorted(version_mismatch_map.keys()):
        vm = version_mismatch_map[k]
        vranges = sorted(list(vm["version_ranges"]))
        vrange_str = ", ".join(vranges) if len(vranges) > 1 else (vranges[0] if vranges else "")
        version_mismatch_list.append({
            "to": vm["to"],
            "supplied_version": vm["supplied_version"],
            "required_by": sorted(list(vm["required_by"])),
            "version_range": vrange_str,
            "reason": "declared_range_not_satisfied",
        })
    version_mismatch_list.sort(key=lambda x: x["to"].casefold())

    # Sort incompatible_pairs and unresolved_ranges
    incompatible_pairs.sort(key=lambda x: (x["to"].casefold(), x["from"].casefold()))
    unresolved_ranges.sort(key=lambda x: (x["to"].casefold(), x["from"].casefold()))

    has_issue = bool(missing_list or version_mismatch_list or incompatible_pairs or unresolved_ranges)
    status = "REVIEW_REQUIRED" if has_issue else "PASS"

    if status == "PASS":
        next_step = "宣告依賴在本機檔案間自洽，若需測試請在隔離沙盒啟動"
    else:
        next_step = "請檢查缺少的依賴或版本不符項目，補齊相容模組後重新檢查"

    return {
        "schema": CLOSURE_SCHEMA,
        "mode": "offline_read_only",
        "verified_scope": "declared_metadata_only",
        "side": side,
        "status": status,
        "supplied": {
            "count": len(supplied_list),
            "mods": supplied_list,
        },
        "missing": missing_list,
        "version_mismatch": version_mismatch_list,
        "incompatible_pairs": incompatible_pairs,
        "unresolved_ranges": unresolved_ranges,
        "findings_reused": findings_reused,
        "not_verified": NOT_VERIFIED_CHECKS,
        "next_step": next_step,
    }


def format_human_closure(data: dict) -> str:
    status = data.get("status", "UNKNOWN")
    side = data.get("side", "both")
    lines = [f"TotemOps 依賴閉包檢查結果：{status}（端：{side}）"]

    if status == "BLOCK":
        lines.append(f"  阻擋原因：{data.get('reason', 'unknown')}")
        lines.append(f"  建議下一步：{data.get('next_step', '請確認輸入路徑並重試')}")
        return "\n".join(lines)

    supplied = data.get("supplied", {})
    lines.append(f"  已提供模組數：{supplied.get('count', 0)}")

    missing = data.get("missing", [])
    if missing:
        lines.append(f"  缺少的必要依賴（{len(missing)} 項）：")
        for m in missing:
            reqs = ", ".join(m.get("required_by", []))
            ranges = ", ".join(m.get("version_ranges", []))
            lines.append(f"    - {m.get('to')}（要求端：{m.get('side')}，被要求者：{reqs}，版本範圍：{ranges}）")

    mismatch = data.get("version_mismatch", [])
    if mismatch:
        lines.append(f"  版本不符項目（{len(mismatch)} 項）：")
        for vm in mismatch:
            reqs = ", ".join(vm.get("required_by", []))
            lines.append(f"    - {vm.get('to')}：供給版本 {vm.get('supplied_version')} 不滿足 {vm.get('version_range')}（被要求者：{reqs}）")

    incompat = data.get("incompatible_pairs", [])
    if incompat:
        lines.append(f"  宣告不相容組合（{len(incompat)} 項）：")
        for inc in incompat:
            lines.append(f"    - {inc.get('from')} 與 {inc.get('to')} 不相容（範圍：{inc.get('version_range')}）")

    unres = data.get("unresolved_ranges", [])
    if unres:
        lines.append(f"  無法精確判定之版本範圍（{len(unres)} 項）：")
        for u in unres:
            note_str = f" [{u.get('note')}]" if u.get("note") else ""
            lines.append(f"    - {u.get('from')} -> {u.get('to')}：{u.get('version_range')}（原因：{u.get('reason')}{note_str}）")

    reused = data.get("findings_reused", [])
    if reused:
        lines.append(f"  複用套件檢查特徵：{', '.join(reused)}")

    lines.append(f"  已驗證範疇：{data.get('verified_scope', '')}")
    lines.append(f"  建議下一步：{data.get('next_step', '')}")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="TotemOps offline dependency closure verifier")
    parser.add_argument("path", help="Path to mod JAR, .mrpack, .zip, or directory")
    parser.add_argument("--side", choices=("both", "client", "server"), default="both")
    parser.add_argument("--json", action="store_true", help="Output JSON object")
    args = parser.parse_args(argv)

    res = check_closure(Path(args.path), side=args.side)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, sort_keys=True))
    else:
        print(format_human_closure(res))

    st = res.get("status")
    return 0 if st == "PASS" else 2 if st == "BLOCK" else 3


if __name__ == "__main__":
    sys.exit(main())
