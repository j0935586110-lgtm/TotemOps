# TotemOps / 朋友優先的深度痛點調查與新手體驗決策
日期：2026-10-14（Asia/Taipei）
狀態：研究 + 泛用最小工具已驗收；**未修改朋友 GitHub 倉庫、正式網站、伺服器或玩家世界**。

## 方法：先從他們已經做的解法逆推，禁止無憑據重造

- 直接檢視網站 mcweb.barian.moe、mc8.yuaner.tw/page/download，以及以下實際公共倉庫的原始碼與 README。
- 確認已有能力 → 找使用者旅程的缺口 → 找同一功能的真實證據 → 只做可驗證的最小交付。
- 「README 沒提」不等於不存在；「靜態原始碼有疑點」不等於正式部署版本正在故障。所有站點連線/下載狀態需另做正常玩家瀏覽器實測。
- 不要求每一位 Minecraft 玩家用 AI。Minecraft 啟動器和同步器歸朋友原本工具負責，TotemOps 服務開發者／服主。

## 已有成熟解法：不應重做

### Barian
1. modsync-v2 (b63df158330cdc0624f2565c1cc8df3d89c55bc0)：有 GUI、--auto、--dir、config 同步、必要時 ZIP；故不重做模組下載器。
2. Multiverse-Forge-V2 / Essentials / InventoryRollback：正在自己做 Minecraft 遊戲玩法、跨版本維護。需要更少時間完成編譯、改動與發布，不需要讓 AI 幫他玩。
3. mcserver-web：已有玩家網站與進服資訊。最新 checkout 為 2025 年網站倉庫，**不能假設就是目前正式網站同版**。

### chyuaner
1. python-minecraft-mods-sync (4453bdfedb75ae35e913fd1dd5554f0440cbb59e)：README 已說明 ZIP／單檔切換（大差異 >70% 選 ZIP）、ZIP 失敗退單檔、只管理 barian_ 開頭的模組以保護玩家自加模組、Prism 預啟動命令、PCL 的 --inst 解析。**不重做上述機制**。
2. php-minecraft-server-info (0fe73ffacb511b25a858391055575877ee151a42)：已做 /mods JSON、檔案下載、ZIP、快取與可用性考量；README 清楚提到 www-data 權限與 sudo 導致擁有者不同的維運風險，但不能因此斷言目前網站在故障。
3. Minecraft-NeoAuthReloaded (1c7a7d0eec9a9583e2db3638fbbc8e445ce4c6c3)：跨 Forge/NeoForge、官方／離線帳號認證，已專門處理握手延遲、重播 race，並有 client smoke runner。若做 Agent，應調用現有測試而不是再次發明認證系統。
4. WSMC / BlueMap Barian Essentials：跨協定、多世界與跨倉庫插件整合。只有在實際更新或故障時才觸發相依檢查，無須長期無限輪詢。

## 痛點排序（事實、推論、尚待本人證明必須分開）

### P0 / Barian 玩家更新可靠度：程式碼中可證明的風險
- 公開 main.py:96-99 用 worker.finished 直接回報「✅ 同步完成」並 app.quit；finished != every file validated。
- WorkerThread.py:339-355：download_and_verify 即使初始 download_file 失敗也仍會到 return True；重驗 MD5 不合後只再次下載但未檢查第二次結果。
- WorkerThread.py:90-103 請求失敗會 continue；批量 futures 過程只更新 progress，這些不能保證整個同步成功。
- 重要註記：實際使用者下載的編譯版是否等於這份公開 repo，**尚未比對 EXE 版本／雜湊**。
- 最小改善建議：擴充原同步器的確定性 sync result、非零失敗退出碼與預啟動阻擋。先做 mock/隔離測試與 patch 交服主審閱，不直接部署。
- 官網公開 URL http://modapi.barian.moe/clientupdate 曾在 Linux / Windows 測試機取得 HTTP 502；本輪 Ubuntu 再取仍 502，HTTPS 發 TLS unrecognized name。**只代表該測試網路路線失敗，不聲稱所有玩家均無法下載**。應先在本人正常瀏覽器/網路確認源頭與發布網址。

### P0 / MC8 新玩家 14 次選配詢問：我們親自遇到
- 官方 CurseForge 整合包 v3.5.0：Minecraft 1.21.1 NeoForge 21.1.250，322 筆必選+14 筆可選 CurseForge 外部 file refs。
- PCL 正式 Windows 匯入時確實逐次問 14 個 optional；已用 J1 true foreground + UIA 動態座標逐次確認，最後完成進入 launcher。但這不代表全新安裝必然每次都需要同樣流程（不同 launcher 可能呈現不同預設）。
- 新手真正痛點是「有 14 個不清楚如何決定的選項」，不是缺少一個 Agent 代點 14 次。應詢問服主哪些選項要預設安裝、哪些保留選配，提供省操作、可回滾且尊重版權的發布方案，不能擅自把全部改 required。

