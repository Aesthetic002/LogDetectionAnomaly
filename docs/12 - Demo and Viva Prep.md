---
tags: [aiml, el-project, log-anomaly-detection, demo, viva]
created: 2026-10-22
updated: 2026-10-22
status: prep
---

# Demo and Viva Prep

Related: [[00 - Project Hub]] · [[01 - Concepts Explained Simply]] · [[07 - Evaluation Plan]]

## Table of Contents

- [[#30-second pitch|30-second pitch]]
- [[#Demo script|Demo script]]
- [[#Before the demo checklist|Before the demo checklist]]
- [[#Likely viva questions with answers|Likely viva questions with answers]]
- [[#Honest limitations to state upfront|Honest limitations to state upfront]]

## 30-second pitch

"Microservices produce millions of log lines and many failures never print an error. We built a pipeline that turns raw logs into event templates with Drain, groups them per request using a trace ID — the same idea as the block ID in the HDFS benchmark — and learns what normal requests look like, using classical ML and a DeepLog-style LSTM. We evaluated it honestly with a chronological split on HDFS and BGL, showed how random splitting inflates scores, and then ran it live on our own four-service app: we break a service on purpose and the dashboard flags it within a few seconds — including a bug that produces no error line at all."

## Demo script

~9 minutes. Panels referenced are designed in [[13 - Demo Visualization and Traceability]].

1. **The system (30 s)** — topology map: containers, traffic flowing, all green; load generator on.
2. **The raw problem (30 s)** — log wall: raw interleaved lines scrolling — "no human can read this live."
3. **Parsing (45 s)** — event chips + template library: raw line → template → event ID; template count stabilising.
4. **Untangling (30 s)** — one lane per trace ID: "each request becomes a sentence."
5. **What the model learned (45 s)** — normal flow graph: "this is what normal looks like."
6. **Error-visible fault (1 min)** — press *Slow payment* (F1). Payment box turns red; alert card shows expected vs observed with probabilities; scoreboard shows time to detect. The keyword alert also fires — say so, it's fair.
7. **Silent fault (1.5 min)** — press *Skip stock step* (F3). No ERROR lines anywhere; keyword and error-rate columns stay dark; our model fires. Drill down: the trace takes a road that doesn't exist on the flow graph → raw lines → ground truth says TRUE POSITIVE. This is the money moment.
8. **Our contribution (1 min)** — press *Deploy reworded logs* (F7). Vanilla DeepLog's alert counter explodes; ours stays calm; template library shows "new → matched to E4 (0.83)".
9. **Results (2 min)** — four headline metric cards, Table A heatmap (baselines vs ours), deploy false-alarm chart, benchmark F1, ablation. Include one "where we lose" row.
10. **Close (30 s)** — incident report auto-generated for this run; limitations + future work.

## Before the demo checklist

- [ ] Fresh `docker compose down -v && up` the morning of; warm up 10 min of normal traffic.
- [ ] Model + template map loaded from the frozen `v1.0` files.
- [ ] Fault commands in a script with one key each — no typing live.
- [ ] Backup screen recording of the full demo, in case Wi-Fi/Docker misbehaves.
- [ ] Results slides exported as PDF too.
- [ ] Each teammate knows which part they narrate.

## Likely viva questions with answers

**Why parse logs at all? Why not feed raw text to a model?**
Raw messages almost never repeat exactly because of IDs and numbers. Templates collapse millions of lines into a few dozen event types, which makes counts and sequences meaningful and models small and fast.

**How does Drain work, briefly?**
Mask obvious variables, split into tokens, route through a fixed-depth tree by length and leading tokens, then compare with the templates in that leaf; join the most similar if similarity ≥ threshold, otherwise create a new template. Differing positions become `<*>`.

**What happens if sim_th is too low / too high?**
Too low → different events merge (e.g. "logged in" and "logged out"). Too high → one event splits into many templates. We tuned it on Loghub-2k using grouping accuracy.

**Why does DeepLog use top-g instead of the single most likely next event?**
Normal behaviour has branches. Requiring the exact top-1 event would flag many normal sessions. g trades false alarms against missed anomalies; we plotted F1 vs g.

**Why train DeepLog only on normal data?**
Anomalies are rare, varied and usually unlabelled. A healthy period is easy to get. The model only needs to know what normal looks like.

**What is a chronological split and why does it matter?**
Train on earlier data, test on later data — the way a real deployment works. A random split lets the model see the future, which inflates scores. The ICSE 2022 study showed DeepLog's BGL F1 drop from 0.927 to 0.426; we measured <our Δ>.

**Why is accuracy not reported?**
With ~3% anomalies, predicting "normal" always gives ~97% accuracy. Precision, recall, F1 and PR-AUC show real performance.

**How do you get sessions in microservices?**
The gateway creates a trace ID and every service forwards it in an HTTP header and writes it into every log line. All lines with the same trace ID form one session, like HDFS block IDs.

**How did you label the live data?**
The fault injector records type, target service and time window. Traces overlapping a fault window and touching the target service are anomalous. We hand-checked <N> traces to validate the rule.

**What about new log messages after a deployment?**
That's the unstable-log problem. We compared three policies — always anomalous, ignore, severity-aware — in experiment E6.

**Why compare with classical ML if you have an LSTM?**
To keep the deep model honest. On HDFS, count-based models are already very strong; the LSTM's advantage shows on ordering anomalies and in needing no anomaly labels.

**Which of your models is syllabus material?**
Decision Tree, Naive Bayes, Logistic Regression, Random Forest (ensembles) and K-means/PCA-style unsupervised methods; the LSTM is the beyond-syllabus extension.

**Can this scale to a real company?**
The design does — Drain is online and linear, the LSTM is small, and Fluent Bit/Kafka are what production uses. Our test is laptop-scale: 4 services and synthetic traffic, so we don't claim production performance.

**What did you contribute beyond implementing DeepLog?**
Three modifications, each measured against the conventional version: a semantic template matcher that maps reworded log messages to known events (fewer false alarms after deployments), an adaptive top-p acceptance rule instead of fixed top-g (better F1 on BGL), and step-wise online scoring (faster detection). Results in [[15 - Our Improvements#Result tables|Tables D1–D3]] and the ablation.

**Couldn't the matcher hide a real error by mapping it to a normal event?**
It only maps within the same service and the same log-level class, so an ERROR template can't be mapped to a normal INFO event. Unmatched ERROR/WARN templates are still anomalous. We report recall on real faults after the deploy to show it didn't drop much, and we hand-checked the mapping table.

**Why top-p instead of top-g?**
A fixed g ignores how confident the model is. After a step with only two plausible next events, g = 9 accepts seven implausible ones; after a branchy step it rejects normal ones. Top-p adapts the allowed set to the model's confidence. Same trained model, only the decision rule changes, so the comparison is clean.

**How do you know your baselines weren't set up to lose?**
Each baseline's window and threshold was tuned on the same validation runs as our model, all detectors ran on the same live stream at the same time, and we report the faults where baselines did as well or better than us.

**How is time to detect measured?**
The fault injector timestamps the fault start in the ground-truth file; detection time is the first alert that maps to that fault. Median and IQR over 10 runs per fault type; undetected runs are reported separately.

**What would you do next?**
Template-semantic models (LogAnomaly) for unstable logs, Kubernetes deployment with Chaos Mesh/LitmusChaos, root-cause localisation per service, and a feedback loop where operators mark false alarms to retrain.

## Honest limitations to state upfront

- The demo system is small and traffic is synthetic; real systems have far more templates and noisier behaviour.
- Live labels come from our own fault schedule — a rule, not human ground truth.
- HDFS is near-saturated as a benchmark; differences between models there are small.
- DeepLog in our version ignores parameter values (e.g. latency numbers inside messages); the original paper has an extra model for that.
