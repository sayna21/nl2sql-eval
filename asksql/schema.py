"""Database schema, column descriptions and helpers for building a database file."""

from __future__ import annotations

import sqlite3
from functools import lru_cache
from pathlib import Path

import yaml

from asksql.config import resource_path

DDL = """\
CREATE TABLE zones (zone_id INTEGER PRIMARY KEY, borough TEXT, zone TEXT, service_zone TEXT);
CREATE TABLE payment_types (code INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE trips (
  trip_id INTEGER PRIMARY KEY, vendor_id INTEGER,
  pickup_at TEXT NOT NULL, dropoff_at TEXT NOT NULL,     -- 'YYYY-MM-DD HH:MM:SS', local NYC time
  passenger_count INTEGER, trip_distance_mi REAL, rate_code_id INTEGER,
  pu_zone_id INTEGER REFERENCES zones(zone_id), do_zone_id INTEGER REFERENCES zones(zone_id),
  payment_type INTEGER REFERENCES payment_types(code),
  fare_amount REAL, tip_amount REAL, tolls_amount REAL,
  congestion_surcharge REAL, airport_fee REAL, total_amount REAL
);
"""

INDEXES = """\
CREATE INDEX idx_trips_pickup_at ON trips(pickup_at);
CREATE INDEX idx_trips_pu_zone ON trips(pu_zone_id);
CREATE INDEX idx_trips_do_zone ON trips(do_zone_id);
"""

# TLC yellow-taxi data dictionary, "Payment_type".
PAYMENT_TYPES = [
    (0, "Flex Fare trip"),
    (1, "Credit card"),
    (2, "Cash"),
    (3, "No charge"),
    (4, "Dispute"),
    (5, "Unknown"),
    (6, "Voided trip"),
]

TRIP_COLUMNS = (
    "trip_id",
    "vendor_id",
    "pickup_at",
    "dropoff_at",
    "passenger_count",
    "trip_distance_mi",
    "rate_code_id",
    "pu_zone_id",
    "do_zone_id",
    "payment_type",
    "fare_amount",
    "tip_amount",
    "tolls_amount",
    "congestion_surcharge",
    "airport_fee",
    "total_amount",
)

DESCRIPTIONS_PATH = resource_path("data/descriptions.yaml")


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(DDL)
    conn.executemany("INSERT INTO payment_types VALUES (?, ?)", PAYMENT_TYPES)


def create_indexes(conn: sqlite3.Connection) -> None:
    conn.executescript(INDEXES)


def insert_trips(conn: sqlite3.Connection, rows) -> None:
    placeholders = ", ".join("?" * len(TRIP_COLUMNS))
    conn.executemany(f"INSERT INTO trips VALUES ({placeholders})", rows)


def build_db_from_script(sql_path: Path, db_path: Path) -> Path:
    """Create a fresh database: schema, then the INSERTs in `sql_path`, then indexes."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        create_schema(conn)
        conn.executescript(Path(sql_path).read_text(encoding="utf-8"))
        create_indexes(conn)
        conn.commit()
    finally:
        conn.close()
    return db_path


@lru_cache(maxsize=4)
def load_descriptions(path: Path = DESCRIPTIONS_PATH) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def describe(path: Path = DESCRIPTIONS_PATH) -> dict:
    """Tables, columns and descriptions, in the shape served by GET /schema."""
    doc = load_descriptions(path)
    tables = []
    for name, table in doc["tables"].items():
        tables.append(
            {
                "name": name,
                "description": table.get("description", ""),
                "columns": [
                    {"name": col, "description": text} for col, text in table["columns"].items()
                ],
            }
        )
    return {"tables": tables, "data_quality": doc.get("data_quality", [])}


def descriptions_text(path: Path = DESCRIPTIONS_PATH) -> str:
    """Column descriptions rendered as plain text for the S2 prompt."""
    doc = load_descriptions(path)
    lines: list[str] = []
    for name, table in doc["tables"].items():
        lines.append(f"{name}: {table.get('description', '')}".rstrip())
        for col, text in table["columns"].items():
            lines.append(f"  {col}: {text}")
    notes = doc.get("data_quality", [])
    if notes:
        lines.append("Data quality notes:")
        lines.extend(f"  - {note}" for note in notes)
    return "\n".join(lines)
