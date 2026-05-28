/**
 * LEVIX install — 100% our UI. Chrome/Google native popups suppressed.
 * Mobile: /install-app full page. Marketing pages: same wizard in modal on click only.
 */
(() => {
  const INSTALL_BTN_SELECTOR = "#install-app-btn, [data-levix-install-trigger]";
  const SHEET_ID = "levix-install-sheet";
  const PAGE_ROOT_ID = "levix-install-page-root";

  const ua = navigator.userAgent || "";
  const isIOS =
    /iPad|iPhone|iPod/.test(ua) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  const isAndroid = /Android/i.test(ua);
  const isStandalone =
    window.matchMedia("(display-mode: standalone)").matches ||
    window.navigator.standalone === true;
  const isSecure = window.isSecureContext === true;

  function detectBrowser() {
    if (isIOS) {
      const isSafari = /Safari/i.test(ua) && !/CriOS|FxiOS|EdgiOS|OPiOS/i.test(ua);
      return isSafari ? "safari" : "ios-other";
    }
    if (isAndroid) {
      if (/GSA\//i.test(ua) || (/GoogleApp/i.test(ua) && !/Chrome/i.test(ua))) return "google-app";
      if (/SamsungBrowser/i.test(ua)) return "samsung";
      if (/Chrome/i.test(ua) && !/EdgA|OPR|MiuiBrowser/i.test(ua)) return "chrome";
      if (/Firefox/i.test(ua)) return "firefox";
      return "android-other";
    }
    if (/Chrome/i.test(ua) && !/Edg|OPR/i.test(ua)) return "chrome-desktop";
    return "desktop-other";
  }

  const browser = detectBrowser();
  const isChrome = browser === "chrome" || browser === "chrome-desktop";
  const needsChrome = isAndroid && !isChrome;

  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function delay(ms) {
    return new Promise((r) => setTimeout(r, ms));
  }

  function getInstallUrl() {
    const path = window.location.pathname || "/";
    const from = encodeURIComponent(path);
    return `/install-app?from=${from}`;
  }

  function chromeIntentUrl() {
    const target = `https://${window.location.host}/install-app?from=chrome`;
    return `intent://${window.location.host}/install-app?from=chrome#Intent;scheme=https;package=com.android.chrome;S.browser_fallback_url=${encodeURIComponent(target)};end`;
  }

  function progressRow(id, label, state) {
    const icons = {
      pending: '<span class="levix-ip-dot"></span>',
      active: '<span class="levix-ip-spinner"></span>',
      done: '<span class="levix-ip-check">✓</span>',
      error: '<span class="levix-ip-error">!</span>',
    };
    return `<li class="levix-install-progress-item is-${state}" data-step="${id}">
      <span class="levix-install-progress-icon">${icons[state] || icons.pending}</span>
      <span class="levix-install-progress-label">${escapeHtml(label)}</span>
    </li>`;
  }

  function updateProgressStep(stepId, state, label) {
    document.querySelectorAll(`[data-step="${stepId}"]`).forEach((item) => {
      item.className = `levix-install-progress-item is-${state}`;
      if (label) {
        const el = item.querySelector(".levix-install-progress-label");
        if (el) el.textContent = label;
      }
      const icon = item.querySelector(".levix-install-progress-icon");
      if (!icon) return;
      const icons = {
        pending: '<span class="levix-ip-dot"></span>',
        active: '<span class="levix-ip-spinner"></span>',
        done: '<span class="levix-ip-check">✓</span>',
        error: '<span class="levix-ip-error">!</span>',
      };
      icon.innerHTML = icons[state] || icons.pending;
    });
  }

  function setStatusText(text) {
    document.querySelectorAll("[data-levix-install-status]").forEach((el) => {
      el.textContent = text;
    });
  }

  function browserBadgeHtml() {
    if (browser === "chrome" || browser === "chrome-desktop") {
      return '<span class="levix-browser-badge is-ok">✓ Google Chrome detected</span>';
    }
    if (browser === "google-app") {
      return '<span class="levix-browser-badge is-bad">✕ Google app — install not supported here</span>';
    }
    if (browser === "safari") {
      return '<span class="levix-browser-badge is-ok">✓ Safari detected</span>';
    }
    if (isIOS) {
      return '<span class="levix-browser-badge is-warn">! Use Safari on iPhone</span>';
    }
    return '<span class="levix-browser-badge is-warn">! Use Google Chrome for install</span>';
  }

  function chromeMenuMockHtml() {
    return `
      <div class="levix-chrome-mock" aria-hidden="true">
        <div class="levix-chrome-mock-bar">
          <span>levixapp.in</span>
          <span class="levix-chrome-mock-dots" title="Menu">⋮</span>
        </div>
        <div class="levix-chrome-mock-menu">
          <div class="levix-chrome-mock-item">New tab</div>
          <div class="levix-chrome-mock-item">Share…</div>
          <div class="levix-chrome-mock-item is-target">Add to Home screen</div>
          <div class="levix-chrome-mock-item">Install app</div>
        </div>
      </div>`;
  }

  function guideStepsHtml(platform) {
    if (platform === "ios") {
      return `
        <ol class="levix-install-steps">
          <li><span class="levix-install-step-num">1</span><span>In <strong>Safari</strong>, tap <strong>Share</strong> (bottom).</span></li>
          <li><span class="levix-install-step-num">2</span><span>Tap <strong>Add to Home Screen</strong>.</span></li>
          <li><span class="levix-install-step-num">3</span><span>Tap <strong>Add</strong> — LEVIX icon appears on your home screen.</span></li>
        </ol>`;
    }
    return `
      ${chromeMenuMockHtml()}
      <ol class="levix-install-steps">
        <li><span class="levix-install-step-num">1</span><span>In <strong>Chrome</strong>, tap <strong>⋮</strong> (top-right).</span></li>
        <li><span class="levix-install-step-num">2</span><span>Tap <strong>Add to Home screen</strong> (see blue highlight above).</span></li>
        <li><span class="levix-install-step-num">3</span><span>Tap <strong>Add</strong> — done! Open LEVIX from your home screen.</span></li>
      </ol>`;
  }

  function progressBlockHtml() {
    return `
      <ul class="levix-install-progress" data-levix-progress>
        ${progressRow("secure", "Secure connection", "active")}
        ${progressRow("files", "App icon & manifest", "pending")}
        ${progressRow("worker", "Offline support", "pending")}
        ${progressRow("ready", "Ready to add", "pending")}
      </ul>
      <p class="levix-install-status-text" data-levix-install-status>Starting…</p>`;
  }

  function googleAppBlockHtml() {
    return `
      ${browserBadgeHtml()}
      <p class="levix-install-note">The <strong>Google app</strong> cannot install LEVIX. You must open this site in <strong>Google Chrome</strong>.</p>
      <button type="button" class="levix-open-chrome-btn" data-levix-open-chrome>Open in Google Chrome</button>
      <button type="button" class="levix-install-cta is-secondary" data-levix-copy-url>Copy link for Chrome</button>
      <p class="levix-install-note">Or install from Chrome: <strong>⋮ → Add to Home screen</strong></p>`;
  }

  async function waitForServiceWorker(timeoutMs) {
    if (!("serviceWorker" in navigator)) return false;
    try {
      if (window.__levixSwReady) {
        await Promise.race([window.__levixSwReady, delay(timeoutMs)]);
      }
      if (navigator.serviceWorker.controller) return true;
      await Promise.race([navigator.serviceWorker.ready, delay(timeoutMs)]);
      return Boolean(navigator.serviceWorker.controller);
    } catch (_) {
      return Boolean(navigator.serviceWorker.controller);
    }
  }

  async function verifyInstallAssets() {
    try {
      const res = await fetch("/manifest.webmanifest", { cache: "no-store" });
      if (!res.ok) return false;
      const manifest = await res.json();
      const icons = (manifest.icons || []).filter((i) => /192|512/.test(String(i.sizes)));
      for (const icon of icons.slice(0, 2)) {
        const p = new URL(icon.src, window.location.origin).pathname;
        const ir = await fetch(p, { cache: "no-store" });
        if (!ir.ok) return false;
      }
      return true;
    } catch (_) {
      return false;
    }
  }

  async function runProgressPhase(container) {
    const platform = isIOS ? "ios" : "android";
    if (!isSecure) {
      container.innerHTML = `
        <div class="levix-install-card">
          ${browserBadgeHtml()}
          <p class="levix-install-note">Open <strong>https://levixapp.in</strong> (secure lock icon), then try again.</p>
        </div>`;
      return;
    }

    if (needsChrome) {
      container.innerHTML = `<div class="levix-install-card">${googleAppBlockHtml()}</div>`;
      bindGoogleAppActions(container);
      return;
    }

    container.innerHTML = `
      <div class="levix-install-card" data-levix-phase="progress">
        ${browserBadgeHtml()}
        <p class="levix-install-note" style="margin-top:0">Preparing install — <strong>LEVIX UI only</strong> (not Play Store).</p>
        ${progressBlockHtml()}
      </div>`;

    await delay(150);
    updateProgressStep("secure", "done", "Secure connection");
    setStatusText("Loading app files…");
    updateProgressStep("files", "active");

    const filesOk = await verifyInstallAssets();
    updateProgressStep("files", filesOk ? "done" : "error", filesOk ? "App icon & manifest" : "Files unavailable");
    if (!filesOk) {
      setStatusText("Check connection — showing manual steps…");
      await delay(800);
    } else {
      setStatusText("Enabling offline support…");
      updateProgressStep("worker", "active");
      const workerOk = await waitForServiceWorker(5000);
      updateProgressStep("worker", workerOk ? "done" : "error", workerOk ? "Offline support ready" : "Offline optional");
    }

    updateProgressStep("ready", "done", "Ready to add");
    setStatusText("Opening install guide…");
    await delay(500);

    container.innerHTML = `
      <div class="levix-install-card" data-levix-phase="guide">
        ${browserBadgeHtml()}
        <p style="margin:0 0 8px;font-weight:700;font-size:0.95rem">Follow these steps in Chrome</p>
        ${guideStepsHtml(platform)}
        <p class="levix-install-note">This adds LEVIX to your home screen — no download from Play Store. If Chrome popup appeared before, ignore it and use the menu steps above.</p>
      </div>
      <div class="levix-install-panel-actions">
        <button type="button" class="levix-install-cta" data-levix-finish>Done — I added it</button>
        <a href="/" class="levix-install-cta is-secondary" style="text-decoration:none;text-align:center">Back to website</a>
      </div>`;

    container.querySelector("[data-levix-finish]")?.addEventListener("click", () => {
      try {
        localStorage.setItem("levix-install-complete", "1");
      } catch (_) {}
      window.location.href = "/login";
    });
  }

  function bindGoogleAppActions(root) {
    root.querySelector("[data-levix-open-chrome]")?.addEventListener("click", () => {
      window.location.href = chromeIntentUrl();
    });
    root.querySelector("[data-levix-copy-url]")?.addEventListener("click", async () => {
      const url = `https://${window.location.host}/install-app`;
      try {
        await navigator.clipboard.writeText(url);
        setStatusText("Link copied — paste in Chrome");
      } catch (_) {
        prompt("Copy this link and open in Chrome:", url);
      }
    });
  }

  function renderFullPage() {
    const root = document.getElementById(PAGE_ROOT_ID);
    if (!root) return;

    const platform = isIOS ? "ios" : "android";
    const startLabel = needsChrome ? "Open in Chrome first" : "Start install";

    root.innerHTML = `
      <div class="levix-install-brand">
        <img src="/static/icons/icon-192.png" width="72" height="72" alt="LEVIX">
        <h1>Install LEVIX</h1>
        <p>Add to your home screen — works in <strong>Chrome</strong> (Android) or <strong>Safari</strong> (iPhone).</p>
      </div>
      <div id="levix-install-dynamic"></div>
      <div class="levix-install-card" id="levix-install-start-card">
        ${browserBadgeHtml()}
        <button type="button" class="levix-install-cta" id="levix-start-install">${escapeHtml(startLabel)}</button>
        ${needsChrome ? googleAppBlockHtml() : ""}
      </div>
      <a href="/" class="levix-install-back-link">← Back to website</a>`;

    if (needsChrome) {
      bindGoogleAppActions(root);
      document.getElementById("levix-start-install")?.setAttribute("disabled", "true");
    }

    const startBtn = document.getElementById("levix-start-install");
    const dynamic = document.getElementById("levix-install-dynamic");
    const startCard = document.getElementById("levix-install-start-card");

    startBtn?.addEventListener("click", async () => {
      if (needsChrome) return;
      startBtn.disabled = true;
      startCard.style.display = "none";
      await runProgressPhase(dynamic);
    });

    const params = new URLSearchParams(window.location.search);
    if (params.get("start") === "1" && !needsChrome) {
      startBtn?.click();
    }
  }

  function setupNavButtons() {
    if (isStandalone) {
      document.querySelectorAll(INSTALL_BTN_SELECTOR).forEach((el) => {
        el.setAttribute("hidden", "");
      });
      return;
    }

    document.querySelectorAll(INSTALL_BTN_SELECTOR).forEach((el) => {
      el.removeAttribute("hidden");
      const label = isIOS || isAndroid ? "Add to Home Screen" : "Install App";
      if (el.tagName === "A") {
        el.setAttribute("href", `${getInstallUrl()}&start=1`);
        el.textContent = label;
      } else {
        el.textContent = label;
      }

      el.addEventListener("click", (event) => {
        if (document.getElementById(PAGE_ROOT_ID)) return;
        const onInstallPage = window.location.pathname === "/install-app";
        if (onInstallPage) return;

        if (el.tagName === "A") return;

        event.preventDefault();
        window.location.href = `${getInstallUrl()}&start=1`;
      });
    });
  }

  function suppressNativeChromeInstall() {
    window.addEventListener(
      "beforeinstallprompt",
      (event) => {
        event.preventDefault();
        event.stopImmediatePropagation();
      },
      { capture: true }
    );
  }

  function init() {
    suppressNativeChromeInstall();

    if (document.getElementById(PAGE_ROOT_ID)) {
      renderFullPage();
      return;
    }

    setupNavButtons();

    window.addEventListener("appinstalled", () => {
      document.querySelectorAll(INSTALL_BTN_SELECTOR).forEach((el) => el.setAttribute("hidden", ""));
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();
