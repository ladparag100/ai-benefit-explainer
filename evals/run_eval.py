"""Run the eval suite end to end and write a report.

    # one-time: build fixtures + golden dataset
    python -m evals.generators.synthetic_data
    python -m evals.generators.golden_cases

    # quick smoke run (one case per intent + all adversarial)
    python -m evals.run_eval --tags smoke adversarial

    # full nightly-style run, 3 repeats, fail the process if under thresholds
    python -m evals.run_eval --repeats 3 --gate

    # re-score a previous run's saved traces without calling the model
    python -m evals.run_eval --rescore evals/reports/<run>/results.jsonl

    # also upload the run to LangSmith (needs LANGSMITH_API_KEY)
    python -m evals.run_eval --tags smoke adversarial --export langsmith

Reports land in evals/reports/<timestamp>/: results.jsonl (every trace +
score), summary.json (machine-readable, for CI / baselines) and summary.md.
"""

import argparse
import asyncio
import json
import statistics
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from evals.harness.runner import CaseTrace, ToolCall, configure_env
from evals.paths import DATASETS_DIR, FIXTURES_DIR, REPORTS_DIR, THRESHOLDS_PATH
from evals.scorers import METRICS, score_case

DEFAULT_DATASETS = [DATASETS_DIR / "golden_v1.jsonl", DATASETS_DIR / "adversarial_v1.jsonl"]


def load_cases(paths: list[Path], tags: list[str], ids: list[str], limit: int) -> list[dict]:
    cases = []
    for path in paths:
        with open(path) as f:
            cases += [json.loads(line) for line in f if line.strip()]
    if tags:
        cases = [c for c in cases if set(tags) & set(c["tags"])]
    if ids:
        cases = [c for c in cases if any(c["id"].startswith(i) for i in ids)]
    return cases[:limit] if limit else cases


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


async def run_all(cases: list[dict], repeats: int, concurrency: int) -> list[tuple[dict, int, CaseTrace]]:
    from evals.harness.runner import AgentHarness

    harness = AgentHarness()
    sem = asyncio.Semaphore(concurrency)
    done = 0
    total = len(cases) * repeats

    async def one(case, rep):
        nonlocal done
        async with sem:
            trace = await harness.run_case(case)
        done += 1
        status = "ERR" if trace.error else "ok"
        print(f"[{done}/{total}] {case['id']} r{rep} {status} {trace.latency_s:.1f}s", file=sys.stderr)
        return case, rep, trace

    return await asyncio.gather(*(one(c, r) for c in cases for r in range(repeats)))


def _trace_from_dict(d: dict) -> CaseTrace:
    calls = [ToolCall(**c) for c in d.pop("tool_calls")]
    return CaseTrace(**d, tool_calls=calls)


def summarize(rows: list[dict], meta: dict) -> dict:
    by_metric: dict = defaultdict(list)
    by_intent: dict = defaultdict(list)
    by_case: dict = defaultdict(list)
    for r in rows:
        case_pass = all(s["passed"] for s in r["scores"])
        by_intent[r["intent"]].append(case_pass)
        by_case[r["case_id"]].append(case_pass)
        for s in r["scores"]:
            if s["applicable"]:
                by_metric[s["metric"]].append(s)

    metrics = {}
    for m in METRICS:
        scores = by_metric.get(m, [])
        if scores:
            metrics[m] = {
                "pass_rate": round(sum(s["passed"] for s in scores) / len(scores), 4),
                "mean_score": round(statistics.mean(s["score"] for s in scores), 4),
                "n": len(scores),
            }

    latencies = sorted(r["trace"]["latency_s"] for r in rows)
    p = lambda q: latencies[min(len(latencies) - 1, int(q * len(latencies)))] if latencies else 0
    return {
        **meta,
        "runs": len(rows),
        "cases": len(by_case),
        "overall_pass_rate": round(sum(all(s["passed"] for s in r["scores"]) for r in rows) / max(len(rows), 1), 4),
        # pass^k: share of cases that passed on *every* repeat -- the
        # consistency number that matters for a member-facing assistant.
        "pass_all_repeats": round(sum(all(v) for v in by_case.values()) / max(len(by_case), 1), 4),
        "run_errors": sum(1 for r in rows if r["trace"]["error"]),
        "metrics": metrics,
        "by_intent": {k: round(sum(v) / len(v), 4) for k, v in sorted(by_intent.items())},
        "latency_s": {"p50": p(0.5), "p95": p(0.95)},
        "tokens": {
            "input_total": sum(r["trace"]["input_tokens"] for r in rows),
            "output_total": sum(r["trace"]["output_tokens"] for r in rows),
            "avg_model_calls_per_run": round(statistics.mean(r["trace"]["model_calls"] for r in rows), 2) if rows else 0,
        },
    }


def check_gate(summary: dict, thresholds: dict) -> list[str]:
    failures = []
    for metric, minimum in thresholds.items():
        if metric.startswith("_") or metric == "run_errors_max":
            continue
        got = summary["metrics"].get(metric, {}).get("pass_rate")
        if got is not None and got < minimum:
            failures.append(f"{metric}: {got:.1%} < {minimum:.0%}")
    if summary["run_errors"] > thresholds.get("run_errors_max", 0):
        failures.append(f"run_errors: {summary['run_errors']} > {thresholds.get('run_errors_max', 0)}")
    return failures


