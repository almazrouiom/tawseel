"""Small shared helpers for dates, phone numbers, status labels and money."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

OMAN_TZ = timezone(timedelta(hours=4))
ARABIC_MONTHS = (
    "يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
    "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر",
)

STATUS_META = {
    "pending": {"label": "قيد التسجيل", "tone": "neutral", "hint": "تم إنشاء الشحنة وبانتظار استلامها."},
    "picked_up": {"label": "تم الاستلام", "tone": "info", "hint": "تم استلام الشحنة من المرسل."},
    "in_transit": {"label": "قيد النقل", "tone": "info", "hint": "الشحنة في الطريق إلى الوجهة."},
    "out_for_delivery": {"label": "قيد التوصيل", "tone": "warning", "hint": "الشحنة مع مندوب التوصيل."},
    "delivered": {"label": "تم التوصيل", "tone": "success", "hint": "تم تسليم الشحنة بنجاح."},
    "on_hold": {"label": "معلّقة", "tone": "warning", "hint": "هناك أمر يحتاج مراجعة قبل المتابعة."},
    "cancelled": {"label": "ملغاة", "tone": "danger", "hint": "تم إلغاء الشحنة."},
}

SERVICE_META = {
    "standard": "توصيل قياسي",
    "express": "توصيل سريع",
    "same_day": "توصيل نفس اليوم",
    "documents": "توصيل مستندات",
    "ecommerce": "حلول المتاجر الإلكترونية",
}

STAFF_ROLE_META = {
    "manager": "مدير فرع",
    "agent": "موظف عمليات",
}

PURPOSE_LABELS = {
    "login": "تسجيل الدخول",
    "register": "إنشاء حساب",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().replace(microsecond=0).isoformat()


def to_local(value: datetime | str | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(OMAN_TZ)


def format_datetime(value: datetime | str | None, include_time: bool = True) -> str:
    local = to_local(value)
    if not local:
        return "—"
    date_part = f"{local.day} {ARABIC_MONTHS[local.month - 1]} {local.year}"
    if not include_time:
        return date_part
    hour = local.hour % 12 or 12
    period = "ص" if local.hour < 12 else "م"
    return f"{date_part}، {hour}:{local.minute:02d} {period}"


def format_date(value: datetime | str | None) -> str:
    return format_datetime(value, include_time=False)


def format_input_datetime(value: datetime | str | None) -> str:
    local = to_local(value)
    return local.strftime("%Y-%m-%dT%H:%M") if local else ""


def parse_local_datetime(value: str | None) -> str:
    """Convert a datetime-local value (Oman time) into a UTC ISO string."""
    if not value:
        return iso_now()
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return iso_now()
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=OMAN_TZ)
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def normalize_code(raw: str | None) -> str:
    return re.sub(r"\s+", "", raw or "").lstrip("#").upper()[:32]


def status_meta(key: str | None) -> dict:
    return STATUS_META.get(key or "", {"label": key or "غير محددة", "tone": "neutral", "hint": ""})


def service_label(key: str | None) -> str:
    return SERVICE_META.get(key or "", key or "—")


def staff_role_label(key: str | None) -> str:
    return STAFF_ROLE_META.get(key or "", key or "—")


def normalize_phone(raw: str | None, default_country: str = "968") -> str:
    """Return an E.164-like phone number, defaulting to the Oman country code."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return ""
    if raw.strip().startswith("+"):
        return "+" + digits
    if digits.startswith("00"):
        return "+" + digits[2:]
    if len(digits) == 8 and not digits.startswith(default_country):
        return f"+{default_country}{digits}"
    if digits.startswith(default_country) and len(digits) == len(default_country) + 8:
        return "+" + digits
    if 8 <= len(digits) <= 15:
        return "+" + digits
    return ""


def valid_phone(raw: str | None, default_country: str = "968") -> bool:
    phone = normalize_phone(raw, default_country)
    return bool(phone and 8 <= len(phone.lstrip("+")) <= 15)


def format_phone(phone: str | None) -> str:
    if not phone:
        return ""
    phone = phone.strip()
    if phone.startswith("+968") and len(phone) == 12:
        return f"+968 {phone[4]} {phone[5:9]} {phone[9:]}"
    if phone.startswith("+") and len(phone) > 5:
        return phone[:4] + " " + phone[4:]
    return phone


def mask_phone(phone: str | None) -> str:
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone)
    if len(digits) < 4:
        return "•" * len(digits)
    return "•" * (len(digits) - 3) + digits[-3:]


def format_money(amount: float | int | None, currency: str = "OMR") -> str:
    if amount is None:
        return "—"
    suffix = "ر.ع." if currency == "OMR" else currency
    return f"{amount:,.3f} {suffix}"


def format_weight(value: float | int | None) -> str:
    if value is None:
        return "—"
    return f"{value:g} كجم"


def paginate(total: int, page: int, per_page: int) -> dict:
    pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, pages))
    return {"page": page, "pages": pages, "per_page": per_page, "offset": (page - 1) * per_page}
