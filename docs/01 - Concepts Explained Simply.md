---
tags: [aiml, el-project, log-anomaly-detection, explainer]
created: 2026-10-22
updated: 2026-10-22
status: reference
---

# Concepts Explained Simply

Related: [[00 - Project Hub]] · [[04 - Log Parsing with Drain]] · [[05 - Models]]

## Table of Contents

- [[#What a log is|What a log is]]
- [[#Templates — the constant part of a log line|Templates — the constant part of a log line]]
- [[#Sessions and windows — grouping lines into stories|Sessions and windows]]
- [[#What counts as an anomaly|What counts as an anomaly]]
- [[#Two ways to look at a sequence|Two ways to look at a sequence]]
- [[#Supervised vs semi-supervised vs unsupervised|Supervised vs semi-supervised vs unsupervised]]
- [[#What an LSTM does here|What an LSTM does here]]
- [[#Why microservices make this harder|Why microservices make this harder]]
- [[#The whole idea in one paragraph|The whole idea in one paragraph]]

## What a log is

A log line is a sentence a program prints about what it just did:

```
2026-10-22 10:15:02 INFO  orders  [trace=a91f] Created order 5521 for user 88
2026-10-22 10:15:02 INFO  payment [trace=a91f] Charging card for order 5521 amount 499.00
2026-10-22 10:15:03 ERROR payment [trace=a91f] Gateway timeout after 3000 ms
```

It has a **header** (timestamp, level, service, trace ID) and a **message** (free text written by a developer).

## Templates — the constant part of a log line

The message is really a fixed sentence with blanks filled in. The code that printed it looked like:

```python
log.info(f"Created order {order_id} for user {user_id}")
```

So every such line, no matter the numbers, has the same **template**: `Created order <*> for user <*>`. The numbers are **parameters**.

Turning millions of raw lines into a few dozen templates is called **log parsing**. After parsing, every line becomes a small integer: "event E3". That is what makes ML possible — models can't learn from free text that never repeats exactly, but they can learn from "E1, E3, E7, E7, E2".

Drain is the algorithm we use for this. [[04 - Log Parsing with Drain]]

## Sessions and windows — grouping lines into stories

A single line is rarely abnormal on its own. A *story* is. So we group lines:

- **Session window** — all lines belonging to one unit of work. In HDFS, everything about one data block (`blk_-123…`). In our microservices, everything for one request (`trace=a91f`).
- **Fixed window** — every 100 lines, or every 1 hour, regardless of meaning. Used for BGL, which has no natural session ID.
- **Sliding window** — like fixed, but overlapping (e.g. 1 hour long, moving forward 30 minutes).

## What counts as an anomaly

Three kinds, from easy to hard:

1. **Bad event** — a template that should never appear in normal runs (`Gateway timeout`). A rule could catch this.
2. **Bad counts** — normal events in abnormal amounts (a request that retried 14 times). Count-based models catch this.
3. **Bad order** — normal events in an abnormal sequence (payment confirmed *before* the stock was reserved, or the "release lock" step never happened). Only sequence models like DeepLog catch this.

The interesting part of the project is kinds 2 and 3 — the ones `grep ERROR` misses.

## Two ways to look at a sequence

Take the session `E1 E2 E2 E5`.

- **As a bag (count vector)** — "E1 once, E2 twice, E5 once, everything else zero": `[1, 2, 0, 0, 1, 0, …]`. Order is lost. Classical ML (Logistic Regression, Random Forest, PCA) uses this.
- **As a sequence** — order kept. DeepLog uses this: it learns "after E1 E2, normally E3 or E4 comes next", and complains when E5 shows up.

## Supervised vs semi-supervised vs unsupervised

| Type | Needs labels? | Trained on | Example in this project |
|---|---|---|---|
| Supervised | Yes, normal + anomalous | Both classes | Logistic Regression, Decision Tree, Random Forest, Naive Bayes |
| Semi-supervised | Only "this is normal" | Normal data only | DeepLog |
| Unsupervised | No | Everything, unlabelled | PCA, Isolation Forest, K-means |

In real life, labels are rare and expensive — nobody tags millions of lines. That's why semi-supervised DeepLog is attractive: you just need a period where you know the system was healthy.

## What an LSTM does here

An LSTM is a neural network that reads a sequence one step at a time and keeps a running memory. It's the same idea as a phone keyboard predicting your next word.

DeepLog trains it on normal sessions to answer: *"given the last 10 events, what are the likely next events?"* At detection time:

- If the actual next event is in the model's top 9 guesses → fine.
- If it isn't → this step is surprising → the session is flagged.

That's the whole trick. It never needs to see a failure during training. [[05 - Models#DeepLog — the sequence model|Details and dry run]]

## Why microservices make this harder

- **Logs are scattered** across many services and containers — they must be collected into one place (Fluent Bit).
- **No natural session** unless you create one — that's why we propagate a `trace_id` through every service call.
- **Lines interleave** — thousands of requests run at once, so without the trace ID you cannot tell which line belongs to which request.
- **Code changes constantly** — new deployments add new log templates, which a naive model treats as anomalies (the "unstable logs" problem). Our online Drain3 parser plus an "unseen template" policy handles this. [[07 - Evaluation Plan#Known pitfalls|See pitfalls]]

## The whole idea in one paragraph

Collect every log line from every service, strip out the changing parts so each line becomes an event ID, group events by the request they belong to, learn what normal requests look like — either as counts (classical ML) or as ordered sequences (LSTM) — and raise an alert for any request whose events are unusual. Prove it works on public benchmarks, then prove it works live by deliberately breaking our own system and timing how fast it notices.
