"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const path = require("node:path");
const { analyzeLog, analyzeFile, LIMIT_BYTES, CHUNK_BYTES, samples } = require("../docs/assets/diagnose.js");

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
test("64 MiB is the file cap and 30,000 lines is no longer a cap", async () => {
  assert.equal(LIMIT_BYTES, 64 * 1024 * 1024);
  assert.equal(CHUNK_BYTES, 512 * 1024);
  const tooBig = { size: LIMIT_BYTES + 1, slice() { throw new Error("must not read"); } };
  assert.equal((await analyzeFile(tooBig)).status, "too_large");
  const lines = "hello\n".repeat(30001) + "OutOfMemoryError\n";
  const out = analyzeLog(lines);
  assert.equal(out.status, "indicators_found");
  assert.equal(out.findings.find((f) => f.id === "memory").evidence[0].line, 30002);
});
test("streamed chunks preserve CRLF, Unicode, exact line numbers and progress", async () => {
  const content = "啟動\r\n[INFO] ok\r\nMissing mandatory dependencies: Mod A requires mod B to be installed\n";
  const bytes = new TextEncoder().encode(content);
  const progress = [];
  const out = await analyzeFile(new Blob([bytes]), (done, total) => progress.push([done, total]), 5);
  assert.equal(out.status, "indicators_found");
  assert.equal(out.findings[0].evidence[0].line, 3);
  assert.equal(out.lineCount, 4);
  assert.equal(progress.at(-1)[0], bytes.length);
  assert(progress.length > 1);
  assert.equal(out.findings[0].certainty, "heuristic");
});
test("streams a realistic 30 MiB log without truncating findings", async () => {
  const line = "[00:00:00] [Server thread/INFO]: heartbeat".padEnd(1023, ".") + "\n";
  const block = line.repeat(1024);
  const bigLog = new Blob([...Array(30).fill(block), "[ERROR] OutOfMemoryError\n"]);
  assert(bigLog.size > 30 * 1024 * 1024);
  const out = await analyzeFile(bigLog);
  assert.equal(out.status, "indicators_found");
  assert.equal(out.findings.find((f) => f.id === "memory").evidence[0].line, 30721);
  assert(out.lineCount > 30000);
});
test("works with windows newlines and unicode", () => {
  const out = analyzeLog("啟動\r\nMissing mandatory dependencies: Mod A requires mod B to be installed\r\n");
  assert.equal(out.findings[0].evidence[0].line, 2);
});
test("page has no external scripts, network endpoints or forms", () => {
  const page = fs.readFileSync(path.join(__dirname, "../docs/diagnose.html"), "utf8");
  assert(page.includes("connect-src 'none'"));
  assert(page.includes("worker-src 'self'"));
  assert(page.includes("檔案大小上限 64 MiB"));
  const worker = fs.readFileSync(path.join(__dirname, "../docs/assets/diagnose-worker.js"), "utf8");
  assert(!/\bfetch\s*\(|XMLHttpRequest/.test(worker));
  assert(page.includes('script src="assets/diagnose.js" defer'));
  assert(!/<form\b/i.test(page));
  assert(!/<script[^>]+src=["']https?:/i.test(page));
  assert(!/https?:\/\/(?:www\.)?google-analytics\.com/i.test(page));
});
test("original homepage links to local diagnoser", () => {
  const homepage = fs.readFileSync(path.join(__dirname, "../docs/index.html"), "utf8");
  assert(homepage.includes('href="diagnose.html"'));
});

test("homepage has a functional local file chooser and visible feedback", () => {
  const homepage = fs.readFileSync(path.join(__dirname, "../docs/index.html"), "utf8");
  assert(homepage.includes('id="log-file"'));
  assert(homepage.includes('id="dropzone"'));
  assert(homepage.includes('id="file-feedback"'));
  assert(homepage.includes('id="result"'));
  assert(homepage.includes('src="assets/diagnose.js" defer'));
  assert(homepage.includes('64 MiB'));
});
test("invalid file types and drops outside the target have explicit handling", () => {
  const source = fs.readFileSync(path.join(__dirname, "../docs/assets/diagnose.js"), "utf8");
  assert(source.includes('ZIP/JAR'));
  assert(source.includes('document.addEventListener("drop"'));
  assert(source.includes('showFeedback('));
});
