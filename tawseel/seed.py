from __future__ import annotations

import sys
from datetime import timedelta

from flask import current_app

from .db import execute, query_one
from .security import hash_password
from .utils import iso_now, utc_now

DEMO_BRANCH_CODE = "MCT"
DEMO_STAFF_EMAIL = "staff@tawseel.local"
DEMO_STAFF_PASSWORD = "Staff1234!"


def bootstrap(app) -> None:
    with app.app_context():
        _bootstrap_admin()
        if app.config["SEED_DEMO"]:
            _bootstrap_demo_branch()
            seed_demo(app, force=False)


def _ensure_demo_branch():
    branch = query_one("SELECT * FROM branches WHERE code = ?", (DEMO_BRANCH_CODE,))
    if branch:
        return branch
    execute(
        """
        INSERT INTO branches (code, name, city, address, phone, is_active, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 1, ?, ?)
        """,
        (
            DEMO_BRANCH_CODE,
            "فرع مسقط",
            "مسقط",
            "مسقط، سلطنة عُمان",
            "",
            iso_now(),
            iso_now(),
        ),
    )
    return query_one("SELECT * FROM branches WHERE code = ?", (DEMO_BRANCH_CODE,))


def _bootstrap_demo_branch() -> None:
    branch = _ensure_demo_branch()
    staff = query_one("SELECT id FROM staff WHERE email = ?", (DEMO_STAFF_EMAIL,))
    if not staff:
        execute(
            """
            INSERT INTO staff
                (branch_id, name, email, phone, password_hash, role,
                 is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'manager', 1, ?, ?)
            """,
            (
                branch["id"],
                "سالم المسؤولي",
                DEMO_STAFF_EMAIL,
                "",
                hash_password(DEMO_STAFF_PASSWORD),
                iso_now(),
                iso_now(),
            ),
        )
        if not current_app.config["IS_PRODUCTION"]:
            print(
                f"  Branch staff: {DEMO_STAFF_EMAIL} / {DEMO_STAFF_PASSWORD}  "
                "(development only — change before launch)",
                file=sys.stdout,
            )
    execute(
        "UPDATE shipments SET branch_id = ? WHERE branch_id IS NULL",
        (branch["id"],),
    )


def _bootstrap_admin() -> None:
    existing = query_one("SELECT COUNT(*) AS count FROM admins")
    if existing and existing["count"]:
        return
    email = current_app.config["ADMIN_EMAIL"]
    password = current_app.config["ADMIN_PASSWORD"]
    if not email or not password:
        if current_app.config["IS_PRODUCTION"]:
            raise RuntimeError(
                "No admin account exists. Set ADMIN_EMAIL and ADMIN_PASSWORD, "
                "or run: flask --app wsgi create-admin"
            )
        password = "Admin1234!"
    execute(
        "INSERT INTO admins (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
        (
            current_app.config["ADMIN_NAME"],
            email,
            hash_password(password),
            iso_now(),
        ),
    )
    if not current_app.config["IS_PRODUCTION"]:
        print(
            f"  Admin: {email} / {password}  (development only — change before launch)",
            file=sys.stdout,
        )


