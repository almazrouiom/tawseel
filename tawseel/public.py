from __future__ import annotations

import re
from datetime import datetime, timezone

from flask import (
    Blueprint,
    Response,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)

from .db import query, query_one
from .security import client_ip, rate_limit
from .settings import get_settings
from .utils import (
    format_input_datetime,
    format_phone,
    normalize_code,
    normalize_phone,
    service_label,
    status_meta,
    valid_phone,
)

bp = Blueprint("public", __name__)

PUBLIC_PAGES = (
    ("/", "الرئيسية", 1.0),
    ("/services", "خدماتنا", 0.9),
    ("/about", "من نحن", 0.7),
    ("/contact", "اتصل بنا", 0.8),
    ("/faq", "الأسئلة الشائعة", 0.6),
    ("/track", "تتبع الشحنة", 0.9),
    ("/privacy", "سياسة الخصوصية", 0.3),
    ("/terms", "الشروط والأحكام", 0.3),
)


def find_shipment(code: str):
    normalized = normalize_code(code)
    if not normalized:
        return None
    return query_one(
        """
        SELECT s.*, u.name AS customer_name, u.phone AS customer_phone
        FROM shipments s
        LEFT JOIN users u ON u.id = s.customer_id
        WHERE s.code = ?
        """,
        (normalized,),
    )


def shipment_events(shipment_id: int):
    return query(
        """
        SELECT * FROM tracking_events
        WHERE shipment_id = ?
        ORDER BY event_at DESC, id DESC
        """,
        (shipment_id,),
    )


def _contact_values() -> dict:
    return {
        "name": request.form.get("name", "").strip(),
        "phone": request.form.get("phone", "").strip(),
        "email": request.form.get("email", "").strip(),
        "company": request.form.get("company", "").strip(),
        "origin": request.form.get("origin", "").strip(),
        "destination": request.form.get("destination", "").strip(),
        "weight": request.form.get("weight", "").strip(),
        "message": request.form.get("message", "").strip(),
        "kind": "quote" if request.form.get("kind") == "quote" else "contact",
    }


@bp.get("/")
def home():
    settings = get_settings()
    return render_template(
        "public/home.html",
        page_title=settings["company_name"],
        page_description=settings["meta_description"],
        tracking_code=request.args.get("code", ""),
    )


@bp.get("/services")
def services():
    return render_template(
        "public/services.html",
        page_title="خدماتنا",
        page_description="حلول توصيل وشحن للشركات والأفراد: توصيل سريع، شحن تجاري، مستندات، وحلول المتاجر الإلكترونية.",
    )


@bp.get("/about")
def about():
    return render_template(
        "public/about.html",
        page_title="من نحن",
        page_description="تعرّف على توصيل ورؤيتنا في تقديم تجربة توصيل موثوقة في سلطنة عُمان.",
    )


@bp.get("/faq")
def faq():
    return render_template(
        "public/faq.html",
        page_title="الأسئلة الشائعة",
        page_description="إجابات عن الأسئلة المتكررة حول التوصيل، تتبع الشحنات، الأسعار، وخدمات توصيل.",
    )


@bp.get("/privacy")
def privacy():
    return render_template(
        "public/privacy.html",
        page_title="سياسة الخصوصية",
        page_description="كيف نجمع بياناتك ونستخدمها ونحميها في توصيل.",
    )


@bp.get("/terms")
def terms():
    return render_template(
        "public/terms.html",
        page_title="الشروط والأحكام",
        page_description="شروط استخدام موقع وخدمات توصيل.",
    )


