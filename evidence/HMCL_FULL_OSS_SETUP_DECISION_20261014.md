# TotemOps — 完全開源 Windows 安裝器選型修正與 MC8 准入條件
日期：2026-10-14 / 台灣時間
階段：只讀官方原始碼／文件已核對；此文件是**架構決策與阻擋項目**，不是已做出可遊玩的 Setup.exe。

## 玩家目標
官網下載一個可信任的 Setup.exe → 雙擊安裝 → 自動建立桌面捷徑 → 以後雙擊捷徑自動校驗和更新、第一次完成 Java/Loader 和本人登入後啟動遊戲（視登入／啟動器支援可自動連線）。

「完全開源」指啟動器改動、安裝腳本、同步器、發布/驗收工具均提供可閱讀的原始碼、對應授權與可重現 build。Minecraft 本體、第三方 mod、官方 Microsoft 登入服務各自有獨立的授權／條款，不可能宣稱整套遊戲內容完全開源。

## 官方來源精確核對（禁止作未測試承諾）

### Helios Launcher + Nebula — 對現有 MC8 直接 BLOCK
- 官方 Helios `dscalzi/HeliosLauncher` 程式碼 inspected commit `86e4316`（2026-05-03），MIT；`electron-builder.yml` 已設 Windows NSIS x64，`oneClick:false`，可建立真正 Setup.exe。
- 官方 Nebula `dscalzi/nebula` inspected commit `7ffc978`（2026-01-02），MIT；`src/index.ts:196-214` 對 Forge 1.20.3+ 明確提示因 Forge 移除 `--fml.modLists`，應用 Fabric 或**等 NeoForge 支援**；來源無 `neoforge` generator。官方 README 僅給 `--forge` 與 `--fabric`。
- MC8 官方完整包實證 Minecraft 1.21.1 / NeoForge 21.1.250；因此**Helios + Nebula 現成組合不能視為支援 MC8**。若硬選此方案即是在替專屬 Launcher 補底層 NeoForge 支援，是高維護成本而非零代碼方案。
- Helios 為品牌專屬 UI 的候選，未來倘服主明確需要再評估，先不 fork、改源碼、部署。

### HMCL + 開源 NSIS — MC8 初版首選，仍需真機試跑
- HMCL 官方 `HMCL-dev/HMCL`，GPL-3.0 + GPLv3 第 7 節附加條款：更名／版本區分、原版著作權標示；官方列出支援 Forge、**NeoForge**、Fabric、模組整合包。
- 官方文檔 https://docs.hmcl.net/modpack/serverpack.html 說明在 HMCL **匯出『伺服器自動更新整合包』**、初始化新的空白客戶端實例、把 `server-manifest.json` / `overrides/*` 託管於可讀取的 HTTP 服務。**不能只把一般 CurseForge modpack.zip 和一個 server-manifest.json 隨意丟在 hmcl.exe 旁就聲稱完成**。
- NSIS 官方 https://nsis.sourceforge.io/Docs/AppendixI.html：主體 zlib/libpng、部分模組其他開源授權；能自行從腳本編譯 Windows 安裝檔、加入桌面捷徑與解除安裝。支援 fully source-auditable 的安裝工具鏈。Inno Setup 亦公開來源且允許修改散布，但使用特殊的 Inno Setup License、原工具建置牽涉 Delphi，因此本專案想要簡單 OSS 構建就先用 NSIS。
- HMCL 官方 NeoForge 支援 ≠ MC8 實例導入、Java 21、帳號驗證、自動更新、直接連進伺服器全部已成功。尤其 serverpack 原教學時間較早；需以目前 HMCL stable + MC8 真實包驗收。

## 不做的事
- 不另造 Minecraft/Java 安裝核心、不克隆 Helios 作 NeoForge 承載、不讓玩家安裝 AI Agent。
- 不把完整 Minecraft 本體或未知可再散布權限的第三方 mod 打包進 Setup.exe；以合法來源與原有下載／校驗機制取得。
- 不假設 Barian 使用官方 Microsoft 登入或 chyuaner 只用 Microsoft；NeoAuth 和第三方驗證必須依服主真實政策與合法玩家自行認證。
- 不覆蓋玩家自己改的 config/mods/world，不接正式伺服器或使用玩家帳號測試。
- 不把『啟動器提供預啟動命令』等同『任何 exit=1 必然阻止 Minecraft』；需實機驗證。

## 隔離驗收計畫（先做能真的幫玩家的步驟）
P0. 保留現有 PCL/Prism 導入 MC8 已成功的流程作 baseline。避免換啟動器導致流程退步。
P1. 真實 Windows 11 隔離目錄導入官方 MC8 ZIP 至 HMCL，驗收 NeoForge 21.1.250 / Java 21、14 個 optional 是否逐次詢問、模組下載成功/失敗後提示。此環節先不登入正式帳號、不連正式伺服器。
P2. 在隔離 HTTP 端點用 HMCL 原生功能匯出＋再次導入 serverpack，建立兩個版本差異，比對 SHA-256、更新回退、世界/配置保留。
P3. 維持 Barian 已有的同步器功能；已修復成功回報的隔離候選 commit `b756a5d`，需實際確認在 HMCL 或 PCL 是否能由同步失敗阻止啟動；若不能，不能假裝 P0 已成功。
P4. HMCL 真能載入 MC8 且更新可靠時，才以 NSIS 產生含「受授權開源 launcher／配置／合法下載入口」的 Setup.exe、建立桌面捷徑與解除安裝；通過乾淨 Win11 端到端試驗才算真正交付。
P5. 若 HMCL 無法滿足登入／更新政策，回到現有 Prism/PCL 或能滿足 NeoForge 的其他開源工具，不為了品牌外觀硬 fork。

## 審核門檻
每一步記錄來源 Git SHA、HMCL 版本、依賴授權、下載網址及 hash、實機畫面／日誌；排除「工具說成功但後置狀態未改變」的假陽性。絕不把『已產生 Setup.exe』當成『玩家已能遊玩』。
