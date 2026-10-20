from __future__ import annotations

import sqlite3
from pathlib import Path

import click
from flask import current_app, g

SCHEMA_FILE = Path(__file__).with_name("schema.sql")


def _connect(path: str) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = _connect(current_app.config["DATABASE"])
    return g.db


def close_db(_error=None) -> None:
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


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
