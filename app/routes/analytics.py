from datetime import date, datetime, time, timedelta, timezone
import csv
import io
import os
from decimal import Decimal
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..services.subscription_service import SubscriptionService
from .auth import UserIdentity, get_current_shop, require_permission

router = APIRouter(tags=["analytics"])
_AI_INSIGHT_CACHE: dict[str, dict[str, Any]] = {}

@router.get("/api/analytics/demand")
def get_demand_intelligence(
    identity: UserIdentity = Depends(require_permission("analytics_view")),
    db: Session = Depends(get_db),
):
    """Phase 4: Trending Missing Product Requests."""
    shop_id = identity.shop.id
    
    trending = db.query(
        models.MissingProductRequest.product_name,
        func.sum(models.MissingProductRequest.count).label("total_requests"),
        func.count(models.MissingProductRequest.customer_phone.distinct()).label("unique_users")
    ).filter(
        models.MissingProductRequest.shop_id == shop_id
    ).group_by(
        models.MissingProductRequest.product_name
    ).order_by(
        func.sum(models.MissingProductRequest.count).desc()
    ).limit(10).all()
    
    return {
        "success": True,
        "trending_requests": [
            {
                "product": t.product_name,
                "requests": int(t.total_requests),
                "users": int(t.unique_users),
                "trend": "🔥 High Demand" if t.total_requests > 5 else "Medium Demand"
            } for t in trending
        ]
    }


def _safe_float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _to_date(raw: Optional[str], fallback: date) -> date:
    if not raw:
        return fallback
    try:
        return datetime.fromisoformat(raw.split("T")[0]).date()
    except ValueError:
        return fallback


def _date_bounds(start_raw: Optional[str], end_raw: Optional[str]) -> tuple[date, date]:
    today = datetime.now().date()
    end_date = _to_date(end_raw, today)
    start_date = _to_date(start_raw, end_date - timedelta(days=6))
    if start_date > end_date:
        start_date, end_date = end_date, start_date
    return start_date, end_date


def _delta_obj(current: float, previous: float) -> Dict[str, Any]:
    if previous == 0 and current > 0:
        return {"kind": "new", "value": None, "label": "New", "direction": "up"}
    if previous == 0 and current == 0:
        return {"kind": "pct", "value": 0.0, "label": "0%", "direction": "flat"}
    pct = round(((current - previous) / previous) * 100, 2)
    direction = "up" if pct > 0 else ("down" if pct < 0 else "flat")
    return {"kind": "pct", "value": pct, "label": f"{abs(pct):.1f}%", "direction": direction}


def _inr(value: float) -> str:
    return f"₹{value:,.2f}"


def _heuristic_insights(payload: Dict[str, Any]) -> list[str]:
    summary = payload.get("summary", {})
    top_products = payload.get("top_products", [])
    low_stock = payload.get("low_stock", [])
    deltas = summary.get("deltas", {})
    insights = []
    if top_products:
        insights.append(f"{top_products[0]['name']} drives the most revenue in this period.")
    conv = summary.get("conversion_rate", 0.0)
    if conv < 20:
        insights.append("Inquiries are high but conversion is low; improve response speed and clarity.")
    elif conv > 40:
        insights.append("Conversion is healthy; keep the same sales workflow for top products.")
    if low_stock:
        insights.append(f"{low_stock[0]['name']} is low on stock; reorder soon to avoid missed sales.")
    if deltas.get("revenue", {}).get("direction") == "up":
        insights.append("Revenue trend is improving compared to the previous period.")
    else:
        insights.append("Revenue growth is flat/declining; consider timed offers on best sellers.")
    insights.append("Review top customer repeat behavior and launch targeted upsell bundles.")
    return [f"• {line}" for line in insights[:5]]


