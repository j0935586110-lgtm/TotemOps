/* Strict, read-only metadata rules for browser folder diagnostics. No network or world writes. */
(function (root) {
  "use strict";
  const reserved = new Set(["minecraft", "java", "fabricloader", "forge", "neoforge", "quilt_loader", "fabric", "quilt"]);
  function normalizedId(id) {
    const value = String(id || "").toLowerCase();
    return /^[a-z0-9_.-]{1,100}$/.test(value) ? value : "";
  }
  function versionString(value) {
    return String(typeof value === "string" ? value : "?").slice(0, 80);
  }
  function fabricMetadata(text) {
    const obj = JSON.parse(text);
    if (!obj || typeof obj !== "object" || !normalizedId(obj.id)) return [];
    const dependencies = [];
    for (const [field, kind] of [["depends", "required"], ["breaks", "incompatible"],
                                  ["conflicts", "warning"], ["recommends", "suggested"]]) {
      const map = obj[field];
      if (!map || typeof map !== "object" || Array.isArray(map)) continue;
      for (const [id, range] of Object.entries(map).slice(0, 100)) {
        if (normalizedId(id) && !reserved.has(id.toLowerCase())) {
          dependencies.push({ id: id.toLowerCase(), kind, range: versionString(range) });
        }
      }
    }
    return [{ id: obj.id.toLowerCase(), version: versionString(obj.version),
      loader: "fabric", dependencies }];
  }
  function tomlMetadata(text, loader, parser) {
    if (typeof parser !== "function") throw new Error("TOML parser unavailable");
    const doc = parser(text);
    if (!doc || typeof doc !== "object") return [];
    const mods = Array.isArray(doc.mods) ? doc.mods.slice(0, 20) : [];
    const deps = doc.dependencies && typeof doc.dependencies === "object" ? doc.dependencies : {};
    return mods.map(mod => {
      if (!mod || !normalizedId(mod.modId)) return null;
      const id = mod.modId.toLowerCase();
      const declared = Array.isArray(deps[id]) ? deps[id] : deps[id] ? [deps[id]] : [];
      const dependencies = [];
      for (const dep of declared.slice(0, 100)) {
        if (!dep || !normalizedId(dep.modId)) continue;
        const depId = dep.modId.toLowerCase();
        if (reserved.has(depId)) continue;
        const side = String(dep.side || "BOTH").toUpperCase();
        if (side === "SERVER") continue; // This is a client-folder scan.
        let kind = "suggested";
        if (loader === "neoforge") {
          const type = String(dep.type || "required").toLowerCase();
          if (type === "required") kind = "required";
          if (type === "incompatible") kind = "incompatible";
          if (type === "discouraged") kind = "warning";
        } else {
          if (dep.mandatory === true) kind = "required";
        }
        dependencies.push({ id: depId, kind, range: versionString(dep.versionRange) });
      }
      return { id, version: versionString(mod.version), loader, dependencies };
    }).filter(Boolean);
  }
  function dependencyFindings(modules, complete) {
    const installed = new Map();
    const findings = [];
    const seen = new Set();
    const presentLoaders = new Set();
    for (const mod of modules) {
      if (!normalizedId(mod.id)) continue;
      if (!installed.has(mod.id)) installed.set(mod.id, []);
      installed.get(mod.id).push(mod);
      presentLoaders.add(mod.loader);
    }
    for (const [id, instances] of installed) {
      if (new Set(instances.map(m => m.path)).size > 1) {
        findings.push({ title: "可能有重複模組 ID：" + id,
          description: "兩個以上的 JAR 宣告同一個模組 ID；需確認 Loader、版本與檔案用途。",
          path: instances[0].path, evidence: instances.map(m => m.version).join("、").slice(0, 160) });
      }
    }
    // Multiple metadata formats inside ONE multi-loader JAR are legitimate.
    if (presentLoaders.has("fabric") && (presentLoaders.has("forge") || presentLoaders.has("neoforge"))) {
      const mixed = modules.filter(m => m.loader === "fabric");
      const others = modules.filter(m => m.loader !== "fabric");
      if (mixed.some(a => others.some(b => a.path !== b.path))) {
        findings.push({ title: "偵測到多種 Loader 的模組描述檔",
          description: "Fabric 與 Forge／NeoForge 類型同時出現；跨 Loader 模組可能無法一起載入，請核對實際啟動環境。多 Loader 通用模組可能屬正常情況。" });
      }
    }
    for (const mod of modules) {
      for (const dep of mod.dependencies || []) {
        const key = mod.path + "|" + mod.id + "|" + dep.id + "|" + dep.kind;
        if (seen.has(key)) continue;
        seen.add(key);
        const exists = installed.has(dep.id);
        if (dep.kind === "incompatible" && exists) {
          findings.push({ title: "可能有宣告衝突的模組：" + dep.id,
            description: mod.loader + " 描述檔宣告與此模組不相容；版本範圍可能限制衝突條件，請進一步依官方版本資訊確認。",
            path: mod.path, evidence: mod.id + " ↔ " + dep.id + "（範圍 " + dep.range + "）" });
        } else if (dep.kind === "required" && !exists && complete) {
          findings.push({ title: "可能缺少必要前置模組：" + dep.id,
            description: "完整且可讀的模組清單中找不到描述檔宣告的必要相依 ID；請確認所需版本與 Loader。內建元件不在此檢查。",
            path: mod.path, evidence: mod.id + " → " + dep.id + "（範圍 " + dep.range + "）" });
        }
      }
    }
    return findings;
  }

  const SECTOR_BYTES = 4096;
  const HEADER_BYTES = 8192;
  function inspectRegionHeader(bytes, length) {
    const result = { chunks: [], issues: [], populated: 0 };
    if (!(bytes instanceof Uint8Array) || bytes.length < HEADER_BYTES || length < HEADER_BYTES) {
      result.issues.push({ slot: -1, description: "Anvil 區域檔少於必要的 8 KiB 索引表，可能遭截斷。" });
      return result;
    }
    const ranges = [];
    for (let slot = 0; slot < 1024; slot++) {
      const at = slot * 4;
      const offset = bytes[at] * 65536 + bytes[at + 1] * 256 + bytes[at + 2];
      const count = bytes[at + 3];
      if (offset === 0 && count === 0) continue;
      result.populated++;
      if (offset < 2 || count === 0) {
        result.issues.push({ slot, description: "區塊索引位置或扇區數量無效。" });
        continue;
      }
      if ((offset + count) * SECTOR_BYTES > length) {
        result.issues.push({ slot, description: "區塊索引超出區域檔實際長度，可能截斷。" });
        continue;
      }
      const overlap = ranges.find(r => offset < r.end && r.start < offset + count);
      if (overlap) {
        result.issues.push({ slot, description: "扇區與另一個區塊索引重疊（槽位 " + overlap.slot + "）。" });
        continue;
      }
      ranges.push({ start: offset, end: offset + count, slot });
      result.chunks.push({ slot, offset: offset * SECTOR_BYTES, sectorCount: count });
    }
    return result;
  }
  function chooseRegionSamples(chunks, max) {
    const limit = Math.max(0, Math.min(16, Number(max) || 0));
    if (!limit || !chunks.length) return [];
    if (chunks.length <= limit) return chunks;
    if (limit === 1) return [chunks[0]];
    const positions = new Set();
    for (let i = 0; i < limit; i++) {
      positions.add(Math.round(i * (chunks.length - 1) / (limit - 1)));
    }
    return [...positions].map(i => chunks[i]);
  }
  const api = { fabricMetadata, tomlMetadata, dependencyFindings,
    inspectRegionHeader, chooseRegionSamples };
  if (typeof module === "object" && module.exports) module.exports = api;
  root.TotemFolderRules = api;
})(typeof globalThis === "object" ? globalThis : this);
