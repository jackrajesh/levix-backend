/**
 * LEVIX PWA install — permanent mobile + desktop flow.
 * Install does NOT require camera/location permissions.
 */
(() => {
  const INSTALL_BTN_ID = "install-app-btn";
  const MODAL_ID = "levix-install-modal";

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

  function getInstallBtn() {
    return document.getElementById(INSTALL_BTN_ID);
  }

  function hideInstallBtn(btn) {
    if (!btn) return;
    btn.hidden = true;
    btn.setAttribute("aria-hidden", "true");
  }

  function showInstallBtn(btn, label) {
    if (!btn) return;
    btn.hidden = false;
    btn.removeAttribute("aria-hidden");
    btn.disabled = false;
    if (label) btn.textContent = label;
  }

  function setBtnLoading(btn, loading) {
    if (!btn) return;
    btn.disabled = loading;
    btn.setAttribute("aria-busy", loading ? "true" : "false");
    if (loading) {
      btn.dataset.prevLabel = btn.textContent;
      btn.textContent = "Preparing install…";
    } else if (btn.dataset.prevLabel) {
      btn.textContent = btn.dataset.prevLabel;
      delete btn.dataset.prevLabel;
    }
  }

  function closeModal() {
    const modal = document.getElementById(MODAL_ID);
    if (modal) modal.remove();
    document.body.classList.remove("levix-install-modal-open");
  }

  function openModal(title, steps, note) {
    closeModal();
    const modal = document.createElement("div");
    modal.id = MODAL_ID;
    modal.className = "levix-install-modal";
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    modal.setAttribute("aria-labelledby", "levix-install-modal-title");

    const stepsHtml = steps
      .map(
        (step, i) =>
          `<li><span class="levix-install-step-num">${i + 1}</span><span>${step}</span></li>`
      )
      .join("");

    modal.innerHTML = `
      <div class="levix-install-backdrop" data-close="1"></div>
      <div class="levix-install-panel">
        <button type="button" class="levix-install-close" aria-label="Close" data-close="1">&times;</button>
        <h2 id="levix-install-modal-title">${title}</h2>
        <ol class="levix-install-steps">${stepsHtml}</ol>
        ${note ? `<p class="levix-install-note">${note}</p>` : ""}
        <button type="button" class="levix-install-done" data-close="1">Got it</button>
      </div>
    `;

    modal.addEventListener("click", (event) => {
      const target = event.target;
      if (target instanceof HTMLElement && target.dataset.close === "1") {
        closeModal();
      }
    });

    document.body.appendChild(modal);
    document.body.classList.add("levix-install-modal-open");
  }

  function showInAppBrowserHelp() {
    openModal(
      "Open in Chrome or Safari first",
      [
        "You opened LEVIX inside another app (Instagram, Facebook, etc.).",
        "Tap the <strong>menu (⋮)</strong> and choose <strong>Open in Chrome</strong> or <strong>Open in browser</strong>.",
        "Then install from Chrome (Android) or Safari (iPhone).",
      ],
      "In-app browsers cannot install apps to your home screen."
    );
  }

  function showIOSInstructions() {
    openModal(
      "Add LEVIX to Home Screen (iPhone/iPad)",
      [
        "Use <strong>Safari</strong> — Chrome on iPhone cannot add real home screen apps.",
        "Tap <strong>Share</strong> (square with arrow) at the bottom.",
        "Scroll down and tap <strong>Add to Home Screen</strong>.",
        "Tap <strong>Add</strong> (top right).",
      ],
      "LEVIX will appear on your home screen like a normal app. No extra permissions are required."
    );
  }

  function showAndroidManualInstructions(extraNote) {
    openModal(
      "Install LEVIX on Android",
      [
        "Use <strong>Google Chrome</strong> (recommended).",
        "Open <strong>https://levixapp.in</strong> (must show a lock icon).",
        "Tap <strong>⋮ Menu</strong> → <strong>Install app</strong> or <strong>Add to Home screen</strong>.",
        "Confirm — wait until the icon appears on your home screen.",
      ],
      extraNote ||
        "If install spins forever: sign into Google Play Store, remove any old LEVIX shortcut, then try again. Settings → Apps → Chrome → Install unknown apps (allow)."
    );
  }

  function showInsecureHelp() {
    openModal(
      "Secure connection required",
      [
        "Open <strong>https://levixapp.in</strong> (with the lock icon).",
        "Do not use http:// or a local IP on your phone.",
      ],
      "PWAs install only over HTTPS. No special permission popup is needed for install."
    );
  }

  async function waitForServiceWorker(timeoutMs) {
    if (!("serviceWorker" in navigator)) return false;
    const start = Date.now();
    try {
      if (window.__levixSwReady) {
        await Promise.race([
          window.__levixSwReady,
          new Promise((resolve) => setTimeout(resolve, timeoutMs)),
        ]);
      }
      if (navigator.serviceWorker.controller) return true;
      await Promise.race([
        navigator.serviceWorker.ready,
        new Promise((resolve) => setTimeout(resolve, timeoutMs)),
      ]);
      return Boolean(navigator.serviceWorker.controller);
    } catch (_) {
      return Date.now() - start < timeoutMs && Boolean(navigator.serviceWorker.controller);
    }
  }

  async function verifyInstallAssets() {
    try {
      const manifestRes = await fetch("/manifest.webmanifest", { cache: "no-store" });
      if (!manifestRes.ok) return { ok: false, reason: "manifest" };
      const manifest = await manifestRes.json();
      const icons = Array.isArray(manifest.icons) ? manifest.icons : [];
      const required = icons.filter((icon) => {
        const sizes = String(icon.sizes || "");
        return sizes.includes("192") || sizes.includes("512");
      });
      for (const icon of required.slice(0, 2)) {
        const iconPath = (() => {
          try {
            return new URL(icon.src, window.location.origin).pathname;
          } catch (_) {
            return icon.src;
          }
        })();
        const iconRes = await fetch(iconPath, { cache: "no-store" });
        if (!iconRes.ok) return { ok: false, reason: "icon" };
      }
      return { ok: true };
    } catch (_) {
      return { ok: false, reason: "network" };
    }
  }

  function init() {
    const installBtn = getInstallBtn();
    if (!installBtn) return;

    if (isStandalone) {
      hideInstallBtn(installBtn);
      return;
    }

    let deferredInstallPrompt = null;
    const defaultLabel = isMobile ? "Add to Home Screen" : "Install App";
    installBtn.textContent = defaultLabel;

    if (isMobile) {
      showInstallBtn(installBtn, defaultLabel);
    }

    window.addEventListener("beforeinstallprompt", (event) => {
      event.preventDefault();
      deferredInstallPrompt = event;
      showInstallBtn(installBtn, defaultLabel);
    });

    window.addEventListener("appinstalled", () => {
      deferredInstallPrompt = null;
      hideInstallBtn(installBtn);
      closeModal();
    });

    installBtn.addEventListener("click", async () => {
      if (isInAppBrowser) {
        showInAppBrowserHelp();
        return;
      }

      if (!isSecure) {
        showInsecureHelp();
        return;
      }

      if (isIOS) {
        showIOSInstructions();
        return;
      }

      setBtnLoading(installBtn, true);

      const swReady = await waitForServiceWorker(8000);
      const assets = await verifyInstallAssets();

      if (!swReady || !assets.ok) {
        setBtnLoading(installBtn, false);
        showAndroidManualInstructions(
          !swReady
            ? "App worker is still loading. Use Chrome menu → Install app, or refresh and try again."
            : "Install files could not be verified. Check your connection and use Chrome menu → Install app."
        );
        return;
      }

      if (deferredInstallPrompt) {
        try {
          await deferredInstallPrompt.prompt();
          const choice = await deferredInstallPrompt.userChoice;
          deferredInstallPrompt = null;
          setBtnLoading(installBtn, false);
          if (choice && choice.outcome === "accepted") {
            hideInstallBtn(installBtn);
            return;
          }
          showAndroidManualInstructions(
            "Install was cancelled or blocked. Use Chrome ⋮ menu → Install app. Ensure Google Play Store is signed in."
          );
          return;
        } catch (_) {
          deferredInstallPrompt = null;
          setBtnLoading(installBtn, false);
          showAndroidManualInstructions();
          return;
        }
      }

      setBtnLoading(installBtn, false);
      if (isAndroid) {
        showAndroidManualInstructions(
          "If the button does not open install: Chrome ⋮ → Install app. This does not need camera or location permission."
        );
        return;
      }

      openModal(
        "Install LEVIX",
        [
          "Use Chrome or Edge.",
          "Click the install icon in the address bar, or open the browser menu → <strong>Install LEVIX</strong>.",
        ],
        "No extra permissions are required to install."
      );
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();
