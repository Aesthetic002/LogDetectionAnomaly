---
tags: [aiml, el-project, log-anomaly-detection, metrics, baselines, results]
created: 2026-10-22
updated: 2026-10-22
status: plan — numbers to be filled from experiments
---

# Metrics and Baselines

Related: [[00 - Project Hub]] · [[07 - Evaluation Plan]] · [[15 - Our Improvements]] · [[13 - Demo Visualization and Traceability]]

Results matter. This note defines **what we compare against** (the "before"), **which numbers should move** (the "after"), and **how to measure them so they hold up** in a review or viva.

## Table of Contents

- [[#The comparison story|The comparison story]]
- [[#Baselines — what conventional monitoring does|Baselines — what conventional monitoring does]]
- [[#Headline metrics|Headline metrics]]
- [[#Supporting metrics|Supporting metrics]]
- [[#Metric definitions and formulas|Metric definitions and formulas]]
- [[#Measurement protocol|Measurement protocol]]
- [[#Result tables to fill|Result tables to fill]]
- [[#How to present the numbers|How to present the numbers]]
- [[#Credibility rules|Credibility rules]]
- [[#Expected outcome — hypotheses, not claims|Expected outcome — hypotheses, not claims]]

## The comparison story

Three levels of comparison, each answering a different judge question:

| Level | Our method vs | Question it answers | Where |
|---|---|---|---|
| 1 | Conventional monitoring (keyword, error-rate threshold, health check) | "Is ML even needed?" | Live demo app |
| 2 | Standard ML / DL models (LR, DT, NB, RF, PCA, IsoForest, vanilla DeepLog) | "Is your model better than known methods?" | HDFS, BGL, demo app |
| 3 | Vanilla DeepLog vs **our improved DeepLog** | "What did *you* contribute?" | HDFS, BGL, demo app (deploy fault F7) |

Level 3 is the project's own contribution — details in [[15 - Our Improvements]].

## Baselines — what conventional monitoring does

Implement all three as small detectors that read the same log stream / request outcomes as our model and write to `baseline_alerts`.

**B1 — Keyword alerting**
- Alert when a log line matches `ERROR|Exception|Traceback|timeout|failed` (case-insensitive).
- Debounce: at most one alert per service per 10 s (otherwise it's unfairly noisy).
- What it represents: `grep`-style alerts most small teams use.

**B2 — Error-rate threshold**
- From gateway response logs: alert when the share of non-2xx responses in a sliding 60 s window exceeds 5% (with at least 20 requests in the window).
- What it represents: the standard Prometheus/Grafana alert rule.

**B3 — Health check**
- Gateway (or a separate prober) calls `/health` on every service every 10 s; alert after 3 consecutive failures.
- What it represents: Docker/Kubernetes liveness probes.

Make each baseline as **good as reasonably possible** — tune its window/threshold on validation runs, same as our model. Beating a deliberately weak baseline proves nothing.

## Headline metrics

The four numbers for the opening results slide:

| # | Metric | Direction | Compared against | Why it matters |
|---|---|---|---|---|
| H1 | **Fault detection rate** (% of injected faults caught) — overall and **silent faults only** | ↑ | B1, B2, B3 | Silent faults (F3 skipped step, F4 retry storm) print no ERROR — conventional alerts barely catch them |
| H2 | **Mean time to detect (MTTD)** | ↓ | B1, B2, B3 | Step-wise scoring fires at the first odd event; a 60 s threshold window has to fill up first |
| H3 | **False alarms per hour** on fault-free traffic — and **after a deployment** | ↓ (or no worse) | B1, B2, vanilla DeepLog | Proves we didn't just make it trigger-happy; the post-deploy number is our own improvement |
| H4 | **Lines a human must read per incident** | ↓ | Raw logs in the fault window | Turns "it's smarter" into a tangible effort reduction |

## Supporting metrics

| Metric | Direction | Purpose |
|---|---|---|
| Precision / Recall / F1 (HDFS, BGL, demo app) | ↑ | Standard benchmark comparison with published methods |
| PR-AUC | ↑ | Threshold-free view under heavy class imbalance |
| F1 gap random vs chronological split | report | Shows evaluation honesty (see [[07 - Evaluation Plan]]) |
| Anomaly labels required to train | ↓ | DeepLog: 0 anomaly labels; supervised models: thousands |
| Parsing grouping accuracy before/after tuning | ↑ | Our improvement to the parsing stage (masks + sim_th) |
| Log compression ratio (lines → templates) | report | What parsing buys |
| Time to root cause (user study) | ↓ | Human-centred benefit of the explainable alert view |
| Throughput (lines/s), CPU %, RAM, added latency | report | Proves it can run continuously and cheaply |
| Detection rate per fault type | ↑ | Shows where the model helps and where baselines are enough |

## Metric definitions and formulas

**Fault-level detection** (live demo):
- A fault *run* `f` with window `[s_f, e_f]` is **detected** by a method if that method raises ≥ 1 alert that maps to `f` within `[s_f, e_f + grace]` (grace = 30 s).
- An alert **maps to** `f` if it falls in that window *and* concerns the target service or a trace that touched it.
- `Detection rate = detected fault runs / total fault runs`.

**Mean time to detect:**
- `TTD_f = (time of first mapped alert) − s_f`; only for detected runs.
- Report **median and IQR**, not just mean (latency is skewed). Undetected runs are listed separately, never averaged in as zero.

**False alarms per hour:**
- Alerts that map to no fault, during fault-free periods, divided by fault-free hours.
- Report two numbers: steady state, and the first 30 min after a deploy (F7).

**Lines to read:**
- `raw_lines_in_window` = all raw lines from all services during `[s_f, e_f]`.
- `lines_attached` = raw lines linked to the first alert (the offending trace's lines).
- Report the ratio and the absolute pair, e.g. "38,904 → 6".

**Session-level P / R / F1** (benchmarks + demo app):
- Positive = anomalous session; standard definitions; anomalous sessions in demo app labelled by the ground-truth rule in [[03 - Datasets#Our own demo-app dataset|Datasets]].

**Time to root cause (user study):**
- 6–10 participants (classmates), 3 incidents each, randomised order.
- Condition A: raw logs + terminal (`grep`, `less`). Condition B: our alert drill-down.
- Task: name the faulty service and the failing step. Record time and correctness. Each participant does some incidents in A and some in B (within-subject), so individual skill cancels out.

## Measurement protocol

1. **Warm-up:** 10 min normal traffic after `docker compose up` (templates stabilise).
2. **Fault schedule:** each fault type × **10 runs**, random start times, random order, 2–3 min each, ≥ 3 min normal traffic between faults. Generated by `chaos/schedule.py --seed N`.
3. **Fault-free blocks:** at least 2 h total for false-alarm rates.
4. **Deploy block (F7):** swap in the reworded-log image for one service, run 30 min with some real faults mixed in.
5. **All detectors run simultaneously** on the same stream: B1, B2, B3, RF baseline, vanilla DeepLog, improved DeepLog.
6. **Separate tuning and test runs:** tune thresholds on schedule seeds 1–3; report on seeds 4–8. Never tune on reported runs.
7. **Everything logged automatically**; `scripts/score_live.py` recomputes all metrics from the store.

## Result tables to fill

**Table A — Conventional monitoring vs our model (live demo, test seeds)**

| Fault | Visible error? | B1 keyword | B2 error-rate | B3 health | RF | DeepLog (ours) |
|---|---|---|---|---|---|---|
| F1 payment slow | yes | det % / TTD | | | | |
| F2 payment down | yes | | | | | |
| F3 stock step skipped | **no** | | | | | |
| F4 retry storm | partly | | | | | |
| F5 DB exhaustion | yes | | | | | |
| F6 inventory paused | partly | | | | | |
| **All faults** | | | | | | |
| **Silent faults (F3, F4)** | | | | | | |
| False alarms / h (steady) | | | | | | |

**Table B — Headline metric cards**

| Metric | Best conventional | Ours | Change |
|---|---|---|---|
| Fault detection rate (all) | | | |
| Fault detection rate (silent) | | | |
| Median time to detect | | | |
| False alarms / h after deploy | (vanilla DeepLog) | (improved) | |
| Lines to read per incident | (raw window) | (alert) | |

**Table C — Benchmarks** → Tables 2–3 in [[07 - Evaluation Plan#Results table templates|Evaluation Plan]].

**Table D — Our improvements** → [[15 - Our Improvements#Result tables|Our Improvements]].

**Table E — Overhead**

| Component | Lines/s | CPU % | RAM MB | Added latency per request |
|---|---|---|---|---|

**Table F — User study**

| Condition | Median time to root cause | Correct answers |
|---|---|---|
| Raw logs + grep | | |
| Our alert view | | |

## How to present the numbers

- **Slide 1 of results: four metric cards** (H1–H4), each as "baseline → ours", with the comparison named under it.
- **Table A as a heatmap** — rows = faults, columns = methods, cell colour = detection rate; the silent-fault rows make the story obvious.
- **TTD timeline per fault type** — fault start at 0, a marker per method's median first alert, IQR whiskers.
- **Deploy chart** — alerts/min over time around the F7 deploy, vanilla vs improved DeepLog as two lines.
- **Benchmark bar chart** — F1 per model on HDFS and BGL (chronological).
- **"Where we lose" box** — e.g. if B3 health check detects "payment down" faster, say so. One admitted limitation makes every other number more believable.

## Credibility rules

- Pre-register: write the metric list, thresholds-to-tune and test seeds in this note **before** final runs.
- Same stream, same time, all detectors — no cherry-picked runs.
- Median + IQR across ≥ 10 runs per fault; mean ± std across 5 seeds for benchmarks.
- Tune on validation only; test touched once.
- Every number traces to `reports/results.csv` and can be regenerated by one script.
- Report failures and non-improvements too.
- Placeholder numbers in notes/slides are never left in final material.

## Expected outcome — hypotheses, not claims

What we *expect* and will test (do not write these as achieved results anywhere until measured):

- H1: on error-visible faults, B1/B2 detect most runs too; on silent faults (F3), B1/B2/B3 detect few or none, while the sequence model detects most.
- H2: our MTTD is a few seconds vs tens of seconds for B2 (window-bound); B1 can be as fast as us on error-visible faults.
- H3: vanilla DeepLog's false-alarm rate spikes after F7; the semantic matcher reduces it substantially without a large recall loss.
- H4: lines to read drops by orders of magnitude (tens of thousands → tens).
- Benchmarks: classical supervised models are very strong on HDFS; DeepLog's advantage, if any, appears on BGL and on ordering anomalies.
