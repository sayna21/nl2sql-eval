"""Generate synthetic taxi trips with the same schema as the real loader.

Usage: python scripts/make_synthetic.py [--rows 250000] [--seed 42]

A fallback for when the TLC files are not available. About 1% of rows are made
dirty on purpose, matching the kinds of bad records found in the real data.
"""

from __future__ import annotations

import argparse
import random
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from asksql.config import ROOT
from asksql.schema import create_indexes, create_schema, insert_trips

ZONES = [
    (1, "EWR", "Newark Airport", "EWR"),
    (4, "Manhattan", "Alphabet City", "Yellow Zone"),
    (7, "Queens", "Astoria", "Boro Zone"),
    (13, "Manhattan", "Battery Park City", "Yellow Zone"),
    (25, "Brooklyn", "Boerum Hill", "Boro Zone"),
    (33, "Brooklyn", "Brooklyn Heights", "Boro Zone"),
    (41, "Manhattan", "Central Harlem", "Boro Zone"),
    (43, "Manhattan", "Central Park", "Yellow Zone"),
    (48, "Manhattan", "Clinton East", "Yellow Zone"),
    (68, "Manhattan", "East Chelsea", "Yellow Zone"),
    (79, "Manhattan", "East Village", "Yellow Zone"),
    (87, "Manhattan", "Financial District North", "Yellow Zone"),
    (97, "Brooklyn", "Fort Greene", "Boro Zone"),
    (100, "Manhattan", "Garment District", "Yellow Zone"),
    (107, "Manhattan", "Gramercy", "Yellow Zone"),
    (132, "Queens", "JFK Airport", "Airports"),
    (138, "Queens", "LaGuardia Airport", "Airports"),
    (141, "Manhattan", "Lenox Hill West", "Yellow Zone"),
    (142, "Manhattan", "Lincoln Square East", "Yellow Zone"),
    (161, "Manhattan", "Midtown Center", "Yellow Zone"),
    (162, "Manhattan", "Midtown East", "Yellow Zone"),
    (163, "Manhattan", "Midtown North", "Yellow Zone"),
    (170, "Manhattan", "Murray Hill", "Yellow Zone"),
    (181, "Brooklyn", "Park Slope", "Boro Zone"),
    (186, "Manhattan", "Penn Station/Madison Sq West", "Yellow Zone"),
    (206, "Staten Island", "Saint George/New Brighton", "Boro Zone"),
    (230, "Manhattan", "Times Sq/Theatre District", "Yellow Zone"),
    (234, "Manhattan", "Union Sq", "Yellow Zone"),
    (236, "Manhattan", "Upper East Side North", "Yellow Zone"),
    (237, "Manhattan", "Upper East Side South", "Yellow Zone"),
    (238, "Manhattan", "Upper West Side North", "Yellow Zone"),
    (239, "Manhattan", "Upper West Side South", "Yellow Zone"),
    (247, "Bronx", "West Concourse", "Boro Zone"),
    (255, "Brooklyn", "Williamsburg (North Side)", "Boro Zone"),
    (264, "Unknown", "N/A", "N/A"),
    (265, "N/A", "Outside of NYC", "N/A"),
]
AIRPORTS = {1, 132, 138}
FMT = "%Y-%m-%d %H:%M:%S"


def make_trip(rng: random.Random, trip_id: int) -> tuple:
    zone_ids = [z[0] for z in ZONES]
    pickup = datetime(2024, 1, 1) + timedelta(seconds=rng.randrange(31 * 86400))
    minutes = max(1.0, rng.lognormvariate(2.5, 0.6))
    distance = round(max(0.1, minutes * rng.uniform(0.12, 0.35)), 2)
    dropoff = pickup + timedelta(minutes=minutes)
    pu, do = rng.choice(zone_ids), rng.choice(zone_ids)
    payment = rng.choices([1, 2, 3, 4, 0], weights=[78, 16, 1, 1, 4])[0]
    fare = round(3.0 + 2.8 * distance + 0.6 * minutes, 2)
    tip = round(fare * rng.uniform(0.1, 0.3), 2) if payment == 1 else 0.0
    tolls = 6.94 if rng.random() < 0.06 else 0.0
    congestion = 2.5 if rng.random() < 0.85 else 0.0
    airport_fee = 1.75 if pu in AIRPORTS - {1} else 0.0
    passengers = (
        None if payment == 0 else rng.choices([1, 2, 3, 4, 5, 6, 0], [72, 14, 4, 2, 1, 1, 1])[0]
    )
    rate_code = None if payment == 0 else (2 if 132 in (pu, do) and rng.random() < 0.7 else 1)

    # Dirty rows, roughly 1% in total.
    roll = rng.random()
    if roll < 0.003:
        fare, tip = -fare, 0.0  # refunds / reversed charges
    elif roll < 0.006:
        distance = 0.0
    elif roll < 0.008:
        dropoff = pickup - timedelta(minutes=rng.uniform(1, 30))
    elif roll < 0.0085:
        pickup = pickup.replace(year=rng.choice([2002, 2009, 2023]), month=12)
        dropoff = pickup + timedelta(minutes=minutes)

    total = round(fare + tip + tolls + congestion + airport_fee + 1.5, 2)
    return (
        trip_id,
        rng.choice([1, 2]),
        pickup.strftime(FMT),
        dropoff.strftime(FMT),
        passengers,
        distance,
        rate_code,
        pu,
        do,
        payment,
        fare,
        tip,
        tolls,
        congestion,
        airport_fee,
        total,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rows", type=int, default=250_000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "taxi.db")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    args.out.unlink(missing_ok=True)
    conn = sqlite3.connect(args.out)
    try:
        create_schema(conn)
        conn.executemany("INSERT INTO zones VALUES (?, ?, ?, ?)", ZONES)
        insert_trips(conn, (make_trip(rng, i) for i in range(1, args.rows + 1)))
        conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.executemany(
            "INSERT INTO meta VALUES (?, ?)",
            [("data_source", "synthetic"), ("seed", str(args.seed))],
        )
        create_indexes(conn)
        conn.commit()
    finally:
        conn.close()
    print(f"wrote {args.out} with {args.rows} synthetic trips (seed {args.seed})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
