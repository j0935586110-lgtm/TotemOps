# TotemOps: 新手第一次使用（AGY）

## 新增：三指令 / Skill 快速開始（2026-10-15）

圖文使用方式：[TotemOps 開發者快速開始](https://j0935586110-lgtm.github.io/TotemOps/start.html)。保留本頁原有 AGY 原生插件安裝流程。當 AGY 已開啟 Clone 的倉庫，`.agents/skills/totem-ops/SKILL.md` 可導引至根目錄 `SKILL.md`，優先呼叫 `manifest --json --summary`、`crash --json`，有**已授權隔離伺服器**時才使用 `smoke`。2026-10-15 已在全新隔離 HOME 實測 `agy plugin install https://github.com/j0935586110-lgtm/TotemOps`，證實插件包含 `tools/totem_operator.py`、三指令能執行、`agy plugin uninstall totem-ops` 可移除註冊與安裝檔案。一般對話只貼 URL 仍不會自動取得電腦執行權限。


GitHub： https://github.com/j0935586110-lgtm/TotemOps

## 把連結給 AGY

AGY 官方支援由 GitHub 倉庫安裝原生 Plugin。
想要「貼一次連結，往後對話都能使用」，請讓 AGY 將這個
倉庫安裝成 Plugin；單純把網址貼在聊天框，不代表每個
Agent 都會自動執行安裝。安裝會先經由 AGY 本身處理。

最短的確定性指令：

    agy plugin install https://github.com/j0935586110-lgtm/TotemOps

確認：

    agy plugin list --json

應看到 totem-ops，內含 1 個 Skill。安裝完成後開新工作階段，
對 AGY 說「幫我檢查 Minecraft latest.log」即可。

如果使用 AGY 聊天端、不能直接打 CLI 指令，可貼給它一段話：

    這是我要用的 Minecraft 維運 Skill：
    https://github.com/j0935586110-lgtm/TotemOps
    請依官方 AGY 原生 Plugin 方式安裝，驗證成功後先做唯讀診斷。
    不要動正式世界，不要自行使用付費 API 或上傳私人日誌。

AGY 安裝會在自己的外掛區建立獨立副本。Plugin 不會安裝
MCP、事件 hook、帳號、背景 daemon；本專案並非把 AGY 換成
另一個 Agent。診斷 CLI 仍要求 Python 3.11+。

## 可逆

    agy plugin disable totem-ops
    agy plugin enable totem-ops
    agy plugin uninstall totem-ops

這只還原 AGY 外掛的安裝，不可能撤銷其他工作中已修改的
Minecraft 正式伺服器。因此不死圖騰預設不寫正式世界。
沙箱內經授權的改動應另外有備份、Diff、驗收、復原證據。

## 新手說一句需求，Agent 應該怎麼做？

1. 先問／讀取必要的 Minecraft 與 Loader 版本，不猜版本。
2. 先找現成相容模組與修法；Modrinth、mclo.gs、Crash Assistant
   是資訊來源，不需要重做它們（上傳隱私資料需要另外同意）。
3. 將「想要什麼新玩法」轉成小範圍可驗收的變更計畫。
4. 在有權使用的獨立專案或沙箱，以 AGY 既有的程式能力製作最小
   補丁／設定調整。先做回歸測試，再實際確認同版 Minecraft
   伺服器或客戶端有沒有通過；未驗證則不要說已修好。
5. 把修補差異、測試結果、可逆方法交給使用者。
   正式伺服器要寫入時另須擁有者授權。

**REA 不必預先安裝。** 若涉及沒有原始碼、且具有合法研究權限的
JAR／程式，才在隔離環境可選用 REA 與合適的 Java 靜態分析工具，
研究原因並由 AGY 撰寫候選修補。REA 不是 Minecraft 版的
自動補丁魔法，也不能繞過第三方模組的授權與著作權。

## 真實能力限制

目前這個 Plugin **已經有**：原生 AGY 安裝與解除安裝、
既有的唯讀診斷工具、Modrinth 外掛、經明確同意的 mclo.gs 選用外掛、
AGY Skill 的安全測試流程。

尚**未實證**：把純網址送進所有 Agent 聊天框會自動安裝；
任何模組衝突都能自動修復；REA 接上後能自動產出合法且
可在 Minecraft 遊玩成功的補丁；正式世界一鍵回滾。
