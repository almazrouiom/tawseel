from __future__ import annotations

import os
import sqlite3
import threading
from collections import deque
from pathlib import Path

import click
from flask import current_app, g

SCHEMA_FILE = Path(__file__).with_name("schema.sql")

# Per-application pool of live SQLite connections. Opening a fresh connection
# on every request forces SQLite to re-read the WAL header and run a
# checkpoint on close, which dominated request latency. Connections are cheap
# to keep warm and safe to reuse as long as each one stays on its own thread.
_POOLS_KEY = "_tawseel_db_pool"
_POOL_SIZE = int(os.environ.get("DB_POOL_SIZE", "8"))
_pools_lock = threading.Lock()


def _connect(path: str) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=30, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA journal_mode = WAL")
    # Keep the WAL file from growing without bound between checkpoints.
    connection.execute("PRAGMA wal_autocheckpoint = 1000")
    connection.execute("PRAGMA synchronous = NORMAL")
    return connection


def _ensure_perf_indexes(connection: sqlite3.Connection) -> None:
    """Create indexes that support hot query paths on existing databases."""
    # Covers `WHERE shipment_id = ? ORDER BY event_at DESC, id DESC` used by
    # every tracking timeline render without requiring a database rebuild.
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_events_shipment_order "
        "ON tracking_events(shipment_id, event_at DESC, id DESC)"
    )


def _get_pool(app) -> deque:
    with _pools_lock:
        pool = getattr(app, _POOLS_KEY, None)
        if pool is None:
            pool = deque(maxlen=_POOL_SIZE)
            setattr(app, _POOLS_KEY, pool)
        return pool


def _checkout(app) -> sqlite3.Connection:
    path = app.config["DATABASE"]
    pool = _get_pool(app)
    while True:
        try:
            connection, stamp = pool.popleft()
        except IndexError:
            return _connect(path)
        # Discard pooled connections if the database file was replaced or the
        # connection died (e.g. after a WAL truncation race or process fork).
        if stamp != path:
            connection.close()
            continue
        try:
            connection.execute("SELECT 1")
        except sqlite3.Error:
            connection.close()
            continue
        return connection


def _checkin(app, connection: sqlite3.Connection) -> None:
    pool = _get_pool(app)
    try:
        # Roll back any implicit transaction left open by the request.
        if connection.in_transaction:
            connection.rollback()
    except sqlite3.Error:
        connection.close()
        return
    pool.append((connection, app.config["DATABASE"]))


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = _checkout(current_app._get_current_object())
    return g.db


def close_db(_error=None) -> None:
    connection = g.pop("db", None)
    if connection is not None:
        _checkin(current_app._get_current_object(), connection)


def query(sql: str, params: tuple | list = ()) -> list[sqlite3.Row]:
    return get_db().execute(sql, params).fetchall()


def query_one(sql: str, params: tuple | list = ()) -> sqlite3.Row | None:
    return get_db().execute(sql, params).fetchone()


def execute(sql: str, params: tuple | list = (), commit: bool = True) -> sqlite3.Cursor:
    connection = get_db()
    cursor = connection.execute(sql, params)
    if commit:
        connection.commit()
    return cursor


def executemany(sql: str, rows: list[tuple]) -> None:
    connection = get_db()
    connection.executemany(sql, rows)
    connection.commit()


def init_app(app) -> None:
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
    app.cli.add_command(seed_demo_command)


@click.command("init-db")
def init_db_command() -> None:
    """Create the database schema and bootstrap the first admin."""
    init_db()
    from .seed import bootstrap
    bootstrap(current_app)
    click.echo("Database initialized.")


@click.command("seed-demo")
def seed_demo_command() -> None:
    """Insert demo customers, shipments and requests (development only)."""
    from .seed import seed_demo
    seed_demo(current_app, force=True)
    click.echo("Demo data seeded.")


def init_db() -> None:
    path = Path(current_app.config["DATABASE"])
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = _connect(str(path))
    try:
        connection.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
        _migrate(connection)
        _ensure_perf_indexes(connection)
        connection.commit()
    finally:
        connection.close()


def _has_column(connection: sqlite3.Connection, table: str, column: str) -> bool:
    return any(row["name"] == column for row in connection.execute(f"PRAGMA table_info({table})"))


def _migrate(connection: sqlite3.Connection) -> None:
    """Apply additive migrations for databases created by older versions."""
    if not _has_column(connection, "shipments", "branch_id"):
        connection.execute(
            "ALTER TABLE shipments ADD COLUMN branch_id INTEGER REFERENCES branches(id) ON DELETE SET NULL"
        )
    if not _has_column(connection, "audit_log", "staff_id"):
        connection.execute(
            "ALTER TABLE audit_log ADD COLUMN staff_id INTEGER REFERENCES staff(id) ON DELETE SET NULL"
        )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_shipments_branch ON shipments(branch_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_staff ON audit_log(staff_id)"
    )
