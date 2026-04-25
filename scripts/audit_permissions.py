from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.permissions import MASTER_PERMISSION_KEYS, PERMISSION_GROUPS

APP_DIR = ROOT / "app"
ROUTES_DIR = APP_DIR / "routes"
TEMPLATE_PATH = ROOT / "templates" / "dashboard.html"


@dataclass
class PermissionAuditRow:
    permission_key: str
    description: str
    related_ui_tab: str
    related_buttons: list[str]
    related_api_routes: list[str]
    status: str
    notes: str


def _desc_map() -> dict[str, str]:
    out: dict[str, str] = {}
    for group in PERMISSION_GROUPS:
        for item in group.get("items", []):
            out[item["key"]] = item.get("description", "")
    return out


def _scan_backend() -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    for route_file in sorted(ROUTES_DIR.glob("*.py")):
        text = route_file.read_text(encoding="utf-8")
        for m in re.finditer(r"require_permission\(\s*['\"]([a-z0-9_]+)['\"]\s*\)", text):
            key = m.group(1)
            mapping.setdefault(key, []).append(str(route_file.relative_to(ROOT)))
    return mapping


def _scan_ui() -> tuple[set[str], dict[str, str]]:
    if not TEMPLATE_PATH.exists():
        return set(), {}
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    ui_perms = set()
    for pattern in (
        r"hasPerm\(\s*['\"]([a-z0-9_]+)['\"]\s*\)",
        r"key:\s*['\"]([a-z0-9_]+)['\"]",
        r":\s*['\"]([a-z0-9_]+)['\"]",
    ):
        ui_perms.update(re.findall(pattern, text))
    tab_mapping: dict[str, str] = {}
    tab_match = re.search(r"tabPermMapping\s*=\s*\{([^}]+)\}", text, re.MULTILINE | re.DOTALL)
    if tab_match:
        tab_pairs = re.findall(r"([a-z_]+)\s*:\s*['\"]([a-z0-9_]+)['\"]", tab_match.group(1))
        tab_mapping = {tab: perm for tab, perm in tab_pairs}
        ui_perms.update(tab_mapping.values())
    ui_perms.intersection_update(set(MASTER_PERMISSION_KEYS))
    return ui_perms, tab_mapping


def build_rows() -> tuple[list[PermissionAuditRow], dict]:
    descriptions = _desc_map()
    backend = _scan_backend()
    ui, tab_mapping = _scan_ui()
    canonical = set(MASTER_PERMISSION_KEYS)

    rows: list[PermissionAuditRow] = []
    for key in MASTER_PERMISSION_KEYS:
        has_ui = key in ui
        has_backend = key in backend
        status = "PASS"
        notes = "Mapped in UI and backend" if (has_ui and has_backend) else ""
        if not has_ui and not has_backend:
            status = "FAIL"
            notes = "Dead permission: not referenced in UI/backend"
        elif has_ui and not has_backend:
            status = "WARNING"
            notes = "UI references permission, but no backend route guard found"
        elif has_backend and not has_ui:
            status = "WARNING"
            notes = "Backend guard exists, but no UI mapping found"

        rows.append(
            PermissionAuditRow(
                permission_key=key,
                description=descriptions.get(key, ""),
                related_ui_tab=next((tab for tab, perm in tab_mapping.items() if perm == key), key.split("_", 1)[0]),
                related_buttons=[],
                related_api_routes=backend.get(key, []),
                status=status,
                notes=notes,
            )
        )

    unknown_backend = sorted(set(backend.keys()) - canonical)
    unknown_ui = sorted(ui - canonical)
    duplicates = sorted(k for k in MASTER_PERMISSION_KEYS if MASTER_PERMISSION_KEYS.count(k) > 1)
    stats = {
        "unknown_backend_permissions": unknown_backend,
        "unknown_ui_permissions": unknown_ui,
        "duplicate_permission_names": sorted(set(duplicates)),
    }
    return rows, stats


def print_report(rows: list[PermissionAuditRow], stats: dict):
    passed = [r for r in rows if r.status == "PASS"]
    failed = [r for r in rows if r.status == "FAIL"]
    warnings = [r for r in rows if r.status == "WARNING"]

    print("LEVIX RBAC PERMISSION AUDIT")
    print("=" * 32)
    print(f"Total permissions tested: {len(rows)}")
    print(f"Passed count: {len(passed)}")
    print(f"Failed count: {len(failed)}")
    print(f"Warning count: {len(warnings)}")
    print(f"Security holes found: {len(stats['unknown_backend_permissions']) + len(stats['unknown_ui_permissions'])}")
    print(f"Dead permissions found: {len(failed)}")
    print()

    if passed:
        print("PASS:")
        for row in passed:
            print(f"- {row.permission_key}")
        print()

    if failed:
        print("FAIL:")
        for row in failed:
            print(f"- {row.permission_key} ({row.notes})")
        print()

    if warnings or stats["duplicate_permission_names"]:
        print("WARNING:")
        for row in warnings:
            print(f"- {row.permission_key} ({row.notes})")
        for dup in stats["duplicate_permission_names"]:
            print(f"- {dup} (duplicate permission key)")
        print()

    if stats["unknown_ui_permissions"]:
        print("UI-only unknown permission keys:", stats["unknown_ui_permissions"])
    if stats["unknown_backend_permissions"]:
        print("Backend-only unknown permission keys:", stats["unknown_backend_permissions"])

    cleanup = []
    cleanup.extend([f"Remove or wire dead permission: {r.permission_key}" for r in failed])
    cleanup.extend([f"Align UI/backend mapping: {r.permission_key}" for r in warnings])
    if stats["duplicate_permission_names"]:
        cleanup.extend([f"Deduplicate key: {k}" for k in stats["duplicate_permission_names"]])

    print()
    print("Recommended cleanup list:")
    if cleanup:
        for item in cleanup:
            print(f"- {item}")
    else:
        print("- No cleanup needed")


def main():
    parser = argparse.ArgumentParser(description="Audit Levix RBAC permission coverage")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text report")
    args = parser.parse_args()

    rows, stats = build_rows()
    if args.json:
        payload = {
            "rows": [row.__dict__ for row in rows],
            "stats": stats,
        }
        print(json.dumps(payload, indent=2))
        return
    print_report(rows, stats)


if __name__ == "__main__":
    main()
