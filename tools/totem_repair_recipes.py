#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""TotemOps deterministic, read-only repair recipe planner (fixplan).

Maps crash log evidence signals into reproducible, non-executing repair recipes.
No Java execution, no live server mutation, no docker calls, no network lookups.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from mc_package_inspector import InputBlocked, PATTERNS, inspect_log
except ImportError:
    from tools.mc_package_inspector import InputBlocked, PATTERNS, inspect_log

CATALOG_SCHEMA = "totemops.repair_recipes/1"
FIXPLAN_SCHEMA = "totemops.fixplan/1"
DEFAULT_CATALOG_PATH = Path(__file__).resolve().parent.parent / "data" / "repair_recipes.json"


def load_catalog(path: Path | None = None) -> dict:
    """Loads and strictly validates the repair recipes catalog.

    Fail-closed: raises ValueError on missing file, corrupted JSON, schema mismatch,
    duplicate IDs, or non-1-to-1 match with mc_package_inspector.PATTERNS signals.
    """
    catalog_path = path if path is not None else DEFAULT_CATALOG_PATH
    if not isinstance(catalog_path, Path):
        catalog_path = Path(catalog_path)

    if catalog_path.is_symlink() or not catalog_path.is_file():
        raise ValueError("repair_recipes_catalog_missing")

    try:
        data = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        raise ValueError("repair_recipes_catalog_invalid_json") from exc

    if not isinstance(data, dict) or data.get("schema") != CATALOG_SCHEMA:
        raise ValueError("repair_recipes_schema_mismatch")

    recipes = data.get("recipes")
    if not isinstance(recipes, list):
        raise ValueError("repair_recipes_invalid_recipes_list")

    expected_signals = [kind for kind, _, _ in PATTERNS]
    expected_signal_set = set(expected_signals)

    seen_signals = []
    seen_ids = set()

    for item in recipes:
        if not isinstance(item, dict):
            raise ValueError("repair_recipes_invalid_entry")

        sig = item.get("signal")
        rec_id = item.get("id")
        title = item.get("title")
        why = item.get("why")
        steps = item.get("steps")
        verify = item.get("verify")
        stop_if = item.get("stop_if")
        do_not = item.get("do_not")

        if not isinstance(sig, str) or sig not in expected_signal_set:
            raise ValueError(f"repair_recipes_unexpected_signal:{sig}")
        if not isinstance(rec_id, str) or not rec_id or rec_id in seen_ids:
            raise ValueError(f"repair_recipes_duplicate_or_invalid_id:{rec_id}")

        for label_dict, name in ((title, "title"), (why, "why")):
            if not isinstance(label_dict, dict) or not label_dict.get("zh-TW") or not label_dict.get("en"):
                raise ValueError(f"repair_recipes_missing_i18n_{name}:{rec_id}")

        if not isinstance(steps, list) or not (3 <= len(steps) <= 6):
            raise ValueError(f"repair_recipes_steps_count_out_of_range:{rec_id}")

        for step in steps:
            if not isinstance(step, dict):
                raise ValueError(f"repair_recipes_invalid_step:{rec_id}")
            order = step.get("order")
            action = step.get("action")
            how = step.get("how")
            risk = step.get("risk")
            requires_conf = step.get("requires_confirmation")
            may_change = step.get("may_change_files")

            if not isinstance(order, int):
                raise ValueError(f"repair_recipes_invalid_step_order:{rec_id}")
            if not isinstance(action, dict) or not action.get("zh-TW") or not action.get("en"):
                raise ValueError(f"repair_recipes_invalid_step_action:{rec_id}")
            if not isinstance(how, dict) or not how.get("zh-TW") or not how.get("en"):
                raise ValueError(f"repair_recipes_invalid_step_how:{rec_id}")
            if risk not in ("low", "medium", "high"):
                raise ValueError(f"repair_recipes_invalid_step_risk:{rec_id}")
            if not isinstance(requires_conf, bool) or not isinstance(may_change, bool):
                raise ValueError(f"repair_recipes_invalid_step_booleans:{rec_id}")

            if order == 1 and may_change is not False:
                raise ValueError(f"repair_recipes_first_step_must_be_read_only:{rec_id}")
            if (may_change or requires_conf) and risk == "low":
                raise ValueError(f"repair_recipes_modifying_step_cannot_be_low_risk:{rec_id}")

        for field, name, min_len in ((verify, "verify", 1), (stop_if, "stop_if", 1), (do_not, "do_not", 2)):
            if not isinstance(field, list) or len(field) < min_len:
                raise ValueError(f"repair_recipes_missing_or_short_{name}:{rec_id}")
            for entry in field:
                if not isinstance(entry, dict) or not entry.get("zh-TW") or not entry.get("en"):
                    raise ValueError(f"repair_recipes_invalid_entry_i18n_{name}:{rec_id}")

        seen_signals.append(sig)
        seen_ids.add(rec_id)

    if len(seen_signals) != len(expected_signal_set) or set(seen_signals) != expected_signal_set:
        raise ValueError("repair_recipes_signals_not_one_to_one_with_patterns")

    return data


