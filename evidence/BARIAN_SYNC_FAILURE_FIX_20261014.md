# TotemOps — Barian modsync-v2 可靠更新修補：實測與交接證據
日期：2026-10-14
性質：獨立本地工作樹實作與驗收；**未修改 Barian 原始倉庫、網站、正式伺服器或任何玩家實例，亦未推 PR**。

## 需求是否成立：已由原版程式＋RED 實驗證實

公開來源：Barian0517/modsync-v2，原始 Git HEAD `b63df158330cdc0624f2565c1cc8df3d89c55bc0`；公開倉庫未發現 LICENSE，**不得在未徵得本人同意前將其程式碼複製發布到 TotemOps Apache 專案**。

實際原始碼：
- `WorkerThread.py:339-355` 的 `download_and_verify` 即使 `download_file` 回 `False`，最後仍回 `True`；首次與重試之後的 MD5 錯誤未能穩定傳遞。
- `WorkerThread.py:48-103` 的資料夾清單／各資料夾下載列表異常，有 `return` 或 `continue` 分支，但沒有代表「所有任務確實通過」的結束狀態。
- `main.py:95-100` 的 `--auto` 不論成功／失敗，都在 worker 的 `finished` 發出後記錄「同步完成」及關閉程序；`finished` 只意味執行緒結束，不能證明檔案同步成功。
- 因此玩家可能誤以為已更新完成並進入不相容伺服器。**這是公開原始碼已被證實的行為風險，不代表目前公開下載的編譯版已確認相同。**

## 修補內容：只限可靠成功判定與啟動器回傳

工作樹：`/home/LOCAL_USER/totemops-friend-review-20261014/modsync-v2-failure-lab`
分支：`totemops/sync-result-proof-20261014`
本地 commit：`b756a5d89eefaa6ea0b2b365053d293cf18cf58d`
完整審閱 Patch：`/home/LOCAL_USER/totemops-friend-review-20261014/barian-modsync-verified-result-20261014.patch`
Patch SHA-256：`2739b69c3643826e65ffdcf74e31041844179f73bde90d90688652b716e28268`

- Worker 預設 `sync_success=False`，只有合法清單、完整下載、MD5 驗證都通過才變為 `True`。中止、清單錯誤、檔案下載失敗、校驗缺失及例外均不能當成功。
- `download_and_verify` 下載失敗回 `False`；要求 HTTP 200 與可用 MD5，若 MD5 不相符重試一次，**重新下載後必須再驗證一次**才可成功。
- 批量 futures 的 `future.result()` 必須真的評估；進度跑滿不是成功證據。
- ZIP 快速下載失敗後如逐檔回退修復了所有檔案，允許成功；資料夾清單無法可靠重驗時維持失敗。
- `--auto` 用 `window.worker.sync_success` 決定 `app.exit(0)`（成功）或 `app.exit(1)`（失敗），不再「有 finished 就宣稱成功」。
- `readme.md` 把原本 `--reconf` 修為實際 `--reconfig`，並說明啟動器的退出碼門檻（還需實機驗證各啟動器是否攔截）。
- 未改其模組同步策略、預設 config 選項、server API 連線目標與完整更新 UI，不新增新同步引擎。

## 可重現測試（完整測試快照再次通過）

原始碼 RED：以 9 項測試對原版執行，9 項中有預期 FAIL/ERROR，包含 `sync_success` 不存在及下載失敗仍回 `True`。檔案 `/tmp/totem-barian-red-20261014.log`。

修補後 GREEN：使用獨立沙箱測試、無正式 Minecraft 網路：
- `python3 -m unittest discover -p 'test_*.py' -q`，**17 tests PASS**。內容包含 HTTP 503、MD5 再下載後仍錯、無更新合法成功、手動停止、損毀 ZIP、ZIP 503 轉逐檔恢復、實際本機 HTTP 下載與 MD5、以及執行真實 `main.py` 的模擬 Qt 視窗 `--auto` 退出碼 `0/1`。
- `QT_QPA_PLATFORM=offscreen /tmp/totem-barian-pyqt6-20261014/bin/python -m unittest qt_real_integration -q`，**3 tests PASS**。此組使用隔離安裝的**真正 PyQt6 QThread/finished 信號**與本機 HTTP 端點，驗證成功下載、manifest HTTP 503、錯誤 MD5；不是 fake Qt。
- **從已提交 Git 的乾淨 `git archive HEAD` 重跑同樣 20 項全部 PASS**。
- `git -C <original-public-clone> apply --check <patch>` 成功。原始乾淨 checkout HEAD 仍為 `b63df158...`，且 `git status --porcelain` 無更動。

## 風險與真正交付標準

**這不是已部署或完整安全修復**。尚未測試：
1. 朋友目前提供玩家下載的編譯 EXE 是否對應公開原始碼此 SHA；如不是，需先對照版本。
2. 真正 Windows PyQt6 可見 GUI／PyInstaller EXE／PCL／Prism 預啟動對 `exit 1` 是否會阻止遊戲啟動，是否會向玩家顯示足夠清楚的失敗提示。
3. 原始程式現有的嚴格同步刪除、ZIP 解壓前路徑驗證、部分下載原子性與失敗回滾，仍應獨立安全審查，**本輪沒修改**。不得拿本次測試結果宣稱相關檔案操作已安全。
4. 朋友未授權將修補推送進其正式倉庫；在取得明確同意前保留本地 Patch，不公開、不代發版。

## 交給使用者或 Barian 的最簡成果

- 一句話：「同步器不應在有檔案失敗或 MD5 錯誤時仍告訴玩家已更新好；我做了一份不動你架構的本地修補和 20 項測試，你可以先審查是否有幫助。」
- 對照：原版可能錯誤宣稱完成；修補版能正確顯示失敗並回傳非零。正常下載、ZIP 失效後逐檔恢復仍可成功。
- 若本人確認真實需求與程式版本，再由本人審核提交 PR，切勿直接對其玩家或正式 API 執行破壞性測試。

其他尚未處理事項仍以此主線為優先；不要因本輪成功而增加新的獨立 AI Agent 產品。
