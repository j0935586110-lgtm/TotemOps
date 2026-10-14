# TotemOps 可選客戶端啟動方案：離線原型（2026-10-14）

**狀態：PLAN_ONLY；無下載、無部署、無登入、無啟動，不能直接發給玩家當正式安裝器。**

## 重用既有開源實作

- Prism Launcher 官方 CLI 支援 `--launch <instance>` 加 `--server <address>`：https://www.prismlauncher.org/wiki/getting-started/command-line-interface/
- Prism 的 pre-launch 自訂命令可接原有模組同步器／packwiz，但必須獨立驗證非 0 退出碼真的阻止遊戲：https://www.prismlauncher.org/wiki/help-pages/custom-commands/
- AutoModpack 原生支援可選群組、更新、部分版本同步（依 Loader/啟動器支援條件），**前提是服主同意裝在伺服器與玩家端並通過沙箱測試**：https://github.com/Skidamek/AutoModpack/blob/main/docs/quick-start.mdx

不死圖騰只做審核、政策控制與證據，不重造 Minecraft 登入／下載器。

## 使用

```sh
python3 tools/totem_operator.py plugins list
python3 tools/totem_operator.py plugins run launcher-plan inspect --input '{"schema":1,"launcher":"prism","instance_id":"barian-test-1201","server_address":"minecraft.example.org:25565","sync_mode":"existing-modsync"}'
python3 -m unittest discover -s tools -p 'test_launcher_plan.py' -v
```

`launcher-plan` 是可選插件；其讀取 JSON、產生參數陣列與未驗證項目清單，不寫入檔案，也不調用 Prism、Java 或更新端。也可透過以下 switchboard 獨立啟用／停用：

```sh
python3 tools/totem_operator.py modules init --config ./launcher-modules.json
python3 tools/totem_operator.py modules enable --config ./launcher-modules.json launcher-plan
python3 tools/totem_operator.py modules run --config ./launcher-modules.json launcher-plan -- --input '{"schema":1,"launcher":"prism","instance_id":"demo-forge","sync_mode":"none"}'
python3 tools/totem_operator.py modules disable --config ./launcher-modules.json launcher-plan
```

停用不會刪玩家檔案或改其他模組；也可以在不用 switchboard 的情況下，從 `plugins/launcher-plan` 卸載該插件。執行前請確認是信任的本地 Python 程式；**此插件不授予 Minecraft 更新、網路下載或 Windows 操作權限**。測試使用虛構網址及實例名稱。

## 更新如何適應

- 模組／設定等一般更新：保留現有可信 updater，同版仍需每次觸發同步；**release-gate 本身不會下載**。
- 更換 Minecraft／Forge→NeoForge／Java／更新器協定：停止自動流程，重新驗收；**不以既有成功紀錄推定新版成功**。
- AutoModpack 可以減少部分手動版本同步，但不是 Barian 目前已採用或已認可的方案；切換它會改變伺服器和客戶端部署，必須獨立 opt-in。
- 服主既有更新 URL 是 HTTP、TLS 錯誤或來源未釘選：不得直接打包成正式同步器；先取得正式 HTTPS 端點及完整性驗證。

## 下一個需要真實環境的 Gate

1. 服主同意更新方案與玩家檔案政策；提供可驗證 HTTPS 來源與簽章公鑰。
2. 確認 Barian Forge 1.20.1 的實際 instance、Java 版本、伺服器 IP 和 Microsoft 登入流程；**本原型不猜真實伺服器位址**。
3. 在獨立 Windows 客戶端驗證 Prism CLI、pre-launch 的失敗阻擋、一次成功更新、一次故障回滾、完整解除安裝。
4. 只有以上證據都齊備才將原 NSIS QA 安裝包升級為遊戲安裝器，不發布未經許可的朋友模組或資產。
