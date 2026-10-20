from __future__ import annotations

import re
import time

from flask import (
    Blueprint,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from .db import execute, query_one
from .security import (
    clear_auth_cookie,
    client_ip,
    create_auth_session,
    generate_otp,
    hash_otp,
    logout_current_session,
    rate_limit,
    safe_next_url,
    set_auth_cookie,
    verify_otp,
)
from .sms import SmsError, send_otp
from .utils import iso_now, mask_phone, normalize_phone as normalize_phone_util, valid_phone

bp = Blueprint("auth", __name__)


def _phone(raw: str | None) -> str:
    return normalize_phone_util(raw, current_app.config["DEFAULT_COUNTRY_CODE"])


def _email_valid(email: str) -> bool:
    return bool(not email or re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email))


def _start_challenge(
    phone: str,
    purpose: str,
    name: str = "",
    email: str = "",
    company: str = "",
) -> int | None:
    code = generate_otp()
    now = int(time.time())
    if not rate_limit(f"otp:ip:{client_ip()}", 12, 900):
        flash("تم إرسال رموز كثيرة من هذا الجهاز. يرجى المحاولة بعد قليل.", "error")
        return None
    if not rate_limit(f"otp:phone:{phone}", current_app.config["OTP_RATE_LIMIT"], 900):
        flash("تم إرسال رموز كثيرة إلى هذا الرقم. يرجى المحاولة بعد قليل.", "error")
        return None

    cursor = execute(
        """
        INSERT INTO otp_challenges
            (phone, code_hash, dev_code, purpose, name, email, company, expires_at,
             attempts, resends, created_at, sent_at, ip)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?)
        """,
        (
            phone,
            hash_otp(code),
            code if current_app.config["ALLOW_DEV_OTP"] else None,
            purpose,
            name.strip() or None,
            email.strip() or None,
            company.strip() or None,
            now + current_app.config["OTP_TTL_SECONDS"],
            now,
            now,
            client_ip(),
        ),
    )
    challenge_id = cursor.lastrowid
    try:
        send_otp(phone, code, purpose)
    except SmsError as exc:
        execute("DELETE FROM otp_challenges WHERE id = ?", (challenge_id,))
        current_app.logger.error("OTP delivery failed for %s: %s", mask_phone(phone), exc)
        flash("تعذر إرسال رمز التحقق الآن. يرجى المحاولة لاحقاً أو التواصل معنا.", "error")
        return None
    execute("DELETE FROM otp_challenges WHERE consumed_at IS NOT NULL OR expires_at < ?", (now - 86400,))
    session["otp_id"] = challenge_id
    session.permanent = True
    return challenge_id


def _get_challenge():
    challenge_id = session.get("otp_id")
    if not challenge_id:
        return None
    return query_one(
        "SELECT * FROM otp_challenges WHERE id = ? AND consumed_at IS NULL",
        (challenge_id,),
    )


def _otp_view(challenge, error: str = "", status: int = 200):
    now = int(time.time())
    return (
        render_template(
            "auth/otp.html",
            page_title="رمز التحقق",
            challenge=challenge,
            error=error,
            masked_phone=mask_phone(challenge["phone"]),
            dev_code=challenge["dev_code"] if current_app.config["ALLOW_DEV_OTP"] else None,
            resend_wait=max(0, challenge["sent_at"] + current_app.config["OTP_RESEND_COOLDOWN"] - now),
            resend_left=max(0, current_app.config["OTP_MAX_RESENDS"] - challenge["resends"]),
            purpose_label="تسجيل الدخول" if challenge["purpose"] == "login" else "إنشاء حساب",
        ),
        status,
    )


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.get("user"):
        return redirect(url_for("customer.dashboard"))
    next_url = safe_next_url(request.args.get("next") or request.form.get("next"), "")
    if request.method == "POST":
        phone = _phone(request.form.get("phone"))
        if not valid_phone(request.form.get("phone"), current_app.config["DEFAULT_COUNTRY_CODE"]):
            flash("يرجى إدخال رقم هاتف صحيح.", "error")
            return render_template(
                "auth/start.html", mode="login", page_title="تسجيل الدخول",
                phone=request.form.get("phone", ""), next_url=next_url,
            ), 400
        user = query_one("SELECT * FROM users WHERE phone = ?", (phone,))
        if not user:
            flash("لا يوجد حساب بهذا الرقم. يمكنك إنشاء حساب جديد خلال دقيقة.", "info")
            return redirect(url_for("auth.register", phone=phone, next=next_url))
        if not user["is_active"]:
            flash("هذا الحساب موقوف حالياً. يرجى التواصل مع خدمة العملاء.", "error")
            return redirect(url_for("auth.login"))
        if _start_challenge(phone, "login"):
            session["otp_next"] = next_url
            return redirect(url_for("auth.verify"))
        return redirect(url_for("auth.login"))
    return render_template(
        "auth/start.html", mode="login", page_title="تسجيل الدخول",
        phone=request.args.get("phone", ""), next_url=next_url,
    )