### P1 / Docs↔Code 新手一致性（本輪新增泛用 CLI，已實查）
- Barian README readme.md:29 使用 --reconf，但 main.py:34 實際辨識 --reconfig。是否有另一個編譯版支援別名未確認，但公開文件與公開來源明確不一致。
- chyuaner README.md:55 的 PCL Launcher 安裝設定章節仍寫「TODO: 待補」，雖然 main.py 已有 PCL 目錄替換標記解說與 --inst 入口。PCL 使用者可能無法從 README 知道正確如何預啟動；但 MC8 官網目前主推薦 Prism/Fjord，故這項是**需要確認玩家使用比例**的可改善點，不應直接斷言大家都困擾。
- 新工具（對任意 Python repo、無朋友硬編碼）：
  python3 tools/totem_operator.py onboarding inspect --repo-dir REPO --entry main.py --readme README.md
  利用 Python AST 靜態取旗標與 README 對照相近拼字、識別 PCL/Prism onboarding 小節明確 TODO，附 Git HEAD/文件 SHA-256/行號；不執行 Python 源碼、不跑下載、不改原 repo，NO_FINDINGS 也不宣稱玩家流程 PASS。
- 本輪實查兩份 JSON：evidence/BARIAN_ONBOARDING_AUDIT_20261014.json / evidence/YUAN_ONBOARDING_AUDIT_20261014.json。

### P1 / 新版更新不應對剛全新安裝的玩家重複執行
- MC8 官網完整包與同版 update ZIP 有獨立版本策略；官方 README 要手動刪 3 個舊 JAR、新增/覆蓋 9 個檔。
- 實際 Windows 全新 v3.5.0 安裝實例中：3 個舊 JAR 均不在；新 multimine 與 wsmc 已經存在。是應先區分 fresh vs upgrade 的證據。
- TotemOps release inspect 已可產生 read-only 版本、更新與可選模組報告。下一版可以在人工核准後改善「只針對舊版」的升級指引；不新增玩家端同步引擎。

### P2 / 跨專案相容性、登入、BlueMap API 等
- Chyuaner 已經建立 CI、smoke test 與會話穩定機制。只有實際改動（例如 php API JSON, NeoAuth 或 BlueMap 介面）才讓 AGY/OpenCode 幫忙找 downstream、跑原本測試，不 24/7 推理所有專案。
- 外部玩家密碼、登入資料庫、正式站點資料不應進入外部模型；測試用假帳號/假資料庫、隔離世界。

## 新手體驗原則：相同結果應縮短路徑而不是增加 Agent
目標新玩家：網站 → 下載既有可信啟動器/整合包 → 匯入一次 → 依清楚指引選 Java/記憶體與登入 → 開始玩。
目標老玩家：啟動 → 原生 updater 比對/可靠更新 → 成功才啟動遊戲；失敗時告知「哪一個模組、為什麼、如何重試」，不得假稱完成。
目標服主：只提供已授權的 ZIP/repo → TotemOps 提供差異/風險與可選項決策 → AGY 編寫最小 patch → 既有測試/沙箱實證 → 本人批准發布。

### 泛用而不失焦
- 核心是「使用者旅程、版本來源、確定性比較、真實結果、授權界線」，可泛用其他 Minecraft 服主。
- Barian 與 chyuaner 的網址、預啟動命令、版本檔名、模組前綴均屬 Profile/Skill 的配置，**不寫死進核心**。
- 使用官方 CLI 和已存在的同步器、啟動器、CI。不得再造通用 agent、下載器、24 小時監控、登入系統。

## 需問朋友（不是先替他們選）
- Barian：「目前玩家每次新進服／模組更新，最多哪一步向你求助？官方下載編譯版的版本與 GitHub modsync-v2 相同嗎？」
- chyuaner：「你日常玩家主要是 Prism/Fjord 還是 PCL？未來想讓 PCL 也一鍵自動同步嗎？你最麻煩的更新是同步 API 還是 NeoAuth 登入？」
- 各拿最近一次真實的安裝求助或發版事件，衡量新舊耗時/新手步驟/最終能否遊玩；沒有改善就不做。

## 本輪可驗證交付／未完成
- 新工具 tools/totem_onboarding.py 與 tools/test_totem_onboarding.py：10 tests PASS。
- 兩位朋友公開 repo 的 read-only source/doc audit：均 1 項有具體檔案行號的 finding。
- 未執行兩位朋友的同步程式、未安裝正式 Java21、未登入 Minecraft 帳號、未啟動單機遊戲或連正式 server，未 push 公開 PR。
- 這些項目皆需後續實際確認：PCL 新手教學完整安裝、網站正常玩家來源的檔案可用性、Barian 編譯版與 GitHub 來源版本是否一致。
