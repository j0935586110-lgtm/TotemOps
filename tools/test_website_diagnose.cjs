"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const path = require("node:path");
const { analyzeLog, LIMIT_BYTES, LIMIT_LINES, samples } = require("../docs/assets/diagnose.js");

test("dependency demo identifies missing required module with correct source line", () => {
  const out = analyzeLog(samples.missing.log);
  assert.equal(out.status, "indicators_found");
  assert.equal(out.findings[0].id, "dependency");
  assert.equal(out.findings[0].evidence[0].line, 3);
  assert.equal(out.findings[0].certainty, "heuristic");
});
test("mixin case is a clue rather than verified root cause", () => {
  const out = analyzeLog(samples.mixin.log);
  assert(out.findings.some(f => f.id === "mixin"));
  assert(out.message.includes("不是已驗證"));
});
test("memory case is classified", () => {
  assert(analyzeLog(samples.memory.log).findings.some(f => f.id === "memory"));
});
test("clean sample does not imply a healthy server", () => {
  const out = analyzeLog(samples.clean.log);
  assert.equal(out.status, "no_known_indicators");
  assert(out.message.includes("不代表"));
});
test("Java, port, duplicate mod detection is isolated", () => {
  for (const [line, id] of [
    ["java.lang.UnsupportedClassVersionError: class file version 65", "java"],
    ["java.net.BindException: Address already in use", "port"],
    ["Duplicate mod IDs detected", "duplicate"]
  ]) assert(analyzeLog(line).findings.some(f => f.id === id));
});
test("empty and invalid inputs are rejected", () => {
  assert.equal(analyzeLog("   ").status, "empty");
  assert.equal(analyzeLog(null).status, "invalid");
});
test("file size and line count are capped", () => {
  assert.equal(analyzeLog("x".repeat(LIMIT_BYTES + 1)).status, "too_large");
  assert.equal(analyzeLog("a\n".repeat(LIMIT_LINES + 1)).status, "too_many_lines");
});
test("works with windows newlines and unicode", () => {
  const out = analyzeLog("啟動\r\nMissing mandatory dependencies: Mod A requires mod B to be installed\r\n");
  assert.equal(out.findings[0].evidence[0].line, 2);
});
test("page has no external scripts, network endpoints or forms", () => {
  const page = fs.readFileSync(path.join(__dirname, "../docs/diagnose.html"), "utf8");
  assert(page.includes("connect-src 'none'"));
  assert(page.includes('script src="assets/diagnose.js" defer'));
  assert(!/<form\b/i.test(page));
  assert(!/<script[^>]+src=["']https?:/i.test(page));
  assert(!/https?:\/\/(?:www\.)?google-analytics\.com/i.test(page));
});
test("original homepage links to local diagnoser", () => {
  const homepage = fs.readFileSync(path.join(__dirname, "../docs/index.html"), "utf8");
  assert(homepage.includes('href="diagnose.html"'));
});
