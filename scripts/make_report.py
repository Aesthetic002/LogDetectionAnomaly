"""Build the Word report: reports/LogPulse_Report.docx.

    python scripts/make_report.py

Text adapted from docs/11; every number comes from reports/results.csv via
logpulse.eval.tables, and the results discussion from reports/discussion.md (written
after the runs, so no placeholder number ever reaches the report).
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import matplotlib.patches as mpatches
import pandas as pd

from logpulse.eval.plots import INK2, SERIES, fig, save
from logpulse.eval.tables import build
from logpulse.paths import FIGURES, REPORTS, ROOT, RESULTS_CSV

B: list[dict] = []
h1 = lambda t, brk=True: B.append({"type": "h1", "text": t, "break": brk})  # noqa: E731
h2 = lambda t: B.append({"type": "h2", "text": t})  # noqa: E731
h3 = lambda t: B.append({"type": "h3", "text": t})  # noqa: E731
p = lambda t: B.append({"type": "p", "text": " ".join(t.split())})  # noqa: E731
bullets = lambda items, numbered=False: B.append({"type": "bullets", "items": items, "numbered": numbered})  # noqa: E731
figure = lambda path, cap, w=6.2: B.append({"type": "figure", "path": f"reports/figures/{path}", "caption": cap, "width_in": w})  # noqa: E731
code = lambda t: B.append({"type": "code", "text": t.strip("\n")})  # noqa: E731


def table(df: pd.DataFrame, title: str, note: str | None = None):
    df = df.fillna("—")
    B.append({"type": "table", "title": title, "note": note, "columns": [str(c) for c in df.columns],
              "rows": [[str(v) for v in r] for r in df.itertuples(index=False)]})


def md_blocks(path: Path):
    """Tiny markdown reader for discussion.md: ## / ### headings, - bullets, paragraphs."""
    if not path.exists():
        return
    buf: list[str] = []
    items: list[str] = []

    def flush():
        if buf:
            p(" ".join(buf))
            buf.clear()
        if items:
            bullets(list(items))
            items.clear()

    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("### "):
            flush()
            h3(s[4:])
        elif s.startswith("## "):
            flush()
            h2(s[3:])
        elif s.startswith("- "):
            if buf:
                p(" ".join(buf))
                buf.clear()
            items.append(s[2:])
        elif not s:
            flush()
        else:
            if items:
                bullets(list(items))
                items.clear()
            buf.append(s)
    flush()


