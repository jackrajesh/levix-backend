/**
 * LEVIX PWA install wizard.
 * Android: manual "Add to Home screen" only (avoids broken Play/WebAPK download flow).
 * iOS: Safari manual steps. Desktop: optional native prompt with timeout.
 */
(() => {
  const INSTALL_BTN_ID = "install-app-btn";
  const SHEET_ID = "levix-install-sheet";
  const STORAGE_KEY = "levix-install-prefer-manual";

  const ua = navigator.userAgent || "";
  const isIOS =
    /iPad|iPhone|iPod/.test(ua) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  const isAndroid = /Android/i.test(ua);
  const isMobile = isIOS || isAndroid || window.innerWidth <= 768;
  const isStandalone =
    window.matchMedia("(display-mode: standalone)").matches ||
    window.navigator.standalone === true;
  const isInAppBrowser =
    /Instagram|FBAN|FBAV|Twitter|LinkedInApp|Snapchat|Line\//i.test(ua) ||
    (isAndroid && /\bwv\b/.test(ua));
  const isSecure = window.isSecureContext === true;

  /** Never use Chrome WebAPK prompt on Android — it often hangs on "Preparing download" / Play Games. */
  const USE_NATIVE_PROMPT = !isAndroid && !isIOS;

  let deferredInstallPrompt = null;
  let wizardOpen = false;
  let abortWizard = false;

  function getInstallBtn() {
    return document.getElementById(INSTALL_BTN_ID);
  }

  function hideInstallBtn(btn) {
    if (!btn) return;
    btn.hidden = true;
    btn.setAttribute("aria-hidden", "true");
    btn.disabled = false;
  }

  function showInstallBtn(btn, label) {
    if (!btn) return;
    btn.hidden = false;
    btn.removeAttribute("aria-hidden");
    btn.disabled = false;
    if (label) btn.textContent = label;
  }

  function forceCleanup() {
    wizardOpen = false;
    abortWizard = false;
    document.body.classList.remove("levix-install-sheet-open");
    const sheet = document.getElementById(SHEET_ID);
    if (sheet) sheet.remove();
    const btn = getInstallBtn();
    if (btn) {
      btn.disabled = false;
      btn.removeAttribute("aria-busy");
      if (btn.dataset.prevLabel) {
        btn.textContent = btn.dataset.prevLabel;
        delete btn.dataset.prevLabel;
      }
    }
  }

  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function renderSheet({ title, bodyHtml, footerHtml }) {
    forceCleanup();
    wizardOpen = true;

    const sheet = document.createElement("div");
    sheet.id = SHEET_ID;
    sheet.className = "levix-install-sheet";
    sheet.setAttribute("role", "dialog");
    sheet.setAttribute("aria-modal", "true");
    sheet.setAttribute("aria-labelledby", "levix-install-sheet-title");

    sheet.innerHTML = `
      <div class="levix-install-sheet-backdrop" data-levix-close="1" aria-hidden="true"></div>
      <div class="levix-install-sheet-panel">
        <header class="levix-install-sheet-header">
          <h2 id="levix-install-sheet-title">${escapeHtml(title)}</h2>
          <button type="button" class="levix-install-sheet-x" data-levix-close="1" aria-label="Close">×</button>
        </header>
        <div class="levix-install-sheet-body">${bodyHtml}</div>
        ${footerHtml ? `<footer class="levix-install-sheet-footer">${footerHtml}</footer>` : ""}
      </div>
    `;

    sheet.addEventListener("click", (event) => {
      const t = event.target;
      if (t instanceof HTMLElement && t.dataset.levixClose === "1") {
        forceCleanup();
      }
    });

    document.addEventListener(
      "keydown",
      function onKey(event) {
        if (event.key === "Escape") {
          forceCleanup();
          document.removeEventListener("keydown", onKey);
        }
      },
      { once: true }
    );

    document.body.appendChild(sheet);
    document.body.classList.add("levix-install-sheet-open");
    return sheet;
  }

  function progressRow(id, label, state) {
    const icons = {
      pending: '<span class="levix-ip-dot"></span>',
      active: '<span class="levix-ip-spinner" aria-hidden="true"></span>',
      done: '<span class="levix-ip-check" aria-hidden="true">✓</span>',
      error: '<span class="levix-ip-error" aria-hidden="true">!</span>',
    };
    return `<li class="levix-install-progress-item is-${state}" data-step="${id}">
      <span class="levix-install-progress-icon">${icons[state] || icons.pending}</span>
      <span class="levix-install-progress-label">${escapeHtml(label)}</span>
    </li>`;
  }

  function updateProgressStep(stepId, state, label) {
    const item = document.querySelector(`[data-step="${stepId}"]`);
    if (!item) return;
    item.className = `levix-install-progress-item is-${state}`;
    const icon = item.querySelector(".levix-install-progress-icon");
    if (icon) {
      const icons = {
        pending: '<span class="levix-ip-dot"></span>',
        active: '<span class="levix-ip-spinner" aria-hidden="true"></span>',
        done: '<span class="levix-ip-check" aria-hidden="true">✓</span>',
        error: '<span class="levix-ip-error" aria-hidden="true">!</span>',
      };
      icon.innerHTML = icons[state] || icons.pending;
    }
    if (label) {
      const labelEl = item.querySelector(".levix-install-progress-label");
      if (labelEl) labelEl.textContent = label;
    }
  }

  function showProgressWizard() {
    const bodyHtml = `
      <p class="levix-install-lead">Setting up home screen install. This is <strong>not</strong> a Play Store download.</p>
      <ul class="levix-install-progress" id="levix-install-progress">
        ${progressRow("secure", "Secure connection", "active")}
        ${progressRow("files", "App icon & manifest", "pending")}
        ${progressRow("worker", "Offline support", "pending")}
        ${progressRow("ready", "Ready to add", "pending")}
      </ul>
      <p class="levix-install-status" id="levix-install-status">Checking…</p>
    `;
    const footerHtml = `<button type="button" class="levix-install-btn-secondary" data-levix-close="1">Cancel</button>`;
    renderSheet({ title: "Preparing install", bodyHtml, footerHtml });
  }

  function showManualWizard(platform) {
    const isApple = platform === "ios";
    const steps = isApple
      ? [
          "Open this page in <strong>Safari</strong> (required on iPhone).",
          "Tap <strong>Share</strong> at the bottom of Safari.",
          "Tap <strong>Add to Home Screen</strong>.",
          "Tap <strong>Add</strong> — LEVIX appears on your home screen.",
        ]
      : [
          "Stay in <strong>Google Chrome</strong> (not Play Store / Games).",
          "Tap <strong>⋮</strong> (three dots) top-right.",
          "Tap <strong>Add to Home screen</strong> or <strong>Install app</strong>.",
          "Tap <strong>Add</strong> or <strong>Install</strong> — check your home screen for the LEVIX icon.",
        ];

    const stepsHtml = steps
      .map(
        (s, i) =>
          `<li><span class="levix-install-step-num">${i + 1}</span><span>${s}</span></li>`
      )
      .join("");

    const note = isApple
      ? "No Play Store needed. This creates a home screen shortcut that opens LEVIX like an app."
      : "If you saw “Preparing download” or Play Games before: ignore that. Use Chrome menu → Add to Home screen instead — it works reliably.";

    const bodyHtml = `
      <div class="levix-install-success-banner">✓ Ready — follow these steps</div>
      <ol class="levix-install-steps">${stepsHtml}</ol>
      <p class="levix-install-note">${note}</p>
      <p class="levix-install-note levix-install-warning">Still stuck? Remove any old LEVIX shortcut, then try again.</p>
    `;
    const footerHtml = `<button type="button" class="levix-install-btn-primary" data-levix-close="1">Got it</button>`;
    renderSheet({
      title: isApple ? "Add to Home Screen" : "Add LEVIX to Home Screen",
      bodyHtml,
      footerHtml,
    });
  }

  function showBlockedWizard(reason) {
    const messages = {
      inapp: {
        title: "Open in Chrome or Safari",
        steps: [
          "You are inside Instagram, Facebook, or another in-app browser.",
          "Tap ⋮ menu → <strong>Open in Chrome</strong> or <strong>Open in browser</strong>.",
          "Return here and tap Add to Home Screen again.",
        ],
      },
      insecure: {
        title: "HTTPS required",
        steps: [
          "Open <strong>https://levixapp.in</strong> (lock icon in the address bar).",
          "Do not use http:// or a saved offline copy.",
        ],
      },
    };
    const block = messages[reason] || messages.inapp;
    const stepsHtml = block.steps
      .map(
        (s, i) =>
          `<li><span class="levix-install-step-num">${i + 1}</span><span>${s}</span></li>`
      )
      .join("");
    renderSheet({
      title: block.title,
      bodyHtml: `<ol class="levix-install-steps">${stepsHtml}</ol>`,
      footerHtml: `<button type="button" class="levix-install-btn-primary" data-levix-close="1">OK</button>`,
    });
  }

  function delay(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
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
      const manifestRes = await fetch("/manifest.webmanifest", { cache: "no-store" });
      if (!manifestRes.ok) return false;
      const manifest = await manifestRes.json();
      const icons = (manifest.icons || []).filter((icon) => {
        const s = String(icon.sizes || "");
        return s.includes("192") || s.includes("512");
      });
      for (const icon of icons.slice(0, 2)) {
        const path = new URL(icon.src, window.location.origin).pathname;
        const res = await fetch(path, { cache: "no-store" });
        if (!res.ok) return false;
      }
      return true;
    } catch (_) {
      return false;
    }
  }

  function setStatus(text) {
    const el = document.getElementById("levix-install-status");
    if (el) el.textContent = text;
  }

  async function runPrepareWizard(platform) {
    abortWizard = false;
    showProgressWizard();

    const step = async (id, fn, okLabel, failLabel) => {
      if (abortWizard) return false;
      updateProgressStep(id, "active");
      setStatus(okLabel || "Working…");
      const ok = await fn();
      if (abortWizard) return false;
      updateProgressStep(id, ok ? "done" : "error", ok ? okLabel : failLabel);
      return ok;
    };

    await delay(200);

    const secureOk = isSecure;
    updateProgressStep("secure", secureOk ? "done" : "error", secureOk ? "Secure connection" : "Not secure");
    if (!secureOk) {
      setStatus("Use https://levixapp.in");
      await delay(1200);
      forceCleanup();
      showBlockedWizard("insecure");
      return;
    }

    const filesOk = await step(
      "files",
      verifyInstallAssets,
      "App icon & manifest",
      "Could not load install files"
    );
    if (!filesOk) {
      setStatus("Check internet, then try again");
      await delay(1500);
      forceCleanup();
      showManualWizard(platform);
      return;
    }

    const workerOk = await step(
      "worker",
      () => waitForServiceWorker(6000),
      "Offline support ready",
      "Still loading (you can install anyway)"
    );

    updateProgressStep("ready", "done", "Ready to add");
    setStatus(workerOk ? "All set — opening steps…" : "Opening manual steps…");
    await delay(600);

    forceCleanup();
    showManualWizard(platform);
  }

  async function tryDesktopNativePrompt(installBtn) {
    if (!deferredInstallPrompt || !USE_NATIVE_PROMPT) return false;

    showProgressWizard();
    updateProgressStep("secure", "done", "Secure connection");
    updateProgressStep("files", "done", "App icon & manifest");
    updateProgressStep("worker", "done", "Offline support ready");
    updateProgressStep("ready", "active", "Opening install dialog…");
    setStatus("Confirm in the browser popup…");

    let outcome = "dismissed";
    try {
      const promptPromise = deferredInstallPrompt.prompt();
      const timeoutPromise = delay(25000).then(() => "timeout");
      await Promise.race([promptPromise, timeoutPromise]);
      const choice = await Promise.race([
        deferredInstallPrompt.userChoice,
        delay(5000).then(() => ({ outcome: "dismissed" })),
      ]);
      outcome = choice?.outcome || "dismissed";
    } catch (_) {
      outcome = "error";
    }

    deferredInstallPrompt = null;
    forceCleanup();

    if (outcome === "accepted") {
      hideInstallBtn(installBtn);
      return true;
    }
    return false;
  }

  async function onInstallClick(installBtn) {
    if (wizardOpen) return;

    if (isInAppBrowser) {
      showBlockedWizard("inapp");
      return;
    }
    if (!isSecure) {
      showBlockedWizard("insecure");
      return;
    }

    installBtn.dataset.prevLabel = installBtn.textContent;
    installBtn.disabled = true;
    installBtn.setAttribute("aria-busy", "true");

    try {
      if (isIOS) {
        await runPrepareWizard("ios");
        return;
      }

      if (isAndroid || isMobile) {
        try {
          localStorage.setItem(STORAGE_KEY, "1");
        } catch (_) {}
        await runPrepareWizard("android");
        return;
      }

      const nativeOk = await tryDesktopNativePrompt(installBtn);
      if (!nativeOk) {
        await runPrepareWizard("android");
      }
    } finally {
      installBtn.disabled = false;
      installBtn.removeAttribute("aria-busy");
      if (installBtn.dataset.prevLabel) {
        installBtn.textContent = installBtn.dataset.prevLabel;
        delete installBtn.dataset.prevLabel;
      }
    }
  }

  function init() {
    const installBtn = getInstallBtn();
    if (!installBtn) return;

    if (isStandalone) {
      hideInstallBtn(installBtn);
      return;
    }

    const defaultLabel = isMobile ? "Add to Home Screen" : "Install App";
    showInstallBtn(installBtn, defaultLabel);

    window.addEventListener("beforeinstallprompt", (event) => {
      if (!USE_NATIVE_PROMPT) return;
      event.preventDefault();
      deferredInstallPrompt = event;
      showInstallBtn(installBtn, defaultLabel);
    });

    window.addEventListener("appinstalled", () => {
      deferredInstallPrompt = null;
      hideInstallBtn(installBtn);
      forceCleanup();
    });

    installBtn.addEventListener("click", () => onInstallClick(installBtn));

    window.addEventListener("pagehide", forceCleanup);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();
