"""Transparent rule layer for signals the PaySim data cannot teach a model.

PaySim has no real location, device or per-customer history (almost every account
appears once), so training a model on those would be learning noise.  The sandbox
app *does* capture them, so they are evaluated here as explicit, auditable rules
and reported next to - never mixed into - the machine-learning probability.
"""
from __future__ import annotations

import os

from .features import _to_float


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def high_risk_countries() -> set[str]:
    """Configure with e.g. HIGH_RISK_COUNTRIES="XX,YY".  Empty by default (a policy choice)."""
    return {c.strip().upper() for c in os.getenv("HIGH_RISK_COUNTRIES", "").split(",") if c.strip()}


def evaluate_context(payload: dict, amount: float) -> list[dict]:
    """Return a list of ``{code, label, detail}`` flags raised by the rule layer."""
    flags: list[dict] = []

    def flag(code: str, label: str, detail: str) -> None:
        flags.append({"code": code, "label": label, "detail": detail})

    distance = _to_float(payload.get("location_change_distance_km"))
    if payload.get("impossible_travel_flag") in (1, True, "1", "true"):
        detail = "Location changed too far, too quickly since the previous transaction."
        if distance == distance:
            detail = f"Location moved {distance:,.0f} km since the previous transaction in a very short time."
        flag("impossible_travel", "Impossible travel", detail)

    country = str(payload.get("country") or "").strip().upper()
    if country and country in high_risk_countries():
        flag("high_risk_country", "High-risk country", f"Transaction originated in {country}, which is on the watch list.")

    burst_limit = _int_env("BURST_TX_LIMIT_24H", 25)
    count_24h = _to_float(payload.get("tx_count_24h"))
    if count_24h == count_24h and count_24h >= burst_limit:
        flag("burst_activity", "Burst of activity", f"{int(count_24h)} transactions in the last 24 hours.")

    rapid = _to_float(payload.get("rapid_withdrawal_count"))
    if rapid == rapid and rapid >= 3:
        flag("rapid_withdrawals", "Rapid withdrawals", f"{int(rapid)} withdrawals in a short period.")

    high_value = _int_env("HIGH_VALUE_AMOUNT", 5000)
    if payload.get("is_new_device") in (1, True, "1", "true") and amount >= high_value:
        flag("new_device_high_value", "New device, high value",
             f"A never-seen device was used for a transaction of {amount:,.2f}.")

    return flags
