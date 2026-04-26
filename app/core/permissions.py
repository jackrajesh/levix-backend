from __future__ import annotations

from typing import Iterable

# Canonical enterprise RBAC keys
MASTER_PERMISSION_KEYS = [
    "inbox_view",
    "inbox_reply",
    "orders_view",
    "orders_edit",
    "orders_cancel",
    "inventory_view",
    "inventory_add",
    "inventory_edit",
    "inventory_delete",
    "stock_adjust",
    "price_change",
    "sales_create",
    "sales_delete",
    "analytics_view",
    "analytics_export",
    "team_view",
    "team_add_member",
    "team_edit_member",
    "team_remove_member",
    "team_manage_permissions",
    "logs_view",
    "logs_export",
    "logs_clear",
    "settings_view",
    "settings_edit",
    "billing_view",
    "billing_manage",
    "owner_impersonation",
]

# Backward compatibility map to preserve existing staff accounts.
LEGACY_PERMISSION_MAP = {
    "inbox_access": "inbox_view",
    "reply_customers": "inbox_reply",
    "inventory_edit": "inventory_edit",
    "quantity_change": "stock_adjust",
    "price_change": "price_change",
    "inventory_stock_change": "stock_adjust",
    "inventory_price_change": "price_change",
    "inventory_import": "inventory_add",
    "inventory_export": "analytics_export",
    "orders_refund": "orders_cancel",
    "sales_view": "sales_create",
    "sales_edit": "sales_create",
    "sales_refund": "sales_delete",
    "customer_view": "inbox_view",
    "customer_edit": "inbox_reply",
    "manage_team": "team_manage_permissions",
    "settings_access": "settings_edit",
    "export_data": "analytics_export",
    "data_export": "analytics_export",
    "csv_export": "analytics_export",
    "excel_export": "analytics_export",
    "report_export": "analytics_export",
    "logs_download": "logs_export",
    "delete_data": "logs_clear",
    "data_delete": "logs_clear",
    "billing_access": "billing_view",
}

# Accept old checks that may still exist in routes/UI code.
REQUIREMENT_ALIASES = {
    "inbox_access": "inbox_view",
    "reply_customers": "inbox_reply",
    "manage_team": "team_manage_permissions",
    "settings_access": "settings_edit",
    "export_data": "analytics_export",
    "csv_export": "analytics_export",
    "excel_export": "analytics_export",
    "report_export": "analytics_export",
    "logs_download": "logs_export",
    "delete_data": "logs_clear",
    "billing_access": "billing_view",
    "quantity_change": "stock_adjust",
    "price_change": "price_change",
    "inventory_stock_change": "stock_adjust",
    "inventory_price_change": "price_change",
    "data_export": "analytics_export",
    "data_delete": "logs_clear",
    "sales_view": "sales_create",
    "sales_edit": "sales_create",
    "sales_refund": "sales_delete",
    "orders_refund": "orders_cancel",
}

