from __future__ import annotations

import functools
import hashlib
import hmac
import secrets
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

from flask import (
    abort,
    current_app,
    g,
    redirect,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from .db import execute, get_db, query_one


# ---------------------------------------------------------------------------
# Password hashing / tokens
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    return generate_password_hash(password, method="scrypt")


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return check_password_hash(password_hash, password)
    except (ValueError, TypeError):
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_otp(code: str) -> str:
    secret = current_app.config["SECRET_KEY"].encode("utf-8")
    return hmac.new(secret, code.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_otp(code: str, expected_hash: str) -> bool:
    return hmac.compare_digest(hash_otp(code), expected_hash)


def generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


# ---------------------------------------------------------------------------
# Authentication sessions
# ---------------------------------------------------------------------------

def create_auth_session(user_id: int | None = None, admin_id: int | None = None) -> str:
    token = secrets.token_urlsafe(40)
    now = int(time.time())
    ttl = current_app.config["AUTH_SESSION_TTL"]
    execute(
        "DELETE FROM auth_sessions WHERE expires_at <= ?",
        (now,),
    )
    execute(
        """
        INSERT INTO auth_sessions
            (token_hash, user_id, admin_id, created_at, expires_at, last_seen, ip, user_agent)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _token_hash(token),
            user_id,
            admin_id,
            now,
            now + ttl,
            now,
            client_ip(),
            (request.user_agent.string or "")[:300],
        ),
    )
    return token


def create_staff_session(staff_id: int) -> str:
    token = secrets.token_urlsafe(40)
    now = int(time.time())
    ttl = current_app.config["STAFF_SESSION_TTL"]
    execute("DELETE FROM staff_sessions WHERE expires_at <= ?", (now,))
    execute(
        """
        INSERT INTO staff_sessions
            (token_hash, staff_id, created_at, expires_at, last_seen, ip, user_agent)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _token_hash(token),
            staff_id,
            now,
            now + ttl,
            now,
            client_ip(),
            (request.user_agent.string or "")[:300],
        ),
    )
    return token


def set_auth_cookie(response, token: str):
    response.set_cookie(
        current_app.config["AUTH_COOKIE_NAME"],
        token,
        max_age=current_app.config["AUTH_SESSION_TTL"],
        httponly=True,
        secure=current_app.config["AUTH_COOKIE_SECURE"],
        samesite="Lax",
        path="/",
    )
    return response


def clear_auth_cookie(response):
    response.delete_cookie(
        current_app.config["AUTH_COOKIE_NAME"],
        path="/",
        secure=current_app.config["AUTH_COOKIE_SECURE"],
        httponly=True,
        samesite="Lax",
    )
    return response


def set_staff_cookie(response, token: str):
    response.set_cookie(
        current_app.config["STAFF_COOKIE_NAME"],
        token,
        max_age=current_app.config["STAFF_SESSION_TTL"],
        httponly=True,
        secure=current_app.config["STAFF_COOKIE_SECURE"],
        samesite="Lax",
        path="/",
    )
    return response


def clear_staff_cookie(response):
    response.delete_cookie(
        current_app.config["STAFF_COOKIE_NAME"],
        path="/",
        secure=current_app.config["STAFF_COOKIE_SECURE"],
        httponly=True,
        samesite="Lax",
    )
    return response


def load_auth() -> None:
    g.user = None
    g.admin = None
    g.auth_session = None
    token = request.cookies.get(current_app.config["AUTH_COOKIE_NAME"])
    if not token:
        return
    row = query_one(
        """
        SELECT s.*, u.name AS user_name, u.phone AS user_phone, u.email AS user_email,
               u.company AS user_company, u.is_active AS user_active,
               a.name AS admin_name, a.email AS admin_email, a.is_active AS admin_active
        FROM auth_sessions s
        LEFT JOIN users u ON u.id = s.user_id
        LEFT JOIN admins a ON a.id = s.admin_id
        WHERE s.token_hash = ? AND s.expires_at > ?
        """,
        (_token_hash(token), int(time.time())),
    )
    if not row:
        return
    if row["user_id"] and row["user_active"]:
        g.user = {
            "id": row["user_id"],
            "name": row["user_name"],
            "phone": row["user_phone"],
            "email": row["user_email"],
            "company": row["user_company"],
        }
    elif row["admin_id"] and row["admin_active"]:
        g.admin = {
            "id": row["admin_id"],
            "name": row["admin_name"],
            "email": row["admin_email"],
        }
    else:
        return
    g.auth_session = {
        "id": row["id"],
        "user_id": row["user_id"],
        "admin_id": row["admin_id"],
    }
    if int(time.time()) - row["last_seen"] > 300:
        execute("UPDATE auth_sessions SET last_seen = ? WHERE id = ?", (int(time.time()), row["id"]))


def load_staff() -> None:
    g.staff = None
    g.staff_session = None
    token = request.cookies.get(current_app.config["STAFF_COOKIE_NAME"])
    if not token:
        return
    row = query_one(
        """
        SELECT ss.id AS session_id, ss.staff_id, ss.last_seen,
               st.name, st.email, st.phone, st.role, st.is_active AS staff_active,
               b.id AS branch_id, b.code AS branch_code, b.name AS branch_name,
               b.city AS branch_city, b.phone AS branch_phone, b.is_active AS branch_active
        FROM staff_sessions ss
        JOIN staff st ON st.id = ss.staff_id
        JOIN branches b ON b.id = st.branch_id
        WHERE ss.token_hash = ? AND ss.expires_at > ?
        """,
        (_token_hash(token), int(time.time())),
    )
    if not row or not row["staff_active"] or not row["branch_active"]:
        return
    g.staff = {
        "id": row["staff_id"],
        "name": row["name"],
        "email": row["email"],
        "phone": row["phone"],
        "role": row["role"],
        "branch_id": row["branch_id"],
        "branch_code": row["branch_code"],
        "branch_name": row["branch_name"],
        "branch_city": row["branch_city"],
        "branch_phone": row["branch_phone"],
    }
    g.staff_session = {"id": row["session_id"], "staff_id": row["staff_id"]}
    if int(time.time()) - row["last_seen"] > 300:
        execute(
            "UPDATE staff_sessions SET last_seen = ? WHERE id = ?",
            (int(time.time()), row["session_id"]),
        )


def logout_current_session() -> None:
    if g.get("auth_session"):
        execute("DELETE FROM auth_sessions WHERE id = ?", (g.auth_session["id"],))


def logout_current_staff_session() -> None:
    if g.get("staff_session"):
        execute("DELETE FROM staff_sessions WHERE id = ?", (g.staff_session["id"],))


def customer_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not g.get("user"):
            return redirect(url_for("auth.login", next=request.full_path if request.query_string else request.path))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not g.get("admin"):
            return redirect(url_for("admin.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def staff_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not g.get("staff"):
            return redirect(url_for("staff.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


# ---------------------------------------------------------------------------
# CSRF
# ---------------------------------------------------------------------------

def csrf_token() -> str:
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def validate_csrf() -> None:
    if request.method != "POST":
        return
    sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
    expected = session.get("csrf_token")
    if not expected or not sent or not hmac.compare_digest(str(sent), str(expected)):
        abort(400, description="انتهت صلاحية النموذج. حدّث الصفحة وحاول مرة أخرى.")


def safe_next_url(target: str | None, fallback: str) -> str:
    if not target:
        return fallback
    parts = urlsplit(target)
    if parts.scheme or parts.netloc or not target.startswith("/") or target.startswith("//"):
        return fallback
    return target


# ---------------------------------------------------------------------------
# Rate limiting (SQLite-backed so it also works with multiple threads)
# ---------------------------------------------------------------------------

def rate_limit(key: str, limit: int, window_seconds: int) -> bool:
    """Return True when the action is allowed, False when the limit is reached."""
    now = int(time.time())
    connection = get_db()
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT window_start, count FROM rate_limits WHERE key = ?", (key,)
        ).fetchone()
        if not row or now - row["window_start"] >= window_seconds:
            connection.execute(
                """
                INSERT INTO rate_limits (key, window_start, count) VALUES (?, ?, 1)
                ON CONFLICT(key) DO UPDATE SET window_start = excluded.window_start, count = 1
                """,
                (key, now),
            )
            connection.commit()
            return True
        if row["count"] >= limit:
            connection.rollback()
            return False
        connection.execute(
            "UPDATE rate_limits SET count = count + 1 WHERE key = ?", (key,)
        )
        connection.commit()
        return True
    except Exception:
        connection.rollback()
        raise


def client_ip() -> str:
    # ProxyFix rewrites ``remote_addr`` only when TRUST_PROXY is enabled, so
    # this cannot be spoofed with a raw X-Forwarded-For header on a direct
    # connection.
    return request.remote_addr or "unknown"


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------

def audit(action: str, detail: str = "") -> None:
    # A browser can hold both an admin and a staff session. Attribute staff
    # portal actions to the staff member rather than to the separate admin
    # session that happens to share the same cookie jar.
    staff = g.get("staff") if request.blueprint == "staff" else None
    admin = g.get("admin") if not staff else None
    if not admin and not staff:
        admin = g.get("admin")
        staff = g.get("staff") if not admin else None
    execute(
        "INSERT INTO audit_log (admin_id, staff_id, action, detail, ip, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            admin["id"] if admin else None,
            staff["id"] if staff else None,
            action[:120],
            detail[:2000],
            client_ip(),
            datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        ),
    )
