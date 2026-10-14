# TotemOps — 兩位朋友實際工作流程，第 1 輪

日期：2026-10-14（Asia/Taipei）
主線：/home/LOCAL_USER/agy-minecraft-sandbox
性質：僅分析公開原始碼、產出可機器讀取收據。沒有啟動玩家客戶端、修改朋友的正式 GitHub repo、發 PR、修改伺服器或呼叫正式模組 API。

## Barian：以玩家可一鍵玩為成功指標

- Barian0517/modsync-v2，commit：b63df158330cdc0624f2565c1cc8df3d89c55bc0。
- 已有 Windows PyQt GUI、模組與 config 同步、--auto 自動開始、--dir 指向實例。**先重用**，不能重造。
- 來源 main.py：QThread 的 finished event 被當成同步成功，然後 app.quit。WorkerThread.py 的 download_and_verify 在下載失敗／hash 未驗證時仍可能 return True；前置必要工作是把失敗傳遞到 process exit，否則無法可靠接到啟動器預啟動命令。
- 新玩家第一次下載一鍵安裝 PCL/Forge：現有 repo 並沒有這個已驗證完成的安裝器；最佳路線是重用合法的 PCL 實例打包／匯入功能，再研究是否真的需製作安裝 EXE。
- 指令：python3 tools/totem_operator.py friend-flow barian-player --repo-dir /home/LOCAL_USER/totemops-friend-review-20261014/modsync-v2
- 結果 ACTIONABLE/STATIC_ONLY，遊戲可玩狀態與 Windows GUI E2E = NOT_RUN。

## chyuaner：後端改版是否破壞自有客戶端

- chyuaner/php-minecraft-server-info commit：0fe73ffacb511b25a858391055575877ee151a42。
- chyuaner/python-minecraft-mods-sync commit：4453bdfedb75ae35e913fd1dd5554f0440cbb59e。
- Barian modsync 同上。
- PHP producer public/mods.php + src/McModUtils/Mod.php 發布 /mods、/mods/zip、mods 陣列、sha1、downloadUrl。
- chyuaner Python client src/mcmods_sync/server.py 使用 /mods/?type=json + mods[]/sha1/downloadUrl。
- **實際 API 部署主機不能從 git 推定**：Yuan sync config 預設 api-minecraft.yuaner.tw，而 PHP 文件範例為 mc-api.yuaner.tw。這些是原始碼的 API family 相容關係，不代表目前這兩個域名配置已證實一致。
- Barian client 預設 modapi.barian.moe，讀 /config_names?json=1 和 /{folder}/?json=1；不能推定受前述 PHP API 變更影響，也不該硬把兩個同步器整合成單一引擎。
- 指令：python3 tools/totem_operator.py friend-flow yuan-impact --api-dir /home/LOCAL_USER/totemops-friend-review-20261014/php-minecraft-server-info --updater-dir /home/LOCAL_USER/totemops-friend-review-20261014/python-minecraft-mods-sync --barian-dir /home/LOCAL_USER/totemops-friend-review-20261014/modsync-v2 --changed-file public/mods.php
- 結果：Yuan updater SOURCE_CONTRACT_MATCH / affected=true；Barian DIFFERENT_DEFAULT_API / affected=UNKNOWN。**尚未 mock API 或 live HTTP E2E。**

## 優先級

1. Barian 的現有 updater 可靠地回報失敗，再利用 PCL 原有的版本匯入與預啟動整合；後續做乾淨 Windows 首次安裝與正常入服實測。
2. chyuaner 更新後端 API 時，用 TotemOps 查改動影響哪些現有 consumer；只對受影響的路徑跑其原有 mock/CI/同步器測試。
3. 不建新同步器、不建另一個監控平台、不造大型 Agent 運行環境。專用 Skill + deterministic read-only tools + AGY 現有檔案/Git 能力已足夠做第一輪。
4. 跨服務授權、repo 版本、網站部署是否符合目前 GitHub，必須由本人確認，不能基於靜態分析直接發布。

## 可稽核完成標準

- 功能：tools/totem_friend_flows.py，透過 tools/totem_operator.py friend-flow 進入，僅讀 source。
- 測試：tools/test_totem_friend_flows.py，測可靠成功與失敗標記、不同 API 不誤歸因、來源 symlink/path 受限、未知路徑不提醒。
- 兩位朋友各有一個真實場景的 STATIC_ONLY 報告；Windows PCL 首次安裝、GUI、玩家入服、API mock end-to-end 均未驗證，不能寫成已完成。

## AGY 本次模型呼叫的實際限制

- AGY 1.3.4 / gemini-3.8-flash-low / plan + sandbox headless 呼叫試圖存取工具，但工具要求 command permission；headless 不能互動確認，因此被平台明確 auto-denied，回應 `jetski: no output produced`。本輪 AGY **NOT_RUN/BLOCK_PERMISSION**，不可宣稱模型已執行新流程。
- 沒有使用 dangerously-skip-permissions、沒有修改權限、沒有繞過 gate。先由確定性 CLI + Python 單元測試驗收。
