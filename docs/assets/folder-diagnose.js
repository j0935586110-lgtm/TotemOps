/* TotemOps local folder triage. Files are selected and read only on this device. */
(function (root) {
  "use strict";
  const MiB = 1024 * 1024;
  const LIMITS = Object.freeze({
    files: 20000, logs: 4, logBytes: 64 * MiB, totalLogBytes: 192 * MiB,
    jars: 350, jarBytes: 256 * MiB, nbt: 12, nbtBytes: 8 * MiB,
    zipEntries: 10000, metadataBytes: 64 * 1024, expandedNbtBytes: 8 * MiB,
    durationMs: 180000
  });
  const ignoredSegments = /(?:^|\/)(?:playerdata|advancements|stats|screenshots|resourcepacks|shaderpacks|backups|schematics|schematic|downloads)(?:\/|$)/i;
  const privateNames = /(?:token|password|secret|credentials|session|account|access[_-]?key|private[_-]?key)/i;

  function classifyPath(input) {
    const path = String(input || "").replace(/\\/g, "/").replace(/^\/+/, "");
    if (!path || path.includes("..") || ignoredSegments.test(path) || privateNames.test(path)) return null;
    if (/(?:^|\/)(?:logs|crash-reports)\/[^/]+\.(?:log|txt)$/i.test(path) || /(?:^|\/)latest\.log$/i.test(path)) return "log";
    if (/(?:^|\/)mods\/[^/]+\.jar$/i.test(path)) return "jar";
    if (/(?:^|\/)saves\/[^/]+\/level\.dat(?:_old)?$/i.test(path)) return "nbt";
    return null;
  }
  function logSort(a, b) {
    const score = (p) => /(?:^|\/)crash-reports\//i.test(p) ? 2 : /\/latest\.log$/i.test(p) ? 3 : 1;
    return score(b.path) - score(a.path) ||
      (b.file.lastModified || 0) - (a.file.lastModified || 0);
  }
  function planFolder(fileList) {
    const list = { entries: [], log: [], jar: [], nbt: [], count: 0, bytes: 0,
      skipped: { unselected: 0, size: 0, budget: 0, safety: 0 }, eligible: { log: 0, jar: 0, nbt: 0 } };
    const total = Number(fileList && fileList.length) || 0;
    list.count = total;
    if (!total) return list;
    for (let i = 0; i < total; i++) {
      const file = fileList[i];
      const path = String(file && (file.webkitRelativePath || file.name) || "");
      if (!file || !Number.isSafeInteger(file.size) || file.size < 0) { list.skipped.safety++; continue; }
      list.bytes += file.size;
      if (i >= LIMITS.files) { list.skipped.budget++; continue; }
      const kind = classifyPath(path);
      if (!kind) { list.skipped.unselected++; continue; }
      list.eligible[kind]++;
      const bytesLimit = kind === "log" ? LIMITS.logBytes : kind === "jar" ? LIMITS.jarBytes : LIMITS.nbtBytes;
      if (file.size > bytesLimit || !file.size) { list.skipped.size++; continue; }
      list[kind].push({ file, path, kind });
    }
    list.log.sort(logSort);
    let logBytes = 0;
    list.log = list.log.filter((entry, i) => {
      if (i >= LIMITS.logs || logBytes + entry.file.size > LIMITS.totalLogBytes) {
        list.skipped.budget++; return false;
      }
      logBytes += entry.file.size;
      return true;
    });
    for (const kind of ["jar", "nbt"]) {
      list[kind].sort((a, b) => a.path.localeCompare(b.path));
      const limit = LIMITS[kind === "jar" ? "jars" : "nbt"];
      if (list[kind].length > limit) {
        list.skipped.budget += list[kind].length - limit;
        list[kind].length = limit;
      }
    }
    list.entries = [...list.log, ...list.jar, ...list.nbt];
    return list;
  }
  const api = { LIMITS, classifyPath, planFolder };
  if (typeof module === "object" && module.exports) module.exports = api;
  root.TotemFolder = api;

  if (typeof document === "undefined") return;
  const picker = document.getElementById("folder-file");
  const progress = document.getElementById("folder-progress");
  const output = document.getElementById("folder-result");
  const cancel = document.getElementById("folder-cancel");
  if (!picker || !progress || !output || !cancel) return;

  let worker = null;
  let timer = null;
  let serial = 0;
  function element(tag, content, css) {
    const node = document.createElement(tag);
    if (content !== undefined && content !== null) node.textContent = String(content);
    if (css) node.className = css;
    return node;
  }
  function stop() {
    serial++;
    if (worker) { worker.terminate(); worker = null; }
    if (timer) { clearTimeout(timer); timer = null; }
    cancel.hidden = true;
  }
  function render(data) {
    output.replaceChildren();
    const sum = data.summary || {};
    output.appendChild(element("h3", "資料夾診斷結果"));
    output.appendChild(element("p",
      "共索引 " + (sum.count || 0).toLocaleString() + " 個檔案（" +
      ((sum.bytes || 0) / (1024 * MiB)).toFixed(2) + " GiB）；" +
      "選讀 " + (sum.processed || 0) + " 個，略過 " + (sum.skipped || 0) + " 個。"));
    if (data.warning) output.appendChild(element("p", data.warning, "folder-warning"));
    const findings = Array.isArray(data.findings) ? data.findings : [];
    if (!findings.length) output.appendChild(element("p",
      "沒有命中目前支援的故障規則；不等於所有檔案都沒有問題。"));
    for (const item of findings.slice(0, 32)) {
      const card = element("section", null, "folder-finding");
      card.appendChild(element("strong", item.title || "待確認的線索"));
      card.appendChild(element("p", item.description || ""));
      if (item.path) card.appendChild(element("p", "來源：" + item.path, "folder-evidence"));
      if (item.evidence) card.appendChild(element("p", "證據：" + item.evidence, "folder-evidence"));
      output.appendChild(card);
    }
    if (findings.length > 32) output.appendChild(element("p", "另有 " + (findings.length - 32) + " 項線索未顯示。"));
    const stats = element("p",
      "日誌 " + (sum.logs || 0) + "／模組 JAR " + (sum.jars || 0) +
      "／世界 NBT " + (sum.nbt || 0) + "；僅使用唯讀取樣。", "folder-evidence");
    output.appendChild(stats);
  }
  function showFailure(message) {
    progress.textContent = message;
    output.replaceChildren(element("p", "分析未完成：不會修改檔案或送出資料，請減少選取範圍後重試。"));
  }
  picker.addEventListener("change", () => {
    stop();
    const run = serial;
    const plan = planFolder(picker.files);
    picker.value = "";
    output.replaceChildren();
    if (!plan.count) { progress.textContent = "尚未選取資料夾。"; return; }
    const chosen = plan.entries.length;
    progress.textContent = "已建立 " + plan.count.toLocaleString() + " 個檔案的清單（" +
      (plan.bytes / (1024 * MiB)).toFixed(2) + " GiB），候選 " + chosen + " 個；正在瀏覽器本機分析…";
    if (!chosen) {
      render({ summary: { count: plan.count, bytes: plan.bytes, processed: 0,
        skipped: plan.count, logs: 0, jars: 0, nbt: 0 },
        warning: "沒有找到支援的 logs、crash-reports、mods/*.jar 或 saves/*/level.dat。請選取 .minecraft 根資料夾。" });
      progress.textContent = "清單建立完成，未讀取任何檔案內容。";
      return;
    }
    if (typeof Worker === "undefined") { showFailure("瀏覽器不支援背景執行緒，請使用新版 Edge／Chrome。"); return; }
    try {
      const instance = new Worker("assets/folder-worker.js");
      worker = instance;
      cancel.hidden = false;
      timer = setTimeout(() => {
        if (run !== serial) return;
        stop();
        showFailure("為保護瀏覽器，超過 180 秒已中止分析。");
      }, LIMITS.durationMs);
      instance.onmessage = ({ data }) => {
        if (run !== serial) return;
        if (data.type === "progress") {
          progress.textContent = "分析中 " + data.done + "/" + chosen + "：" + String(data.stage || "").slice(0, 90);
        } else if (data.type === "result") {
          stop();
          progress.textContent = "本機分析完成。所有檔案未上傳，亦未修改。";
          render(data);
        } else if (data.type === "error") {
          stop();
          showFailure("分析失敗：" + String(data.message || "未知錯誤").slice(0, 160));
        }
      };
      instance.onerror = () => {
        if (run !== serial) return;
        stop();
        showFailure("背景解析器無法執行，請重新整理頁面。");
      };
      instance.postMessage({ type: "analyze", entries: plan.entries,
        summary: { count: plan.count, bytes: plan.bytes,
          skipped: Object.values(plan.skipped).reduce((a, b) => a + b, 0),
          eligible: plan.eligible } });
    } catch (_) { stop(); showFailure("無法建立背景工作執行緒。"); }
  });
  cancel.addEventListener("click", () => {
    stop();
    progress.textContent = "使用者已取消；背景分析已停止，沒有檔案上傳。";
  });
})(typeof globalThis === "object" ? globalThis : this);