def architecture_figure():
    f, ax = fig(9, 4.6)
    ax.axis("off")
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 5.2)

    def box(x, y, w, h, text, color):
        ax.add_patch(mpatches.FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.04,rounding_size=0.12",
                                             fc=color + "22", ec=color, lw=1.4))
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=8.5, color="#0b0b0b")

    def arrow(x0, y0, x1, y1, dashed=False):
        ax.annotate("", xy=(x1, y1), xytext=(x0, y0),
                    arrowprops=dict(arrowstyle="-|>", color=INK2, lw=1.1, ls="--" if dashed else "-"))

    ax.add_patch(mpatches.Rectangle((0.1, 2.75), 3.5, 2.3, fc="none", ec="#c3c2b7", ls="--"))
    ax.text(0.2, 4.85, "Demo system (Docker Compose)", fontsize=8, color=INK2)
    box(0.3, 3.9, 0.9, 0.5, "gateway", SERIES[0])
    box(1.5, 3.9, 0.9, 0.5, "orders", SERIES[1])
    box(2.6, 4.3, 0.9, 0.45, "inventory", SERIES[2])
    box(2.6, 3.35, 0.9, 0.45, "payment", SERIES[3])
    box(2.6, 2.85, 0.9, 0.35, "postgres", "#898781")
    arrow(1.2, 4.15, 1.5, 4.15)
    arrow(2.4, 4.2, 2.6, 4.5)
    arrow(2.4, 4.05, 2.6, 3.6)
    box(0.3, 1.6, 1.6, 0.6, "Fault injector\n(chaos API, ground truth)", SERIES[7])
    arrow(1.1, 2.2, 1.1, 2.75, dashed=True)
    box(4.1, 3.75, 1.2, 0.8, "Fluent Bit\n(forward → http)", "#898781")
    arrow(3.6, 4.1, 4.1, 4.1)
    box(5.7, 3.75, 1.4, 0.8, "Ingest API\nDrain3 (frozen + learn)", SERIES[0])
    arrow(5.3, 4.15, 5.7, 4.15)
    box(7.5, 3.75, 1.2, 0.8, "Sessionizer\n(trace_id, reorder)", SERIES[0])
    arrow(7.1, 4.15, 7.5, 4.15)
    box(7.3, 2.4, 1.6, 0.95, "Detectors\nDeepLog ×5, RF,\nB1 / B2 / B3", SERIES[6])
    arrow(8.1, 3.75, 8.1, 3.35)
    box(5.5, 2.45, 1.4, 0.8, "Template matcher\n(TF-IDF, τ)", SERIES[6])
    arrow(6.9, 2.85, 7.3, 2.85)
    box(7.5, 1.1, 1.2, 0.75, "SQLite store\n(per run)", "#898781")
    arrow(8.1, 2.4, 8.1, 1.85)
    box(5.4, 1.1, 1.6, 0.75, "Dashboard\nStreamlit + React Flow", SERIES[0])
    arrow(7.5, 1.5, 7.0, 1.5)
    ax.add_patch(mpatches.Rectangle((0.1, 0.05), 4.6, 1.2, fc="none", ec="#c3c2b7", ls="--"))
    ax.text(0.2, 1.05, "Offline research track", fontsize=8, color=INK2)
    box(0.25, 0.2, 1.3, 0.6, "Loghub\nHDFS / BGL", "#898781")
    box(1.75, 0.2, 1.3, 0.6, "Drain3 parse\nsessions/windows", SERIES[0])
    box(3.25, 0.2, 1.3, 0.6, "7 models + rules\nresults.csv", SERIES[6])
    arrow(1.55, 0.5, 1.75, 0.5)
    arrow(3.05, 0.5, 3.25, 0.5)
    box(9.0, 2.45, 0.9, 0.85, "Scorer\nTP/FP/FN,\nTTD", SERIES[7])
    arrow(8.7, 1.5, 9.4, 2.45)
    save(f, FIGURES / "fig_architecture.png")


def res() -> pd.DataFrame:
    return pd.read_csv(RESULTS_CSV)


