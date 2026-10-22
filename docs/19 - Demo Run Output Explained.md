---
tags: [aiml, el-project, log-anomaly-detection, demo, results]
created: 2026-10-22
updated: 2026-10-22
status: explains run demo_0918 (python scripts/demo.py, 2026-10-22 09:18 IST)
---

# Demo Run Output Explained

Related: [[16 - Fault Catalogue Explained]] · [[17 - How to Run]] · [[14 - Metrics and Baselines]]

What every line of the terminal output of `python scripts/demo.py` means, using the latest run, **`demo_0918`** (22 Oct 2026, 09:18 IST, about 7 minutes of traffic at 20 requests/s). It also covers what to say about each number in a review, and which numbers need a caveat.

## Table of Contents

- [[#The run in one picture|The run in one picture]]
- [[#The full terminal output|The full terminal output]]
- [[#Part 1 — Time to detect per fault|Part 1 — Time to detect per fault]]
- [[#Part 2 — The F7 deploy alert counts|Part 2 — The F7 deploy alert counts]]
- [[#Part 3 — New templates and the semantic matcher|Part 3 — New templates and the semantic matcher]]
- [[#Part 4 — Lines to read per incident|Part 4 — Lines to read per incident]]
- [[#The run summary file|The run summary file]]
- [[#Honest caveats for this run|Honest caveats for this run]]
- [[#What to say in the demo — 4 sentences|What to say in the demo]]
- [[#Reproduce or re-print this output|Reproduce or re-print this output]]

## The run in one picture

| Time (IST) | What `demo.py` did |
|---|---|
| 09:18:43 | New run `demo_0918` starts, normal traffic begins |
| 09:19:43 – 09:20:43 | **F1 slow payment** (payment answers in 3 s; orders gives up at 2 s) |
| 09:20:43 – 09:21:14 | normal traffic |
| 09:21:14 – 09:22:14 | **F3 skip stock step** (orders silently skips inventory) |
| 09:22:14 – 09:22:45 | normal traffic |
| 09:22:45 – 09:25:23 | **F7 deploy** of payment:v2 with reworded log messages (not a fault) |
| 09:25:23 → end | rollback, normal traffic, export, scoring |

Totals: 7,234 requests, 112,280 raw log lines, 6 new templates seen.

## The full terminal output

```text
Time to detect per fault (from injector's start timestamp):
detector           B1_keyword B2_error_rate B3_health deeplog_vanilla deeplog_full
type
F1_payment_latency       2.8s         10.8s    missed            9.8s         4.2s
F3_skip_reserve        missed         39.9s    missed            2.4s         1.0s

F7 deploy (157s, no real fault): alerts raised
  deeplog_vanilla    2593
  deeplog_full         15
  B1_keyword            2

New templates and what the semantic matcher did:
 event_id        status  matched_to  match_score                                                 template
       37   new-matched        34.0        0.903    Payment call timed out after <NUM> ms for order <NUM>
       38 new-unmatched         NaN        0.311          Order <NUM> failed after <NUM> payment attempts
       39 new-unmatched         NaN        0.092                     Stock release failed for order <NUM>
       40 new-unmatched         NaN        0.117         Payment service unreachable for order <NUM>: <*>
       41   new-matched        19.0        0.855 Charging customer card for order <NUM> with amount <NUM>
       42   new-matched        20.0        1.000           Payment successfully confirmed for order <NUM>

Lines to read per incident (raw window -> attached to alert):
        fault_id fault  lines_in_window  lines_attached
F1-1792640983565    F1            14746              37
F3-1792641074805    F3            12852              17
```

## Part 1 — Time to detect per fault

**How to read it.** Each cell is how many seconds after the fault started (the timestamp written by the injector) the detector raised its first alert about the affected service. "missed" means no alert by fault end + 30 s.

| Column | Detector | In plain words |
|---|---|---|
| `B1_keyword` | keyword alert | "grep for ERROR/timeout/failed" |
| `B2_error_rate` | error-rate threshold | "more than 10% failed responses in the last 60 s" |
| `B3_health` | health check | "`/health` failed 3 times in a row" |
| `deeplog_vanilla` | DeepLog as in the paper | LSTM, scores a request only after it finishes; any unknown log line = anomaly |
| `deeplog_full` | **our model** | LSTM, scores every log line as it arrives (step-wise), top-p rule, semantic matcher |

### Row F1 — slow payment (error-visible fault)

| Detector | Time | Why |
|---|---|---|
| Keyword | **2.8 s** | The first `Payment call timed out after 2003 ms` ERROR line appears about 2 s after the fault starts. Keyword alerting is fastest on a fault that prints errors, and we say so openly |
| **Ours** | **4.2 s** | Fires on that same first timeout line: the LSTM did not expect a timeout after `Calling payment`. The extra ~1.4 s over keyword is mostly the 2 s reorder buffer that waits for out-of-order lines |
| Vanilla DeepLog | 9.8 s | Same evidence, but it only scores a request once the request **finishes**, and an F1 request retries payment 4 times (~9 s) before giving up. **This gap (4.2 s vs 9.8 s) is improvement 3, step-wise scoring** |
| Error rate | 10.8 s | Has to wait until more than 10% of the last 60 s of responses have failed |
| Health check | missed | Payment is alive, just slow, so `/health` keeps answering. A realistic blind spot of liveness probes |

### Row F3 — stock step skipped (silent fault)

The fault prints **no error at all**: orders simply stops calling inventory and every response is still 200.

| Detector | Time | Why |
|---|---|---|
| Keyword | **missed** | No ERROR line, nothing to grep. This is the point of the demo |
| Health check | missed | Every service is up |
| Vanilla DeepLog | **2.4 s** | After `Created order`, the model expects `Calling inventory to reserve` (p ≈ 1.00) but sees `Calling payment` (p ≈ 0.000) |
| **Ours** | **1.0 s (the real skipped-step detection is at 2.4 s; see caveat 1)** | Same evidence as vanilla. For F3 the bad step happens about 0.2 s into the request, so step-wise and finish-then-score are equally fast; both wait the 2 s reorder buffer |
| Error rate | 39.9 s (**not a real detection**; see caveat 2) | Its 60 s window still contained F1's failed responses. F3 itself causes no failures |

**Takeaway.** Only the sequence models catch the silent fault; keyword alerting and health checks cannot see it.

## Part 2 — The F7 deploy alert counts

During the 157 s deploy, payment v2 handled every request. Nothing was broken; two log messages were simply worded differently. **Every alert here is a false alarm.**

| Detector | Alerts | Why |
|---|---|---|
| Vanilla DeepLog | **2,593** | Treats every unknown template as an anomaly, so it alerts on **almost every request** that touched payment (about 16 alerts per second) |
| **Ours** | **15** | The matcher mapped both reworded messages back to the known events (Part 3), so requests were scored normally. The 15 that remain: 10 come from requests caught mid-switch when v1 was stopped (`Payment service unreachable`, a genuine but short error caused by the deploy itself), and 5 from a rare normal event (`Restocked book`, see caveat 3) |
| Keyword | 2 | The same switch-over errors, debounced to one alert per 10 s |

**This is improvement 1, the semantic template matcher: 2,593 → 15 alerts (−99.4%) after a harmless deploy.**

## Part 3 — New templates and the semantic matcher

"New" means Drain created a template that did not exist in the training data. For each one the matcher looks for the most similar known template **in the same service and with the same severity**; if the similarity is at least τ = 0.6, the line is treated as that known event (`new-matched`), otherwise it stays unknown (`new-unmatched`).

| ID | Template | Came from | What the matcher did | Is that right? |
|---|---|---|---|---|
| 41 | `Charging customer card for order <NUM> with amount <NUM>` | F7 rewording | matched E19 `Charging card for order <NUM> amount <NUM>` (0.855) | ✔ correct, the intended case |
| 42 | `Payment successfully confirmed for order <NUM>` | F7 rewording | matched E20 `Payment confirmed for order <NUM>` (1.000) | ✔ correct (identical words after stop-word weighting) |
| 37 | `Payment call timed out after <NUM> ms for order <NUM>` | F1 | matched E34 `Inventory call timed out after <NUM> ms for order <NUM>` (0.903) | ✘ wrong meaning (payment ≠ inventory). Harmless here: E34 is itself a rare ERROR event, so the step is still flagged. Same service and severity (orders, ERROR), which is exactly why the matcher only maps within one severity class |
| 38 | `Order <NUM> failed after <NUM> payment attempts` | F1 | unmatched (0.311) | ✔ new ERROR → stays anomalous |
| 39 | `Stock release failed for order <NUM>` | F1 | unmatched (0.092) | ✔ new ERROR → stays anomalous |
| 40 | `Payment service unreachable for order <NUM>: <*>` | F7 switch-over | unmatched (0.117) | ✔ new ERROR → stays anomalous |

**Takeaway.** The matcher forgives rewordings but never hides a genuinely new ERROR. Unmatched ERROR/WARN templates are still anomalies.

## Part 4 — Lines to read per incident

| Fault | Raw lines from all services during the fault | Lines attached to our first alert |
|---|---|---|
| F1 | 14,746 | **37** |
| F3 | 12,852 | **17** |

Without the tool, an engineer would scroll through about 13–15 thousand interleaved lines to find the problem. With it, the alert links straight to the one request's 17–37 lines, with the bad step highlighted (Investigate tab). That's roughly **400–750× fewer lines** (headline metric H4 in [[14 - Metrics and Baselines]]).

## The run summary file

`reports/incidents/demo_0918__summary.md`:

| Field | Value | Meaning |
|---|---|---|
| requests_processed | 7,234 | traces (requests) the detector closed |
| raw_lines | 112,280 | log lines ingested (~15 per request) |
| anomalous_traces_by_service | orders 1,658 · gateway 459 · inventory 12 | traces our model flagged, by the service of the bad step. Gateway = F1 requests that timed out at the gateway |
| new_templates | 6 | Part 3 |
| false_alarms_per_h | 129.5 | **9 debounced false alarms in only ~4 minutes of fault-free time, extrapolated to an hour.** Short runs inflate this number; see caveat 3 |
| detection_latency_s | [4.2, 1.0] | F1 and F3 times from Part 1 |
| faults_detected | 2/2 | F1 and F3 both detected (F7 is not a fault) |

The full incident reports, `demo_0918__F1-….md` and `demo_0918__F3-….md`, show the first alert, what the model expected, the services involved, the comparison with the baselines and the raw lines.

## Honest caveats for this run

1. **F3 "1.0 s" was a lucky coincidence.** The first alert mapped to F3 was on a request that started 1.7 s *before* the fault, flagged for a rare `Restocked book` event. The scoring rule accepts any alert about the target service inside the fault window, so it counted. The first alert for an actually skipped step came at **+2.4 s**. Quote 2.4 s for F3.
2. **Error-rate "39.9 s" on F3 is F1's leftover.** Its 60 s window at that moment still contained 76 × 502 and 11 × 504 responses from F1 (the last one 10.9 s before F3 started). F3 produces no failed responses at all, so error-rate effectively **missed** F3. The scorer is deliberately generous to error-rate alerts (they have no request ID, so they count for any fault active at the time), and with only 30 s between faults in the demo, windows overlap. The measurement protocol uses ≥ 105 s gaps to avoid this.
3. **Rare normal events still cause a few false alarms.** `Restocked book to <NUM> units` happens only when book stock runs low. Drain also keeps one template per item (pen/book/mug/lamp), which makes each one rarer, so with p = 0.999 the model sometimes flags it. This caused 8 of our 18 raw false alarms. Possible fixes for later: mask item names, or train on more normal traffic.
4. **Demo settings, not tuned settings.** g = 9, p = 0.999 and τ = 0.6 were set by hand from a short check run; the automatic tuning step is still pending. These are numbers from **one** run, not the averaged multi-run results the report needs ([[14 - Metrics and Baselines#Measurement protocol|measurement protocol]]).

## What to say in the demo — 4 sentences

1. "On a fault that prints errors (F1), keyword alerts are fastest. We admit that, but our model fires at 4 seconds, more than twice as fast as vanilla DeepLog and the error-rate threshold, because it scores every log line as it arrives."
2. "On the silent fault (F3) nothing prints an error. Keyword and health-check alerts see nothing; only the sequence model notices that the stock step is missing, within about 2 seconds."
3. "After a harmless deploy that reworded two log messages, vanilla DeepLog raised 2,593 alerts in under 3 minutes; ours raised 15, because the semantic matcher recognised the rewordings, while genuinely new error messages still alarm."
4. "Every alert points to 17–37 log lines instead of 13–15 thousand, and is checked automatically against the injected ground truth."

## Reproduce or re-print this output

```bash
.venv/Scripts/python scripts/demo_summary.py demo_0918        # print this exact output again
.venv/Scripts/python scripts/incident_report.py --run demo_0918
.venv/Scripts/python scripts/demo.py                           # a new run (numbers vary a little run to run)
```

Replay it visually: dashboard (http://localhost:8501), sidebar → **Run** → `demo_0918`.
