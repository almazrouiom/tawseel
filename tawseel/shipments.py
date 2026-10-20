"""Shared shipment operations used by the admin and branch portals."""
from __future__ import annotations

from flask import current_app

from .db import execute
from .settings import status_sms_enabled
from .sms import SmsError, send_status_update
from .utils import iso_now, status_meta


def notify_for_status(shipment, status: str, note: str = "") -> None:
    """Create an in-app notification and, when enabled, send a status SMS."""
    if not shipment["customer_id"]:
        return
    label = status_meta(status)["label"]
    body = (note or "").strip() or status_meta(status)["hint"]
    execute(
        """
        INSERT INTO notifications (user_id, title, body, link, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            shipment["customer_id"],
            f"تحديث شحنة {shipment['code']}",
            body or f"الحالة الجديدة: {label}",
            f"/dashboard/shipments/{shipment['code']}",
            iso_now(),
        ),
    )
    if status_sms_enabled() and shipment["customer_phone"]:
        try:
            send_status_update(shipment["customer_phone"], shipment["code"], label)
        except SmsError as exc:
            current_app.logger.error("Status SMS failed for %s: %s", shipment["code"], exc)


def record_status_update(
    shipment,
    status: str,
    location: str = "",
    note: str = "",
    event_at: str | None = None,
) -> str:
    """Add a tracking event, move the shipment, and notify its customer."""
    label = status_meta(status)["label"]
    note = (note or "").strip() or f"تم تحديث حالة الشحنة إلى: {label}."
    execute(
        """
        INSERT INTO tracking_events (shipment_id, status, location, note, event_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            shipment["id"],
            status,
            (location or "").strip() or shipment["destination"],
            note,
            event_at or iso_now(),
            iso_now(),
        ),
    )
    delivered_at = shipment["delivered_at"]
    if status == "delivered" and not delivered_at:
        delivered_at = iso_now()
    execute(
        "UPDATE shipments SET status = ?, updated_at = ?, delivered_at = ? WHERE id = ?",
        (status, iso_now(), delivered_at, shipment["id"]),
    )
    notify_for_status(shipment, status, note)
    return note
