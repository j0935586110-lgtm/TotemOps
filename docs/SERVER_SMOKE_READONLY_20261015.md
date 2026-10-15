# TotemOps Server Smoke：真正 Docker 讀回，僅限既有隔離伺服器

日期：2026-10-15（Asia/Taipei）

## 執行範圍與限制

**已實作的不是自動建立新 Minecraft 伺服器，而是唯讀檢查目前已存在、正在執行的** `itzg/minecraft-server` 隔離 Docker。避免重新發明 Docker 啟動器、禁止覆蓋任何玩家世界或公開伺服器。

```sh
python3 tools/totem_operator.py smoke /sandbox/server/mods \
  --side server \
  --container tot-e2e-server-20261015 \
  --sandbox-root /sandbox \
  --minecraft 1.21.1 --neoforge 21.1.259 --json
```

- **僅檢查** `docker inspect`、`docker network inspect`、`docker logs`。絕不執行 `docker run/start/stop/exec`、`rcon-cli`，不授權遠端 Docker socket 給 OpenCode。
- 拒絕非 `tot-e2e-*`、`totem-sandbox-*` 測試容器，拒絕不在 `totemops-*/server/mods` 的路徑、錯誤 Docker volume 掛載、非唯一本機內部 Docker 網路、對外連接埠、unhealthy、非 NeoForge、缺少 `Done`、未列出指定 JAR 或版本不符。
- 使用既有 `mc_package_inspector` 識別 JAR 與 SHA-256；不接受壞 JAR 或重複模組 ID。對原始 console 只做擷取日誌 SHA-256 和已知啟動標記判斷，不輸出玩家 IP、密鑰或整份日志。
- 即使能驗證實際伺服器啟動，狀態仍是 `REVIEW_REQUIRED`、exit code **3**、`server_boot_smoke_verified=true`、`release_allowed=false`、`gameplay_verified=false`。
- `--side client` 尚未實作，明確輸出 BLOCK。這不是客戶端 UI、GameTest、玩家登入、傳送成功或「重新建立一個全新沙箱」的證明。要做到完整發布 Gate，仍需另有真實建置與回滾測試。

## 已實際執行（2026-10-15）

J1 `j-e3`：測試目錄 `/home/j/totemops-playable-e2e-20261015`，容器 `tot-e2e-server-20261015`。

- 既有容器 healthy、唯一 Docker network 為 `tot-e2e-20261015` 且 `Internal=true`、無 port publish；`/data` 指向隔離沙箱的 `server`。
- 日誌確認 `NeoForge mod loading, version 21.1.259, for MC 1.21.1`、`Done`、Waystones/Balm 模組載入及 JAR 名稱。
- 真實 JAR：Waystones 21.1.46 / Balm 21.0.66；SHA-256 各由原檔計算，與先前私有收據一致。
- 測試收據（不含密鑰）存在：`j-e3:/home/j/totemops-playable-e2e-20261015/qa-totem-manifest-20261015/server-smoke-receipt.json`。該次收據 SHA-256 為 `13f9e0426b6dfa99ef5a790d42a13f02c3733b87adad2b07f7bab2e533e1c6f7`（欄位名稱更新前的第一次實測，成功條件不變）。

## 開發者驗收

`python3 -m unittest discover -s tools -p 'test_*.py' -q`

涵蓋正常 boot、對外埠、非內部網路、unhealthy、Loader 版本錯誤、缺少 Done、致命日志、未載入指定 JAR、非測試容器。Mock 驗收不能替代 j-e3 的真實 Docker 執行。

**下一階段：** 將乾淨新沙箱啟動 + 自動備份/還原演練做成另外需要明確授權的流程，並使用既有 itzg Docker 映像，不自己實作啟動器。仍須獨立驗證 NeoForge 同版本客戶端多人連線與 Waystones UI/傳送。
