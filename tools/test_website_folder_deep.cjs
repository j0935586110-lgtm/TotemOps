"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { classifyPath, planFolder, LIMITS } = require("../docs/assets/folder-diagnose.js");
const rules = require("../docs/assets/folder-rules.js");
const assets = path.resolve(__dirname, "../docs/assets");
const sandbox = vm.createContext({});
vm.runInContext(fs.readFileSync(path.join(assets, "vendor/toml.min.js"), "utf8"), sandbox);
vm.runInContext(fs.readFileSync(path.join(assets, "vendor/json5.min.js"), "utf8"), sandbox);
const parseToml = sandbox.TotemToml.parse;

function fakeFile(name, size = 100, extra = {}) {
  return { name: name.split("/").at(-1), webkitRelativePath: name, size, ...extra };
}
function regionHeader(locations) {
  const bytes = new Uint8Array(8192);
  for (const [slot, offset, sectors] of locations) {
    const at = slot * 4;
    bytes[at] = offset >> 16 & 255;
    bytes[at + 1] = offset >> 8 & 255;
    bytes[at + 2] = offset & 255;
    bytes[at + 3] = sectors;
  }
  return bytes;
}

test("deep folder classification excludes player files and handles only known NBT and config layouts", () => {
  for (const filename of [
    "world/.minecraft/saves/Demo/region/r.0.-4.mca",
    "world/.minecraft/saves/Demo/DIM-1/region/r.3.4.mca",
    "world/.minecraft/saves/Demo/dimensions/mymod/moon/region/r.1.2.mca",
    "world/.minecraft/config/mymod/client/settings.json5",
    "world/.minecraft/saves/Demo/data/forcedchunks.dat",
    "world/.minecraft/saves/Demo/data/idcounts.dat",
    "world/.minecraft/config/test.toml",
    "world/.minecraft/defaultconfigs/test.json5",
    "world/.minecraft/saves/Demo/serverconfig/a.json"
  ]) assert.ok(classifyPath(filename), filename);
  for (const filename of [
    "world/.minecraft/saves/Demo/playerdata/uuid.dat",
    "world/.minecraft/saves/Demo/data/map_23.dat",
    "world/.minecraft/config/token.json",
    "world/.minecraft/accounts.json",
    "world/.minecraft/saves/Demo/region/r.0.0.mca/../secret",
    "world/.minecraft/resourcespacks/data.zip"
  ]) assert.equal(classifyPath(filename), null, filename);
});

test("1.5 GiB folder planning never reads content, limits configs and regions", () => {
  const files = [
    fakeFile(".minecraft/resourcepacks/large.zip", 1490 * 1024 * 1024, {
      slice() { throw new Error("must not open resource pack"); }
    }),
    fakeFile(".minecraft/logs/latest.log", 1024)
  ];
  for (let i = 0; i < 31; i++) files.push(fakeFile(".minecraft/saves/Demo/region/r." + i + ".0.mca", 1024 * 1024));
  for (let i = 0; i < 70; i++) files.push(fakeFile(".minecraft/config/a-" + i + ".toml", 128 * 1024));
  const result = planFolder(files);
  assert.equal(result.region.length, LIMITS.regions);
  assert.equal(result.config.length, Math.min(LIMITS.configs, LIMITS.totalConfigBytes / (128 * 1024)));
  assert.equal(result.log.length, 1);
  assert.ok(result.skipped.budget >= 40);
  assert.ok(result.bytes >= 1490 * 1024 * 1024);
});

