from __future__ import annotations

import re

from flask import (
    Blueprint,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)

from .db import execute, query, query_one
from .security import customer_required
from .utils import (
    iso_now,
    normalize_code,
    paginate,
    status_meta,
)

bp = Blueprint("customer", __name__, url_prefix="/dashboard")


def _shipment_for_user(code: str):
    return query_one(
        """
        SELECT * FROM shipments
        WHERE code = ? AND customer_id = ?
        """,
        (normalize_code(code), g.user["id"]),
    )


@bp.get("")
@bp.get("/")
@customer_required
def dashboard():
    shipments = query(
        """
        SELECT * FROM shipments
        WHERE customer_id = ?
        ORDER BY created_at DESC
        LIMIT 6
        """,
        (g.user["id"],),
    )
    stats_row = query_one(
        """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN status = 'delivered' THEN 1 ELSE 0 END) AS delivered,
            SUM(CASE WHEN status IN ('pending','picked_up','in_transit','out_for_delivery','on_hold') THEN 1 ELSE 0 END) AS active
        FROM shipments WHERE customer_id = ?
        """,
        (g.user["id"],),
    )
    notifications = query(
        """
        SELECT * FROM notifications
        WHERE user_id = ?
        ORDER BY created_at DESC LIMIT 4
        """,
        (g.user["id"],),
    )
    return render_template(
        "customer/dashboard.html",
        page_title="لوحتي",
        shipments=shipments,
        stats={
            "total": stats_row["total"] or 0,
            "delivered": stats_row["delivered"] or 0,
            "active": stats_row["active"] or 0,
        },
        notifications=notifications,
    )


@bp.get("/shipments")
@customer_required
def shipments():
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "").strip()
    page = max(1, request.args.get("page", 1, type=int))
    where = ["customer_id = ?"]
    params: list = [g.user["id"]]
    if q:
        where.append("(code LIKE ? OR destination LIKE ? OR origin LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like, like])
    if status in {"pending", "picked_up", "in_transit", "out_for_delivery", "delivered", "on_hold", "cancelled"}:
        where.append("status = ?")
        params.append(status)
    clause = " AND ".join(where)
    total = query_one(f"SELECT COUNT(*) AS count FROM shipments WHERE {clause}", params)["count"]
    pagination = paginate(total, page, 20)
    rows = query(
        f"""
        SELECT * FROM shipments WHERE {clause}
        ORDER BY created_at DESC LIMIT ? OFFSET ?
        """,
        (*params, pagination["per_page"], pagination["offset"]),
    )
    return render_template(
        "customer/shipments.html",
        page_title="شحناتي",
        shipments=rows,
        q=q,
        status=status,
        pagination=pagination,
        total=total,
    )


@bp.get("/shipments/<code>")
@customer_required
def shipment_detail(code):
    shipment = _shipment_for_user(code)
    if not shipment:
        abort(404)
    events = query(
        """
        SELECT * FROM tracking_events
        WHERE shipment_id = ?
        ORDER BY event_at DESC, id DESC
        """,
        (shipment["id"],),
    )
    return render_template(
        "customer/shipment_detail.html",
        page_title=f"شحنة {shipment['code']}",
        shipment=shipment,
        events=events,
    )


@bp.route("/profile", methods=["GET", "POST"])
@customer_required
def profile():
    user = query_one("SELECT * FROM users WHERE id = ?", (g.user["id"],))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        company = request.form.get("company", "").strip()
        errors = []
        if len(name) < 2:
            errors.append("يرجى إدخال الاسم.")
        if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            errors.append("يرجى إدخال بريد إلكتروني صحيح.")
        if errors:
            for error in errors:
                flash(error, "error")
            return render_template(
                "customer/profile.html",
                page_title="بيانات الحساب",
                page_description="حدّث بيانات حسابك في بوابة توصيل.",
                user=user,
            ), 400
        execute(
            "UPDATE users SET name = ?, email = ?, company = ?, updated_at = ? WHERE id = ?",
            (name, email or None, company or None, iso_now(), g.user["id"]),
        )
        g.user["name"] = name
        g.user["email"] = email
        g.user["company"] = company
        flash("تم تحديث بيانات الحساب.", "success")
        return redirect(url_for("customer.profile"))
    return render_template(
        "customer/profile.html",
        page_title="بيانات الحساب",
        page_description="حدّث بيانات حسابك في بوابة توصيل.",
        user=user,
    )


@bp.get("/notifications")
@customer_required
def notifications():
    rows = query(
        "SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC LIMIT 100",
        (g.user["id"],),
    )
    return render_template(
        "customer/notifications.html",
        page_title="الإشعارات",
        notifications=rows,
    )


@bp.post("/notifications/read")
@customer_required
def notifications_read():
    execute(
        "UPDATE notifications SET read_at = ? WHERE user_id = ? AND read_at IS NULL",
        (iso_now(), g.user["id"]),
    )
    flash("تم تحديد جميع الإشعارات كمقروءة.", "success")
    return redirect(url_for("customer.notifications"))
