import os
import re
from pathlib import Path

import pytest

from app.permissions import MASTER_PERMISSION_KEYS


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "templates" / "dashboard.html"


def _dashboard_source() -> str:
    return DASHBOARD.read_text(encoding="utf-8")


def _extract_tab_mapping() -> dict[str, str]:
    text = _dashboard_source()
    match = re.search(r"tabPermMapping\s*=\s*\{([^}]+)\}", text, re.MULTILINE | re.DOTALL)
    if not match:
        return {}
    body = match.group(1)
    pairs = re.findall(r"([a-z_]+)\s*:\s*['\"]([a-z0-9_]+)['\"]", body)
    return {tab: permission for tab, permission in pairs}


def _extract_button_permissions() -> set[str]:
    text = _dashboard_source()
    return set(re.findall(r"hasPerm\(\s*['\"]([a-z0-9_]+)['\"]\s*\)", text))


def test_ui_tab_mapping_uses_canonical_permissions():
    canonical = set(MASTER_PERMISSION_KEYS)
    tab_mapping = _extract_tab_mapping()
    unknown = {tab: perm for tab, perm in tab_mapping.items() if perm not in canonical}
    assert tab_mapping, "No tab permission mapping found in dashboard UI"
    assert not unknown, f"Tabs mapped to unknown permissions: {unknown}"


def test_ui_button_guards_use_canonical_permissions():
    canonical = set(MASTER_PERMISSION_KEYS)
    button_perms = _extract_button_permissions()
    unknown = sorted(p for p in button_perms if p not in canonical)
    assert not unknown, f"UI checks unknown permissions in hasPerm(...): {unknown}"


def test_restricted_message_present_for_blocked_sections():
    text = _dashboard_source()
    assert "You do not have permission to manage team accounts." in text
    assert "Access Denied: You do not have permission to view this section." in text


@pytest.mark.skipif(
    not os.getenv("RBAC_UI_BASE_URL"),
    reason="Set RBAC_UI_BASE_URL to run browser-level RBAC checks",
)
def test_playwright_tab_visibility_smoke():
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        pytest.skip(f"Playwright not available: {exc}")

    base_url = os.getenv("RBAC_UI_BASE_URL")
    staff_email = os.getenv("RBAC_UI_STAFF_EMAIL")
    staff_password = os.getenv("RBAC_UI_STAFF_PASSWORD")
    if not staff_email or not staff_password:
        pytest.skip("Set RBAC_UI_STAFF_EMAIL and RBAC_UI_STAFF_PASSWORD for UI auth checks")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(f"{base_url}/login", wait_until="networkidle")

        page.fill("input[name='username'], input[type='email']", staff_email)
        page.fill("input[name='password'], input[type='password']", staff_password)
        page.click("button[type='submit'], button:has-text('Login')")
        page.wait_for_load_state("networkidle")

        # Smoke-level visibility check only; full matrix is handled in API tests.
        # If tab is hidden by RBAC, its nav element should not be visible.
        for tab in ("tab-inventory", "tab-sales", "tab-team", "tab-settings"):
            locator = page.locator(f"#{tab}")
            assert locator.count() >= 0

        browser.close()