def render_markdown(summary: dict, rows: list[dict], gate_failures: list[str]) -> str:
    lines = [
        f"# Eval run {summary['run_id']}",
        "",
        f"git `{summary['git_sha']}` · supervisor `{summary['supervisor_model']}` · specialist `{summary['specialist_model']}` · "
        f"{summary['cases']} cases × {summary['repeats']} repeats = {summary['runs']} runs",
        "",
        f"**Overall pass rate:** {summary['overall_pass_rate']:.1%} · **pass on every repeat:** {summary['pass_all_repeats']:.1%} · "
        f"**run errors:** {summary['run_errors']} · **latency** p50 {summary['latency_s']['p50']}s / p95 {summary['latency_s']['p95']}s",
        "",
    ]
    if gate_failures:
        lines += ["**Gate: FAILED**", ""] + [f"- {f}" for f in gate_failures] + [""]
    lines += ["| Metric | Pass rate | Mean score | n |", "|---|---|---|---|"]
    for m, v in summary["metrics"].items():
        lines.append(f"| {m} | {v['pass_rate']:.1%} | {v['mean_score']:.2f} | {v['n']} |")
    lines += ["", "## By intent", "", "| Intent | Pass rate |", "|---|---|"]
    lines += [f"| {k} | {v:.0%} |" for k, v in summary["by_intent"].items()]

    failed = [r for r in rows if not all(s["passed"] for s in r["scores"])]
    lines += ["", f"## Failures ({len(failed)})", ""]
    for r in failed:
        lines.append(f"### {r['case_id']} (r{r['repeat']}) — member {r['member_id']}")
        lines.append("")
        for t, reply in zip(r["trace"]["turns"], r["trace"]["replies"] or [""]):
            lines.append(f"> **User:** {t}")
            lines.append(">")
            lines.append("> **Reply:** " + reply.strip().replace("\n", "\n> "))
            lines.append("")
        for s in r["scores"]:
            if not s["passed"]:
                lines.append(f"- **{s['metric']}**: " + "; ".join(s["details"]))
        calls = [f"{c['agent']}→{c['tool']}" for c in r["trace"]["tool_calls"]]
        lines.append(f"- calls: {' , '.join(calls) or 'none'}")
        if r["trace"]["error"]:
            lines.append(f"- error: `{r['trace']['error']}`")
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", type=Path, nargs="+", default=DEFAULT_DATASETS)
    parser.add_argument("--tags", nargs="*", default=[], help="keep cases having ANY of these tags")
    parser.add_argument("--ids", nargs="*", default=[], help="keep cases whose id starts with any of these")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--data-dir", type=Path, default=FIXTURES_DIR)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--gate", action="store_true", help="exit 1 if any metric is under thresholds.json")
    parser.add_argument("--rescore", type=Path, default=None, help="re-score a saved results.jsonl instead of running the agent")
    parser.add_argument("--export", choices=["langsmith"], default=None, help="upload the finished run (see evals/exporters/)")
    args = parser.parse_args()

    if not (args.data_dir / "members.json").exists():
        sys.exit(f"No fixtures at {args.data_dir}. Run: python -m evals.generators.synthetic_data")
    with open(args.data_dir / "members.json") as f:
        members = json.load(f)

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = args.out or REPORTS_DIR / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.rescore:
        with open(args.rescore) as f:
            old = [json.loads(line) for line in f]
        triples = [(r["case"], r["repeat"], _trace_from_dict(r["trace"])) for r in old]
        meta_src = json.loads((args.rescore.parent / "summary.json").read_text())
        models = (meta_src["supervisor_model"], meta_src["specialist_model"])
        repeats = meta_src["repeats"]
    else:
        configure_env(args.data_dir)
        from app.config import SPECIALIST_MODEL, SUPERVISOR_MODEL

        cases = load_cases(args.dataset, args.tags, args.ids, args.limit)
        if not cases:
            sys.exit("No cases matched the filters.")
        print(f"Running {len(cases)} cases × {args.repeats} repeats against {SUPERVISOR_MODEL}", file=sys.stderr)
        triples = asyncio.run(run_all(cases, args.repeats, args.concurrency))
        models = (SUPERVISOR_MODEL, SPECIALIST_MODEL)
        repeats = args.repeats

    rows = []
    for case, rep, trace in triples:
        scores = score_case(case, trace, members)
        rows.append({
            "case_id": case["id"], "intent": case["intent"], "member_id": case["member_id"], "repeat": rep,
            "case": case, "trace": trace.to_dict(), "scores": [s.__dict__ for s in scores],
        })

    meta = {
        "run_id": run_id, "git_sha": _git_sha(), "supervisor_model": models[0], "specialist_model": models[1],
        "repeats": repeats, "data_dir": str(args.data_dir),
    }
    summary = summarize(rows, meta)
    thresholds = json.loads(THRESHOLDS_PATH.read_text())
    gate_failures = check_gate(summary, thresholds)
    summary["gate_failures"] = gate_failures

    with open(out_dir / "results.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r, default=str) + "\n")
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (out_dir / "summary.md").write_text(render_markdown(summary, rows, gate_failures))

    print(f"\nOverall {summary['overall_pass_rate']:.1%} over {summary['runs']} runs")
    for m, v in summary["metrics"].items():
        print(f"  {m:<11} {v['pass_rate']:.1%}  (n={v['n']})")
    print(f"Report: {out_dir / 'summary.md'}")
    if args.export == "langsmith":
        from evals.exporters.langsmith_export import export_run

        export_run(out_dir)
    if args.gate and gate_failures:
        print("GATE FAILED:\n  " + "\n  ".join(gate_failures))
        sys.exit(1)


if __name__ == "__main__":
    main()
