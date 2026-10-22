#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""TotemOps offline triage verdict engine.

Consolidates declared dependency closure and log repair recipe fixplans into a single verdict.
Strictly offline, read-only, privacy-safe. No network lookups, no server mutation.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from totem_dependency_closure import check_closure
    from totem_repair_recipes import build_fixplan
except ImportError:
    from tools.totem_dependency_closure import check_closure
    from tools.totem_repair_recipes import build_fixplan

TRIAGE_SCHEMA = "totemops.triage/1"
NOT_VERIFIED_CHECKS = [
    "remote_availability",
    "runtime_resolution",
    "maven_full_semantics",
    "actual_server_boot",
]


def run_triage(
    path: Path | str,
    log_path: Path | str | None = None,
    side: str = "both",
) -> dict:
    if not isinstance(path, Path):
        path = Path(path)

    # 1. Run dependency closure check
    closure_res = check_closure(path, side=side)

    # Determine mod input info
    file_count = closure_res.get("supplied", {}).get("count", 0)
    if path.is_file():
        suffix = path.suffix.lower()
        if suffix == ".jar":
            mod_kind = "jar"
            file_count = 1
        elif suffix == ".mrpack":
            mod_kind = "mrpack"
            if file_count == 0:
                file_count = 1
        else:
            mod_kind = "jar"
            file_count = 1
    elif path.is_dir():
        mod_kind = "mods_dir"
        if file_count == 0 and path.exists():
            try:
                candidate_files = [p for p in path.iterdir() if p.suffix.lower() in {".jar", ".zip", ".mrpack"}]
                file_count = len(candidate_files)
            except OSError:
                file_count = 0
    else:
        mod_kind = (
            "mods_dir"
            if not path.suffix
            else (
                "jar"
                if path.suffix.lower() == ".jar"
                else "mrpack"
                if path.suffix.lower() == ".mrpack"
                else "unknown"
            )
        )
        file_count = 0

    inputs = [{"file_count": file_count, "kind": mod_kind}]

    # 2. Run fixplan if log_path is provided
    fixplan_res = None
    fixplan_summary = None

    if log_path is not None:
        if not isinstance(log_path, Path):
            log_path = Path(log_path)

        if not log_path.exists():
            inputs.append({"file_count": 0, "kind": "log", "log_sha256": ""})
            fixplan_summary = {"signals": [], "status": "BLOCK", "top_action": None}
            fixplan_res = {
                "recipes": [],
                "status": "BLOCK",
                "reason": "log_path_not_found",
                "unmatched_signals": [],
            }
        elif log_path.is_symlink():
            inputs.append({"file_count": 0, "kind": "log", "log_sha256": ""})
            fixplan_summary = {"signals": [], "status": "BLOCK", "top_action": None}
            fixplan_res = {
                "recipes": [],
                "status": "BLOCK",
                "reason": "log_symlink_not_allowed",
                "unmatched_signals": [],
            }
        elif not log_path.is_file():
            inputs.append({"file_count": 0, "kind": "log", "log_sha256": ""})
            fixplan_summary = {"signals": [], "status": "BLOCK", "top_action": None}
            fixplan_res = {
                "recipes": [],
                "status": "BLOCK",
                "reason": "log_not_a_regular_file",
                "unmatched_signals": [],
            }
        else:
            try:
                fixplan_res = build_fixplan(log_path)
                log_sha256 = fixplan_res.get("log_sha256", "")
                inputs.append({"file_count": 1, "kind": "log", "log_sha256": log_sha256})

                signals = []
                for r in fixplan_res.get("recipes", []):
                    sig = r.get("signal")
                    if sig and sig not in signals:
                        signals.append(sig)
                for sig in fixplan_res.get("unmatched_signals", []):
                    if sig and sig not in signals:
                        signals.append(sig)
                signals.sort()

                recipes = fixplan_res.get("recipes", [])
                top_action = None
                if recipes:
                    top_action = recipes[0].get("title", {}).get("zh-TW", recipes[0].get("id", ""))

                fixplan_summary = {
                    "signals": signals,
                    "status": fixplan_res.get("status", "UNKNOWN"),
                    "top_action": top_action,
                }
            except Exception as exc:
                reason_str = str(exc)[:80]
                if "/" in reason_str or "\\" in reason_str:
                    reason_str = "log_inspection_blocked"
                inputs.append({"file_count": 0, "kind": "log", "log_sha256": ""})
                fixplan_summary = {"signals": [], "status": "BLOCK", "top_action": None}
                fixplan_res = {
                    "recipes": [],
                    "status": "BLOCK",
                    "reason": reason_str,
                    "unmatched_signals": [],
                }

    # 3. Closure summary
    closure_summary = {
        "incompatible_pairs": len(closure_res.get("incompatible_pairs", [])),
        "missing": len(closure_res.get("missing", [])),
        "status": closure_res.get("status", "UNKNOWN"),
        "unresolved_ranges": len(closure_res.get("unresolved_ranges", [])),
        "version_mismatch": len(closure_res.get("version_mismatch", [])),
    }

    # 4. Actions collection
    raw_actions = []

    # From closure
    for m in closure_res.get("missing", []):
        to_mod = m.get("to", "")
        req_by = ", ".join(m.get("required_by", []))
        vranges = ", ".join(m.get("version_ranges", [])) if m.get("version_ranges") else ""
        range_part = f"，範圍 {vranges}" if vranges else ""
        raw_actions.append({
            "action": f"補上 {to_mod}（被 {req_by} 要求{range_part}）後重跑 triage",
            "blocks_boot": True,
            "sort_name": to_mod,
            "source": "closure",
            "why": f"缺少必要依賴模組 {to_mod}，伺服器啟動時將因依賴不足而失敗",
        })

    for vm in closure_res.get("version_mismatch", []):
        to_mod = vm.get("to", "")
        req_by = ", ".join(vm.get("required_by", []))
        sup_ver = vm.get("supplied_version", "")
        vrange = vm.get("version_range", "")
        raw_actions.append({
            "action": f"更新或更換 {to_mod}（目前版本 {sup_ver} 不滿足 {req_by} 要求之範圍 {vrange}）後重跑 triage",
            "blocks_boot": True,
            "sort_name": to_mod,
            "source": "closure",
            "why": f"已安裝模組 {to_mod} 版本不符宣告要求，載入器將拒絕載入",
        })

    for inc in closure_res.get("incompatible_pairs", []):
        from_mod = inc.get("from", "")
        to_mod = inc.get("to", "")
        vrange = inc.get("version_range", "")
        range_part = f"（範圍 {vrange}）" if vrange else ""
        raw_actions.append({
            "action": f"移除或隔離衝突模組 {from_mod} 或 {to_mod}{range_part}後重跑 triage",
            "blocks_boot": True,
            "sort_name": to_mod,
            "source": "closure",
            "why": f"模組 {from_mod} 與 {to_mod} 宣告互不相容，同時載入會導致啟動崩潰",
        })

    for u in closure_res.get("unresolved_ranges", []):
        from_mod = u.get("from", "")
        to_mod = u.get("to", "")
        vrange = u.get("version_range", "")
        u_reason = u.get("reason", "")
        raw_actions.append({
            "action": f"人工確認 {to_mod} 版本是否相容於 {from_mod} 之要求範圍 {vrange}（原因：{u_reason}）",
            "blocks_boot": False,
            "sort_name": to_mod,
            "source": "closure",
            "why": "版本範圍語法或版本格式無法由離線規則直接判定",
        })

    if closure_res.get("status") == "BLOCK":
        c_reason = closure_res.get("reason", "unknown")
        raw_actions.append({
            "action": closure_res.get("next_step", "請確認輸入路徑並重新檢查"),
            "blocks_boot": True,
            "sort_name": c_reason,
            "source": "closure",
            "why": f"依賴閉包檢查遭阻擋（{c_reason}）",
        })

    # From fixplan (only if log_path was given)
    if fixplan_res:
        if fixplan_res.get("status") == "BLOCK":
            f_reason = fixplan_res.get("reason", "unknown")
            raw_actions.append({
                "action": f"確認日誌檔案有效且可讀取（原因：{f_reason}）",
                "blocks_boot": True,
                "sort_name": "log_blocked",
                "source": "fixplan",
                "why": "日誌檔案無法讀取或格式無效，無法提取崩潰特徵",
            })
        else:
            for r in fixplan_res.get("recipes", []):
                sig = r.get("signal", "")
                title = r.get("title", {}).get("zh-TW", r.get("id", ""))
                why_text = r.get("why", {}).get("zh-TW", "")
                raw_actions.append({
                    "action": f"依處方套用：{title}",
                    "blocks_boot": True,
                    "sort_name": sig,
                    "source": "fixplan",
                    "why": why_text or f"日誌中偵測到崩潰訊號 {sig}",
                })
            for sig in fixplan_res.get("unmatched_signals", []):
                raw_actions.append({
                    "action": f"人工檢視未匹配處方之日誌訊號：{sig}",
                    "blocks_boot": True,
                    "sort_name": sig,
                    "source": "fixplan",
                    "why": "日誌中出現未收錄至修復處方之崩潰訊號",
                })

    def _action_sort_key(item: dict) -> tuple:
        bb = 0 if item["blocks_boot"] else 1
        src = 0 if item["source"] == "closure" else 1
        name = str(item.get("sort_name", "")).casefold()
        return (bb, src, name)

    raw_actions.sort(key=_action_sort_key)

    actions = []
    for rank_idx, item in enumerate(raw_actions, 1):
        actions.append({
            "action": item["action"],
            "blocks_boot": item["blocks_boot"],
            "rank": rank_idx,
            "source": item["source"],
            "why": item["why"],
        })

    # 5. Determine verdict and reason
    closure_status = closure_res.get("status", "UNKNOWN")
    fixplan_status = fixplan_res.get("status") if fixplan_res else None

    if closure_status == "BLOCK" or (fixplan_res is not None and fixplan_status == "BLOCK"):
        verdict = "BLOCK"
        if closure_status == "BLOCK":
            reason = closure_res.get("reason", "closure_check_blocked")
        else:
            reason = fixplan_res.get("reason", "log_analysis_blocked")
    elif (
        closure_status in ("REVIEW_REQUIRED", "BLOCK")
        or (fixplan_res is not None and fixplan_status in ("REVIEW_REQUIRED", "PLAN_ONLY", "NO_RECIPE", "BLOCK"))
    ):
        verdict = "REVIEW_REQUIRED"
        reason = None
    elif closure_status == "PASS" and (fixplan_res is None or fixplan_status == "PASS"):
        verdict = "PASS"
        reason = None
    else:
        verdict = "REVIEW_REQUIRED"
        reason = None

    # 6. Conflicts detection
    conflicts = []
    if closure_status == "PASS" and fixplan_summary and fixplan_summary.get("signals"):
        sig_str = ", ".join(fixplan_summary["signals"])
        conflicts.append(f"宣告依賴檢查為 PASS，但日誌偵測到崩潰特徵（{sig_str}），可能為執行時期動態引用或未宣告之相依項目。")

    # 7. Next step
    if verdict == "PASS":
        next_step = "宣告 metadata 自洽且無待處理處方，若要確認可開服請在隔離沙盒實跑"
    elif verdict == "BLOCK":
        next_step = f"請排除阻擋原因（{reason}）後重新執行 triage 裁決"
    else:
        next_step = "請依建議動作依序處理問題後，重新執行 triage 裁決"

    return {
        "actions": actions,
        "closure_summary": closure_summary,
        "conflicts": conflicts,
        "fixplan_summary": fixplan_summary,
        "inputs": inputs,
        "mode": "offline_read_only",
        "next_step": next_step,
        "not_verified": NOT_VERIFIED_CHECKS,
        "reason": reason,
        "schema": TRIAGE_SCHEMA,
        "verdict": verdict,
        "verified_scope": "declared_metadata_only",
    }


