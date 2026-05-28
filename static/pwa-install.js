/**
 * LEVIX PWA install helper — Android Chrome + iOS Safari + desktop.
 */
(() => {
  const INSTALL_BTN_ID = "install-app-btn";
  const MODAL_ID = "levix-install-modal";
  const STORAGE_INSTALLED = "levix-pwa-installed";

  const isStandalone =
    window.matchMedia("(display-mode: standalone)").matches ||
    window.navigator.standalone === true;

  const ua = navigator.userAgent || "";
  const isIOS =
    /iPad|iPhone|iPod/.test(ua) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  const isAndroid = /Android/i.test(ua);
  const isMobile = isIOS || isAndroid || window.innerWidth <= 768;

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
      btn.textContent = "Installing…";
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
      .map((step, i) => `<li><span class="levix-install-step-num">${i + 1}</span><span>${step}</span></li>`)
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

  function showIOSInstructions() {
    openModal(
      "Add LEVIX to your Home Screen",
      [
        "Open this site in <strong>Safari</strong> (Chrome on iPhone cannot install apps to the home screen).",
        "Tap the <strong>Share</strong> button at the bottom of Safari.",
        "Scroll and tap <strong>Add to Home Screen</strong>.",
        "Tap <strong>Add</strong> in the top-right corner.",
      ],
      "After adding, open LEVIX from your home screen like any other app."
    );
  }

  function showAndroidManualInstructions() {
    openModal(
      "Install LEVIX on your phone",
      [
        "Make sure you are on <strong>https://levixapp.in</strong> (not http).",
        "Tap the browser <strong>menu</strong> (three dots, top-right).",
        "Tap <strong>Install app</strong> or <strong>Add to Home screen</strong>.",
        "Confirm when prompted — the icon should appear on your home screen.",
      ],
      "If you already tried installing, remove the old LEVIX shortcut first, then install again."
    );
  }

  function showInsecureContextHelp() {
    openModal(
      "Install requires a secure connection",
      [
        "Open <strong>https://levixapp.in</strong> in your browser.",
        "Do not use http:// or a local IP address on your phone.",
        "Then tap Install App again.",
      ],
      "PWAs can only be installed over HTTPS."
    );
  }

  async function cleanupLegacyServiceWorkers() {
    if (!("serviceWorker" in navigator)) return;
    try {
      const registrations = await navigator.serviceWorker.getRegistrations();
      await Promise.all(
        registrations.map((registration) => {
          const scope = registration.scope || "";
          if (scope.includes("/static/")) {
            return registration.unregister();
          }
          return Promise.resolve();
        })
      );
    } catch (_) {
      // Non-fatal.
    }
  }

  async function registerRootServiceWorker() {
    if (!("serviceWorker" in navigator)) return false;
    try {
      await cleanupLegacyServiceWorkers();
      const registration = await navigator.serviceWorker.register("/sw.js", {
        scope: "/",
        updateViaCache: "none",
      });
      if (registration.waiting) {
        registration.waiting.postMessage({ type: "SKIP_WAITING" });
      }
      return true;
    } catch (_) {
      return false;
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

    // On phones, always show the CTA — iOS never fires beforeinstallprompt.
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
      try {
        localStorage.setItem(STORAGE_INSTALLED, "1");
      } catch (_) {}
      hideInstallBtn(installBtn);
      closeModal();
    });

    try {
      if (localStorage.getItem(STORAGE_INSTALLED) === "1" && !deferredInstallPrompt) {
        // User installed before; keep button available on mobile in case they removed the icon.
        if (!isMobile) hideInstallBtn(installBtn);
      }
    } catch (_) {}

    installBtn.addEventListener("click", async () => {
      if (!isSecure) {
        showInsecureContextHelp();
        return;
      }

      if (isIOS) {
        showIOSInstructions();
        return;
      }

      if (deferredInstallPrompt) {
        setBtnLoading(installBtn, true);
        try {
          await deferredInstallPrompt.prompt();
          const choice = await deferredInstallPrompt.userChoice;
          deferredInstallPrompt = null;
          if (choice && choice.outcome === "accepted") {
            hideInstallBtn(installBtn);
          } else {
            showInstallBtn(installBtn, defaultLabel);
            if (isAndroid) showAndroidManualInstructions();
          }
        } catch (_) {
          showInstallBtn(installBtn, defaultLabel);
          if (isAndroid) showAndroidManualInstructions();
        } finally {
          setBtnLoading(installBtn, false);
        }
        return;
      }

      if (isAndroid) {
        showAndroidManualInstructions();
        return;
      }

      // Desktop without deferred prompt (Safari, Firefox, etc.)
      openModal(
        "Install LEVIX",
        [
          "Look for an install icon in the address bar, or",
          "Open the browser menu and choose <strong>Install LEVIX</strong> or <strong>Install app</strong>.",
        ],
        "If you do not see an install option, try Chrome or Edge on desktop."
      );
    });

    registerRootServiceWorker();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();
