from __future__ import annotations

import csv
import io
import re
import secrets
from datetime import datetime, timezone

from flask import (
    Blueprint,
    Response,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)
from werkzeug.security import check_password_hash

from .db import execute, query, query_one
from .security import (
    admin_required,
    audit,
    clear_auth_cookie,
    client_ip,
    create_auth_session,
    hash_password,
    logout_current_session,
    rate_limit,
    safe_next_url,
    set_auth_cookie,
    verify_password,
)
from .settings import SETTING_KEYS, get_settings, save_settings
from .shipments import notify_for_status
from .sms import sms_ready
from .utils import (
    SERVICE_META,
    STAFF_ROLE_META,
    STATUS_META,
    format_input_datetime,
    iso_now,
    normalize_code,
    normalize_phone,
    paginate,
    parse_local_datetime,
    status_meta,
    valid_phone,
)

bp = Blueprint("admin", __name__, url_prefix="/admin")

DEMO_PHONE_NUMBERS = ("+96891234567", "+96899887766")
ACTIVE_SHIPMENT_STATUSES = ("pending", "picked_up", "in_transit", "out_for_delivery", "on_hold")


def _customers():
    return query("SELECT id, name, phone, company FROM users ORDER BY created_at DESC")


def _branches():
    return query("SELECT * FROM branches ORDER BY is_active DESC, name")


def _branch_form_values(branch=None) -> dict:
    if request.method == "POST":
        return {
            "code": normalize_code(request.form.get("code", "")),
            "name": request.form.get("name", "").strip(),
            "city": request.form.get("city", "").strip(),
            "address": request.form.get("address", "").strip(),
            "phone": request.form.get("phone", "").strip(),
            "is_active": 1 if request.form.get("is_active") else 0,
        }
    if branch:
        return {
            "code": branch["code"],
            "name": branch["name"],
            "city": branch["city"] or "",
            "address": branch["address"] or "",
            "phone": branch["phone"] or "",
            "is_active": branch["is_active"],
        }
    return {"code": "", "name": "", "city": "", "address": "", "phone": "", "is_active": 1}


def _validate_branch(values: dict, branch_id: int | None = None) -> list[str]:
    errors = []
    if not re.match(r"^[A-Z0-9-]{2,12}$", values["code"]):
        errors.append("كود الفرع يجب أن يكون من 2 إلى 12 حرفاً أو رقماً.")
    if len(values["name"]) < 2:
        errors.append("يرجى إدخال اسم الفرع.")
    if values["phone"] and not valid_phone(
        values["phone"], current_app.config["DEFAULT_COUNTRY_CODE"]
    ):
        errors.append("رقم هاتف الفرع غير صحيح.")
    duplicate = query_one("SELECT id FROM branches WHERE code = ?", (values["code"],))
    if duplicate and duplicate["id"] != branch_id:
        errors.append("كود الفرع مستخدم بالفعل.")
    return errors


def _staff_form_values(staff=None) -> dict:
    if request.method == "POST":
        return {
            "name": request.form.get("name", "").strip(),
            "email": request.form.get("email", "").strip().lower(),
            "phone": request.form.get("phone", "").strip(),
            "branch_id": request.form.get("branch_id", "").strip(),
            "role": request.form.get("role", "agent").strip(),
            "is_active": 1 if request.form.get("is_active") else 0,
            "password": request.form.get("password", ""),
            "confirm_password": request.form.get("confirm_password", ""),
        }
    if staff:
        return {
            "name": staff["name"],
            "email": staff["email"],
            "phone": staff["phone"] or "",
            "branch_id": str(staff["branch_id"]),
            "role": staff["role"],
            "is_active": staff["is_active"],
            "password": "",
            "confirm_password": "",
        }
    return {
        "name": "",
        "email": "",
        "phone": "",
        "branch_id": "",
        "role": "agent",
        "is_active": 1,
        "password": "",
        "confirm_password": "",
    }


