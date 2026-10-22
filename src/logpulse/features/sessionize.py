"""Sessions: HDFS by block ID (offline) and demo-app traces by trace_id (online / training)."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from logpulse.paths import PROCESSED


@dataclass
class SessionSet:
    """A list of event-id sequences with labels and a time key for chronological splits."""
    seqs: list[np.ndarray]
    labels: np.ndarray
    time_key: np.ndarray
    ids: np.ndarray | None = None
    # per-event side info aligned with seqs (used by the template matcher); optional
    components: list[np.ndarray] | None = None
    levels: list[np.ndarray] | None = None
    meta: dict = field(default_factory=dict)

    def __len__(self):
        return len(self.seqs)

    def subset(self, idx) -> "SessionSet":
        idx = np.asarray(idx)
        pick = lambda xs: [xs[i] for i in idx] if xs is not None else None  # noqa: E731
        return SessionSet(pick(self.seqs), self.labels[idx], self.time_key[idx],
                          self.ids[idx] if self.ids is not None else None,
                          pick(self.components), pick(self.levels), self.meta)


def _list_column(table, name) -> list[np.ndarray]:
    col = table.column(name).combine_chunks()
    offsets = col.offsets.to_numpy()
    values = col.values.to_numpy()
    return [values[offsets[i]:offsets[i + 1]] for i in range(len(offsets) - 1)]


def load_hdfs(mode: str = "honest") -> SessionSet:
    """mode: 'honest' (fit-on-train parse) or 'full' (parser saw everything)."""
    t = pq.read_table(PROCESSED / "hdfs" / "sessions.parquet")
    return SessionSet(
        seqs=_list_column(t, f"seq_{mode}"),
        labels=t.column("label").to_numpy().astype(np.int8),
        time_key=t.column("first_ts").to_numpy(),
        ids=np.array(t.column("BlockId").to_pylist(), dtype=object),
        meta={"dataset": "hdfs", "mode": mode},
    )


def trace_sessions(events: pd.DataFrame, eid_col: str = "event_id") -> pd.DataFrame:
    """Group parsed demo-app events into one ordered sequence per trace_id.

    ``events`` needs: trace_id, ts (sortable), seq (arrival order tie-break), service, eid_col.
    Returns one row per trace: trace_id, start_ts, end_ts, events (np.ndarray), services (set).
    """
    ev = events[events["trace_id"].notna() & (events["trace_id"] != "-")]
    ev = ev.sort_values(["trace_id", "ts", "seq"], kind="stable")
    rows = []
    for tid, g in ev.groupby("trace_id", sort=False):
        rows.append((tid, g["ts"].iloc[0], g["ts"].iloc[-1], g[eid_col].to_numpy(),
                     set(g["service"].unique())))
    return pd.DataFrame(rows, columns=["trace_id", "start_ts", "end_ts", "events", "services"])
