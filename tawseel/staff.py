from __future__ import annotations

from flask import (
    Blueprint,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)

from .db import execute, query, query_one
from .security import (
    audit,
    clear_staff_cookie,
    client_ip,
    create_staff_session,
    hash_password,
    logout_current_staff_session,
    rate_limit,
    safe_next_url,
    set_staff_cookie,
    staff_required,
    verify_password,
)
from .shipments import record_status_update
from .utils import STATUS_META, iso_now, paginate, status_meta

bp = Blueprint("staff", __name__, url_prefix="/staff")


def _shipment_for_branch(shipment_id: int):
    return query_one(
        """
        SELECT s.*, u.name AS customer_name, u.phone AS customer_phone,
               u.email AS customer_email, b.name AS branch_name, b.code AS branch_code
        FROM shipments s
        LEFT JOIN users u ON u.id = s.customer_id
        LEFT JOIN branches b ON b.id = s.branch_id
        WHERE s.id = ? AND s.branch_id = ?
        """,
        (shipment_id, g.staff["branch_id"]),
    )


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.get("staff"):
        return redirect(url_for("staff.dashboard"))

    next_url = safe_next_url(
        request.args.get("next") or request.form.get("next"),
        url_for("staff.dashboard"),
    )
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not rate_limit(f"staff-login:{client_ip()}", 8, 900):
            flash("محاولات دخول كثيرة. يرجى المحاولة بعد 15 دقيقة.", "error")
            return redirect(url_for("staff.login"))

        staff = query_one(
            """
            SELECT st.*, b.name AS branch_name, b.code AS branch_code,
                   b.city AS branch_city, b.phone AS branch_phone,
                   b.is_active AS branch_active
            FROM staff st
            JOIN branches b ON b.id = st.branch_id
            WHERE st.email = ?
            """,
            (email,),
        )
        if (
            staff
            and staff["is_active"]
            and staff["branch_active"]
            and verify_password(staff["password_hash"], password)
        ):
            execute(
                "UPDATE staff SET last_login_at = ? WHERE id = ?",
                (iso_now(), staff["id"]),
            )
            token = create_staff_session(staff["id"])
            g.staff = {
                "id": staff["id"],
                "name": staff["name"],
                "email": staff["email"],
                "phone": staff["phone"],
                "role": staff["role"],
                "branch_id": staff["branch_id"],
                "branch_code": staff["branch_code"],
                "branch_name": staff["branch_name"],
                "branch_city": staff["branch_city"],
                "branch_phone": staff["branch_phone"],
            }
            audit("تسجيل دخول موظف", f"{staff['name']} — {staff['branch_name']}")
            response = redirect(next_url)
            return set_staff_cookie(response, token)

        flash("البريد الإلكتروني أو كلمة المرور غير صحيحة، أو الحساب غير مفعّل.", "error")
        return (
            render_template(
                "staff/login.html",
                page_title="دخول الموظفين",
                email=email,
                next_url=next_url,
            ),
            401,
        )

    return render_template(
        "staff/login.html",
        page_title="دخول الموظفين",
        email="",
        next_url=next_url,
    )


@bp.post("/logout")
def logout():
    logout_current_staff_session()
    response = redirect(url_for("staff.login"))
    flash("تم تسجيل الخروج من بوابة الفرع.", "success")
    return clear_staff_cookie(response)


@bp.get("")
@bp.get("/")
@staff_required
def dashboard():
    branch_id = g.staff["branch_id"]
    stats = query_one(
        """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN status IN ('pending','picked_up','in_transit','out_for_delivery','on_hold') THEN 1 ELSE 0 END) AS active,
               SUM(CASE WHEN status = 'out_for_delivery' THEN 1 ELSE 0 END) AS out_for_delivery,
               SUM(CASE WHEN status = 'delivered' THEN 1 ELSE 0 END) AS delivered
        FROM shipments WHERE branch_id = ?
        """,
        (branch_id,),
    )
    recent_shipments = query(
        """
        SELECT s.*, u.name AS customer_name
        FROM shipments s
        LEFT JOIN users u ON u.id = s.customer_id
        WHERE s.branch_id = ?
        ORDER BY s.updated_at DESC, s.id DESC
        LIMIT 6
        """,
        (branch_id,),
    )
    team = query(
        """
        SELECT name, role, email, phone
        FROM staff
        WHERE branch_id = ? AND is_active = 1
        ORDER BY CASE role WHEN 'manager' THEN 0 ELSE 1 END, name
        """,
        (branch_id,),
    )
    return render_template(
        "staff/dashboard.html",
        page_title="نظرة عامة",
        stats={
            "total": stats["total"] or 0,
            "active": stats["active"] or 0,
            "out_for_delivery": stats["out_for_delivery"] or 0,
            "delivered": stats["delivered"] or 0,
        },
        recent_shipments=recent_shipments,
        team=team,
    )