def format_human_triage(data: dict) -> str:
    verdict = data.get("verdict", "UNKNOWN")
    lines = [f"【TotemOps 裁決】狀態：{verdict}"]

    cl_sum = data.get("closure_summary", {})
    fp_sum = data.get("fixplan_summary")
    cl_status = cl_sum.get("status", "NONE")
    fp_status = fp_sum.get("status") if fp_sum else "未提供"
    lines.append(f"檢查摘要：依賴閉包 {cl_status} ｜ 日誌處方 {fp_status}")

    actions = data.get("actions", [])
    if actions:
        show_count = min(len(actions), 3)
        lines.append(f"建議動作（共 {len(actions)} 項，顯示前 {show_count} 項）：")
        for act in actions[:show_count]:
            prefix = "[阻擋開服]" if act.get("blocks_boot") else "[建議]"
            lines.append(f"  {act.get('rank')}. {prefix} {act.get('action')}")
    else:
        lines.append("建議動作：無待處理動作")

    conflicts = data.get("conflicts", [])
    if conflicts:
        lines.append(f"衝突警示：{conflicts[0]}")

    lines.append(f"下一步：{data.get('next_step', '')}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)
    if args_list and args_list[0] == "triage":
        args_list = args_list[1:]

    parser = argparse.ArgumentParser(
        prog="totem-ops triage",
        description="TotemOps offline dependency closure and log repair triage verdict",
    )
    parser.add_argument("path", help="Path to mods directory, single JAR, or .mrpack")
    parser.add_argument("--log", default=None, help="Path to Minecraft crash/server log")
    parser.add_argument("--side", choices=("both", "client", "server"), default="both")
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    args = parser.parse_args(args_list)

    result = run_triage(
        Path(args.path),
        log_path=Path(args.log) if args.log else None,
        side=args.side,
    )

    verdict = result.get("verdict")
    exit_code = 0 if verdict == "PASS" else 2 if verdict == "BLOCK" else 3

    if args.json:
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    else:
        print(format_human_triage(result))

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