def _ai_insights(payload: Dict[str, Any], cache_key: str) -> list[str]:
    now = datetime.now(timezone.utc)
    cached = _AI_INSIGHT_CACHE.get(cache_key)
    if cached and (now - cached["created_at"]).total_seconds() < 1800:
        return cached["items"]

    model_key = os.getenv("GEMINI_API_KEY")
    if not model_key:
        items = _heuristic_insights(payload)
        _AI_INSIGHT_CACHE[cache_key] = {"created_at": now, "items": items}
        return items

    try:
        from ..core.ai_client import AIClient
        
        compact = {
            "summary": payload.get("summary", {}),
            "top_products": payload.get("top_products", [])[:3],
            "low_stock": payload.get("low_stock", [])[:3],
            "orders_series_tail": payload.get("orders_series", [])[-7:],
        }
        prompt = (
            "Generate exactly 5 concise analytics bullets for a shop owner. "
            "Each bullet max one line, no numbering, no markdown header.\n"
            f"Data: {compact}"
        )
        
        text = AIClient.generate_content(
            contents=prompt,
            config={'max_output_tokens': 200, 'temperature': 0.2}
        )
        lines = [ln.strip("• ").strip() for ln in text.splitlines() if ln.strip()]
        if len(lines) < 5:
            lines = _heuristic_insights(payload)
        items = [f"• {line}" for line in lines[:5]]
        _AI_INSIGHT_CACHE[cache_key] = {"created_at": now, "items": items}
        return items
    except Exception as e:
        print(f"[ANALYTICS AI ERROR] {e}")
        items = _heuristic_insights(payload)
        _AI_INSIGHT_CACHE[cache_key] = {"created_at": now, "items": items}
        return items


def _make_series_bucket(start_date: date, end_date: date, by: str) -> list[str]:
    labels: list[str] = []
    current = start_date
    if by == "hourly":
        now = datetime.now()
        base = datetime.combine(end_date, time.min)
        for h in range(24):
            labels.append((base + timedelta(hours=h)).strftime("%Y-%m-%d %H:00"))
        return labels
    if by == "monthly":
        current = date(start_date.year, start_date.month, 1)
        while current <= end_date:
            labels.append(current.strftime("%Y-%m"))
            next_month = date(current.year + (1 if current.month == 12 else 0), 1 if current.month == 12 else current.month + 1, 1)
            current = next_month
    elif by == "weekly":
        while current <= end_date:
            labels.append(current.strftime("%Y-%m-%d"))
            current += timedelta(days=7)
    else:
        while current <= end_date:
            labels.append(current.strftime("%Y-%m-%d"))
            current += timedelta(days=1)
    return labels


def _bucket_key(dt_value: datetime | date, by: str) -> str:
    if by == "hourly":
        if isinstance(dt_value, datetime):
            dth = dt_value
        else:
            dth = datetime.combine(dt_value, time.min)
        return dth.strftime("%Y-%m-%d %H:00")
    dt = dt_value if isinstance(dt_value, date) and not isinstance(dt_value, datetime) else dt_value.date()
    if by == "monthly":
        return dt.strftime("%Y-%m")
    if by == "weekly":
        monday = dt - timedelta(days=dt.weekday())
        return monday.strftime("%Y-%m-%d")
    return dt.strftime("%Y-%m-%d")


