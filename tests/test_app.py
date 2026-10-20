from __future__ import annotations

import contextlib
import io
import re
import tempfile
import unittest
from pathlib import Path

from tawseel import create_app
from tawseel.db import execute, query_one
from tawseel.utils import iso_now


class TawseelAppTestCase(unittest.TestCase):
    """Exercise the public site, customer portal and admin console."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.database = str(Path(self.temp_dir.name) / "tawseel-test.db")
        with contextlib.redirect_stdout(io.StringIO()):
            self.app = create_app(
                {
                    "TESTING": True,
                    "DATABASE": self.database,
                    "SECRET_KEY": "test-secret-key-that-is-long-enough-for-tests",
                    "IS_PRODUCTION": False,
                    "APP_ENV": "development",
                    "SEED_DEMO": True,
                    "ALLOW_DEV_OTP": True,
                    "SMS_PROVIDER": "log",
                    "ADMIN_EMAIL": "admin@test.local",
                    "ADMIN_PASSWORD": "Admin1234!",
                    "ADMIN_NAME": "Test Admin",
                    "PUBLIC_BASE_URL": "http://localhost",
                    "SESSION_COOKIE_SECURE": False,
                    "AUTH_COOKIE_SECURE": False,
                    "TRUST_PROXY": False,
                }
            )
        self.client = self.app.test_client()
        self.admin = self.app.test_client()
        self.staff = self.app.test_client()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def token(response) -> str:
        html = response.get_data(as_text=True)
        match = re.search(r'name="csrf_token" value="([^"]+)"', html)
        if not match:
            raise AssertionError("CSRF token was not found in the page.")
        return match.group(1)

    def login_admin(self, password: str = "Admin1234!", client=None) -> None:
        client = client or self.admin
        response = client.post(
            "/admin/login",
            data={
                "csrf_token": self.token(client.get("/admin/login")),
                "email": "admin@test.local",
                "password": password,
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].startswith("/admin"))

    def login_customer(self, phone: str = "91234567") -> None:
        html = self.client.get("/login").get_data(as_text=True)
        response = self.client.post(
            "/login",
            data={"csrf_token": self.token(self.client.get("/login")), "phone": phone},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/verify")

        html = self.client.get("/verify").get_data(as_text=True)
        match = re.search(r'<strong dir="ltr">(\d{6})</strong>', html)
        self.assertIsNotNone(match, "Development OTP was not rendered.")
        response = self.client.post(
            "/verify",
            data={"csrf_token": self.token(self.client.get("/verify")), "code": match.group(1)},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

    def login_staff(
        self,
        email: str = "staff@tawseel.local",
        password: str = "Staff1234!",
        client=None,
    ):
        client = client or self.staff
        page = client.get("/staff/login")
        response = client.post(
            "/staff/login",
            data={
                "csrf_token": self.token(page),
                "email": email,
                "password": password,
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].startswith("/staff"))
        return client

    # ------------------------------------------------------------------
    # Public site
    # ------------------------------------------------------------------
    def test_public_pages_and_assets(self) -> None:
        for path in (
            "/",
            "/services",
            "/about",
            "/contact",
            "/faq",
            "/track",
            "/track?code=TS1392042",
            "/privacy",
            "/terms",
            "/login",
            "/register",
            "/staff/login",
            "/health",
            "/robots.txt",
            "/sitemap.xml",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)

        missing = self.client.get("/does-not-exist")
        self.assertEqual(missing.status_code, 404)
        self.assertIn("الصفحة غير موجودة", missing.get_data(as_text=True))

        home_html = self.client.get("/").get_data(as_text=True)
        self.assertRegex(home_html, r"local/site\.css\?v=\d+")
        self.assertRegex(home_html, r"local/site\.js\?v=\d+")

        css = self.client.get("/assets/local/site.css")
        self.assertEqual(css.status_code, 200)
        self.assertIn("max-age=31536000", css.headers.get("Cache-Control", ""))
        css.close()

        robots = self.client.get("/robots.txt").get_data(as_text=True)
        self.assertIn("Disallow: /admin", robots)
        self.assertIn("Disallow: /staff", robots)
        self.assertIn("Disallow: /dashboard", robots)

    def test_api_tracking(self) -> None:
        response = self.client.get("/api/track/TS1392042")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["found"])
        self.assertEqual(payload["code"], "TS1392042")
        self.assertGreaterEqual(len(payload["events"]), 1)

        missing = self.client.get("/api/track/UNKNOWN")
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.get_json()["found"], False)

    def test_contact_submission_reaches_admin(self) -> None:
        html = self.client.get("/contact").get_data(as_text=True)
        response = self.client.post(
            "/contact",
            data={
                "csrf_token": self.token(self.client.get("/contact")),
                "kind": "quote",
                "name": "عميل الاختبار",
                "phone": "95551122",
                "email": "lead@example.com",
                "company": "شركة الاختبار",
                "origin": "مسقط",
                "destination": "صلالة",
                "weight": "12 كجم",
                "message": "نحتاج عرض سعر أسبوعي لشحن الطرود.",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("success=1", response.headers["Location"])

        with self.app.app_context():
            row = query_one(
                "SELECT * FROM contact_requests WHERE name = ? ORDER BY id DESC LIMIT 1",
                ("عميل الاختبار",),
            )
        self.assertIsNotNone(row)
        self.assertEqual(row["kind"], "quote")
        self.assertEqual(row["origin"], "مسقط")

        self.login_admin()
        page = self.admin.get("/admin/requests").get_data(as_text=True)
        self.assertIn("عميل الاختبار", page)
        self.assertIn("طلب عرض سعر", page)

    def test_contact_honeypot_does_not_create_request(self) -> None:
        with self.app.app_context():
            before = query_one("SELECT COUNT(*) AS count FROM contact_requests")["count"]
        self.client.get("/contact")
        response = self.client.post(
            "/contact",
            data={
                "csrf_token": self.token(self.client.get("/contact")),
                "website": "https://spam.example",
                "kind": "contact",
                "name": "Spam",
                "phone": "95551122",
                "message": "Spam message",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            after = query_one("SELECT COUNT(*) AS count FROM contact_requests")["count"]
        self.assertEqual(before, after)

    def test_contact_rate_limit(self) -> None:
        self.client.get("/contact")
        token = self.token(self.client.get("/contact"))
        for index in range(5):
            response = self.client.post(
                "/contact",
                data={
                    "csrf_token": token,
                    "kind": "contact",
                    "name": f"مرسل {index}",
                    "phone": "95551122",
                    "message": "استفسار لاختبار حد المعدل.",
                },
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 302)
        blocked = self.client.post(
            "/contact",
            data={
                "csrf_token": token,
                "kind": "contact",
                "name": "مرسل سادس",
                "phone": "95551122",
                "message": "استفسار زائد عن الحد.",
            },
            follow_redirects=False,
        )
        self.assertEqual(blocked.status_code, 400)
        self.assertIn("عدد كبير", blocked.get_data(as_text=True))

    # ------------------------------------------------------------------
    # Customer authentication and portal
    # ------------------------------------------------------------------
    def test_customer_otp_login_and_portal(self) -> None:
        self.login_customer()
        for path in (
            "/dashboard/",
            "/dashboard/shipments",
            "/dashboard/shipments?status=delivered",
            "/dashboard/shipments/TS2026001",
            "/dashboard/profile",
            "/dashboard/notifications",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)

        portal = self.client.get("/dashboard/").get_data(as_text=True)
        self.assertIn("أحمد بن سالم", portal)
        self.assertIn("TS2026001", portal)

    def test_customer_cannot_view_another_customers_shipment(self) -> None:
        self.login_customer()
        response = self.client.get("/dashboard/shipments/TS2026004")
        self.assertEqual(response.status_code, 404)

    def test_customer_registration_and_profile_update(self) -> None:
        self.client.get("/register")
        response = self.client.post(
            "/register",
            data={
                "csrf_token": self.token(self.client.get("/register")),
                "name": "سالم الجديد",
                "phone": "95551234",
                "email": "new@example.com",
                "company": "مؤسسة جديدة",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/verify")

        html = self.client.get("/verify").get_data(as_text=True)
        code = re.search(r'<strong dir="ltr">(\d{6})</strong>', html).group(1)
        response = self.client.post(
            "/verify",
            data={"csrf_token": self.token(self.client.get("/verify")), "code": code},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            user = query_one("SELECT * FROM users WHERE phone = ?", ("+96895551234",))
        self.assertIsNotNone(user)
        self.assertEqual(user["name"], "سالم الجديد")

        html = self.client.get("/dashboard/profile").get_data(as_text=True)
        response = self.client.post(
            "/dashboard/profile",
            data={
                "csrf_token": self.token(self.client.get("/dashboard/profile")),
                "name": "سالم المحدّث",
                "email": "updated@example.com",
                "company": "مؤسسة محدثة",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            user = query_one("SELECT * FROM users WHERE phone = ?", ("+96895551234",))
        self.assertEqual(user["name"], "سالم المحدّث")
        self.assertEqual(user["email"], "updated@example.com")

    def test_dashboard_requires_login(self) -> None:
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    # ------------------------------------------------------------------
    # Admin console
    # ------------------------------------------------------------------
    def test_admin_requires_login_and_rejects_bad_credentials(self) -> None:
        response = self.admin.get("/admin")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login", response.headers["Location"])

        html = self.admin.get("/admin/login").get_data(as_text=True)
        response = self.admin.post(
            "/admin/login",
            data={"csrf_token": self.token(self.admin.get("/admin/login")), "email": "admin@test.local", "password": "wrong-password"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 401)
        self.assertIn("غير صحيحة", response.get_data(as_text=True))

    def test_admin_shipment_crud_notifications_and_csv(self) -> None:
        self.login_admin()
        with self.app.app_context():
            customer = query_one("SELECT id FROM users ORDER BY id LIMIT 1")
            notifications_before = query_one(
                "SELECT COUNT(*) AS count FROM notifications WHERE user_id = ?",
                (customer["id"],),
            )["count"]

        response = self.admin.post(
            "/admin/shipments/new",
            data={
                "csrf_token": self.token(self.admin.get("/admin/shipments/new")),
                "code": "TSTEST01",
                "customer_id": str(customer["id"]),
                "service_type": "express",
                "status": "pending",
                "origin": "مسقط",
                "destination": "صلالة",
                "sender_name": "مرسل الاختبار",
                "sender_phone": "95550000",
                "weight_kg": "4.5",
                "pieces": "2",
                "amount": "12.500",
                "currency": "OMR",
                "description": "شحنة اختبار",
                "location": "مسقط",
                "note": "تم استلام الشحنة للاختبار.",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        with self.app.app_context():
            shipment = query_one("SELECT * FROM shipments WHERE code = 'TSTEST01'")
            self.assertIsNotNone(shipment)
            notifications_after = query_one(
                "SELECT COUNT(*) AS count FROM notifications WHERE user_id = ?",
                (customer["id"],),
            )["count"]
            events_after = query_one(
                "SELECT COUNT(*) AS count FROM tracking_events WHERE shipment_id = ?",
                (shipment["id"],),
            )["count"]
        self.assertEqual(notifications_after, notifications_before + 1)
        self.assertEqual(events_after, 1)
        shipment_id = shipment["id"]

        detail = self.admin.get(f"/admin/shipments/{shipment_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertIn("TSTEST01", detail.get_data(as_text=True))

        response = self.admin.post(
            f"/admin/shipments/{shipment_id}/edit",
            data={
                "csrf_token": self.token(detail),
                "customer_id": str(customer["id"]),
                "service_type": "express",
                "status": "delivered",
                "origin": "مسقط",
                "destination": "صلالة",
                "sender_name": "مرسل الاختبار",
                "sender_phone": "95550000",
                "weight_kg": "4.5",
                "pieces": "2",
                "amount": "12.500",
                "currency": "OMR",
                "description": "شحنة اختبار",
                "location": "صلالة",
                "note": "تم التوصيل بنجاح.",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        with self.app.app_context():
            shipment = query_one("SELECT * FROM shipments WHERE id = ?", (shipment_id,))
            notifications_after_edit = query_one(
                "SELECT COUNT(*) AS count FROM notifications WHERE user_id = ?",
                (customer["id"],),
            )["count"]
        self.assertEqual(shipment["status"], "delivered")
        self.assertIsNotNone(shipment["delivered_at"])
        self.assertEqual(notifications_after_edit, notifications_after + 1)

        detail = self.admin.get(f"/admin/shipments/{shipment_id}")
        response = self.admin.post(
            f"/admin/shipments/{shipment_id}/events",
            data={
                "csrf_token": self.token(detail),
                "event_status": "in_transit",
                "event_at": "2026-10-20T10:00",
                "event_location": "نزوى",
                "event_note": "الشحنة في الطريق عبر نزوى.",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            shipment = query_one("SELECT * FROM shipments WHERE id = ?", (shipment_id,))
            event = query_one(
                "SELECT * FROM tracking_events WHERE shipment_id = ? ORDER BY id DESC LIMIT 1",
                (shipment_id,),
            )
        self.assertEqual(shipment["status"], "in_transit")
        self.assertEqual(event["note"], "الشحنة في الطريق عبر نزوى.")

        csv_response = self.admin.get("/admin/shipments.csv")
        self.assertEqual(csv_response.status_code, 200)
        self.assertIn("text/csv", csv_response.headers["Content-Type"])
        self.assertIn("TSTEST01", csv_response.get_data(as_text=True))

    def test_generated_shipment_code_uses_tawseel_prefix(self) -> None:
        self.login_admin()
        with self.app.app_context():
            customer = query_one("SELECT id FROM users ORDER BY id LIMIT 1")

        response = self.admin.post(
            "/admin/shipments/new",
            data={
                "csrf_token": self.token(self.admin.get("/admin/shipments/new")),
                "code": "",
                "customer_id": str(customer["id"]),
                "service_type": "standard",
                "status": "pending",
                "origin": "مسقط",
                "destination": "صلالة",
                "sender_name": "مرسل الاختبار",
                "sender_phone": "95550000",
                "weight_kg": "1",
                "pieces": "1",
                "amount": "2.000",
                "currency": "OMR",
                "description": "اختبار توليد الكود",
                "location": "مسقط",
                "note": "تم إنشاء الشحنة للاختبار.",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            shipment = query_one("SELECT * FROM shipments ORDER BY id DESC LIMIT 1")
        self.assertRegex(shipment["code"], r"^TS\d{8}$")

    def test_admin_pagination_renders(self) -> None:
        self.login_admin()
        with self.app.app_context():
            customer = query_one("SELECT id FROM users ORDER BY id LIMIT 1")
            for index in range(20):
                execute(
                    """
                    INSERT INTO shipments
                        (code, customer_id, origin, destination, service_type, status,
                         pieces, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"TSPAGE{index:02d}",
                        customer["id"],
                        "مسقط",
                        "صلالة",
                        "standard",
                        "pending",
                        1,
                        iso_now(),
                        iso_now(),
                    ),
                )
        response = self.admin.get("/admin/shipments?page=2")
        self.assertEqual(response.status_code, 200)
        self.assertIn("صفحة 2", response.get_data(as_text=True))

        self.login_customer()
        response = self.client.get("/dashboard/shipments?page=2")
        self.assertEqual(response.status_code, 200)
        self.assertIn("صفحة 2", response.get_data(as_text=True))

    def test_admin_demo_data_page(self) -> None:
        response = self.admin.get("/admin/demo")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login", response.headers["Location"])

        self.login_admin()
        response = self.admin.get("/admin/demo")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("بيانات التجربة", html)
        self.assertIn("+96891234567", html)
        self.assertIn("TS2026001", html)
        self.assertIn("خطوات التجربة", html)
        self.assertIn("Admin1234!", html)
        self.assertIn("staff@tawseel.local", html)
        self.assertIn("Staff1234!", html)
        self.assertIn("بيانات التجربة", self.admin.get("/admin").get_data(as_text=True))

        self.app.config["IS_PRODUCTION"] = True
        production_html = self.admin.get("/admin/demo").get_data(as_text=True)
        self.assertNotIn("Admin1234!", production_html)
        self.assertNotIn("Staff1234!", production_html)
        self.assertIn("تُدار من إعدادات الأمان", production_html)

    def test_staff_portal_updates_and_branch_scope(self) -> None:
        anonymous = self.app.test_client()
        response = anonymous.get("/staff")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/staff/login", response.headers["Location"])

        self.login_staff()
        dashboard = self.staff.get("/staff/")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn("فرع مسقط", dashboard.get_data(as_text=True))
        self.assertIn("فريق الفرع", dashboard.get_data(as_text=True))
        self.assertEqual(self.staff.get("/staff/profile").status_code, 200)

        with self.app.app_context():
            branch = query_one("SELECT * FROM branches WHERE code = 'MCT'")
            own_shipment = query_one(
                "SELECT * FROM shipments WHERE code = 'TS2026002' AND branch_id = ?",
                (branch["id"],),
            )
            self.assertIsNotNone(own_shipment)
            notifications_before = query_one(
                "SELECT COUNT(*) AS count FROM notifications WHERE user_id = ?",
                (own_shipment["customer_id"],),
            )["count"]

            execute(
                """
                INSERT INTO branches (code, name, city, is_active, created_at, updated_at)
                VALUES (?, ?, ?, 1, ?, ?)
                """,
                ("SLL", "فرع صلالة", "صلالة", iso_now(), iso_now()),
            )
            other_branch = query_one("SELECT * FROM branches WHERE code = 'SLL'")
            cursor = execute(
                """
                INSERT INTO shipments
                    (code, branch_id, origin, destination, service_type, status,
                     pieces, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "TSSTAFFOTHER", other_branch["id"], "صلالة", "مسقط",
                    "standard", "pending", 1, iso_now(), iso_now(),
                ),
            )
            other_shipment_id = cursor.lastrowid
            own_shipment_id = own_shipment["id"]

        listing = self.staff.get("/staff/shipments").get_data(as_text=True)
        self.assertIn("TS2026002", listing)
        self.assertNotIn("TSSTAFFOTHER", listing)

        detail_page = self.staff.get(f"/staff/shipments/{own_shipment_id}")
        self.assertEqual(detail_page.status_code, 200)
        self.assertIn("TS2026002", detail_page.get_data(as_text=True))

        other_page = self.staff.get(f"/staff/shipments/{other_shipment_id}")
        self.assertEqual(other_page.status_code, 302)
        self.assertIn("/staff/shipments", other_page.headers["Location"])

        cross_update = self.staff.post(
            f"/staff/shipments/{other_shipment_id}/status",
            data={
                "csrf_token": self.token(detail_page),
                "status": "picked_up",
                "location": "صلالة",
                "note": "محاولة تحديث من فرع آخر.",
            },
            follow_redirects=False,
        )
        self.assertEqual(cross_update.status_code, 302)
        with self.app.app_context():
            other_shipment = query_one(
                "SELECT * FROM shipments WHERE id = ?", (other_shipment_id,)
            )
        self.assertEqual(other_shipment["status"], "pending")

        response = self.staff.post(
            f"/staff/shipments/{own_shipment_id}/status",
            data={
                "csrf_token": self.token(detail_page),
                "status": "picked_up",
                "location": "مسقط",
                "note": "تم استلام الشحنة من المرسل بواسطة فريق الفرع.",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            updated = query_one("SELECT * FROM shipments WHERE id = ?", (own_shipment_id,))
            event = query_one(
                "SELECT * FROM tracking_events WHERE shipment_id = ? ORDER BY id DESC LIMIT 1",
                (own_shipment_id,),
            )
            notifications_after = query_one(
                "SELECT COUNT(*) AS count FROM notifications WHERE user_id = ?",
                (updated["customer_id"],),
            )["count"]
        self.assertEqual(updated["status"], "picked_up")
        self.assertEqual(event["note"], "تم استلام الشحنة من المرسل بواسطة فريق الفرع.")
        self.assertEqual(notifications_after, notifications_before + 1)

        self.login_admin()
        audit_page = self.admin.get("/admin/audit").get_data(as_text=True)
        self.assertIn("سالم المسؤولي", audit_page)
        self.assertIn("تحديث شحنة", audit_page)

        response = self.staff.get("/admin")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login", response.headers["Location"])

        logout = self.staff.post(
            "/staff/logout",
            data={"csrf_token": self.token(self.staff.get("/staff/profile"))},
            follow_redirects=False,
        )
        self.assertEqual(logout.status_code, 302)
        self.assertEqual(self.staff.get("/staff").status_code, 302)

    def test_staff_audit_prefers_staff_actor_when_admin_cookie_also_present(self) -> None:
        dual = self.app.test_client()
        self.login_admin(client=dual)
        self.login_staff(client=dual)

        with self.app.app_context():
            shipment = query_one("SELECT * FROM shipments WHERE code = 'TS2026002'")
        detail = dual.get(f"/staff/shipments/{shipment['id']}")
        self.assertEqual(detail.status_code, 200)
        response = dual.post(
            f"/staff/shipments/{shipment['id']}/status",
            data={
                "csrf_token": self.token(detail),
                "status": "in_transit",
                "location": "مسقط",
                "note": "تحديث من جلسة تجمع الإدارة والفرع.",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            entry = query_one(
                "SELECT * FROM audit_log WHERE action = ? ORDER BY id DESC LIMIT 1",
                ("تحديث شحنة",),
            )
        self.assertIsNotNone(entry)
        self.assertEqual(entry["staff_id"], 1)
        self.assertIsNone(entry["admin_id"])
        self.assertEqual(dual.get("/admin").status_code, 200)

    def test_admin_creates_branch_staff_and_assigns_shipment(self) -> None:
        self.login_admin()
        self.assertEqual(self.admin.get("/admin/branches").status_code, 200)
        self.assertEqual(self.admin.get("/admin/staff").status_code, 200)

        page = self.admin.get("/admin/branches/new")
        response = self.admin.post(
            "/admin/branches/new",
            data={
                "csrf_token": self.token(page),
                "code": "SLL",
                "name": "فرع صلالة",
                "city": "صلالة",
                "address": "صلالة، سلطنة عُمان",
                "phone": "95550000",
                "is_active": "1",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            branch = query_one("SELECT * FROM branches WHERE code = 'SLL'")
            customer = query_one("SELECT id FROM users ORDER BY id LIMIT 1")
        self.assertIsNotNone(branch)
        self.assertIsNotNone(customer)

        page = self.admin.get("/admin/staff/new")
        response = self.admin.post(
            "/admin/staff/new",
            data={
                "csrf_token": self.token(page),
                "name": "موظف صلالة",
                "email": "staff.sll@test.local",
                "phone": "95551111",
                "branch_id": str(branch["id"]),
                "role": "manager",
                "is_active": "1",
                "password": "Staff1234!",
                "confirm_password": "Staff1234!",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            staff = query_one("SELECT * FROM staff WHERE email = 'staff.sll@test.local'")
        self.assertIsNotNone(staff)
        self.assertEqual(staff["branch_id"], branch["id"])

        page = self.admin.get("/admin/shipments/new")
        response = self.admin.post(
            "/admin/shipments/new",
            data={
                "csrf_token": self.token(page),
                "code": "TSSLL01",
                "customer_id": str(customer["id"]),
                "branch_id": str(branch["id"]),
                "service_type": "standard",
                "status": "pending",
                "origin": "صلالة",
                "destination": "مسقط",
                "sender_name": "مرسل صلالة",
                "sender_phone": "95552222",
                "weight_kg": "3.5",
                "pieces": "1",
                "amount": "5.000",
                "currency": "OMR",
                "description": "شحنة فرع صلالة",
                "location": "صلالة",
                "note": "تم إنشاء الشحنة للاختبار.",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            shipment = query_one("SELECT * FROM shipments WHERE code = 'TSSLL01'")
        self.assertEqual(shipment["branch_id"], branch["id"])

        branch_client = self.app.test_client()
        self.login_staff("staff.sll@test.local", "Staff1234!", client=branch_client)
        dashboard = branch_client.get("/staff/").get_data(as_text=True)
        self.assertIn("فرع صلالة", dashboard)
        listing = branch_client.get("/staff/shipments").get_data(as_text=True)
        self.assertIn("TSSLL01", listing)
        self.assertNotIn("TS2026001", listing)
        self.assertEqual(
            branch_client.get(f"/staff/shipments/{shipment['id']}").status_code, 200
        )

        edit_page = self.admin.get(f"/admin/staff/{staff['id']}/edit")
        response = self.admin.post(
            f"/admin/staff/{staff['id']}/edit",
            data={
                "csrf_token": self.token(edit_page),
                "name": staff["name"],
                "email": staff["email"],
                "phone": staff["phone"] or "",
                "branch_id": str(branch["id"]),
                "role": "manager",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            deactivated = query_one("SELECT * FROM staff WHERE id = ?", (staff["id"],))
            staff_sessions = query_one(
                "SELECT COUNT(*) AS count FROM staff_sessions WHERE staff_id = ?",
                (staff["id"],),
            )["count"]
        self.assertEqual(deactivated["is_active"], 0)
        self.assertEqual(staff_sessions, 0)
        self.assertEqual(branch_client.get("/staff/").status_code, 302)
        self.assertIn("/staff/login", branch_client.get("/staff/").headers["Location"])

    def test_admin_settings_and_password_change(self) -> None:
        self.login_admin()
        page = self.admin.get("/admin/settings")
        self.assertEqual(page.status_code, 200)
        response = self.admin.post(
            "/admin/settings",
            data={
                "csrf_token": self.token(page),
                "company_name": "توصيل",
                "company_name_en": "Tawseel",
                "tagline": "توصيل موثوق، في الوقت المناسب.",
                "phone": "+968 9000 0000",
                "whatsapp": "+968 9000 0000",
                "email": "info@example.com",
                "address": "مسقط، سلطنة عُمان",
                "working_hours": "الأحد – الخميس",
                "instagram": "",
                "twitter": "",
                "meta_description": "وصف تجريبي للموقع.",
                "sms_status_updates": "1",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            phone = query_one("SELECT value FROM settings WHERE key = 'phone'")["value"]
            sms = query_one("SELECT value FROM settings WHERE key = 'sms_status_updates'")["value"]
        self.assertEqual(phone, "+968 9000 0000")
        self.assertEqual(sms, "1")
        self.assertIn("+968 9000 0000", self.client.get("/").get_data(as_text=True))

        wrong = self.admin.post(
            "/admin/password",
            data={
                "csrf_token": self.token(self.admin.get("/admin/password")),
                "current_password": "wrong",
                "new_password": "NewPassword123!",
                "confirm_password": "NewPassword123!",
            },
            follow_redirects=False,
        )
        self.assertEqual(wrong.status_code, 400)

        changed = self.admin.post(
            "/admin/password",
            data={
                "csrf_token": self.token(self.admin.get("/admin/password")),
                "current_password": "Admin1234!",
                "new_password": "NewPassword123!",
                "confirm_password": "NewPassword123!",
            },
            follow_redirects=False,
        )
        self.assertEqual(changed.status_code, 302)

        token = self.token(self.admin.get("/admin"))
        self.admin.post("/admin/logout", data={"csrf_token": token})
        self.login_admin("NewPassword123!")

    def test_csrf_rejection_and_security_headers(self) -> None:
        response = self.client.post("/contact", data={"name": "No token"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("انتهت صلاحية النموذج", response.get_data(as_text=True))

        response = self.client.get("/")
        headers = response.headers
        self.assertIn("Content-Security-Policy", headers)
        self.assertIn("nonce-", headers["Content-Security-Policy"])
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["Cache-Control"], "no-store")


if __name__ == "__main__":
    unittest.main(verbosity=2)
