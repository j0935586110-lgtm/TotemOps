# 實體 Windows 11 Minecraft 玩家流程驗收（2026-10-14）

## 執行對象

- J1: desktop-jne4fna-bdb6，主機 DESKTOP-JNE4FNA，真實 Windows 11
- CPU Intel Core i5-3340（**不是 i5-9500**）、15.9 GiB RAM、掃描時可用記憶體 6.9 GiB、Intel HD Graphics 舊款內顯、C 槽當時約 164 GiB 剩餘。
- 所有測試下載和 PCL EXE 只放在 `C:\TotemOps-Test-20261014\` 子目錄；未使用現有 .minecraft 目錄，未操作朋友正式伺服器。
- J1 Windows 桌面 session 的 Chrome、Gemini、RustDesk、Colab 等現存作業保持運作；沒有關閉其他程式。

## 真實 Windows 端下載與雜湊（與 Ubuntu 主機先前下載結果一致）

- `downloads\PCL-official.zip`: 2,572,363 bytes，SHA256 `5321f0754137fbdd2c5c1420db868b8e516bcd5d4ed94729d00813f1597c4b46`
- `downloads\Yuan-MC8-v3.5.0-client.zip`: 116,547,360 bytes，SHA256 `7e0a69af9f113aaaa692787b210cfedde42ed9f43e725658cb1366c0e09ad439`
- `downloads\Yuan-MC8-v3.5.0-update.zip`: 1,068,103 bytes，SHA256 `6d6142b792ace4351c4ed0cf00746601a79ef9b04493cddc36772f6358b27abd`
- 原始來源都是 Barian／MC8 官網公開連結。Windows HEAD: MC8 完整包 200、Content-Length 116547360；Barian modapi.barian.moe/clientupdate 回 HTTP 502，與 Ubuntu 觀察吻合。
- PowerShell 直接執行 .ps1 腳本被 Windows ExecutionPolicy 明確拒絕：**沒有變更或繞過該政策**。下載改以本機 curl.exe 直接執行，用 certutil.exe -hashfile SHA256 獨立驗證。

## PCL 實體 Windows GUI 實測

- 官方 PCL ZIP 解壓到 `C:\TotemOps-Test-20261014\launcher\`，內含 `Plain Craft Launcher 2.exe` 5,750,272 bytes（產品版本 `2.13.1.1`）。
- 該 EXE 依 Windows Authenticode 顯示 `NotSigned`；官方網站連結的 SHA256 已驗證，Windows Defender 即時防護啟用，對 launcher 子目錄 custom scan 完成且沒有回報該路徑威脅。掃描結果不能保證檔案絕對安全。
- 真正執行 PCL，PID `16028`；讀回 `PCL_HAS_EXITED=False`、`Responding=True`；J1 CUA windows 和 window state 成功回讀 PCL 視窗。
- PCL 畫面顯示「版本選擇」、「下載遊戲」、「未找到可用的遊戲版本」與「協議授權」、「同意／拒絕」、「查看用户协议与免责声明」。
- **保留 PCL 在協議授權畫面，未代替使用者接受條款，也未登入任何 Minecraft 帳號。**
- 透過指令列尋找 Windows PATH `java`：`NOT_FOUND`。PCL 可能能自行下載／管理 Java，但本輪尚未驗收。

## 完成與未完成的界線

- WIN11_REAL_HOST_CONNECTED PASS
- OFFICIAL_DOWNLOADED_FILES_WIN11_SHA256_MATCH PASS
- PCL_LOCAL_EXTRACT PASS
- PCL_GUI_LAUNCHED_AND_READBACK PASS
- WINDOWS_DEFENDER_CUSTOM_SCAN_FINISHED_NO_REPORTED_THREAT
- MINECRAFT_CLIENT_IMPORT NOT_RUN（PCL 首次使用條款待本人核准）
- NEOFORGE_INSTALL / JAVA_INSTALL NOT_RUN
- MINECRAFT_GAMEPLAY / REAL_SERVER_JOIN NOT_RUN
- Intel HD 舊顯示卡與目前僅約 6.9 GiB 可用 RAM 是否滿足 MC8 的大型模組包，未知；**不能聲稱已可玩**。
- 未修改本來的 J1 Windows VM 或 Ubuntu 專案原始碼。Windows EXE 本身在啟動後可能建立自有設定檔，不能無依據聲稱所有個人系統檔完全沒有變動。
