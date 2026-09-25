"""Smart Detector - FastAPI service.

Scores transactions described with *named* fields (amount, balances, type, ...) using the
three-layer system in ``models/`` and returns SHAP-based, plain-English explanations.

Run locally :  uvicorn api:app --reload --port 8000
On Render   :  uvicorn api:app --host 0.0.0.0 --port $PORT   (see render.yaml)
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from fraud.features import CONTEXT_FIELDS, FEATURE_LABELS, FEATURE_NAMES, INPUT_ALIASES, TRANSACTION_TYPES
from fraud.system import FraudDetectionSystem

logger = logging.getLogger("smartdetector")
MODEL_DIR = Path(os.getenv("MODEL_DIR", Path(__file__).parent / "models"))
system: FraudDetectionSystem | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global system
    try:
        system = FraudDetectionSystem.load(MODEL_DIR)
        logger.info("Loaded model %s from %s", system.metadata.get("model_version"), MODEL_DIR)
    except Exception:  # keep the API up so /health can report the problem
        logger.exception("Could not load model artifacts from %s", MODEL_DIR)
        system = None
    yield


app = FastAPI(
    title="Smart Detector - Fraud Detection API",
    description="Three-layer, explainable fraud detection with quantum-inspired optimisation, on named features.",
    version="2.0.0",
    lifespan=lifespan,
)

_origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=_origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _require_model() -> FraudDetectionSystem:
    if system is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    return system


EXAMPLE = {
    "transaction_type": "TRANSFER", "amount": 181.0,
    "oldbalanceOrg": 181.0, "newbalanceOrig": 0.0,
    "oldbalanceDest": 0.0, "newbalanceDest": 0.0, "hour_of_day": 3,
}


@app.get("/")
def root():
    return {"service": "Smart Detector API", "status": "active" if system else "inactive", "docs": "/docs"}


@app.get("/health")
def health():
    return {"status": "healthy" if system else "unhealthy", "model_loaded": system is not None,
            "model_version": system.metadata.get("model_version") if system else None}


@app.get("/feature-schema")
def feature_schema():
    """The named inputs a client can send (any alias per field is accepted)."""
    return {
        "required": ["amount", "transaction_type"],
        "recommended": ["oldbalanceOrg", "newbalanceOrig", "hour_of_day"],
        "optional": ["oldbalanceDest", "newbalanceDest", *CONTEXT_FIELDS],
        "aliases": INPUT_ALIASES,
        "transaction_types": TRANSACTION_TYPES,
        "model_features": [{"name": n, "label": FEATURE_LABELS[n]} for n in FEATURE_NAMES],
        "example": EXAMPLE,
    }


@app.get("/model-info")
def model_info():
    model = _require_model()
    info = model.info()
    metrics = model.metrics or {}
    champion = model.champion
    info["champion_test_metrics"] = (metrics.get("test_metrics") or {}).get(champion)
    info["feature_selection"] = {
        "chosen_method": (metrics.get("feature_selection") or {}).get("chosen_method"),
        "selected_features": info["selected_features"],
    }
    return info


@app.get("/metrics")
def metrics():
    """Full evaluation report written at training time (test metrics, baseline comparison, ...)."""
    model = _require_model()
    return {"metadata": model.metadata, **model.metrics}


@app.post("/predict_named")
def predict_named(payload: dict = Body(..., examples=[EXAMPLE])):
    model = _require_model()
    try:
        return model.score_named(payload, explain=True)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    except Exception as error:
        logger.exception("prediction failed")
        raise HTTPException(status_code=500, detail=f"Prediction error: {error}")


@app.post("/predict_simple")
def predict_simple(payload: dict = Body(...)):
    """Backward-compatible alias (older PHP config pointed here); accepts the same named fields."""
    return predict_named(payload)


@app.post("/explain_named")
def explain_named(payload: dict = Body(...)):
    result = predict_named(payload)
    return {"explanation": result["explanation"], "fraud_probability": result["fraud_probability"]}


@app.post("/predict_batch")
def predict_batch(payloads: list[dict] = Body(...)):
    model = _require_model()
    if len(payloads) > 5000:
        raise HTTPException(status_code=413, detail="At most 5000 transactions per request")
    try:
        return {"predictions": model.score_batch(payloads), "count": len(payloads)}
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