def _validate_staff(values: dict, staff_id: int | None = None) -> list[str]:
    errors = []
    if len(values["name"]) < 2:
        errors.append("يرجى إدخال اسم الموظف.")
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", values["email"]):
        errors.append("البريد الإلكتروني غير صحيح.")
    duplicate = query_one("SELECT id FROM staff WHERE email = ?", (values["email"],))
    if duplicate and duplicate["id"] != staff_id:
        errors.append("البريد الإلكتروني مستخدم بالفعل.")
    branch = None
    if values["branch_id"]:
        branch = query_one("SELECT * FROM branches WHERE id = ?", (values["branch_id"],))
    if not branch:
        errors.append("يرجى اختيار فرع.")
    elif values["is_active"] and not branch["is_active"]:
        errors.append("لا يمكن تعيين موظف نشط إلى فرع موقوف.")
    if values["role"] not in STAFF_ROLE_META:
        errors.append("دور الموظف غير صالح.")
    if values["phone"] and not valid_phone(
        values["phone"], current_app.config["DEFAULT_COUNTRY_CODE"]
    ):
        errors.append("رقم هاتف الموظف غير صحيح.")
    if staff_id is None or values["password"]:
        if len(values["password"]) < 10:
            errors.append("كلمة المرور يجب أن تكون 10 أحرف على الأقل.")
        if values["password"] != values["confirm_password"]:
            errors.append("تأكيد كلمة المرور غير مطابق.")
    return errors


def _shipment(shipment_id: int):
    return query_one(
        """
        SELECT s.*, u.name AS customer_name, u.phone AS customer_phone,
               u.email AS customer_email, b.name AS branch_name, b.code AS branch_code
        FROM shipments s
        LEFT JOIN users u ON u.id = s.customer_id
        LEFT JOIN branches b ON b.id = s.branch_id
        WHERE s.id = ?
        """,
        (shipment_id,),
    )


def _generate_code() -> str:
    year = datetime.now(timezone.utc).strftime("%y")
    prefix = str(current_app.config.get("SHIPMENT_CODE_PREFIX", "TS"))
    for _ in range(20):
        code = f"{prefix}{year}{secrets.randbelow(1_000_000):06d}"
        if not query_one("SELECT id FROM shipments WHERE code = ?", (code,)):
            return code
    raise RuntimeError("Could not generate a unique shipment code.")


def _shipment_form_values() -> dict:
    return {
        "code": request.form.get("code", "").strip(),
        "customer_id": request.form.get("customer_id", "").strip(),
        "branch_id": request.form.get("branch_id", "").strip(),
        "sender_name": request.form.get("sender_name", "").strip(),
        "sender_phone": request.form.get("sender_phone", "").strip(),
        "origin": request.form.get("origin", "").strip(),
        "destination": request.form.get("destination", "").strip(),
        "service_type": request.form.get("service_type", "standard").strip(),
        "status": request.form.get("status", "pending").strip(),
        "weight_kg": request.form.get("weight_kg", "").strip(),
        "pieces": request.form.get("pieces", "1").strip(),
        "description": request.form.get("description", "").strip(),
        "amount": request.form.get("amount", "").strip(),
        "currency": request.form.get("currency", "OMR").strip(),
        "location": request.form.get("location", "").strip(),
        "note": request.form.get("note", "").strip(),
    }