def build_fixplan(log_path: Path, catalog_path: Path | None = None) -> dict:
    """Builds a deterministic, privacy-safe, read-only fixplan for a Minecraft log.

    Privacy: Never emits raw log lines, absolute file paths, usernames, or IP addresses.
    Ordering: Recipes follow mc_package_inspector.PATTERNS order, then recipe ID.
    Deduplication: Same signal across multiple lines produces one recipe with up to 20 lines.
    """
    if not isinstance(log_path, Path):
        log_path = Path(log_path)

    catalog = load_catalog(catalog_path)
    report = inspect_log(log_path)

    log_sha256 = report.get("file_sha256", "")
    findings = report.get("signals", [])

    signals_by_kind: dict[str, list[int]] = {}
    for item in findings:
        kind = item.get("kind")
        line = item.get("line")
        if kind and isinstance(line, int):
            signals_by_kind.setdefault(kind, []).append(line)

    catalog_by_signal: dict[str, list[dict]] = {}
    for rec in catalog.get("recipes", []):
        catalog_by_signal.setdefault(rec.get("signal", ""), []).append(rec)

    patterns_order = [kind for kind, _, _ in PATTERNS]
    ordered_kinds = [k for k in patterns_order if k in signals_by_kind] + [
        k for k in signals_by_kind if k not in patterns_order
    ]

    recipes: list[dict] = []
    unmatched_signals: list[str] = []

    for kind in ordered_kinds:
        lines = sorted(list(set(signals_by_kind[kind])))[:20]
        matching = catalog_by_signal.get(kind, [])
        if not matching:
            unmatched_signals.append(kind)
        else:
            for rec in sorted(matching, key=lambda x: str(x.get("id", ""))):
                recipe_entry = dict(rec)
                recipe_entry["evidence_lines"] = lines
                recipes.append(recipe_entry)

    unmatched_signals = sorted(list(set(unmatched_signals)))

    if unmatched_signals:
        status = "REVIEW_REQUIRED"
    elif recipes:
        status = "PLAN_ONLY"
    else:
        status = "NO_RECIPE"
        recipes = []

    return {
        "applied": False,
        "confirmed_root_cause": None,
        "log_sha256": log_sha256,
        "mode": "offline_read_only",
        "next_step": "以一次性沙箱重現；本輸出沒有執行任何變更",
        "not_verified": ["actual_fix_applied", "target_runtime_compatibility"],
        "recipes": recipes,
        "schema": FIXPLAN_SCHEMA,
        "status": status,
        "unmatched_signals": unmatched_signals,
    }


