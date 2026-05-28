/**
 * Levix Theme System — Preparation Layer
 * ----------------------------------------
 * Status: ARCHITECTURE ONLY — dark mode CSS not yet implemented.
 * This script detects system preference and stores the user's theme
 * so the full dark mode rollout can be toggled without HTML changes.
 *
 * Usage:
 *   Include this script in <head> (before any CSS) to prevent flash:
 *   <script src="/static/theme.js"></script>
 *
 * When dark mode CSS is ready:
 *   1. Add [data-theme="dark"] CSS rules to your stylesheets.
 *   2. Uncomment the applyTheme() call below.
 *   3. Add a theme toggle button that calls window.levixTheme.toggle().
 */

(function () {
  var STORAGE_KEY = 'levix-theme';

  function getPreferredTheme() {
    // 1. Check stored preference
    var stored = localStorage.getItem(STORAGE_KEY);
    if (stored === 'dark' || stored === 'light') return stored;

    // 2. Fall back to system preference
    if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
      return 'dark';
    }
    return 'light';
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    // meta theme-color
    var metaTheme = document.querySelector('meta[name="theme-color"]');
    if (metaTheme) {
      metaTheme.setAttribute('content', '#000000');
    }
  }

  function setTheme(theme) {
    localStorage.setItem(STORAGE_KEY, theme);
    applyTheme(theme);
  }

  function toggle() {
    var current = document.documentElement.getAttribute('data-theme') || 'light';
    setTheme(current === 'dark' ? 'light' : 'dark');
  }

  // Listen for system preference changes
  if (window.matchMedia) {
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function (e) {
      if (!localStorage.getItem(STORAGE_KEY)) {
        applyTheme(e.matches ? 'dark' : 'light');
      }
    });
  }

  // Apply on load — currently always forces 'light' until dark CSS is ready.
  // To enable: replace the line below with: applyTheme(getPreferredTheme());
  applyTheme('light');

  // Expose public API for future toggle button
  window.levixTheme = {
    get: getPreferredTheme,
    set: setTheme,
    toggle: toggle,
  };
})();