def _validate_shipment(values: dict, shipment_id: int | None = None) -> list[str]:
    errors = []
    origin = values["origin"]
    destination = values["destination"]
    if len(origin) < 2:
        errors.append("يرجى إدخال مدينة الإرسال.")
    if len(destination) < 2:
        errors.append("يرجى إدخال مدينة الوصول.")
    if values["service_type"] not in SERVICE_META:
        errors.append("نوع الخدمة غير صالح.")
    if values["status"] not in STATUS_META:
        errors.append("حالة الشحنة غير صالحة.")
    if values["customer_id"]:
        if not query_one("SELECT id FROM users WHERE id = ?", (values["customer_id"],)):
            errors.append("العميل المحدد غير موجود.")
    if values["branch_id"]:
        if not query_one("SELECT id FROM branches WHERE id = ?", (values["branch_id"],)):
            errors.append("الفرع المحدد غير موجود.")
    if values["sender_phone"] and not valid_phone(
        values["sender_phone"], current_app.config["DEFAULT_COUNTRY_CODE"]
    ):
        errors.append("رقم هاتف المرسل غير صحيح.")
    try:
        pieces = int(values["pieces"] or "1")
        if pieces < 1 or pieces > 10000:
            raise ValueError
    except ValueError:
        errors.append("عدد القطع يجب أن يكون رقماً صحيحاً.")
    if values["weight_kg"]:
        try:
            if float(values["weight_kg"]) < 0:
                raise ValueError
        except ValueError:
            errors.append("الوزن يجب أن يكون رقماً صحيحاً.")
    if values["amount"]:
        try:
            if float(values["amount"]) < 0:
                raise ValueError
        except ValueError:
            errors.append("المبلغ يجب أن يكون رقماً صحيحاً.")
    code = normalize_code(values["code"])
    if code:
        if not re.match(r"^[A-Z0-9#-]{3,32}$", code):
            errors.append("كود الشحنة يجب أن يحتوي على حروف وأرقام فقط.")
        duplicate = query_one("SELECT id FROM shipments WHERE code = ?", (code,))
        if duplicate and duplicate["id"] != shipment_id:
            errors.append("كود الشحنة مستخدم بالفعل.")
    return errors


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.get("admin"):
        return redirect(url_for("admin.dashboard"))
    next_url = safe_next_url(request.args.get("next") or request.form.get("next"), url_for("admin.dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not rate_limit(f"admin-login:{client_ip()}", 8, 900):
            flash("محاولات دخول كثيرة. يرجى المحاولة بعد 15 دقيقة.", "error")
            return redirect(url_for("admin.login"))
        admin = query_one("SELECT * FROM admins WHERE email = ?", (email,))
        if admin and admin["is_active"] and verify_password(admin["password_hash"], password):
            execute("UPDATE admins SET last_login_at = ? WHERE id = ?", (iso_now(), admin["id"]))
            token = create_auth_session(admin_id=admin["id"])
            g.admin = {"id": admin["id"], "name": admin["name"], "email": admin["email"]}
            audit("تسجيل دخول", f"المدير: {admin['email']}")
            response = redirect(next_url)
            return set_auth_cookie(response, token)
        flash("البريد الإلكتروني أو كلمة المرور غير صحيحة.", "error")
        return render_template(
            "admin/login.html", page_title="دخول الإدارة", email=email, next_url=next_url
        ), 401
    return render_template("admin/login.html", page_title="دخول الإدارة", email="", next_url=next_url)


@bp.post("/logout")
def logout():
    logout_current_session()
    response = redirect(url_for("admin.login"))
    flash("تم تسجيل الخروج من لوحة الإدارة.", "success")
    return clear_auth_cookie(response)


@bp.get("")
@bp.get("/")
@admin_required
def dashboard():
    stats = query_one(
        """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN status IN ('pending','picked_up','in_transit','out_for_delivery','on_hold') THEN 1 ELSE 0 END) AS active,
            SUM(CASE WHEN status = 'delivered' THEN 1 ELSE 0 END) AS delivered
        FROM shipments
        """
    )
    customers_count = query_one("SELECT COUNT(*) AS count FROM users")["count"]
    requests_count = query_one("SELECT COUNT(*) AS count FROM contact_requests WHERE status = 'new'")["count"]
    recent_shipments = query(
        """
        SELECT s.*, u.name AS customer_name
        FROM shipments s LEFT JOIN users u ON u.id = s.customer_id
        ORDER BY s.created_at DESC LIMIT 6
        """
    )
    recent_requests = query(
        "SELECT * FROM contact_requests ORDER BY created_at DESC LIMIT 5"
    )
    return render_template(
        "admin/dashboard.html",
        page_title="نظرة عامة",
        stats={
            "total": stats["total"] or 0,
            "active": stats["active"] or 0,
            "delivered": stats["delivered"] or 0,
            "customers": customers_count,
            "requests": requests_count,
        },
        recent_shipments=recent_shipments,
        recent_requests=recent_requests,
        sms_ok=sms_ready(),
    )


@bp.get("/demo")
@admin_required
def demo_data():
    """Internal cheat sheet with demo accounts and shipments for staff."""
    placeholders = ", ".join("?" for _ in DEMO_PHONE_NUMBERS)
    demo_customers = query(
        f"""
        SELECT id, name, phone, email, company
        FROM users
        WHERE phone IN ({placeholders})
        ORDER BY name
        """,
        DEMO_PHONE_NUMBERS,
    )
    demo_shipments = query(
        f"""
        SELECT s.id, s.code, s.status, s.origin, s.destination,
               s.service_type, s.created_at, u.name AS customer_name, u.phone AS customer_phone
        FROM shipments s
        JOIN users u ON u.id = s.customer_id
        WHERE u.phone IN ({placeholders})
        ORDER BY s.created_at DESC
        LIMIT 8
        """,
        DEMO_PHONE_NUMBERS,
    )
    active_shipment = next(
        (shipment for shipment in demo_shipments if shipment["status"] in ACTIVE_SHIPMENT_STATUSES),
        None,
    )

    demo_password = ""
    admin_row = query_one(
        "SELECT password_hash FROM admins WHERE id = ?", (g.admin["id"],)
    )
    if not current_app.config["IS_PRODUCTION"] and admin_row:
        configured_password = current_app.config.get("ADMIN_PASSWORD", "")
        if configured_password and check_password_hash(
            admin_row["password_hash"], configured_password
        ):
            demo_password = configured_password

    from .seed import DEMO_STAFF_EMAIL, DEMO_STAFF_PASSWORD

    demo_staff = query_one(
        """
        SELECT st.*, b.name AS branch_name
        FROM staff st JOIN branches b ON b.id = st.branch_id
        WHERE st.email = ?
        """,
        (DEMO_STAFF_EMAIL,),
    )
    demo_staff_password = ""
    if (
        demo_staff
        and not current_app.config["IS_PRODUCTION"]
        and check_password_hash(demo_staff["password_hash"], DEMO_STAFF_PASSWORD)
    ):
        demo_staff_password = DEMO_STAFF_PASSWORD

    return render_template(
        "admin/demo.html",
        page_title="بيانات التجربة",
        demo_customers=demo_customers,
        demo_shipments=demo_shipments,
        active_shipment=active_shipment,
        demo_password=demo_password,
        demo_staff=demo_staff,
        demo_staff_password=demo_staff_password,
    )


@bp.get("/branches")
@admin_required
def branches():
    rows = query(
        """
        SELECT b.*,
               (SELECT COUNT(*) FROM staff st WHERE st.branch_id = b.id) AS staff_count,
               (SELECT COUNT(*) FROM shipments sh WHERE sh.branch_id = b.id) AS shipment_count
        FROM branches b
        ORDER BY b.is_active DESC, b.name
        """
    )
    return render_template("admin/branches.html", page_title="الفروع", branches=rows)


@bp.route("/branches/new", methods=["GET", "POST"])
@admin_required
def branch_new():
    values = _branch_form_values()
    if request.method == "POST":
        errors = _validate_branch(values)
        if errors:
            for error in errors:
                flash(error, "error")
            return (
                render_template(
                    "admin/branch_form.html",
                    page_title="فرع جديد",
                    values=values,
                    branch=None,
                ),
                400,
            )
        execute(
            """
            INSERT INTO branches (code, name, city, address, phone, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                values["code"], values["name"], values["city"] or None,
                values["address"] or None, values["phone"] or None,
                values["is_active"], iso_now(), iso_now(),
            ),
        )
        audit("إنشاء فرع", f"{values['code']} — {values['name']}")
        flash("تم إنشاء الفرع.", "success")
        return redirect(url_for("admin.branches"))
    return render_template(
        "admin/branch_form.html", page_title="فرع جديد", values=values, branch=None
    )


@bp.route("/branches/<int:branch_id>/edit", methods=["GET", "POST"])
@admin_required
def branch_edit(branch_id):
    branch = query_one("SELECT * FROM branches WHERE id = ?", (branch_id,))
    if not branch:
        flash("الفرع غير موجود.", "error")
        return redirect(url_for("admin.branches"))
    values = _branch_form_values(branch)
    if request.method == "POST":
        errors = _validate_branch(values, branch_id)
        if errors:
            for error in errors:
                flash(error, "error")
            return (
                render_template(
                    "admin/branch_form.html",
                    page_title="تعديل الفرع",
                    values=values,
                    branch=branch,
                ),
                400,
            )
        execute(
            """
            UPDATE branches SET code = ?, name = ?, city = ?, address = ?, phone = ?,
                   is_active = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                values["code"], values["name"], values["city"] or None,
                values["address"] or None, values["phone"] or None,
                values["is_active"], iso_now(), branch_id,
            ),
        )
        if not values["is_active"]:
            execute(
                "DELETE FROM staff_sessions WHERE staff_id IN (SELECT id FROM staff WHERE branch_id = ?)",
                (branch_id,),
            )
        audit("تعديل فرع", f"{values['code']} — {values['name']}")
        flash("تم حفظ بيانات الفرع.", "success")
        return redirect(url_for("admin.branches"))
    return render_template(
        "admin/branch_form.html", page_title="تعديل الفرع", values=values, branch=branch
    )


@bp.get("/staff")
@admin_required
def staff_list():
    rows = query(
        """
        SELECT st.*, b.name AS branch_name, b.code AS branch_code
        FROM staff st JOIN branches b ON b.id = st.branch_id
        ORDER BY st.is_active DESC, b.name, st.name
        """
    )
    return render_template("admin/staff.html", page_title="الموظفون", staff_members=rows)


@bp.route("/staff/new", methods=["GET", "POST"])
@admin_required
def staff_new():
    values = _staff_form_values()
    if request.method == "POST":
        errors = _validate_staff(values)
        if errors:
            for error in errors:
                flash(error, "error")
            return (
                render_template(
                    "admin/staff_form.html",
                    page_title="موظف جديد",
                    values=values,
                    staff=None,
                    branches=_branches(),
                ),
                400,
            )
        execute(
            """
            INSERT INTO staff
                (branch_id, name, email, phone, password_hash, role,
                 is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(values["branch_id"]), values["name"], values["email"],
                normalize_phone(values["phone"], current_app.config["DEFAULT_COUNTRY_CODE"]) or None,
                hash_password(values["password"]), values["role"], values["is_active"],
                iso_now(), iso_now(),
            ),
        )
        audit("إنشاء موظف فرع", f"{values['email']} — {values['role']}")
        flash("تم إنشاء حساب الموظف.", "success")
        return redirect(url_for("admin.staff_list"))
    return render_template(
        "admin/staff_form.html",
        page_title="موظف جديد",
        values=values,
        staff=None,
        branches=_branches(),
    )


@bp.route("/staff/<int:staff_id>/edit", methods=["GET", "POST"])
@admin_required
def staff_edit(staff_id):
    staff = query_one("SELECT * FROM staff WHERE id = ?", (staff_id,))
    if not staff:
        flash("الموظف غير موجود.", "error")
        return redirect(url_for("admin.staff_list"))
    values = _staff_form_values(staff)
    if request.method == "POST":
        errors = _validate_staff(values, staff_id)
        if errors:
            for error in errors:
                flash(error, "error")
            return (
                render_template(
                    "admin/staff_form.html",
                    page_title="تعديل الموظف",
                    values=values,
                    staff=staff,
                    branches=_branches(),
                ),
                400,
            )
        branch_changed = str(staff["branch_id"]) != values["branch_id"]
        password_changed = bool(values["password"])
        password_hash = staff["password_hash"]
        if password_changed:
            password_hash = hash_password(values["password"])
        execute(
            """
            UPDATE staff SET branch_id = ?, name = ?, email = ?, phone = ?,
                   password_hash = ?, role = ?, is_active = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                int(values["branch_id"]), values["name"], values["email"],
                normalize_phone(values["phone"], current_app.config["DEFAULT_COUNTRY_CODE"]) or None,
                password_hash, values["role"], values["is_active"], iso_now(), staff_id,
            ),
        )
        if not values["is_active"] or branch_changed or password_changed:
            execute("DELETE FROM staff_sessions WHERE staff_id = ?", (staff_id,))
        audit("تعديل موظف فرع", f"{values['email']} — {values['role']}")
        flash("تم حفظ بيانات الموظف.", "success")
        return redirect(url_for("admin.staff_list"))
    return render_template(
        "admin/staff_form.html",
        page_title="تعديل الموظف",
        values=values,
        staff=staff,
        branches=_branches(),
    )