def format_human_plan(result: dict) -> str:
    """Formats a fixplan result into clear, structured zh-TW text for human operators."""
    status = result.get("status", "UNKNOWN")
    lines = [
        "【TotemOps 修復處方（Fixplan）】",
        f"狀態：{status}",
        f"日誌 SHA-256：{result.get('log_sha256', 'none')}",
    ]
    recipes = result.get("recipes", [])
    if not recipes:
        if status == "NO_RECIPE":
            lines.append("未在日誌中偵測到已知的崩潰特徵訊號，無需套用處方。")
        elif status == "REVIEW_REQUIRED":
            unmatched = ", ".join(result.get("unmatched_signals", []))
            lines.append(f"發現未匹配處方的訊號：{unmatched}，需人工檢視。")
    else:
        lines.append(f"\n共產出 {len(recipes)} 個建議修復配方：\n")
        for idx, r in enumerate(recipes, 1):
            title = r.get("title", {}).get("zh-TW", r.get("id", ""))
            signal = r.get("signal", "")
            ev_lines = r.get("evidence_lines", [])
            ev_str = ", ".join(str(l) for l in ev_lines)
            lines.append(f"=== 配方 {idx}：{title} ({r.get('id')}) ===")
            lines.append(f"  訊號類別：{signal}（日誌行號：{ev_str}）")
            lines.append(f"  原因說明：{r.get('why', {}).get('zh-TW', '')}")
            lines.append("  執行步驟：")
            for step in r.get("steps", []):
                order = step.get("order")
                action = step.get("action", {}).get("zh-TW", "")
                how = step.get("how", {}).get("zh-TW", "")
                risk = str(step.get("risk", "low")).upper()
                change = " [可能變更檔案]" if step.get("may_change_files") else " [唯讀]"
                confirm = " [需確認]" if step.get("requires_confirmation") else ""
                lines.append(f"    {order}. [{risk}]{change}{confirm} {action}")
                lines.append(f"       執行指引：{how}")
            lines.append("  驗證方式：")
            for v in r.get("verify", []):
                lines.append(f"    - {v.get('zh-TW', '')}")
            lines.append("  終止條件（Stop if）：")
            for s in r.get("stop_if", []):
                lines.append(f"    - {s.get('zh-TW', '')}")
            lines.append("  嚴禁操作（Do NOT）：")
            for d in r.get("do_not", []):
                lines.append(f"    - {d.get('zh-TW', '')}")
            lines.append("")

    lines.append(f"下一步：{result.get('next_step', '')}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for totem_repair_recipes.

    Exit codes:
      0 = Unused (fixplan never represents a verified fix)
      2 = BLOCK (unsafe path, oversized file, broken catalog, non-log)
      3 = PLAN_ONLY, NO_RECIPE, or REVIEW_REQUIRED (no actions executed)
    """
    args_list = list(sys.argv[1:] if argv is None else argv)
    if args_list and args_list[0] == "fixplan":
        args_list = args_list[1:]

    parser = argparse.ArgumentParser(
        prog="totem-ops fixplan",
        description="TotemOps deterministic read-only repair recipe plan generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exit codes:
  0 = Unused (fixplan never represents a verified fix)
  2 = BLOCK (safety gate blocked, invalid argument, or broken catalog)
  3 = PLAN_ONLY, NO_RECIPE, or REVIEW_REQUIRED (no actions executed)
""",
    )
    parser.add_argument("log_path", help="Path to Minecraft crash/server log")
    parser.add_argument("--json", action="store_true", help="Emit JSON output for agents")
    args = parser.parse_args(args_list)

    try:
        data = build_fixplan(Path(args.log_path))
    except (InputBlocked, OSError, ValueError, TypeError) as err:
        block_data = {
            "status": "BLOCK",
            "reason": str(err)[:120],
            "mode": "offline_read_only",
        }
        if args.json:
            print(json.dumps(block_data, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
        else:
            print(f"[BLOCK] {str(err)[:120]}")
        return 2

    if args.json:
        print(json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    else:
        print(format_human_plan(data))

    return 2 if data.get("status") == "BLOCK" else 3


if __name__ == "__main__":
    sys.exit(main())
