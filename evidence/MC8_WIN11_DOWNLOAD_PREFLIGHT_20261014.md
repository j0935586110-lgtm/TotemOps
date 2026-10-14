# MC8 / Barian 玩家端下載與 Windows 11 沙箱準備實測（2026-10-14，台灣時間）

**工作主線：** /home/LOCAL_USER/agy-minecraft-sandbox
**實際下載主機：** J1 j-baa0，Intel i5-9500 Ubuntu 24.04
**Windows 測試虛擬機：** libvirt qemu:///system / win11-sandbox
**嚴格範圍：** 已進行公開站點 HTTPS 檔案下載、SHA-256、ZIP CRC 與版本文件檢查；**沒有啟動 Windows 虛擬機，尚未執行安裝、遊戲登入、Minecraft GUI 或玩家進服 E2E**。

## VM 與回滾驗證

- 只讀查得 `win11-sandbox` 關機，2 vCPU / 4 GiB guest RAM；`virsh snapshot-list` 沒有列出快照。
- 原有 VM 磁碟 `/home/LOCAL_USER/vms/win11-teach-test/teaching-overlay-v2.qcow2`，其 backing `/mnt/backup1tb/archive-from-ssd/vms/win11-sandbox2/disk.qcow2`。
- **已新建不影響原磁碟的獨立測試 overlay：** `/home/LOCAL_USER/vms/win11-teach-test/minecraft-site-trial-20261014.qcow2`，`qemu-img check` 回報無錯。
- **已備份原 VM 設定：** `/home/LOCAL_USER/vms/win11-teach-test/win11-domain-before-minecraft-20261014.xml`，SHA-256：`8b1d3bc0b99fe305282262294946b21be8a9a65011358e0153bb0d1d71db8ade`。
- 測試 overlay 目前**尚未掛入虛擬機，VM 尚未啟動**。若要開始 Windows GUI 測試，應先在 VM 關機時把測試 overlay 作為唯一可寫磁碟，再確認 domblklist；測後以原 XML 恢復磁碟路徑。不得對原磁碟做 reset 或 force 操作。
- 資源安全阻礙：宿主 23 GiB RAM，當時 MemAvailable 約 12 GiB，Swap 8 GiB 已用 7.7 GiB；之前 `SAFE_TEST_REPORT_2026-10-10.md` 記錄兩次 VM 開機觸發 swap/PSI watchdog（已停機）。原 VM 配額 4 GiB 不足以分配 MC8 建議的遊戲 Java 6–8 GiB，故在現有負載下**不安全，也無法聲稱能實測完整遊玩**。不要在未進行負載隔離與 watchdog 檢查時啟動 VM。

## 官網客戶端真實下載結果

### Yuan MC8 官網

來源 `https://mc8.yuaner.tw/dl/20261002%20v3.5.0/`，發布日期頁面標為 2026-10-02。
檔案儲存區 `/mnt/backup1tb/minecraft-client-trials-20261014/`。

1. **完整客戶端** `Yuan-MC8-v3.5.0-client.zip`，大小 116,547,360 bytes；SHA-256 `7e0a69af9f113aaaa692787b210cfedde42ed9f43e725658cb1366c0e09ad439`；ZIP CRC PASS，4,583 entries，解壓總約 148.7 MB，沒有絕對或 ../ 路徑。
   - 根目錄 `manifest.json`：CurseForge 格式 minecraftModpack v1、名稱 Yuan MC8 Client Prod、version 3.5.0、**Minecraft 1.21.1、NeoForge 21.1.250**。
   - `manifest.files` 含 **336 筆**（主要為外部依賴參照，需要啟動器另行下載），不能把「111 MB ZIP 已下載完成」說成「整個模組遊戲已可離線啟動」。
   - 有 `overrides/config`、`overrides/kubejs`、`overrides/mods`、`overrides/servers.dat` 等。
2. **更新包** `MC8-v3.5.0-update.zip`，SHA-256 `6d6142b792ace4351c4ed0cf00746601a79ef9b04493cddc36772f6358b27abd`；ZIP CRC PASS，14 entries。
   - update Readme.md **明確要求玩家手動複製檔案，刪除三個舊版本的 JAR**（better_tools_and_armor、zstdnet、MultiMine），並更新 servers.dat。這是有證據的「手動更新摩擦點」。
   - 更新包內 wsmc 等檔案與完整包 overrides 中的同名項目部分雜湊吻合；部分項目在完整包 overrides 中沒有同名路徑，可能由 manifest 管理，不應當作矛盾或錯誤。
3. ZIP 檢查是封裝完整性與格式檢查，並非模組依賴、惡意程式安全或 Minecraft 可玩性證明。

### Barian 幽影櫻官網

網站 `https://mcweb.barian.moe/` 的玩家教學包含 PCL、Forge 1.20.1、modsync 更新器。
- 其 PCL 下載 ZIP 已成功取得：`PCL-official-latest.zip`，SHA-256 `5321f0754137fbdd2c5c1420db868b8e516bcd5d4ed94729d00813f1597c4b46`；ZIP CRC PASS，內有 `Plain Craft Launcher 2.exe`。
- 官網更新器 `http://modapi.barian.moe/clientupdate` 從 **此 Ubuntu 主機** 測得 502 Bad Gateway；`https://modapi.barian.moe/clientupdate` 出現 TLS unrecognized name。**尚未從 Windows guest 瀏覽器確認，也不代表全球玩家皆故障。** 不應改其 DNS、伺服器或公開文案。
- 原 `Barian0517/modsync-v2` 已有 `--auto` 與 `--dir`，不重做同步器；先優先將成功／失敗可靠地回傳給啟動器，再研究正常玩家的雙擊流程。

## 後續驗收界線

已完成：**DOWNLOAD_PASS、ZIP_CRC_PASS、VERSION_IDENTIFIED、INDEPENDENT_ROLLBACK_OVERLAY_PREPARED**。
尚未完成：**VM_BOOT_NOT_RUN、WINDOWS_INSTALL_NOT_RUN、LAUNCHER_IMPORT_NOT_RUN、MINECRAFT_GAME_NOT_RUN、REAL_SERVER_LOGIN_NOT_RUN**。
只有實際在 Windows 11 沙箱啟動、下載 manifest.files 依賴、完成合法遊戲登入和進服，才可說玩家「雙擊能玩」。當主機資源與沙箱 watchdog 不允許時，繼續停在已驗證階段，不能冒充完成。