@bp.get("/shipments")
@admin_required
def shipments():
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "").strip()
    page = max(1, request.args.get("page", 1, type=int))
    where = ["1 = 1"]
    params: list = []
    if q:
        where.append("(s.code LIKE ? OR s.destination LIKE ? OR s.origin LIKE ? OR u.name LIKE ? OR u.phone LIKE ? OR b.name LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like, like, like, like, like])
    if status in STATUS_META:
        where.append("s.status = ?")
        params.append(status)
    clause = " AND ".join(where)
    total = query_one(
        f"""
        SELECT COUNT(*) AS count
        FROM shipments s
        LEFT JOIN users u ON u.id = s.customer_id
        LEFT JOIN branches b ON b.id = s.branch_id
        WHERE {clause}
        """,
        params,
    )["count"]
    pagination = paginate(total, page, 20)
    rows = query(
        f"""
        SELECT s.*, u.name AS customer_name, b.name AS branch_name
        FROM shipments s
        LEFT JOIN users u ON u.id = s.customer_id
        LEFT JOIN branches b ON b.id = s.branch_id
        WHERE {clause}
        ORDER BY s.created_at DESC LIMIT ? OFFSET ?
        """,
        (*params, pagination["per_page"], pagination["offset"]),
    )
    return render_template(
        "admin/shipments.html",
        page_title="الشحنات",
        shipments=rows,
        q=q,
        status=status,
        total=total,
        pagination=pagination,
    )


@bp.route("/shipments/new", methods=["GET", "POST"])
@admin_required
def shipment_new():
    values = _shipment_form_values()
    if request.method == "POST":
        errors = _validate_shipment(values)
        if errors:
            for error in errors:
                flash(error, "error")
            return render_template(
                "admin/shipment_new.html",
                page_title="شحنة جديدة",
                values=values,
                customers=_customers(),
                branches=_branches(),
            ), 400
        code = normalize_code(values["code"]) or _generate_code()
        cursor = execute(
            """
            INSERT INTO shipments
                (code, customer_id, branch_id, sender_name, sender_phone, origin, destination,
                 service_type, status, weight_kg, pieces, description, amount, currency,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                code,
                values["customer_id"] or None,
                values["branch_id"] or None,
                values["sender_name"] or None,
                normalize_phone(values["sender_phone"], current_app.config["DEFAULT_COUNTRY_CODE"]) or None,
                values["origin"],
                values["destination"],
                values["service_type"],
                values["status"],
                float(values["weight_kg"]) if values["weight_kg"] else None,
                int(values["pieces"] or "1"),
                values["description"] or None,
                float(values["amount"]) if values["amount"] else None,
                values["currency"] or "OMR",
                iso_now(),
                iso_now(),
            ),
        )
        shipment_id = cursor.lastrowid
        execute(
            """
            INSERT INTO tracking_events (shipment_id, status, location, note, event_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                shipment_id,
                values["status"],
                values["location"] or values["origin"],
                values["note"] or "تم إنشاء الشحنة وتسجيلها في النظام.",
                iso_now(),
                iso_now(),
            ),
        )
        shipment = _shipment(shipment_id)
        if shipment:
            notify_for_status(shipment, values["status"], values["note"] or "تم إنشاء الشحنة.")
        audit("إنشاء شحنة", f"{code} — {values['origin']} إلى {values['destination']}")
        flash(f"تم إنشاء الشحنة {code}.", "success")
        return redirect(url_for("admin.shipment_detail", shipment_id=shipment_id))
    return render_template(
        "admin/shipment_new.html",
        page_title="شحنة جديدة",
        values=values,
        customers=_customers(),
        branches=_branches(),
    )


@bp.get("/shipments/<int:shipment_id>")
@admin_required
def shipment_detail(shipment_id):
    shipment = _shipment(shipment_id)
    if not shipment:
        flash("الشحنة غير موجودة.", "error")
        return redirect(url_for("admin.shipments"))
    events = query(
        "SELECT * FROM tracking_events WHERE shipment_id = ? ORDER BY event_at DESC, id DESC",
        (shipment_id,),
    )
    return render_template(
        "admin/shipment_detail.html",
        page_title=f"شحنة {shipment['code']}",
        shipment=shipment,
        events=events,
        customers=_customers(),
        branches=_branches(),
        now_value=format_input_datetime(iso_now()),
    )


@bp.post("/shipments/<int:shipment_id>/edit")
@admin_required
def shipment_edit(shipment_id):
    shipment = _shipment(shipment_id)
    if not shipment:
        flash("الشحنة غير موجودة.", "error")
        return redirect(url_for("admin.shipments"))
    values = _shipment_form_values()
    errors = _validate_shipment(values, shipment_id)
    if errors:
        for error in errors:
            flash(error, "error")
        return redirect(url_for("admin.shipment_detail", shipment_id=shipment_id))
    status_changed = values["status"] != shipment["status"]
    execute(
        """
        UPDATE shipments SET
            customer_id = ?, branch_id = ?, sender_name = ?, sender_phone = ?, origin = ?, destination = ?,
            service_type = ?, status = ?, weight_kg = ?, pieces = ?, description = ?,
            amount = ?, currency = ?, updated_at = ?,
            delivered_at = CASE WHEN ? = 'delivered' AND delivered_at IS NULL THEN ? ELSE delivered_at END
        WHERE id = ?
        """,
        (
            values["customer_id"] or None,
            values["branch_id"] or None,
            values["sender_name"] or None,
            normalize_phone(values["sender_phone"], current_app.config["DEFAULT_COUNTRY_CODE"]) or None,
            values["origin"],
            values["destination"],
            values["service_type"],
            values["status"],
            float(values["weight_kg"]) if values["weight_kg"] else None,
            int(values["pieces"] or "1"),
            values["description"] or None,
            float(values["amount"]) if values["amount"] else None,
            values["currency"] or "OMR",
            iso_now(),
            values["status"],
            iso_now(),
            shipment_id,
        ),
    )
    if status_changed:
        execute(
            """
            INSERT INTO tracking_events (shipment_id, status, location, note, event_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                shipment_id,
                values["status"],
                values["location"] or values["destination"],
                values["note"] or f"تم تحديث حالة الشحنة إلى: {status_meta(values['status'])['label']}.",
                iso_now(),
                iso_now(),
            ),
        )
        updated = _shipment(shipment_id)
        if updated:
            notify_for_status(updated, values["status"], values["note"])
    audit("تعديل شحنة", f"{shipment['code']} — الحالة: {values['status']}")
    flash("تم حفظ تعديلات الشحنة.", "success")
    return redirect(url_for("admin.shipment_detail", shipment_id=shipment_id))


@bp.post("/shipments/<int:shipment_id>/events")
@admin_required
def shipment_add_event(shipment_id):
    shipment = _shipment(shipment_id)
    if not shipment:
        flash("الشحنة غير موجودة.", "error")
        return redirect(url_for("admin.shipments"))
    status = request.form.get("event_status", "").strip()
    location = request.form.get("event_location", "").strip()
    note = request.form.get("event_note", "").strip()
    event_at = parse_local_datetime(request.form.get("event_at"))
    if status not in STATUS_META:
        flash("حالة الحدث غير صالحة.", "error")
        return redirect(url_for("admin.shipment_detail", shipment_id=shipment_id))
    if len(note) < 3:
        flash("يرجى إدخال وصف للحدث.", "error")
        return redirect(url_for("admin.shipment_detail", shipment_id=shipment_id))
    execute(
        """
        INSERT INTO tracking_events (shipment_id, status, location, note, event_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (shipment_id, status, location or shipment["destination"], note, event_at, iso_now()),
    )
    delivered_at = shipment["delivered_at"]
    if status == "delivered" and not delivered_at:
        delivered_at = iso_now()
    execute(
        "UPDATE shipments SET status = ?, updated_at = ?, delivered_at = ? WHERE id = ?",
        (status, iso_now(), delivered_at, shipment_id),
    )
    notify_for_status(shipment, status, note)
    audit("إضافة حدث تتبع", f"{shipment['code']} — {status}")
    flash("تمت إضافة حدث التتبع وتحديث حالة الشحنة.", "success")
    return redirect(url_for("admin.shipment_detail", shipment_id=shipment_id))


@bp.get("/shipments.csv")
@admin_required
def shipments_csv():
    rows = query(
        """
        SELECT s.code, s.status, s.origin, s.destination, s.service_type,
               s.weight_kg, s.pieces, s.amount, s.currency, s.created_at,
               u.name AS customer_name, u.phone AS customer_phone, b.name AS branch_name
        FROM shipments s
        LEFT JOIN users u ON u.id = s.customer_id
        LEFT JOIN branches b ON b.id = s.branch_id
        ORDER BY s.created_at DESC
        """
    )
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "code", "status", "origin", "destination", "branch", "service", "weight_kg",
        "pieces", "amount", "currency", "created_at", "customer", "phone",
    ])
    for row in rows:
        writer.writerow([
            row["code"], status_meta(row["status"])["label"], row["origin"], row["destination"],
            row["branch_name"] or "", row["service_type"], row["weight_kg"], row["pieces"],
            row["amount"], row["currency"], row["created_at"], row["customer_name"] or "",
            row["customer_phone"] or "",
        ])
    response = Response("\ufeff" + output.getvalue(), mimetype="text/csv; charset=utf-8")
    response.headers["Content-Disposition"] = "attachment; filename=tawseel-shipments.csv"
    return response


