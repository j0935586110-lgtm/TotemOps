# TotemOps — Minecraft 啟動器／更新方案選型紀錄（2026-10-14）

狀態：**DECISION / READ-ONLY**。主線不改：修復既有玩家更新的真問題、降低首次入服障礙。沒有開發新的 Windows Launcher、沒有部署、沒有修改朋友專案。

## 核心結論：需要「可靠更新」，不等於需要「自己做啟動器」

- 原版／Paper／Purpur 純插件玩法：通常不需要伺服器專屬啟動器；原生遊戲登入 IP 即可。但若依賴額外客戶端模組、資源包或特定版本，仍要檢查實際前置條件。
- Forge／NeoForge／Fabric 模組服：玩家需要合適的 Minecraft / Java / ModLoader／客戶端模組及伺服器相容版本；可以由現成 Prism、HMCL、PCL 等**完成**，自製 EXE 並非必要條件。
- 本專案已在 Windows PCL 實機成功匯入 MC8 3.5.0、逐一處理 14 個 optional prompts、下載模組，PCL 已辨識版本。**尚未真正遊戲啟動及連線**，不能把流程通過寫成「已能玩」。
- Barian modsync-v2 與 chyuaner python-minecraft-mods-sync 已提供差異更新／啟動前介接：保留和改善它們，避免另做重複下載器。

## 已核對官方專案與修正的說法

| 方案 | 官方／授權 | 能做什麼 | 現階段判斷 |
|---|---|---|---|
| Prism Launcher | GPL-3.0-only / https://github.com/PrismLauncher/PrismLauncher | 管理獨立遊戲實例、下載整合包、執行 Pre-launch commands | 首選已存在的玩家端；不 Fork、不重品牌；如使用預啟動必須在實機測 **非零退出碼是否阻止遊戲**，官方文件僅證明命令會在遊戲前執行 |
| packwiz + packwiz-installer | 官方安裝教學 https://packwiz.infra.link/tutorials/installing/packwiz-installer/ | pack.toml 靜態託管 + bootstrap JAR + Prism/MultiMC Custom pre-launch；Git 可版控。**不是 Prism 原生無設定的一鍵同步**，需要初始化並發布託管內容；packwiz 可選模組 GUI 仍有機會要求玩家選擇 | 可做不碰正式服的 **獨立乾淨實例 A/B**，只在已存在更新器不敷使用時採用 |
| HMCL | GPLv3、附 GPLv3 第 7 節附加條款 / https://github.com/HMCL-dev/HMCL | 官方文件支援伺服器自動更新整合包；服主須有 HTTP 託管與發布設定 https://docs.hmcl.net/modpack/serverpack.html | 二線候選；可以比較同一份整合包的玩家操作數與版本更新，非立即替換 |
| PCL2 | 公開大部分原始碼，但官方源碼庫可能缺部分程式碼、非全量可建置，見 https://github.com/HayashiJules/PCL2 | MC8 玩家安裝已實測；與朋友教學一致 | 現有玩家端仍支援，但不作新 Launcher Fork 底座；不要把「公開部分程式碼」說成「完全閉源」 |
| HeliosLauncher | MIT / https://github.com/dscalzi/HeliosLauncher | Electron/Node、自動校驗／下載資源、Java 檢查、伺服器專屬品牌 | 只有服主明確需要品牌、且新手安裝問題有量化證據才評估。**NeoForge 1.21.1 與 Microsoft OAuth/再打包需端對端驗證**，不可先認定支援 |
| XMCL | MIT / https://github.com/Voxelum/x-minecraft-launcher | Electron + TypeScript/Vue，提供 @xmcl/installer、mod-parser 等開源模組 | 若未來真的要定製 UI 或 API，可借鏡其套件；目前不引入依賴／不重造啟動器 |

### 矯正三個常見偽需求

1. 「模組服一定要自製 Windows 啟動器」**錯**；需要可靠的客戶端版本與更新機制，Prism/HMCL/PCL + 既有同步器即可解決大部分問題。
2. 「Prism + Packwiz 裝好就每次自動更新」**不完整**：必須把 bootstrap JAR 放進對應實例，配置預啟動命令和 HTTP 的 pack.toml；此外 14 個 optional 若轉成 Packwiz 仍可能詢問，不保證天然消失。
3. 「預啟動同步工具 exit 1 就一定阻止 Minecraft」**尚未證明**。Barian 補丁已能回 0/1，但 Prism/PCL/Fjord 真正失敗後是否阻止遊戲，必須在隔離遊戲實例實測。即使正常啟動器忽略 exit 1，不能向服主宣稱阻止玩家進服已完成。

## 推薦產品策略（無多餘元件）
1. **立即**：繼續驗收 Barian 已存在的同步器修補：本地提交 b756a5d、20 tests green、審閱檔 evidence/BARIAN_SYNC_FAILURE_FIX_20261014.md；不推他 GitHub、不複製無 LICENSE 程式碼進 Apache TotemOps。
2. **本週可做的小型真實對照**：在 Windows 回滾測試環境用「官方公開實例/模組」，對照 現有啟動器+同步器 與 Prism/HMCL/Packwiz 的首次安裝操作數、完整更新、失敗恢復、非零返回碼和最後是否真正能啟動。不登正式玩家帳號、不用真實伺服器資料。
3. **只有發現可靠、可重現、會影響玩家的缺口**，才用現有 AGY/OpenCode Skill 協助生成最小 Patch 或新手文件，交服主審核；不能只因為某個方案 MIT 授權漂亮就加入依賴。
4. 新手驗收：網站 → 一份清楚的 launcher/zip → 最少互動 → 合法帳號登入 → 正確版本更新 → 成功啟動；同步失敗需明確阻擋或告警。註：帳號登入仍需要玩家自己執行。
5. 品牌 Launcher **延後**：需服主明確要「專屬 Logo/一鍵進服」，並證明現有流程痛點顯著，且有維護 Microsoft 登入、程式簽章、SmartScreen、Java 和 NeoForge 多版本、分發與更新成本的資源，才選 Helios 或 XMCL 作 PoC。

## 衡量（不要只靠主觀好看）
- 新玩家：點擊次數／完整安裝的時間／下載失敗的可恢復性／需要人工客服的步驟。
- 老玩家：差異更新成功率／雜湊一致性／同步失敗是否仍進遊戲／失敗後是否可以不破壞既有世界地重試。
- 服主：每次發版要維護的 Manifest／教學／同步器數量、能否沿用現有 website/CDN/CI、是否引入額外需要長期維護的 Launcher fork。
- 所有結論記錄來源 Git SHA/完整配置與實機證據；沒有驗證就寫 NOT_TESTED，不能寫 PASS。

## 這輪的執行界線
只核對官方授權／功能與整理工程決策。未下載或啟動第三方新 Launcher、未實測其 Windows 相容性、未以任何方式改動現有 Minecraft 玩家檔案或使用者安全政策，未推 Github。