test("Fabric required and breaks and Forge/NeoForge mandatory semantics", () => {
  const fabric = rules.fabricMetadata(JSON.stringify({
    id: "clientmod", version: "1.0",
    depends: { "fabric-api": "*", libmod: ">=1.0", minecraft: "1.21.1" },
    breaks: { oldmod: "<2.0" }, recommends: { cosmetic: "*" }
  }));
  assert.deepEqual(fabric[0].dependencies.map(d => [d.id, d.kind]), [
    ["fabric-api", "required"], ["libmod", "required"], ["oldmod", "incompatible"], ["cosmetic", "suggested"]
  ]);
  const forge = rules.tomlMetadata(`modLoader="javafml"
[[mods]]
modId="forgeaddon"
version="1.0"
[[dependencies.forgeaddon]]
modId="library"
mandatory=true
versionRange="[1.0,)"
side="BOTH"
[[dependencies.forgeaddon]]
modId="serveronly"
mandatory=true
side="SERVER"
`, "forge", parseToml);
  assert.deepEqual(forge[0].dependencies.map(d => [d.id, d.kind]), [["library", "required"]]);
  const neo = rules.tomlMetadata(`modLoader="javafml"
[[mods]]
modId="neoaddon"
version="1.1"
[[dependencies.neoaddon]]
modId="helper"
type="required"
[[dependencies.neoaddon]]
modId="conflictmod"
type="incompatible"
[[dependencies.neoaddon]]
modId="optional"
type="optional"
`, "neoforge", parseToml);
  assert.deepEqual(neo[0].dependencies.map(d => [d.id, d.kind]), [
    ["helper", "required"], ["conflictmod", "incompatible"], ["optional", "suggested"]
  ]);
  const modules = [
    {...fabric[0], path:"mods/fabric.jar"},
    {...forge[0], path:"mods/forge.jar"},
    {...neo[0], path:"mods/neo.jar"},
    { id:"oldmod", version:"1.0", loader:"fabric", path:"mods/old.jar", dependencies:[]},
    { id:"conflictmod", version:"1.0", loader:"neoforge", path:"mods/conflict.jar", dependencies:[]}
  ];
  const complete = rules.dependencyFindings(modules, true);
  assert.ok(complete.some(x=>x.title.includes("fabric-api")));
  assert.ok(complete.some(x=>x.title.includes("library")));
  assert.ok(complete.some(x=>x.title.includes("helper")));
  assert.ok(complete.some(x=>x.title.includes("oldmod") && x.title.includes("衝突")));
  assert.ok(complete.some(x=>x.title.includes("conflictmod") && x.title.includes("衝突")));
  assert.equal(rules.dependencyFindings(modules, false).some(x=>x.title.includes("缺少")), false);
});

test("valid Anvil headers, truncation, zero counts and overlaps", () => {
  const good = rules.inspectRegionHeader(regionHeader([[0,2,1],[1,3,2]]), 5 * 4096);
  assert.equal(good.issues.length, 0);
  assert.equal(good.populated, 2);
  assert.equal(rules.chooseRegionSamples(good.chunks, 4).length, 2);
  const bad = rules.inspectRegionHeader(regionHeader([[0,1,1],[1,2,0],[2,2,3],[3,3,1],[4,10,2]]), 5 * 4096);
  assert.equal(bad.issues.length, 4);
  assert.ok(bad.issues.some(i => i.description.includes("重疊")));
  assert.ok(bad.issues.some(i => i.description.includes("超出")));
  const truncated = rules.inspectRegionHeader(new Uint8Array(1024), 1024);
  assert.ok(truncated.issues.some(x => x.description.includes("8 KiB")));
});

test("TOML and JSON5 use bundled maintained parsers, not regex or evaluation", () => {
  assert.ok(parseToml('name = "ok"').name === "ok");
  assert.throws(() => parseToml('name = "not closed'), /.+/);
  assert.deepEqual(JSON.parse(JSON.stringify(sandbox.JSON5.parse("{foo: 'bar',}"))), { foo: "bar" });
  assert.throws(() => sandbox.JSON5.parse("{foo:,"), /.+/);
});

test("deep worker is bounded, local-only and documents third-party licenses", () => {
  const source = fs.readFileSync(path.join(assets, "folder-worker.js"), "utf8");
  assert.match(source, /regionCompressedBytes/);
  assert.match(source, /expandedRegionBytes/);
  assert.match(source, /inspectRegionHeader/);
  assert.match(source, /vendor\/toml.min.js/);
  assert.match(source, /vendor\/json5.min.js/);
  assert.match(source, /DecompressionStream/);
  assert.doesNotMatch(source, /\b(?:fetch|XMLHttpRequest|sendBeacon)\s*\(/);
  const thirdParty = fs.readFileSync(path.join(assets, "vendor/THIRD_PARTY.md"), "utf8");
  assert.match(thirdParty, /smol-toml/);
  assert.match(thirdParty, /json5/);
});
