/* Read-only Minecraft folder triage in a dedicated worker. No fetch/network/storage. */
"use strict";
importScripts("diagnose.js", "folder-diagnose.js", "vendor/zip.min.js", "vendor/prismarine-nbt.min.js");
const LIMITS = self.TotemFolder.LIMITS;
const findings = [];
const MAX_FINDINGS = 100;
function report(title, description, path, evidence) {
  if (findings.length < MAX_FINDINGS) findings.push({ title, description, path, evidence });
}
function progress(done, total, stage) {
  self.postMessage({ type: "progress", done, total, stage });
}
function safeReason(err) {
  const msg = String(err && err.message || "");
  if (/password|encrypted/i.test(msg)) return "加密或受密碼保護";
  if (/invalid|corrupt|unexpected|signature|checksum|CRC|inflate|eof/i.test(msg)) return "結構或校驗異常";
  return "格式不支援或解析失敗";
}
const standardDeps = new Set(["minecraft", "java", "fabricloader", "fabric-api", "forge", "neoforge", "quilt_loader", "quilted_fabric_api", "fabric", "quilt"]);
function metadataFromJson(text) {
  const obj = JSON.parse(text);
  if (!obj || typeof obj !== "object" || typeof obj.id !== "string") return [];
  const depends = obj.depends && typeof obj.depends === "object" ? Object.keys(obj.depends) : [];
  return [{ id: obj.id.toLowerCase(), version: String(obj.version || "?").slice(0, 80),
    depends: depends.filter(d => !standardDeps.has(d.toLowerCase())).map(d => d.toLowerCase()) }];
}
function metadataFromToml(text) {
  const chunks = text.split(/^\s*\[\[mods\]\]\s*$/mi).slice(1, 12);
  return chunks.map(chunk => {
    const id = /^\s*modId\s*=\s*["']([^"' \r\n]{1,100})["']/mi.exec(chunk);
    const ver = /^\s*version\s*=\s*["']([^"'\r\n]{1,100})["']/mi.exec(chunk);
    return id ? { id: id[1].toLowerCase(), version: ver ? ver[1] : "?", depends: [] } : null;
  }).filter(Boolean);
}
async function inspectJar(entry) {
  const reader = new zip.ZipReader(new zip.BlobReader(entry.file), { useWebWorkers: false });
  try {
    const files = await reader.getEntries();
    if (files.length > LIMITS.zipEntries) {
      report("JAR 項目過多，已略過", "為保護瀏覽器，超出封裝檔項目上限。", entry.path);
      return [];
    }
    const allowed = new Map([
      ["fabric.mod.json", metadataFromJson],
      ["meta-inf/mods.toml", metadataFromToml],
      ["meta-inf/neoforge.mods.toml", metadataFromToml]
    ]);
    const mods = [];
    for (const zipped of files) {
      const name = String(zipped.filename || "").toLowerCase();
      const decode = allowed.get(name);
      if (!decode || zipped.directory) continue;
      if (!Number.isSafeInteger(zipped.uncompressedSize) ||
          zipped.uncompressedSize > LIMITS.metadataBytes ||
          zipped.compressedSize > LIMITS.metadataBytes ||
          zipped.uncompressedSize < 0) {
        report("模組描述檔過大，已略過", "僅允許讀取 64 KiB 內的模組描述檔，不解壓整個 JAR。", entry.path);
        continue;
      }
      try {
        const payload = await zipped.getData(new zip.TextWriter(), { useWebWorkers: false, checkSignature: true });
        mods.push(...decode(payload).slice(0, 12));
      } catch (_) {
        report("模組描述檔無法解析", "JAR 內的模組描述檔格式異常或版本不相容。", entry.path, name);
      }
    }
    return mods;
  } finally {
    await reader.close();
  }
}
async function boundedInflate(file) {
  const first = new Uint8Array(await file.slice(0, 2).arrayBuffer());
  const source = file.stream();
  if (first[0] !== 31 || first[1] !== 139) {
    if (file.size > LIMITS.expandedNbtBytes) throw new Error("NBT oversize");
    return new Uint8Array(await file.arrayBuffer());
  }
  if (typeof DecompressionStream === "undefined") throw new Error("gzip unavailable");
  const stream = source.pipeThrough(new DecompressionStream("gzip"));
  const reader = stream.getReader();
  const parts = [];
  let total = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.length;
      if (total > LIMITS.expandedNbtBytes) {
        reader.cancel().catch(() => {});
        throw new Error("NBT inflated too large");
      }
      parts.push(value);
    }
  } finally { try { reader.releaseLock(); } catch (_) {} }
  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const part of parts) { bytes.set(part, offset); offset += part.length; }
  return bytes;
}
async function inspectNbt(entry) {
  const bytes = await boundedInflate(entry.file);
  if (!bytes.length) throw new Error("empty nbt");
  const nbt = self.require("prismarine-nbt");
  const Buffer = self.require("buffer").Buffer;
  const parsed = nbt.parseUncompressed(Buffer.from(bytes));
  if (!parsed || !parsed.value || typeof parsed.value !== "object") throw new Error("invalid nbt root");
  const data = parsed.value.Data && parsed.value.Data.value || parsed.value;
  const version = data.DataVersion && data.DataVersion.value;
  return Number.isInteger(version) ? version : null;
}
async function analyze(entries, inputSummary) {
  const summary = { ...inputSummary, processed: 0, logs: 0, jars: 0, nbt: 0 };
  const installed = new Map();
  const pendingDeps = [];
  let unreadableJars = 0;
  let nbtLogPath = "";
  const unreadableNbt = [];
  let processed = 0;
  for (const entry of entries) {
    progress(processed, entries.length, entry.path);
    try {
      if (entry.kind === "log") {
        summary.logs++;
        const result = await self.TotemDiagnose.analyzeFile(entry.file, (done, total) => {
          if (done === total || done % (8 * 1024 * 1024) === 0) {
            progress(processed, entries.length, "日誌 " + Math.round(done * 100 / Math.max(total, 1)) + "%");
          }
        });
        for (const issue of result.findings || []) {
          if (issue.id === "nbt") nbtLogPath = entry.path;
          const hit = issue.evidence && issue.evidence[0];
          report(issue.name, issue.detail, entry.path, hit ? "日誌第 " + hit.line + " 行（" + issue.code + "）" : issue.code);
        }
      } else if (entry.kind === "jar") {
        summary.jars++;
        let mods = [];
        try { mods = await inspectJar(entry); }
        catch (err) {
          unreadableJars++;
          report("模組 JAR 無法讀取", "ZIP 封裝可能損壞、加密或格式不支援，請核對來源檔案。", entry.path, safeReason(err));
        }
        for (const mod of mods) {
          if (!/^[a-z0-9_.-]{1,100}$/.test(mod.id)) continue;
          if (!installed.has(mod.id)) installed.set(mod.id, []);
          installed.get(mod.id).push({ path: entry.path, version: mod.version });
          for (const dep of mod.depends) pendingDeps.push({ id: mod.id, depends: dep, path: entry.path });
        }
      } else if (entry.kind === "nbt") {
        summary.nbt++;
        try {
          const version = await inspectNbt(entry);
          if (version !== null && version > 0) {
            // Validation only: do not expose world name, seed, inventory, coordinates or NBT tree.
          }
        } catch (err) {
          unreadableNbt.push(entry.path);
          report("世界 NBT 讀取異常", "level.dat 結構無法驗證。請先備份存檔，再確認壓縮、檔案完整性及版本；本站不會修復或寫入。", entry.path, safeReason(err));
        }
      }
    } catch (err) {
      report("檔案分析未完成", "單一檔案解析失敗；其他檔案仍會繼續檢查。", entry.path, safeReason(err));
    }
    processed++;
    summary.processed = processed;
  }
  if (nbtLogPath && unreadableNbt.length) {
    report("交叉線索：日誌 NBT 錯誤與世界檔異常",
      "日誌包含 NBT 讀取錯誤，同時至少一個 level.dat 解析失敗；兩者可能相關，但仍需核對日誌所指世界與檔案，再備份、驗證。",
      unreadableNbt[0], "相關日誌：" + nbtLogPath);
  }
  for (const [id, occurrences] of installed) {
    if (occurrences.length > 1) report("偵測到重複模組 ID：" + id,
      "多個 JAR 宣告相同模組 ID，可能造成啟動衝突。請先確認 Loader 與版本後再處理。",
      occurrences[0].path, occurrences.map(m => m.version).join("、").slice(0, 160));
  }
  // Report missing dependencies only for an exhaustive, readable inventory.
  const eligible = inputSummary.eligible || {};
  if (!unreadableJars && Number(eligible.jar) <= LIMITS.jars &&
      summary.jars === Number(eligible.jar) && installed.size) {
    const reported = new Set();
    for (const dep of pendingDeps) {
      if (standardDeps.has(dep.depends) || installed.has(dep.depends) || reported.has(dep.id + ":" + dep.depends)) continue;
      reported.add(dep.id + ":" + dep.depends);
      report("可能缺少前置模組：" + dep.depends,
        "已讀取的 Fabric 描述檔宣告相依，但模組清單找不到該 ID；請依 Loader、Minecraft 版本和模組官方說明確認。",
        dep.path, dep.id + " → " + dep.depends);
    }
  }
  if (Number(eligible.jar) > LIMITS.jars || unreadableJars) {
    summary.warning = "部分模組檔案未完整檢查，因此未判定任何缺少依賴。";
  }
  return { type: "result", findings, summary,
    warning: (inputSummary.skipped || 0) > 0 ?
      "超出範圍、私密路徑或資源上限的檔案已略過；這是抽樣診斷，不能證明其餘檔案正常。" :
      "這是規則式初步診斷，不等於已證實根因。" };
}
self.onmessage = async ({ data }) => {
  if (!data || data.type !== "analyze") return;
  try {
    const result = await analyze(data.entries || [], data.summary || {});
    self.postMessage(result);
  } catch (_) {
    self.postMessage({ type: "error", message: "背景掃描發生錯誤，請縮小資料夾範圍。" });
  }
};
