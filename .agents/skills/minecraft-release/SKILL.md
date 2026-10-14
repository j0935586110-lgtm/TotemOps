---
name: minecraft-release
description: TotemOps 唯讀 Minecraft CurseForge 整合包／更新包發布驗收。供 AGY、OpenCode、Hermes 等現有 Agent 使用，不是新同步引擎。
license: Apache-2.0
---

# Minecraft 發布助手（不死圖騰選用 Skill）

## 問題來源（MC8 實際 Windows 玩家流程）
- 官方 MC8 v3.5.0 CurseForge manifest 包含 322 筆必選與 14 筆可選的外部模組參照；PCL 首次匯入時真實逐一詢問 14 次。
- 官方更新 ZIP 說明要求人工刪除 3 個舊 JAR，再覆蓋 mods/config/servers.dat。這是當前服主實際需要簡化的動作。
- 先從發布端決策與既有啟動器／同步器著手，**不在每位玩家端部署 AI 滑鼠機器人，也不重寫 PCL、Prism 或同步引擎**。

## 只讀入口

```bash
python3 tools/totem_operator.py release inspect \
  --pack /path/to/full-curseforge-client.zip \
  --update /path/to/manual-update.zip
```

可省略 `--update`。標準輸出為單一 JSON：`status=REVIEW_REQUIRED`、`evidence=PACKAGING_STATIC_ONLY`，**命令 exit 0 代表報告成功，不代表允許發布**。

報告包含：
- 與來源 ZIP 雜湊綁定的版本、Minecraft/Loader、外部必需／可選項數量。
- **需要服主決策**的可選 CurseForge `projectID/fileID` 清單；只能由本人決定要「設為必要、排除、保留玩家可選」，Agent 不可默默修改原始 manifest。
- 從更新 README 抽出的「移除舊模組」候選、更新包需要複製或覆蓋的相對路徑；只提供 backup-first 的動作預覽，**不執行刪除／覆蓋**。
- 更新包與完整版 overrides 中同名檔案的雜湊差異；找不到同名項目**不能判為缺少模組**，可能由 CurseForge manifest 另外下載。
- 稽核界線：`write_performed=false`、`updates_applied=false`、`game_launched=false`、`server_contacted=false`。

## AGY / OpenCode 作業程序

1. 先確認正式公開來源與 SHA-256；不複製非授權模組到本專案，不下載不明來源 Jar。
2. 跑唯讀 release inspect，檢查 ZIP 路徑／重複／symlink 攔截與報告。
3. 若有選配模組／刪除舊檔，列出**最少的服主決策**，不要猜玩家偏好。
4. 服主核准後，優先運用既有 CurseForge/PCL/Prism 原生打包能力和 Barian modsync-v2、chyuaner python-minecraft-mods-sync，而非實作新安裝器。
5. 使用獨立 Windows 實例做「下載 → Java/Loader → 安裝 → 遊戲啟動」實測；以畫面、日誌與檔案結果驗證。未執行遊戲時一律 `GAME_LAUNCH_NOT_RUN`，Java/顯卡不支援時標 `ENVIRONMENT_BLOCK`。
6. 提交報告給服主核准；不得自動 push、發版、連玩家正式伺服器或刪改實際世界。

## 參考證據
- `evidence/MC8_REAL_WIN11_IMPORT_20261014.md`
- `evidence/TOTEM_PCL_OPTIONAL_LIVE_20261014.md`
- `evidence/MC8_RELEASE_REVIEW_20261014.json`

**本 Skill 是 AGY 等 Agent 的領域能力，不包含獨立 LLM。** 無 AI 時依舊可以執行上述 CLI。

## 新手教學與程式不一致的檢查（通用 Python 專案）

命令：

    python3 tools/totem_operator.py onboarding inspect --repo-dir /path/to/repo --entry main.py --readme README.md

- 解析 Python AST，比對 README 寫法與程式實際出現的 CLI 旗標，只呈現近似拼字與精確來源行號。不把其他工具（例如 PyInstaller）參數當成錯誤。
- 抓取 PCL／Prism 等新手教學章節的明確 TODO，提醒服主補上一份經實機驗證的範例；這不表示玩家不能玩。
- 回報 SOURCE_AND_DOCS_STATIC_ONLY 與 Git SHA／檔案 SHA-256，無網路、無執行同步器、無修改朋友文件。NO_FINDINGS 不等於可玩性通過。
- 最終玩家體驗應是下載、匯入、登入、啟動。AI 幫服主排除流程不一致，不要求玩家安裝額外 AI。

## 版本與更新器相容性檢查（只讀關卡）

執行：python3 tools/totem_operator.py release gate --help。

- 使用服主離線簽署的 release JSON + Ed25519 簽章與安裝器釘選公鑰；絕不打包私鑰。
- 必須指定唯一可信的 HTTPS 網域、profile 身份；未經授權的 HTTP、不同站點、重播、降版、版本序號衝突、破損簽章全部阻擋。
- Minecraft/Forge/NeoForge/Java 更換 -> MIGRATION_TEST_REQUIRED；更新器介面／發送網址更換 -> INSTALLER_RECONFIG_REQUIRED。
- 相同的環境與更新介面 -> READY/RUN_EXISTING_UPDATER（只是允許呼叫已有同步器，不代表安裝或下載完成）；同一版本每次開啟也應呼叫原更新器。
- 完整證據：evidence/SIGNED_RELEASE_COMPATIBILITY_PROTOTYPE_20261014.md；測試檔 tools/test_totem_release_gate.py。
- **Barian 現有 HTTP 模組 API 不能因發布資訊有簽章就變安全。** 需要服主提供正式 HTTPS 分發與可信的 JAR 完整性驗證，才能正式上線。