def _build_dashboard_payload(
    db: Session,
    shop_id: int,
    start_date: date,
    end_date: date,
    compare: bool,
    by: str = "daily",
) -> Dict[str, Any]:
    start_dt = datetime.combine(start_date, time.min)
    end_dt = datetime.combine(end_date, time.max)
    period_days = (end_date - start_date).days + 1
    prev_end_date = start_date - timedelta(days=1)
    prev_start_date = prev_end_date - timedelta(days=period_days - 1)
    prev_start_dt = datetime.combine(prev_start_date, time.min)
    prev_end_dt = datetime.combine(prev_end_date, time.max)

    sales_rows = db.query(models.SalesRecord).filter(
        models.SalesRecord.shop_id == shop_id,
        models.SalesRecord.date >= start_date,
        models.SalesRecord.date <= end_date,
    ).all()

    orders_rows = db.query(models.Order).filter(
        models.Order.shop_id == shop_id,
        models.Order.status == "completed",
        models.Order.created_at >= start_dt,
        models.Order.created_at <= end_dt,
    ).all()

    pending_rows = db.query(models.PendingRequest).filter(
        models.PendingRequest.shop_id == shop_id,
        models.PendingRequest.created_at >= start_dt,
        models.PendingRequest.created_at <= end_dt,
    ).all()

    low_stock_rows = db.query(models.InventoryItem).filter(
        models.InventoryItem.shop_id == shop_id,
        models.InventoryItem.quantity <= 10,
    ).order_by(models.InventoryItem.quantity.asc()).all()

    revenue_total = 0.0
    product_stats: Dict[str, Dict[str, float]] = {}
    revenue_series_map: Dict[str, float] = {}
    sales_series_map: Dict[str, float] = {}
    for row in sales_rows:
        unit_price = _safe_float(row.price if row.price is not None else (row.inventory_item.price if row.inventory_item else 0))
        qty = int(row.quantity or 0)
        value = qty * unit_price
        revenue_total += value
        product_name = (row.product_name or (row.inventory_item.name if row.inventory_item else "Unknown Product") or "Unknown Product").strip()
        if product_name not in product_stats:
            product_stats[product_name] = {"units": 0.0, "revenue": 0.0}
        product_stats[product_name]["units"] += qty
        product_stats[product_name]["revenue"] += value
        bucket = _bucket_key(row.date, by)
        revenue_series_map[bucket] = round(revenue_series_map.get(bucket, 0.0) + value, 2)
        sales_series_map[bucket] = round(sales_series_map.get(bucket, 0.0) + qty, 2)

    orders_count = len(orders_rows)
    inquiries_count = len(pending_rows)
    conversion_rate = round((orders_count / inquiries_count) * 100, 2) if inquiries_count > 0 else 0.0
    avg_order_value = round(revenue_total / orders_count, 2) if orders_count > 0 else 0.0

    orders_series_map: Dict[str, Dict[str, int]] = {}
    for row in orders_rows:
        bucket = _bucket_key(row.created_at, by)
        if bucket not in orders_series_map:
            orders_series_map[bucket] = {"orders": 0, "inquiries": 0}
        orders_series_map[bucket]["orders"] += 1
        if by == "hourly":
            revenue_series_map[bucket] = round(revenue_series_map.get(bucket, 0.0) + _safe_float(row.total_amount), 2)
            sales_series_map[bucket] = round(sales_series_map.get(bucket, 0.0) + int(row.quantity or 0), 2)

    for row in pending_rows:
        bucket = _bucket_key(row.created_at, by)
        if bucket not in orders_series_map:
            orders_series_map[bucket] = {"orders": 0, "inquiries": 0}
        orders_series_map[bucket]["inquiries"] += 1

    labels = _make_series_bucket(start_date, end_date, by)
    revenue_series = [{"label": k, "value": round(revenue_series_map.get(k, 0.0), 2)} for k in labels]
    sales_series = [{"label": k, "value": round(sales_series_map.get(k, 0.0), 2)} for k in labels]
    orders_series = [
        {
            "label": k,
            "orders": int(orders_series_map.get(k, {}).get("orders", 0)),
            "inquiries": int(orders_series_map.get(k, {}).get("inquiries", 0)),
        }
        for k in labels
    ]

    top_products = sorted(
        [{"name": name, "units_sold": int(v["units"]), "revenue": round(v["revenue"], 2)} for name, v in product_stats.items()],
        key=lambda item: (item["revenue"], item["units_sold"]),
        reverse=True,
    )[:8]

    customers_grouped = {}
    for row in orders_rows:
        phone = (row.phone or "").strip() or "unknown"
        name = (row.customer_name or "Walk-in Customer").strip() or "Walk-in Customer"
        key = f"{phone}:{name.lower()}"
        if key not in customers_grouped:
            customers_grouped[key] = {"name": name, "phone": phone, "orders": 0, "total_spend": 0.0, "last_purchase": None}
        customers_grouped[key]["orders"] += 1
        customers_grouped[key]["total_spend"] += _safe_float(row.total_amount)
        ts = row.created_at or datetime.now()
        if not customers_grouped[key]["last_purchase"] or ts > customers_grouped[key]["last_purchase"]:
            customers_grouped[key]["last_purchase"] = ts

    customer_profiles = {p.customer_phone: p for p in db.query(models.CustomerProfile).filter(models.CustomerProfile.shop_id == shop_id).all()}
    
    top_customers = []
    for c in sorted(customers_grouped.values(), key=lambda item: (item["total_spend"], item["orders"]), reverse=True)[:8]:
        phone = c["phone"]
        profile = customer_profiles.get(phone)
        
        top_customers.append({
            "name": c["name"],
            "phone": phone,
            "orders": int(c["orders"]),
            "total_spend": round(c["total_spend"], 2),
            "is_repeat": bool(c["orders"] > 1),
            "last_purchase": c["last_purchase"].isoformat() if c["last_purchase"] else None,
            "vip_tier": profile.vip_tier if profile else "NEW",
            "conversion_score": profile.conversion_score if profile else 0,
            "visits": profile.visit_count if profile else 1,
            "favorite_product": max(profile.favorite_products, key=profile.favorite_products.get) if profile and profile.favorite_products else None,
            "avg_budget": profile.avg_budget if profile else None
        })

    low_stock = [
        {
            "name": item.name,
            "qty": int(item.quantity or 0),
            "severity": "critical" if (item.quantity or 0) <= 3 else "low",
        }
        for item in low_stock_rows
    ]

    recent_sales = sorted(orders_rows, key=lambda row: row.created_at or datetime.min, reverse=True)[:8]
    recent_sales_payload = [
        {
            "order_id": row.order_id,
            "customer": row.customer_name or "Walk-in Customer",
            "product": row.product or "",
            "date": (row.created_at or datetime.now()).isoformat(),
            "amount": round(_safe_float(row.total_amount), 2),
            "status": row.status or "pending",
        }
        for row in recent_sales
    ]

    order_products = {(row.product or "").strip().lower() for row in orders_rows if row.product}
    recent_inquiries_payload = []
    for row in sorted(pending_rows, key=lambda item: item.created_at or datetime.min, reverse=True)[:8]:
        pname = (row.product_name or "Unknown Product").strip()
        recent_inquiries_payload.append(
            {
                "name": "",
                "phone": "",
                "product": pname,
                "message": row.customer_message or "",
                "date": (row.created_at or datetime.now()).isoformat(),
                "converted": pname.lower() in order_products,
            }
        )

    prev_revenue = 0.0
    prev_orders = 0
    prev_inquiries = 0
    if compare:
        prev_sales_rows = db.query(models.SalesRecord).filter(
            models.SalesRecord.shop_id == shop_id,
            models.SalesRecord.date >= prev_start_date,
            models.SalesRecord.date <= prev_end_date,
        ).all()
        prev_orders = db.query(models.Order).filter(
            models.Order.shop_id == shop_id,
            models.Order.status == "completed",
            models.Order.created_at >= prev_start_dt,
            models.Order.created_at <= prev_end_dt,
        ).count()
        prev_pending = db.query(models.PendingRequest).filter(
            models.PendingRequest.shop_id == shop_id,
            models.PendingRequest.created_at >= prev_start_dt,
            models.PendingRequest.created_at <= prev_end_dt,
        ).count()
        prev_inquiries = prev_pending
        prev_revenue = sum((int(row.quantity or 0) * _safe_float(row.price or 0)) for row in prev_sales_rows)

    # Calculate Understanding Metrics
    understanding_events = db.query(models.AIAnalyticsEvent).filter(
        models.AIAnalyticsEvent.shop_id == shop_id,
        models.AIAnalyticsEvent.created_at >= start_dt,
        models.AIAnalyticsEvent.created_at <= end_dt
    ).all()
    
    intent_confirmed = sum(1 for e in understanding_events if e.event_type == "INTENT_CONFIRMED")
    clarifications = sum(1 for e in understanding_events if e.event_type == "CLARIFICATION_TRIGGERED")
    total_understanding_events = intent_confirmed + clarifications
    
    understanding_success_rate = round((intent_confirmed / total_understanding_events) * 100, 2) if total_understanding_events > 0 else 100.0
    clarification_rate = round((clarifications / total_understanding_events) * 100, 2) if total_understanding_events > 0 else 0.0
    
    missed_requests = db.query(models.MissingProductRequest).filter(
        models.MissingProductRequest.shop_id == shop_id,
        models.MissingProductRequest.created_at >= start_dt,
        models.MissingProductRequest.created_at <= end_dt
    ).count()

    previous_conversion = round((prev_orders / prev_inquiries) * 100, 2) if prev_inquiries > 0 else 0.0
    previous_aov = (prev_revenue / prev_orders) if prev_orders > 0 else 0.0
    summary = {
        "total_revenue": round(revenue_total, 2),
        "orders": int(orders_count),
        "inquiries": int(inquiries_count),
        "conversion_rate": conversion_rate,
        "average_order_value": avg_order_value,
        "low_stock_products": len(low_stock),
        "understanding_success_rate": understanding_success_rate,
        "clarification_rate": clarification_rate,
        "missed_requests": missed_requests,
        "previous": {
            "total_revenue": round(prev_revenue, 2),
            "orders": int(prev_orders),
            "inquiries": int(prev_inquiries),
            "conversion_rate": previous_conversion,
            "average_order_value": round(previous_aov, 2),
            "low_stock_products": 0,
        },
        "deltas": {
            "revenue": _delta_obj(revenue_total, prev_revenue),
            "orders": _delta_obj(float(orders_count), float(prev_orders)),
            "inquiries": _delta_obj(float(inquiries_count), float(prev_inquiries)),
            "conversion": _delta_obj(conversion_rate, previous_conversion),
            "aov": _delta_obj(avg_order_value, previous_aov),
        },
    }
    cache_key = f"{shop_id}:{start_date.isoformat()}:{end_date.isoformat()}:{by}:{summary['total_revenue']}:{summary['orders']}:{summary['inquiries']}:{summary['low_stock_products']}"
    insights = _ai_insights(
        {
            "summary": summary,
            "top_products": top_products,
            "low_stock": low_stock,
            "orders_series": orders_series,
        },
        cache_key,
    )

    return {
        "success": True,
        "period": {
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "compare": compare,
            "group_by": by,
        },
        "summary": summary,
        "revenue_series": revenue_series,
        "orders_series": orders_series,
        "sales_series": sales_series,
        "top_products": top_products,
        "top_customers": top_customers,
        "low_stock": low_stock,
        "recent_sales": recent_sales_payload,
        "recent_inquiries": recent_inquiries_payload,
        "insights": insights,
        "insights_generated_by": "LEVIX AI",
        "compare_products": [
            {"name": item.name, "image": None}
            for item in db.query(models.InventoryItem).filter(models.InventoryItem.shop_id == shop_id).order_by(models.InventoryItem.name.asc()).all()
        ],
    }


