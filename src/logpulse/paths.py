"""Project paths. LOGPULSE_ROOT overrides the repo root (used inside containers)."""
import os
from pathlib import Path

ROOT = Path(os.environ.get("LOGPULSE_ROOT", Path(__file__).resolve().parents[2]))
CONFIGS = ROOT / "configs"
DATA = ROOT / "data"
RAW = DATA / "raw"
PROCESSED = DATA / "processed"
DEMO = DATA / "demo"
RUNS = DEMO / "runs"  # exported run DBs (read by host scripts)
# Where the detector writes live run DBs. In Docker this is a named volume: SQLite WAL is not
# coherent across the Docker Desktop VM <-> Windows bind-mount boundary.
LIVE_RUNS = Path(os.environ.get("LOGPULSE_LIVE_RUNS", RUNS))
ARTIFACTS = ROOT / "artifacts"
REPORTS = ROOT / "reports"
FIGURES = REPORTS / "figures"
RESULTS_CSV = REPORTS / "results.csv"
DRAIN_INI = CONFIGS / "drain3.ini"

# Event ID convention (note 08): 0 = PAD, 1 = UNSEEN, real templates from 2.
PAD = 0
UNSEEN = 1
FIRST_EVENT = 2
# Templates first mined in the test period (honest parse) get ids from here; models
# never see these ids directly — an unseen-template policy maps them first.
NOVEL_BASE = 1_000_000
