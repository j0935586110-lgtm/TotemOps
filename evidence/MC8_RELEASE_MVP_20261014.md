# TotemOps 發布助手 MVP / 2026-10-14

此報告是**本人授權的真實 Windows 測試與公開 ZIP 唯讀分析**，不是兩位朋友的正式發版核准。

## 完成：Release Inspect v0.1

- 指令：`python3 tools/totem_operator.py release inspect --pack /path/complete.zip --update /path/update.zip`
- 工具：`tools/totem_release.py`，AGY/OpenCode Skill：`.agents/skills/minecraft-release/SKILL.md`。
- 讀入：MC8 官網 `Yuan-MC8-v3.5.0-client.zip`（SHA-256：`7e0a69af9f113aaaa692787b210cfedde42ed9f43e725658cb1366c0e09ad439`）與 `MC8-v3.5.0-update.zip`（SHA-256：`6d6142b792ace4351c4ed0cf00746601a79ef9b04493cddc36772f6358b27abd`）。
- 來源 JSON：`evidence/MC8_RELEASE_REVIEW_20261014.json`。
- 返回：`REVIEW_REQUIRED` + `PACKAGING_STATIC_ONLY`，不是發版、安裝或遊戲成功。寫入、刪除、登入、連線正式伺服器：**全部無**。
- 解析 Minecraft 1.21.1 / NeoForge 21.1.250，322 個必選 + 14 個可選外部檔案。
- 更新包 README 要求手動刪除 3 個舊 JAR；ZIP 包含需複製/覆蓋的 9 個遊戲相對路徑。
- 與完整包 `overrides` 同名檔案比較：4 同雜湊、1 有差異（`servers.dat`）、4 不在完整包 overrides（**不表示缺少**，可能由外部 manifest 參照）。`servers.dat` 差異代表更新版要覆蓋，需服主確認是否刻意。
- 呈現 update 的 `REMOVE_AFTER_BACKUP` 與 `COPY_AFTER_BACKUP` 只是**計畫預覽**；執行權限需要另行授予，不影響現有遊戲檔案。

## 關鍵實機交叉驗證

- Windows 裝置 `desktop-jne4fna-bdb6`、PCL 2.13.1.1，獨立實例路徑 `C:\TotemOps-Test-20261014\launcher\.minecraft\versions\Yuan MC8 Client Prod`。
- 在官網**全新安裝** v3.5.0，三個手動刪除目標 JAR `better_tools_and_armor_v13.1.1-neoforge-1.21.1.jar`、`zstdnet-1.21.1-neoforge-1.4.8.jar`、`MultiMine-neoforge-1.2.0.jar` 均不存在；`multimine-1.21.1.1NF.jar` 與 `wsmc-0.7.2-neoforge.jar` 則已存在。
- 因此**新安裝不能盲套同版更新包**：其 3 個刪除是舊版升級遷移步驟，對新實例不需要。更不應盲目覆蓋 `servers.dat` 等玩家可能更改的檔案。
- PCL 先前的 14 個可選模組提醒已由 UIA 動態定位 + J1 foreground SendInput 在一次性 Windows 測試中全部驗收；未新增玩家端 AI。
- 這說明真正的發版助手需要先分類 `FRESH_INSTALL` vs `UPGRADE`，再決定是否提供增量更新或只需完整包。未經版本前置檢查，不執行 update。

## P0 Java / 遊戲驗收

- PCL 版本設定中 Java 選「自動」；文字明確顯示**無法用的 Java，PCL 將於啟動時自動下載**。
- MC8 version JSON 明確要求 Java **21**，Windows 現有舊 Java runtime 為 **16.0.1**，未發現 Java21。
- 版本的 JVM 記憶體選項「跟隨全局」，GUI 顯示分配約 **7.0 GB**。當下 Windows 可用物理記憶體約 7.6–7.8 GB，且 Chrome/Gemini 等作業仍在運行。
- GPU `Intel(R) HD Graphics`，driver `10.18.10.4252`；實際 OpenGL 能力與 1.21.1 啟動相容**尚未驗證**。
- 因此本輪採取 fail-closed：**沒有按「啟動遊戲」**，沒有觸發 PCL 的 Java21 自動下載、沒有登入遊戲或進伺服器。主因是避免 7GB 配額與當下有限的宿主記憶體造成其他工作的 OOM/換頁負荷，並非宣稱 MC8 遊戲本身不能玩。
- 後續須找**有足夠可用記憶體／GPU 且可回滾**的 Windows 實驗機，或於業務作業閒置時經使用者安排再跑 Java21 → NeoForge → 實際單機遊戲畫面驗收。

## 工程驗收 / 界線

- 10 組 deterministic release tests；阻擋路徑穿越、大小寫重複、symlink、惡意更新包目錄；驗證 read-only 與檔案未刪除。
- 現場混合工作樹原有及新增 `python3 -m unittest discover -s tools -p 'test_*.py' -q`：**222 項 PASS**。原型 `local_tasks` 的舊測試仍打印已知授權漏洞提示，**不屬本次 release MVP，更不能宣稱已修復**。
- 新功能不在玩家端增加安裝工具，單純協助 AGY/OpenCode 調用確定性 CLI 作發版審核。
- 朋友的 GitHub repo、網站、正式 MC8 伺服器、存檔均未修改；未 push PR 或做任何更新檔案刪除。
