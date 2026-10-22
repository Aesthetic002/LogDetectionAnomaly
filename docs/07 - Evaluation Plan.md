---
tags: [aiml, el-project, log-anomaly-detection, evaluation]
created: 2026-10-22
updated: 2026-10-22
status: plan
---

# Evaluation Plan

Related: [[00 - Project Hub]] · [[05 - Models]] · [[03 - Datasets]]

## Table of Contents

- [[#What we must be able to claim|What we must be able to claim]]
- [[#Metrics|Metrics]]
- [[#Splitting rules|Splitting rules]]
- [[#Experiments|Experiments]]
- [[#Conventional baselines|Conventional baselines]]
- [[#Results table templates|Results table templates]]
- [[#Figures for the report|Figures for the report]]
- [[#Known pitfalls|Known pitfalls]]
- [[#Reproducibility rules|Reproducibility rules]]

## What we must be able to claim

1. "Drain parses HDFS/BGL with X% grouping accuracy at Y lines/sec."
2. "On a chronological split, model M reaches precision P / recall R / F1 F on HDFS and BGL."
3. "A random split inflates F1 by Δ — here is why we don't use it."
4. "DeepLog detects ordering anomalies (fault F3) that count-based models miss / catch less often."
5. "Live, the system detects injected faults within T seconds with a false-alarm rate of Z per hour."

Every number in the report should trace back to one row in `reports/results.csv`.

## Metrics

Anomaly = positive class.

| Metric | Formula | Why |
|---|---|---|
| Precision | TP / (TP + FP) | How many alerts are real — operators hate false alarms |
| Recall | TP / (TP + FN) | How many real problems we caught |
| F1 | 2PR / (P + R) | Single headline number |
| ROC-AUC / PR-AUC | threshold-free | For score-based models (PCA, IsoForest, LR probabilities); PR-AUC is more honest under heavy imbalance |
| False alarms / hour | FP per hour of normal traffic | Live demo metric people understand |
| Detection latency | alert time − fault start | Live demo metric |
| Throughput | lines/sec through parser + detector | Shows it can run online |
| Parsing GA | see [[04 - Log Parsing with Drain#Measuring parsing accuracy|parsing note]] | Parser quality |

Never report plain accuracy as a headline — with 3% anomalies, "always say normal" scores 97%.

```python
from sklearn.metrics import precision_recall_fscore_support, roc_auc_score, average_precision_score
p, r, f1, _ = precision_recall_fscore_support(y_true, y_pred, average="binary")
```

## Splitting rules

- **Chronological** is the default: sort sessions/windows by first timestamp, train = first 80%, test = last 20%. Validation = last 10% of the train part.
- **Semi-supervised (DeepLog, PCA)**: train only on the *normal* sessions from the train part; test on everything in the test part.
- **Parser**: fit on the train period; `match()` on the test period (unknown → UNSEEN).
- Fit TF-IDF/scalers/thresholds on train/validation only.
- **Random split** is run *only* as the comparison experiment E3.
- Run each configuration with 3–5 seeds and report mean ± std.

## Experiments

| ID | Question | Setup |
|---|---|---|
| E1 | How good is parsing? | GA on HDFS-2k, BGL-2k for sim_th 0.3–0.7, with/without masks; throughput |
| E2 | Main comparison | All 7 models × {HDFS, BGL} on chronological split |
| E3 | Does the split matter? | Same models, random vs chronological split → Δ F1 |
| E4 | Training-set size | DeepLog and RF trained on 1%, 10%, 50%, 100% of train data |
| E5 | DeepLog sensitivity | F1 vs g (1–15), vs h (5/10/20) |
| E6 | Unseen-template policy | Policies 1–3 from [[05 - Models#Handling unseen templates|Models]] on BGL chronological + demo fault F7 |
| E7 | Feature ablation (classical) | counts vs TF-IDF vs binary |
| E8 | Live demo evaluation | Demo app: per fault type → detected?, latency, false alarms/hour, per model |
| E9 (stretch) | Generalisation | Train on our app, test on Online Boutique logs (or vice versa) |
| E10 | Does the semantic template matcher cut post-deploy false alarms? | Policies P1–P4 on demo F7 deploy runs + BGL chronological — [[15 - Our Improvements#Experiment (E10)|details]] |
| E11 | Does adaptive top-p beat fixed top-g? | Same trained LSTM, two decision rules, HDFS/BGL/demo — [[15 - Our Improvements#Experiment (E11)|details]] |
| E12 | Does step-wise scoring detect faster? | TTD vs session-close scoring and baselines B1–B3 — [[15 - Our Improvements#Experiment (E12)|details]] |
| E13 | Does the model beat conventional monitoring? | B1 keyword, B2 error-rate threshold, B3 health check vs our model on all demo faults — [[14 - Metrics and Baselines]] |
| E14 | Ablation | Vanilla → +matcher → +top-p → full — [[15 - Our Improvements#Ablation plan|details]] |

E2, E3, E8, **E10, E13** are must-have (E10 and E13 carry the headline numbers). E1, E5, E11, E12 are cheap and give strong figures. The rest are optional.

## Conventional baselines

Defined in full in [[14 - Metrics and Baselines#Baselines — what conventional monitoring does|Metrics and Baselines]]:

- **B1 keyword alerting** — regex on ERROR/Exception/timeout, debounced.
- **B2 error-rate threshold** — > 5% non-2xx in a 60 s window.
- **B3 health check** — `/health` every 10 s, 3 failures.

All three run on the same live stream as our model, tuned on validation runs.

## Results table templates

**Table 1 — Parsing (E1)**

| Dataset | sim_th | Masking | GA | Templates found | True templates | Lines/sec |
|---|---|---|---|---|---|---|
| HDFS-2k | 0.5 | yes | | | | |
| BGL-2k | 0.5 | yes | | | | |

**Table 2 — Main results, chronological split (E2)**

| Model | Labels | HDFS P | HDFS R | HDFS F1 | BGL P | BGL R | BGL F1 |
|---|---|---|---|---|---|---|---|
| LR | sup | | | | | | |
| DT | sup | | | | | | |
| NB | sup | | | | | | |
| RF | sup | | | | | | |
| PCA | unsup | | | | | | |
| IsoForest | unsup | | | | | | |
| DeepLog | semi | | | | | | |

**Table 3 — Random vs chronological (E3)**

| Model | Dataset | F1 random | F1 chrono | Δ |
|---|---|---|---|---|

For context: the ICSE 2022 study reported DeepLog on BGL at 0.927 (random) vs 0.426 (chronological).

**Table 4 — Live faults (E8)**

| Fault | Type | Model | Detected (runs) | Median latency (s) | False alarms/h |
|---|---|---|---|---|---|
| F1 payment latency | error-visible | DeepLog | | | |
| F3 skipped reserve | ordering, no error | DeepLog | | | |
| F3 skipped reserve | ordering, no error | RF | | | |
| F4 retry storm | count | DeepLog | | | |

Tables for the conventional-baseline comparison (Table A), headline cards (Table B), overhead and user study: [[14 - Metrics and Baselines#Result tables to fill|Metrics and Baselines]]. Tables for our improvements (D1–D3): [[15 - Our Improvements#Result tables|Our Improvements]].

## Figures for the report

- Pipeline / architecture diagram.
- Template frequency long-tail plot.
- GA vs sim_th line plot.
- Grouped bar chart of F1 per model per dataset.
- Random vs chronological slope chart.
- DeepLog F1 / precision / recall vs g.
- Decision tree top levels (interpretability).
- Dashboard screenshot during a fault, with latency annotated.
- Confusion matrices for the best classical model and DeepLog.

## Known pitfalls

1. **Data leakage via random splits** — inflates semi-supervised models most.
2. **Parser leakage** — parsing the full dataset before splitting.
3. **Label noise** — the ICSE 2022 study found that just 1% mislabelled HDFS training data cut LogRobust's F1 by 37%. Our auto-labelling rule for the demo app must be checked by hand on a sample.
4. **Unstable logs** — new templates after a code change look anomalous. Handled by E6.
5. **Tuning on test** — choose thresholds, `g`, depth etc. on validation, then touch test once.
6. **HDFS ceiling effect** — almost everything scores > 0.9; don't oversell HDFS results, lean on BGL + live demo for the real comparison.
7. **Imbalance** — report P/R/F1 and PR-AUC, not accuracy.

## Reproducibility rules

- One config file per experiment (`configs/exp_E2_hdfs.yaml`), logged with results.
- Fixed seeds (`random`, `numpy`, `torch`).
- `make results` (or one script) regenerates every table from processed data.
- Record library versions (`pip freeze > reports/env.txt`) and hardware.
- Results are appended to `reports/results.csv` with columns: `exp_id, dataset, split, model, seed, precision, recall, f1, pr_auc, train_time_s, notes`.