@bp.get("/shipments")
@staff_required
def shipments():
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "").strip()
    page = max(1, request.args.get("page", 1, type=int))
    where = ["s.branch_id = ?"]
    params: list = [g.staff["branch_id"]]
    if q:
        where.append(
            "(s.code LIKE ? OR s.destination LIKE ? OR s.origin LIKE ? OR u.name LIKE ? OR u.phone LIKE ?)"
        )
        like = f"%{q}%"
        params.extend([like, like, like, like, like])
    if status in STATUS_META:
        where.append("s.status = ?")
        params.append(status)
    clause = " AND ".join(where)
    total = query_one(
        f"""
        SELECT COUNT(*) AS count
        FROM shipments s LEFT JOIN users u ON u.id = s.customer_id
        WHERE {clause}
        """,
        params,
    )["count"]
    pagination = paginate(total, page, 20)
    rows = query(
        f"""
        SELECT s.*, u.name AS customer_name
        FROM shipments s LEFT JOIN users u ON u.id = s.customer_id
        WHERE {clause}
        ORDER BY s.updated_at DESC, s.id DESC
        LIMIT ? OFFSET ?
        """,
        (*params, pagination["per_page"], pagination["offset"]),
    )
    return render_template(
        "staff/shipments.html",
        page_title="شحنات الفرع",
        shipments=rows,
        q=q,
        status=status,
        total=total,
        pagination=pagination,
    )


@bp.get("/shipments/<int:shipment_id>")
@staff_required
def shipment_detail(shipment_id):
    shipment = _shipment_for_branch(shipment_id)
    if not shipment:
        flash("الشحنة غير موجودة أو غير مرتبطة بفرعك.", "error")
        return redirect(url_for("staff.shipments"))
    events = query(
        "SELECT * FROM tracking_events WHERE shipment_id = ? ORDER BY event_at DESC, id DESC",
        (shipment_id,),
    )
    return render_template(
        "staff/shipment_detail.html",
        page_title=f"شحنة {shipment['code']}",
        shipment=shipment,
        events=events,
    )


@bp.post("/shipments/<int:shipment_id>/status")
@staff_required
def shipment_update(shipment_id):
    shipment = _shipment_for_branch(shipment_id)
    if not shipment:
        flash("الشحنة غير موجودة أو غير مرتبطة بفرعك.", "error")
        return redirect(url_for("staff.shipments"))

    status = request.form.get("status", "").strip()
    location = request.form.get("location", "").strip()
    note = request.form.get("note", "").strip()
    if status not in STATUS_META:
        flash("حالة الشحنة غير صالحة.", "error")
        return redirect(url_for("staff.shipment_detail", shipment_id=shipment_id))
    if len(location) > 120 or len(note) > 500:
        flash("الموقع أو الملاحظة أطول من الحد المسموح.", "error")
        return redirect(url_for("staff.shipment_detail", shipment_id=shipment_id))

    record_status_update(shipment, status, location, note)
    audit(
        "تحديث شحنة",
        f"{shipment['code']} — {status_meta(status)['label']} — {g.staff['branch_name']}",
    )
    flash("تم تحديث حالة الشحنة وإضافة حدث التتبع.", "success")
    return redirect(url_for("staff.shipment_detail", shipment_id=shipment_id))


@bp.route("/profile", methods=["GET", "POST"])
@staff_required
def profile():
    staff = query_one(
        """
        SELECT st.*, b.name AS branch_name, b.code AS branch_code,
               b.city AS branch_city, b.phone AS branch_phone
        FROM staff st JOIN branches b ON b.id = st.branch_id
        WHERE st.id = ?
        """,
        (g.staff["id"],),
    )
    if request.method == "POST":
        current = request.form.get("current_password", "")
        new = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")
        errors = []
        if not staff or not verify_password(staff["password_hash"], current):
            errors.append("كلمة المرور الحالية غير صحيحة.")
        if len(new) < 10:
            errors.append("كلمة المرور الجديدة يجب أن تكون 10 أحرف على الأقل.")
        if new != confirm:
            errors.append("تأكيد كلمة المرور غير مطابق.")
        if errors:
            for error in errors:
                flash(error, "error")
            return (
                render_template("staff/profile.html", page_title="ملفي", staff=staff),
                400,
            )
        execute(
            "UPDATE staff SET password_hash = ?, updated_at = ? WHERE id = ?",
            (hash_password(new), iso_now(), g.staff["id"]),
        )
        execute(
            "DELETE FROM staff_sessions WHERE staff_id = ? AND id <> ?",
            (g.staff["id"], g.staff_session["id"]),
        )
        audit("تغيير كلمة مرور موظف", g.staff["email"])
        flash("تم تغيير كلمة المرور. تم إنهاء الجلسات الأخرى.", "success")
        return redirect(url_for("staff.profile"))
    return render_template("staff/profile.html", page_title="ملفي", staff=staff)