@bp.route("/contact", methods=["GET", "POST"])
def contact():
    values = {"kind": request.args.get("type", "contact")}
    if request.method == "POST":
        values = _contact_values()
        if request.form.get("website"):
            return redirect(url_for("public.contact", success="1"))
        errors = []
        if len(values["name"]) < 2:
            errors.append("يرجى إدخال الاسم.")
        if not valid_phone(values["phone"], current_app.config["DEFAULT_COUNTRY_CODE"]):
            errors.append("يرجى إدخال رقم هاتف صحيح.")
        if values["email"] and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", values["email"]):
            errors.append("يرجى إدخال بريد إلكتروني صحيح.")
        if len(values["message"]) < 5:
            errors.append("يرجى كتابة تفاصيل الطلب.")
        if values["kind"] == "quote" and (not values["origin"] or not values["destination"]):
            errors.append("يرجى تحديد مدينة الإرسال والوصول.")
        if not rate_limit(f"contact:{client_ip()}", 5, 3600):
            errors.append("تم إرسال عدد كبير من الطلبات. يرجى المحاولة لاحقاً.")
        if errors:
            for error in errors:
                flash(error, "error")
            return render_template(
                "public/contact.html",
                page_title="اتصل بنا",
                page_description="اطلب عرض سعر أو تواصل مع فريق توصيل.",
                values=values,
            ), 400
        from .db import execute
        from .utils import iso_now, normalize_phone
        execute(
            """
            INSERT INTO contact_requests
                (kind, name, phone, email, company, origin, destination, weight, message, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                values["kind"], values["name"],
                normalize_phone(values["phone"], current_app.config["DEFAULT_COUNTRY_CODE"]),
                values["email"], values["company"], values["origin"],
                values["destination"], values["weight"], values["message"], iso_now(),
            ),
        )
        return redirect(url_for("public.contact", success="1"))
    return render_template(
        "public/contact.html",
        page_title="اتصل بنا",
        page_description="اطلب عرض سعر أو تواصل مع فريق توصيل.",
        values=values,
    )


@bp.get("/track")
def track():
    code = normalize_code(request.args.get("code", ""))
    shipment = find_shipment(code) if code else None
    events = shipment_events(shipment["id"]) if shipment else []
    return render_template(
        "public/track.html",
        page_title="تتبع الشحنة",
        page_description="تتبع شحنتك لحظة بلحظة باستخدام رقم الشحنة.",
        code=code,
        shipment=shipment,
        events=events,
    )


@bp.get("/api/track")
@bp.get("/api/track/<code>")
def api_track(code: str | None = None):
    if not rate_limit(f"api-track:{client_ip()}", 120, 60):
        return jsonify({"error": "rate_limited", "message": "Too many requests."}), 429
    code = normalize_code(code or request.args.get("code", ""))
    shipment = find_shipment(code)
    if not shipment:
        return jsonify({"found": False, "code": code}), 404
    events = shipment_events(shipment["id"])
    return jsonify(
        {
            "found": True,
            "code": shipment["code"],
            "status": status_meta(shipment["status"])["label"],
            "status_key": shipment["status"],
            "service": service_label(shipment["service_type"]),
            "origin": shipment["origin"],
            "destination": shipment["destination"],
            "pieces": shipment["pieces"],
            "weight_kg": shipment["weight_kg"],
            "created_at": shipment["created_at"],
            "updated_at": shipment["updated_at"],
            "delivered_at": shipment["delivered_at"],
            "events": [
                {
                    "status": status_meta(event["status"])["label"],
                    "status_key": event["status"],
                    "location": event["location"],
                    "note": event["note"],
                    "at": event["event_at"],
                }
                for event in events
            ],
        }
    )


@bp.get("/health")
def health():
    database_ok = True
    try:
        query_one("SELECT 1 AS ok")
    except Exception:
        database_ok = False
    from .sms import sms_ready
    return jsonify(
        {
            "status": "ok" if database_ok else "degraded",
            "database": "ok" if database_ok else "error",
            "sms": "ready" if sms_ready() else "not_configured",
            "version": "2.0.0",
        }
    ), (200 if database_ok else 503)


@bp.get("/robots.txt")
def robots():
    base = current_app.config["PUBLIC_BASE_URL"]
    content = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /admin\n"
        "Disallow: /dashboard\n"
        "Disallow: /staff\n"
        "Disallow: /verify\n"
        "Disallow: /api/\n"
        f"Sitemap: {base}/sitemap.xml\n"
    )
    return Response(content, mimetype="text/plain")


@bp.get("/sitemap.xml")
def sitemap():
    base = current_app.config["PUBLIC_BASE_URL"]
    urls = "".join(
        f"<url><loc>{base}{path}</loc><changefreq>weekly</changefreq>"
        f"<priority>{priority:.1f}</priority></url>"
        for path, _label, priority in PUBLIC_PAGES
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{urls}</urlset>"
    )
    return Response(xml, mimetype="application/xml")


@bp.get("/favicon.ico")
def favicon():
    return send_from_directory(
        current_app.static_folder, "media/logos/favicon-32x32.png", mimetype="image/png"
    )


@bp.get("/site.webmanifest")
def manifest():
    response = send_from_directory(
        current_app.static_folder, "media/logos/site.webmanifest", mimetype="application/manifest+json"
    )
    return response