def main():
    architecture_figure()
    T = build()
    r = res()
    facts = json.loads((REPORTS / "facts.json").read_text()) if (REPORTS / "facts.json").exists() else {}

    B.append({"type": "title", "text": "LogPulse: Online Anomaly Detection in Microservice Logs with Drain and LSTM",
              "lines": ["Log-Based Anomaly Detection for Microservice Systems Using Template Mining and Sequence Learning",
                        "", "5th Semester AIML Experiential Learning Project — Report", "",
                        "Team: <names and USNs as per the department template>", "Guide: <guide name>",
                        "Department of Artificial Intelligence and Machine Learning", "", "January 2027"]})
    B.append({"type": "toc"})

    h1("Abstract", brk=False)
    p(facts.get("abstract", ""))

    # ------------------------------------------------------------ 1 Introduction
    h1("1. Introduction")
    p("""Logs are the primary record of what a software system did at runtime. In a monolithic application one log
    file tells the story of a request; in a microservice architecture the same request crosses several services,
    containers and machines, and its log lines are interleaved with those of thousands of other requests. Operators
    rely on dashboards and threshold alerts, but many failures — a skipped processing step, a silent retry loop, an
    unusual ordering of operations — never produce an explicit error message.""")
    p("""Log-based anomaly detection addresses this by learning patterns of normal behaviour from historical logs and
    flagging deviations automatically. The standard pipeline has three stages: log parsing (extracting a constant
    template from each message), feature extraction (grouping events into sessions or windows and representing them
    as counts or sequences), and anomaly detection (supervised, unsupervised or semi-supervised models). Research
    systems such as DeepLog have reported F1-scores above 0.9 on benchmark datasets, but later empirical studies showed
    that these numbers depend heavily on evaluation choices such as random versus chronological data splitting.""")
    p("""This project implements the complete pipeline, compares classical and deep models fairly on the same data and
    splits, and applies the approach to a live microservice system where trace identifiers make request-level
    sessions possible — the microservice equivalent of the block identifier that makes the HDFS benchmark work.""")
    h2("1.1 Problem statement")
    p("""To design and implement a system that automatically detects anomalous behaviour in microservice applications
    from their unstructured logs, by parsing log messages into event templates, constructing request-level event
    sequences, and identifying sessions whose event counts or event order deviate from learned normal behaviour —
    evaluated with realistic, leakage-free protocols on public benchmarks and on a live system with injected faults.""")
    h2("1.2 Objectives")
    bullets([
        "To parse unstructured system logs into structured event templates using the Drain algorithm and evaluate parsing accuracy on labelled benchmark samples.",
        "To construct session- and window-based event representations for the HDFS and BGL datasets and for a microservice application using propagated trace identifiers.",
        "To implement and compare supervised (Logistic Regression, Decision Tree, Naive Bayes, Random Forest), unsupervised (PCA, Isolation Forest) and semi-supervised (LSTM-based DeepLog) anomaly detection models.",
        "To evaluate the models using precision, recall and F1-score under a chronological split, and quantify the effect of random splitting on reported performance.",
        "To deploy the pipeline for online detection on a containerised microservice application with controlled fault injection, and measure detection latency and false-alarm rate.",
        "To propose and evaluate improvements over the standard DeepLog approach — a semantic template matcher for unstable logs, an adaptive top-p acceptance rule and step-wise online scoring — and compare the system against conventional monitoring (keyword alerts, error-rate thresholds, health checks).",
    ], numbered=True)
    h2("1.3 Scope")
    p("""In scope: two public benchmarks (HDFS, BGL), a four-service demo application with seven fault types, seven
    models, three improvements, three conventional baselines, a live dashboard with traceable alerts. Out of scope:
    Kubernetes deployment, Kafka transport, transformer models and parameter-value anomaly models; these are listed as
    future work. Live measurements use a reduced version of the measurement protocol (Section 6.1).""")

    # ------------------------------------------------------------ 2 Literature
    h1("2. Literature survey")
    lit = pd.DataFrame([
        ["1", "Xu et al., Mining console logs", "SOSP 2009", "Source-code-based parsing + PCA on event count vectors", "Introduced HDFS dataset", "Needs source code; ignores event order"],
        ["2", "He et al., Experience report", "ISSRE 2016", "Benchmarked LR, DT, SVM, PCA, IM, LogCluster", "Supervised models strongest when labels exist", "Labels rarely available"],
        ["3", "Du et al., DeepLog", "CCS 2017", "LSTM next-event prediction, top-g rule, normal-only training", "F1 ≈ 0.96 on HDFS; explains which step deviated", "New templates treated as anomalies; favourable splits"],
        ["4", "He et al., Drain", "ICWS 2017", "Fixed-depth tree online parser", "High accuracy and speed", "Sensitive to similarity threshold"],
        ["5", "Zhu et al., Log parsing benchmarks", "ICSE-SEIP 2019", "13 parsers on 16 datasets", "Drain among most accurate", "Evaluated on 2k-line samples"],
        ["6", "Meng et al., LogAnomaly", "IJCAI 2019", "template2vec + LSTM", "Handles new templates better", "Needs word embeddings"],
        ["7", "Zhang et al., LogRobust", "ESEC/FSE 2019", "Semantic vectors + attention Bi-LSTM", "Robust to unstable logs", "Needs labelled anomalies"],
        ["8", "Guo et al., LogBERT", "IJCNN 2021", "Masked event prediction transformer", "Strong on HDFS/BGL", "Heavy for course scale"],
        ["9", "Le & Zhang, How far are we?", "ICSE 2022", "Re-evaluated 5 deep models", "Chronological split: DeepLog BGL F1 0.927 → 0.426", "Benchmarks only"],
        ["10", "Zhu et al., Loghub", "ISSRE 2023", "19 log datasets", "Standard benchmark source", "Few microservice datasets"],
        ["11", "He et al., Survey", "ACM CSUR 2021", "Survey of automated log analysis", "Taxonomy for this work", "—"],
        ["12", "Zhou et al., TrainTicket", "IEEE TSE 2021", "Industrial survey + benchmark system", "Microservice faults often multi-service and silent", "Debugging, not log ML"],
    ], columns=["#", "Paper", "Venue", "Approach", "Key result", "Limitation for us"])
    table(lit, "Table 2.1 — Literature survey")
    h2("2.1 Research gap")
    bullets([
        "Most reported results use random splits that leak future information; realistic chronological evaluation is less common in applied work.",
        "HDFS and BGL come from file systems and supercomputers; few studies show the same pipeline on containerised microservices, where trace IDs replace block IDs as the session key.",
        "Classical and deep models are often compared on different preprocessing and splits.",
        "Silent anomalies (skipped steps, retry storms) are under-represented in evaluations that focus on error-visible faults.",
        "Unstable logs after deployments are known to cause false alarms, but practical, measurable mitigations in live systems are rare.",
    ])

    # ------------------------------------------------------------ 3 Design
    h1("3. System requirements and design")
    h2("3.1 Architecture")
    figure("fig_architecture.png", "Figure 3.1 — LogPulse architecture: live track (top) and offline research track (bottom).")
    comp = pd.DataFrame([
        ["Demo microservices", "Realistic logs with trace IDs", "FastAPI, Docker"],
        ["Load generator", "Poisson traffic, 20 req/s", "httpx (async)"],
        ["Fault injector", "F1–F7 + ground truth", "Docker SDK, runtime fault switch"],
        ["Log shipper", "Collect container stdout", "Fluent Bit 3.1 (forward → http + file)"],
        ["Ingest API + parser", "Line → event id", "FastAPI, Drain3 (frozen tree, keeps learning)"],
        ["Sessionizer", "Group by trace_id, reorder, close", "Python heap + timers"],
        ["Detectors", "DeepLog ×5 configs, RF, B1–B3", "PyTorch, scikit-learn"],
        ["Template matcher", "Map unseen templates", "TF-IDF cosine (scikit-learn)"],
        ["Store", "Raw lines … alerts, ground truth", "SQLite per run (WAL), exported for scoring"],
        ["Dashboard", "8 panels + drill-down", "Streamlit + Plotly, React Flow page"],
        ["Scorer", "TP/FP/FN, TTD, FA/h", "Python (eval/live.py)"],
    ], columns=["Component", "Job", "Technology"])
    table(comp, "Table 3.1 — Components")
    h2("3.2 Data contracts")
    code("""raw line   {"ts": "...Z", "level": "INFO", "service": "orders", "trace_id": "a91f3c...", "msg": "Created order 5521 for user 88"}
event      {raw_id, ts, service, trace_id, event_id, template, unseen, matched_to, match_score}
decision   {trace_id, step, detector, event_id, p_actual, allowed_k, anomalous, top5, params}
alert      {detector, ts, event_ts, trace_id, service, step, expected[top5], observed, p_observed,
            reason, raw_ref, model_version, template_version}
ground     {fault_id, type, target_service, start_ts, end_ts, run_id}   (written by the injector only)""")
    h2("3.3 Hardware and software")
    p(f"""Development and all measurements: {facts.get('hardware', 'Windows 11 laptop, 12 logical CPUs, 16 GB RAM, no GPU')}.
    Software: Python 3.11, drain3 0.9.11, scikit-learn 1.9, PyTorch 2.14 (CPU), FastAPI, Streamlit, Docker Desktop
    with Compose v2, Fluent Bit 3.1, PostgreSQL 16, SQLite. Exact versions are in `requirements.lock` and `reports/env.txt`.""")

    # ------------------------------------------------------------ 4 Methodology
    h1("4. Methodology")
    h2("4.1 Log parsing with Drain")
    p("""Each message is first masked with ordered regular expressions (block IDs, IPs, UUIDs, Blue Gene node IDs, hex,
    numbers). Drain then routes the token list through a fixed-depth tree by length and leading tokens and compares it
    with the templates in the leaf: similarity = matching non-wildcard positions / length. If the best similarity
    reaches sim_th the line joins that group and differing positions become <*>; otherwise it starts a new group. The
    threshold is chosen by grouping accuracy (GA) on labelled data: Loghub-2k for HDFS and BGL, and — because the true
    template of every demo-app line is known from its source code — on the demo application's own logs.""")
    p("""Two parse modes are produced for the benchmarks. In the *full* mode Drain learns from every line (common, leaky
    practice). In the *honest* mode Drain learns only from the training period and test-period lines are matched against
    the frozen tree; lines that match nothing are mined by a separate miner so they still get a template, and an
    unseen-template policy decides what the model sees. Because Drain's output depends only on the masked content,
    each distinct masked string is processed once in order of first occurrence — identical to streaming every line.""")
    h2("4.2 Sessions, windows and splits")
    bullets([
        "HDFS: one session per block ID (`blk_-?\\d+`), labelled from anomaly_label.csv; 575,061 sessions.",
        "BGL: non-overlapping windows of 20 lines (variants: 100 lines, 1 h windows with 30 min step); a window is anomalous if any line has a non-'-' label.",
        "Demo app: one session per trace ID; the gateway creates it and every service forwards it in the X-Trace-Id header and writes it into every log line.",
        "Chronological split (default): sessions sorted by first timestamp; first 80 % train (last 10 % of it = validation), last 20 % test. Random split only for E3.",
        "Semi-supervised models (DeepLog, PCA) train on normal sessions of the training part only; every threshold and hyperparameter is chosen on validation.",
    ])
    h2("4.3 Models")
    p("""Classical models use an event-count matrix (sessions × templates; TF-IDF, binary and count+length variants in
    E7): Logistic Regression, Decision Tree (depth tuned on validation), Multinomial Naive Bayes and Random Forest with
    balanced class weights; PCA (squared prediction error of the residual subspace, 95 % variance) and Isolation
    Forest, both thresholded on validation.""")
    p("""DeepLog embeds the previous h = 10 event IDs, passes them through a two-layer LSTM (64 units) and predicts a
    distribution over the next event; it is trained on normal sequences only with cross-entropy and early stopping on
    a normal validation slice. Training windows are de-duplicated and sampled in proportion to their counts, which
    keeps the expected gradient identical to iterating over every window. At detection time every step is scored once
    and three statistics are stored — rank of the actual event, probability mass ranked above it, and its
    log-probability — so every decision rule is evaluated from the same forward pass.""")
    h2("4.4 Our improvements")
    h3("Improvement 1 — semantic template matcher")
    p("""A template unseen in training is mapped to the most similar known template of the same service and the same
    severity class if the TF-IDF cosine similarity reaches τ; the step is then scored as that known event. Unmatched
    WARN/ERROR templates are anomalous steps; unmatched INFO templates are neutral and queued for review. Compared
    policies: P1 unseen = anomaly (vanilla), P2 ignore, P3 severity only, P4 matcher (ours).""")
    h3("Improvement 2 — adaptive top-p acceptance")
    p("""Instead of accepting the actual event when it is among the top g predictions, accept it when it lies in the
    smallest set of predictions whose cumulative probability reaches p. Equivalently, the step is anomalous when the
    probability mass ranked above the actual event is at least p. The allowed set shrinks after confident steps and
    grows after branchy ones. A per-step surprise threshold (−log p > θ) is evaluated as a variant.""")
    h3("Improvement 3 — step-wise online scoring")
    p("""Each event is scored the moment it is released from the sessionizer's reorder buffer, using the trace's events
    so far as the LSTM window, and the first anomalous step raises the alert — instead of waiting for the trace to
    close (session-level scoring) or for a 60 s window to fill (error-rate alerting).""")
    h2("4.5 Conventional baselines and live metrics")
    p("""B1 keyword alerting (ERROR|Exception|Traceback|timeout|failed, debounced per service), B2 error-rate threshold
    (non-2xx share of gateway responses in a sliding 60 s window, at least 20 requests) and B3 health checks (/health
    every 10 s, 3 consecutive failures) run on the same stream as the models. B1's debounce and B2's threshold are tuned
    on the tuning runs like the models. A fault run is detected when an alert that concerns the target service (or a
    trace that touched it) falls in [start, end + 30 s]; time to detect is measured from the injector's fault-start
    timestamp; false alarms are alerts outside every fault window, debounced to one per detector and service per 10 s.""")

    # ------------------------------------------------------------ 5 Implementation
    h1("5. Implementation")
    h2("5.1 Demo application and fault injection")
    p("""Four FastAPI services (gateway, orders, inventory with PostgreSQL, payment) implement a checkout flow and log
    one JSON object per line. Normal traffic deliberately contains rare-but-normal paths (≈1 % auth rejects, ≈1.5 %
    declined cards, ≈1.5 % out-of-stock, ≈2 % single payment retries) so the model does not learn that every rare path
    is an anomaly. Faults are applied by a chaos service that also writes the ground truth.""")
    faults = pd.DataFrame([
        ["F1", "Payment latency", "payment sleeps 3 s (orders times out at 2 s, retries)", "yes"],
        ["F2", "Payment hard down", "docker stop payment", "yes"],
        ["F3", "Inventory step skipped", "orders silently skips the reserve call; order completes", "no"],
        ["F4", "Retry storm", "payment answers 503 for 50 % of calls", "partly"],
        ["F5", "DB exhaustion", "docker pause postgres (inventory queries time out)", "yes"],
        ["F6", "Inventory paused", "docker pause inventory", "partly"],
        ["F7", "Bad deploy", "payment:v2 — 2 of 6 messages reworded + 1 new ERROR under real faults", "—"],
    ], columns=["ID", "Fault", "How", "Visible error?"])
    table(faults, "Table 5.1 — Fault catalogue")
    h2("5.2 Online pipeline")
    p("""Fluent Bit receives container logs through Docker's fluentd driver, lifts the JSON fields and posts batches to
    the detector's /ingest endpoint while also writing a copy to disk (the published demo dataset). A background loop
    (every 0.25 s) parses new lines with the frozen-then-learning Drain tree, runs the matcher on new templates, feeds
    the reorder buffer (2 s), scores released events step-wise, closes traces on the gateway's response line or after
    5 s idle, runs the session-level detectors, and writes raw lines, events, decisions and alerts to a per-run SQLite
    file. Every alert stores the expected top-5 events, the observed event and probability, the raw line reference and
    the model and template versions — the traceability chain from raw line to verdict.""")
    h2("5.3 Dashboard")
    p("""The Streamlit dashboard shows the live topology (node colour from alerts and health), the log wall with event
    chips, the untangling view (one lane per trace), alert cards with expected vs observed and the ground-truth verdict,
    fault buttons and the scoreboard; an Investigate tab drills from an alert to the predicted distribution, per-step
    surprise, raw lines and verdict; further tabs show the normal flow graph with trace overlay, the template library
    (new → matched rows), incident reports and the benchmark tables. A React Flow page served by the detector renders the
    animated topology and the flow graph. Any recorded run can be replayed by selecting it.""")
    for f in ("fig_dashboard_live.png", "fig_dashboard_investigate.png"):
        if (FIGURES / f).exists():
            figure(f, "Figure 5.%d — Dashboard: %s." % (1 if "live" in f else 2,
                                                         "live mode during a fault" if "live" in f else "alert drill-down"))
    h2("5.4 Repository and reproducibility")
    code("""src/logpulse/  parsing/ features/ models/ eval/ online/ store.py
services/      gateway orders inventory payment (+ common/logging_setup.py)
deploy/        docker-compose.yml fluent-bit.conf *.Dockerfile
chaos/         inject.py schedule.py ground_truth.csv
dashboard/     app.py (Streamlit), react/index.html
scripts/       download_data.py run_all_experiments.py run_live_protocol.py score_live.py make_report.py
reports/       results.csv tables.md figures/ incidents/""")
    p("""Every number in this report is a row in reports/results.csv and is regenerated by `make results` (benchmarks)
    and `make score` (live runs). Seeds are fixed; thresholds are chosen on validation or tuning runs only.""")

    # ------------------------------------------------------------ 6 Results
    h1("6. Experiments and results")
    h2("6.1 Protocol actually run")
    p(facts.get("protocol", ""))
    order = ["Table 1 — Parsing (E1)", "Table 2 — Main results, chronological split (E2)",
             "Table 3 — Random vs chronological split (E3)", "Table D2 — Decision rule (E11)",
             "Table D1 — Unseen-template policies (E6 / E10)", "Table A — Conventional monitoring vs our model (E13)",
             "Table B — Headline metrics", "Table 4 — Live faults per model (E8)", "Table D3 — Detection latency (E12)",
             "Ablation (E14)", "Table E — Overhead", "Table F — User study (time to root cause)"]
    figs = {
        "Table 1 — Parsing (E1)": [("fig_ga_vs_simth.png", "Grouping accuracy vs sim_th, with and without masking (E1).")],
        "Table 2 — Main results, chronological split (E2)": [
            ("fig_f1_models.png", "F1 per model and dataset, chronological split (E2)."),
            ("fig_confusion.png", "Confusion matrices, RF and DeepLog."),
            ("fig_dt_top_hdfs.png", "Top levels of the HDFS decision tree — which events decide.")],
        "Table 3 — Random vs chronological split (E3)": [("fig_random_vs_chrono.png", "Random vs chronological split (E3).")],
        "Table D2 — Decision rule (E11)": [("fig_rules.png", "Decision rules on the same trained LSTM (E11)."),
                                            ("fig_topp_vs_p.png", "F1 vs p with the best fixed top-g for reference."),
                                            ("fig_deeplog_vs_g.png", "DeepLog precision / recall / F1 vs g (E5).")],
        "Table D1 — Unseen-template policies (E6 / E10)": [("fig_policies_bgl.png", "Unseen-template policies on BGL and τ sensitivity."),
                                                           ("fig_deploy_alerts.png", "Alerts per minute around the F7 deploy.")],
        "Table A — Conventional monitoring vs our model (E13)": [("fig_table_a_heatmap.png", "Table A as a heatmap.")],
        "Table D3 — Detection latency (E12)": [("fig_ttd_timeline.png", "Time to detect per fault type (median, IQR).")],
    }
    sec = 2
    for title in order:
        if title not in T:
            continue
        h2(f"6.{sec} {title.split(' — ')[1]}")
        sec += 1
        table(T[title], title)
        for f, cap in figs.get(title, []):
            if (FIGURES / f).exists():
                figure(f, f"Figure — {cap}")
    supp = [k for k in T if k.startswith("E") and " — " in k]
    if supp:
        h2(f"6.{sec} Supplementary experiments")
        for k in supp:
            table(T[k], k)
        for f, cap in (("fig_train_size.png", "Training-set size (E4)."), ("fig_dt_overfit_hdfs.png", "Decision tree depth vs F1 (HDFS).")):
            if (FIGURES / f).exists():
                figure(f, f"Figure — {cap}", 5.0)
    h2("6.%d Discussion" % (sec + 1))
    md_blocks(REPORTS / "discussion.md")

    # ------------------------------------------------------------ 7 Conclusion
    h1("7. Conclusion and future work")
    md_blocks(REPORTS / "conclusion.md")

    # ------------------------------------------------------------ References
    h1("References")
    refs = [
        "W. Xu, L. Huang, A. Fox, D. Patterson, and M. I. Jordan, \"Detecting large-scale system problems by mining console logs,\" in Proc. ACM SOSP, 2009.",
        "S. He, J. Zhu, P. He, and M. R. Lyu, \"Experience report: System log analysis for anomaly detection,\" in Proc. IEEE ISSRE, 2016.",
        "M. Du, F. Li, G. Zheng, and V. Srikumar, \"DeepLog: Anomaly detection and diagnosis from system logs through deep learning,\" in Proc. ACM CCS, 2017.",
        "P. He, J. Zhu, Z. Zheng, and M. R. Lyu, \"Drain: An online log parsing approach with fixed depth tree,\" in Proc. IEEE ICWS, 2017.",
        "J. Zhu, S. He, J. Liu, P. He, Q. Xie, Z. Zheng, and M. R. Lyu, \"Tools and benchmarks for automated log parsing,\" in Proc. ICSE-SEIP, 2019.",
        "W. Meng et al., \"LogAnomaly: Unsupervised detection of sequential and quantitative anomalies in unstructured logs,\" in Proc. IJCAI, 2019.",
        "X. Zhang et al., \"Robust log-based anomaly detection on unstable log data,\" in Proc. ESEC/FSE, 2019.",
        "H. Guo, S. Yuan, and X. Wu, \"LogBERT: Log anomaly detection via BERT,\" in Proc. IJCNN, 2021.",
        "V.-H. Le and H. Zhang, \"Log-based anomaly detection with deep learning: How far are we?,\" in Proc. ICSE, 2022.",
        "J. Zhu, S. He, P. He, J. Liu, and M. R. Lyu, \"Loghub: A large collection of system log datasets for AI-driven log analytics,\" in Proc. IEEE ISSRE, 2023.",
        "S. He, P. He, Z. Chen, T. Yang, Y. Su, and M. R. Lyu, \"A survey on automated log analysis for reliability engineering,\" ACM Computing Surveys, vol. 54, no. 6, 2021.",
        "X. Zhou et al., \"Fault analysis and debugging of microservice systems: Industrial survey, benchmark system, and empirical study,\" IEEE Trans. Software Eng., 2021.",
    ]
    bullets([f"[{i}] {t}" for i, t in enumerate(refs, 1)])

    h1("Appendix A — Configuration")
    code((ROOT / "configs" / "drain3.ini").read_text())
    h1("Appendix B — Sample incident report", brk=False)
    inc = sorted((REPORTS / "incidents").glob("test_s*__F3*.md")) or sorted((REPORTS / "incidents").glob("test_s*__F*.md"))
    if inc:
        code(re.sub(r"[*`#]", "", inc[0].read_text(encoding="utf-8")))

    out_json = REPORTS / "report_content.json"
    out_json.write_text(json.dumps({"title": "LogPulse — Project Report", "short_title": "LogPulse — log anomaly detection",
                                    "author": "LogPulse team", "blocks": B}, ensure_ascii=False), encoding="utf-8")
    docx = REPORTS / "LogPulse_Report.docx"
    subprocess.run(["node", str(ROOT / "scripts" / "report" / "build_docx.js"), str(out_json), str(docx)], check=True)


if __name__ == "__main__":
    main()
