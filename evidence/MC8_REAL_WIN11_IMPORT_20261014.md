# 不死圖騰主線：實體 Win11 MC8 首次安裝與整合包匯入實證

日期：2026-10-14，台灣時間。此紀錄只放在 TotemOps 專案，J1 控制器修復仍留在其獨立工作樹。

## 真實 Windows 11 玩家路線
- J1 設備：`desktop-jne4fna-bdb6`，Windows 11 / i5-3340、16GB RAM、Intel HD Graphics；不是 Linux i5-9500 上的虛擬機。未使用正式伺服器、未登入 Minecraft。
- 玩家測試目錄：`C:\TotemOps-Test-20261014\`。PCL 位於 `launcher\Plain Craft Launcher 2.exe`，已通過官網 SHA-256 檢查、曾通過 Defender 該路徑檢查。
- 官網 MC8 ZIP `downloads\Yuan-MC8-v3.5.0-client.zip`，SHA-256 `7e0a69af9f113aaaa692787b210cfedde42ed9f43e725658cb1366c0e09ad439`，116,547,360 bytes；已由 Windows 下載、核對。
- 玩家入服實測步驟：PCL 使用條款（之前使用者已授權接受）→ PCL「下載」→「整合包」→「安裝已有整合包」→ Windows 系統檔案選擇器 → 貼上上述獨立資料夾 ZIP 路徑 → J1 `j1_cua_type verify=true` 確認檔案名稱欄位實際等於指定路徑 → UIA 點擊檔案對話框的「開啟」。
- **獨立畫面證據：** Windows 檔案對話框消失，PCL 顯示「下載可選文件」與「是否要下載整合包中的可選文件 3.2.0-b - 1.21.1 neo/fabric?」之 Yes/No。證明 PCL 識別 ZIP 與 CurseForge manifest，已進入後續安裝提示；**不能說依賴、NeoForge 或遊戲已安裝完成。**
- 對話框「否」的背景視窗定向點擊回報 injected，但獨立截圖顯示彈窗仍然存在，沒有操作後成功證據。**停止重試，不把工具自述當成功。** 下一次需要真人或經驗證的控件交互方式完成可選項選擇，然後才可追蹤下載、安裝。
- PCL 測試期間 `C:\TotemOps-Test-20261014\launcher\.minecraft` 存在，`%APPDATA%\.minecraft\runtime` 也存在。不能假定所有內容只寫入專案資料夾；正式安裝時先確定隔離遊戲路徑。沒有刪改其他 Minecraft 存檔。

## TotemOps 工具改善：讓 Agent 直接懂 CurseForge 整合包
- 不是重建 PCL 或同步引擎；在既有 `tools/mc_package_inspector.py` 加入 `manifest.json` / `minecraftModpack` v1 離線唯讀辨識（不聯網、不解壓、不執行 JAR）。
- 驗證來源：上面的 MC8 正式 ZIP；結果在 `evidence/MC8_CURSEFORGE_PREFLIGHT_20261014.json`：
  - `name=Yuan MC8 Client Prod`，`version=3.5.0`。
  - `minecraft=1.21.1`、`mod_loaders=[neoforge-21.1.250]`。
  - **336 筆 CurseForge 外部檔案參照，其中 required=322，optional=14**。此 ZIP 並非完整離線遊戲；啟動器需要從外部合法下載模組與 Java/Loader。
  - 工具報 `PARTIAL`（`curseforge_external_files_not_resolved`），正確保留下載、相容、實機驗證的未完成狀態；CLI 在 PARTIAL 用 exit code 2 fail-closed。
- 新測試 `tools/test_mc_package_inspector_curseforge.py`：4 組測試（驗證必選/可選計數、阻擋 ../ overrides、阻擋非法參照、阻擋非 CurseForge 格式）。
- RED（修前 3 FAIL、1 ERROR）→ GREEN（新 4 PASS、原 Inspector 21 PASS）。
- 現場混合工作樹全套 `python3 -m unittest discover -s tools -p 'test_*.py' -q`：**212 tests PASS**；其中舊測試仍印 `EXPECTED VULNERABILITY: transition to approved succeeds without real authorization/verification check`，屬未納入本次交付的既有原型問題。需再用已提交乾淨快照做驗收。
- 沒有修改朋友 Github 專案、沒有自動提交 PR、沒有接觸正式玩家帳號或伺服器。

## 產品發現與下一步
1. **不要寫新的模組下載引擎。** MC8 ZIP 已能被 PCL 匯入；主要問題是首次啟動與依賴下載的多步驟，以及更新包 README 要手動覆蓋檔案並刪除三個舊 JAR。
2. **Agent 服務服主，不服務每位玩家。** Agent 可讀 ZIP/manifest、產生版本/依賴稽核及玩家導引；正常玩家仍透過 PCL 現有安裝/自動更新功能完成任務。
3. 當 PCL 選擇可選檔案後，先檢查**遊戲安裝路徑**是否在測試範圍，再追蹤下載 322 必要檔案與 14 可選項狀態；失敗應提供實際下載 URL/錯誤，不假裝已可玩。
4. 最終能進遊戲需要合法 Minecraft 登入，這台機器的舊 Intel HD 也可能不支援重度整合包；**下載/安裝驗收與實際 FPS/入服必須分開。**
5. J1 真實滑鼠前景控制與其他框架差異已獨立記於 `/home/LOCAL_USER/j1-opensource/docs/J1_CUA_PCL_FOREGROUND_INCIDENT_20261014.md` 與隔離分支 `fix/cua-foreground-evidence-20261014`。本輪沒有部署 J1 修補。主線仍是 TotemOps。

## 後續實機更新：2026-10-14 13:26，先前安裝阻礙已排除

完整逐步證據見 `evidence/TOTEM_PCL_OPTIONAL_LIVE_20261014.md`：PCL 在 Windows 取得真正前景控制權後，J1 `foreground`/SendInput 模式搭配逐次 UIA「否」按鈕 BoundingRectangle 動態座標，完成 **14/14 個可選模組提示**。每次點擊均由下一個模組名稱或提示消失獨立驗證。原先「點了仍見彈窗」包含前景焦點拒絕、模態視窗大小改變導致靜態座標失準、及多個不同提示外觀相似的因素。

已在隔離遊戲資料夾讀到 `Yuan MC8 Client Prod` 的 JSON/JAR、358 個 `mods` JAR（包含 ZIP overrides，不能對照 required=322 直接判斷遺漏）及 137 個 libraries 檔案。PCL 啟動頁讀回「啟動遊戲」與 `Yuan MC8 Client Prod`，代表啟動器已識別此版本。**未執行真正遊戲啟動、帳號登入或伺服器連線**。J1 的底層程式碼修補仍留在獨立分支，未部署。