@bp.get("/customers")
@admin_required
def customers():
    q = request.args.get("q", "").strip()
    if q:
        like = f"%{q}%"
        rows = query(
            """
            SELECT u.*, COUNT(s.id) AS shipment_count
            FROM users u LEFT JOIN shipments s ON s.customer_id = u.id
            WHERE u.name LIKE ? OR u.phone LIKE ? OR u.email LIKE ? OR u.company LIKE ?
            GROUP BY u.id ORDER BY u.created_at DESC
            """,
            (like, like, like, like),
        )
    else:
        rows = query(
            """
            SELECT u.*, COUNT(s.id) AS shipment_count
            FROM users u LEFT JOIN shipments s ON s.customer_id = u.id
            GROUP BY u.id ORDER BY u.created_at DESC
            """
        )
    return render_template("admin/customers.html", page_title="العملاء", customers=rows, q=q)


@bp.get("/customers/<int:user_id>")
@admin_required
def customer_detail(user_id):
    customer = query_one("SELECT * FROM users WHERE id = ?", (user_id,))
    if not customer:
        flash("العميل غير موجود.", "error")
        return redirect(url_for("admin.customers"))
    shipments = query(
        "SELECT * FROM shipments WHERE customer_id = ? ORDER BY created_at DESC",
        (user_id,),
    )
    return render_template(
        "admin/customer_detail.html",
        page_title=customer["name"],
        customer=customer,
        shipments=shipments,
    )


