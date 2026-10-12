"""Evaluation harness: execution accuracy per strategy, plus the adversarial set.

Writes results/eval-<YYYYMMDD-HHMM>.json with enough provenance to reproduce the run.
"""

from __future__ import annotations

import json
import os
import platform
import sqlite3
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from asksql import pipeline
from asksql.config import ALLOWED_TABLES, ROOT, Settings, resource_path
from asksql.db import QueryError, QueryTimeout, execute, file_sha256, open_readonly
from asksql.evaluation.compare import MATCH, compare_results
from asksql.guard import check_sql
from asksql.providers.base import Provider

QUESTIONS_PATH = resource_path("eval/questions.jsonl")
ADVERSARIAL_PATH = resource_path("eval/adversarial.jsonl")
RESULTS_DIR = ROOT / "results"


def load_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def select_questions(questions: list[dict], include_unverified: bool) -> list[dict]:
    """Only reviewed gold SQL counts; the result records each review method."""
    if include_unverified:
        return list(questions)
    return [q for q in questions if q.get("verified_by")]


def mock_answer_key(questions: list[dict], adversarial: list[dict]) -> dict[str, str]:
    """Answers for the mock provider: the gold SQL, and each attack's payload."""
    key = {q["question"]: f"```sql\n{q['gold_sql']}\n```" for q in questions}
    key.update({a["prompt"]: f"```sql\n{a['sql']}\n```" for a in adversarial})
    return key


# --------------------------------------------------------------------- provenance


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def git_info() -> dict:
    sha = _git("rev-parse", "HEAD")
    status = _git("status", "--porcelain")
    return {"git_sha": sha, "dirty": bool(status) if sha else None}


def _cpu_model() -> str:
    if sys.platform == "win32":
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
            )
            return winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
        except OSError:
            pass
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or platform.machine()


def _ram_gb() -> float | None:
    if sys.platform == "win32":
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(MemoryStatus)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return round(status.ullTotalPhys / 2**30, 1)
        return None
    try:
        return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30, 1)
    except (ValueError, OSError, AttributeError):
        return None


def machine_info() -> dict:
    return {
        "os": f"{platform.system()} {platform.release()}",
        "cpu": _cpu_model(),
        "cores": os.cpu_count(),
        "ram_gb": _ram_gb(),
    }


def run_test_suite() -> dict:
    """Run the unit tests at this checkout and return pass/fail/skip counts."""
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "junit.xml"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                f"--junitxml={report}",
            ],
            cwd=ROOT,
            capture_output=True,
            check=False,
        )
        if not report.is_file():
            return {"passed": None, "failed": None, "skipped": None}
        root = ET.parse(report).getroot()
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    total = int(suite.get("tests", 0))
    failed = int(suite.get("failures", 0)) + int(suite.get("errors", 0))
    skipped = int(suite.get("skipped", 0))
    return {"passed": total - failed - skipped, "failed": failed, "skipped": skipped}


def data_info(conn: sqlite3.Connection) -> dict:
    trip_rows = conn.execute("SELECT COUNT(*) FROM trips").fetchone()[0]
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = 'data_source'").fetchone()
        source = row[0] if row else "unknown"
    except sqlite3.Error:
        source = "fixture"
    return {"data_source": source, "trip_rows": trip_rows}


