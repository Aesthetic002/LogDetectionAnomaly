"""Download Loghub HDFS_v1, BGL and the corrected Loghub-2k samples into data/raw/.

Every teammate runs this to get identical files; SHA-256 checksums go to data/README.md.

    python scripts/download_data.py            # everything
    python scripts/download_data.py --only 2k  # just the 2k samples
"""
import argparse
import hashlib
import shutil
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"

ZENODO = "https://zenodo.org/records/8196385/files/{}?download=1"
LOGPARSER = "https://raw.githubusercontent.com/logpai/logparser/main/data"

FULL = {
    "HDFS_v1.zip": RAW / "HDFS_v1",
    "BGL.zip": RAW / "BGL",
}
TWO_K = {
    f"{LOGPARSER}/loghub_2k/HDFS/HDFS_2k.log": RAW / "loghub-2k" / "HDFS_2k.log",
    f"{LOGPARSER}/loghub_2k_corrected/HDFS/HDFS_2k.log_structured_corrected.csv":
        RAW / "loghub-2k" / "HDFS_2k.log_structured.csv",
    f"{LOGPARSER}/loghub_2k/BGL/BGL_2k.log": RAW / "loghub-2k" / "BGL_2k.log",
    f"{LOGPARSER}/loghub_2k_corrected/BGL/BGL_2k.log_structured_corrected.csv":
        RAW / "loghub-2k" / "BGL_2k.log_structured.csv",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  have {dest.relative_to(ROOT)}")
        return dest
    print(f"  get  {url}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f, length=1 << 20)
    tmp.rename(dest)
    return dest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["2k", "full"], default=None)
    args = ap.parse_args()

    sums = {}
    if args.only in (None, "2k"):
        for url, dest in TWO_K.items():
            fetch(url, dest)
            sums[dest] = sha256(dest)
    if args.only in (None, "full"):
        for name, out_dir in FULL.items():
            z = fetch(ZENODO.format(name), RAW / name)
            sums[z] = sha256(z)
            if not out_dir.exists():
                print(f"  unzip {name}")
                with zipfile.ZipFile(z) as zf:
                    zf.extractall(out_dir)

    readme = ROOT / "data" / "README.md"
    lines = ["# Data", "", "Raw data is gitignored. Recreate with `python scripts/download_data.py`.", "",
             "| File | SHA-256 |", "|---|---|"]
    lines += [f"| `{p.relative_to(ROOT).as_posix()}` | `{s}` |" for p, s in sums.items()]
    readme.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("checksums ->", readme.relative_to(ROOT))


if __name__ == "__main__":
    main()
