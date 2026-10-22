---
tags: [aiml, el-project, log-anomaly-detection, learning, resources]
created: 2026-10-22
updated: 2026-10-22
status: reference
---

# Learning Plan and Resources

Related: [[00 - Project Hub]] · [[09 - Roadmap and Team Split]]

## Table of Contents

- [[#What you actually need to know|What you actually need to know]]
- [[#Study order and time estimates|Study order and time estimates]]
- [[#Papers — must read|Papers — must read]]
- [[#Papers — nice to read|Papers — nice to read]]
- [[#Docs and tutorials|Docs and tutorials]]
- [[#Code to learn from|Code to learn from]]
- [[#Self-check questions|Self-check questions]]

## What you actually need to know

Not a whole ML degree. Specifically:

- **Python data work** — pandas groupby, regex, reading big files in chunks, parquet.
- **scikit-learn workflow** — fit/predict, train/val/test, `class_weight`, precision/recall/F1, confusion matrix.
- **Just enough deep learning** — what an embedding is, what an LSTM layer outputs, cross-entropy, a PyTorch training loop, `topk`.
- **Logs and observability** — structured logging, trace IDs, log shippers.
- **Docker Compose** — services, networks, env vars, logging drivers.
- **Evaluation hygiene** — imbalance, leakage, chronological splits.

You don't need: transformers, BERT, Kubernetes (unless doing the stretch), Kafka (unless stretch), any cloud account.

## Study order and time estimates

| # | Topic | Hours | Resource | Done when you can… |
|---|---|---|---|---|
| 1 | Read the 3 core papers | 6–8 | Below | Explain Drain, DeepLog and the leakage finding on a whiteboard |
| 2 | pandas + regex refresh | 3 | pandas user guide; regex101.com | Extract block IDs and build sessions from HDFS-2k |
| 3 | scikit-learn workflow | 4 | sklearn "Getting Started" + imbalanced metrics | Produce Table 2 rows for HDFS-2k |
| 4 | LSTM intuition | 2 | Colah's "Understanding LSTM Networks" blog | Explain gates and hidden state in plain words |
| 5 | PyTorch basics | 5 | Official "Learn the Basics" tutorial | Write the DeepLog training loop without copying |
| 6 | Structured logging + tracing | 2 | Python `logging` docs; OpenTelemetry concepts page | Add trace IDs to a FastAPI app |
| 7 | Docker Compose | 3 | Docker docs "Compose getting started" | Run 4 services + Postgres from one file |
| 8 | Fluent Bit | 2 | Fluent Bit docs: forward input, http output | Ship container logs to an HTTP endpoint |
| 9 | Streamlit | 2 | Streamlit docs "Get started" | Live-refreshing table + chart from SQLite |
| | **Total** | **~30–35 h per person** | spread over weeks 1–5 | |

Each person goes deeper on their own track (A: 2–3, B: 3–5, C: 6–8, D: 7–9) but everyone does #1 and #4.

## Papers — must read

1. **DeepLog** — M. Du, F. Li, G. Zheng, V. Srikumar, *"DeepLog: Anomaly Detection and Diagnosis from System Logs through Deep Learning"*, ACM CCS 2017.
2. **Drain** — P. He, J. Zhu, Z. Zheng, M. R. Lyu, *"Drain: An Online Log Parsing Approach with Fixed Depth Tree"*, ICWS 2017.
3. **How far are we?** — V.-H. Le, H. Zhang, *"Log-based Anomaly Detection with Deep Learning: How Far Are We?"*, ICSE 2022. (arXiv 2202.04301) — read for evaluation pitfalls.

## Papers — nice to read

4. W. Xu et al., *"Detecting Large-Scale System Problems by Mining Console Logs"*, SOSP 2009 — the PCA method and the origin of the HDFS dataset.
5. S. He et al., *"Experience Report: System Log Analysis for Anomaly Detection"*, ISSRE 2016 — classical models compared (the loglizer paper).
6. J. Zhu et al., *"Tools and Benchmarks for Automated Log Parsing"*, ICSE-SEIP 2019 — parser comparison, GA metric.
7. J. Zhu et al., *"Loghub: A Large Collection of System Log Datasets for AI-driven Log Analytics"*, ISSRE 2023 (arXiv 2008.06448).
8. W. Meng et al., *"LogAnomaly"*, IJCAI 2019; X. Zhang et al., *"LogRobust"*, ESEC/FSE 2019 — handling unstable logs.
9. S. He et al., *"A Survey on Automated Log Analysis for Reliability Engineering"*, ACM Computing Surveys 2021 — the big-picture survey for the literature chapter.

Reading tip: abstract → figures → method section → evaluation tables. Skip proofs and related-work on first pass. Write a 5-line summary per paper in a `Papers/` note — these become the literature survey.

## Docs and tutorials

- Drain3 README — github.com/logpai/Drain3
- Loghub datasets — github.com/logpai/loghub
- PyTorch tutorials — pytorch.org/tutorials ("Learn the Basics", "Sequence models and LSTMs")
- scikit-learn user guide — model evaluation section
- Fluent Bit docs — docs.fluentbit.io
- Docker Compose docs — docs.docker.com/compose
- FastAPI tutorial — fastapi.tiangolo.com
- Streamlit docs — docs.streamlit.io
- Chaos Mesh / LitmusChaos docs (stretch)

## Code to learn from

Read, don't copy-paste — the report must describe *your* implementation.

- **logpai/loglizer** — classical models + feature extraction for HDFS/BGL (older, but very readable).
- **logpai/logparser** — reference implementations of Drain and other parsers, plus GA evaluation.
- **LogIntelligence/LogADEmpirical** — code for the ICSE 2022 study: chronological splits, DeepLog/LogAnomaly/LogRobust implementations.
- **logpai/Drain3** — examples folder.

## Self-check questions

Answer these without notes before the first review:

- Why does Drain group by length first?
- What does `sim_th` trade off? What breaks if it's too low? Too high?
- Why is accuracy a bad metric here?
- Why does DeepLog train only on normal data, and what does `g` control?
- What is data leakage in a random split of time-ordered logs?
- What is the microservice equivalent of the HDFS block ID, and how do we create it?
- Name an anomaly with no error line in it. Which model can catch it?
