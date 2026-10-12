"""Cross-check the benchmark gold SQL with independent Python calculations.

This is automated verification, not a claim of human review. The Python reference
calculations read raw rows and do not reuse the gold SQL's aggregates or joins.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

from asksql.config import ROOT, resource_path
from asksql.db import execute, file_sha256, open_readonly


def references(conn: sqlite3.Connection) -> dict[str, list[tuple]]:
    conn.row_factory = sqlite3.Row
    trips = [dict(row) for row in conn.execute("SELECT * FROM trips")]
    zones = {row["zone_id"]: dict(row) for row in conn.execute("SELECT * FROM zones")}
    payments = {row["code"]: row["name"] for row in conn.execute("SELECT * FROM payment_types")}
    conn.row_factory = None

    def values(field, rows=trips):
        return [row[field] for row in rows if row[field] is not None]

    def average(field, rows=trips):
        numbers = values(field, rows)
        return math.fsum(numbers) / len(numbers) if numbers else None

    def total(field, rows=trips):
        numbers = values(field, rows)
        return math.fsum(numbers) if numbers else None

    def groups(field, rows=trips):
        result = defaultdict(list)
        for row in rows:
            result[row[field]].append(row)
        return result

    def count(predicate):
        return [(sum(bool(predicate(row)) for row in trips),)]

    def positive(row, field, threshold=0):
        return row[field] is not None and row[field] > threshold

    def key(value):
        return (value is not None, value)

    cash = [row for row in trips if row["payment_type"] == 2]
    card = [row for row in trips if row["payment_type"] == 1]
    by_payment = groups("payment_type")
    by_passenger = groups("passenger_count")
    by_vendor = groups("vendor_id")
    by_pickup = groups("pu_zone_id")
    by_dropoff = groups("do_zone_id")
    pickup_counts = sorted(by_pickup.items(), key=lambda item: (-len(item[1]), key(item[0])))
    vendor_counts = sorted(by_vendor.items(), key=lambda item: -len(item[1]))
    picked_up = [row for row in trips if row["pu_zone_id"] in zones]
    boroughs = defaultdict(list)
    cash_boroughs = defaultdict(list)
    for row in picked_up:
        borough = zones[row["pu_zone_id"]]["borough"]
        boroughs[borough].append(row)
        if row["payment_type"] == 2:
            cash_boroughs[borough].append(row)
    durations = [
        (
            datetime.fromisoformat(row["dropoff_at"]) - datetime.fromisoformat(row["pickup_at"])
        ).total_seconds()
        for row in trips
    ]
    by_hour = defaultdict(list)
    for row in trips:
        by_hour[datetime.fromisoformat(row["pickup_at"]).hour].append(row)
    day_counts = Counter(
        row["pickup_at"][:10]
        for row in trips
        if "2024-01-01" <= row["pickup_at"][:10] <= "2024-01-07"
    )
    pairs = Counter(
        (row["pu_zone_id"], row["do_zone_id"])
        for row in trips
        if row["pu_zone_id"] in zones and row["do_zone_id"] in zones
    )
    winners = {}
    for zone_id, rows in pickup_counts:
        if zone_id in zones:
            winners.setdefault(zones[zone_id]["borough"], (zones[zone_id]["zone"], len(rows)))
    average_fare = average("fare_amount")
    return {
        "f01": [(len(trips),)],
        "f02": [(len(cash),)],
        "f03": [
            (average("fare_amount", [r for r in trips if positive(r, "trip_distance_mi", 10)]),)
        ],
        "f04": [(total("tip_amount", card),)],
        "f05": count(lambda r: positive(r, "passenger_count", 4)),
        "f06": [(max(values("tip_amount"), default=None),)],
        "f07": count(lambda r: positive(r, "tolls_amount")),
        "f08": [(average("trip_distance_mi", by_passenger.get(1, [])),)],
        "f09": count(lambda r: r["total_amount"] is not None and 50 <= r["total_amount"] <= 100),
        "f10": [
            (100 * sum(positive(r, "tip_amount") for r in card) / len(card) if card else None,)
        ],
        "g01": [(code, len(rows)) for code, rows in by_payment.items()],
        "g02": [(code, len(rows)) for code, rows in pickup_counts[:5]],
        "g03": [
            (n, average("fare_amount", rows)) for n, rows in by_passenger.items() if n is not None
        ],
        "g04": [(n, len(rows)) for n, rows in by_vendor.items() if len(rows) > 1000],
        "g05": sorted(
            [(n, total("total_amount", rows)) for n, rows in by_vendor.items()],
            key=lambda row: (-row[1], key(row[0])),
        ),
        "g06": sorted(
            [
                (n, average("tip_amount", rows))
                for n, rows in by_dropoff.items()
                if len(rows) >= 500
            ],
            key=lambda row: (-row[1], key(row[0])),
        )[:3],
        "g07": [(n, average("tip_amount", rows)) for n, rows in by_payment.items()],
        "g08": sorted(
            [(n, len(rows)) for n, rows in by_passenger.items() if n is not None and 1 <= n <= 6]
        ),
        "g09": [
            (n, max(values("fare_amount", rows), default=None)) for n, rows in by_vendor.items()
        ],
        "g10": sorted(
            [(n, total("tolls_amount", rows)) for n, rows in by_pickup.items()],
            key=lambda row: (-row[1], key(row[0])),
        )[:10],
        "j01": [(n, len(rows)) for n, rows in boroughs.items()],
        "j02": [(zones[n]["zone"], len(rows)) for n, rows in pickup_counts if n in zones][:5],
        "j03": [(payments[n], len(rows)) for n, rows in by_payment.items() if n in payments],
        "j04": count(
            lambda r: r["do_zone_id"] in zones and zones[r["do_zone_id"]]["zone"] == "JFK Airport"
        ),
        "j05": [
            (
                average(
                    "tip_amount",
                    [r for r in picked_up if zones[r["pu_zone_id"]]["zone"] == "LaGuardia Airport"],
                ),
            )
        ],
        "j06": count(
            lambda r: (
                r["pu_zone_id"] in zones
                and r["do_zone_id"] in zones
                and zones[r["pu_zone_id"]]["borough"] is not None
                and zones[r["pu_zone_id"]]["borough"] == zones[r["do_zone_id"]]["borough"]
            )
        ),
        "j07": [(n, average("fare_amount", rows)) for n, rows in cash_boroughs.items()],
        "j08": [
            (zones[p]["zone"], zones[d]["zone"], n)
            for (p, d), n in sorted(pairs.items(), key=lambda item: (-item[1], item[0]))[:5]
        ],
        "t01": [(hour, len(rows)) for hour, rows in by_hour.items()],
        "t02": [(math.fsum(durations) / len(durations) / 60 if durations else None,)],
        "t03": list(day_counts.items()),
        "t04": count(lambda r: datetime.fromisoformat(r["pickup_at"]).weekday() in (5, 6)),
        "t05": sorted(
            [(hour, average("fare_amount", rows)) for hour, rows in by_hour.items()],
            key=lambda row: (-row[1], row[0]),
        )[:1],
        "t06": [(sum(duration > 7200 for duration in durations),)],
        "w01": count(lambda r: positive(r, "fare_amount", average_fare)),
        "w02": [(borough, zone, n) for borough, (zone, n) in winners.items()],
        "w03": [(code, 100 * len(rows) / len(trips)) for code, rows in by_payment.items()],
        "w04": [
            (code, len(rows), 1 + sum(len(other) > len(rows) for other in by_vendor.values()))
            for code, rows in vendor_counts
        ],
        "d01": [(sum(duration < 0 for duration in durations),)],
        "d02": count(lambda r: not "2024-01-01" <= r["pickup_at"][:10] < "2024-02-01"),
    }


def verify(db_path: Path, questions_path: Path) -> dict:
    questions = [
        json.loads(line)
        for line in questions_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    before = file_sha256(db_path)
    conn = open_readonly(db_path)
    try:
        expected = references(conn)
        assert {q["id"] for q in questions} == set(expected), (
            "Reference set must cover all questions"
        )
        items = []
        for question in questions:
            actual = execute(conn, question["gold_sql"], timeout_s=30, max_rows=500)
            rows = expected[question["id"]]

            def normalize(data):
                return [
                    tuple(round(v, 2) if isinstance(v, float) else v for v in row) for row in data
                ]

            a, b = normalize(actual.rows), normalize(rows)
            passed = a == b if question["ordered"] else Counter(a) == Counter(b)
            ident = question["id"]
            width = (
                1
                if ident.startswith(("f", "d"))
                or ident in ("j04", "j05", "j06", "t02", "t04", "t06", "w01")
                else 3
                if ident in ("j08", "w02", "w04")
                else 2
            )
            passed = passed and len(actual.columns) == width
            if question["id"] in ("t01", "t05"):
                passed = passed and all(type(row[0]) is int for row in actual.rows)
            items.append(
                {
                    "id": question["id"],
                    "passed": passed,
                    "question": question["question"],
                    "gold_sql": question["gold_sql"],
                    "expected_rows": rows,
                    "actual_rows": actual.rows,
                    "column_count": len(actual.columns),
                }
            )
    finally:
        conn.close()
    after = file_sha256(db_path)
    return {
        "reviewer": "Codex",
        "verification_method": "automated",
        "method": "Semantic review plus independent Python calculations over raw database rows; "
        "float comparisons at two decimals, matching the evaluation contract.",
        "human_verified": False,
        "verified_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "database_sha256_before": before,
        "database_sha256_after": after,
        "questions_sha256": file_sha256(questions_path),
        "n": len(items),
        "passed": sum(item["passed"] for item in items),
        "items": items,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=ROOT / "data/taxi.db")
    parser.add_argument("--questions", type=Path, default=resource_path("eval/questions.jsonl"))
    parser.add_argument("--out", type=Path, default=ROOT / "results/gold-verification.json")
    parser.add_argument("--sign-off", action="store_true", help="record automated review metadata")
    args = parser.parse_args()
    result = verify(args.db, args.questions)
    passed = result["passed"] == result["n"] and (
        result["database_sha256_before"] == result["database_sha256_after"]
    )
    if args.sign_off and passed:
        questions = [
            json.loads(line)
            for line in args.questions.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        for question in questions:
            question.update(
                verified_by=result["reviewer"],
                verification_method="automated",
                verified_at=result["verified_at"],
            )
        args.questions.write_text(
            "".join(json.dumps(q) + "\n" for q in questions), encoding="utf-8"
        )
        result["questions_sha256"] = file_sha256(args.questions)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        f"Independent gold checks: {result['passed']}/{result['n']}; database unchanged: "
        f"{result['database_sha256_before'] == result['database_sha256_after']}",
        flush=True,
    )
    for item in result["items"]:
        print(f"{item['id']}: {'PASS' if item['passed'] else 'FAIL'}", flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