@bp.route("/register", methods=["GET", "POST"])
def register():
    if g.get("user"):
        return redirect(url_for("customer.dashboard"))
    next_url = safe_next_url(request.args.get("next") or request.form.get("next"), "")
    values = {
        "name": request.args.get("name", ""),
        "phone": request.args.get("phone", ""),
        "email": request.args.get("email", ""),
        "company": request.args.get("company", ""),
    }
    if request.method == "POST":
        values = {
            "name": request.form.get("name", "").strip(),
            "phone": request.form.get("phone", "").strip(),
            "email": request.form.get("email", "").strip(),
            "company": request.form.get("company", "").strip(),
        }
        phone = _phone(values["phone"])
        errors = []
        if len(values["name"]) < 2:
            errors.append("يرجى إدخال الاسم الكامل.")
        if not valid_phone(values["phone"], current_app.config["DEFAULT_COUNTRY_CODE"]):
            errors.append("يرجى إدخال رقم هاتف صحيح.")
        if not _email_valid(values["email"]):
            errors.append("يرجى إدخال بريد إلكتروني صحيح.")
        if query_one("SELECT id FROM users WHERE phone = ?", (phone,)):
            errors.append("هذا الرقم مسجل مسبقاً. يمكنك تسجيل الدخول برمز التحقق.")
        if errors:
            for error in errors:
                flash(error, "error")
            return render_template(
                "auth/start.html", mode="register", page_title="إنشاء حساب",
                values=values, next_url=next_url,
            ), 400
        if _start_challenge(phone, "register", values["name"], values["email"], values["company"]):
            session["otp_next"] = next_url
            return redirect(url_for("auth.verify"))
        return redirect(url_for("auth.register", phone=values["phone"]))
    return render_template(
        "auth/start.html", mode="register", page_title="إنشاء حساب",
        values=values, next_url=next_url,
    )


