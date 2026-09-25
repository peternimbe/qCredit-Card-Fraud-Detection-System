"""Stream paysim.csv into compact train/val/test splits (run once; ~minutes, low memory).

    python scripts/prepare_data.py [--csv paysim.csv] [--out data/cache/paysim_splits.npz]
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fraud.data import prepare_paysim  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", default=str(ROOT / "paysim.csv"))
    parser.add_argument("--out", default=str(ROOT / "data" / "cache" / "paysim_splits.npz"))
    parser.add_argument("--negatives", type=int, default=320_000, help="legitimate rows kept in the training split")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    summary = prepare_paysim(args.csv, args.out, seed=args.seed, negatives_in_train=args.negatives)
    print(summary)


if __name__ == "__main__":
    main()