@bp.post("/customers/<int:user_id>/toggle")
@admin_required
def customer_toggle(user_id):
    customer = query_one("SELECT * FROM users WHERE id = ?", (user_id,))
    if not customer:
        flash("العميل غير موجود.", "error")
        return redirect(url_for("admin.customers"))
    new_state = 0 if customer["is_active"] else 1
    execute("UPDATE users SET is_active = ?, updated_at = ? WHERE id = ?", (new_state, iso_now(), user_id))
    audit("تغيير حالة عميل", f"{customer['name']} — {'تنشيط' if new_state else 'إيقاف'}")
    flash("تم تحديث حالة الحساب." if new_state else "تم إيقاف الحساب.", "success")
    return redirect(url_for("admin.customer_detail", user_id=user_id))


@bp.get("/requests")
@admin_required
def requests_list():
    status = request.args.get("status", "").strip()
    if status in {"new", "handled"}:
        rows = query(
            "SELECT * FROM contact_requests WHERE status = ? ORDER BY created_at DESC LIMIT 200",
            (status,),
        )
    else:
        rows = query("SELECT * FROM contact_requests ORDER BY created_at DESC LIMIT 200")
    return render_template(
        "admin/requests.html", page_title="طلبات التواصل", requests=rows, status=status
    )


@bp.post("/requests/<int:request_id>/status")
@admin_required
def request_status(request_id):
    row = query_one("SELECT * FROM contact_requests WHERE id = ?", (request_id,))
    if not row:
        flash("الطلب غير موجود.", "error")
        return redirect(url_for("admin.requests_list"))
    new_status = "handled" if row["status"] == "new" else "new"
    execute(
        "UPDATE contact_requests SET status = ?, handled_at = ? WHERE id = ?",
        (new_status, iso_now() if new_status == "handled" else None, request_id),
    )
    audit("تحديث طلب تواصل", f"#{request_id} — {new_status}")
    flash("تم تحديث حالة الطلب.", "success")
    return redirect(url_for("admin.requests_list"))


