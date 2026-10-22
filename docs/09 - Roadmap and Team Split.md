---
tags: [aiml, el-project, log-anomaly-detection, roadmap, team]
created: 2026-10-22
updated: 2026-10-22
status: plan — adjust dates to the EL review schedule
---

# Roadmap and Team Split

Related: [[00 - Project Hub]] · [[07 - Evaluation Plan]] · [[08 - Tech Stack and Repo Structure]]

## Table of Contents

- [[#How to read this plan|How to read this plan]]
- [[#MVP definition|MVP definition]]
- [[#10-week plan|10-week plan]]
- [[#Review milestones|Review milestones]]
- [[#Team split|Team split]]
- [[#Weekly rhythm|Weekly rhythm]]
- [[#Risks and fallbacks|Risks and fallbacks]]

## How to read this plan

Starts the week of **26 Oct 2026** and runs 10 weeks to early January 2027. Weeks are milestones, not hard deadlines — once you have the actual EL review dates, slide the weeks so that each review lands right after a milestone with something to show. Assumes ~8–10 hours per person per week alongside other coursework.

## MVP definition

The project is "complete and defensible" when all of these exist:

- [ ] Drain3 parsing of HDFS + BGL with measured grouping accuracy
- [ ] At least LR + RF + PCA baselines and DeepLog on HDFS and BGL, chronological split
- [ ] Random vs chronological comparison (E3)
- [ ] Demo app with trace IDs, Fluent Bit, online detection, F1 + F3 faults detected live on a dashboard
- [ ] Conventional baselines B1–B3 running alongside the model + Table A (E13)
- [ ] Semantic template matcher + post-deploy false-alarm experiment (E10) — the headline contribution
- [ ] Dashboard with topology map, alert drill-down (expected vs observed + raw lines) and scoreboard
- [ ] Report with results tables and figures

Everything else is stretch.

## 10-week plan

**Week 1 (26 Oct – 1 Nov) — Setup + reading**
- [ ] Repo, folder structure, requirements, `.gitignore`, project board
- [ ] Everyone reads: DeepLog, Drain, "How Far Are We?" (ICSE 2022) — 1-page summary each
- [ ] Download Loghub HDFS, BGL, Loghub-2k
- [ ] EDA notebook started

**Week 2 (2 – 8 Nov) — Parsing**
- [ ] `drain3.ini` with masks; parse HDFS-2k / BGL-2k; GA metric; sim_th sweep (E1)
- [ ] Parse full HDFS + BGL → parquet
- [ ] Demo services skeleton: 4 FastAPI apps with JSON logging + trace IDs

**Week 3 (9 – 15 Nov) — Sequences + splits**
- [ ] HDFS sessionization by block ID, labels joined
- [ ] BGL fixed/time windows, labels
- [ ] Chronological + random split utilities; count matrices
- [ ] Docker Compose running all services + Postgres

**Week 4 (16 – 22 Nov) — Classical baselines** → *good point for Review 1*
- [ ] LR, DT, NB, RF, PCA, Isolation Forest on HDFS + BGL
- [ ] `results.csv` + Table 2 v1 + first figures
- [ ] Fluent Bit shipping demo logs to a file

**Week 5 (23 – 29 Nov) — DeepLog**
- [ ] Dataset/windows, model, training loop, batched detection
- [ ] DeepLog on HDFS; compare with baselines
- [ ] Load generator + "normal" demo dataset recorded

**Week 6 (30 Nov – 6 Dec) — DeepLog tuning + E3**
- [ ] DeepLog on BGL; g / h sweeps (E5)
- [ ] Random vs chronological for all models (E3)
- [ ] Fault injector F1–F4 + ground_truth.csv
- [ ] Adaptive top-p decision rule + E11 sweeps (same trained model)
- [ ] Baseline detectors B1 keyword, B2 error-rate, B3 health check

**Week 7 (7 – 13 Dec) — Online pipeline** → *good point for Review 2*
- [ ] `/ingest` API → Drain3 (`match` + learn) → sessionizer → detector → SQLite
- [ ] Train DeepLog on the demo app's normal data
- [ ] First end-to-end live detection of F1
- [ ] Step-wise online scoring; store per-step decisions (top-5 probs) for traceability
- [ ] Semantic template matcher + `payment:v2` reworded-log image (F7)

**Week 8 (14 – 20 Dec) — Dashboard + live evaluation**
- [ ] Dashboard panels from [[13 - Demo Visualization and Traceability]]: topology map, log wall + chips, untangling view, alert drill-down, fault buttons, scoreboard
- [ ] Run the full measurement protocol from [[14 - Metrics and Baselines#Measurement protocol|Metrics and Baselines]] (10 runs per fault, tuning seeds vs test seeds) → Tables A, B, D1–D3
- [ ] E10 matcher experiment on F7 deploy + BGL; ablation (E14)
- [ ] Incident report generator

**Week 9 (21 – 27 Dec) — Stretch or polish**
- [ ] Time-to-root-cause user study with 6–10 classmates (Table F)
- [ ] React Flow version of topology map + normal flow graph (if a teammate owns frontend)
- [ ] Pick one: K8s + Chaos Mesh/LitmusChaos · Kafka · LogAnomaly/LSTM-AE · Online Boutique generalisation
- [ ] Freeze all experiments; regenerate every table from one script

**Week 10 (28 Dec – 3 Jan) — Report + demo**
- [ ] Report chapters (use [[11 - Report and Synopsis Content]])
- [ ] Rehearse demo twice end to end; record a backup video
- [ ] README with results + GIF; tag `v1.0`
- [ ] Optional: convert to a short paper (IEEE conference format)

## Review milestones

| Review | Show | Evidence |
|---|---|---|
| Synopsis | Problem, objectives, literature, methodology | [[11 - Report and Synopsis Content]] |
| Review 1 (≈ week 4) | Parsing works, baselines table, demo services running | GA table, Table 2 v1, `docker compose ps` |
| Review 2 (≈ week 7) | DeepLog results, E3 finding, first live detection | Tables 2–3, short live run |
| Final | Full live demo + all results | [[12 - Demo and Viva Prep]] |

## Team split

Written for 4 people; for 3, merge C and D; for 2, A takes A+C and B takes B+D.

| Person | Track | Owns | Also must understand |
|---|---|---|---|
| **A — Parsing & data** | Offline | Drain3 config, GA metric, sessionization, windows, splits, EDA figures | How DeepLog consumes sequences |
| **B — Models & evaluation** | Offline | Baselines, DeepLog, top-p rule, semantic matcher, all experiments, results tables | Why Drain's threshold matters |
| **C — Microservices & chaos** | Live | 4 services, trace IDs, Compose, Fluent Bit, load generator, fault injector, `payment:v2` deploy image, ground truth, conventional baselines B1–B3 | What a session is for the model |
| **D — Online pipeline & UI** | Live | Ingest API, online sessionizer, step-wise detector, store, dashboard panels, scorer, incident reports | How metrics are computed |

Rule from the SentinelDB plan applies here too: every teammate must be able to explain every part. Do one "teach-back" session at weeks 4 and 8 where each person explains another person's component.

## Weekly rhythm

- One 30-min sync per week: what's done, what's blocked, what's next — update the board.
- Every PR has a short description + how to test.
- Every Friday: append new numbers to `results.csv` and drop one figure into `reports/figures/`. The report then writes itself.

## Risks and fallbacks

| Risk | Fallback |
|---|---|
| HDFS too big for someone's laptop | Process in chunks; share parsed parquet via Drive; use Colab |
| DeepLog underperforms baselines on HDFS | That's a legitimate finding (HDFS is easy for count models) — emphasise BGL + ordering faults (F3) |
| Fluent Bit setup eats days | Write logs to a shared volume file and tail it from Python; add Fluent Bit later |
| Live labels noisy | Hand-check 100 traces; report label-check accuracy |
| Docker on Windows painful | WSL2; or run services directly with uvicorn for the demo |
| Guide rejects LSTM as off-syllabus | Classical models + PCA + K-means become the core; DeepLog becomes "future work" demo |
| Time crunch near exams | MVP list above is the line — cut stretch, never cut evaluation |
