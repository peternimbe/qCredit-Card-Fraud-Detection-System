"""Post-deploy smoke test for the API (works locally and against Render).

    python scripts/smoke_test.py                                   # http://localhost:8000
    python scripts/smoke_test.py https://smartdetector-api.onrender.com

The first request to a free Render service can take ~1 minute (cold start); the script waits.
"""
import sys
import time

import requests

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
failures = []


def check(name: str, condition: bool, detail: str = "") -> None:
    print(("PASS " if condition else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not condition:
        failures.append(name)


def post(payload):
    return requests.post(f"{BASE}/predict_named", json=payload, timeout=90)


deadline = time.time() + 180
while True:
    try:
        health = requests.get(f"{BASE}/health", timeout=30).json()
        if health.get("model_loaded"):
            break
    except Exception:
        pass
    if time.time() > deadline:
        sys.exit("API did not become healthy within 3 minutes")
    time.sleep(5)
check("health: model loaded", True, health.get("model_version"))

normal = post({"type": "payment", "amount": 45, "balance_before": 900, "balance_after": 855, "hour_of_day": 14}).json()
check("everyday payment is not flagged", not normal["is_fraudulent"], f"p={normal['fraud_probability']:.4f}")

drain = post({"type": "send", "amount": 1500, "balance_before": 1500, "balance_after": 0, "hour_of_day": 3}).json()
check("account-draining transfer is flagged", drain["is_fraudulent"], f"p={drain['fraud_probability']:.4f}")
check("explanation names the emptied account", "emptied" in drain["explanation"]["reason"].lower())
check("explanation has SHAP impacts", len(drain["explanation"]["feature_impacts"]) > 0)

ctx = post({"type": "payment", "amount": 30, "balance_before": 900, "balance_after": 870, "impossible_travel_flag": 1}).json()
check("context rule escalates a normal payment for review", ctx["review_required"] and not ctx["is_fraudulent"])

check("missing amount is rejected (422)", post({"type": "payment"}).status_code == 422)
batch = requests.post(f"{BASE}/predict_batch", json=[
    {"type": "send", "amount": 10, "balance_before": 100, "balance_after": 90},
    {"type": "send", "amount": 100, "balance_before": 100, "balance_after": 0}], timeout=60).json()["predictions"]
check("batch ranks the drained transfer higher", batch[1]["fraud_probability"] > batch[0]["fraud_probability"])
check("/metrics served", "test_metrics" in requests.get(f"{BASE}/metrics", timeout=30).json())
check("/feature-schema served", "model_features" in requests.get(f"{BASE}/feature-schema", timeout=30).json())

sys.exit(1 if failures else 0)
