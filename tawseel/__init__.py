from __future__ import annotations

import secrets
import sys
from datetime import datetime
from pathlib import Path

import click
from flask import Flask, g, jsonify, render_template, request, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import Config
from .db import get_db, init_app as init_db_app, init_db, query_one
from .security import (
    csrf_token,
    hash_password,
    load_auth,
    load_staff,
    validate_csrf,
)
from .settings import get_settings
from .utils import (
    format_date,
    format_datetime,
    format_money,
    format_phone,
    format_weight,
    iso_now,
    mask_phone,
    service_label,
    staff_role_label,
    status_meta,
)


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(
        __name__,
        static_folder=Config.STATIC_DIR,
        static_url_path=Config.STATIC_URL_PATH,
    )
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)

    if app.config.get("TRUST_PROXY"):
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    init_db_app(app)
    with app.app_context():
        init_db()
        from .seed import bootstrap
        bootstrap(app)

    from .admin import bp as admin_bp
    from .auth import bp as auth_bp
    from .customer import bp as customer_bp
    from .public import bp as public_bp
    from .staff import bp as staff_bp

    app.register_blueprint(public_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(customer_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(staff_bp)

    @app.before_request
    def before_request():
        g.nonce = secrets.token_urlsafe(16)
        load_auth()
        load_staff()
        validate_csrf()

    @app.context_processor
    def inject_globals():
        try:
            settings = get_settings()
        except Exception:
            # Keep the error page renderable during a database outage.
            app.logger.exception("Could not load site settings")
            settings = dict(app.config["COMPANY_DEFAULTS"])
        unread = 0
        new_requests = 0
        try:
            if g.get("user"):
                row = query_one(
                    "SELECT COUNT(*) AS count FROM notifications WHERE user_id = ? AND read_at IS NULL",
                    (g.user["id"],),
                )
                unread = row["count"] if row else 0
            if g.get("admin"):
                row = query_one("SELECT COUNT(*) AS count FROM contact_requests WHERE status = 'new'")
                new_requests = row["count"] if row else 0
        except Exception:
            app.logger.exception("Could not load notification counters")

        def page_url(page: int) -> str:
            args = request.args.to_dict(flat=True)
            args["page"] = page
            return url_for(request.endpoint, **args)

        return {
            "settings": settings,
            "csrf_token": csrf_token,
            "current_user": g.get("user"),
            "current_admin": g.get("admin"),
            "current_staff": g.get("staff"),
            "unread_notifications": unread,
            "new_requests": new_requests,
            "nonce": g.get("nonce", ""),
            "current_year": datetime.now().year,
            "current_path": request.path,
            "allow_dev_otp": app.config["ALLOW_DEV_OTP"],
            "page_url": page_url,
        }

    app.jinja_env.filters["datetime"] = format_datetime
    app.jinja_env.filters["date"] = format_date
    app.jinja_env.filters["money"] = format_money
    app.jinja_env.filters["weight"] = format_weight
    app.jinja_env.filters["phone"] = format_phone
    app.jinja_env.filters["mask_phone"] = mask_phone
    app.jinja_env.filters["service"] = service_label
    app.jinja_env.filters["staff_role"] = staff_role_label
    app.jinja_env.globals["status_meta"] = status_meta
    app.jinja_env.globals["sms_ready"] = _sms_ready
    app.jinja_env.globals["sms_provider"] = lambda: app.config["SMS_PROVIDER"]

    static_root = Path(app.static_folder)
    asset_version_cache: dict[str, int] = {}

    @app.template_global()
    def asset_url(filename: str) -> str:
        """Add a cache-busting version based on the asset's modification time.

        The stat result is memoised for the life of the process so that pages
        referencing several assets do not hit the filesystem on every render.
        Restart the app (or bump the file and restart) to refresh versions.
        """
        version = asset_version_cache.get(filename)
        if version is None:
            try:
                version = int((static_root / filename).stat().st_mtime)
            except OSError:
                version = 0
            asset_version_cache[filename] = version
        return url_for("static", filename=filename, v=version)

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        nonce = g.get("nonce", "")
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            f"script-src 'self' 'nonce-{nonce}'; "
            "style-src 'self'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
        if app.config.get("IS_PRODUCTION") and request.is_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if response.mimetype == "text/html":
            response.headers["Cache-Control"] = "no-store"
        elif request.path.startswith("/assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response

    @app.errorhandler(400)
    def bad_request(error):
        if request.path.startswith("/api/"):
            return jsonify({"error": "bad_request", "message": str(error.description)}), 400
        return _render_error("طلب غير صالح", str(error.description), 400)

    @app.errorhandler(403)
    def forbidden(error):
        if request.path.startswith("/api/"):
            return jsonify({"error": "forbidden"}), 403
        return _render_error("غير مسموح", "لا تملك صلاحية الوصول إلى هذه الصفحة.", 403)

    @app.errorhandler(404)
    def not_found(error):
        if request.path.startswith("/api/"):
            return jsonify({"error": "not_found"}), 404
        return _render_error(
            "الصفحة غير موجودة",
            "الرابط الذي طلبته غير متوفر. يمكنك العودة إلى الرئيسية أو تتبع شحنتك.",
            404,
        )

    @app.errorhandler(413)
    def too_large(error):
        if request.path.startswith("/api/"):
            return jsonify({"error": "payload_too_large"}), 413
        return _render_error("الطلب كبير جداً", "حجم البيانات المرسلة أكبر من الحد المسموح.", 413)

    @app.errorhandler(500)
    def server_error(error):
        app.logger.exception("Unhandled error: %s", error)
        if request.path.startswith("/api/"):
            return jsonify({"error": "server_error"}), 500
        return _render_error(
            "حدث خطأ غير متوقع",
            "تعذر إكمال الطلب. حاول مرة أخرى، وإذا استمرت المشكلة فتواصل معنا.",
            500,
        )

    @app.cli.command("create-admin")
    @click.option("--email", prompt=True)
    @click.option("--name", prompt=True)
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    def create_admin(email, name, password):
        """Create an additional administrator account."""
        email = email.strip().lower()
        if query_one("SELECT id FROM admins WHERE email = ?", (email,)):
            raise click.ClickException("An admin with this email already exists.")
        get_db().execute(
            "INSERT INTO admins (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
            (name.strip(), email, hash_password(password), iso_now()),
        )
        get_db().commit()
        click.echo(f"Admin {email} created.")

    @app.cli.command("set-admin-password")
    @click.option("--email", prompt=True)
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    def set_admin_password(email, password):
        """Change an administrator password."""
        email = email.strip().lower()
        row = query_one("SELECT id FROM admins WHERE email = ?", (email,))
        if not row:
            raise click.ClickException("Admin not found.")
        get_db().execute(
            "UPDATE admins SET password_hash = ? WHERE id = ?",
            (hash_password(password), row["id"]),
        )
        get_db().commit()
        click.echo("Password updated.")

    if not app.config["IS_PRODUCTION"]:
        pass
    elif app.config["SMS_PROVIDER"] == "log":
        print(
            "WARNING: SMS_PROVIDER=log in production. Configure Twilio or Unifonic "
            "before accepting customer logins.",
            file=sys.stderr,
        )

    return app


def _sms_ready() -> bool:
    from .sms import sms_ready

    return sms_ready()


def _render_error(title: str, message: str, status: int):
    return (
        render_template("errors/error.html", title=title, message=message, status=status),
        status,
    )
