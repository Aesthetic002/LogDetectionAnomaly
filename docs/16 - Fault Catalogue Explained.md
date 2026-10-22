---
tags: [aiml, el-project, log-anomaly-detection, faults, chaos, demo]
created: 2026-10-22
updated: 2026-10-22
status: reference — matches the code in chaos/inject.py and services/*/app.py
---

# Fault Catalogue Explained (F1–F7)

Related: [[06 - Microservices Demo Setup]] · [[14 - Metrics and Baselines]] · [[17 - How to Run]] · [[18 - What Does What]]

This note explains every fault we can inject into the demo app: what breaks, how the injector does it, what the logs look like afterwards, and which detector is expected to catch it. Measured numbers are only quoted where we have actually run that fault in the demo.

## Table of Contents

- [[#First, what a normal request looks like|First, what a normal request looks like]]
- [[#Overview table|Overview table]]
- [[#F1 — Slow payment|F1 — Slow payment]]
- [[#F2 — Payment down|F2 — Payment down]]
- [[#F3 — Stock step skipped (silent)|F3 — Stock step skipped (silent)]]
- [[#F4 — Retry storm|F4 — Retry storm]]
- [[#F5 — Database exhaustion|F5 — Database exhaustion]]
- [[#F6 — Inventory paused|F6 — Inventory paused]]
- [[#F7 — Bad deploy (reworded logs)|F7 — Bad deploy (reworded logs)]]
- [[#How a fault is injected and recorded|How a fault is injected and recorded]]
- [[#How a fault counts as detected|How a fault counts as detected]]
- [[#Results from the quick demo run|Results from the quick demo run]]

## First, what a normal request looks like

One `POST /checkout` produces one **trace** of about 15 log lines across 4 services, all carrying the same `trace_id`:

```text
gateway    Checkout request received for user 12 item book qty 2
gateway    Auth ok for user 12
gateway    Forwarding order to orders service
orders     Received order request from user 12 for item book
orders     Created order 52811 for user 12
orders     Calling inventory to reserve 2 x book for order 52811
inventory  Reserve request for 2 x book order 52811
inventory  Reserved 2 x book for order 52811, remaining 271
orders     Stock reserved for order 52811
orders     Calling payment to charge order 52811 amount 998.00
payment    Charging card for order 52811 amount 998.00
payment    Payment confirmed for order 52811
payment    Ledger entry written for order 52811
orders     Payment accepted for order 52811
orders     Order 52811 completed
gateway    Response sent with status 200 in 41 ms
```

Normal traffic also contains **rare-but-normal paths** on purpose, so the model learns they are fine:

| Path | How often | Lines it adds |
|---|---|---|
| Auth rejected | ~1% of users (ids 495–500) | `Auth rejected for user <n>` (WARN), status 401 |
| Card declined | ~1.5% | `Card declined…`, `Order … rejected: card declined`, stock released, status 402 |
| Out of stock | ~1.5% | `Insufficient stock…`, `Order … rejected: insufficient stock…`, status 409 |
| One payment retry | ~2% | `Payment processor busy…`, `Payment busy…`, `Retrying payment attempt 2…` |
| Restock | when stock < 10 | `Restocked <item> to <n> units` |

Drain turns these lines into **35 templates (event types)**. The model learned from about 37,000 healthy traces.

## Overview table

| ID | Name | What breaks | Target service | Error line in logs? | Kind of anomaly | Who should catch it |
|---|---|---|---|---|---|---|
| F1 | Slow payment | Payment takes 3 s; orders gives up after 2 s and retries | payment | yes | bad events + order | keyword ✔, our model ✔ (faster than vanilla) |
| F2 | Payment down | Payment container stopped | payment | yes | bad events | keyword ✔, health check ✔, model ✔ |
| F3 | Stock step skipped | Orders silently skips the inventory call | orders | **no** | **bad order** (a step is missing) | **only the sequence model** |
| F4 | Retry storm | Payment answers "busy" (503) half the time | payment | partly | **bad counts** (many retries) | model ✔, keyword only on some requests |
| F5 | DB exhaustion | Postgres paused; inventory queries time out | inventory | yes | bad events | keyword ✔, model ✔, health check ✘ |
| F6 | Inventory paused | Inventory container frozen | inventory | partly | bad events + missing steps | health check ✔, model ✔ |
| F7 | Bad deploy | New payment version rewords 2 log messages | payment | no (not a failure) | **not a fault**: tests false alarms | vanilla DeepLog ✘ (alarm flood), ours ✔ (stays quiet) |

F3 and F4 are the "silent" faults: no ERROR line, or almost none. They are the reason the project exists.

## F1 — Slow payment

**What breaks.** The payment service takes 3 seconds to answer every charge, like a slow external card gateway.

**How it is injected.** The injector calls `POST http://payment:8000/admin/fault {"mode": "slow"}`. Payment then sleeps 3 s inside `/charge`. The switch itself never logs anything.

**What the logs show.** Orders waits at most 2 s for payment, so for every request:

```text
orders   Calling payment to charge order 61021 amount 249.00
payment  Charging card for order 61021 amount 249.00
orders   Payment call timed out after 2003 ms for order 61021          (ERROR, new template)
orders   Retrying payment attempt 2 for order 61021
...      (up to 4 attempts)
orders   Order 61021 failed after 4 payment attempts                   (ERROR, new template)
orders   Calling inventory to release stock for order 61021
gateway  Orders service call failed: ReadTimeout                       (ERROR — gateway gave up at 8 s)
payment  Payment confirmed for order 61021                             (arrives late, after orders gave up)
```

**Who catches it.** It is error-visible, so keyword alerting fires too; that's fair, and we say so in the demo. Our step-wise model fires at the first `Payment call timed out` line. Vanilla DeepLog has to wait until the whole trace closes (about 9–10 s of retries). The error-rate threshold has to wait for its 60 s window to cross 10%. The health check never fires, because payment is alive, just slow.

**Restore.** The mode is set back to `none`.

## F2 — Payment down

**What breaks.** The payment service is completely gone, like a crashed pod.

**How it is injected.** `docker stop` on whichever payment container is serving (v1, or v2 during a deploy). Restore = `docker start` and wait for `/health`.

**What the logs show.**

```text
orders  Calling payment to charge order 61500 amount 45.00
orders  Payment service unreachable for order 61500: ConnectError     (ERROR, new template)
orders  Order 61500 failed after 1 payment attempts                   (ERROR)
orders  Calling inventory to release stock for order 61500
gateway Response sent with status 503 in 12 ms
```

Payment itself writes nothing (it's dead).

**Who catches it.** Keyword (ERROR lines), error-rate (every response is 503), and the health check (`/health` fails 3 times in a row, so it fires after about 30 s). The model sees a new ERROR template and a trace with no payment events.

## F3 — Stock step skipped (silent)

**What breaks.** A logic bug: orders forgets to reserve stock and still completes the order. Nothing crashes and every response is 200. In real life this sells items you don't have.

**How it is injected.** `POST http://orders:8000/admin/fault {"mode": "skip_reserve"}`. The `if` around the inventory call in `services/orders/app.py` is skipped.

**What the logs show.** Exactly the normal trace with four lines missing:

```text
orders     Created order 52811 for user 12
                                                  ← "Calling inventory to reserve…" missing
                                                  ← inventory "Reserve request…" / "Reserved…" missing
                                                  ← "Stock reserved for order…" missing
orders     Calling payment to charge order 52811 amount 998.00
...
gateway    Response sent with status 200 in 35 ms
```

**No ERROR, no timeout, no failed status.** The inventory box on the topology simply goes quiet.

**Who catches it.** Only a model that knows the **order** of events. After `Created order`, DeepLog predicts `Calling inventory to reserve` with probability ≈ 1.00. It sees `Calling payment` (probability ≈ 0.000) and fires:

```text
ALERT · trace 592e9ab0cb70 · orders · step 5
expected: E8 Calling inventory to reserve … p=1.00
observed: E10 Calling payment to charge order … p=0.000   → TRUE POSITIVE
```

Keyword, error-rate and health check all stay dark. **This is the money moment of the demo.**

## F4 — Retry storm

**What breaks.** The payment processor is overloaded and answers "busy" (503) for 50% of calls, instead of the normal ~2%.

**How it is injected.** `POST http://payment:8000/admin/fault {"mode": "retry_storm"}`.

**What the logs show.** Many requests now retry 2, 3 or 4 times:

```text
payment  Payment processor busy for order 70110, returning 503        (WARN)
orders   Payment busy for order 70110                                 (WARN)
orders   Retrying payment attempt 2 for order 70110
payment  Payment processor busy for order 70110, returning 503
orders   Retrying payment attempt 3 for order 70110
...
```

Every line here also happens in normal traffic. What is abnormal is **how many** of them there are. Only about 6% of requests fail all 4 attempts and print an ERROR (`Order … failed after 4 payment attempts`).

**Who catches it.** The sequence model: after one retry it expects success, not a second or third "busy". Count-based models also see it (a retry count far above normal). Keyword alerting catches only the few requests that fail completely.

## F5 — Database exhaustion

**What breaks.** Postgres stops answering, like a database whose connection pool is exhausted.

**How it is injected.** `docker pause` on the `db` container; restore = `docker unpause`. The ground-truth target is `inventory`, because that's the service whose behaviour changes.

**What the logs show.**

```text
inventory  Reserve request for 1 x pen order 80210
inventory  Database query failed for order 80210: TimeoutError        (ERROR, after 1.5 s)
orders     Inventory returned status 503 for order 80210              (ERROR)
gateway    Response sent with status 503 in 1530 ms
```

**Who catches it.** Keyword, error-rate and the model. The health check does **not**: inventory's `/health` is a liveness probe and doesn't touch the database, which is a realistic blind spot.

## F6 — Inventory paused

**What breaks.** The inventory service is frozen (a hung process): it doesn't crash, it just stops answering.

**How it is injected.** `docker pause` on the inventory container; restore = `docker unpause`.

**What the logs show.**

```text
orders   Calling inventory to reserve 3 x mug for order 81011
                                                  ← inventory writes nothing (frozen)
orders   Inventory call timed out after 2006 ms for order 81011       (ERROR)
gateway  Response sent with status 504 in 2010 ms
```

**Who catches it.** Health check (inventory `/health` times out), keyword and error-rate (ERROR lines and 504s), and the model (the expected `Reserve request` never comes; a timeout comes instead).

## F7 — Bad deploy (reworded logs)

**What happens.** A new version of payment is deployed. It **behaves exactly the same** but two of its six log messages were reworded by a developer:

| Old (v1, seen in training) | New (v2) |
|---|---|
| `Charging card for order <n> amount <x>` | `Charging customer card for order <n> with amount <x>` |
| `Payment confirmed for order <n>` | `Payment successfully confirmed for order <n>` |

v2 also has one **genuinely new ERROR** message, `Ledger write failed code <n> for order <n>`, which only appears while a real payment fault (F1, F4) is active.

**How it is injected.** The `payment-v2` container (image `logpulse-payment:v2`, built with `LOG_VARIANT=v2`, network alias `payment`) is started and the v1 container is stopped. Traffic moves to v2 without any request failing. Rollback does the reverse. F7 is recorded with type `deploy`, so it is **not** a fault; any alert it causes is a false alarm.

**What the logs show.** The same traces, with two unfamiliar sentences in every request.

**Who does what.**
- **Vanilla DeepLog** treats every unseen template as an anomaly, so it alerts on **every single request**: an alarm flood after a harmless deploy (the "unstable logs" problem).
- **Our model** runs each new template through the **semantic template matcher**: same service, same severity, TF-IDF cosine similarity ≥ τ = 0.6. Both rewordings map back to the old events, and the requests are scored normally. A genuinely new ERROR (`Ledger write failed…`) has low similarity to anything known, so it stays unmatched and is still flagged.

What the template library tab shows:

```text
E41  Charging customer card for order <NUM> with amount <NUM>   new → matched to E19 (0.855)
E42  Payment successfully confirmed for order <NUM>              new → matched to E20 (1.000)
```

## How a fault is injected and recorded

Three ways to trigger a fault. All go through the same injector (`chaos/inject.py`, the `chaos` container on port 9100):

| Way | Example |
|---|---|
| Dashboard button | Live tab → panel **7 · Fault control** → `F3 · Skip stock step` (auto-restores after 90 s; F7 stays until pressed again) |
| HTTP | `curl -X POST "http://localhost:9100/faults/F3?duration=60"` · end early: `curl -X POST http://localhost:9100/faults/F3/end` · everything: `curl -X POST http://localhost:9100/restore` |
| Script | `python scripts/demo.py` (fixed story) or `python chaos/schedule.py --seed 4 --runs 1 --duration 75 --gap 105` (random order) |

Every fault is **recorded by the injector itself, never by hand**:
1. At start, a row (`fault_id, type, target_service, start_ts`) is sent to the detector's `ground_truth` table.
2. At end, the row is completed with `end_ts` and also appended to `chaos/ground_truth.csv`.

## How a fault counts as detected

(Full rules: `src/logpulse/eval/live.py`, defined in [[14 - Metrics and Baselines]].)

- A fault is **detected** by a method if that method raises an alert between fault start and fault end + 30 s, and the alert **concerns the target**: same service, or its trace touched the target service. Error-rate alerts have no trace, so they count for any fault active at the time.
- **Time to detect (TTD)** = first such alert − fault start time written by the injector.
- An alert outside every fault window is a **false alarm**.
- A trace is labelled **anomalous** if it started during the fault window and touched the target service.

## Results from the quick demo run

Run `demo` (2026-10-22, `python scripts/demo.py`): 20 requests/s, F1 for 60 s → F3 for 60 s → F7 deploy for 160 s. Demo settings g = 9, p = 0.999, τ = 0.6 (full tuning still pending).

| Fault | Keyword (B1) | Error-rate (B2) | Health (B3) | Vanilla DeepLog | **Ours (step-wise + matcher + top-p)** |
|---|---|---|---|---|---|
| F1 slow payment | 3.6 s | 12.3 s | missed | 10.1 s | **4.5 s** |
| F3 stock step skipped | missed | missed | missed | 2.3 s | **2.3 s** |
| F7 deploy (no fault): alerts raised | 6 | — | — | **1,664** | **46** |

Lines a human must read: 10,009 raw lines in the F1 window → **37** lines attached to the alert; 9,426 → **12** for F3.

F2, F4, F5 and F6 are implemented and were exercised in a tuning run, but they are **not part of the quick demo**. Their numbers come from the full measurement protocol (not yet run with the fixed services), so none are quoted here.
