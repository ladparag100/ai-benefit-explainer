# Evals: what's been built so far

_Last updated 2026-10-12. For how to run it, see [README.md](README.md)._

## At a glance

| | |
|---|---|
| ✅ **Overall pass rate** | **97.4%** (37/38 cases) |
| 🔒 **Data leaks** | **0** (incl. prompt-injection and cross-member attacks) |
| 🐞 **Agent bugs found** | **1** (multi-agent routing defect) |
| ⏱️ **Latency p50 / p95** | **9.9s / 26.8s** per conversation |

> Pass rates are from the 38-case run (smoke + adversarial, 2026-10-09, after the scorer fix), not all 157 cases.
> Run the full suite to update them: `python -m evals.run_eval --export langsmith`

## Baseline quality

| Check | Pass rate | | Notes |
|-------|----------:|---|-------|
| Factual accuracy | 100% | `██████████` | |
| Data leakage | 100% | `██████████` | 0 leaks out of 38 |
| Tool use | 100% | `██████████` | |
| Outcome | 100% | `██████████` | answer / escalate / clarify / refuse |
| Reply format | 100% | `██████████` | |
| Routing | 96.8% | `█████████▋` | `medical.necessity_judgment` routed to two specialists |
| **Overall** | **97.4%** | `█████████▋` | **37/38** |

## Baseline performance

| Metric | Value |
|--------|-------|
| Latency p50 | 9.9s per conversation |
| Latency p95 | 26.8s per conversation |
| Model calls per query | ~4.7 |
| Input tokens per case (avg) | ~8.2k |
| Output tokens per case (avg) | ~360 |
| Run errors | 0 |

## Scale of the eval suite

| What | Count | Details |
|------|------:|---------|
| Agents under test | 7 | supervisor + 6 specialists (Google ADK + Gemini) |
| Synthetic members | 30 | 6 demo + 24 generated, fixed seed |
| Test cases | 157 | 143 generated golden + 14 hand-written adversarial |
| Intents covered | 24 | |
| Scored dimensions | 6 | routing, tool use, facts, outcome, format, data leakage |
| Unit tests for the eval code | 27 | |
| Hand-labelled answers | 0 | expected answers are computed from the data |

## What's been built

| Component | Where | What it does |
|-----------|-------|--------------|
| Synthetic data | `generators/synthetic_data.py` → `fixtures/` | 6 demo + 24 generated members from a fixed seed (same data every run). Covers every combination the agents branch on: plan, dependents, contacts already used, claim status, individual vs employer plan. |
| Golden test set | `generators/golden_cases.py` → `datasets/golden_v1.jsonl` | 143 cases across 24 question types (benefits, dependents, ID cards, find a doctor, claims, billing, escalation, off-topic, multi-turn). Expected answers computed from the data. |
| Adversarial test set | `datasets/adversarial_v1.jsonl` | 14 hand-written cases: prompt injection, cross-member data requests, a typed SSN, medical questions, escalations. |
| Harness | `harness/runner.py` | Runs each case through the real supervisor agent, set up like the Streamlit app. A recorder plugin captures every tool call (including inside specialists) plus token counts. |
| Scorers | `scorers/` | Six code-based checks, no LLM: routing, tool calls, facts, outcome, reply format, leakage. |
| CLI | `run_eval.py` | Filter by tag or ID, repeat runs, write a report to `reports/<timestamp>/`, fail against `thresholds.json`, re-score a saved run without calling the model. |
| LangSmith export | `exporters/langsmith_export.py` (`--export langsmith`) | Uploads every case to the dataset `ai-benefit-explainer-evals` and each run as an experiment, with per-check scores and nested tool-call traces. |
| Tests | `tests/` | 27 offline tests for the generators and scorers. |
| App change | `app/config.py` | Now honours `VSP_DATA_DIR`, so evals can run against the synthetic data. |

## Status

| | Item | Result |
|---|------|--------|
| ✅ | Live test, 6 cases against the real agent | All passed; inner tool calls captured correctly |
| ✅ | First baseline (2026-10-09), 38 cases on `gemini-flash-lite-latest` | 97.4% pass after scorer fix; leakage, facts and tool calls at 100%; uploaded to LangSmith |
| ⚠️ | CSV export `results/d795ee1-gemini-flash-lite-latest-dae82385.csv` | Taken before the scorer fix, so it shows 36/38 |
| 🐞 | Agent bug | For a medical-necessity question, the supervisor called `benefits_agent` **and** `escalation_agent` in the same turn (breaks the one-specialist-per-turn rule) |

## LangSmith results

Links open in LangSmith for anyone with access to the workspace. No download needed.

**Dataset (all cases and every experiment):** [ai-benefit-explainer-evals](https://smith.langchain.com/o/28826077-32cb-4cee-ba7e-9c5c9e60926c/datasets/1832935e-3239-4e46-a742-180cf7115d9a)

| Date | Experiment | Cases | Pass | Notes |
|------|------------|-------|------|-------|
| 2026-10-09 | [d795ee1-gemini-flash-lite-latest-dae82385](https://smith.langchain.com/o/28826077-32cb-4cee-ba7e-9c5c9e60926c/datasets/1832935e-3239-4e46-a742-180cf7115d9a/compare?selectedSessions=c8430346-fd7b-4849-864b-34a1a49770f2) | 38 (smoke + adversarial) | 36/38 in LangSmith; 37/38 after scorer fix | Baseline. Supervisor `gemini-flash-lite-latest`, specialists `gemini-flash-latest`. CSV: `results/d795ee1-gemini-flash-lite-latest-dae82385.csv` |

Add a row for each new run. The exporter prints the experiment link at the end of each upload.

Per-check results for the baseline, as LangSmith shows them:

| Check | In LangSmith | After scorer fix | |
|-------|-------------:|-----------------:|---|
| leakage | 100% (38/38) | 100% | `██████████` |
| facts | 100% | 100% | `██████████` |
| trajectory | 100% | 100% | `██████████` |
| format | 100% | 100% | `██████████` |
| routing | 96.8% | 96.8% | `█████████▋` |
| outcome | 96.4% | 100% (clarify-check fix) | `█████████▋` → `██████████` |

## Not done yet

| Area | Next step |
|------|-----------|
| Determinism | Pass today's date into the system prompt so date-based answers are stable |
| Reproducibility | Pin model versions for comparable runs |
| Scoring | LLM-judge scoring (ADK rubric metrics, using each case's `judge_notes`) |
| Test data | LLM paraphrasing of the test questions |
| Coverage | Evaluate the knowledge-base search (RAG) |
| Automation | CI wiring |
| Production | Score live production traffic |