def _build_basic_payload(db: Session, shop_id: int, start_date: date, end_date: date) -> Dict[str, Any]:
    sales_rows = db.query(models.SalesRecord).filter(
        models.SalesRecord.shop_id == shop_id,
        models.SalesRecord.date >= start_date,
        models.SalesRecord.date <= end_date,
    ).all()
    orders_count = db.query(models.Order).filter(
        models.Order.shop_id == shop_id,
        models.Order.created_at >= datetime.combine(start_date, time.min),
        models.Order.created_at <= datetime.combine(end_date, time.max),
    ).count()
    revenue_series_map: Dict[str, float] = {}
    total_revenue = 0.0
    total_sales_units = 0
    for row in sales_rows:
        unit_price = _safe_float(row.price if row.price is not None else (row.inventory_item.price if row.inventory_item else 0))
        qty = int(row.quantity or 0)
        total_sales_units += qty
        value = qty * unit_price
        total_revenue += value
        k = row.date.strftime("%Y-%m-%d")
        revenue_series_map[k] = round(revenue_series_map.get(k, 0.0) + value, 2)
    labels = _make_series_bucket(start_date, end_date, "daily")
    return {
        "success": True,
        "tier": "basic",
        "upgrade_required": True,
        "message": "Analytics Pro required for advanced analytics.",
        "period": {"start": start_date.isoformat(), "end": end_date.isoformat()},
        "summary": {
            "total_revenue": round(total_revenue, 2),
            "orders": int(orders_count),
            "sales_count": int(total_sales_units),
        },
        "revenue_series": [{"label": label, "value": revenue_series_map.get(label, 0.0)} for label in labels],
    }


