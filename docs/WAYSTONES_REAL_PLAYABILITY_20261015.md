# 真實 Minecraft「能玩」驗收：Waystones / NeoForge 1.21.1

這不是聲稱已能玩，而是**把已驗證與未驗證分開的真實執行收據**。2026-10-15（Asia/Taipei）。

## 需求與驗收門檻

**真正要交給使用者玩的修復**應通過：
1. 正確的 Minecraft／Loader／Java／Mod 版本，不缺依賴。
2. 啟動伺服器；實際遊戲世界能執行受影響的功能，重啟後資料不壞。
3. **與伺服器相容的遊戲客戶端成功登入同一台隔離伺服器**，不是僅能讀取 Ping。
4. **玩家實際使用修復功能**，如 Waystones UI 和傳送，結果正確。
5. 修復前重現錯誤、修復後不再重現，且不造成新錯誤；回滾或備份可驗證。

前三項未完成時，**不得宣布 PLAYABLE_VERIFIED**。單人客戶端可以載入世界，只代表客戶端能運行，不代表在相同多人伺服器能傳送。

## 現成工具（無自製引擎）

- 正式 [NeoForge GameTest](https://docs.neoforged.net/docs/1.21.1/misc/gametest/)：遊戲邏輯測試。
- 開源 [MC-Runtime-Test](https://github.com/headlesshq/mc-runtime-test)：透過 HeadlessMC 和 Xvfb 讓實際 NeoForge 客戶端啟動進入單人遊戲世界（範圍僅為 client-world smoke）。
- 開源 [itzg/minecraft-server](https://github.com/itzg/docker-minecraft-server) 官方現成 Java 21 映像：隔離伺服器啟動。
- 現成 RCON CLI：在測試世界中執行 `setblock`、`data get block`、`save-all flush`，不是假模擬。
- Mineflayer：標準客戶端協定驗證；**不支援本例 NeoForge 模組握手**，因此標成預期不相容，不謊稱遊玩成功。

## 已執行的真實沙箱

Agent：`j-e3`；僅限本機獨立目錄：`/home/j/totemops-playable-e2e-20261015`。

Minecraft 1.21.1、NeoForge 21.1.259、Waystones 21.1.46、Balm 21.0.66。所有模組都使用既有來源的 SHA-256 核對。

沙箱使用 Docker `--network tot-e2e-20261015`，該網路設為 `--internal`；`docker port` 無對外映射。容器使用唯讀 root FS、cap_drop ALL、無新增特權和記憶體上限。新世界不含實際玩家紀錄或正式伺服器資料；隔離環境使用不需真實帳號的離線測試使用者，**不能把這個離線設定套用到正式伺服器**。

透過真正伺服器 RCON 取得下列成功輸出：

```text
forceload add 0 0
Marked chunk [0, 0] in Overworld to be force loaded

setblock 0 81 0 waystones:waystone
Changed the block at 0, 81, 0

data get block 0 81 0
0, 81, 0 has the following block data:
{x: 0, y: 81, Items: {Size: 5, Items: []}, z: 0,
 id: "waystones:waystone",
 UUID: [I; 2140306932, -469872644, -1876999041, 1268054851]}

save-all flush
Saved the game
```

**已實際 stop/start 重新啟動伺服器，再次取得完全相同的 Block Entity 資料與 UUID。**

原始本地測試日誌（沒有上傳到公開倉庫）：
`/home/j/totemops-playable-e2e-20261015/evidence/waystones-ingame-block-before-restart.log`
`/home/j/totemops-playable-e2e-20261015/evidence/waystones-block-after-restart.log`
其 SHA-256 均已寫入機器收據。

## 獨立負面驗收：不是所有登入失敗都代表修復失敗

在完全隔離的 Docker 網路嘗試使用 Mineflayer 4.39.0 標準 Minecraft 1.21.1 客戶端登入**已能正常啟動**的 Waystones 伺服器。

伺服器明確回報：

```text
You are trying to connect to a server that is running NeoForge,
but you are not. Please install NeoForge Version: 21.1.259
to connect to this server.
```

因此：`VANILLA_BOT_JOIN=FAIL_EXPECTED_UNSUPPORTED_CLIENT`，不應把「伺服器已修好」推導成「原生無 Mod 客戶端能登入」。

## CI 客戶端驗證：第一次找出我們的驗證工具缺點

為了不用真實 Microsoft 使用者登入，依官方說明使用 MC-Runtime-Test 的 CI 離線測試模式，這個模式不能當成免費玩 Minecraft 的一般客戶端。

測試分支：`test/playable-e2e-20261015`；`on: push` 僅限此分支指定檔案變更，另外支援手動觸發。只給 GitHub Actions `contents: read` 權限。

第一次 CI：下載模組的腳本假設 Modrinth 官方提供 SHA-256 欄位，實際官方只提供 SHA-1 與 SHA-512 → **fail closed**，未啟動客戶端。修正後同時驗證官方 SHA-512 和我們原有的本地 SHA-256，另外新增 4 項回歸測試。

第二次 CI：成功下載兩個校驗通過的 JAR 並安裝 NeoForge，卻被 MC-Runtime-Test 4.5.1 與 HeadlessMC 3 的 CLI 引數不相容擋下（`Couldn't find object for regex '-regex'!`）。未改寫啟動器，而是改用相容的 MC-Runtime-Test 5.0.0（commit `dfc8a2a...`）及其模組 5.0.1。

**關鍵界線：** 以上所有 server-world 資料／CI 成功或失敗，不構成 Waystones UI 及玩家實際傳送成功的證據。

機器可讀紀錄：[Waystones 2026-10-15 收據](../evidence/waystones-playability-20261015.json)。`tools/test_waystones_playability_receipt.py` 明確拒絕以「伺服器啟動與方塊可用」冒稱已完整遊玩。

## 第一性反思

驗證工具必須能辨識「程式錯誤」與「測試工具或測試帳號不相容」，否則修復 Agent 會錯修原本正常的模組。最小驗收做法是**不同來源的獨立證據**：官方元件版本、原始遊戲世界實測、客户端測試、真實使用者行為。不要造新的啟動器或大量診斷引擎。

## 新增：GitHub Actions CI 綠燈，但 GameTest 是零項（已查原始日誌）

2026-10-15 核對 [CI Run 38627418271](https://github.com/j0935586110-lgtm/TotemOps/actions/runs/38627418271) 與下載的 Artifact 11923644786：

- JDK 21 / NeoForge 1.21.1 客戶端在 CI 中成功載入 `New World` 單人世界，Waystones / Balm JAR 來源及 SHA-256 通過。
- `logs/latest.log` 明確寫出 `TestFunctions: []` 和 `No tests found, Successfully finished.`，代表 **0 項 GameTest 被找到**。
- 這個 workflow 的綠燈只證明 **CLIENT_WORLD_SMOKE_PASS**，**不能當成 Waystones 的 GUI/傳送驗證**。
- 仍未在相同模組的 NeoForge 客戶端與獨立隔離伺服器間完成玩家登入／傳送測試。
- 對任何聲稱 GameTest 成功的報告，必須另外檢查發現的測試數量 `> 0` 且包含目標功能；否則標記 `BLOCKED_ZERO_TESTS_DISCOVERED`。

**重要：** 不可把這個 CI 成功誤解為 Waystones 已修好能玩。下一步需真正執行修復功能的 GameTest 或同版本 GUI 操作驗收。
