"""Render results/latest.md from the newest eval JSON. Nothing in results/ is hand-edited."""

from __future__ import annotations

import json
from pathlib import Path

from asksql.evaluation.run_eval import RESULTS_DIR

CATEGORY_ORDER = ["filter_agg", "group_order", "join", "time", "window_subquery", "data_quality"]


def latest_result(results_dir: Path = RESULTS_DIR) -> Path | None:
    files = sorted(results_dir.glob("eval-*.json"))
    return files[-1] if files else None


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _ms(value: float | None) -> str:
    return "n/a" if value is None else f"{value:,.0f}"


def _one_line(sql: str | None) -> str:
    return " ".join(sql.split()) if sql else "(none)"


def render(result: dict, source_name: str) -> str:
    strategies = result["strategies"]
    names = list(strategies)
    machine = result["machine"]
    tests = result.get("tests") or {}
    lines = [
        "# Evaluation results",
        "",
        f"Generated from `results/{source_name}`. Do not edit by hand; run `make report`.",
        "",
    ]
    if result["params"].get("include_unverified"):
        lines += [
            f"> **DRAFT.** This run scored all {result['n_evaluated']} questions, but only "
            f"{result['n_verified']} have reviewed gold SQL. "
            "These numbers are not reportable.",
            "",
        ]

    review = result.get("gold_review", {})
    if review:
        methods = ", ".join(f"{method}: {count}" for method, count in review["methods"].items())
        lines += [
            f"Gold review methods: {methods}. Reviewers: {', '.join(review['reviewers'])}.",
            "Automated review is not human verification."
            if review["methods"].get("automated")
            else "Gold labels were reviewed by the named reviewers.",
            f"Question-set SHA-256: `{review['questions_sha256']}`",
            "",
        ]

    lines += [
        "## Run",
        "",
        f"- Command: `{result['command']}`",
        f"- Model: `{result['model_tag']}` via {result['params']['provider']}, temperature 0",
        f"- Data: {result['data_source']}, {result['trip_rows']:,} trips",
        f"- Questions: {result['n_evaluated']} evaluated, {result['n_verified']} verified, "
        f"{result['n_questions']} in the file",
        f"- Machine: {machine['cpu']}, {machine['cores']} cores, {machine['ram_gb']} GB RAM, "
        f"{machine['os']}, Python {result['python']}",
        f"- Commit: `{result['git_sha'] or 'not a git checkout'}`"
        + (" (dirty)" if result.get("dirty") else ""),
        f"- Tests at this checkout: {tests.get('passed')} passed, {tests.get('failed')} failed, "
        f"{tests.get('skipped')} skipped"
        if tests
        else "- Tests at this checkout: not run",
        f"- Started {result['started_at']}, finished {result['finished_at']}",
        "",
        "## Accuracy by strategy",
        "",
        "| Strategy | Correct | Execution accuracy | Repairs tried | p50 latency (ms) "
        "| p95 latency (ms) |",
        "|---|---|---|---|---|---|",
    ]
    for name in names:
        s = strategies[name]
        lines.append(
            f"| {name.upper()} | {s['correct']}/{s['n']} | {_pct(s['accuracy'])} | "
            f"{s['repair_attempts']} | {_ms(s['p50_latency_ms'])} | {_ms(s['p95_latency_ms'])} |"
        )

    lines += ["", "## Accuracy by category", ""]
    lines.append("| Category | " + " | ".join(n.upper() for n in names) + " |")
    lines.append("|---|" + "---|" * len(names))
    seen = {c for n in names for c in strategies[n]["by_category"]}
    for category in [c for c in CATEGORY_ORDER if c in seen] + sorted(seen - set(CATEGORY_ORDER)):
        cells = []
        for name in names:
            bucket = strategies[name]["by_category"].get(category)
            cells.append(f"{bucket['correct']}/{bucket['n']}" if bucket else "-")
        lines.append(f"| {category} | " + " | ".join(cells) + " |")

    lines += ["", "## Failures by type", ""]
    lines.append("| Failure type | " + " | ".join(n.upper() for n in names) + " |")
    lines.append("|---|" + "---|" * len(names))
    types = sorted({t for n in names for t in strategies[n]["failures_by_type"]})
    for failure in types:
        counts = [str(strategies[n]["failures_by_type"].get(failure, 0)) for n in names]
        lines.append(f"| {failure} | " + " | ".join(counts) + " |")
    if not types:
        lines.append("| (none) | " + " | ".join("0" for _ in names) + " |")

    adv = result["adversarial"]
    lines += [
        "",
        "## Guardrails",
        "",
        f"- Adversarial prompts passed: **{adv['adversarial_pass']}/{adv['adversarial_total']}** "
        "(pass = the database file is byte-identical afterwards)",
        f"- Attack payloads blocked by the guard alone: "
        f"{adv['guard_blocked']}/{adv['adversarial_total']}",
        f"- False blocks on benign questions: **{result['false_blocks']}**",
        f"- Database SHA-256 before: `{result['db_sha256_before']}`",
        f"- Database SHA-256 after: `{result['db_sha256_after']}`",
        "",
        "| Attack | Guard on the payload | Executor with no guard | Model's SQL via the pipeline |",
        "|---|---|---|---|",
    ]
    for item in adv["items"]:
        lines.append(
            f"| {item['attack']} | {item['guard']} | {item['executor_without_guard']} | "
            f"{item['model']} |"
        )

    # Worst failures: the last strategy listed is the strongest prompt, so its misses matter most.
    focus = names[-1]
    failures = [i for i in strategies[focus]["items"] if not i["ok"]]
    shown = min(5, len(failures))
    lines += ["", f"## Failures under {focus.upper()} ({shown} of {len(failures)} shown)", ""]
    if not failures:
        lines.append("None.")
    for item in failures[:5]:
        lines += [
            f"**{item['id']}** ({item['category']}, {item['failure_type']}): {item['question']}",
            "",
            f"- Predicted: `{_one_line(item['pred_sql'])}`",
            f"- Gold: `{_one_line(item['gold_sql'])}`",
        ]
        if item.get("detail"):
            lines.append(f"- Detail: {item['detail']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_latest(results_dir: Path = RESULTS_DIR, source: Path | None = None) -> Path | None:
    source = source or latest_result(results_dir)
    if source is None:
        return None
    result = json.loads(source.read_text(encoding="utf-8"))
    out = results_dir / "latest.md"
    out.write_text(render(result, source.name), encoding="utf-8")
    return out