PERMISSION_GROUPS = [
    {
        "title": "COMMUNICATION",
        "items": [
            {"key": "inbox_view", "label": "View Inbox", "description": "Open inbox and see incoming requests."},
            {"key": "inbox_reply", "label": "Reply Customers", "description": "Reply to customer requests and resolve pending messages."},
        ],
    },
    {
        "title": "ORDERS",
        "items": [
            {"key": "orders_view", "label": "View Orders", "description": "View orders and order history."},
            {"key": "orders_edit", "label": "Edit Orders", "description": "Accept, complete, and update order details."},
            {"key": "orders_cancel", "label": "Cancel Orders", "description": "Reject or cancel existing orders."},
        ],
    },
    {
        "title": "INVENTORY",
        "items": [
            {"key": "inventory_view", "label": "View Inventory", "description": "View inventory list and stock levels."},
            {"key": "inventory_add", "label": "Add Product", "description": "Create new products in inventory."},
            {"key": "inventory_edit", "label": "Edit Product", "description": "Edit product details and aliases."},
            {"key": "inventory_delete", "label": "Delete Product", "description": "Delete products from inventory."},
            {"key": "price_change", "label": "Change Price", "description": "Modify product pricing."},
            {"key": "stock_adjust", "label": "Adjust Stock", "description": "Increase or decrease stock quantities."},
        ],
    },
    {
        "title": "SALES",
        "items": [
            {"key": "sales_create", "label": "Create Sales", "description": "Create new sales entries."},
            {"key": "sales_delete", "label": "Delete Sales", "description": "Delete sales entries."},
        ],
    },
    {
        "title": "ANALYTICS",
        "items": [
            {"key": "analytics_view", "label": "View Analytics", "description": "Open analytics and insights dashboards."},
            {"key": "analytics_export", "label": "Export Reports", "description": "Export analytics reports."},
        ],
    },
    {
        "title": "TEAM",
        "items": [
            {"key": "team_view", "label": "View Team", "description": "View team member list."},
            {"key": "team_add_member", "label": "Add Staff", "description": "Create staff accounts."},
            {"key": "team_edit_member", "label": "Edit Staff", "description": "Edit staff profile, role, and status."},
            {"key": "team_remove_member", "label": "Remove Staff", "description": "Delete staff accounts."},
            {"key": "team_manage_permissions", "label": "Manage Permissions", "description": "Assign and edit role permissions."},
        ],
    },
    {
        "title": "LOGS",
        "items": [
            {"key": "logs_view", "label": "View Logs", "description": "View activity logs."},
            {"key": "logs_export", "label": "Export Logs", "description": "Export activity logs."},
            {"key": "logs_clear", "label": "Clear Logs", "description": "Clear activity logs."},
        ],
    },
    {
        "title": "BILLING",
        "items": [
            {"key": "billing_view", "label": "View Billing", "description": "View plan and billing history."},
            {"key": "billing_manage", "label": "Manage Subscription", "description": "Upgrade plan and activate add-ons."},
        ],
    },
    {
        "title": "SETTINGS",
        "items": [
            {"key": "settings_view", "label": "View Settings", "description": "Open settings page."},
            {"key": "settings_edit", "label": "Edit Settings", "description": "Edit shop settings and integrations."},
        ],
    },
]

ROLE_TEMPLATES = {
    "Cashier": ["orders_view", "orders_edit", "sales_create", "inventory_view"],
    "Inventory Manager": ["inventory_view", "inventory_add", "inventory_edit", "stock_adjust", "price_change"],
    "Support Agent": ["inbox_view", "inbox_reply", "orders_view"],
    "Manager": [
        "inbox_view",
        "inbox_reply",
        "orders_view",
        "orders_edit",
        "orders_cancel",
        "inventory_view",
        "inventory_add",
        "inventory_edit",
        "stock_adjust",
        "price_change",
        "sales_create",
        "sales_delete",
        "analytics_view",
        "analytics_export",
        "team_view",
        "team_edit_member",
        "logs_view",
        "logs_export",
        "settings_view",
        "settings_edit",
        "billing_view",
    ],
    "Admin": [k for k in MASTER_PERMISSION_KEYS if k not in {"owner_impersonation"}],
}

DEFAULT_ROLE_SUGGESTIONS = list(ROLE_TEMPLATES.keys())

IMPLIED_PERMISSIONS = {
    "settings_edit": {"settings_view"},
    "billing_manage": {"billing_view"},
    "team_manage_permissions": {"team_view", "team_edit_member"},
    "team_add_member": {"team_view"},
    "team_edit_member": {"team_view"},
    "team_remove_member": {"team_view"},
    "inventory_add": {"inventory_view"},
    "inventory_edit": {"inventory_view"},
    "inventory_delete": {"inventory_view"},
    "price_change": {"inventory_view", "inventory_edit"},
    "stock_adjust": {"inventory_view", "inventory_edit"},
    "orders_edit": {"orders_view"},
    "orders_cancel": {"orders_view"},
    "sales_create": set(),
    "sales_delete": {"sales_create"},
    "analytics_export": {"analytics_view"},
    "logs_export": {"logs_view"},
    "logs_clear": {"logs_view"},
    "owner_impersonation": {"team_view"},
}


def normalize_permission_key(key: str) -> str:
    if not key:
        return key
    return REQUIREMENT_ALIASES.get(LEGACY_PERMISSION_MAP.get(key, key), LEGACY_PERMISSION_MAP.get(key, key))


def normalize_permissions(perms: Iterable[str] | None) -> list[str]:
    if not perms:
        return []
    result = []
    seen = set()
    for p in perms:
        normalized = normalize_permission_key(p)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def has_effective_permission(granted_permissions: Iterable[str] | None, required_permission: str) -> bool:
    canonical_required = normalize_permission_key(required_permission)
    normalized = set(normalize_permissions(granted_permissions))
    if "*" in normalized:
        return True
    if canonical_required in normalized:
        return True
    for perm in list(normalized):
        implied = IMPLIED_PERMISSIONS.get(perm, set())
        if canonical_required in implied:
            return True
    return False