@router.get("/api/analytics/dashboard")
def get_analytics_dashboard(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    by: str = Query("daily"),
    identity: UserIdentity = Depends(require_permission("analytics_view")),
    db: Session = Depends(get_db),
):
    start_date, end_date = _date_bounds(start, end)
    group_by = by if by in {"hourly", "daily", "weekly", "monthly"} else "daily"
    if not SubscriptionService.has_analytics_pro(db, identity.shop.id):
        return _build_basic_payload(db, identity.shop.id, start_date, end_date)
    return _build_dashboard_payload(db, identity.shop.id, start_date, end_date, True, group_by)


@router.get("/api/analytics/compare-products")
def compare_products(
    product_a: str = Query(...),
    product_b: str = Query(...),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    identity: UserIdentity = Depends(require_permission("analytics_view")),
    db: Session = Depends(get_db),
):
    if not SubscriptionService.has_analytics_pro(db, identity.shop.id):
        return JSONResponse(
            status_code=403,
            content={"success": False, "upgrade_required": True, "message": "Analytics Pro required"},
        )
    start_date, end_date = _date_bounds(start, end)
    rows = db.query(models.SalesRecord).filter(
        models.SalesRecord.shop_id == identity.shop.id,
        models.SalesRecord.date >= start_date,
        models.SalesRecord.date <= end_date,
        models.SalesRecord.product_name.in_([product_a, product_b]),
    ).all()
    data = {
        product_a: {"units_sold": 0, "revenue": 0.0, "orders": 0, "inquiries": 0, "conversion_rate": 0.0, "repeat_customer_rate": 0.0, "avg_price": 0.0, "series": {}},
        product_b: {"units_sold": 0, "revenue": 0.0, "orders": 0, "inquiries": 0, "conversion_rate": 0.0, "repeat_customer_rate": 0.0, "avg_price": 0.0, "series": {}},
    }
    for row in rows:
        name = row.product_name
        if name not in data:
            continue
        qty = int(row.quantity or 0)
        rev = qty * _safe_float(row.price)
        data[name]["units_sold"] += qty
        data[name]["revenue"] += rev
        data[name]["orders"] += 1
        key = row.date.strftime("%Y-%m-%d")
        data[name]["series"][key] = round(data[name]["series"].get(key, 0.0) + rev, 2)

    for product in [product_a, product_b]:
        inquiries = db.query(models.PendingRequest).filter(
            models.PendingRequest.shop_id == identity.shop.id,
            models.PendingRequest.created_at >= datetime.combine(start_date, time.min),
            models.PendingRequest.created_at <= datetime.combine(end_date, time.max),
            models.PendingRequest.product_name == product,
        ).count()
        data[product]["inquiries"] = inquiries
        data[product]["conversion_rate"] = round((data[product]["orders"] / inquiries) * 100, 2) if inquiries > 0 else 0.0
        data[product]["avg_price"] = round((data[product]["revenue"] / max(data[product]["units_sold"], 1)), 2)

    rev_a = data[product_a]["revenue"]
    rev_b = data[product_b]["revenue"]
    winner = product_a if rev_a >= rev_b else product_b
    loser = product_b if winner == product_a else product_a
    loser_rev = data[loser]["revenue"] or 1
    uplift = round(((data[winner]["revenue"] - data[loser]["revenue"]) / loser_rev) * 100, 2) if loser_rev else 0.0
    return {
        "success": True,
        "product_a": {"name": product_a, **data[product_a]},
        "product_b": {"name": product_b, **data[product_b]},
        "winner_summary": f"{winner} outperformed {loser} by {uplift}% revenue",
    }


