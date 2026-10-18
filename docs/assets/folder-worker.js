/* Read-only Minecraft folder triage in a dedicated worker. No fetch/network/storage. */
"use strict";
importScripts("diagnose.js", "folder-diagnose.js", "folder-rules.js",
  "vendor/zip.min.js", "vendor/prismarine-nbt.min.js", "vendor/toml.min.js", "vendor/json5.min.js");
const LIMITS = self.TotemFolder.LIMITS;
const RULES = self.TotemFolderRules;
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
  if (/invalid|corrupt|unexpected|signature|checksum|CRC|inflate|eof|truncat|incorrect|failed/i.test(msg)) return "結構或校驗異常";
  if (/too large|oversize|limit/i.test(msg)) return "超過安全解析上限";
  return "格式不支援或解析失敗";
}
async function safeZipEntryBudget(file) {
  // The ZIP end record lives in the final 22 + at most 65,535 comment bytes.
  // Inspect it before ZIP.js allocates an entry list for an untrusted archive.
  const size = file.size;
  const tail = new Uint8Array(await file.slice(Math.max(0, size - 65557)).arrayBuffer());
  const view = new DataView(tail.buffer, tail.byteOffset, tail.byteLength);
  for (let i = tail.length - 22; i >= 0; i--) {
    if (view.getUint32(i, true) !== 0x06054b50) continue;
    const commentSize = view.getUint16(i + 20, true);
    if (i + 22 + commentSize !== tail.length) continue;
    const count = view.getUint16(i + 10, true);
    return count !== 0xffff && count <= LIMITS.zipEntries;
  }
  return false; // Missing end record and ZIP64 need specialist inspection.
}
async function readBoundedManifest(zipped) {
  const parts = [];
  let count = 0;
  const sink = new WritableStream({
    write(bytes) {
      count += bytes.length;
      if (count > LIMITS.metadataBytes) throw new Error("metadata expanded limit");
      parts.push(bytes);
    }
  });
  await zipped.getData(sink, { useWebWorkers: false, checkSignature: true });
  const merged = new Uint8Array(count);
  let at = 0;
  for (const part of parts) { merged.set(part, at); at += part.length; }
  return new TextDecoder("utf-8", { fatal: true }).decode(merged);
}
async function inspectJar(entry) {
  if (!await safeZipEntryBudget(entry.file)) {
    report("JAR 結構過大或不支援", "ZIP 目錄項目超額、ZIP64 或結尾記錄異常，已安全略過。", entry.path);
    return { modules: [], complete: false };
  }
  const reader = new zip.ZipReader(new zip.BlobReader(entry.file), { useWebWorkers: false });
  let manifestCount = 0;
  let unreadableMetadata = false;
  try {
    const files = await reader.getEntries();
    if (files.length > LIMITS.zipEntries) {
      report("JAR 項目過多，已略過", "為保護瀏覽器，超出封裝檔項目上限。", entry.path);
      return { modules: [], complete: false };
    }
    const allowed = new Map([
      ["fabric.mod.json", text => RULES.fabricMetadata(text)],
      ["meta-inf/mods.toml", text => RULES.tomlMetadata(text, "forge", TotemToml.parse)],
      ["meta-inf/neoforge.mods.toml", text => RULES.tomlMetadata(text, "neoforge", TotemToml.parse)]
    ]);
    const modules = [];
    for (const zipped of files) {
      const name = String(zipped.filename || "").toLowerCase();
      const decode = allowed.get(name);
      if (!decode || zipped.directory) continue;
      manifestCount++;
      if (!Number.isSafeInteger(zipped.uncompressedSize) ||
          !Number.isSafeInteger(zipped.compressedSize) ||
          zipped.uncompressedSize > LIMITS.metadataBytes ||
          zipped.compressedSize > LIMITS.metadataBytes ||
          zipped.uncompressedSize < 0) {
        unreadableMetadata = true;
        report("模組描述檔過大，已略過", "只解壓每份 64 KiB 以內的模組描述檔，不讀取整個 JAR。", entry.path);
        continue;
      }
      try {
        const payload = await readBoundedManifest(zipped);
        modules.push(...decode(payload).slice(0, 20).map(m => ({ ...m, path: entry.path })));
      } catch (_) {
        unreadableMetadata = true;
        report("模組描述檔無法解析", "JAR 中的 Fabric JSON 或 Forge／NeoForge TOML 格式異常。", entry.path, name);
      }
    }
    // A library JAR without metadata must not make the mod inventory look exhaustive.
    return { modules, complete: !!manifestCount && !unreadableMetadata && !!modules.length };
  } finally {
    await reader.close();
  }
}
async function boundedInflate(file, compression, limit) {
  if (compression === "none") {
    if (file.size > limit) throw new Error("expanded limit");
    return new Uint8Array(await file.arrayBuffer());
  }
  if (typeof DecompressionStream === "undefined") throw new Error("DecompressionStream unavailable");
  const stream = file.stream().pipeThrough(new DecompressionStream(compression));
  const reader = stream.getReader();
  const chunks = [];
  let size = 0;
  try {
    while (true) {
      const next = await reader.read();
      if (next.done) break;
      size += next.value.length;
      if (size > limit) {
        await reader.cancel().catch(() => {});
        throw new Error("expanded limit");
      }
      chunks.push(next.value);
    }
  } finally { try { reader.releaseLock(); } catch (_) {} }
  const bytes = new Uint8Array(size);
  let position = 0;
  for (const chunk of chunks) { bytes.set(chunk, position); position += chunk.length; }
  return bytes;
}
function parseNbt(bytes) {
  if (!bytes.length) throw new Error("empty NBT");
  const nbt = self.require("prismarine-nbt");
  const Buffer = self.require("buffer").Buffer;
  const parsed = nbt.parseUncompressed(Buffer.from(bytes));
  if (!parsed || !parsed.value || typeof parsed.value !== "object") throw new Error("invalid NBT root");
  return parsed.value;
}
async function inspectNbt(entry) {
  const header = new Uint8Array(await entry.file.slice(0, 2).arrayBuffer());
  const format = header[0] === 31 && header[1] === 139 ? "gzip" : "none";
  const parsed = parseNbt(await boundedInflate(entry.file, format, LIMITS.expandedNbtBytes));
  // Deliberately never serialize world name, seed, player inventory, location or any NBT value.
  return !!parsed;
}
async function inspectConfig(entry) {
  const text = await entry.file.text();
  const ext = entry.path.toLowerCase();
  if (ext.endsWith(".toml")) TotemToml.parse(text);
  else if (ext.endsWith(".json5")) JSON5.parse(text);
  else JSON.parse(text);
  // Deliberately never retain, report or send any config values.
}
async function inspectRegion(entry) {
  const bytes = new Uint8Array(await entry.file.slice(0, 8192).arrayBuffer());
  const header = RULES.inspectRegionHeader(bytes, entry.file.size);
  let invalid = 0;
  for (const issue of header.issues.slice(0, 5)) {
    invalid++;
    report("區域檔索引異常", issue.description + "（僅唯讀檢查，請先備份世界）。",
      entry.path, issue.slot >= 0 ? "索引槽 " + issue.slot : "檔頭");
  }
  if (header.issues.length > 5) report("區域檔其他索引異常",
    "尚有 " + (header.issues.length - 5) + " 個索引異常未逐一顯示。", entry.path);
  let samples = 0;
  let deferred = header.populated - header.chunks.length; // structurally invalid or unreadable
  for (const chunk of RULES.chooseRegionSamples(header.chunks, LIMITS.regionSamples)) {
    const head = new Uint8Array(await entry.file.slice(chunk.offset, chunk.offset + 5).arrayBuffer());
    const slot = "區塊槽 " + chunk.slot;
    if (head.length < 5) {
      report("區域檔區塊損壞", "區塊標頭讀取不足。", entry.path, slot);
      invalid++; continue;
    }
    const declared = ((head[0] * 16777216) + (head[1] << 16) + (head[2] << 8) + head[3]) >>> 0;
    const end = chunk.offset + 4 + declared;
    if (declared < 1 || declared > chunk.sectorCount * 4096 - 4 || end > entry.file.size) {
      report("區域檔區塊長度異常", "區塊宣告長度超出配置範圍或實際檔案。", entry.path, slot);
      invalid++; continue;
    }
    const compression = head[4] & 0x7f;
    const external = !!(head[4] & 0x80);
    if (external || compression === 4 || (compression !== 1 && compression !== 2 && compression !== 3)) {
      // External .mcc/LZ4/new compression variants need a specialist; do not call them damaged.
      deferred++; continue;
    }
    if (declared - 1 > LIMITS.regionCompressedBytes) { deferred++; continue; }
    try {
      const blob = entry.file.slice(chunk.offset + 5, end);
      const kind = compression === 1 ? "gzip" : compression === 2 ? "deflate" : "none";
      parseNbt(await boundedInflate(blob, kind, LIMITS.expandedRegionBytes));
      samples++;
    } catch (err) {
      if (/expanded limit|unavailable/i.test(String(err && err.message))) {
        deferred++; continue;
      }
      report("區域檔區塊可能損壞", "抽樣區塊壓縮資料或 NBT 格式無法驗證，請先備份世界再進一步檢查。",
        entry.path, slot + "（" + safeReason(err) + "）");
      invalid++;
    }
  }
  return { samples, invalid, deferred: deferred + Math.max(0, header.chunks.length - LIMITS.regionSamples) };
}
async function analyze(entries, inputSummary) {
  const summary = { ...inputSummary, processed: 0, logs: 0, jars: 0, nbt: 0, configs: 0,
    regions: 0, regionSamples: 0, deferredRegionChunks: 0 };
  const modules = [];
  const unreadableNbt = [];
  const unreadableRegions = [];
  const unreadableConfigs = [];
  let incompleteJars = 0;
  let nbtLogPath = "";
  let regionLogPath = "";
  let configLogPath = "";
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
          if (issue.id === "region") regionLogPath = entry.path;
          if (issue.id === "config") configLogPath = entry.path;
          const hit = issue.evidence && issue.evidence[0];
          report(issue.name, issue.detail, entry.path,
            hit ? "日誌第 " + hit.line + " 行（" + issue.code + "）" : issue.code);
        }
      } else if (entry.kind === "jar") {
        summary.jars++;
        try {
          const result = await inspectJar(entry);
          modules.push(...result.modules);
          if (!result.complete) incompleteJars++;
        } catch (err) {
          incompleteJars++;
          report("模組 JAR 無法讀取", "ZIP 封裝可能損壞、加密或格式不支援，請核對來源檔案。",
            entry.path, safeReason(err));
        }
      } else if (entry.kind === "nbt") {
        summary.nbt++;
        try { await inspectNbt(entry); }
        catch (err) {
          unreadableNbt.push(entry.path);
          report("世界 NBT 讀取異常", "這份資料檔無法驗證。請先備份存檔再核對檔案與版本；本站不會修復或寫入。",
            entry.path, safeReason(err));
        }
      } else if (entry.kind === "config") {
        summary.configs++;
        try { await inspectConfig(entry); }
        catch (_) {
          unreadableConfigs.push(entry.path);
          report("設定檔語法異常", "JSON／JSON5／TOML 語法無法通過解析；請備份並以模組要求的格式確認。本站不顯示設定值。",
            entry.path);
        }
      } else if (entry.kind === "region") {
        summary.regions++;
        try {
          const region = await inspectRegion(entry);
          summary.regionSamples += region.samples;
          summary.deferredRegionChunks += region.deferred;
          if (region.invalid) unreadableRegions.push(entry.path);
        } catch (err) {
          unreadableRegions.push(entry.path);
          report("區域檔檢查未完成", "無法讀取 Anvil 索引或抽樣區塊。請保留原始世界檔。",
            entry.path, safeReason(err));
        }
      }
    } catch (err) {
      report("檔案分析未完成", "單一檔案解析失敗；其他檔案仍會繼續檢查。",
        entry.path, safeReason(err));
    }
    processed++;
    summary.processed = processed;
  }
  if (nbtLogPath && unreadableNbt.length) {
    report("交叉線索：日誌 NBT 錯誤與世界資料異常",
      "日誌中的 NBT 讀取錯誤和世界資料解析失敗可能相關，但需要核對實際世界、備份與錯誤位置。",
      unreadableNbt[0], "相關日誌：" + nbtLogPath);
  }
  if ((nbtLogPath || regionLogPath) && unreadableRegions.length) {
    report("交叉線索：日誌與區域檔異常",
      "日誌提及 NBT／區塊讀取問題，並有區域檔索引或抽樣區塊驗證失敗；不能單憑此判定哪個世界區塊是根因。",
      unreadableRegions[0], "相關日誌：" + (regionLogPath || nbtLogPath));
  }
  if (configLogPath && unreadableConfigs.length) {
    report("交叉線索：設定載入錯誤與語法異常",
      "日誌出現設定載入問題，同時有設定檔無法解析；請對照日誌提及的確切設定檔名稱。",
      unreadableConfigs[0], "相關日誌：" + configLogPath);
  }
  const eligible = inputSummary.eligible || {};
  const complete = !incompleteJars && Number(eligible.jar) <= LIMITS.jars &&
    summary.jars === Number(eligible.jar) && modules.length > 0;
  for (const f of RULES.dependencyFindings(modules, complete)) {
    report(f.title, f.description, f.path, f.evidence);
  }
  const skipped = Number(inputSummary.skipped || 0);
  const warnings = [];
  if (skipped) {
    const detail = inputSummary.skippedDetail || {};
    const nonTarget = Number(detail.unselected || 0);
    const limited = Number(detail.size || 0) + Number(detail.budget || 0) + Number(detail.safety || 0);
    warnings.push("有 " + nonTarget + " 個非目標或敏感檔案未讀取、" +
      limited + " 個檔案因大小或安全預算略過。這些檔案尚未驗證。");
  }
  if (incompleteJars || Number(eligible.jar) > LIMITS.jars) {
    warnings.push("模組清單未完整驗證，因此不判定缺少必要依賴。");
  }
  if (summary.regions) warnings.push("區域檔只抽查部分區塊；未抽查的區塊不代表正常。");
  return { type: "result", findings, summary,
    warning: warnings.join(" ") || "這是規則式初步診斷，不等於已證實根因。" };
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