@bp.route("/verify", methods=["GET", "POST"])
def verify():
    challenge = _get_challenge()
    if not challenge:
        flash("انتهت جلسة التحقق. يرجى البدء من جديد.", "error")
        return redirect(url_for("auth.login"))
    if request.method == "GET":
        return _otp_view(challenge)

    now = int(time.time())
    if challenge["expires_at"] < now:
        return _otp_view(challenge, "انتهت صلاحية الرمز. اطلب رمزاً جديداً للمتابعة.", 400)
    code = re.sub(r"\D", "", request.form.get("code", ""))
    if len(code) != 6:
        return _otp_view(challenge, "أدخل رمزاً مكوناً من ٦ أرقام.", 400)
    if challenge["attempts"] >= current_app.config["OTP_MAX_ATTEMPTS"]:
        execute("UPDATE otp_challenges SET consumed_at = ? WHERE id = ?", (now, challenge["id"]))
        session.pop("otp_id", None)
        flash("تم استهلاك عدد المحاولات. يرجى طلب رمز جديد.", "error")
        return redirect(url_for("auth.login"))

    if not verify_otp(code, challenge["code_hash"]):
        attempts = challenge["attempts"] + 1
        execute("UPDATE otp_challenges SET attempts = ? WHERE id = ?", (attempts, challenge["id"]))
        remaining = current_app.config["OTP_MAX_ATTEMPTS"] - attempts
        if remaining <= 0:
            execute("UPDATE otp_challenges SET consumed_at = ? WHERE id = ?", (now, challenge["id"]))
            session.pop("otp_id", None)
            flash("تم استهلاك عدد المحاولات. يرجى طلب رمز جديد.", "error")
            return redirect(url_for("auth.login"))
        return _otp_view(challenge, f"الرمز غير صحيح. المحاولات المتبقية: {remaining}.", 400)

    execute("UPDATE otp_challenges SET consumed_at = ? WHERE id = ?", (now, challenge["id"]))
    if challenge["purpose"] == "register":
        user = query_one("SELECT * FROM users WHERE phone = ?", (challenge["phone"],))
        if not user:
            cursor = execute(
                """
                INSERT INTO users (name, phone, email, company, created_at, updated_at, last_login_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    challenge["name"] or "عميل توصيل",
                    challenge["phone"],
                    challenge["email"],
                    challenge["company"],
                    iso_now(),
                    iso_now(),
                    iso_now(),
                ),
            )
            user = query_one("SELECT * FROM users WHERE id = ?", (cursor.lastrowid,))
        flash("تم إنشاء حسابك بنجاح. أهلاً بك في توصيل.", "success")
    else:
        user = query_one("SELECT * FROM users WHERE phone = ?", (challenge["phone"],))
        flash("تم تسجيل الدخول بنجاح.", "success")

    if not user or not user["is_active"]:
        flash("تعذر تسجيل الدخول. تواصل مع خدمة العملاء.", "error")
        return redirect(url_for("auth.login"))

    execute("UPDATE users SET last_login_at = ? WHERE id = ?", (iso_now(), user["id"]))
    token = create_auth_session(user_id=user["id"])
    target = safe_next_url(session.pop("otp_next", ""), url_for("customer.dashboard"))
    session.pop("otp_id", None)
    response = redirect(target)
    return set_auth_cookie(response, token)


@bp.post("/resend")
def resend():
    challenge = _get_challenge()
    if not challenge:
        flash("انتهت جلسة التحقق. يرجى البدء من جديد.", "error")
        return redirect(url_for("auth.login"))
    now = int(time.time())
    if challenge["resends"] >= current_app.config["OTP_MAX_RESENDS"]:
        flash("تم طلب رمز جديد عدة مرات. يرجى المحاولة لاحقاً.", "error")
        return redirect(url_for("auth.verify"))
    if now < challenge["sent_at"] + current_app.config["OTP_RESEND_COOLDOWN"]:
        flash("يرجى الانتظار قبل طلب رمز جديد.", "error")
        return redirect(url_for("auth.verify"))
    if not rate_limit(f"otp:phone:{challenge['phone']}", current_app.config["OTP_RATE_LIMIT"], 900):
        flash("تم إرسال رموز كثيرة إلى هذا الرقم. يرجى المحاولة بعد قليل.", "error")
        return redirect(url_for("auth.verify"))

    code = generate_otp()
    try:
        send_otp(challenge["phone"], code, challenge["purpose"])
    except SmsError as exc:
        current_app.logger.error("OTP resend failed for %s: %s", mask_phone(challenge["phone"]), exc)
        flash("تعذر إرسال رمز جديد الآن. حاول بعد قليل.", "error")
        return redirect(url_for("auth.verify"))
    execute(
        """
        UPDATE otp_challenges
        SET code_hash = ?, dev_code = ?, expires_at = ?, attempts = 0,
            resends = resends + 1, sent_at = ?
        WHERE id = ?
        """,
        (
            hash_otp(code),
            code if current_app.config["ALLOW_DEV_OTP"] else None,
            now + current_app.config["OTP_TTL_SECONDS"],
            now,
            challenge["id"],
        ),
    )
    flash("تم إرسال رمز جديد.", "success")
    return redirect(url_for("auth.verify"))


@bp.post("/logout")
def logout():
    logout_current_session()
    session.pop("otp_id", None)
    flash("تم تسجيل الخروج.", "success")
    response = redirect(url_for("public.home"))
    return clear_auth_cookie(response)