@bp.route("/settings", methods=["GET", "POST"])
@admin_required
def settings_page():
    settings = get_settings()
    if request.method == "POST":
        values = {key: request.form.get(key, "") for key in SETTING_KEYS}
        values["sms_status_updates"] = "1" if request.form.get("sms_status_updates") else "0"
        save_settings(values)
        audit("تعديل إعدادات الموقع", "تحديث بيانات الشركة والإشعارات")
        flash("تم حفظ الإعدادات.", "success")
        return redirect(url_for("admin.settings_page"))
    return render_template(
        "admin/settings.html", page_title="إعدادات الموقع", settings=settings
    )


@bp.route("/password", methods=["GET", "POST"])
@admin_required
def password():
    if request.method == "POST":
        current = request.form.get("current_password", "")
        new = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")
        admin = query_one("SELECT * FROM admins WHERE id = ?", (g.admin["id"],))
        errors = []
        if not admin or not verify_password(admin["password_hash"], current):
            errors.append("كلمة المرور الحالية غير صحيحة.")
        if len(new) < 10:
            errors.append("كلمة المرور الجديدة يجب أن تكون 10 أحرف على الأقل.")
        if new != confirm:
            errors.append("تأكيد كلمة المرور غير مطابق.")
        if errors:
            for error in errors:
                flash(error, "error")
            return render_template("admin/password.html", page_title="تغيير كلمة المرور"), 400
        execute(
            "UPDATE admins SET password_hash = ? WHERE id = ?",
            (hash_password(new), g.admin["id"]),
        )
        audit("تغيير كلمة مرور المدير", g.admin["email"])
        flash("تم تغيير كلمة المرور.", "success")
        return redirect(url_for("admin.dashboard"))
    return render_template("admin/password.html", page_title="تغيير كلمة المرور")


@bp.get("/audit")
@admin_required
def audit_log():
    rows = query(
        """
        SELECT a.*, ad.name AS admin_name, ad.email AS admin_email,
               st.name AS staff_name, st.email AS staff_email, b.name AS staff_branch
        FROM audit_log a
        LEFT JOIN admins ad ON ad.id = a.admin_id
        LEFT JOIN staff st ON st.id = a.staff_id
        LEFT JOIN branches b ON b.id = st.branch_id
        ORDER BY a.created_at DESC LIMIT 300
        """
    )
    return render_template("admin/audit.html", page_title="سجل النشاط", entries=rows)