# --------------------------------------------------------------------- scoring


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, -(-len(ordered) * pct // 100))  # nearest-rank, ceil
    return ordered[int(rank) - 1]


def evaluate_strategy(
    questions: list[dict],
    provider: Provider,
    conn: sqlite3.Connection,
    strategy: str,
    settings: Settings,
    progress=None,
) -> dict:
    items = []
    for q in questions:
        gold = execute(conn, q["gold_sql"], timeout_s=30.0, max_rows=settings.max_limit)
        answer = pipeline.ask(
            q["question"],
            provider,
            conn,
            strategy=strategy,
            max_limit=settings.max_limit,
            timeout_s=settings.timeout_s,
        )
        if answer.failure is None:
            verdict = compare_results(answer.rows, gold.rows, bool(q.get("ordered")))
            failure = None if verdict == MATCH else verdict
        else:
            failure = answer.failure
        item = {
            "id": q["id"],
            "category": q["category"],
            "question": q["question"],
            "ok": failure is None,
            "failure_type": failure,
            "pred_sql": answer.sql,
            "gold_sql": q["gold_sql"],
            "attempts": answer.attempts,
            "latency_ms": answer.latency_ms,
            "detail": answer.blocked_reason or answer.error,
        }
        items.append(item)
        if progress:
            progress(strategy, item)

    by_category: dict[str, dict] = {}
    for item in items:
        bucket = by_category.setdefault(item["category"], {"n": 0, "correct": 0})
        bucket["n"] += 1
        bucket["correct"] += int(item["ok"])
    for bucket in by_category.values():
        bucket["accuracy"] = round(bucket["correct"] / bucket["n"], 4)

    correct = sum(item["ok"] for item in items)
    latencies = [item["latency_ms"] for item in items]
    return {
        "n": len(items),
        "correct": correct,
        "accuracy": round(correct / len(items), 4) if items else None,
        "by_category": by_category,
        "failures_by_type": dict(Counter(i["failure_type"] for i in items if not i["ok"])),
        "false_blocks": sum(1 for i in items if i["failure_type"] == pipeline.BLOCKED),
        "repair_attempts": sum(1 for i in items if i["attempts"] > 1),
        "p50_latency_ms": _percentile(latencies, 50),
        "p95_latency_ms": _percentile(latencies, 95),
        "items": items,
    }


def _run_directly(conn: sqlite3.Connection, sql: str, settings: Settings) -> str:
    """What the executor alone does with a statement, with no guard in front of it."""
    try:
        execute(conn, sql, timeout_s=settings.timeout_s, max_rows=settings.max_limit)
    except QueryTimeout:
        return "timeout"
    except QueryError as err:
        return f"denied: {err}"
    return "ran_read_only"


def evaluate_adversarial(
    items: list[dict],
    provider: Provider,
    conn: sqlite3.Connection,
    db_path: Path,
    settings: Settings,
    strategy: str = "s2",
    progress=None,
) -> dict:
    """Each attack takes three paths: guard, bare executor, and the full pipeline.

    An item passes when the database file is byte-identical afterwards.
    """
    baseline = file_sha256(db_path)
    results = []
    for item in items:
        verdict = check_sql(item["sql"], ALLOWED_TABLES, settings.max_limit)
        if verdict.ok:
            guard_outcome = "allowed: " + _run_directly(conn, verdict.sql, settings)
        else:
            guard_outcome = f"blocked: {verdict.reason}"
        executor_outcome = _run_directly(conn, item["sql"], settings)

        answer = pipeline.ask(
            item["prompt"],
            provider,
            conn,
            strategy=strategy,
            max_limit=settings.max_limit,
            timeout_s=settings.timeout_s,
        )
        if answer.failure == pipeline.BLOCKED:
            model_outcome = f"blocked: {answer.blocked_reason}"
        elif answer.failure:
            model_outcome = answer.failure
        else:
            model_outcome = "ran_read_only"

        unchanged = file_sha256(db_path) == baseline
        result = {
            "id": item["id"],
            "attack": item["attack"],
            "passed": unchanged,
            "guard": guard_outcome,
            "executor_without_guard": executor_outcome,
            "model_sql": answer.sql,
            "model": model_outcome,
            "db_unchanged": unchanged,
        }
        results.append(result)
        if progress:
            progress("adversarial", result)
    return {
        "adversarial_total": len(results),
        "adversarial_pass": sum(r["passed"] for r in results),
        "guard_blocked": sum(r["guard"].startswith("blocked") for r in results),
        "items": results,
    }


def run_eval(
    provider: Provider,
    db_path: Path,
    settings: Settings,
    strategies: list[str],
    questions_path: Path = QUESTIONS_PATH,
    adversarial_path: Path = ADVERSARIAL_PATH,
    out_dir: Path = RESULTS_DIR,
    include_unverified: bool = False,
    run_tests: bool = True,
    limit: int | None = None,
    progress=None,
) -> tuple[Path, dict]:
    started = datetime.now(UTC)
    all_questions = load_jsonl(questions_path)
    questions = select_questions(all_questions, include_unverified)
    if limit:
        questions = questions[:limit]
    adversarial = load_jsonl(adversarial_path)

    sha_before = file_sha256(db_path)
    conn = open_readonly(db_path)
    try:
        result: dict = {
            **git_info(),
            "started_at": started.isoformat(timespec="seconds"),
            "finished_at": None,
            "command": " ".join(["asksql", *sys.argv[1:]]),
            "params": {
                "strategies": strategies,
                "provider": provider.name,
                "temperature": 0,
                "max_limit": settings.max_limit,
                "timeout_s": settings.timeout_s,
                "include_unverified": include_unverified,
                "limit": limit,
            },
            "machine": machine_info(),
            "python": platform.python_version(),
            "tests": run_test_suite() if run_tests else None,
            "model_tag": provider.model,
            "model_digest": getattr(provider, "model_digest", lambda: None)(),
            **data_info(conn),
            "n_questions": len(all_questions),
            "n_verified": sum(1 for q in all_questions if q.get("verified_by")),
            "n_evaluated": len(questions),
            "gold_review": {
                "reviewers": sorted({q["verified_by"] for q in questions if q.get("verified_by")}),
                "methods": dict(
                    Counter(
                        q.get("verification_method", "human")
                        for q in questions
                        if q.get("verified_by")
                    )
                ),
                "questions_sha256": file_sha256(questions_path),
            },
            "strategies": {},
        }
        for strategy in strategies:
            result["strategies"][strategy] = evaluate_strategy(
                questions, provider, conn, strategy, settings, progress
            )
        result["adversarial"] = evaluate_adversarial(
            adversarial, provider, conn, db_path, settings, progress=progress
        )
    finally:
        conn.close()

    result["false_blocks"] = sum(s["false_blocks"] for s in result["strategies"].values())
    result["adversarial_pass"] = result["adversarial"]["adversarial_pass"]
    result["adversarial_total"] = result["adversarial"]["adversarial_total"]
    result["db_sha256_before"] = sha_before
    result["db_sha256_after"] = file_sha256(db_path)
    finished = datetime.now(UTC)
    result["finished_at"] = finished.isoformat(timespec="seconds")

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"eval-{started.astimezone():%Y%m%d-%H%M}.json"
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return out_path, result
