"""Train the three-layer system on the prepared PaySim splits and write ``models/``.

    python scripts/prepare_data.py          # once
    python scripts/train_pipeline.py        # full run
    python scripts/train_pipeline.py --quick --out models_quick   # fast smoke run on a small slice
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from fraud.data import load_splits  # noqa: E402
from fraud.training import log, train_system  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default=str(ROOT / "data" / "cache" / "paysim_splits.npz"))
    parser.add_argument("--out", default=str(ROOT / "models"))
    parser.add_argument("--quick", action="store_true", help="small slice + tiny search budgets (pipeline check only)")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    splits = load_splits(args.data)
    if args.quick:  # keep every fraud but few legitimate rows so the run finishes in minutes
        rng = np.random.default_rng(args.seed)
        for name, limit in (("train", 40_000), ("val", 60_000), ("test", 80_000)):
            raw, y = splits[name]
            keep = np.sort(np.concatenate([np.flatnonzero(y == 1), rng.choice(np.flatnonzero(y == 0), limit, replace=False)]))
            splits[name] = (raw.iloc[keep].reset_index(drop=True), y[keep])
        splits["beta"] = 1.0  # the slice is not a faithful prior; only the pipeline is being exercised

    system = train_system(splits, seed=args.seed, n_jobs=args.jobs, quick=args.quick)
    sizes = system.save(args.out)
    log(f"Saved artifacts to {args.out}: {sizes} (MB)")


if __name__ == "__main__":
    main()
