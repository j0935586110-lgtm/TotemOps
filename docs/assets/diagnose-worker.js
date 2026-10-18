/* Local-only background processing for large Minecraft logs. */
"use strict";
importScripts("diagnose.js");

self.onmessage = async (event) => {
  try {
    const file = event.data && event.data.file;
    const result = await self.TotemDiagnose.analyzeFile(file, (done, total) => {
      self.postMessage({ type: "progress", done, total });
    });
    self.postMessage({ type: "result", result });
  } catch (error) {
    self.postMessage({ type: "error" });
  }
};
