# TotemOps 可選模組（DSH 式啟用/停用，v0.1）

**原則：不用的模組不執行。** 所有可選模組預設停用；對特定測試／玩家流程，只開需要的能力。這不是新的 Agent、不是「關閉安全防護」開關，核心驗證和授權底線始終存在。每個模組只是通向現有已測試確定性工具的安全入口，且不允許任意 shell / J1 遠端桌面命令。

## 最短操作方式

在 TotemOps 專案根目錄：

```bash
# 第一次選擇時建立設定（所有模組預設 OFF）
python3 tools/totem_operator.py modules init --config /tmp/totem-modules.json

# 看目前有哪些模組、哪些已啟用
python3 tools/totem_operator.py modules status --config /tmp/totem-modules.json

# 只啟用整合包檢查，其他保持關閉
python3 tools/totem_operator.py modules enable --config /tmp/totem-modules.json pack-review

# 使用該模組：輸入你有授權的 ZIP
python3 tools/totem_operator.py modules run --config /tmp/totem-modules.json pack-review -- --pack /path/to/client.zip --update /path/to/update.zip

# 用完關閉：不會移除報告或其他設定
python3 tools/totem_operator.py modules disable --config /tmp/totem-modules.json pack-review
```

注意：配置檔是本地 JSON，適用使用者自己指定的工作目錄，`init` 不覆蓋現有配置。未提供配置或該模組未明確啟用時，`modules run` 直接 BLOCK，不會執行。

## 可選功能

| ID | 作用 | 預設 | 依賴 |
|---|---|---|---|
| pack-review | 讀取整合包／更新包並產生差異 | OFF | Python |
| release-gate | 驗證服主簽署發布資訊，禁止不相容更新 | OFF | Python + cryptography |
| onboarding | 比對同步器程式與新手教學 | OFF | Python |
| log-diagnose | 唯讀分析 Minecraft 日誌 | OFF | Python |
| repo-review | 唯讀專案配置與測試建議 | OFF | Python |

已存在的 `plugins list/run` 插件機制維持向後相容，但**它不是此模組開關的強制安全政策**；不會因為 `modules status` 顯示 OFF 就禁止直接呼叫現有 legacy CLI 或使用者主動執行的 Plugin。正式多租戶／多人遠端授權應由 J1 和獨立權限政策強制。這一版不宣稱停用模組可停用任意外部程式碼。

## 可擴充的技術原則

- 一個模組 = 獨立 Python 功能／測試／明確命令映射／可選依賴。核心只負責列表、啟用、停用與授權路由，不由不可信 JSON 動態執行腳本。
- 新能力先做獨立測試，再經程式碼審核加入 `tools/totem_modules.py` 的固定 Registry。未知模組、未知 JSON key、重複 key、篡改 JSON、symlink 配置都 fail-closed。
- J1 及其它電腦控制未開放給這個模組開關；需要真實授權與稽核，不應透過 `--enable all` 取得。
- 模組切換只影響明確透過 `modules run` 執行的流程；這是初版**CLI 選擇**，尚未有圖形化設定畫面或跨機配置分發。

## 驗收

- `tools/test_totem_modules.py`（14 項）：獨立啟閉、重開設定、不覆蓋配置、拒絕未知模組、拒絕符號連結、拒絕壞 JSON、停用不執行、不移除其他資料。
- 整合包實測：透過 `modules run pack-review` 讀 MC8 官方 v3.5.0 的 ZIP + update；停用後相同命令必須被拒絕。
- Windows 安裝測試是 **NSIS 獨立 QA**，不表示真正 Minecraft 已能玩，見 `evidence/WINDOWS_NSIS_SMOKE_20261014.md`。
