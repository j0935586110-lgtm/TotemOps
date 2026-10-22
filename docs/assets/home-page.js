/* Home-page-only language side effects (image variant, guide links, meta description).
   Defines the hook that docs/assets/site-header.js calls after every language change. */
window.TOTEM_I18N_ON_LANGUAGE = function (lang) {
  "use strict";
  var english = lang === "en";

  var image = document.getElementById("workflow-image");
  if (image) {
    image.src = english ? "assets/totemops-steps-en.svg" : "assets/totemops-steps-zh.svg";
    image.alt = english
      ? "Concept workflow: inspect logs, check dependencies, optionally test in a sandbox, report results"
      : "流程示意：看線索、查相依、可選沙箱、交付報告";
  }

  var advanced = document.getElementById("advanced-link");
  if (advanced) {
    advanced.href = english
      ? "https://github.com/j0935586110-lgtm/TotemOps/blob/main/docs/ADVANCED_GUIDE.en.md"
      : "https://github.com/j0935586110-lgtm/TotemOps/blob/main/docs/ADVANCED_GUIDE.zh-TW.md";
  }

  var guide = document.getElementById("guide-link");
  if (guide) {
    guide.href = english
      ? "https://github.com/j0935586110-lgtm/TotemOps/blob/main/README.en.md"
      : "https://github.com/j0935586110-lgtm/TotemOps/blob/main/README.md";
  }
};
