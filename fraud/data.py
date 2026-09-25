"""Streaming PaySim loader that produces leakage-safe train / validation / test splits.

* Rows are assigned to a split independently at random (70 / 10 / 20 %).
* Only the *training* split is re-balanced (all frauds, a random slice of legitimate rows).
  Validation and test keep the natural ~0.13 % fraud rate so every reported metric reflects
  what production would see.  ``beta`` (the legitimate-row keep rate) is stored so predicted
  probabilities can be corrected back to the natural prior.
* Recipient balances are unknown for merchant recipients (PaySim stores 0/0 for them) and
  are additionally hidden on a random share of training rows, so the model learns to cope
  with "recipient balance unknown" - exactly what the sandbox app sends.
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd

from .features import TRANSACTION_TYPES

RAW_COLUMNS = ["transaction_type", "amount", "oldbalanceOrg", "newbalanceOrig",
               "oldbalanceDest", "newbalanceDest", "hour_of_day"]
_NUMERIC = ["amount", "oldbalanceOrg", "newbalanceOrig", "oldbalanceDest", "newbalanceDest", "hour_of_day"]
SPLITS = ("train", "val", "test")


def raw_frame(arrays: dict, prefix: str) -> pd.DataFrame:
    frame = pd.DataFrame({c: arrays[f"{prefix}_{c}"] for c in _NUMERIC})
    frame.insert(0, "transaction_type", np.array(TRANSACTION_TYPES)[arrays[f"{prefix}_type"]])
    return frame[RAW_COLUMNS]


def prepare_paysim(csv_path: str | Path, out_path: str | Path, seed: int = 42, chunksize: int = 400_000,
                   shares: tuple[float, float, float] = (0.70, 0.10, 0.20), negatives_in_train: int = 320_000,
                   mask_dest_rate: float = 0.20) -> dict:
    rng = np.random.default_rng(seed)
    started = time.time()
    parts: dict[str, list[dict]] = {s: [] for s in SPLITS}
    neg_pool = 0  # legitimate rows that landed in the training pool
    rows_seen = 0
    frauds_seen = 0

    # First pass would be needed to know the exact pool size; PaySim is a fixed 6,362,620 rows,
    # so derive the keep-rate from the known negative count and adjust beta afterwards.
    expected_pool_negatives = 6_354_407 * shares[0]
    keep_rate = min(1.0, negatives_in_train / expected_pool_negatives)
    neg_kept = 0

    usecols = ["step", "type", "amount", "oldbalanceOrg", "newbalanceOrig", "nameDest",
               "oldbalanceDest", "newbalanceDest", "isFraud"]
    for chunk in pd.read_csv(csv_path, usecols=usecols, chunksize=chunksize):
        n = len(chunk)
        rows_seen += n
        frauds_seen += int(chunk["isFraud"].sum())
        y = chunk["isFraud"].to_numpy(dtype=np.int8)
        draw = rng.random(n)
        split = np.where(draw < shares[0], 0, np.where(draw < shares[0] + shares[1], 1, 2))

        merchant_dest = chunk["nameDest"].astype(str).str.startswith("M").to_numpy()
        old_d = chunk["oldbalanceDest"].to_numpy(dtype=np.float32).copy()
        new_d = chunk["newbalanceDest"].to_numpy(dtype=np.float32).copy()
        # Merchant recipients are genuinely unknown in every split.  Training additionally hides
        # recipient balances on a random share of rows (augmentation); val/test stay untouched.
        hide = merchant_dest | ((split == 0) & (rng.random(n) < mask_dest_rate))
        old_d[hide] = np.nan
        new_d[hide] = np.nan

        keep = np.ones(n, dtype=bool)
        train_neg = (split == 0) & (y == 0)
        neg_pool += int(train_neg.sum())
        drop = train_neg & (rng.random(n) >= keep_rate)
        keep &= ~drop
        neg_kept += int((train_neg & keep).sum())

        type_code = pd.Categorical(chunk["type"], categories=TRANSACTION_TYPES).codes.astype(np.int8)
        hour = (chunk["step"].to_numpy() % 24).astype(np.float32)
        for index, name in enumerate(SPLITS):
            take = (split == index) & keep
            if not take.any():
                continue
            parts[name].append({
                "type": type_code[take], "y": y[take],
                "amount": chunk["amount"].to_numpy(dtype=np.float32)[take],
                "oldbalanceOrg": chunk["oldbalanceOrg"].to_numpy(dtype=np.float32)[take],
                "newbalanceOrig": chunk["newbalanceOrig"].to_numpy(dtype=np.float32)[take],
                "oldbalanceDest": old_d[take], "newbalanceDest": new_d[take], "hour_of_day": hour[take],
            })
        print(f"  [{time.time() - started:6.0f}s] rows read: {rows_seen:,}", flush=True)

    arrays: dict[str, np.ndarray] = {}
    summary: dict = {"source": str(csv_path), "rows": rows_seen, "frauds": frauds_seen, "seed": seed}
    for name in SPLITS:
        merged = {k: np.concatenate([p[k] for p in parts[name]]) for k in parts[name][0]}
        for key, value in merged.items():
            arrays[f"{name}_{key}"] = value
        summary[name] = {"rows": int(len(merged["y"])), "frauds": int(merged["y"].sum())}
    beta = neg_kept / max(neg_pool, 1)
    arrays["beta"] = np.array([beta])
    summary["beta"] = float(beta)
    summary["train_negatives_in_pool"] = neg_pool
    summary["train_negatives_kept"] = neg_kept
    summary["mask_dest_rate"] = mask_dest_rate

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out_path, **arrays)
    (out_path.with_suffix(".json")).write_text(_json(summary))
    print(f"Saved {out_path} in {time.time() - started:.0f}s", flush=True)
    return summary


def _json(obj) -> str:
    import json
    return json.dumps(obj, indent=2)


def load_splits(path: str | Path) -> dict:
    data = np.load(path)
    arrays = {k: data[k] for k in data.files}
    out = {name: (raw_frame(arrays, name), arrays[f"{name}_y"].astype(int)) for name in SPLITS}
    out["beta"] = float(arrays["beta"][0])
    return out
