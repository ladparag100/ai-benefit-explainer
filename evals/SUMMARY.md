# Evals: what's been built so far

_Last updated 2026-10-12. For how to run it, see [README.md](README.md)._

## Added

- **Synthetic data** (`generators/synthetic_data.py` → `fixtures/`)
  - 6 demo members + 24 generated members, from a fixed seed (same data every run).
  - Covers every combination the agents branch on: plan, dependents, contacts already used, claim status, individual vs employer plan.
- **Golden test set** (`generators/golden_cases.py` → `datasets/golden_v1.jsonl`)
  - 143 cases across 24 question types (benefits, dependents, ID cards, find a doctor, claims, billing, escalation, off-topic, multi-turn).
  - Expected answers are computed from the data; nothing is labelled by hand.
- **Adversarial test set** (`datasets/adversarial_v1.jsonl`)
  - 14 hand-written cases: prompt injection, cross-member data requests, a typed SSN, medical questions, escalations.
- **Harness** (`harness/runner.py`)
  - Runs each case through the real supervisor agent, set up the same way as the Streamlit app.
  - A recorder plugin captures every tool call, including the ones inside specialists, plus token counts.
- **Scorers** (`scorers/`)
  - Six code-based checks, no LLM: routing, tool calls, facts, outcome, reply format, leakage.
- **CLI** (`run_eval.py`)
  - Filter cases by tag or ID; repeat runs.
  - Writes a report (`reports/<timestamp>/`).
  - Can fail the run against minimum pass rates in `thresholds.json`.
  - Can re-score a saved run without calling the model.
- **LangSmith export** (`exporters/langsmith_export.py`, `run_eval.py --export langsmith`)
  - Uploads every case to the dataset `ai-benefit-explainer-evals`, and each run as an experiment.
  - Each experiment has per-check scores and nested tool-call traces.
- **Tests** (`tests/`): 27 offline tests for the generators and scorers.
- **App change**: `app/config.py` now honours `VSP_DATA_DIR`, so evals can run against the synthetic data.

## Status

- Live test of 6 cases against the real agent: all passed, and inner tool calls were captured correctly.
- First real baseline (2026-10-09): 38-case run (smoke + adversarial) on `gemini-flash-lite-latest`.
  - 97.4% pass after a scorer fix; leakage, facts and tool calls at 100%.
  - Uploaded to LangSmith.
  - Export saved at `results/d795ee1-gemini-flash-lite-latest-dae82385.csv`.
  - The export was taken before the scorer fix, so it shows 36/38.
- One real agent bug found: for a medical-necessity question, the supervisor called `benefits_agent` **and** `escalation_agent` in the same turn (breaks the one-specialist-per-turn rule).

## LangSmith results

Links open in LangSmith for anyone with access to the workspace. No download needed.

- **Dataset (all cases and every experiment):** [ai-benefit-explainer-evals](https://smith.langchain.com/o/28826077-32cb-4cee-ba7e-9c5c9e60926c/datasets/1832935e-3239-4e46-a742-180cf7115d9a)

| Date | Experiment | Cases | Pass | Notes |
|---|---|---|---|---|
| 2026-10-09 | [d795ee1-gemini-flash-lite-latest-dae82385](https://smith.langchain.com/o/28826077-32cb-4cee-ba7e-9c5c9e60926c/datasets/1832935e-3239-4e46-a742-180cf7115d9a/compare?selectedSessions=c8430346-fd7b-4849-864b-34a1a49770f2) | 38 (smoke + adversarial) | 36/38 in LangSmith; 37/38 after scorer fix | Baseline. Supervisor `gemini-flash-lite-latest`, specialists `gemini-flash-latest`. CSV: `results/d795ee1-gemini-flash-lite-latest-dae82385.csv` |

What the baseline showed:

| Check | Pass rate |
|---|---|
| leakage | 100% (38/38) |
| facts | 100% |
| trajectory | 100% |
| format | 100% |
| routing | 96.8%: `medical.necessity_judgment` routed to two specialists |
| outcome | 96.4% in LangSmith; 100% after the clarify-check fix |

Add a row to this table for each new run. The exporter prints the experiment link at the end of each upload.

## Not done yet

- Making date-based answers deterministic (pass today's date into the system prompt).
- Pinned model versions for comparable runs.
- LLM-judge scoring (ADK rubric metrics, using each case's `judge_notes`).
- LLM paraphrasing of the test questions.
- Evaluating the knowledge-base search (RAG).
- CI wiring.
- Scoring live production traffic.
