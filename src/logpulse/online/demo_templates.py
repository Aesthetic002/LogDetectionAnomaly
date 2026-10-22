"""Ground-truth templates of the demo app = its log statements (services/*/app.py).

Used for (a) parsing accuracy (GA) on demo logs, which picks the demo sim_th, and
(b) checking the semantic matcher after the F7 deploy: every v2 rewording has a known
v1 counterpart, so "mapped correctly" is computed, not hand-labelled.
"""
from __future__ import annotations

import re

STATEMENTS = [
    # (id, service, regex, v1-equivalent for v2 rewordings)
    ("G1", "gateway", r"Checkout request received for user \d+ item \w+ qty \d+", None),
    ("G2", "gateway", r"Auth rejected for user \d+", None),
    ("G3", "gateway", r"Auth ok for user \d+", None),
    ("G4", "gateway", r"Forwarding order to orders service", None),
    ("G5", "gateway", r"Orders service call failed: \w+", None),
    ("G6", "gateway", r"Response sent with status \d+ in \d+ ms", None),
    ("O1", "orders", r"Received order request from user \d+ for item \w+", None),
    ("O2", "orders", r"Created order \d+ for user \d+", None),
    ("O3", "orders", r"Calling inventory to reserve \d+ x \w+ for order \d+", None),
    ("O4", "orders", r"Inventory call timed out after \d+ ms for order \d+", None),
    ("O5", "orders", r"Inventory service unreachable for order \d+: \w+", None),
    ("O6", "orders", r"Order \d+ rejected: insufficient stock for \w+", None),
    ("O7", "orders", r"Inventory returned status \d+ for order \d+", None),
    ("O8", "orders", r"Stock reserved for order \d+", None),
    ("O9", "orders", r"Retrying payment attempt \d+ for order \d+", None),
    ("O10", "orders", r"Calling payment to charge order \d+ amount [\d.]+", None),
    ("O11", "orders", r"Payment call timed out after \d+ ms for order \d+", None),
    ("O12", "orders", r"Payment service unreachable for order \d+: \w+", None),
    ("O13", "orders", r"Payment accepted for order \d+", None),
    ("O14", "orders", r"Order \d+ completed", None),
    ("O15", "orders", r"Order \d+ rejected: card declined", None),
    ("O16", "orders", r"Payment busy for order \d+", None),
    ("O17", "orders", r"Payment returned status \d+ for order \d+", None),
    ("O18", "orders", r"Order \d+ failed after \d+ payment attempts", None),
    ("O19", "orders", r"Calling inventory to release stock for order \d+", None),
    ("O20", "orders", r"Stock release failed for order \d+", None),
    ("I1", "inventory", r"Reserve request for \d+ x \w+ order \d+", None),
    ("I2", "inventory", r"Insufficient stock for \w+: requested \d+, available \d+", None),
    ("I3", "inventory", r"Reserved \d+ x \w+ for order \d+, remaining -?\d+", None),
    ("I4", "inventory", r"Restocked \w+ to \d+ units", None),
    ("I5", "inventory", r"Database query failed for order \d+: \w+", None),
    ("I6", "inventory", r"Release request for order \d+", None),
    ("I7", "inventory", r"Released \d+ x \w+ for order \d+", None),
    ("P1", "payment", r"Charging card for order \d+ amount [\d.]+", None),
    ("P1v2", "payment", r"Charging customer card for order \d+ with amount [\d.]+", "P1"),
    ("P2v2", "payment", r"Ledger write failed code \d+ for order \d+", None),  # genuinely new ERROR
    ("P3", "payment", r"Payment processor busy for order \d+, returning 503", None),
    ("P4", "payment", r"Card declined for order \d+", None),
    ("P5", "payment", r"Payment confirmed for order \d+", None),
    ("P5v2", "payment", r"Payment successfully confirmed for order \d+", "P5"),
    ("P6", "payment", r"Ledger entry written for order \d+", None),
]
_COMPILED = [(sid, svc, re.compile(f"^{rx}$"), eq) for sid, svc, rx, eq in STATEMENTS]
V1_EQUIVALENT = {sid: eq for sid, _, _, eq in STATEMENTS if eq}


def statement_of(msg: str) -> str:
    for sid, _, rx, _ in _COMPILED:
        if rx.match(msg):
            return sid
    return "?"
