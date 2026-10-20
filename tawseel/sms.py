from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request

from flask import current_app

from .utils import format_phone, mask_phone


class SmsError(RuntimeError):
    pass


def sms_ready() -> bool:
    provider = current_app.config["SMS_PROVIDER"]
    if provider == "twilio":
        return bool(
            current_app.config["TWILIO_ACCOUNT_SID"]
            and current_app.config["TWILIO_AUTH_TOKEN"]
            and current_app.config["TWILIO_FROM"]
        )
    if provider == "unifonic":
        return bool(current_app.config["UNIFONIC_APPSID"] and current_app.config["UNIFONIC_SENDER"])
    return provider == "log" and not current_app.config["IS_PRODUCTION"]


def send_sms(phone: str, message: str) -> None:
    provider = current_app.config["SMS_PROVIDER"]
    if provider == "log":
        if current_app.config["IS_PRODUCTION"]:
            raise SmsError("SMS_PROVIDER=log is not allowed in production.")
        current_app.logger.info("SMS to %s: %s", format_phone(phone), message)
        return
    if provider == "twilio":
        _send_twilio(phone, message)
        return
    if provider == "unifonic":
        _send_unifonic(phone, message)
        return
    raise SmsError(f"Unknown SMS provider: {provider}")


def send_otp(phone: str, code: str, purpose: str) -> None:
    action = "تسجيل الدخول" if purpose == "login" else "إنشاء حساب"
    message = (
        f"رمز {action} في توصيل: {code}\n"
        "صالح لمدة 5 دقائق. لا تشاركه مع أي شخص."
    )
    send_sms(phone, message)


def send_status_update(phone: str, code: str, status_label: str) -> None:
    message = (
        f"تحديث شحنتك {code}: {status_label}.\n"
        "تتبع الشحنة من موقع توصيل."
    )
    send_sms(phone, message)


def _post_form(url: str, payload: dict, headers: dict | None = None) -> tuple[int, str]:
    data = urllib.parse.urlencode(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise SmsError(f"SMS provider returned HTTP {exc.code}: {body[:400]}") from exc
    except urllib.error.URLError as exc:
        raise SmsError(f"Could not reach SMS provider: {exc.reason}") from exc


def _send_twilio(phone: str, message: str) -> None:
    sid = current_app.config["TWILIO_ACCOUNT_SID"]
    token = current_app.config["TWILIO_AUTH_TOKEN"]
    sender = current_app.config["TWILIO_FROM"]
    auth = base64.b64encode(f"{sid}:{token}".encode("utf-8")).decode("ascii")
    status, body = _post_form(
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
        {"To": phone, "From": sender, "Body": message},
        {"Authorization": f"Basic {auth}"},
    )
    if status >= 300:
        raise SmsError(f"Twilio returned HTTP {status}: {body[:300]}")


def _send_unifonic(phone: str, message: str) -> None:
    payload = {
        "AppSid": current_app.config["UNIFONIC_APPSID"],
        "SenderID": current_app.config["UNIFONIC_SENDER"],
        "Recipient": phone.lstrip("+"),
        "Body": message,
    }
    url = current_app.config.get("UNIFONIC_URL") or "https://el.cloud.unifonic.com/rest/SMS/messages"
    status, body = _post_form(url, payload)
    if status >= 300:
        raise SmsError(f"Unifonic returned HTTP {status}: {body[:300]}")
    try:
        parsed = json.loads(body)
        if isinstance(parsed, dict) and parsed.get("success") is False:
            raise SmsError(f"Unifonic rejected the message: {body[:300]}")
    except json.JSONDecodeError:
        pass


def log_phone(phone: str) -> str:
    return mask_phone(phone)