def seed_demo(app, force: bool = False) -> None:
    with app.app_context():
        existing = query_one("SELECT COUNT(*) AS count FROM shipments")
        if existing and existing["count"]:
            return

        branch = _ensure_demo_branch()
        now = utc_now()
        customer_rows = [
            {
                "name": "أحمد بن سالم",
                "phone": "+96891234567",
                "email": "ahmed@example.com",
                "company": "مؤسسة النخبة التجارية",
            },
            {
                "name": "مريم الهنائية",
                "phone": "+96899887766",
                "email": "maryam@example.com",
                "company": "",
            },
        ]
        customer_ids = []
        for customer in customer_rows:
            existing_user = query_one("SELECT id FROM users WHERE phone = ?", (customer["phone"],))
            if existing_user:
                customer_ids.append(existing_user["id"])
                continue
            cursor = execute(
                """
                INSERT INTO users (name, phone, email, company, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    customer["name"], customer["phone"], customer["email"], customer["company"],
                    iso_now(), iso_now(),
                ),
            )
            customer_ids.append(cursor.lastrowid)

        shipments = [
            {
                "code": "TS1392042",
                "customer": customer_ids[0],
                "sender_name": "مؤسسة النخبة التجارية",
                "sender_phone": "+96891234567",
                "origin": "مسقط",
                "destination": "صلالة",
                "service_type": "express",
                "status": "delivered",
                "weight_kg": 12.5,
                "pieces": 3,
                "description": "قطع غيار وملحقات مكتبية",
                "amount": 18.750,
                "age_days": 6,
                "events": [
                    ("pending", "مسقط", "تم إنشاء الشحنة وتسجيلها.", 6),
                    ("picked_up", "مسقط", "تم استلام الشحنة من المرسل.", 5),
                    ("in_transit", "مسقط", "غادرت الشحنة مركز الفرز.", 4),
                    ("delivered", "صلالة", "تم تسليم الشحنة للمستلم.", 2),
                ],
            },
            {
                "code": "TS2026001",
                "customer": customer_ids[0],
                "sender_name": "مؤسسة النخبة التجارية",
                "sender_phone": "+96891234567",
                "origin": "مسقط",
                "destination": "صحار",
                "service_type": "standard",
                "status": "in_transit",
                "weight_kg": 4.2,
                "pieces": 1,
                "description": "مستندات وعقود",
                "amount": 4.500,
                "age_days": 2,
                "events": [
                    ("pending", "مسقط", "تم إنشاء الشحنة وتسجيلها.", 2),
                    ("picked_up", "مسقط", "تم استلام الشحنة من المرسل.", 1),
                    ("in_transit", "الخوض", "الشحنة في مركز الفرز وتجهيزها للنقل.", 0),
                ],
            },
            {
                "code": "TS2026002",
                "customer": customer_ids[0],
                "sender_name": "مؤسسة النخبة التجارية",
                "sender_phone": "+96891234567",
                "origin": "مسقط",
                "destination": "نزوى",
                "service_type": "ecommerce",
                "status": "pending",
                "weight_kg": 8.0,
                "pieces": 2,
                "description": "طلبات متجر إلكتروني",
                "amount": 7.200,
                "age_days": 1,
                "events": [
                    ("pending", "مسقط", "تم إنشاء الشحنة وبانتظار الاستلام.", 1),
                ],
            },
            {
                "code": "TS2026003",
                "customer": customer_ids[0],
                "sender_name": "مؤسسة النخبة التجارية",
                "sender_phone": "+96891234567",
                "origin": "مسقط",
                "destination": "السيب",
                "service_type": "same_day",
                "status": "out_for_delivery",
                "weight_kg": 2.5,
                "pieces": 1,
                "description": "طرد صغير — تسليم نفس اليوم",
                "amount": 3.000,
                "age_days": 0,
                "events": [
                    ("pending", "مسقط", "تم إنشاء الشحنة وتسجيلها.", 0),
                    ("picked_up", "مسقط", "تم استلام الشحنة من المرسل.", 0),
                    ("out_for_delivery", "السيب", "الشحنة مع مندوب التوصيل.", 0),
                ],
            },
            {
                "code": "TS2026004",
                "customer": customer_ids[1],
                "sender_name": "مريم الهنائية",
                "sender_phone": "+96899887766",
                "origin": "صلالة",
                "destination": "مسقط",
                "service_type": "documents",
                "status": "delivered",
                "weight_kg": 0.5,
                "pieces": 1,
                "description": "ظرف مستندات",
                "amount": 2.500,
                "age_days": 3,
                "events": [
                    ("pending", "صلالة", "تم إنشاء الشحنة وتسجيلها.", 3),
                    ("picked_up", "صلالة", "تم استلام الشحنة من المرسل.", 2),
                    ("delivered", "مسقط", "تم تسليم الشحنة للمستلم.", 1),
                ],
            },
            {
                "code": "TS2026005",
                "customer": customer_ids[1],
                "sender_name": "مريم الهنائية",
                "sender_phone": "+96899887766",
                "origin": "مسقط",
                "destination": "صور",
                "service_type": "standard",
                "status": "cancelled",
                "weight_kg": 3.0,
                "pieces": 1,
                "description": "شحنة ملغاة بناءً على طلب العميل",
                "amount": 0.0,
                "age_days": 4,
                "events": [
                    ("pending", "مسقط", "تم إنشاء الشحنة وتسجيلها.", 4),
                    ("cancelled", "مسقط", "تم إلغاء الشحنة بناءً على طلب العميل.", 4),
                ],
            },
        ]

        for shipment in shipments:
            created = now - timedelta(days=shipment["age_days"])
            delivered_at = None
            if shipment["status"] == "delivered":
                delivered_at = (now - timedelta(days=max(0, shipment["age_days"] - 2))).replace(microsecond=0).isoformat()
            cursor = execute(
                """
                INSERT INTO shipments
                    (code, customer_id, branch_id, sender_name, sender_phone, origin, destination,
                     service_type, status, weight_kg, pieces, description, amount,
                     created_at, updated_at, delivered_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    shipment["code"], shipment["customer"], branch["id"], shipment["sender_name"],
                    shipment["sender_phone"], shipment["origin"], shipment["destination"],
                    shipment["service_type"], shipment["status"], shipment["weight_kg"],
                    shipment["pieces"], shipment["description"], shipment["amount"],
                    created.replace(microsecond=0).isoformat(), iso_now(), delivered_at,
                ),
            )
            shipment_id = cursor.lastrowid
            for status, location, note, days_ago in shipment["events"]:
                event_at = (now - timedelta(days=days_ago)).replace(microsecond=0).isoformat()
                execute(
                    """
                    INSERT INTO tracking_events (shipment_id, status, location, note, event_at, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (shipment_id, status, location, note, event_at, iso_now()),
                )
                execute(
                    """
                    INSERT INTO notifications (user_id, title, body, link, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        shipment["customer"],
                        f"تحديث شحنة {shipment['code']}",
                        note,
                        f"/dashboard/shipments/{shipment['code']}",
                        iso_now(),
                    ),
                )

        requests = [
            ("quote", "شركة الواحة للتجارة", "+96891112222", "ops@example.com", "مسقط", "صلالة", "25", "نحتاج عرض سعر أسبوعي لشحن طرود صغيرة.", "new", 1),
            ("contact", "خالد العامري", "+96893334444", "", "", "", "", "هل توصلون إلى المناطق الصناعية في صحار؟", "new", 0),
            ("quote", "متجر لمسة", "+96895556666", "hello@example.com", "مسقط", "جميع الولايات", "10", "حل توصيل للمتجر الإلكتروني مع الدفع عند الاستلام.", "handled", 5),
        ]
        for kind, name, phone, email, origin, destination, weight, message, status, days_ago in requests:
            created = (now - timedelta(days=days_ago)).replace(microsecond=0).isoformat()
            execute(
                """
                INSERT INTO contact_requests
                    (kind, name, phone, email, origin, destination, weight, message, status,
                     created_at, handled_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    kind, name, phone, email, origin, destination, weight, message, status,
                    created, created if status == "handled" else None,
                ),
            )
