"""Command-line entry point: asksql ask | eval | report | gold | serve."""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from asksql import pipeline
from asksql.config import ALLOWED_TABLES, ROOT, get_settings, resource_path
from asksql.db import QueryError, execute, open_readonly
from asksql.evaluation import report, run_eval
from asksql.guard import check_sql
from asksql.providers import MockProvider, ProviderError, get_provider
from asksql.schema import build_db_from_script

FIXTURE_SQL = resource_path("tests/fixtures/tiny.sql")
FIXTURE_DB = ROOT / "build" / "tiny.db"


def format_table(columns: list[str], rows: list[tuple], max_rows: int = 20) -> str:
    shown = [[("NULL" if c is None else str(c)) for c in row] for row in rows[:max_rows]]
    widths = [max(len(str(col)), *(len(r[i]) for r in shown)) for i, col in enumerate(columns)]
    line = "  ".join(str(col).ljust(w) for col, w in zip(columns, widths, strict=True))
    out = [line, "  ".join("-" * w for w in widths)]
    out += ["  ".join(c.ljust(w) for c, w in zip(r, widths, strict=True)) for r in shown]
    if len(rows) > max_rows:
        out.append(f"... {len(rows) - max_rows} more rows")
    return "\n".join(out)


def print_answer(answer: pipeline.AskResult) -> None:
    print(f"SQL:\n  {answer.sql or '(none)'}")
    if answer.failure == pipeline.BLOCKED:
        print(f"BLOCKED: {answer.blocked_reason}")
    elif answer.failure:
        print(f"FAILED ({answer.failure}): {answer.error}")
    else:
        print(format_table(answer.columns, answer.rows))
        print(f"{answer.row_count} row(s)")
    print(f"attempts: {answer.attempts}, latency: {answer.latency_ms:.0f} ms")


