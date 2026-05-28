/**
 * Levix i18n — Multilingual Architecture Preparation
 * ----------------------------------------------------
 * Status: ARCHITECTURE ONLY — translations not yet authored.
 *
 * Supported languages planned:
 *   - en   (English)   — active
 *   - ta   (Tamil)     — planned
 *
 * How it works:
 *   - All translatable strings are tagged with data-i18n="key"
 *   - loadLanguage(lang) fetches /static/locales/{lang}.json and
 *     replaces all matching elements
 *
 * To activate:
 *   1. Create /static/locales/en.json with all string keys.
 *   2. Create /static/locales/ta.json with Tamil translations.
 *   3. Tag HTML elements: <h1 data-i18n="hero.title">...</h1>
 *   4. Call window.levixI18n.load('ta') to switch to Tamil.
 *   5. Add a language toggle button to the navbar.
 *
 * Example locale file (en.json):
 * {
 *   "nav.features":    "Features",
 *   "nav.pricing":     "Pricing",
 *   "nav.about":       "About",
 *   "nav.contact":     "Contact",
 *   "nav.signin":      "Sign In",
 *   "hero.title":      "Manage Your Shop Orders, Inventory & Customers",
 *   "hero.subtitle":   "Levix helps local businesses handle daily operations faster.",
 *   "hero.cta":        "Create Your Shop",
 *   "hero.trust1":     "Starts at ₹799/month",
 *   "hero.trust2":     "MSME Registered",
 *   "hero.trust3":     "Works on any device"
 * }
 *
 * Example locale file (ta.json):
 * {
 *   "nav.features":    "அம்சங்கள்",
 *   "nav.pricing":     "விலை",
 *   ...
 * }
 */

(function () {
  var STORAGE_KEY = 'levix-lang';
  var SUPPORTED = ['en', 'ta'];
  var _cache = {};

  function getStoredLang() {
    var stored = localStorage.getItem(STORAGE_KEY);
    if (stored && SUPPORTED.indexOf(stored) !== -1) return stored;
    // Detect browser language
    var browser = (navigator.language || 'en').split('-')[0];
    return SUPPORTED.indexOf(browser) !== -1 ? browser : 'en';
  }

  function applyStrings(strings) {
    var elements = document.querySelectorAll('[data-i18n]');
    elements.forEach(function (el) {
      var key = el.getAttribute('data-i18n');
      if (strings[key] !== undefined) {
        el.textContent = strings[key];
      }
    });
    document.documentElement.setAttribute('lang', strings['__lang__'] || 'en');
  }

  function load(lang) {
    if (SUPPORTED.indexOf(lang) === -1) lang = 'en';
    localStorage.setItem(STORAGE_KEY, lang);

    // Return from cache if available
    if (_cache[lang]) {
      applyStrings(_cache[lang]);
      return Promise.resolve(_cache[lang]);
    }

    // Fetch locale file
    return fetch('/static/locales/' + lang + '.json')
      .then(function (r) { return r.json(); })
      .then(function (strings) {
        _cache[lang] = strings;
        applyStrings(strings);
        return strings;
      })
      .catch(function (err) {
        console.warn('[i18n] Could not load locale: ' + lang, err);
      });
  }

  // Expose public API
  window.levixI18n = {
    load: load,
    current: getStoredLang,
    supported: SUPPORTED,
  };

  // NOTE: Auto-load is intentionally disabled until locale files are authored.
  // To enable: window.levixI18n.load(getStoredLang());
})();
