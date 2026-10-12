"""Upload an eval run to LangSmith as a dataset + experiment.

    python -m evals.exporters.langsmith_export evals/reports/<run>
    # or, at the end of a run:
    python -m evals.run_eval --tags smoke adversarial --export langsmith

What lands in LangSmith:
- Dataset `ai-benefit-explainer-evals`: one example per eval case, upserted
  by a stable id derived from the case id, so re-exports update rather than
  duplicate. Golden vs adversarial cases are dataset *splits*.
- One experiment per run: each case's replies as outputs, the
  supervisor -> specialist -> tool calls as a nested trace, and one feedback
  score per metric (routing, facts, leakage, ...) plus an overall `pass`.

Scores are uploaded exactly as computed by evals/scorers -- nothing is
re-run or re-scored here -- so LangSmith always matches summary.md. Needs
LANGSMITH_API_KEY (and LANGSMITH_ENDPOINT / LANGSMITH_WORKSPACE_ID if used)
in the environment.
"""

import argparse
import json
import threading
import uuid
from collections import defaultdict, deque
from pathlib import Path

DATASET_NAME = "ai-benefit-explainer-evals"
_ID_NAMESPACE = uuid.UUID("6f1c2a52-9a43-4f7e-9d0b-0f5c3b1e8a11")
SPECIALISTS = {
    "benefits_agent", "id_card_agent", "find_doctor_agent",
    "claims_agent", "billing_agent", "escalation_agent",
}


def _example_id(case_id: str) -> str:
    return str(uuid.uuid5(_ID_NAMESPACE, f"{DATASET_NAME}/{case_id}"))


def _split(case: dict) -> str:
    return "adversarial" if "adversarial" in case["tags"] else "golden"


def _example(case: dict) -> dict:
    return {
        "id": _example_id(case["id"]),
        "inputs": {"case_id": case["id"], "member_id": case["member_id"], "turns": case["turns"]},
        "outputs": {"expected": case["expected"], "judge_notes": case.get("judge_notes", "")},
        "metadata": {"intent": case["intent"], "tags": case["tags"], "member_id": case["member_id"]},
        "split": _split(case),
    }


def sync_dataset(client, cases: list[dict]):
    """Create the dataset if needed and upsert every case. Returns the
    LangSmith Example objects for exactly these cases."""
    if client.has_dataset(dataset_name=DATASET_NAME):
        dataset = client.read_dataset(dataset_name=DATASET_NAME)
    else:
        dataset = client.create_dataset(
            DATASET_NAME, description="AI Benefit Explainer eval cases (generated golden + hand-written adversarial). Source: evals/datasets/."
        )

    existing = {str(e.id): e for e in client.list_examples(dataset_id=dataset.id)}
    wanted = {_example_id(c["id"]): _example(c) for c in cases}

    to_create = [ex for ex_id, ex in wanted.items() if ex_id not in existing]
    to_update = [
        ex for ex_id, ex in wanted.items()
        if ex_id in existing and (existing[ex_id].inputs != ex["inputs"] or existing[ex_id].outputs != ex["outputs"])
    ]
    if to_create:
        client.create_examples(dataset_id=dataset.id, examples=to_create)
    if to_update:
        client.update_examples(dataset_id=dataset.id, updates=to_update)
    print(f"Dataset {DATASET_NAME}: {len(to_create)} added, {len(to_update)} updated, {len(wanted) - len(to_create) - len(to_update)} unchanged")

    examples = [e for e in client.list_examples(dataset_id=dataset.id) if str(e.id) in wanted]
    return dataset, examples


def _replay_tool_calls(tool_calls: list[dict]) -> None:
    """Re-emit the recorded calls as nested LangSmith runs: each specialist
    call becomes a parent with that specialist's inner tool calls under it."""
    from langsmith.run_helpers import trace

    by_specialist: dict = defaultdict(list)
    for c in tool_calls:
        if c["tool"] not in SPECIALISTS:
            by_specialist[(c["turn"], c["agent"])].append(c)

    for c in tool_calls:
        if c["tool"] not in SPECIALISTS:
            if c["agent"] == "supervisor":  # a tool the supervisor called directly
                with trace(c["tool"], "tool", inputs=c["args"]) as rt:
                    rt.end(outputs={"result": c["result"]}, error=c["error"])
            continue
        with trace(c["tool"], "chain", inputs=c["args"], metadata={"turn": c["turn"]}) as parent:
            for inner in by_specialist.pop((c["turn"], c["tool"]), []):
                with trace(inner["tool"], "tool", inputs=inner["args"]) as rt:
                    rt.end(outputs={"result": inner["result"]}, error=inner["error"])
            parent.end(outputs={"result": c["result"]}, error=c["error"])


def export_run(report_dir: Path) -> str:
    from langsmith import Client, evaluate, traceable

    rows = [json.loads(line) for line in open(report_dir / "results.jsonl")]
    summary = json.loads((report_dir / "summary.json").read_text())
    client = Client()

    cases = list({r["case_id"]: r["case"] for r in rows}.values())
    _, examples = sync_dataset(client, cases)

    # evaluate() calls the target once per example per repetition; hand out
    # the recorded repeats in order instead of re-running the agent.
    queues: dict = defaultdict(deque)
    for r in sorted(rows, key=lambda r: r["repeat"]):
        queues[r["case_id"]].append(r)
    lock = threading.Lock()

    @traceable(name="ai-benefit-explainer")
    def replay(inputs: dict) -> dict:
        with lock:
            row = queues[inputs["case_id"]].popleft()
        t = row["trace"]
        _replay_tool_calls(t["tool_calls"])
        return {
            "reply": t["replies"][-1] if t["replies"] else "",
            "replies": t["replies"],
            "error": t["error"],
            "latency_s": t["latency_s"],
            "tokens": {"input": t["input_tokens"], "output": t["output_tokens"], "model_calls": t["model_calls"]},
            "routed_to": [c["tool"] for c in t["tool_calls"] if c["tool"] in SPECIALISTS],
            "eval_scores": row["scores"],
        }

    def recorded_scores(run, example) -> dict:
        scores = (run.outputs or {}).get("eval_scores", [])
        results = [
            {"key": s["metric"], "score": s["score"], "comment": "; ".join(s["details"]) or None}
            for s in scores if s["applicable"]
        ]
        failed = [s["metric"] for s in scores if not s["passed"]]
        results.append({"key": "pass", "score": int(not failed), "comment": f"failed: {', '.join(failed)}" if failed else None})
        return {"results": results}

    prefix = f"{summary['git_sha']}-{summary['supervisor_model']}"
    results = evaluate(
        replay,
        data=examples,
        evaluators=[recorded_scores],
        experiment_prefix=prefix,
        description=f"Local run {summary['run_id']} ({summary['cases']} cases x {summary['repeats']} repeats). Overall pass {summary['overall_pass_rate']:.1%}.",
        metadata={k: summary[k] for k in ("run_id", "git_sha", "supervisor_model", "specialist_model", "repeats", "overall_pass_rate", "pass_all_repeats", "run_errors")},
        num_repetitions=summary["repeats"],
        max_concurrency=4,
        client=client,
    )
    name = results.experiment_name
    print(f"Experiment: {name}")
    return name


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("report_dir", type=Path, help="an evals/reports/<run> directory")
    args = parser.parse_args()
    export_run(args.report_dir)


if __name__ == "__main__":
    main()
