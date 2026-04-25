import re
from pathlib import Path

from app.permissions import MASTER_PERMISSION_KEYS, PERMISSION_GROUPS, ROLE_TEMPLATES


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "app"
TEMPLATE_PATH = ROOT / "templates" / "dashboard.html"


def _canonical_description_map() -> dict[str, str]:
    descriptions: dict[str, str] = {}
    for group in PERMISSION_GROUPS:
        for item in group.get("items", []):
            descriptions[item["key"]] = item.get("description", "").strip()
    return descriptions


def _scan_backend_permission_routes() -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    route_files = sorted((APP_DIR / "routes").glob("*.py"))
    for file_path in route_files:
        text = file_path.read_text(encoding="utf-8")
        for match in re.finditer(r"require_permission\(\s*['\"]([a-z0-9_]+)['\"]\s*\)", text):
            permission = match.group(1)
            mapping.setdefault(permission, []).append(str(file_path.relative_to(ROOT)))
    return mapping


def _scan_ui_permissions() -> set[str]:
    ui_permissions: set[str] = set()
    if not TEMPLATE_PATH.exists():
        return ui_permissions

    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    for pattern in (
        r"hasPerm\(\s*['\"]([a-z0-9_]+)['\"]\s*\)",
        r"key:\s*['\"]([a-z0-9_]+)['\"]",
    ):
        for m in re.finditer(pattern, text):
            ui_permissions.add(m.group(1))
    return ui_permissions


def build_permission_matrix() -> list[dict]:
    descriptions = _canonical_description_map()
    backend_routes = _scan_backend_permission_routes()
    ui_permissions = _scan_ui_permissions()

    matrix = []
    for permission in MASTER_PERMISSION_KEYS:
        matrix.append(
            {
                "permission_key": permission,
                "description": descriptions.get(permission, ""),
                "related_ui_tab": permission.split("_", 1)[0],
                "related_buttons": [],
                "related_api_routes": backend_routes.get(permission, []),
                "ui_referenced": permission in ui_permissions,
                "backend_referenced": permission in backend_routes,
            }
        )
    return matrix


def test_master_permission_keys_are_unique():
    assert len(MASTER_PERMISSION_KEYS) == len(set(MASTER_PERMISSION_KEYS))


def test_role_templates_only_use_canonical_permissions():
    canonical = set(MASTER_PERMISSION_KEYS)
    bad = {
        role: [perm for perm in perms if perm not in canonical]
        for role, perms in ROLE_TEMPLATES.items()
    }
    bad = {k: v for k, v in bad.items() if v}
    assert not bad, f"Role templates include unknown permissions: {bad}"


def test_no_backend_permissions_outside_canonical_list():
    backend_permissions = set(_scan_backend_permission_routes().keys())
    canonical = set(MASTER_PERMISSION_KEYS)
    unexpected = sorted(backend_permissions - canonical)
    assert not unexpected, f"Backend protects unknown permission keys: {unexpected}"


def test_permission_matrix_reports_coverage_gaps():
    matrix = build_permission_matrix()
    missing_everywhere = [
        row["permission_key"]
        for row in matrix
        if not row["backend_referenced"] and not row["ui_referenced"]
    ]
    # Keep this test non-blocking; strict dead-key checks are reported by scripts/audit_permissions.py.
    assert len(matrix) == len(MASTER_PERMISSION_KEYS)
    if missing_everywhere:
        print(
            "Dead permissions detected (not used in backend or UI): "
            f"{missing_everywhere}"
        )
