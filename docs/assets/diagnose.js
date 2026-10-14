/* TotemOps browser-only log triage. No network, uploads, analytics, storage or AI. */
(function (root) {
  "use strict";
  const LIMIT_BYTES = 2 * 1024 * 1024;
  const LIMIT_LINES = 30000;
  const RULES = [
    {
      id: "dependency",
      name: "可能缺少必要前置模組",
      code: "DEPENDENCY_MISSING",
      detail: "日誌包含缺少必要相依模組的訊息。請以模組官方資訊及當前 Minecraft／Loader 版本確認需要安裝的相依項目。",
      patterns: [/missing (?:mandatory )?dependenc(?:y|ies)/i, /requires (?:mod|the mod|modid)\b/i, /requires .*?(?:to be installed|but it is not installed)/i, /mod .+? is not installed/i, /could not find required mod/i],
      priority: 0
    },
    {
      id: "java",
      name: "Java 執行環境版本可能不符",
      code: "JAVA_VERSION",
      detail: "核對目前 Java 版本與 Minecraft／Loader 官方的要求。class file version 65 對應 Java 21、61 對應 Java 17；不要只靠這一行決定升級。",
      patterns: [/UnsupportedClassVersionError/i, /unsupported (?:major.minor|class file) version/i, /class file version (?:65|61)/i],
      priority: 1
    },
    {
      id: "mixin",
      name: "模組 Mixin 注入失敗",
      code: "MIXIN_FAILURE",
      detail: "這是模組或版本衝突的線索，不足以直接判定是哪一個 JAR。請結合完整 stack trace、模組清單與版本查證。",
      patterns: [/mixin(?: apply)? failed/i, /MixinTransformerError/i, /InvalidMixinException/i, /MixinApplyError/i],
      priority: 2
    },
    {
      id: "memory",
      name: "記憶體不足或資源耗盡",
      code: "MEMORY_PRESSURE",
      detail: "檢查 Java heap、主機實際 RAM、啟動參數和近期模組改動。不要直接把所有記憶體配置給 Java。",
      patterns: [/OutOfMemoryError/i, /Java heap space/i, /GC overhead limit exceeded/i, /unable to create native thread/i],
      priority: 3
    },
    {
      id: "port",
      name: "伺服器連接埠可能被占用",
      code: "PORT_CONFLICT",
      detail: "檢查設定的連接埠及其他 Minecraft 實例。不要直接停止未知程式；先確認佔用者與權限。",
      patterns: [/address already in use/i, /failed to bind to port/i, /BindException/i],
      priority: 4
    },
    {
      id: "duplicate",
      name: "可能存在重複模組",
      code: "DUPLICATE_MOD",
      detail: "先比對同名模組、mod ID 與版本。請備份且不要直接刪除正式伺服器 JAR。",
      patterns: [/duplicate mods?/i, /duplicate mod ids?/i, /duplicate mod found/i, /found duplicates/i],
      priority: 5
    },
    {
      id: "loader",
      name: "Loader 或模組載入設定可能不相容",
      code: "LOADER_MISMATCH",
      detail: "確認 Minecraft、Forge／NeoForge／Fabric 的確切版本，並從官方發布頁核對模組支援資訊。",
      patterns: [/incompatible (?:mod|mod set|mods)/i, /mod .+? requires .*?(?:forge|neoforge|fabric)/i, /mod loading has failed/i, /mod resolution encountered an incompatible mod set/i],
      priority: 6
    }
  ];

  function analyzeLog(input) {
    if (typeof input !== "string") return { status: "invalid", error: "需要文字格式的日誌。" };
    if (new TextEncoder().encode(input).length > LIMIT_BYTES) return { status: "too_large", error: "日誌超過 2 MiB，請先截取錯誤附近的片段再分析。" };
    if (!input.trim()) return { status: "empty", error: "請貼上或選擇一份 Minecraft 錯誤日誌。" };
    const lines = input.replace(/\r\n?/g, "\n").split("\n");
    if (lines.length > LIMIT_LINES) return { status: "too_many_lines", error: "超過 30,000 行，請先截取錯誤附近片段。" };
    const findings = [];
    for (const rule of RULES) {
      const evidence = [];
      let matches = 0;
      for (let i = 0; i < lines.length; i++) {
        if (rule.patterns.some((regex) => regex.test(lines[i]))) {
          matches++;
          if (evidence.length < 3) evidence.push({ line: i + 1, text: lines[i].slice(0, 360) });
        }
      }
      if (matches) findings.push({
        id: rule.id, code: rule.code, name: rule.name, detail: rule.detail,
        matches, evidence, certainty: "heuristic", priority: rule.priority
      });
    }
    findings.sort((a, b) => a.priority - b.priority);
    return {
      status: findings.length ? "indicators_found" : "no_known_indicators",
      findings,
      lineCount: lines.length,
      limited: false,
      message: findings.length
        ? "找到可能的故障線索；不是已驗證的根因，也沒有修改任何伺服器檔案。"
        : "未命中目前已知規則；這不代表日誌正常或伺服器沒有問題。"
    };
  }

  const samples = {
    missing: {
      label: "缺少前置模組",
      log: [
        "[18:42:11] [main/INFO] [minecraft/]: Starting minecraft server version 1.21.1",
        "[18:42:12] [main/INFO] [neoforge/]: Loading mods: waystones",
        "[18:42:13] [main/ERROR] [neoforge/]: Missing mandatory dependencies: Mod waystones requires mod balm to be installed",
        "[18:42:13] [main/ERROR] [minecraft/]: Failed to start the minecraft server"
      ].join("\n")
    },
    mixin: {
      label: "Mixin 注入失敗",
      log: [
        "[11:01:03] [main/INFO]: Launching modded server",
        "[11:01:04] [main/ERROR]: Mixin apply failed example.mixins.json:MixinEntity",
        "org.spongepowered.asm.mixin.transformer.throwables.MixinTransformerError: critical injection failure",
        "[11:01:05] [main/ERROR]: Mod loading has failed"
      ].join("\n")
    },
    memory: {
      label: "記憶體不足",
      log: [
        "[15:20:10] [Server thread/INFO]: Preparing world",
        "[15:20:20] [Server thread/ERROR]: java.lang.OutOfMemoryError: Java heap space",
        "[15:20:20] [Server thread/ERROR]: Exception in server tick loop"
      ].join("\n")
    },
    clean: {
      label: "無規則命中",
      log: [
        "[20:30:00] [Server thread/INFO]: Starting Minecraft server",
        "[20:30:01] [Server thread/INFO]: Done (2.431s)! For help, type help"
      ].join("\n")
    }
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { analyzeLog, LIMIT_BYTES, LIMIT_LINES, samples };
  }
  if (typeof document === "undefined") return;

  const el = (id) => document.getElementById(id);
  const input = el("log-input");
  const result = el("result");
  const drop = el("dropzone");
  const file = el("log-file");
  const status = el("status");
  const character = el("totem-face");
  let activeSample = "missing";

  function clearChildren(target) { while (target.firstChild) target.removeChild(target.firstChild); }
  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (typeof text === "string") element.textContent = text;
    if (className) element.className = className;
    return element;
  }
  function render(out) {
    clearChildren(result);
    if (out.error) {
      result.appendChild(node("p", out.error, "result-error"));
      status.textContent = "未分析";
      character.textContent = "!";
      return;
    }
    status.textContent = out.findings.length ? "發現 " + out.findings.length + " 類線索" : "未找到已知線索";
    character.textContent = out.findings.length ? "?" : "·";
    result.appendChild(node("p", out.message, "result-info"));
    result.appendChild(node("p", out.lineCount.toLocaleString("zh-TW") + " 行已在本機掃描，沒有上傳或儲存。", "result-meta"));
    if (!out.findings.length) return;
    for (const f of out.findings) {
      const card = node("article", null, "finding");
      const header = node("div", null, "finding-head");
      header.appendChild(node("strong", f.name));
      header.appendChild(node("span", f.code, "finding-code"));
      card.appendChild(header);
      card.appendChild(node("p", f.detail, "finding-detail"));
      card.appendChild(node("p", "規則比對命中 " + f.matches + " 行 · 僅供初步診斷", "result-meta"));
      const details = node("details");
      details.appendChild(node("summary", "查看對應日誌行號與內容"));
      const list = node("ol", null, "evidence-list");
      for (const ev of f.evidence) {
        const item = node("li");
        item.appendChild(node("span", "L" + ev.line, "line-number"));
        item.appendChild(node("code", ev.text));
        list.appendChild(item);
      }
      details.appendChild(list);
      card.appendChild(details);
      result.appendChild(card);
    }
  }
  function setSample(key) {
    const sample = samples[key];
    if (!sample) return;
    activeSample = key;
    input.value = sample.log;
    document.querySelectorAll("[data-sample]").forEach((btn) => {
      btn.setAttribute("aria-pressed", String(btn.getAttribute("data-sample") === key));
    });
    render(analyzeLog(input.value));
  }

  document.querySelectorAll("[data-sample]").forEach((btn) => btn.addEventListener("click", () => {
    setSample(btn.getAttribute("data-sample"));
  }));
  el("analyze-button").addEventListener("click", () => render(analyzeLog(input.value)));
  el("clear-button").addEventListener("click", () => {
    activeSample = "";
    input.value = "";
    document.querySelectorAll("[data-sample]").forEach((b) => b.setAttribute("aria-pressed", "false"));
    clearChildren(result);
    result.appendChild(node("p", "請選範例或貼入錯誤日誌，再按「開始分析」。", "result-info"));
    status.textContent = "待分析";
    character.textContent = "·";
    file.value = "";
  });
  async function readFile(selected) {
    if (!selected) return;
    if (selected.size > LIMIT_BYTES) {
      render({ error: "檔案超過 2 MiB，請先截取錯誤附近片段。" });
      return;
    }
    try {
      const text = await selected.text();
      input.value = text;
      activeSample = "";
      document.querySelectorAll("[data-sample]").forEach((b) => b.setAttribute("aria-pressed", "false"));
      render(analyzeLog(text));
    } catch (error) {
      render({ error: "無法在瀏覽器讀取檔案，請改用貼上文字。" });
    }
  }
  file.addEventListener("change", () => readFile(file.files && file.files[0]));
  ["dragenter", "dragover"].forEach((eventName) => drop.addEventListener(eventName, (event) => {
    event.preventDefault();
    drop.classList.add("hovering");
  }));
  ["dragleave", "drop"].forEach((eventName) => drop.addEventListener(eventName, (event) => {
    event.preventDefault();
    drop.classList.remove("hovering");
  }));
  drop.addEventListener("drop", (event) => {
    const selected = event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0];
    readFile(selected);
  });
  setSample(activeSample);
})(typeof globalThis === "object" ? globalThis : this);
