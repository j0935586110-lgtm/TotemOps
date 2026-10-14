# Minecraft 客戶端更新：可適應新功能的發布契約（實驗 v0.1）
日期 2026-10-14。這是**發布審核／離線相容性檢查**，不是已上線的自動更新器、Setup.exe 或 Minecraft 客戶端。

## 原則
- 玩家第一次安裝一次有可驗證來源的啟動器（HMCL/Prism/PCL）＋朋友既有同步器；下次雙擊，**仍由現有同步器下載模組**，不另造下載程式。
- 服主修改任務、規則、模組、配置，只要 **Minecraft/Loader/Java/Updater 接口不變**，既有同步器本來就可以每次啟動檢查並處理；即使發布序號未增加，也必須輪詢既有更新端。**本實驗未實際發送 HTTP 請求**。
- Minecraft、Forge/NeoForge/Fabric、Java 或更新器接口改變 => `MIGRATION_TEST_REQUIRED`／`INSTALLER_RECONFIG_REQUIRED`。不能假設老版安裝器自然適應所有功能變更。
- 拒絕降版、重複序號不同內容、跨伺服器 profile、簽章竄改或指向未知網域／HTTP 的發布資料。
- 正式安裝器必須內建／釘選服主的 Ed25519 公鑰；服主應在可信的獨立環境簽署每次發布的 JSON，私鑰**不得**放到安裝器、網站或本 repo。

## 實作內容
`tools/totem_release_gate.py`：Python 只讀程式，要求 `cryptography`（系統現有 41.0.7），公開授權 Apache-2.0。

```shell
python3 tools/totem_operator.py release gate \
  --incoming path/new.json --signature path/new.sig \
  --installed path/last.json --installed-signature path/last.sig \
  --public-key path/maintainer-public.pem \
  --profile game-profile-id --allowed-host updates.example.org
```

首次安裝可省略 installed/installed-signature，返回 `MANUAL_FIRST_INSTALL`。
回傳 `READY/RUN_EXISTING_UPDATER` 才允許上層考慮**呼叫現成同步器**；此工具本身不下載、刪除或啟動任何東西，也不提供自動 HTTP 輪詢。退出碼：0=READY、3=需人工審核或回退、2=驗證失敗，不要當成已成功安裝。
資料格式：`schema=1`、`profile`、`sequence`、`minecraft`、`loader`、`loader_version`、`java_major`、`updater_contract`、`sync_feed`。
簽章：Ed25519，`signature` 檔內為 raw JSON bytes 的簽章（Base64），**只驗原始內容的簽名，不在驗證前重新序列化 JSON**。
只允許 HTTPS + 明確 allow-host；連線或下載不在此工具內執行，簽章亦不等於 download URL 自動安全。

## Barian 真實阻擋項目
- 目前官網 `mcweb.barian.moe` 的『下載模組更新器』指向 `http://modapi.barian.moe/clientupdate`；Ubuntu 實測 HTTP 502，而 HTTPS 端點 TLS SNI 不正確。`modsync-v2/main.py` 的預設 server URL 也是 `http://modapi.barian.moe/`。
- 這不代表對全部玩家都故障，但**現在不應以這個 HTTP 入口宣稱提供安全、可靠的公開自動安裝**。必須先與 Barian 確認現有玩家實際下載來源、可行的 HTTPS／CDN 路徑，和新版編譯 EXE。
- 現有 `modsync-v2` 使用 MD5 比對而不是具簽章的模組發布清單；即使本 Gate 檢查器簽章通過，也無法防止舊同步器透過 HTTP 被置換 JAR。**正式封裝前必須整合下載來源 HTTPS、可信模組 hash/權限及原子更新。**
- 我們已修復「錯誤報成功」的獨立候選補丁 `b756a5d`，20 tests PASS，但仍未實機驗證 PCL/HMCL 遇到 exit=1 的真正啟動阻擋行為，也未徵求 Barian 同意部署。
- 因為沒有新的正式 HTTPS 發布端和已核准安裝資產，此輪**不能**產生宣稱可用的一鍵安裝 EXE。

## 測試與真實需求證據
- 測試要包含：一般同平台模組更新、同版重進、Forge→NeoForge、Java 升級、API 變動、降版/回放、重複版本不同內容、簽章竄改、不同伺服器/網域、HTTP feed、原世界檔不改動。
- 社群不缺開源 Launcher：Prism/Packwiz/AutoModpack/PortalLauncher 都針對更新；需求屬於「第一次安裝複雜、每週新版重裝、更新設定遺失」等持續困擾。不能以幾篇貼文推估總市場大小或付費意願。
- 產品價值應是**服主不用換用戶端也能提交相容性證據、製作安裝包、知道更新是否成功**；若已經有同等現成解法就不再造輪子。

## 下一階段最小驗收
1. 取得本人核准的伺服器端 HTTPS 更新清單與 installer/launcher 來源；不能把 HTTP 502 忽略掉。
2. 用 Barian Forge 1.20.1 隔離實例驗證「正常自動更新、更新錯誤阻止進服」及桌面捷徑；驗證後才可宣稱『雙擊遊玩』。
3. 讓真正的發版程序產生簽章，再將本 Gate 連入 Launcher 的 pre-launch hook；**本輪僅只讀離線 prototype**。
