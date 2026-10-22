"""Online Drain3 parser: starts from the frozen training tree and keeps learning.

Event ids below the training vocabulary size are *known*; anything Drain creates after the
freeze is *unseen* and goes through the unseen-template policy (matcher / severity).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from logpulse.parsing.drain_parser import CachedMiner, make_miner

# Chosen by grouping accuracy on the demo app's own logs (train_demo.py); the frozen
# training tree carries its own value, this one only applies before a model exists.
DEMO_SIM_TH = 0.85


class OnlineParser:
    def __init__(self, art_dir: Path | None = None):
        state = art_dir / "drain_state.bin" if art_dir else None
        if state is not None and state.exists():
            miner = make_miner(state_path=state)
            miner.persistence_handler = None  # never write back into the frozen artifact
            tm = json.loads((art_dir / "template_map.json").read_text())
            self.vocab = int(tm["n_events"])
            self.version = tm.get("version", "unknown")
        else:
            miner = make_miner(sim_th=float(os.environ.get("DEMO_SIM_TH", DEMO_SIM_TH)))
            self.vocab = 0  # collect mode: nothing is "known" yet
            self.version = "none"
        self.cm = CachedMiner(miner)

    def parse(self, msg: str) -> tuple[int, str]:
        cid = self.cm.learn_masked(self.cm.mask(msg))
        return cid + 1, self.cm.miner.drain.id_to_cluster[cid].get_template()

    def is_known(self, eid: int) -> bool:
        return eid < self.vocab
