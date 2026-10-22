---
tags: [aiml, el-project, log-anomaly-detection, runbook, setup]
created: 2026-10-22
updated: 2026-10-22
status: runbook — tested on Windows 11 + Docker Desktop
---

# How to Run

Related: [[16 - Fault Catalogue Explained]] · [[18 - What Does What]] · [[08 - Tech Stack and Repo Structure]]

Step-by-step commands for everything that exists in the repo, from a fresh machine to a live demo. Commands are written for **Git Bash on Windows** (the team's setup); the Linux/macOS differences are noted. Run everything from the repo root (`LogDetecion/`) unless a step says `cd deploy`.

## Table of Contents

- [[#0. What you need|0. What you need]]
- [[#1. One-time setup|1. One-time setup]]
- [[#2. Fastest path — the demo (about 10 minutes)|2. Fastest path — the demo]]
- [[#3. Using the dashboard|3. Using the dashboard]]
- [[#4. Injecting faults by hand|4. Injecting faults by hand]]
- [[#5. Offline benchmarks (HDFS, BGL)|5. Offline benchmarks (HDFS, BGL)]]
- [[#6. Retraining the demo model|6. Retraining the demo model]]
- [[#7. Full live measurement protocol|7. Full live measurement protocol]]
- [[#8. Reports, tables, incidents|8. Reports, tables, incidents]]
- [[#9. Tests|9. Tests]]
- [[#10. Stopping, resetting, cleaning up|10. Stopping, resetting, cleaning up]]
- [[#11. Troubleshooting|11. Troubleshooting]]
- [[#Ports and URLs cheat sheet|Ports and URLs cheat sheet]]

## 0. What you need

| Need | Version used | Check |
|---|---|---|
| Docker Desktop (WSL2 backend) | 28.x, Compose v2 | `docker compose version` |
| Python | 3.11 (3.12 also works for the host scripts) | `py -0` |
| Node.js | 18+ (only for the Word report) | `node --version` |
| RAM / disk | 16 GB recommended / ~10 GB free | |
| Internet | first run only (images, pip, datasets) | |

Docker Desktop must be **running** (whale icon steady) before any `docker` command.

## 1. One-time setup

```bash
# 1. Python environment
py -3.11 -m venv .venv
.venv/Scripts/python -m pip install --upgrade pip
.venv/Scripts/python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m pip install -e .          # makes `import logpulse` work everywhere
# Linux/macOS: python3.11 -m venv .venv && source .venv/bin/activate, then use `python` instead of .venv/Scripts/python

# 2. Datasets (only needed for the offline benchmarks, ~2.5 GB) -> data/raw/
.venv/Scripts/python scripts/download_data.py

# 3. Build and start the demo stack (first build takes a few minutes)
cd deploy
docker compose up -d fluent-bit                       # the log shipper must start first
docker compose --profile deploy build                 # all images incl. payment:v2 for F7
docker compose up -d --build                          # services, db, detector, chaos, dashboard
docker compose --profile deploy create payment-v2     # F7's container: created but stopped
cd ..

# 4. Optional: report tooling and screenshots
cd scripts/report && npm install && cd ../..          # docx-js for the Word report
.venv/Scripts/python -m playwright install chromium   # dashboard screenshots
```

Check that everything is up:

```bash
docker compose -f deploy/docker-compose.yml ps        # 9 containers "running" (payment-v2 "created")
curl -s localhost:9000/api/status                     # "mode":"detect" once a model exists, else "collect"
curl -s -X POST localhost:8000/checkout -H 'content-type: application/json' -d '{"user":1,"item":"pen","qty":1}'
```

> **A trained model is needed for detection.** `artifacts/demo/` (Drain tree, DeepLog, matcher vocabulary, config) is not in git. If it's missing, the detector starts in **collect** mode. Train it with [[#6. Retraining the demo model|section 6]] (about 40 minutes) before running the demo.

## 2. Fastest path — the demo (about 10 minutes)

```bash
.venv/Scripts/python scripts/demo.py            # optional run name: scripts/demo.py my_demo
```

Open these **while it runs**:
- **http://localhost:8501**: Streamlit dashboard (main screen)
- **http://localhost:9000/ui**: React page (animated topology, flow graph, lanes)

What the script does, with timings:

| Time | Step | What to point at on the dashboard |
|---|---|---|
| 0:00 | New run starts, 20 requests/s of normal traffic | Topology all green; log wall scrolling; event chips |
| 1:00 | **F1 slow payment** for 60 s | Payment/orders turn red; alert card; keyword alert also lights (fair) |
| 2:30 | **F3 skip stock step** for 60 s | Inventory goes quiet, all responses 200, keyword and error-rate **dark**, our model lit; alert "expected Calling inventory… observed Calling payment…" |
| 4:00 | **F7 deploy reworded logs** for ~2.5 min | Scoreboard line "vanilla DeepLog N · ours M": vanilla climbs fast, ours stays low; Template library shows "new → matched to E19 (0.86)" |
| 7:00 | Rollback, export, scoring | Terminal prints the table below and writes incident reports |

At the end the terminal prints a summary, for example (run `demo`):

```text
Time to detect per fault (from injector's start timestamp):
detector           B1_keyword B2_error_rate B3_health deeplog_vanilla deeplog_full
F1_payment_latency       3.6s         12.3s    missed           10.1s         4.5s
F3_skip_reserve        missed        missed    missed            2.3s         2.3s

F7 deploy (160s, no real fault): alerts raised
  deeplog_vanilla    1664
  deeplog_full         46
```

Incident reports for the run land in `reports/incidents/<run>__<fault_id>.md`.

**Replaying afterwards.** In the dashboard sidebar, pick the run name under **Run**. Every panel then shows the recorded run instead of live data, so the presentation still works if Docker misbehaves.

## 3. Using the dashboard

http://localhost:8501. Tabs:

| Tab | Panels (note 13 numbering) | Use it for |
|---|---|---|
| **Live** | 1 topology · 8 scoreboard · 2 log wall + event chips · 6 alerts · 3 untangling lanes · 7 fault buttons | The projector view. Refreshes every 2 s (slider in sidebar) |
| **Investigate** | sequence strip · predicted distribution at the bad step · per-step surprise · raw evidence · ground-truth verdict · "mark false alarm" | Drill into one alert (true positives listed first) |
| **Normal flow graph** | 5 | What the model learned; the trace picked in Investigate is overlaid (red dashed = a transition never seen in training) |
| **Template library** | 4 | Every template, its count and status (`known`, `new → matched to E19 (0.86)`, `new-unmatched`) |
| **Incidents** | auto incident reports + run summary | Download each report as `.md` |
| **Benchmarks** | `reports/tables.md` + every figure in `reports/figures/` | Offline results (HDFS/BGL) |

React page http://localhost:9000/ui: buttons **topology** (animated, live), **flow graph** (type a trace id → "show path"), **lanes**.

## 4. Injecting faults by hand

Details of each fault: [[16 - Fault Catalogue Explained]].

```bash
# load in one terminal (Ctrl+C to stop); --duration 0 = forever
.venv/Scripts/python scripts/load.py --rate 20

# start a fault for 60 s (auto-restores), in another terminal
curl -X POST "http://localhost:9100/faults/F3?duration=60"
curl -X POST "http://localhost:9100/faults/F7"              # deploy stays until ended
curl -X POST "http://localhost:9100/faults/F7/end"          # roll back
curl -X POST "http://localhost:9100/restore"                # end everything
curl -s http://localhost:9100/faults                        # catalogue + what's active
```

Or use the buttons in **Live → 7 · Fault control**. To score what you just did, export the run and print its summary:

```bash
curl -X POST localhost:9000/api/admin/export                # copies the live DB to data/demo/runs/<run>.db
.venv/Scripts/python scripts/demo_summary.py <run>          # run name: curl -s localhost:9000/api/status
.venv/Scripts/python scripts/incident_report.py --run <run>
```

Start a fresh, empty run at any time (keeps the model, clears alerts and counters):

```bash
curl -X POST localhost:9000/api/admin/reset -H 'content-type: application/json' -d '{"run":"rehearsal1"}'
```

## 5. Offline benchmarks (HDFS, BGL)

```bash
# parse (once): ~6 min HDFS, ~2 min BGL -> data/processed/{hdfs,bgl}/
.venv/Scripts/python -m logpulse.parsing.drain_parser --dataset hdfs --sim-th 0.5
.venv/Scripts/python -m logpulse.parsing.drain_parser --dataset bgl  --sim-th 0.5

# all experiments in configs/experiments.yaml (E1, E2, E11, E10, E3, E5, E5b, E4, E7, E2b) + figures
.venv/Scripts/python scripts/run_all_experiments.py --nice          # --nice = low CPU priority
.venv/Scripts/python scripts/run_all_experiments.py --only E2 E11   # just some
.venv/Scripts/python scripts/run_all_experiments.py --figures-only  # redraw figures from results.csv
```

Time on a 12-thread laptop: E1 seconds, E2 ~1 h (3 seeds × 7 models × 2 datasets), the rest 10–40 min each. Every number goes to `reports/results.csv`, figures to `reports/figures/`, trained benchmark models to `artifacts/benchmarks/`. Seeds and grids are in `configs/experiments.yaml`; set `seeds_*: [0,1,2,3,4]` for the full 5-seed protocol.

Status today: E1, E2, E10 and E11 are done; E3, E4, E5, E5b, E7 and E2b were stopped to free the machine for the demo. Rerun them with `--only E3 E5 E5b E4 E7 E2b`.

## 6. Retraining the demo model

Needed on a fresh machine, or after changing a service's log messages.

```bash
# 1. record ~30 min of healthy traffic (detector in collect mode)
.venv/Scripts/python scripts/run_live_protocol.py normal --minutes 30

# 2. train: Drain tree (sim_th picked by grouping accuracy), DeepLog, flow graph -> artifacts/demo/
.venv/Scripts/python -m logpulse.online.train_demo --run normal --exclude-error-traces

# 3. load it
docker compose -f deploy/docker-compose.yml restart detector
curl -s localhost:9000/api/status        # "mode":"detect" and the new model version
```

Detector settings live in `artifacts/demo/config.json`:

| Key | Meaning | Current |
|---|---|---|
| `g` | vanilla DeepLog top-g | 9 |
| `p` | our top-p threshold | 0.999 |
| `tau` | matcher similarity threshold | 0.6 |
| `b1_debounce` | keyword alert: max 1 per service per N s | 10 |
| `b2_threshold` | error-rate alert: non-2xx share in 60 s | 0.10 |
| `reorder_delay`, `idle_timeout` | sessionizer: wait 2 s for late lines, close a trace after 5 s idle | defaults |

Edit, then `docker compose -f deploy/docker-compose.yml restart detector`. The values above are hand-set demo settings; the automatic tuner (`python -m logpulse.online.tune_demo --runs tune_s1 tune_s2 --deploy-run tune_deploy`) is pending a fix.

## 7. Full live measurement protocol

Produces the live tables (A, B, D1, D3, E). Long: about 1 h to tune and 1.5 h to test with the reduced defaults; much longer with full-protocol flags. Don't run heavy jobs on the laptop at the same time, because CPU starvation shows up as timeouts.

```bash
.venv/Scripts/python scripts/run_live_protocol.py tune      # tune_s1, tune_s2, tune_deploy
.venv/Scripts/python -m logpulse.online.tune_demo --runs tune_s1 tune_s2 --deploy-run tune_deploy
docker compose -f deploy/docker-compose.yml restart detector
.venv/Scripts/python scripts/run_live_protocol.py test      # test_s4..6, test_faultfree, test_deploy_s7..8
.venv/Scripts/python scripts/score_live.py                  # all live metrics -> results.csv + figures
# full protocol: add --runs-per-fault 3 --duration 150 --gap 180 --test-seeds 4 5 6 7 8 --fault-free-min 120
# skip runs that already exist: --skip tune_s1
```

## 8. Reports, tables, incidents

```bash
.venv/Scripts/python -m logpulse.eval.tables                # reports/tables.md (every table, from results.csv)
.venv/Scripts/python scripts/incident_report.py --all       # reports/incidents/ for every test_* run
.venv/Scripts/python scripts/screenshot_dashboard.py --react                 # reports/figures/fig_dashboard_*.png
.venv/Scripts/python scripts/screenshot_dashboard.py --run demo --tabs Live  # a recorded run
.venv/Scripts/python scripts/make_report.py                 # reports/LogPulse_Report.docx (needs step 8 tables + node)
```

User study kit (Table F): see `scripts/user_study/README.md`.

## 9. Tests

```bash
.venv/Scripts/python -m pytest -q        # 15 tests: parser, sessionizer, scoring rules, DeepLog, matcher
```

## 10. Stopping, resetting, cleaning up

```bash
cd deploy
docker compose stop                     # pause everything, keep data
docker compose start                    # resume (fluent-bit first if containers complain)
docker compose down                     # remove containers (run DBs survive in the "runs" volume)
docker compose down -v                  # also delete the live run volume (exported copies in data/demo/runs stay)
```

Live run databases are written inside Docker (volume `logpulse_runs`) and copied to `data/demo/runs/<run>.db` when a run ends or on `POST /api/admin/export`. Host scripts only read those copies.

## 11. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `docker` commands hang or fail | Docker Desktop not running; start it and wait |
| Containers fail to start, mention fluentd | Start Fluent Bit first: `docker compose up -d fluent-bit` |
| Dashboard red box "API … Connection refused" | Detector still starting (10–20 s) or crashed: `docker compose logs detector --tail 30` |
| `/api/status` says `"mode":"collect"` | No model in `artifacts/demo/`; see [[#6. Retraining the demo model|section 6]] |
| F7 button errors "payment-v2 container missing" | `docker compose --profile deploy create payment-v2` |
| Code change in `src/` not visible | `docker compose restart detector` (src is mounted). Service code (`services/`) needs `docker compose build <svc> && docker compose up -d <svc>` |
| Timeouts / ERROR lines with no fault active | Laptop CPU starved (training or experiments running); stop them or use `--nice` |
| `database disk image is malformed` when reading a live DB from Windows | Read only exported copies in `data/demo/runs/` (call `/api/admin/export` first) |
| A fault seems stuck on | `curl -X POST localhost:9100/restore` |
| Everything weird | `docker compose restart gateway orders inventory payment detector`, then reset a new run |

## Ports and URLs cheat sheet

| Port | What | Useful URLs |
|---|---|---|
| 8000 | gateway (demo app entry) | `POST /checkout`, `GET /health` |
| 8501 | Streamlit dashboard | http://localhost:8501 |
| 9000 | detector: ingest + dashboard API + React page | `/ui`, `/docs`, `/api/status`, `/api/scoreboard`, `/api/alerts`, `/api/traces/<id>`, `/api/templates`, `/api/incidents` |
| 9100 | fault injector | `/docs`, `/faults`, `POST /faults/F3?duration=60`, `POST /restore` |
| 24224 | Fluent Bit forward input (Docker logging driver) | — |
