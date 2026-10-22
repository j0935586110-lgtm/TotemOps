/* TotemOps shared language controller for every public page.
   External file on purpose: diagnose.html runs a strict Content-Security-Policy
   (script-src 'self'), so an inline switcher would be blocked. */
(function () {
  "use strict";
  var STORAGE_KEY = "totemops-language";
  var dict = window.TOTEM_I18N || { zh: {}, en: {} };
  var page = (document.body && document.body.getAttribute("data-page")) || "home";
  var buttons = Array.prototype.slice.call(document.querySelectorAll("[data-select-language]"));

  function lookup(lang, key) {
    var table = dict[lang] || {};
    if (Object.prototype.hasOwnProperty.call(table, key)) return table[key];
    var scoped = page + "." + key;
    if (Object.prototype.hasOwnProperty.call(table, scoped)) return table[scoped];
    var shared = "common." + key;
    if (Object.prototype.hasOwnProperty.call(table, shared)) return table[shared];
    return null;
  }

  function setLanguage(requested) {
    var lang = requested === "en" ? "en" : "zh";
    document.documentElement.lang = lang === "en" ? "en" : "zh-Hant";
    window.TOTEM_LANGUAGE = lang;

    var titles = (dict.titles && dict.titles[lang]) || {};
    if (titles[page]) document.title = titles[page];

    var metaDescription = lookup(lang, "metaDescription");
    var meta = document.querySelector('meta[name="description"]');
    if (meta && metaDescription) meta.setAttribute("content", metaDescription);

    Array.prototype.forEach.call(document.querySelectorAll("[data-i18n]"), function (element) {
      var value = lookup(lang, element.getAttribute("data-i18n"));
      if (value !== null) element.textContent = value;
    });
    Array.prototype.forEach.call(document.querySelectorAll("[data-i18n-html]"), function (element) {
      var value = lookup(lang, element.getAttribute("data-i18n-html"));
      if (value !== null) element.innerHTML = value;
    });
    Array.prototype.forEach.call(document.querySelectorAll("[data-i18n-label]"), function (element) {
      var value = lookup(lang, element.getAttribute("data-i18n-label"));
      if (value !== null) element.setAttribute("aria-label", value);
    });
    Array.prototype.forEach.call(document.querySelectorAll("[data-i18n-placeholder]"), function (element) {
      var value = lookup(lang, element.getAttribute("data-i18n-placeholder"));
      if (value !== null) element.setAttribute("placeholder", value);
    });
    Array.prototype.forEach.call(document.querySelectorAll("[data-i18n-alt]"), function (element) {
      var value = lookup(lang, element.getAttribute("data-i18n-alt"));
      if (value !== null) element.setAttribute("alt", value);
    });

    buttons.forEach(function (button) {
      button.setAttribute("aria-pressed", String(button.getAttribute("data-select-language") === lang));
    });

    if (typeof window.TOTEM_I18N_ON_LANGUAGE === "function") window.TOTEM_I18N_ON_LANGUAGE(lang);
    try { localStorage.setItem(STORAGE_KEY, lang); } catch (_) {}
    document.dispatchEvent(new CustomEvent("totem:language", { detail: { lang: lang } }));
  }

  window.TOTEM_SET_LANGUAGE = setLanguage;
  window.TOTEM_TRANSLATE = function (key) {
    var value = lookup(window.TOTEM_LANGUAGE === "en" ? "en" : "zh", key);
    return value === null ? "" : value;
  };

  buttons.forEach(function (button) {
    button.addEventListener("click", function () {
      setLanguage(button.getAttribute("data-select-language"));
    });
  });

  var params = new URLSearchParams(window.location.search);
  var initial = params.get("lang");
  if (initial !== "zh" && initial !== "en") {
    try { initial = localStorage.getItem(STORAGE_KEY); } catch (_) {}
  }
  setLanguage(initial === "en" ? "en" : "zh");
})();
