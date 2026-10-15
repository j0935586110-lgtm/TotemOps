# TotemOps × modsync-v2：發布前靜態 Gate（2026-10-15）

## 已查證來源與授權界線

- Barian0517/modsync-v2，`master`：`readme.md`、`WorkerThread.py`、`MainWindow.py`，最後推送 2025-11-14。原始碼公開但先前檢索沒有明確可重用 LICENSE，**不能將其程式碼複製進 Apache-2.0 TotemOps**。
- `WorkerThread.run` 查詢 `/config_names?json=1` 和 `/<folder>/?json=1`，期待巢狀 JSON 物件，葉節點為檔案 MD5。
- `WorkerThread` source folder `mods` -> client `mods/servermods`（strict）；`clientmods` -> client `mods`（non-strict）；`needmods` -> client `mods/clientmods`（strict）。`MainWindow.py` 顯示 `needsmods`，與 worker 的 `needmods` 不一致；此差異尚無真實客戶端流程證明一定造成同步錯誤，但發布前必須拒絕混淆。
- 已有 `mc_package_inspector.inspect_one` 能界限讀取 JAR ZIP/TOML，解析 mod ID、版號、聲明依賴與 SHA-256；**不重造解析器**。

## 目前實作

僅 Python 3.11+ 標準庫（原檢查器內 PyYAML 為選用套件；NeoForge TOML 不需 PyYAML）：

```bash
python3 tools/totem_operator.py manifest ./mods --json
python3 tools/totem_operator.py manifest ./source-publish-root --layout modsync-v2 --json
```

第二種 layout 讀 `mods/`、`clientmods/`、`needmods/`，允許子目錄並保留相對路徑。根目錄有 `needsmods/` 便拒絕；任何掃描範圍內 symlink、壞 JAR、重複 modId、明確宣告不相容、檔名大小寫撞名會 BLOCK。需要的前置未包含在此次來源集合時為 REVIEW_REQUIRED（**不能直接判定伺服器缺前置**）。輸出欄位：

- `files[]`：`source_folder`、`path`、`mod_ids[]`、`sha256`、`md5_legacy`。
- `modsync_v2_inventory_preview`：按 folder 還原至原 HTTP API 的巢狀「檔名 → MD5」視圖；**不是可直接發布的完整清單**（`config/kubejs` 等非 JAR 尚未審查）。MD5 只供舊協定相容，不用作安全簽章。
- `execution_side=UNKNOWN`：NeoForge TOML dependencies 的 `side=CLIENT|SERVER|BOTH` 是**依賴關係端別**，不是整個 JAR 的單端真實判斷。
- `release_allowed=false`、`publication_performed=false`、`write_performed=false`、`game_launched=false` 永遠成立。

退出碼：`2`＝BLOCK、`3`＝REVIEW_REQUIRED（刻意 nonzero，避免 CI 綠燈被直接理解成可發布）。無自動解除審核開關。

## 下一條可驗證流程

1. 靜態 Gate → 人工核對 Client/Server 意圖與完整 config/kubejs 範圍。
2. 使用既有 `itzg/minecraft-server` 在用完即焚的 **獨立 Docker 網路與世界**跑 server boot smoke，驗證 SHA-256、loader、啟動狀態與 logs；不允許僅 `Done` 訊息就說全部模組玩法正常。
3. 真正 NeoForge 同版本客戶端登入 / GameTest；功能 UI/玩家傳送仍需獨立證據。
4. 發布前的清單差異／回滾演練及擁有者核准。禁止對 Barian、chyuaner 正式環境寫入或推送。

本次測試用合成 JAR fixture，只能證明靜態分析程式能識別相應條件；不能當成朋友實際模組已通過。
