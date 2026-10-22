---
tags: [aiml, el-project, log-anomaly-detection, report, synopsis]
created: 2026-10-22
updated: 2026-10-22
status: draft text — adapt to the RVCE synopsis/report template
---

# Report and Synopsis Content

Related: [[00 - Project Hub]] · [[07 - Evaluation Plan]] · [[10 - Learning Plan and Resources]]

Ready-to-adapt text for the synopsis, the final report and a possible paper. Fill `<…>` placeholders once results exist. Team names/USNs go into the department template as before.

## Table of Contents

- [[#Title options|Title options]]
- [[#Abstract|Abstract]]
- [[#Introduction|Introduction]]
- [[#Problem statement|Problem statement]]
- [[#Objectives|Objectives]]
- [[#Novelty and contributions|Novelty and contributions]]
- [[#Literature survey|Literature survey]]
- [[#Research gap|Research gap]]
- [[#Proposed methodology|Proposed methodology]]
- [[#Hardware and software requirements|Hardware and software requirements]]
- [[#Expected outcomes|Expected outcomes]]
- [[#Report chapter outline|Report chapter outline]]
- [[#References|References]]

## Title options

1. *Log-Based Anomaly Detection for Microservice Systems Using Template Mining and Sequence Learning*
2. *LogPulse: Online Anomaly Detection in Microservice Logs with Drain and LSTM*
3. *Comparative Study of Classical and Deep Learning Models for Log Anomaly Detection under Realistic Evaluation*

## Abstract

Modern applications are built as many cooperating microservices, each producing large volumes of unstructured log messages. Failures in such systems are often visible in the logs long before users report them, but the volume makes manual inspection impractical and keyword-based alerting misses failures that produce no explicit error. This project builds an end-to-end log anomaly detection pipeline. Raw log messages are converted into structured event templates using the Drain online parsing algorithm, grouped into sessions using block identifiers (HDFS), time windows (BGL) or propagated trace identifiers (microservices), and analysed with both classical machine-learning models (Logistic Regression, Decision Tree, Naive Bayes, Random Forest, PCA, Isolation Forest) and a DeepLog-style LSTM that learns normal event order from fault-free data. Models are evaluated on the public HDFS and BGL benchmarks using a chronological train/test split to avoid data leakage, and on a purpose-built microservice application with controlled fault injection, measuring precision, recall, F1-score, detection latency and false-alarm rate. <Add one sentence with the headline result.>

## Introduction

Logs are the primary record of what a software system did at runtime. In a monolithic application one log file tells the story of a request; in a microservice architecture the same request crosses several services, containers and machines, and its log lines are interleaved with those of thousands of other requests. Operators rely on dashboards and threshold alerts, but many failures — a skipped processing step, a silent retry loop, an unusual ordering of operations — never produce an explicit error message.

Log-based anomaly detection addresses this by learning patterns of normal behaviour from historical logs and flagging deviations automatically. The standard pipeline has three stages: log parsing (extracting a constant template from each message), feature extraction (grouping events into sessions or windows and representing them as counts or sequences), and anomaly detection (supervised, unsupervised or semi-supervised models). Research systems such as DeepLog have reported F1-scores above 0.9 on benchmark datasets, but later empirical studies showed that these numbers depend heavily on evaluation choices such as random versus chronological data splitting.

This project implements the complete pipeline, compares classical and deep models fairly on the same data and splits, and applies the approach to a live microservice system where trace identifiers make request-level sessions possible.

## Problem statement

To design and implement a system that automatically detects anomalous behaviour in microservice applications from their unstructured logs, by parsing log messages into event templates, constructing request-level event sequences, and identifying sessions whose event counts or event order deviate from learned normal behaviour — evaluated with realistic, leakage-free protocols on public benchmarks and on a live system with injected faults.

## Objectives

1. To parse unstructured system logs into structured event templates using the Drain algorithm and evaluate parsing accuracy on labelled benchmark samples.
2. To construct session- and window-based event representations for the HDFS and BGL datasets and for a microservice application using propagated trace identifiers.
3. To implement and compare supervised (Logistic Regression, Decision Tree, Naive Bayes, Random Forest), unsupervised (PCA, Isolation Forest) and semi-supervised (LSTM-based DeepLog) anomaly detection models.
4. To evaluate the models using precision, recall and F1-score under a chronological split, and quantify the effect of random splitting on reported performance.
5. To deploy the pipeline for online detection on a containerised microservice application with controlled fault injection, and measure detection latency and false-alarm rate.
6. To propose and evaluate improvements over the standard DeepLog approach — a semantic template matcher for unstable logs, an adaptive top-p acceptance rule and step-wise online scoring — and compare the system against conventional monitoring (keyword alerts, error-rate thresholds, health checks).

## Novelty and contributions

Beyond reproducing established methods, this work contributes:

1. **Semantic template matching for unstable logs.** Newly appearing log templates are mapped to the most similar known template within the same service and severity class using TF-IDF cosine similarity, so that reworded messages after a deployment are not misreported as anomalies; only unmatched warning/error templates raise alerts. Evaluated by false alarms per hour after a controlled deployment and by recall on concurrent real faults.
2. **Adaptive top-p anomaly decision.** The fixed top-g acceptance set of DeepLog is replaced by the smallest set of predicted events whose cumulative probability reaches p, adapting to model confidence at each step. Evaluated by precision, recall and F1 under chronological splits on HDFS and BGL.
3. **Step-wise online scoring for microservices.** Each event is scored as it arrives within its trace, enabling detection before a request completes. Evaluated by time to detect against session-level scoring and conventional threshold-based alerting.
4. **Traceable, ground-truth-verified evaluation.** Every alert is linked to its raw log lines, the model's predicted distribution and the injected fault, enabling automatic TP/FP/FN scoring of live runs against keyword, error-rate and health-check baselines.

## Literature survey

| # | Paper | Venue / year | Approach | Key result / takeaway | Limitation relevant to us |
|---|---|---|---|---|---|
| 1 | Xu et al., Mining console logs | SOSP 2009 | Source-code-based parsing + PCA on event count vectors | Introduced HDFS dataset; detected large-scale problems | Needs source code; ignores event order |
| 2 | He et al., Experience report | ISSRE 2016 | Benchmarked LR, DT, SVM, PCA, IM, LogCluster | Supervised models strongest when labels exist | Labels rarely available in practice |
| 3 | Du et al., DeepLog | CCS 2017 | LSTM next-event prediction, top-g rule, trained on normal logs | F1 ≈ 0.96 on HDFS; explains which step deviated | Treats new templates as anomalies; evaluated with favourable splits |
| 4 | He et al., Drain | ICWS 2017 | Fixed-depth tree online parser | High accuracy and speed across datasets | Sensitive to similarity threshold and preprocessing |
| 5 | Zhu et al., Tools and benchmarks for log parsing | ICSE-SEIP 2019 | Compared 13 parsers on 16 datasets | Drain among most accurate and robust | Parsing evaluated on 2k-line samples |
| 6 | Meng et al., LogAnomaly | IJCAI 2019 | Template semantics (template2vec) + LSTM | Detects sequential and quantitative anomalies; handles new templates better | More complex; needs word embeddings |
| 7 | Zhang et al., LogRobust | ESEC/FSE 2019 | Semantic vectors + attention Bi-LSTM, supervised | Robust to unstable (evolving) logs | Needs labelled anomalies |
| 8 | Guo et al., LogBERT | IJCNN 2021 | Transformer with masked event prediction | Strong results on HDFS/BGL/Thunderbird | Heavy for a course-scale project |
| 9 | Le & Zhang, How far are we? | ICSE 2022 | Re-evaluated 5 deep models under varied settings | Chronological split drops DeepLog BGL F1 from 0.927 to 0.426; label noise and unstable logs hurt | Benchmarks only, no microservice systems |
| 10 | Zhu et al., Loghub | ISSRE 2023 | Collection of 19 log datasets | Standard benchmark source | Few microservice datasets with trace IDs |
| 11 | He et al., Survey on automated log analysis | ACM CSUR 2021 | Survey of logging, parsing, anomaly detection, failure prediction | Overall taxonomy for this work | — |
| 12 | Zhou et al., Microservice fault analysis (TrainTicket) | IEEE TSE 2021 | Industrial survey + benchmark microservice system | Real microservice faults are often multi-service and silent | Focus on debugging, not log ML |

## Research gap

- Most reported results use random splits that leak future information; realistic chronological evaluation is less common in student and applied work.
- Benchmark datasets (HDFS, BGL) come from file systems and supercomputers; few studies show the same pipeline on modern containerised microservices, where trace IDs replace block IDs as the session key.
- Classical and deep models are often compared on different preprocessing and splits, making comparisons unreliable.
- Silent anomalies (skipped steps, retry storms) are under-represented in evaluations that focus on error-visible faults.

## Proposed methodology

1. **Data collection** — HDFS and BGL from Loghub; microservice logs from a four-service Docker Compose application (gateway, orders, inventory, payment) emitting JSON logs with propagated trace IDs, collected by Fluent Bit.
2. **Preprocessing and parsing** — header extraction; regex masking of IPs, block IDs, numbers and identifiers; Drain3 template mining with tuned similarity threshold; parser fitted on the training period only.
3. **Session construction** — block-ID sessions (HDFS), fixed/time windows (BGL), trace-ID sessions (microservices); labels from benchmark ground truth or the fault-injection log.
4. **Feature representation** — event count vectors (raw/TF-IDF) for classical models; ordered event-ID sequences with sliding windows for the LSTM.
5. **Models** — LR, DT, NB, RF (supervised); PCA, Isolation Forest (unsupervised); DeepLog-style two-layer LSTM with top-g detection (semi-supervised).
6. **Evaluation** — chronological 80/20 split with validation for tuning; precision, recall, F1, PR-AUC; random-split comparison; for the live system, detection latency and false alarms per hour across repeated fault-injection runs.
7. **Online deployment** — ingest API, online parser, trace sessionizer, detector service and Streamlit dashboard showing alerts with the expected-versus-observed event.

## Hardware and software requirements

**Hardware:** laptop/desktop with ≥ 8 GB RAM (16 GB recommended), ≥ 10 GB free disk; optional cloud GPU (Google Colab).

**Software:** Python 3.11, drain3, pandas, NumPy, SciPy, scikit-learn, PyTorch, FastAPI, Streamlit, Docker and Docker Compose, Fluent Bit, PostgreSQL/SQLite, Git/GitHub; OS: Windows 11 with WSL2 or Linux.

## Expected outcomes

- A reusable log anomaly detection pipeline from raw logs to alerts.
- A fair comparison of seven models on HDFS and BGL under chronological evaluation.
- Quantified evidence of how evaluation choices (split strategy, unseen templates) change reported performance.
- A working live demonstration detecting injected faults, including faults that produce no explicit error message.
- A small, documented microservice log dataset with trace IDs and fault labels.
- Quantified improvement over conventional monitoring in fault detection rate (especially for faults without explicit error messages), time to detect, and lines an operator must read per incident.
- Quantified effect of each proposed modification (template matcher, top-p rule, step-wise scoring) via an ablation study.
- A visual, traceable dashboard linking each alert to its evidence and ground truth.

## Report chapter outline

1. Introduction — motivation, problem statement, objectives, scope
2. Literature survey — table above + research gap
3. System requirements and design — architecture diagram, components, data contracts
4. Methodology — parsing, sessionization, features, models
5. Implementation — services, pipeline, dashboard, key code
6. Experiments and results — Tables 1–4, figures, discussion
7. Conclusion and future work — LogAnomaly/LogBERT, Kubernetes deployment, root-cause localisation, feedback-based retraining
8. References
Appendix — config files, fault catalogue, screenshots

## References

[1] W. Xu, L. Huang, A. Fox, D. Patterson, and M. I. Jordan, "Detecting large-scale system problems by mining console logs," in *Proc. ACM SOSP*, 2009.
[2] S. He, J. Zhu, P. He, and M. R. Lyu, "Experience report: System log analysis for anomaly detection," in *Proc. IEEE ISSRE*, 2016.
[3] M. Du, F. Li, G. Zheng, and V. Srikumar, "DeepLog: Anomaly detection and diagnosis from system logs through deep learning," in *Proc. ACM CCS*, 2017.
[4] P. He, J. Zhu, Z. Zheng, and M. R. Lyu, "Drain: An online log parsing approach with fixed depth tree," in *Proc. IEEE ICWS*, 2017.
[5] J. Zhu, S. He, J. Liu, P. He, Q. Xie, Z. Zheng, and M. R. Lyu, "Tools and benchmarks for automated log parsing," in *Proc. ICSE-SEIP*, 2019.
[6] W. Meng et al., "LogAnomaly: Unsupervised detection of sequential and quantitative anomalies in unstructured logs," in *Proc. IJCAI*, 2019.
[7] X. Zhang et al., "Robust log-based anomaly detection on unstable log data," in *Proc. ESEC/FSE*, 2019.
[8] H. Guo, S. Yuan, and X. Wu, "LogBERT: Log anomaly detection via BERT," in *Proc. IJCNN*, 2021.
[9] V.-H. Le and H. Zhang, "Log-based anomaly detection with deep learning: How far are we?," in *Proc. ICSE*, 2022.
[10] J. Zhu, S. He, P. He, J. Liu, and M. R. Lyu, "Loghub: A large collection of system log datasets for AI-driven log analytics," in *Proc. IEEE ISSRE*, 2023.
[11] S. He, P. He, Z. Chen, T. Yang, Y. Su, and M. R. Lyu, "A survey on automated log analysis for reliability engineering," *ACM Computing Surveys*, vol. 54, no. 6, 2021.
[12] X. Zhou et al., "Fault analysis and debugging of microservice systems: Industrial survey, benchmark system, and empirical study," *IEEE Trans. Software Eng.*, 2021.

Double-check author lists and page numbers against Google Scholar before submitting.
