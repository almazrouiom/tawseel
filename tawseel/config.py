"""Application configuration.

Environment variables are loaded from `.env` (if present) before the values
below are read. In production, SECRET_KEY must be supplied explicitly.
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"
SITE_DIR = BASE_DIR / "site"
STATIC_DIR = SITE_DIR / "assets"


def _load_env_file() -> None:
    if not ENV_FILE.exists():
        return
    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


_load_env_file()

APP_ENV = os.environ.get("APP_ENV", "development").strip().lower()
IS_PRODUCTION = APP_ENV == "production"
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR / "data")).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _secret_key() -> str:
    configured = os.environ.get("SECRET_KEY", "").strip()
    if configured:
        return configured
    if IS_PRODUCTION:
        raise RuntimeError(
            "SECRET_KEY is required in production. Generate one with: "
            "python -c \"import secrets; print(secrets.token_urlsafe(48))\""
        )
    key_file = DATA_DIR / ".secret_key"
    if key_file.exists():
        return key_file.read_text(encoding="utf-8").strip()
    key = secrets.token_urlsafe(48)
    key_file.write_text(key, encoding="utf-8")
    try:
        key_file.chmod(0o600)
    except OSError:
        pass
    return key


PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://127.0.0.1:8080").rstrip("/")


def _shipment_code_prefix() -> str:
    configured = os.environ.get("SHIPMENT_CODE_PREFIX", "TS").strip().upper()
    cleaned = "".join(ch for ch in configured if ("A" <= ch <= "Z") or ("0" <= ch <= "9"))
    return cleaned[:8] or "TS"


SHIPMENT_CODE_PREFIX = _shipment_code_prefix()


class Config:
    APP_ENV = APP_ENV
    IS_PRODUCTION = IS_PRODUCTION

    SECRET_KEY = _secret_key()
    DATABASE = str(DATA_DIR / "tawseel.db")
    DATA_DIR = str(DATA_DIR)

    STATIC_DIR = str(STATIC_DIR)
    STATIC_URL_PATH = "/assets"
    PUBLIC_BASE_URL = PUBLIC_BASE_URL
    SHIPMENT_CODE_PREFIX = SHIPMENT_CODE_PREFIX
    PREFERRED_URL_SCHEME = "https" if PUBLIC_BASE_URL.startswith("https://") else "http"

    SESSION_COOKIE_NAME = "tawseel_ui"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", IS_PRODUCTION)
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 30
    MAX_CONTENT_LENGTH = 2 * 1024 * 1024

    AUTH_COOKIE_NAME = "tawseel_auth"
    AUTH_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", IS_PRODUCTION)
    AUTH_SESSION_TTL = 60 * 60 * 24 * 14

    STAFF_COOKIE_NAME = "tawseel_staff"
    STAFF_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", IS_PRODUCTION)
    STAFF_SESSION_TTL = 60 * 60 * 12

    OTP_TTL_SECONDS = int(os.environ.get("OTP_TTL_SECONDS", "300"))
    OTP_MAX_ATTEMPTS = int(os.environ.get("OTP_MAX_ATTEMPTS", "5"))
    OTP_RESEND_COOLDOWN = int(os.environ.get("OTP_RESEND_COOLDOWN", "60"))
    OTP_MAX_RESENDS = int(os.environ.get("OTP_MAX_RESENDS", "3"))
    OTP_RATE_WINDOW = 15 * 60
    OTP_RATE_LIMIT = int(os.environ.get("OTP_RATE_LIMIT", "6"))
    DEFAULT_COUNTRY_CODE = os.environ.get("DEFAULT_COUNTRY_CODE", "968").lstrip("+")

    ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@tawseel.local").strip().lower()
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "" if IS_PRODUCTION else "Admin1234!")
    ADMIN_NAME = os.environ.get("ADMIN_NAME", "مدير الموقع").strip()

    SMS_PROVIDER = os.environ.get("SMS_PROVIDER", "log").strip().lower()
    SMS_SENDER = os.environ.get("SMS_SENDER", "Tawseel")
    TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
    TWILIO_FROM = os.environ.get("TWILIO_FROM", "")
    UNIFONIC_APPSID = os.environ.get("UNIFONIC_APPSID", "")
    UNIFONIC_SENDER = os.environ.get("UNIFONIC_SENDER", "")
    UNIFONIC_URL = os.environ.get("UNIFONIC_URL", "https://el.cloud.unifonic.com/rest/SMS/messages")

    ALLOW_DEV_OTP = env_bool("DEV_SHOW_OTP", not IS_PRODUCTION) and not IS_PRODUCTION
    SEED_DEMO = env_bool("SEED_DEMO", not IS_PRODUCTION) and not IS_PRODUCTION
    SEND_STATUS_SMS = env_bool("SEND_STATUS_SMS", False)
    TRUST_PROXY = env_bool("TRUST_PROXY", IS_PRODUCTION)

    COMPANY_DEFAULTS = {
        "company_name": "توصيل",
        "company_name_en": "Tawseel",
        "tagline": "توصيل موثوق، في الوقت المناسب.",
        "phone": "",
        "whatsapp": "",
        "email": "info@example.com",
        "address": "مسقط، سلطنة عُمان",
        "working_hours": "الأحد – الخميس، 8:00 ص – 5:00 م",
        "instagram": "",
        "twitter": "",
        "meta_description": (
            "توصيل — حلول توصيل وشحن للشركات والأفراد في سلطنة عُمان، "
            "مع تتبع مباشر للشحنات وخدمة عملاء متاحة للمساعدة."
        ),
    }

    @classmethod
    def sms_configured(cls) -> bool:
        if cls.SMS_PROVIDER == "twilio":
            return bool(cls.TWILIO_ACCOUNT_SID and cls.TWILIO_AUTH_TOKEN and cls.TWILIO_FROM)
        if cls.SMS_PROVIDER == "unifonic":
            return bool(cls.UNIFONIC_APPSID and cls.UNIFONIC_SENDER)
        return cls.SMS_PROVIDER == "log" and not cls.IS_PRODUCTION
