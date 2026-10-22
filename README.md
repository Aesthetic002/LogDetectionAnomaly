# LogPulse — log anomaly detection for microservices

A pipeline that reads raw logs from running microservices, turns each line into an event template
(Drain3), groups events per request (trace ID — the microservice equivalent of HDFS's block ID), and
flags request flows that look abnormal, using classical ML baselines and a DeepLog-style LSTM. It is
evaluated honestly on HDFS and BGL (chronological split), then run live on a four-service demo app with
injected faults, side by side with keyword, error-rate and health-check alerting.

On top of vanilla DeepLog it adds three improvements, each measured against the conventional approach:
a **semantic template matcher** for reworded logs after a deploy, an **adaptive top-p** decision rule, and
**step-wise online scoring**.

Design notes (the spec this repo implements) are in [docs/](docs/00%20-%20Project%20Hub.md). Start with:

- [docs/17 — How to Run](docs/17%20-%20How%20to%20Run.md): setup, the 10-minute demo (`python scripts/demo.py`), troubleshooting
- [docs/16 — Fault Catalogue Explained](docs/16%20-%20Fault%20Catalogue%20Explained.md): what F1–F7 are and who catches each
- [docs/18 — What Does What](docs/18%20-%20What%20Does%20What.md): containers, data flow, every file
- [docs/19 — Demo Run Output Explained](docs/19%20-%20Demo%20Run%20Output%20Explained.md): what the demo's terminal output means

<!-- RESULTS -->

## Quick start (Windows / Linux / macOS)

```bash
py -3.11 -m venv .venv && .venv/Scripts/activate        # source .venv/bin/activate on Linux/macOS
pip install -r requirements.txt && pip install -e .
python scripts/download_data.py                          # HDFS_v1, BGL, Loghub-2k (~2.5 GB) -> data/raw
```

### Offline benchmarks (Tables 1–3, D1–D2, figures)

```bash
python -m logpulse.parsing.drain_parser --dataset hdfs --sim-th 0.5    # ~6 min
python -m logpulse.parsing.drain_parser --dataset bgl  --sim-th 0.5    # ~2 min
python scripts/run_all_experiments.py --config configs/experiments.yaml
```

### Live demo stack

```bash
cd deploy
docker compose up -d fluent-bit
docker compose --profile deploy build          # includes the payment:v2 "bad deploy" image
docker compose up -d --build
docker compose --profile deploy create payment-v2
```

| URL | What |
|---|---|
| http://localhost:8501 | Streamlit dashboard (live, investigate, flow graph, templates, incidents, benchmarks) |
| http://localhost:9000/ui | React Flow page — animated topology, flow graph with trace overlay, lanes |
| http://localhost:9000/docs | Detector API (ingest + dashboard API) |
| http://localhost:9100/docs | Fault injector API |
| http://localhost:8000/checkout | Demo app entry point |

### Train, tune and measure (the live protocol)

```bash
python scripts/run_live_protocol.py normal --minutes 30     # healthy traffic, collect mode
python -m logpulse.online.train_demo --run normal           # Drain tree, DeepLog, flow graph -> artifacts/demo
docker compose -f deploy/docker-compose.yml restart detector
python scripts/run_live_protocol.py tune                    # tuning seeds 1-2 + deploy tuning run
python -m logpulse.online.tune_demo --runs tune_s1 tune_s2 --deploy-run tune_deploy
docker compose -f deploy/docker-compose.yml restart detector
python scripts/run_live_protocol.py test                    # test seeds 4-6, fault-free block, deploy seeds 7-8
python scripts/score_live.py && python -m logpulse.eval.tables && python scripts/incident_report.py --all
python scripts/make_report.py                               # reports/LogPulse_Report.docx
```

`make` targets wrap the same steps (`make data parse results demo normal train-demo tune test score report`).

**Full protocol.** The defaults are a reduced protocol (see below). For the protocol in
[docs/14](docs/14%20-%20Metrics%20and%20Baselines.md): `run_live_protocol.py tune|test --runs-per-fault 3
--duration 150 --gap 180 --test-seeds 4 5 6 7 8 --fault-free-min 120 --deploy-min 30 …` and
`seeds_classical/seeds_deeplog: [0,1,2,3,4]` in `configs/experiments.yaml`.

## Demo script (≈9 min)

1. Topology all green under load → 2. log wall → event chips → 3. untangling lanes →
4. normal flow graph → 5. **F1 Slow payment**: payment turns red, alert card with expected vs observed,
keyword alert also fires → 6. **F3 Skip stock step**: no ERROR anywhere, keyword and error-rate stay dark,
our model fires; Investigate shows a road that does not exist on the flow graph → 7. **F7 Deploy reworded
logs**: vanilla DeepLog's counter climbs, ours stays calm, template library shows "new → matched" →
8. Incidents tab → 9. Benchmarks tab. Viva answers: [docs/12](docs/12%20-%20Demo%20and%20Viva%20Prep.md).

## Repository

```text
src/logpulse/
  parsing/drain_parser.py     Drain3 (masks, honest fit-on-train parse, GA metric)
  features/                   sessions (block / trace), BGL windows, count matrices
  models/                     baselines.py, deeplog.py (top-g / top-p / surprise), template_matcher.py
  eval/                       splits, metrics, experiments (E1-E11), live scoring, tables, figures, incidents
  online/                     ingest_api (FastAPI), parser, sessionizer, detector bank, train/tune/replay
  store.py                    SQLite schema (raw line -> event -> decision -> alert -> ground truth)
services/                     gateway, orders, inventory, payment (+ common JSON logging / trace IDs)
deploy/                       docker-compose.yml, fluent-bit.conf, Dockerfiles
chaos/                        inject.py (fault API + ground truth), schedule.py (seeded schedules)
dashboard/                    app.py (Streamlit), react/index.html (React Flow)
scripts/                      download, experiments, live protocol, scoring, report, user study kit
reports/                      results.csv (every number), tables.md, figures/, incidents/, LogPulse_Report.docx
tests/                        parser, sessionizer / scoring, DeepLog / matcher
```

Conventions: event id 0 = PAD, 1 = UNSEEN, templates from 2; timestamps UTC; thresholds chosen on
validation / tuning runs only; every reported number is a row in `reports/results.csv`.

## Notes on running on Windows

- Docker Desktop's fluentd logging driver reaches Fluent Bit on `localhost:24224` (`fluentd-async` lets
  containers start before Fluent Bit).
- Live run databases are written to a Docker named volume (SQLite WAL is not coherent across the Docker
  Desktop VM ↔ Windows bind mount) and exported to `data/demo/runs/` when a run ends
  (`POST /api/admin/export` does it on demand).
- PyTorch is pinned to 2 threads: the small LSTM trains fastest that way on CPU.
