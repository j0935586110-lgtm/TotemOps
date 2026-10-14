# 不死圖騰真實任務 #2472：先重用，後修補

記錄日期：2026-10-15（Asia/Taipei）。本實驗只操作授權範圍內的本地**隔離開源副本**，沒有向 NeoForge 提交 PR、評論或修改任何正式 Minecraft 世界。

## 第一個決策：先搜尋相同問題的上游 PR

公開問題：[NeoForge #2472 — Key Modifier handling is haunted™](https://github.com/neoforged/NeoForge/issues/2472)，標記 `help wanted`、`1.21.1`。

找到**已存在且仍開啟**的 [PR #3331 — Fix key mappings bound to modifier keys](https://github.com/neoforged/NeoForge/pull/3331)。它不只移除一個條件，而是加入：

- 上游自己的 `KeyMappingModifierHelper` 等共用實作。
- 兩份針對按鍵判定的 JUnit 測試，合計約 1,006 行：
  `KeyMappingModifierHelperTest.java`、`KeyMappingLookupTest.java`。
- 明確區分一般按鍵與修飾鍵，以及 GUI、遊戲內、修飾鍵組合之間的衝突。
- 相關的 [PR #3332](https://github.com/neoforged/NeoForge/pull/3332) 另處理原版按鍵的衝突上下文，並建立在 PR #3331 之上。

**重要的版本限制：** #3331 目前目標是 Minecraft **26.2 / Java 25**，本實驗原始問題使用 **1.21.1 / Java 21**。不能直接把新版 PR 的測試通過當成舊版已修復，更不能不經移植測試就複製檔案。

## 第二個決策：重用官方 CI，而不是寫自己的 Minecraft 建置器

本地原始碼（非發布的測試目錄）：

```text
/home/j/totemops-upstream-lab-20261015/neoforge-1.21.1
Git HEAD: 3cae64530de368936d4c07497d3f0a25e2f9ffec
```

上游 1.21.1 官方建置的關鍵順序來自 [NeoForge CI](https://github.com/neoforged/NeoForge/blob/1.21.1/.github/workflows/build-prs.yml)，先設定生成資源，再建置。正確步驟：

```bash
# 在經授權、獨立的 NeoForge 1.21.1 測試工作樹中
# 使用 JDK 21；不要修改正式伺服器
git fetch --deepen=300 origin refs/heads/1.21.1
git fetch origin refs/tags/21.1:refs/tags/21.1 refs/tags/21.1-stable:refs/tags/21.1-stable

./gradlew :neoforge:setup -PvalidateAccessTransformers --no-daemon --max-workers=2 --no-configuration-cache
./gradlew :tests:junitTest --no-daemon --max-workers=2 --no-configuration-cache
```

如需隔離依賴快取，先設定 `GRADLE_USER_HOME` 指向測試資料夾。測試環境使用 Gradle 9.8.1、官方 ModDevGradle 2.0.115 與 JDK 21。

先前失敗經過：
1. `--offline` 缺少官方 Gradle Plugin 版本。
2. 經由官方套件站正常取得依賴後，shallow clone 缺少計算 NeoForge 版本號的 Git tag。
3. 補齊 tag 讓 Gradle `help` 成功，但直接執行 JUnit 缺少生成的 `net.minecraft.*` 類別。
4. **按官方 CI 先執行 `:neoforge:setup`**，接著 `:tests:junitTest` 成功。

讀取實際 JUnit XML：**77 tests、0 failures、0 errors、0 skipped**；這是 NeoForge **1.21.1 原有的單元測試基準線**，不是 #2472 專項 GameTest，也不是實際 GUI 測試。

## 第三個決策：負面測試與可逆性

首次假設：把 `KeyModifier.NONE.isActive()` 無條件改為 `return true`。

已先將原始 Git diff 保存在本機測試證據資料夾；再於隔離工作樹暫時套回這個補丁，執行相同的官方 JUnit。結果仍是 **77/77**，編譯與既有測試都成功。測試後已立即恢復乾淨工作樹。

這表示：**既有 77 項測試不足以排除這個簡化補丁造成新的修飾鍵組合衝突。** 不能因為編譯及既有測試成功，就判斷補丁安全。

上游 PR 明確設計了這些專項測試，因此決策是 **REUSE_UPSTREAM_PR_TESTS_BEFORE_CUSTOM_PATCH**，不要提交重複、缺乏測試的修補。

## 第四個決策：優先利用上游自己執行的 CI

NeoForge PR #3331 Commit：
`78959a88a8f6a34ba4157e4bb651b4f000f7edb7`

查閱官方 GitHub Actions：

- [Run PR gametests #30637823776](https://github.com/neoforged/NeoForge/actions/runs/30637823776) — JDK 25、Gradle 設定、JUnit、GameTest、production client/server self-test 步驟均顯示成功。
- [Build PRs #30637817444](https://github.com/neoforged/NeoForge/actions/runs/30637817444) — 官方建置、Jar 相容檢查等步驟顯示成功。

**不能過度聲稱：** 這些是上游 26.2 PR 的 CI 結果，不是我們自己執行了 26.2 的遊戲測試，更不是 1.21.1 向下移植驗收。PR 仍開啟、尚未合併，不應宣稱已在正式 NeoForge 發布。

## 對所有 TotemOps Agent 的可重用規則

使用者提出故障或想增加功能時，先按下列順序判斷：

1. **找既有版本：** 官方相容版本、現有 mod/plugin、packwiz 或 modpack 能否滿足要求？
2. **找相同問題：** 先搜尋對應 repo 的 Issues、**包含尚未合併的 PR**、既有測試與修補。比較目標遊戲版本、Loader、JDK，不憑標題推定相容。
3. **重用建置系統：** 按專案自己的 CI / Gradle / GameTest / JUnit 步驟執行，先驗證未改動基準線。不要為了無法建置就先編寫假的 Minecraft API。
4. **小範圍修補：** 只有在官方／社群方案不足且許可相容的情況下，才在隔離的授權工作樹新增最小程式碼、回歸測試與確定的復原步驟。
5. **雙重驗證：** 候選修補需有**故障重現前紅後綠**與官方現有測試；遊戲內功能需要對應版本的客戶端／伺服器實測才可宣稱驗證。
6. **不碰正式環境：** 沒有擁有者同意、可信備份及回滾驗證，不執行正式世界部署。沒有經授權不得替上游留言／提交 PR。

執行狀態如實標記：`BASELINE_UNIT_PASS`、`UPSTREAM_PR_CI_PASS`、`PATCH_REJECTED`、`BACKPORT_NOT_TESTED`。**任何前述狀態都不代表 `GAMEPLAY_VERIFIED`。**

機器可讀試驗記錄：[`evidence/upstream-reuse-2472/case.json`](../evidence/upstream-reuse-2472/case.json)。

**結論：** 這個案例真正應新增到不死圖騰的，不是「自己寫第二套 KeyModifier」，而是「寫碼之前優先搜尋現成 PR、重用測試，避免盲目修壞正常功能」的行為規範。
