---
tags: [aiml, el-project, log-anomaly-detection, tech-stack, repo]
created: 2026-10-22
updated: 2026-10-22
status: reference
---

# Tech Stack and Repo Structure

Related: [[00 - Project Hub]] · [[02 - System Architecture]] · [[09 - Roadmap and Team Split]]

## Table of Contents

- [[#Software requirements|Software requirements]]
- [[#Hardware requirements|Hardware requirements]]
- [[#Python dependencies|Python dependencies]]
- [[#Repo layout|Repo layout]]
- [[#Conventions|Conventions]]
- [[#Setup commands|Setup commands]]
- [[#Git workflow for the team|Git workflow for the team]]

## Software requirements

| Layer | Tool | Version (pin) | Used for |
|---|---|---|---|
| Language | Python | 3.11 | Everything ML + services |
| Parsing | drain3 | latest 0.9.x | Log templates |
| Data | pandas, numpy, pyarrow, scipy | — | Tables, sparse count matrices, parquet |
| Classical ML | scikit-learn | 1.5+ | LR, DT, NB, RF, PCA, IsolationForest, metrics |
| Deep learning | PyTorch | 2.x (CPU build is fine) | DeepLog |
| Services | FastAPI, uvicorn, httpx | — | Demo microservices + ingest API |
| Containers | Docker Desktop + Compose v2 | — | Running the demo stack |
| Log shipping | Fluent Bit | 3.x image | Collecting container logs |
| Storage | SQLite → PostgreSQL 16 | — | Events, sessions, alerts |
| Dashboard | Streamlit + Plotly | — | Live UI |
| Load | Locust or plain httpx script | — | Traffic |
| Chaos | docker CLI, Toxiproxy (optional) | — | Faults |
| Notebooks | JupyterLab / VS Code | — | EDA, experiments |
| Tracking (optional) | MLflow or just `results.csv` | — | Experiment log |
| Stretch | kind/minikube, Helm, Chaos Mesh/LitmusChaos, Kafka/Redpanda, Prometheus, Grafana | — | K8s + streaming upgrades |

On Windows: use **WSL2** for the Python environment and Docker Desktop with the WSL2 backend — Fluent Bit, bash scripts and file paths behave much better.

## Hardware requirements

- 8 GB RAM minimum, 16 GB comfortable (HDFS parsing + Docker stack together).
- ~10 GB free disk (raw HDFS ~1.5 GB, BGL ~0.7 GB, processed copies, Docker images).
- No GPU needed; DeepLog is small. Google Colab (free GPU) if training feels slow.

## Python dependencies

`requirements.txt`:

```text
drain3
pandas
numpy
pyarrow
scipy
scikit-learn
torch
matplotlib
seaborn
plotly
fastapi
uvicorn[standard]
httpx
pydantic
streamlit
sqlalchemy
pyyaml
tqdm
pytest
```

Pin exact versions with `pip freeze > requirements.lock` once things work.

## Repo layout

```text
logpulse/
├── README.md                  # what it is, how to run, results summary
├── requirements.txt
├── Makefile                   # make data | parse | train | results | demo
├── configs/
│   ├── drain3.ini
│   ├── exp_E2_hdfs.yaml
│   └── deeplog.yaml
├── data/                      # gitignored
│   ├── raw/                   # HDFS.log, BGL.log, loghub-2k/
│   ├── processed/             # structured.parquet, templates.csv, sessions.parquet
│   └── demo/                  # captured demo-app logs + ground_truth.csv
├── notebooks/
│   ├── 01_eda.ipynb
│   ├── 02_parsing.ipynb
│   ├── 03_baselines.ipynb
│   └── 04_deeplog.ipynb
├── src/logpulse/
│   ├── parsing/drain_parser.py
│   ├── features/sessionize.py     # HDFS block / trace_id sessions
│   ├── features/windows.py        # BGL fixed + time windows
│   ├── features/vectorize.py      # count / tf-idf matrices
│   ├── models/baselines.py
│   ├── models/deeplog.py
│   ├── eval/splits.py             # chronological / random
│   ├── eval/metrics.py
│   ├── online/ingest_api.py       # FastAPI /ingest
│   ├── online/sessionizer.py      # live trace buffering
│   ├── online/detector.py         # loads model, scores sessions
│   └── store.py                   # SQLite/Postgres access
├── services/                  # demo microservices
│   ├── gateway/ orders/ inventory/ payment/   (each: app.py, Dockerfile)
│   └── common/logging_setup.py    # JSON formatter + trace-id filter
├── deploy/
│   ├── docker-compose.yml
│   ├── fluent-bit.conf
│   └── k8s/                   # stretch
├── chaos/
│   ├── inject.py
│   └── ground_truth.csv
├── dashboard/app.py           # Streamlit
├── scripts/
│   ├── download_data.sh
│   ├── load.py
│   └── run_all_experiments.py
├── reports/
│   ├── results.csv
│   ├── figures/
│   └── env.txt
└── tests/
    ├── test_parser.py
    ├── test_sessionize.py
    └── test_deeplog_shapes.py
```

## Conventions

- `src/` code is importable (`pip install -e .`); notebooks only call functions, no copy-pasted logic.
- Event ID 0 = PAD, 1 = UNSEEN, real templates from 2.
- All timestamps in UTC.
- Every experiment script takes a YAML config and appends to `reports/results.csv`.
- Black + ruff for formatting/linting; small tests for parser and sessionizer.

## Setup commands

```bash
# Python env (WSL2 / Linux / macOS)
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -e .

# Data
bash scripts/download_data.sh

# Offline pipeline
python -m logpulse.parsing.drain_parser --dataset hdfs
python scripts/run_all_experiments.py --config configs/exp_E2_hdfs.yaml

# Demo stack
cd deploy && docker compose up -d fluent-bit && docker compose up -d --build
python scripts/load.py &
streamlit run dashboard/app.py
```

## Git workflow for the team

- GitHub repo (public after evaluation — it's a portfolio piece).
- `main` protected; feature branches `feat/drain-parser`, `feat/deeplog`, `feat/demo-services`.
- PRs reviewed by one teammate — same habits as open-source contributions (clear descriptions, small diffs).
- Issues on a GitHub Project board mirroring [[09 - Roadmap and Team Split]].
- `.gitignore`: `data/`, `.venv/`, `*.pt`, `__pycache__/`, `.ipynb_checkpoints/`. Share trained models via Releases or Drive.