def cmd_ask(args) -> int:
    settings = get_settings()
    db_path = args.db or settings.db_path
    try:
        provider = get_provider(settings, args.provider, args.model)
        conn = open_readonly(db_path)
    except (ProviderError, FileNotFoundError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    try:
        answer = pipeline.ask(
            args.question,
            provider,
            conn,
            strategy=args.strategy,
            max_limit=settings.max_limit,
            timeout_s=settings.timeout_s,
        )
    finally:
        conn.close()
    print_answer(answer)
    return 0 if answer.failure is None else 2


def cmd_eval(args) -> int:
    settings = get_settings()
    strategies = [s.strip() for s in args.strategies.split(",") if s.strip()]
    unknown = [s for s in strategies if s not in pipeline.STRATEGIES]
    if not strategies or unknown:
        print(f"error: unknown strategies: {unknown}", file=sys.stderr)
        return 1

    if args.limit is not None and args.limit <= 0:
        print("error: --limit must be positive", file=sys.stderr)
        return 1
    if args.timeout is not None and args.timeout <= 0:
        print("error: --timeout must be positive", file=sys.stderr)
        return 1

    if args.fixture_db:
        db_path = build_db_from_script(FIXTURE_SQL, FIXTURE_DB)
    else:
        db_path = args.db or settings.db_path
    if not Path(db_path).is_file():
        print(f"error: database not found: {db_path} (run `make data`)", file=sys.stderr)
        return 1

    name = args.provider or settings.provider
    if name == "mock":
        key = run_eval.mock_answer_key(
            run_eval.load_jsonl(args.questions), run_eval.load_jsonl(args.adversarial)
        )
        provider = MockProvider(key)
    else:
        try:
            provider = get_provider(settings, name, args.model)
        except ProviderError as err:
            print(f"error: {err}", file=sys.stderr)
            return 1
        if hasattr(provider, "is_up") and not provider.is_up():
            print("error: Ollama is not reachable; start it with `ollama serve`", file=sys.stderr)
            return 1
    if args.timeout:
        settings = replace(settings, timeout_s=args.timeout)

    def progress(stage: str, item: dict) -> None:
        if stage == "adversarial":
            mark = "pass" if item["passed"] else "FAIL"
            print(f"  [adv] {item['id']} {item['attack']:<20} {mark}", flush=True)
        else:
            mark = "ok" if item["ok"] else item["failure_type"]
            print(f"  [{stage}] {item['id']} {mark} ({item['latency_ms']:.0f} ms)", flush=True)

    out_path, result = run_eval.run_eval(
        provider,
        Path(db_path),
        settings,
        strategies,
        questions_path=args.questions,
        adversarial_path=args.adversarial,
        out_dir=args.out_dir,
        include_unverified=args.include_unverified,
        run_tests=not args.skip_tests,
        limit=args.limit,
        progress=progress,
    )
    if result["n_evaluated"] == 0:
        print(
            "note: no verified questions. Set verified_by in eval/questions.jsonl after checking "
            "each gold query, or pass --include-unverified for a draft run."
        )
    for strategy, summary in result["strategies"].items():
        if summary["n"]:
            print(f"{strategy}: {summary['correct']}/{summary['n']} = {summary['accuracy']:.1%}")
    print(
        f"adversarial: {result['adversarial_pass']}/{result['adversarial_total']} passed, "
        f"false blocks: {result['false_blocks']}"
    )
    unchanged = result["db_sha256_before"] == result["db_sha256_after"]
    print(f"database unchanged: {unchanged}")
    print(f"wrote {out_path}")
    latest = report.write_latest(args.out_dir, out_path)
    print(f"wrote {latest}")
    return 0 if unchanged else 3


def cmd_report(args) -> int:
    latest = report.write_latest(args.out_dir)
    if latest is None:
        print(f"error: no eval-*.json files in {args.out_dir}", file=sys.stderr)
        return 1
    print(f"wrote {latest}")
    return 0


def cmd_gold(args) -> int:
    """Print every gold query with its result so a person can verify it."""
    settings = get_settings()
    conn = open_readonly(args.db or settings.db_path)
    questions = run_eval.load_jsonl(args.questions)
    problems = 0
    try:
        for q in questions:
            status = f"verified by {q['verified_by']}" if q.get("verified_by") else "UNVERIFIED"
            print(f"\n=== {q['id']} [{q['category']}, ordered={q['ordered']}] {status}")
            print(f"Q: {q['question']}")
            print(f"SQL: {q['gold_sql']}")
            verdict = check_sql(q["gold_sql"], ALLOWED_TABLES, settings.max_limit)
            if not verdict.ok:
                problems += 1
                print(f"!! blocked by the guard: {verdict.reason}")
                continue
            try:
                result = execute(conn, q["gold_sql"], timeout_s=30.0, max_rows=settings.max_limit)
            except QueryError as err:
                problems += 1
                print(f"!! does not run: {err}")
                continue
            if len(result.rows) > 100:
                problems += 1
                print(f"!! {len(result.rows)} rows; the gold result must be 100 rows or fewer")
            print(format_table(result.columns, result.rows, max_rows=args.rows))
            if q.get("notes"):
                print(f"Note: {q['notes']}")
    finally:
        conn.close()
    verified = sum(1 for q in questions if q.get("verified_by"))
    print(f"\n{len(questions)} questions, {verified} verified, {problems} with problems")
    return 1 if problems else 0


def cmd_serve(args) -> int:
    import uvicorn

    uvicorn.run("asksql.api:app", host=args.host, port=args.port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="asksql", description="Guarded natural-language-to-SQL.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("ask", help="answer one question")
    p.add_argument("question")
    p.add_argument("--strategy", choices=pipeline.STRATEGIES, default="s2")
    p.add_argument("--provider", choices=["ollama", "openai_compat"])
    p.add_argument("--model")
    p.add_argument("--db", type=Path)
    p.set_defaults(func=cmd_ask)

    p = sub.add_parser("eval", help="run the evaluation and write results/")
    p.add_argument("--strategies", default="s1,s2")
    p.add_argument("--provider", choices=["ollama", "openai_compat", "mock"])
    p.add_argument("--model")
    p.add_argument("--db", type=Path)
    p.add_argument("--fixture-db", action="store_true", help="use the tiny test database")
    p.add_argument("--questions", type=Path, default=run_eval.QUESTIONS_PATH)
    p.add_argument("--adversarial", type=Path, default=run_eval.ADVERSARIAL_PATH)
    p.add_argument("--out-dir", type=Path, default=run_eval.RESULTS_DIR)
    p.add_argument("--include-unverified", action="store_true", help="draft run; not reportable")
    p.add_argument("--skip-tests", action="store_true", help="do not run pytest for provenance")
    p.add_argument("--limit", type=int, help="evaluate only the first N questions")
    p.add_argument("--timeout", type=float, help="per-query timeout in seconds")
    p.set_defaults(func=cmd_eval)

    p = sub.add_parser("report", help="regenerate results/latest.md")
    p.add_argument("--out-dir", type=Path, default=run_eval.RESULTS_DIR)
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("gold", help="print every gold query and its result for verification")
    p.add_argument("--db", type=Path)
    p.add_argument("--questions", type=Path, default=run_eval.QUESTIONS_PATH)
    p.add_argument("--rows", type=int, default=12, help="result rows to show per question")
    p.set_defaults(func=cmd_gold)

    p = sub.add_parser("serve", help="start the API and web page")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8201)
    p.set_defaults(func=cmd_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
