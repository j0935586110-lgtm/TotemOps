# TotemOps AGY Repo Maintainer — 2026-10-14 朋友專案實測

主線：/home/LOCAL_USER/agy-minecraft-sandbox（現場最新版 TotemOps）
範圍：兩位朋友的**公開 GitHub 原始碼**，沒有對朋友帳號、遠端倉庫、正式 Minecraft 伺服器或玩家世界執行寫入。

## AGY/CLI

- AGY CLI 版本：1.3.4（實際執行 --version）。
- AGY 訂閱模型：gemini-3.8-flash-low，effort=low，mode=plan，sandbox=true，print-timeout=25s；實際退出 0。
- AGY 已正確讀到現場 AGENTS.md + minecraft-repo-maintainer/SKILL.md，回覆了 Barian 專案的唯讀 maintainer inspect 指令以及 STATIC_ONLY 與 BUILD_PASS 的分界。
- **只驗證了技能說明被理解**；並未驗證 AGY 自主編碼、完整 Java 編譯、真正 GUI 或使用者同意工作流。

## Barian0517 / Multiverse-Forge-V2

- 來源：https://github.com/Barian0517/Multiverse-Forge-V2
- pinned HEAD：f2af57eb2eeb6dcd03b02e849cbe22943bcfa65c，default main
- 唯讀指令：python3 tools/totem_operator.py maintainer inspect --profile barian0517 --repo-dir /home/LOCAL_USER/totemops-friend-review-20261014/Multiverse-Forge-V2
- 真正原始碼的 STATIC_ONLY CI finding：3 件
  1. .github/workflows/gradle.yml 第 5 行：push master，而預設分支 main。
  2. .github/workflows/pulls.yml 第 5 行：PR master，而預設分支 main。
  3. .github/workflows/pulls.yml 第 26 行：Gradle :Multiworld-Fabric-1.21.11:build，根 settings.gradle 只宣告 rootProject.name=multiverse，沒有該 include。
- 在**另一份隔離 Git worktree**準備了候選 patch，將兩個 branch 調整為 main，PR build 改為 ./gradlew build。
- 修復前後唯讀規則證據：3 findings → 0 findings。YAML 已能 safe_load、git diff --check 通過、在乾淨 clone git apply --check 通過。
- 本地候選 patch：/home/LOCAL_USER/totemops-friend-review-20261014/barian-multiverse-ci.patch
- patch SHA-256：fbb2d4cb58555672b19154ebd31f24fff90f301040e569ee48b9f3f6445a123f
- **沒有執行 Gradle build**；目前主機沒有 docker 可用且未配置受控沙箱，不能把 STATIC_ONLY 寫成 BUILD_PASS。
- Workflow 的 branch 設定可能刻意限制其他分支，應由 Barian 本人決定是否採納。

## chyuaner / Minecraft-NeoAuthReloaded

- 來源：https://github.com/chyuaner/Minecraft-NeoAuthReloaded
- pinned HEAD：1c7a7d0eec9a9583e2db3638fbbc8e445ce4c6c3，default master
- 真實 clone 的 Repo Profile inspect 為 PASS、pin 符合、目前無 CI 靜態候選（**不代表 CI 沒問題**）。
- 已由 Python AST 解析 scripts/client_smoke_runner.py；從 settings.gradle 驗證 neoauth-core、neoauth-forge、neoauth-neoforge 三個 module。
- 解析 client-smoke-test.sample.json，看到 forge-1.20.1、neoforge-1.21.1 兩個 client 與 disabled 的測試 server。
- 設定範例指定的 launcher paths 在本測試主機均不存在；因此 CLIENT_UI_NOT_RUN。未啟動真實客戶端、未進行登入或資料庫測試，也未執行 Gradle。
- 不另寫一套 CI 或 Client Runner；只用 profile 描述如何**重用作者既有工具**。

## 新增 TotemOps 原始碼

- tools/totem_maintainer.py — profile 綁定 Git origin / SHA、唯讀 CI 風險候選、錯誤分級
- tools/test_totem_maintainer.py — 11 個獨立單元測試（包含惡意 origin、跨 owner 阻擋、未知 module、symbolic link、未執行 workflow 指令）
- profiles/barian0517.json、profiles/chyuaner.json
- .agents/skills/minecraft-repo-maintainer/SKILL.md
- AGENTS.md / Canonical TotemOps Skill 新增按需載入入口
- 現場所有既有追蹤及 untracked 內容保留；未修改正式世界。已知早期 tools/local_tasks.py 允許偽造 approved，**不能用於正式權限閘門**。

## 驗收

- focused 11/11 PASS
- 現場全部 unittest discover tools/test_*.py：196/196 PASS，但 196 包含以前已知漏洞的對抗**紀錄測試**，不能當成該漏洞已修復。
- Github push / PR / releases：NOT_RUN
- Gradle build：NOT_RUN
- Java Minecraft 伺服器與 GUI E2E：NOT_RUN
- 朋友真人試用：NOT_RUN
