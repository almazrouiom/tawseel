from __future__ import annotations

from flask import current_app, g

from .db import execute, query

SETTING_KEYS = (
    "company_name",
    "company_name_en",
    "tagline",
    "phone",
    "whatsapp",
    "email",
    "address",
    "working_hours",
    "instagram",
    "twitter",
    "meta_description",
    "sms_status_updates",
)


def get_settings(force: bool = False) -> dict[str, str]:
    if not force and "settings" in g:
        return g.settings
    values = dict(current_app.config["COMPANY_DEFAULTS"])
    for row in query("SELECT key, value FROM settings"):
        values[row["key"]] = row["value"]
    g.settings = values
    return values


def save_settings(values: dict[str, str]) -> None:
    for key in SETTING_KEYS:
        if key not in values:
            continue
        value = (values.get(key) or "").strip()[:2000]
        execute(
            """
            INSERT INTO settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
    g.pop("settings", None)


def status_sms_enabled() -> bool:
    return get_settings().get("sms_status_updates", "0") == "1"
