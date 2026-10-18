/* TotemOps browser-only log triage. No network, uploads, analytics, storage or AI. */
(function (root) {
  "use strict";
  const LIMIT_BYTES = 64 * 1024 * 1024;
  const CHUNK_BYTES = 512 * 1024;
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

  function createAnalyzer() {
    const matches = RULES.map((rule) => ({ rule, count: 0, evidence: [] }));
    let pending = "";
    let pendingCR = false;
    let lineCount = 0;
    let hasText = false;

    function scanLine(line) {
      lineCount++;
      if (!hasText && line.trim()) hasText = true;
      for (const entry of matches) {
        if (!entry.rule.patterns.some((regex) => regex.test(line))) continue;
        entry.count++;
        if (entry.evidence.length < 3) {
          entry.evidence.push({ line: lineCount, text: line.slice(0, 360) });
        }
      }
    }

    return {
      pushChunk(input) {
        if (typeof input !== "string") throw new TypeError("Expected a text chunk");
        let chunk = (pendingCR ? "\r" : "") + input;
        pendingCR = false;
        if (chunk.endsWith("\r")) {
          pendingCR = true;
          chunk = chunk.slice(0, -1);
        }
        const parts = chunk.replace(/\r\n?/g, "\n").split("\n");
        for (let i = 0; i < parts.length - 1; i++) {
          scanLine(pending + parts[i]);
          pending = "";
        }
        pending += parts[parts.length - 1];
      },
      finish() {
        if (pendingCR) {
          scanLine(pending);
          pending = "";
          pendingCR = false;
        }
        scanLine(pending);
        if (!hasText) return { status: "empty", error: "請貼上或選擇一份 Minecraft 錯誤日誌。" };
        const findings = matches.filter((entry) => entry.count).map((entry) => ({
          id: entry.rule.id,
          code: entry.rule.code,
          name: entry.rule.name,
          detail: entry.rule.detail,
          matches: entry.count,
          evidence: entry.evidence,
          certainty: "heuristic",
          priority: entry.rule.priority
        }));
        findings.sort((a, b) => a.priority - b.priority);
        return {
          status: findings.length ? "indicators_found" : "no_known_indicators",
          findings,
          lineCount,
          limited: false,
          message: findings.length
            ? "找到可能的故障線索；不是已驗證的根因，也沒有修改任何伺服器檔案。"
            : "未命中目前已知規則；這不代表日誌正常或伺服器沒有問題。"
        };
      }
    };
  }

  function tooLarge() {
    return { status: "too_large", error: "日誌超過 64 MiB，請改用本機 CLI 分析。" };
  }

  function analyzeLog(input) {
    if (typeof input !== "string") return { status: "invalid", error: "需要文字格式的日誌。" };
    if (new TextEncoder().encode(input).length > LIMIT_BYTES) return tooLarge();
    const analyzer = createAnalyzer();
    analyzer.pushChunk(input);
    return analyzer.finish();
  }

  async function analyzeFile(file, onProgress, chunkBytes = CHUNK_BYTES) {
    if (!file || !Number.isSafeInteger(file.size) || typeof file.slice !== "function") {
      return { status: "invalid", error: "無法讀取選取的日誌檔案。" };
    }
    if (file.size > LIMIT_BYTES) return tooLarge();
    const size = Number.isSafeInteger(chunkBytes) && chunkBytes > 0
      ? Math.min(chunkBytes, CHUNK_BYTES) : CHUNK_BYTES;
    const decoder = new TextDecoder("utf-8");
    const analyzer = createAnalyzer();
    for (let offset = 0; offset < file.size; offset += size) {
      const end = Math.min(offset + size, file.size);
      const bytes = await file.slice(offset, end).arrayBuffer();
      analyzer.pushChunk(decoder.decode(bytes, { stream: true }));
      if (typeof onProgress === "function") onProgress(end, file.size);
    }
    analyzer.pushChunk(decoder.decode());
    return analyzer.finish();
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

  const api = { analyzeLog, analyzeFile, createAnalyzer, LIMIT_BYTES, CHUNK_BYTES, samples };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.TotemDiagnose = api;
  if (typeof document === "undefined") return;

  const el = (id) => document.getElementById(id);
  const input = el("log-input");
  const result = el("result");
  const drop = el("dropzone");
  const file = el("log-file");
  const status = el("status");
  const feedback = el("file-feedback");
  const character = el("totem-face");
  let activeSample = "missing";
  let activeWorker = null;
  let runId = 0;
  function stopAnalysis() {
    runId++;
    if (activeWorker) activeWorker.terminate();
    activeWorker = null;
  }

  function showFeedback(message) {
    if (feedback) feedback.textContent = message;
  }
  function showResultOnSmallScreen() {
    if (root.innerWidth <= 850 && typeof result.scrollIntoView === "function") {
      result.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }
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
    stopAnalysis();
    showFeedback("");
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
  el("analyze-button").addEventListener("click", () => {
    stopAnalysis();
    render(analyzeLog(input.value));
    showResultOnSmallScreen();
  });
  el("clear-button").addEventListener("click", () => {
    stopAnalysis();
    showFeedback("");
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
    stopAnalysis();
    const currentRun = runId;
    const fileName = String(selected.name || "未命名檔案").slice(0, 120);
    if (!/\.(log|txt)$/i.test(fileName) && selected.type !== "text/plain") {
      const error = "目前只支援 .log 或 .txt 文字日誌；模組 ZIP/JAR 請使用 TotemOps CLI 檢查。";
      showFeedback(fileName + "：" + error);
      render({ error });
      showResultOnSmallScreen();
      return;
    }
    if (selected.size > LIMIT_BYTES) {
      showFeedback(fileName + " 超過 64 MiB，未開始分析。");
      render(tooLarge());
      showResultOnSmallScreen();
      return;
    }
    showFeedback("已選擇：" + fileName + "（" + (selected.size / 1048576).toFixed(1) + " MiB），正在本機分析…");
    input.value = "";
    activeSample = "";
    document.querySelectorAll("[data-sample]").forEach((b) => b.setAttribute("aria-pressed", "false"));
    clearChildren(result);
    result.appendChild(node("p", "正在本機分析日誌，檔案不會上傳。", "result-info"));
    status.textContent = "分析中 0%";

    function progress(done, total) {
      if (currentRun !== runId) return;
      status.textContent = "分析中 " + Math.round(done * 100 / Math.max(total, 1)) + "%";
    }
    async function fallback() {
      try {
        const out = await analyzeFile(selected, progress);
        if (currentRun === runId) {
          render(out);
          showFeedback("分析完成：" + fileName + "；檔案沒有上傳。");
          showResultOnSmallScreen();
        }
      } catch (error) {
        if (currentRun === runId) {
          render({ error: "本機分析失敗，請使用較新的瀏覽器或本機 CLI。" });
          showFeedback(fileName + " 分析失敗，請再試一次。");
          showResultOnSmallScreen();
        }
      }
    }
    if (typeof Worker === "undefined") {
      await fallback();
      return;
    }
    try {
      const instance = new Worker("assets/diagnose-worker.js");
      activeWorker = instance;
      instance.onmessage = (event) => {
        if (currentRun !== runId) return;
        const data = event.data || {};
        if (data.type === "progress") progress(data.done, data.total);
        if (data.type === "result" || data.type === "error") {
          activeWorker = null;
          instance.terminate();
          render(data.type === "result" ? data.result : { error: "本機分析失敗，請再試一次。" });
          showFeedback(data.type === "result"
            ? "分析完成：" + fileName + "；檔案沒有上傳。"
            : fileName + " 分析失敗，請再試一次。");
          showResultOnSmallScreen();
        }
      };
      instance.onerror = () => {
        if (currentRun !== runId) return;
        activeWorker = null;
        instance.terminate();
        fallback();
      };
      instance.postMessage({ file: selected });
    } catch (error) {
      if (activeWorker) activeWorker.terminate();
      activeWorker = null;
      await fallback();
    }
  }
  file.addEventListener("change", () => {
    const selected = file.files && file.files[0];
    file.value = "";
    readFile(selected);
  });
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
    event.stopPropagation();
    readFile(selected);
  });
  document.addEventListener("dragover", (event) => {
    if (event.dataTransfer && Array.from(event.dataTransfer.types || []).includes("Files")) {
      event.preventDefault();
    }
  });
  document.addEventListener("drop", (event) => {
    const selected = event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0];
    if (!selected) return;
    event.preventDefault();
    readFile(selected);
    if (drop.scrollIntoView) drop.scrollIntoView({ behavior: "smooth", block: "center" });
  });
  if (document.querySelector("[data-sample]")) setSample(activeSample);
  else {
    clearChildren(result);
    result.appendChild(node("p", "選擇或拖入 latest.log，診斷結果會顯示在這裡。", "result-info"));
  }
})(typeof globalThis === "object" ? globalThis : this);
