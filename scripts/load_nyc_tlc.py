"""Load a deterministic sample of NYC TLC yellow-taxi trips into SQLite.

Usage: python scripts/load_nyc_tlc.py [--rows 250000] [--seed 42]

Reads data/raw/yellow_tripdata_2024-01.parquet and data/raw/taxi_zone_lookup.csv and
writes data/taxi.db. Dirty rows (negative fares, zero distances, drop-off before
pick-up, timestamps outside January) are kept on purpose.
"""

from __future__ import annotations

import argparse
import csv
import random
import sqlite3
import sys
from pathlib import Path

import pyarrow.parquet as pq

from asksql.config import ROOT
from asksql.schema import create_indexes, create_schema, insert_trips

RAW = ROOT / "data" / "raw"
PARQUET = RAW / "yellow_tripdata_2024-01.parquet"
ZONES_CSV = RAW / "taxi_zone_lookup.csv"

SOURCE_COLUMNS = [
    "VendorID",
    "tpep_pickup_datetime",
    "tpep_dropoff_datetime",
    "passenger_count",
    "trip_distance",
    "RatecodeID",
    "PULocationID",
    "DOLocationID",
    "payment_type",
    "fare_amount",
    "tip_amount",
    "tolls_amount",
    "congestion_surcharge",
    "Airport_fee",
    "total_amount",
]


def _ts(value) -> str:
    return value.isoformat(sep=" ", timespec="seconds")


def _int(value):
    return None if value is None else int(value)


def read_zones(path: Path) -> list[tuple]:
    with open(path, newline="", encoding="utf-8") as fh:
        return [
            (int(r["LocationID"]), r["Borough"], r["Zone"], r["service_zone"])
            for r in csv.DictReader(fh)
        ]


def sample_trips(path: Path, rows: int, seed: int):
    table = pq.read_table(path, columns=SOURCE_COLUMNS)
    total = table.num_rows
    picked = sorted(random.Random(seed).sample(range(total), min(rows, total)))
    cols = table.take(picked).to_pydict()
    for i in range(len(picked)):
        yield (
            i + 1,
            _int(cols["VendorID"][i]),
            _ts(cols["tpep_pickup_datetime"][i]),
            _ts(cols["tpep_dropoff_datetime"][i]),
            _int(cols["passenger_count"][i]),
            cols["trip_distance"][i],
            _int(cols["RatecodeID"][i]),
            _int(cols["PULocationID"][i]),
            _int(cols["DOLocationID"][i]),
            _int(cols["payment_type"][i]),
            cols["fare_amount"][i],
            cols["tip_amount"][i],
            cols["tolls_amount"][i],
            cols["congestion_surcharge"][i],
            cols["Airport_fee"][i],
            cols["total_amount"][i],
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rows", type=int, default=250_000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "taxi.db")
    args = parser.parse_args()

    missing = [p for p in (PARQUET, ZONES_CSV) if not p.is_file()]
    if missing:
        for p in missing:
            print(f"missing: {p}", file=sys.stderr)
        print("Download the TLC files or run scripts/make_synthetic.py.", file=sys.stderr)
        return 1

    args.out.unlink(missing_ok=True)
    conn = sqlite3.connect(args.out)
    try:
        create_schema(conn)
        conn.executemany("INSERT INTO zones VALUES (?, ?, ?, ?)", read_zones(ZONES_CSV))
        insert_trips(conn, sample_trips(PARQUET, args.rows, args.seed))
        conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.executemany(
            "INSERT INTO meta VALUES (?, ?)",
            [("data_source", "real"), ("seed", str(args.seed)), ("source_file", PARQUET.name)],
        )
        create_indexes(conn)
        conn.commit()
        n = conn.execute("SELECT COUNT(*) FROM trips").fetchone()[0]
    finally:
        conn.close()
    print(f"wrote {args.out} with {n} trips (seed {args.seed})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
