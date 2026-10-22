---
tags: [aiml, el-project, log-anomaly-detection, models, deeplog, lstm, sklearn]
created: 2026-10-22
updated: 2026-10-22
status: reference + build guide
---

# Models

Related: [[00 - Project Hub]] · [[04 - Log Parsing with Drain]] · [[07 - Evaluation Plan]]

## Table of Contents

- [[#Model lineup|Model lineup]]
- [[#Syllabus mapping|Syllabus mapping]]
- [[#Features for classical models|Features for classical models]]
- [[#Supervised baselines|Supervised baselines]]
- [[#Unsupervised baselines|Unsupervised baselines]]
- [[#DeepLog — the sequence model|DeepLog — the sequence model]]
- [[#DeepLog dry run|DeepLog dry run]]
- [[#DeepLog code skeleton|DeepLog code skeleton]]
- [[#Handling unseen templates|Handling unseen templates]]
- [[#Our modifications to DeepLog|Our modifications to DeepLog]]
- [[#Hyperparameters to tune|Hyperparameters to tune]]
- [[#Stretch models|Stretch models]]

## Model lineup

| Model | Family | Labels needed | Input | Captures order? | Role |
|---|---|---|---|---|---|
| Logistic Regression | Supervised | Both classes | Count vector | No | Simple strong baseline |
| Decision Tree | Supervised | Both | Count vector | No | Interpretable — "which event decides" |
| Naive Bayes (Multinomial) | Supervised | Both | Count vector | No | Fast probabilistic baseline |
| Random Forest | Supervised (ensemble) | Both | Count vector | No | Usually best classical model |
| PCA | Unsupervised | None | Count vector | No | Classic Xu et al. (SOSP 2009) method |
| Isolation Forest | Unsupervised | None | Count vector | No | Modern unsupervised baseline |
| **DeepLog (LSTM)** | Semi-supervised | Normal only | Event sequence | **Yes** | Main model |

The story for the report: *supervised models do great when you have labels, unsupervised ones need none but are weaker, DeepLog needs only normal data and catches ordering anomalies — and here's how each holds up under an honest chronological split.*

## Syllabus mapping

AI/ML course (IS353IA) — from the unit outline used for SentinelDB:

| Unit | Topic | Where it shows up here |
|---|---|---|
| III | Decision Tree, overfitting, model selection with a validation set | DT baseline; depth tuned on a validation slice; overfitting curve (train vs val F1 vs depth) |
| IV | Naive Bayes, Logistic Regression | Both are baselines |
| IV | Ensembles — bagging, boosting, Random Forest | Random Forest (+ optional gradient boosting) |
| V | K-means, cluster evaluation | Optional: cluster sessions, flag points far from all centroids; or cluster templates |
| — | LSTM / deep learning | **Beyond syllabus** — DeepLog. Confirm with guide; present it as the advanced contribution |

## Features for classical models

**Event count matrix** — one row per session/window, one column per template:

```python
import numpy as np
from scipy.sparse import csr_matrix

def count_matrix(sequences, n_events):
    rows, cols, vals = [], [], []
    for i, seq in enumerate(sequences):
        ids, counts = np.unique(seq, return_counts=True)
        rows += [i] * len(ids); cols += list(ids); vals += list(counts)
    return csr_matrix((vals, (rows, cols)), shape=(len(sequences), n_events))
```

Variants worth comparing (cheap, and a good small ablation):
- raw counts
- TF-IDF weighting (`sklearn.feature_extraction.text.TfidfTransformer`)
- binary presence (did event E appear at all?)
- + session length as an extra feature

Fit any scaler/TF-IDF on **train only**.

## Supervised baselines

```python
from sklearn.linear_model import LogisticRegression
from sklearn.tree import DecisionTreeClassifier
from sklearn.naive_bayes import MultinomialNB
from sklearn.ensemble import RandomForestClassifier

models = {
    "LR": LogisticRegression(max_iter=2000, class_weight="balanced"),
    "DT": DecisionTreeClassifier(max_depth=10, class_weight="balanced"),
    "NB": MultinomialNB(),
    "RF": RandomForestClassifier(n_estimators=300, class_weight="balanced", n_jobs=-1),
}
for name, m in models.items():
    m.fit(X_train, y_train)
    y_pred = m.predict(X_test)
    # -> precision, recall, F1 (see Evaluation Plan)
```

- Classes are imbalanced (~3% anomalies in HDFS) → `class_weight="balanced"` and report precision/recall, never just accuracy.
- Plot the Decision Tree's top levels — "if count(E7) > 0 → anomaly" is a great report/viva figure.
- Random Forest feature importances → "which templates matter most".

## Unsupervised baselines

**PCA** (Xu et al., SOSP 2009): project count vectors onto the top-k principal components (the "normal subspace"); the leftover part's size (squared prediction error, SPE) is the anomaly score. High SPE → anomaly.

```python
from sklearn.decomposition import PCA
pca = PCA(n_components=0.95).fit(X_train_normal_dense)
recon = pca.inverse_transform(pca.transform(X_test_dense))
spe = ((X_test_dense - recon) ** 2).sum(axis=1)
threshold = np.percentile(spe_val_normal, 99)   # chosen on validation
```

**Isolation Forest**: anomalies are easier to isolate with random splits.

```python
from sklearn.ensemble import IsolationForest
iso = IsolationForest(n_estimators=300, contamination="auto", random_state=0).fit(X_train)
y_pred = (iso.predict(X_test) == -1).astype(int)
```

## DeepLog — the sequence model

Paper: Du, Li, Zheng, Srikumar — *"DeepLog: Anomaly Detection and Diagnosis from System Logs through Deep Learning"*, ACM CCS 2017. Reported F1 ≈ 0.96 on HDFS.

**Idea:** treat a session as a "sentence" of event IDs. Train an LSTM on **normal** sessions to predict the next event from the previous `h` events. At detection time, an event is anomalous if it is **not among the top-`g` predictions**. A session is anomalous if any of its events is.

**Architecture** (paper defaults: `h = 10`, `g = 9`, 2 LSTM layers, 64 hidden units):

```
event IDs (window of h) → Embedding (or one-hot) → LSTM ×2 (64) → Linear → softmax over n_events
```

**Training data:** for each normal session `[e1 … en]`, pad the start with `h` PAD tokens, then every position gives one training pair: `(previous h events) → next event`.

**Why top-g and not top-1?** Normal behaviour is often branchy — after "block received", either "packet responder terminating" or "deleting block" can be normal. Requiring the exact next event would flood you with false alarms. `g` controls the trade-off: larger `g` → fewer false alarms, more missed anomalies.

**Bonus for explainability:** when it fires, you know *exactly which step* broke and *what was expected instead* — that's the dashboard's alert text.

## DeepLog dry run

Templates in the demo app:

| ID | Template |
|---|---|
| E1 | `Received order request <*>` |
| E2 | `Reserved stock for item <*>` |
| E3 | `Charging card for order <*> amount <*>` |
| E4 | `Payment confirmed for order <*>` |
| E5 | `Order <*> completed` |
| E6 | `Gateway timeout after <*> ms` |
| E7 | `Retrying payment attempt <*>` |

Normal training sessions mostly look like `E1 E2 E3 E4 E5`, sometimes `E1 E2 E3 E7 E3 E4 E5` (one retry is normal).

Use `h = 2`, `g = 2` for the dry run.

Test session: `E1 E2 E3 E6 E7 E3 E6 E7 E3 E6`

| Step | Window (last 2) | Model's top-2 guesses | Actual | In top-2? |
|---|---|---|---|---|
| 1 | PAD PAD | E1, — | E1 | ✔ |
| 2 | PAD E1 | E2, — | E2 | ✔ |
| 3 | E1 E2 | E3, — | E3 | ✔ |
| 4 | E2 E3 | E4, E7 | **E6** | ✘ → **anomaly at step 4** |

Alert: *"after `Reserved stock` → `Charging card`, expected `Payment confirmed` or `Retrying payment`, but saw `Gateway timeout`."*

Notice: no "ERROR" keyword was needed — and the same model would also catch `E1 E3 E4 E5` (stock never reserved), which contains no error line at all. A count-based model may miss that if E2 is cheap to skip; the sequence model doesn't.

## DeepLog code skeleton

`src/logpulse/models/deeplog.py`:

```python
import torch, torch.nn as nn
from torch.utils.data import Dataset, DataLoader

PAD = 0  # reserve 0 for padding, 1 for UNSEEN; real templates start at 2

class WindowDataset(Dataset):
    def __init__(self, sessions, h):
        self.x, self.y = [], []
        for s in sessions:
            seq = [PAD] * h + list(s)
            for i in range(h, len(seq)):
                self.x.append(seq[i - h:i]); self.y.append(seq[i])
        self.x = torch.tensor(self.x); self.y = torch.tensor(self.y)
    def __len__(self): return len(self.y)
    def __getitem__(self, i): return self.x[i], self.y[i]

class DeepLog(nn.Module):
    def __init__(self, n_events, emb=32, hidden=64, layers=2):
        super().__init__()
        self.emb = nn.Embedding(n_events, emb, padding_idx=PAD)
        self.lstm = nn.LSTM(emb, hidden, layers, batch_first=True)
        self.fc = nn.Linear(hidden, n_events)
    def forward(self, x):
        out, _ = self.lstm(self.emb(x))
        return self.fc(out[:, -1, :])

def train(model, sessions, h=10, epochs=10, lr=1e-3, bs=2048, device="cpu"):
    dl = DataLoader(WindowDataset(sessions, h), batch_size=bs, shuffle=True)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    loss_fn = nn.CrossEntropyLoss()
    model.to(device).train()
    for ep in range(epochs):
        total = 0
        for x, y in dl:
            x, y = x.to(device), y.to(device)
            opt.zero_grad(); loss = loss_fn(model(x), y); loss.backward(); opt.step()
            total += loss.item() * len(y)
        print(f"epoch {ep}: loss {total / len(dl.dataset):.4f}")

@torch.no_grad()
def detect(model, session, h=10, g=9, device="cpu"):
    """Return (is_anomaly, first_bad_step, expected_topg, actual)."""
    model.eval()
    seq = [PAD] * h + list(session)
    for i in range(h, len(seq)):
        actual = seq[i]
        if actual == 1:                              # UNSEEN template
            return True, i - h, [], actual
        x = torch.tensor([seq[i - h:i]], device=device)
        topg = model(x).topk(g, dim=1).indices[0].tolist()
        if actual not in topg:
            return True, i - h, topg, actual
    return False, None, None, None
```

Speed-up for evaluation: batch all windows of all test sessions at once instead of the per-step loop above, then group results by session. HDFS training fits on a CPU (tiny model); use Colab GPU if epochs are slow.

## Handling unseen templates

Templates that never appeared in training (new deployment, rare path) are a real-world problem — the ICSE 2022 study calls it **unstable logs**. Options, compare at least two:

1. **Always anomalous** (DeepLog default) — high recall, more false alarms after code changes.
2. **Ignore** unseen events — fewer false alarms, misses brand-new error messages.
3. **Severity-aware** — unseen + level `WARN/ERROR` → anomaly; unseen + `INFO` → log it and add to the "review" queue.
4. **Online update** — the operator marks a flagged session as normal → append to training data → periodic fine-tune.
5. **Semantic template matcher (our improvement)** — map a new template to the most similar known template in the same service and log level; only unmatched WARN/ERROR templates are anomalous. Full design and experiment: [[15 - Our Improvements#Improvement 1 — Semantic template matcher|Improvement 1]].

## Our modifications to DeepLog

Vanilla DeepLog (above) is the baseline. Our version adds three changes, each evaluated separately in [[15 - Our Improvements]]:

| Change | Replaces | Goal |
|---|---|---|
| Semantic template matcher | "unseen = anomaly" | Fewer false alarms after deployments |
| Adaptive top-p acceptance set | Fixed top-g (g = 9) | Better precision/recall, esp. on BGL |
| Step-wise online scoring | Scoring after the session closes | Lower time to detect |

```python
# adaptive top-p decision rule (drop-in replacement for the top-g check in detect())
probs = torch.softmax(model(x), dim=-1)[0]
sorted_p, order = probs.sort(descending=True)
k = int((sorted_p.cumsum(0) < p).sum()) + 1
if actual not in order[:k].tolist():
    return True, i - h, order[:k].tolist(), actual
```

## Hyperparameters to tune

| Param | Values to try | Effect |
|---|---|---|
| `h` (window) | 5, 10, 20 | Longer context vs. fewer training pairs from short sessions |
| `g` (top-g) | 1–15 | Main precision/recall knob — plot F1 vs g |
| hidden size | 32, 64, 128 | Capacity |
| layers | 1, 2 | Usually 2 is enough |
| epochs | until val loss flattens | Stop early on a normal-only validation set |
| BGL window | 20 / 100 lines, 1 h time | Different granularity, different results |

## Stretch models

Pick at most one, only after the main results table exists:
- **LSTM autoencoder** — reconstruct the whole sequence; high reconstruction error → anomaly.
- **LogAnomaly** (IJCAI 2019) — adds template semantics (word vectors) so similar templates share knowledge; more robust to unstable logs.
- **LogBERT** (2021) — transformer with masked-event prediction.
- **Gradient boosting** (XGBoost/LightGBM) — likely the strongest supervised baseline; syllabus Unit IV "boosting".