@router.get("/analytics")
def get_analytics(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    identity: UserIdentity = Depends(require_permission("analytics_view")),
    db: Session = Depends(get_db),
):
    start, end = _date_bounds(start_date, end_date)
    if not SubscriptionService.has_analytics_pro(db, identity.shop.id):
        basic = _build_basic_payload(db, identity.shop.id, start, end)
        return {
            "total_requests": 0,
            "status_counts": {},
            "total_revenue": basic["summary"]["total_revenue"],
            "total_orders": basic["summary"]["orders"],
            "top_sold_products": [],
            "low_sold_products": [],
            "top_requested_products": [],
            "low_requested_products": [],
            "top_customers": [],
            "low_stock_items": [],
        }
    dashboard = _build_dashboard_payload(db, identity.shop.id, start, end, compare=False, by="daily")
    top_requested = sorted(dashboard["orders_series"], key=lambda item: item["inquiries"], reverse=True)[:5]
    return {
        "total_requests": dashboard["summary"]["inquiries"],
        "status_counts": {},
        "total_revenue": dashboard["summary"]["total_revenue"],
        "total_orders": dashboard["summary"]["orders"],
        "top_sold_products": [
            {
                "name": p["name"],
                "quantity_sold": p["units_sold"],
                "price": 0,
                "revenue": p["revenue"],
            }
            for p in dashboard["top_products"][:5]
        ],
        "low_sold_products": [],
        "top_requested_products": [{"name": p["label"], "score": p["inquiries"]} for p in top_requested],
        "low_requested_products": [],
        "top_customers": [{"name": c["name"], "phone": c["phone"], "orders": c["orders"]} for c in dashboard["top_customers"][:5]],
        "low_stock_items": [{"name": i["name"], "qty": i["qty"]} for i in dashboard["low_stock"]],
    }

