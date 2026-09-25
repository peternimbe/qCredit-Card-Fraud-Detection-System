"""Named feature contract shared by training and serving.

Every model input is a *named, human-readable* quantity (balances, amount,
transaction type, hour of day, ...) or a value derived from those in plain
arithmetic (e.g. "the sender's balance does not add up").  Nothing is a PCA
component, so any explanation can be shown to a security analyst as-is.

The same ``engineer_features`` function is used to build the training matrix
from PaySim and to score a live transaction from the sandbox app, which is what
guarantees the two sides can never drift apart.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

TRANSACTION_TYPES = ["CASH_IN", "CASH_OUT", "DEBIT", "PAYMENT", "TRANSFER"]

# Words the sandbox / other clients may use for a transaction type.
TYPE_ALIASES = {
    "SEND": "TRANSFER", "WIRE": "TRANSFER", "TRANSFER": "TRANSFER", "BANK_TRANSFER": "TRANSFER",
    "WITHDRAW": "CASH_OUT", "WITHDRAWAL": "CASH_OUT", "CASH_OUT": "CASH_OUT", "CASHOUT": "CASH_OUT", "ATM": "CASH_OUT",
    "DEPOSIT": "CASH_IN", "TOPUP": "CASH_IN", "TOP_UP": "CASH_IN", "CASH_IN": "CASH_IN", "CASHIN": "CASH_IN",
    "PAY": "PAYMENT", "PAYMENT": "PAYMENT", "POS": "PAYMENT", "PURCHASE": "PAYMENT", "ONLINE": "PAYMENT",
    "DEBIT": "DEBIT",
}

# Model input columns, in the exact order the models were trained on.
FEATURE_NAMES = [
    "amount",
    "oldbalanceOrg",
    "newbalanceOrig",
    "oldbalanceDest",
    "newbalanceDest",
    "dest_balance_known",
    "hour_of_day",
    "is_night",
    "orig_balance_error",
    "dest_balance_error",
    "amount_to_balance_ratio",
    "orig_drained",
    "amount_exceeds_balance",
    "dest_empty_before",
    "dest_unchanged",
    "type_CASH_OUT",
    "type_DEBIT",
    "type_PAYMENT",
    "type_TRANSFER",
]

# Columns with a heavy-tailed money scale; signed log1p before standardising.
MONEY_COLUMNS = [
    "amount", "oldbalanceOrg", "newbalanceOrig", "oldbalanceDest", "newbalanceDest",
    "orig_balance_error", "dest_balance_error",
]

FEATURE_LABELS = {
    "amount": "Transaction amount",
    "oldbalanceOrg": "Sender balance before",
    "newbalanceOrig": "Sender balance after",
    "oldbalanceDest": "Recipient balance before",
    "newbalanceDest": "Recipient balance after",
    "dest_balance_known": "Recipient balance available",
    "hour_of_day": "Hour of day",
    "is_night": "Night-time transaction",
    "orig_balance_error": "Sender balance mismatch",
    "dest_balance_error": "Recipient balance mismatch",
    "amount_to_balance_ratio": "Share of balance being moved",
    "orig_drained": "Account emptied",
    "amount_exceeds_balance": "Amount exceeds available balance",
    "dest_empty_before": "Recipient account was empty",
    "dest_unchanged": "Recipient balance did not change",
    "type_CASH_OUT": "Transaction type: cash-out / withdrawal",
    "type_DEBIT": "Transaction type: debit",
    "type_PAYMENT": "Transaction type: payment",
    "type_TRANSFER": "Transaction type: transfer",
}

# Named inputs a client may send, with accepted aliases (first match wins).
INPUT_ALIASES = {
    "transaction_type": ["transaction_type", "type", "transactionType"],
    "amount": ["amount", "Amount"],
    "oldbalanceOrg": ["oldbalanceOrg", "balance_before", "sender_balance_before"],
    "newbalanceOrig": ["newbalanceOrig", "balance_after", "sender_balance_after"],
    "oldbalanceDest": ["oldbalanceDest", "destination_balance_before", "recipient_balance_before"],
    "newbalanceDest": ["newbalanceDest", "destination_balance_after", "recipient_balance_after"],
    "hour_of_day": ["hour_of_day", "time_hour", "hour"],
    "timestamp": ["timestamp", "device_time_ms"],
    "device_timezone_offset_minutes": ["device_timezone_offset_minutes"],
}

# Optional behavioural / location context (rule layer, see fraud.context).
CONTEXT_FIELDS = [
    "country", "impossible_travel_flag", "location_change_distance_km", "is_new_device",
    "is_new_beneficiary", "tx_count_24h", "rapid_withdrawal_count", "location_available",
]


def signed_log1p(values: np.ndarray) -> np.ndarray:
    return np.sign(values) * np.log1p(np.abs(values))


def _to_float(value: Any) -> float:
    if value is None or value == "":
        return float("nan")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return number if math.isfinite(number) else float("nan")


def normalize_payload(payload: dict) -> tuple[dict, list[str]]:
    """Map a client's named fields onto the raw inputs used by the model.

    Returns ``(raw, warnings)``.  Missing recipient balances stay ``NaN`` (the
    model was trained to handle "recipient balance unknown"); everything else
    that is missing is reported in ``warnings`` rather than silently guessed.
    """
    warnings: list[str] = []
    found: dict[str, Any] = {}
    for canonical, aliases in INPUT_ALIASES.items():
        for alias in aliases:
            if alias in payload and payload[alias] is not None and payload[alias] != "":
                found[canonical] = payload[alias]
                break

    raw_type = str(found.get("transaction_type", "")).strip().upper().replace(" ", "_").replace("-", "_")
    if not raw_type:
        warnings.append("transaction_type missing; assumed PAYMENT")
        raw_type = "PAYMENT"
    tx_type = TYPE_ALIASES.get(raw_type)
    if tx_type is None:
        warnings.append(f"unknown transaction_type '{raw_type}'; assumed PAYMENT")
        tx_type = "PAYMENT"

    amount = abs(_to_float(found.get("amount")))
    if math.isnan(amount):
        raise ValueError("amount is required and must be a number")

    old_orig = _to_float(found.get("oldbalanceOrg"))
    new_orig = _to_float(found.get("newbalanceOrig"))
    sender_known = not (math.isnan(old_orig) or math.isnan(new_orig))
    if not sender_known:
        warnings.append("sender balances missing; balance-based signals are unreliable")
        old_orig = 0.0 if math.isnan(old_orig) else old_orig
        new_orig = 0.0 if math.isnan(new_orig) else new_orig

    hour = _to_float(found.get("hour_of_day"))
    if math.isnan(hour):
        ts = _to_float(found.get("timestamp"))
        if not math.isnan(ts):
            seconds = ts / 1000.0 if ts > 1e12 else ts
            offset = _to_float(found.get("device_timezone_offset_minutes"))
            local_seconds = seconds - (0 if math.isnan(offset) else offset * 60)
            hour = (local_seconds // 3600) % 24
        else:
            warnings.append("no time supplied; assumed 12:00")
            hour = 12.0

    raw = {
        "transaction_type": tx_type,
        "amount": amount,
        "oldbalanceOrg": old_orig,
        "newbalanceOrig": new_orig,
        "oldbalanceDest": _to_float(found.get("oldbalanceDest")),
        "newbalanceDest": _to_float(found.get("newbalanceDest")),
        "hour_of_day": float(hour) % 24,
        "sender_balances_known": sender_known,
    }
    return raw, warnings


def engineer_features(raw: pd.DataFrame) -> pd.DataFrame:
    """Vectorised feature engineering; ``raw`` needs the columns of ``normalize_payload``.

    Recipient balances that are NaN mean "unknown" (e.g. merchant accounts, or a
    sandbox that does not track the recipient); all recipient-derived signals are
    then neutral (0) and ``dest_balance_known`` is 0.
    """
    tx_type = raw["transaction_type"].astype(str).str.upper()
    amount = raw["amount"].astype(float).abs()
    old_o = raw["oldbalanceOrg"].astype(float).fillna(0.0)
    new_o = raw["newbalanceOrig"].astype(float).fillna(0.0)
    old_d_raw = raw["oldbalanceDest"].astype(float)
    new_d_raw = raw["newbalanceDest"].astype(float)
    hour = raw["hour_of_day"].astype(float).fillna(12.0) % 24

    known = (old_d_raw.notna() & new_d_raw.notna()).astype(float)
    old_d = old_d_raw.fillna(0.0) * known
    new_d = new_d_raw.fillna(0.0) * known

    incoming = tx_type.eq("CASH_IN")
    # Money moving out of the sender: old - amount should equal new (error 0).
    orig_error = np.where(incoming, new_o - (old_o + amount), new_o - (old_o - amount))
    dest_error = np.where(
        known == 1.0,
        np.where(incoming, new_d - (old_d - amount), new_d - (old_d + amount)),
        0.0,
    )

    out = pd.DataFrame(index=raw.index)
    out["amount"] = amount
    out["oldbalanceOrg"] = old_o
    out["newbalanceOrig"] = new_o
    out["oldbalanceDest"] = old_d
    out["newbalanceDest"] = new_d
    out["dest_balance_known"] = known
    out["hour_of_day"] = hour
    out["is_night"] = (hour < 6).astype(float)
    out["orig_balance_error"] = orig_error
    out["dest_balance_error"] = dest_error
    out["amount_to_balance_ratio"] = np.clip(amount / (old_o + 1.0), 0.0, 10.0)
    out["orig_drained"] = ((old_o > 0) & (new_o <= 0.01) & ~incoming).astype(float)
    out["amount_exceeds_balance"] = ((amount > old_o + 0.01) & ~incoming).astype(float)
    out["dest_empty_before"] = ((known == 1.0) & (old_d <= 0.01)).astype(float)
    out["dest_unchanged"] = ((known == 1.0) & ((new_d - old_d).abs() < 0.01)).astype(float)
    for name in ("CASH_OUT", "DEBIT", "PAYMENT", "TRANSFER"):
        out[f"type_{name}"] = tx_type.eq(name).astype(float)
    return out[FEATURE_NAMES]


class Preprocessor:
    """Signed-log the money columns then standardise; identical at train and serve time."""

    def __init__(self) -> None:
        self.mean_: np.ndarray | None = None
        self.scale_: np.ndarray | None = None
        self._money_idx = [FEATURE_NAMES.index(c) for c in MONEY_COLUMNS]

    def _log(self, features: pd.DataFrame | np.ndarray) -> np.ndarray:
        arr = np.asarray(features[FEATURE_NAMES] if isinstance(features, pd.DataFrame) else features, dtype=np.float64)
        arr = arr.copy()
        arr[:, self._money_idx] = signed_log1p(arr[:, self._money_idx])
        return arr

    def fit(self, features: pd.DataFrame) -> "Preprocessor":
        arr = self._log(features)
        self.mean_ = arr.mean(axis=0)
        scale = arr.std(axis=0)
        self.scale_ = np.where(scale < 1e-9, 1.0, scale)
        return self

    def transform(self, features: pd.DataFrame | np.ndarray) -> np.ndarray:
        arr = self._log(features)
        return ((arr - self.mean_) / self.scale_).astype(np.float32)


# ---------------------------------------------------------------- explanations
def _money(value: float) -> str:
    return f"{value:,.2f}"


def describe_feature(name: str, value: float, contribution: float) -> str:
    """One plain-English sentence for a feature's value and effect on this decision."""
    label = FEATURE_LABELS.get(name, name.replace("_", " "))
    if name == "orig_drained":
        return "The sender's account was emptied by this transaction." if value >= 0.5 else "The sender's account was not emptied."
    if name == "amount_exceeds_balance":
        return "The amount is larger than the sender's available balance." if value >= 0.5 else "The amount is within the sender's balance."
    if name == "dest_empty_before":
        return "The recipient account was empty before this transaction." if value >= 0.5 else "The recipient account already held funds."
    if name == "dest_unchanged":
        return "The recipient's balance did not change even though money was sent." if value >= 0.5 else "The recipient's balance changed as expected."
    if name == "is_night":
        return "The transaction happened at night (00:00-05:59)." if value >= 0.5 else "The transaction happened during the day."
    if name == "dest_balance_known":
        return "Recipient balances are available." if value >= 0.5 else "Recipient balances are unknown, so recipient checks were skipped."
    if name == "orig_balance_error":
        return (f"The sender's balance does not add up (off by {_money(abs(value))})." if abs(value) > 0.01
                else "The sender's balance reconciles exactly.")
    if name == "dest_balance_error":
        return (f"The recipient's balance does not add up (off by {_money(abs(value))})." if abs(value) > 0.01
                else "The recipient's balance reconciles exactly.")
    if name == "amount_to_balance_ratio":
        return f"The transaction moves {min(value, 10) * 100:,.0f}% of the sender's balance."
    if name == "hour_of_day":
        return f"The transaction took place at {int(value):02d}:00."
    if name.startswith("type_"):
        return f"{label}." if value >= 0.5 else f"It is not a {label.split(': ')[1]} transaction."
    if name == "amount":
        return f"The amount is {_money(value)}."
    return f"{label} is {_money(value)}."
