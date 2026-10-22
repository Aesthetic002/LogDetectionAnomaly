---
tags: [aiml, el-project, log-anomaly-detection, drain, parsing]
created: 2026-10-22
updated: 2026-10-22
status: reference + build guide
---

# Log Parsing with Drain

Related: [[00 - Project Hub]] · [[01 - Concepts Explained Simply]] · [[03 - Datasets]]

Paper: He, Zhu, Zheng, Lyu — *"Drain: An Online Log Parsing Approach with Fixed Depth Tree"*, ICWS 2017.

## Table of Contents

- [[#What parsing must achieve|What parsing must achieve]]
- [[#The algorithm in five steps|The algorithm in five steps]]
- [[#Dry run with four lines|Dry run with four lines]]
- [[#The threshold lesson from the dry run|The threshold lesson from the dry run]]
- [[#Drain3 — the library we use|Drain3 — the library we use]]
- [[#Config file|Config file]]
- [[#Code skeleton|Code skeleton]]
- [[#Measuring parsing accuracy|Measuring parsing accuracy]]
- [[#Pitfalls|Pitfalls]]
- [[#Checklist|Checklist]]

## What parsing must achieve

Input: `Received block blk_-695 of size 67108864 from /10.251.42.84`
Output: template `Received block <*> of size <*> from <*>` → `E5`, parameters `[blk_-695, 67108864, /10.251.42.84]`.

It must be **fast** (millions of lines), **online** (handle lines one at a time, as they arrive), and **accurate** (same code statement → same template; different statements → different templates).

## The algorithm in five steps

Drain keeps a tree of fixed depth. Each leaf holds a list of *log groups* (each group = one template).

1. **Preprocess** — regex-mask obvious variables (IPs, block IDs, numbers, hex, UUIDs) to `<IP>`, `<NUM>` etc. Cheap and hugely helpful.
2. **Split** into tokens on whitespace (plus any extra delimiters).
3. **Layer 1: length** — go to the child for "number of tokens = n". Lines from the same print statement almost always have the same length.
4. **Layers 2..depth-1: leading tokens** — follow the child for the 1st token, then the 2nd, …. If a token contains a digit, go to the `<*>` child instead (it's probably a variable). `max_children` caps the branching; overflow goes to `<*>`.
5. **Leaf: similarity match** — compare the line with each group's template:

   `sim = (number of positions where token == template token, excluding <*>) / length`

   - If the best `sim ≥ sim_th` → join that group, and replace every differing position in the template with `<*>`.
   - Else → create a new group with the line itself as its template.

Each line touches one root-to-leaf path and a few comparisons, so parsing is close to linear in the number of lines.

## Dry run with four lines

Masking: numbers → `<NUM>`, IPs → `<IP>`. `sim_th = 0.4`. Note: Drain3 doesn't count `<*>` positions as matches.

**Line 1:** `Connected to server 10.0.0.1 in 23 ms`
→ masked: `Connected to server <IP> in <NUM> ms` (7 tokens)
→ path: length 7 → first token `Connected` → empty leaf → **new group G1**: `Connected to server <IP> in <NUM> ms`

**Line 2:** `User alice logged in`
→ 4 tokens → `User` → empty leaf → **new group G2**: `User alice logged in`

**Line 3:** `User bob logged in`
→ 4 tokens → `User` → leaf has G2
→ compare with `User alice logged in`: User ✔, bob≠alice ✘, logged ✔, in ✔ → 3/4 = **0.75 ≥ 0.4** → join G2
→ template becomes `User <*> logged in`

**Line 4:** `User bob logged out`
→ 4 tokens → `User` → leaf has G2 = `User <*> logged in`
→ User ✔, `<*>` (not counted), logged ✔, out≠in ✘ → 2/4 = **0.5 ≥ 0.4** → join G2
→ template becomes `User <*> logged <*>` ← **wrong!** "logged in" and "logged out" are different events.

## The threshold lesson from the dry run

With `sim_th = 0.6`, line 4 scores 0.5 < 0.6 → its own group `User bob logged out` → correct. Short templates are the most fragile: one differing word is 25% of a 4-token line.

So `sim_th` is a real hyperparameter. Tune it on Loghub-2k (where ground truth exists) and report the curve "parsing accuracy vs sim_th" — that's a nice small experiment and a report figure.

## Drain3 — the library we use

`pip install drain3` (maintained fork from IBM, under the logpai GitHub org). Adds what the original paper lacked:

- **Masking rules** in config (regex → `<IP>`, `<NUM>`, …).
- **Persistence** — save/restore the tree to a file, Redis or Kafka, so the online parser survives restarts.
- **`match()`** — look up a line against existing templates *without* learning from it. Use this at test time to detect **unseen templates** honestly.
- `max_clusters` with LRU eviction to bound memory.

Defaults: `sim_th = 0.4`, `depth = 4` (minimum 3), `max_children = 100`, `max_clusters` unlimited. Each `add_log_message()` returns `change_type`, `cluster_id`, `cluster_size`, `cluster_count`, `template_mined`.

## Config file

`configs/drain3.ini`:

```ini
[MASKING]
masking = [
    {"regex_pattern": "blk_-?\\d+", "mask_with": "BLK"},
    {"regex_pattern": "((?<=[^A-Za-z0-9])|^)(\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}\\.\\d{1,3})(:\\d+)?((?=[^A-Za-z0-9])|$)", "mask_with": "IP"},
    {"regex_pattern": "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "mask_with": "UUID"},
    {"regex_pattern": "0x[0-9a-fA-F]+", "mask_with": "HEX"},
    {"regex_pattern": "((?<=[^A-Za-z0-9])|^)([\\-\\+]?\\d+(\\.\\d+)?)((?=[^A-Za-z0-9])|$)", "mask_with": "NUM"}
    ]
mask_prefix = <
mask_suffix = >

[DRAIN]
sim_th = 0.5
depth = 4
max_children = 100
extra_delimiters = ["=", ","]

[SNAPSHOT]
snapshot_interval_minutes = 10
compress_state = True
```

Order matters: mask block IDs and IPs **before** the generic number rule.

## Code skeleton

`src/logpulse/parsing/drain_parser.py`:

```python
import re
import pandas as pd
from drain3 import TemplateMiner
from drain3.template_miner_config import TemplateMinerConfig
from drain3.file_persistence import FilePersistence

HDFS_RE = re.compile(r"^(\d{6}) (\d{6}) (\d+) (\w+) ([\w.$]+): (.*)$")

def make_miner(cfg_path="configs/drain3.ini", state_path=None):
    cfg = TemplateMinerConfig()
    cfg.load(cfg_path)
    persistence = FilePersistence(state_path) if state_path else None
    return TemplateMiner(persistence, cfg)

def parse_hdfs(log_path, out_path, cfg_path="configs/drain3.ini"):
    miner = make_miner(cfg_path)
    rows = []
    with open(log_path, errors="ignore") as f:
        for line_id, line in enumerate(f):
            m = HDFS_RE.match(line.strip())
            if not m:
                continue
            date, time, pid, level, component, content = m.groups()
            r = miner.add_log_message(content)
            rows.append((line_id, date, time, level, component, content, r["cluster_id"]))
    df = pd.DataFrame(rows, columns=["LineId", "Date", "Time", "Level",
                                     "Component", "Content", "EventId"])
    df.to_parquet(out_path)
    templates = {c.cluster_id: c.get_template() for c in miner.drain.clusters}
    pd.Series(templates, name="EventTemplate").to_csv(out_path.replace(".parquet", "_templates.csv"))
    return df
```

At test/online time for a frozen model:

```python
cluster = miner.match(content)          # does not modify the tree
event_id = cluster.cluster_id if cluster else UNSEEN_ID
```

## Measuring parsing accuracy

**Grouping Accuracy (GA)** — the standard Loghub metric: a line counts as correctly parsed only if the *set of lines* in its predicted group is exactly the set of lines in its true group.

```python
def grouping_accuracy(true_ids, pred_ids):
    df = pd.DataFrame({"t": true_ids, "p": pred_ids})
    correct = 0
    for p, grp in df.groupby("p"):
        t_vals = grp["t"].unique()
        if len(t_vals) == 1 and (df["t"] == t_vals[0]).sum() == len(grp):
            correct += len(grp)
    return correct / len(df)
```

Report GA on HDFS-2k and BGL-2k for `sim_th ∈ {0.3, 0.4, 0.5, 0.6, 0.7}`, with and without masking.

## Pitfalls

- **Forgetting the header.** Parse only the *message* part, not timestamps/PIDs — otherwise every line is "unique".
- **Over-merging** short templates (the dry run above) → raise `sim_th` or add domain masks.
- **Under-merging** when a variable sits in the first tokens (e.g. `node-17 started`) → mask it, or Drain sends it down different branches.
- **Training/test leakage via the parser.** If you parse the whole dataset at once, the parser has "seen" test-time templates. For the honest experiment, fit Drain on the training period, then `match()` the test period, mapping unknown lines to `UNSEEN`.
- **Template IDs change between runs** — save the `templates.csv` mapping together with the model.

## Checklist

- [ ] Write `drain3.ini` with masks for HDFS, BGL and the demo app.
- [ ] Parse HDFS-2k and BGL-2k, compute GA, tune `sim_th`.
- [ ] Parse full HDFS and BGL → `data/processed/`.
- [ ] Save template tables; eyeball the top 30 templates for obvious mistakes.
- [ ] Implement the "fit on train, match on test" mode.
- [ ] Throughput test: lines/second on a laptop (report it).