@router.get("/inventory/insights")
def get_inventory_insights(start_date: Optional[str] = None, end_date: Optional[str] = None, identity: UserIdentity = Depends(require_permission("inventory_view")), db: Session = Depends(get_db)):
    """
    Returns high-level business intelligence.
    STRICT JSON SCHEMA AS PER USER REQUEST.
    """
    current_shop = identity.shop
    safe_default = {
        "items": [],
        "top_requested": [],
        "top_sold": [],
        "low_demand_requests": [],
        "low_demand_sales": [],
        "total_revenue": 0
    }
    
    response_data = safe_default
    try:
        stats = get_analytics(start_date, end_date, identity, db)
        
        # --- PER-ITEM INSIGHTS (for Inventory Tab) ---
        items = db.query(models.InventoryItem).filter(models.InventoryItem.shop_id == current_shop.id).all()
        item_stats = []
        
        # Pre-calculate counts from LogEntry to avoid N+1 queries in loop
        # But for limited inventory, a direct query is simpler to implement correctly
        for item in items:
            log_stats = db.query(
                func.count(models.LogEntry.id),
                func.sum(func.cast(models.LogEntry.status == 'out_of_stock', models.Integer)),
                func.max(models.LogEntry.timestamp),
                func.min(models.LogEntry.timestamp)
            ).filter(
                models.LogEntry.shop_id == current_shop.id,
                models.LogEntry.product_id == item.id
            ).first()
            
            total_req = log_stats[0] or 0
            oos_count = log_stats[1] or 0
            oos_rate = (oos_count / total_req) if total_req > 0 else 0
            
            last_req = log_stats[2]
            first_req = log_stats[3]
            
            days = 1
            if first_req and last_req:
                days = max(1, (last_req - first_req).days)
                
            demand_rate = round(total_req / days, 2) if total_req > 0 else 0
            
            item_stats.append({
                "id": item.id,
                "name": item.name,
                "quantity": item.quantity,
                "price": _safe_float(item.price),
                "total_requests": total_req,
                "out_of_stock_rate": round(float(oos_rate), 2),
                "out_of_stock_count": int(oos_count),
                "demand_rate": demand_rate,
                "last_requested_timestamp": last_req.isoformat() if last_req else None
            })

        response_data = {
            "items": item_stats,
            "top_requested": stats.get("top_requested_products", []),
            "top_sold": stats.get("top_sold_products", []),
            "low_demand_requests": stats.get("low_requested_products", []),
            "low_demand_sales": stats.get("low_sold_products", []),
            "total_revenue": round(stats.get("total_revenue", 0), 2)
        }
        
        print("[ANALYTICS FINAL RESPONSE]", response_data)
        return response_data
        
    except Exception as e:
        print("[ANALYTICS ERROR]", str(e))
        import traceback
        traceback.print_exc()
        return safe_default

@router.get("/dashboard/counts")
def get_dashboard_counts(identity: UserIdentity = Depends(get_current_shop), db: Session = Depends(get_db)):
    """
    Lightweight endpoint for polling navigation badge counts.
    """
    current_shop = identity.shop
    pending_inbox = db.query(models.PendingRequest).filter(
        models.PendingRequest.shop_id == current_shop.id
    ).count()
    
    pending_orders = db.query(models.Order).filter(
        models.Order.shop_id == current_shop.id,
        models.Order.status == "pending"
    ).count()
    
    return {
        "inbox": pending_inbox,
        "orders": pending_orders
    }

