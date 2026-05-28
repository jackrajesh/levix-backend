/**
 * LEVIX dashboard mobile CRM — list/chat single-pane navigation.
 */
(() => {
  const MOBILE_BP = 768;

  function isMobile() {
    return window.innerWidth <= MOBILE_BP;
  }

  function getPanes() {
    return {
      list: document.getElementById("crm-sidebar"),
      workspace: document.getElementById("crm-workspace"),
    };
  }

  function showList() {
    const { list, workspace } = getPanes();
    if (!list || !workspace) return;
    list.classList.remove("is-hidden");
    workspace.classList.remove("is-active");
  }

  function showWorkspace() {
    const { list, workspace } = getPanes();
    if (!list || !workspace) return;
    if (!isMobile()) return;
    list.classList.add("is-hidden");
    workspace.classList.add("is-active");
  }

  function resetForViewport() {
    const { list, workspace } = getPanes();
    if (!list || !workspace) return;
    if (isMobile()) {
      if (workspace.classList.contains("is-active")) {
        list.classList.add("is-hidden");
      } else {
        list.classList.remove("is-hidden");
        workspace.classList.remove("is-active");
      }
    } else {
      list.classList.remove("is-hidden");
      workspace.classList.remove("is-active");
    }
  }

  function closeSidebarOnNavClick() {
    document.querySelectorAll(".sidebar .nav-item").forEach((item) => {
      item.addEventListener("click", () => {
        if (!isMobile()) return;
        const sidebar = document.getElementById("sidebar");
        const overlay = document.getElementById("sidebar-overlay");
        if (sidebar) sidebar.classList.remove("active");
        if (overlay) overlay.classList.remove("active");
      });
    });
  }

  function initFilterScroll() {
    document.querySelectorAll(".crm-filters-scroll").forEach((el) => {
      el.addEventListener(
        "wheel",
        (e) => {
          if (Math.abs(e.deltaY) < Math.abs(e.deltaX)) return;
          if (el.scrollWidth <= el.clientWidth) return;
          el.scrollLeft += e.deltaY;
          e.preventDefault();
        },
        { passive: false }
      );
    });
  }

  window.LevixMobileCrm = {
    isMobile,
    showList,
    showWorkspace,
    resetForViewport,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      resetForViewport();
      closeSidebarOnNavClick();
      initFilterScroll();
    });
  } else {
    resetForViewport();
    closeSidebarOnNavClick();
    initFilterScroll();
  }

  let resizeTimer;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(resetForViewport, 120);
  });
})();
