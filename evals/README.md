# Evals

End-to-end evaluation for the AI Benefit Explainer: synthetic members →
labelled test cases → run through the real supervisor agent → scored →
report and CI gate.

```
evals/
  generators/
    synthetic_data.py   seeded synthetic members/claims → fixtures/
    golden_cases.py     template cases, labels computed from fixtures → datasets/golden_v1.jsonl
  datasets/
    golden_v1.jsonl     143 generated cases, 24 intents (regenerate, don't hand-edit)
    adversarial_v1.jsonl  14 hand-written injection / leakage / PII / medical / escalation cases
  fixtures/             app-shaped data dir: 6 demo + 24 synthetic members
  harness/runner.py     runs a case through root_agent; plugin records every tool call at every depth
  scorers/              deterministic: routing, trajectory, facts, outcome, format, leakage
  thresholds.json       per-metric minimum pass rates for --gate
  run_eval.py           CLI → reports/<timestamp>/{results.jsonl, summary.json, summary.md}
  exporters/            langsmith_export.py: upload a run as a LangSmith dataset + experiment
  tests/                offline unit tests for generators + scorers (no model calls)
```

## Running

```bash
source .venv/bin/activate
set -a && source .env && set +a          # model credentials

# (re)build data -- only needed when generators change; outputs are committed
python -m evals.generators.synthetic_data --count 24 --seed 7
python -m evals.generators.golden_cases --per-intent 6 --seed 7

pytest evals/tests                        # offline, free, run on every commit

python -m evals.run_eval --tags smoke adversarial        # ~38 cases, PR-sized
python -m evals.run_eval --repeats 3 --gate              # full suite, nightly-sized
python -m evals.run_eval --ids claims. --concurrency 4   # one area
python -m evals.run_eval --rescore evals/reports/<run>/results.jsonl   # re-score, no model calls
```

The harness sets `VSP_DATA_DIR` to `evals/fixtures/`, so the app's tools read
synthetic data with no code changes. Generated ID-card PDFs go to
`evals/.generated/`, not `app/generated/`.

## Viewing results in LangSmith

Needs `LANGSMITH_API_KEY` in `.env` (see `.env.example`).

```bash
python -m evals.run_eval --tags smoke adversarial --export langsmith   # run + upload
python -m evals.exporters.langsmith_export evals/reports/<run>          # upload an existing run
```

- **Datasets → `ai-benefit-explainer-evals`**: every case, with `golden` /
  `adversarial` splits. Re-uploads update cases in place; they don't create duplicates.
- **Experiments tab** on that dataset: one experiment per run, named
  `<git commit>-<model>-<suffix>`. Each check is a column (routing, trajectory, facts,
  outcome, format, leakage, pass), with failure reasons in the comments.
- Click a row to see the nested trace: supervisor → specialist → tool calls with
  arguments and results.
- Select two experiments → **Compare** to see which cases got better or worse after a change.

Scores are uploaded as computed locally (nothing is re-run in LangSmith), so
LangSmith always matches `summary.md`. Uploaded traces are replayed after the
run, so their timings don't reflect real latency; use the `latency_s` output.

## What each metric means

| Metric | Checks | Source of truth |
|---|---|---|
| routing | supervisor called the expected specialist, and only one per turn | system prompt routing table |
| trajectory | expected inner tools ran (with arg constraints); forbidden tools didn't; no tool errors | specialist instructions |
| facts | dollar amounts / names / network status / statuses are in the reply; forbidden content isn't | fixture JSON |
| outcome | answer vs escalate vs clarify vs redirect vs refuse | system prompt rules |
| format | four-beat headers on answers; no headers or ticket ID on escalations | system prompt reply shape |
| leakage | no other member's name/number in replies; every tool ran against the session member | zero tolerance |

A case passes only if every applicable metric passes. `pass_all_repeats`
(pass^k) is the share of cases that passed on every repeat: the consistency
number that matters for a member-facing assistant.

## Frameworks: what we use and what fits where

| Framework | Use it for | Status here |
|---|---|---|
| **Custom deterministic scorers** (this folder) | Exact checks against data: amounts, routing, leakage | ✅ built: the core |
| **Google ADK evaluation** (`google.adk.evaluation`, `adk eval`) | Native for this stack. `tool_trajectory_avg_score`, `final_response_match_v2`, `rubric_based_final_response_quality_v1`, `hallucinations_v1`, `safety_v1`, multi-turn task success, user simulation | next: LLM-judge + hallucination layer |
| **Vertex AI Gen AI Evaluation Service** | Managed LLM-judge metrics, experiment tracking, run comparison in GCP | optional: fits Google-first stack |
| **Ragas** | Retrieval quality for `app/rag/` (context precision/recall, faithfulness) | later: RAG layer |
| **DeepEval** | pytest-style LLM assertions (G-Eval, hallucination, bias) if you want judge checks in pytest | alternative to ADK judges |
| **Promptfoo** | Red-teaming / jailbreak generation, prompt A/B matrices in CI | later: expand adversarial set |
| **Arize Phoenix / Langfuse / LangSmith** | Tracing + online eval of production traffic, human annotation queues | optional: today Cloud Trace/Logging covers tracing |

Rule of thumb: check with code whenever the answer is in the data, and use an
LLM judge only for what code can't check (tone, clarity, empathy,
explanation quality).
Use a judge from a different model family than the one being judged, and
check it against human labels before you trust it.

## Adding cases

- New intent → add a builder + entry to `INTENTS` in `golden_cases.py`, regenerate.
- New adversarial / regression case → append a line to `adversarial_v1.jsonl`
  (or a new `*_v2.jsonl`). **Every production bug should become a case here.**
- Never copy text from `app/rag/knowledge/response_examples.md` into a case:
  it's in the retrieval index, so the case would leak its answer.
- Bump the dataset version (`_v2`) rather than silently editing labels, so
  scores stay comparable across runs.

## Known limitations / roadmap

1. **Date-dependent answers aren't deterministic yet.** Nothing gives the
   model "today's date", so "am I due for an exam?" depends on what the
   model assumes. Inject a date (overridable via env) into the system
   prompt, then add `due_for_exam` cases.
2. **Model aliases.** `VSP_*_MODEL` default to `-latest` aliases; pin exact
   versions for eval runs you compare, since the summary records whatever ran.
3. **LLM judge layer** using ADK's rubric-based metrics with
   `judge_notes` from each case as the rubric; calibrate on ~100 human labels.
4. **LLM paraphrasing** of golden questions (personas, typos, Spanish,
   multi-intent), with a meaning-preservation filter.
5. **Retrieval eval** for `query_knowledge`: label the relevant chunk per
   question, report recall@k / MRR.
6. **CI**: `pytest evals/tests` on every PR; `run_eval --tags smoke
   adversarial --gate` on PRs touching `app/`; full `--repeats 3` nightly
   with a baseline diff.
7. **Online eval**: sample PII-redacted production turns from Cloud Logging,
   judge them, and promote failures into datasets.