def _simple_pdf_bytes(title: str, lines: list[str]) -> bytes:
    content_lines = [f"BT /F1 12 Tf 50 800 Td ({title}) Tj ET"]
    y = 780
    for line in lines[:30]:
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        content_lines.append(f"BT /F1 10 Tf 50 {y} Td ({escaped}) Tj ET")
        y -= 18
    stream = "\n".join(content_lines).encode("latin-1", errors="ignore")
    objects = []
    objects.append(b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n")
    objects.append(b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n")
    objects.append(b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n")
    objects.append(b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n")
    objects.append(f"5 0 obj << /Length {len(stream)} >> stream\n".encode("latin-1") + stream + b"\nendstream endobj\n")
    pdf = b"%PDF-1.4\n"
    xref = [0]
    for obj in objects:
        xref.append(len(pdf))
        pdf += obj
    xref_start = len(pdf)
    pdf += f"xref\n0 {len(xref)}\n".encode("latin-1")
    pdf += b"0000000000 65535 f \n"
    for off in xref[1:]:
        pdf += f"{off:010d} 00000 n \n".encode("latin-1")
    pdf += f"trailer << /Size {len(xref)} /Root 1 0 R >>\nstartxref\n{xref_start}\n%%EOF".encode("latin-1")
    return pdf


@router.get("/analytics/export")
def export_analytics(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    compare: bool = Query(False),
    fmt: str = Query("excel"),
    identity: UserIdentity = Depends(require_permission("analytics_export")),
    db: Session = Depends(get_db),
):
    if not SubscriptionService.has_analytics_pro(db, identity.shop.id):
        return JSONResponse(
            status_code=403,
            content={"success": False, "upgrade_required": True, "message": "Analytics Pro required"},
        )
    start, end = _date_bounds(start_date, end_date)
    payload = _build_dashboard_payload(db, identity.shop.id, start, end, compare=compare, by="daily")
    summary = payload["summary"]
    date_suffix = datetime.now().strftime("%Y%m%d")

    if fmt == "csv":
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(["Metric", "Value"])
        writer.writerow(["Total Revenue", summary["total_revenue"]])
        writer.writerow(["Orders", summary["orders"]])
        writer.writerow(["Inquiries", summary["inquiries"]])
        writer.writerow(["Conversion Rate", summary["conversion_rate"]])
        writer.writerow(["Average Order Value", summary["average_order_value"]])
        writer.writerow([])
        writer.writerow(["Top Products"])
        writer.writerow(["Name", "Units Sold", "Revenue"])
        for row in payload["top_products"]:
            writer.writerow([row["name"], row["units_sold"], row["revenue"]])
        return StreamingResponse(
            io.BytesIO(stream.getvalue().encode("utf-8")),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=Levix_Analytics_{date_suffix}.csv"},
        )

    if fmt == "pdf":
        lines = [
            f"Period: {payload['period']['start']} to {payload['period']['end']}",
            f"Revenue: {_inr(summary['total_revenue'])}",
            f"Orders: {summary['orders']}",
            f"Inquiries: {summary['inquiries']}",
            f"Conversion Rate: {summary['conversion_rate']}%",
            f"AOV: {_inr(summary['average_order_value'])}",
            "",
            "Top Products:",
        ] + [f"- {p['name']}: {p['units_sold']} units, {_inr(p['revenue'])}" for p in payload["top_products"][:8]]
        return StreamingResponse(
            io.BytesIO(_simple_pdf_bytes("LEVIX Analytics Summary", lines)),
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=Levix_Analytics_{date_suffix}.pdf"},
        )

    excel_stream = io.StringIO()
    excel_stream.write("Metric\tValue\n")
    excel_stream.write(f"Total Revenue\t{summary['total_revenue']}\n")
    excel_stream.write(f"Orders\t{summary['orders']}\n")
    excel_stream.write(f"Inquiries\t{summary['inquiries']}\n")
    excel_stream.write(f"Conversion Rate\t{summary['conversion_rate']}\n")
    excel_stream.write(f"Average Order Value\t{summary['average_order_value']}\n\n")
    excel_stream.write("Top Products\nName\tUnits Sold\tRevenue\n")
    for row in payload["top_products"]:
        excel_stream.write(f"{row['name']}\t{row['units_sold']}\t{row['revenue']}\n")
    return StreamingResponse(
        io.BytesIO(excel_stream.getvalue().encode("utf-8")),
        media_type="application/vnd.ms-excel",
        headers={"Content-Disposition": f"attachment; filename=Levix_Analytics_{date_suffix}.xls"},
    )
