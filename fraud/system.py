"""FraudDetectionSystem: scoring, explanation and persistence of the trained three-layer system.

Layer 1  logistic_regression, decision_tree, xgboost, random_forest (+ adaboost baseline)
Layer 2  soft_voting, weighted_voting, stacking, adaptive_ensemble
Layer 3  quantum-selected features -> xgboost_optimized / random_forest_optimized,
         isolation-forest anomaly score, risk fusion ("quantum_enhanced")

Training lives in ``fraud.training``; this module is everything needed at serving time.
"""
from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb

from .context import evaluate_context
from .features import (FEATURE_LABELS, FEATURE_NAMES, Preprocessor, describe_feature, engineer_features,
                       normalize_payload)

LAYER1 = ["logistic_regression", "decision_tree", "xgboost", "random_forest"]
OPTIMIZED = ["xgboost_optimized", "random_forest_optimized"]
LAYER2 = ["soft_voting", "weighted_voting", "stacking", "adaptive_ensemble"]
LAYER3 = "quantum_enhanced"
RISK_ORDER = ["Very Low Risk", "Low Risk", "Medium Risk", "High Risk"]
MATERIAL_LOG_ODDS = 0.5     # smallest SHAP contribution worth narrating
MATERIAL_SHARE_PCT = 10.0   # ... and it must carry at least this share of the total impact
BALANCE_FEATURES = {"oldbalanceOrg", "newbalanceOrig", "orig_balance_error", "amount_to_balance_ratio",
                    "orig_drained", "amount_exceeds_balance"}

MODEL_FILE = "layer1_models.joblib"
LAYERS_FILE = "layers_2_3.joblib"
META_FILE = "metadata.json"
METRICS_FILE = "metrics.json"


def correct_prior(p: np.ndarray, beta: float) -> np.ndarray:
    """Undo the legitimate-row under-sampling used in training (Dal Pozzolo et al., 2015)."""
    p = np.asarray(p, dtype=float)
    return beta * p / (beta * p - p + 1.0)


class FraudDetectionSystem:
    def __init__(self) -> None:
        self.preprocessor: Preprocessor | None = None
        self.base_models: dict = {}       # Layer 1 (+ adaboost)
        self.optimized: dict = {}         # Layer 3 tuned models on the selected features
        self.selected_idx: list[int] = []
        self.anomaly = None
        self.ensembles: dict = {}         # Layer 2
        self.fusion = None                # Layer 3 head
        self.beta = 1.0
        self.champion = "soft_voting"
        self.threshold = 0.5
        self.metadata: dict = {}
        self.metrics: dict = {}
        self.is_trained = False

    # ------------------------------------------------------------------ persistence
    def save(self, directory: str | Path) -> dict:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        joblib.dump({"base_models": self.base_models, "optimized": self.optimized}, directory / MODEL_FILE, compress=3)
        joblib.dump({
            "preprocessor": self.preprocessor, "selected_idx": self.selected_idx, "anomaly": self.anomaly,
            "ensembles": self.ensembles, "fusion": self.fusion,
        }, directory / LAYERS_FILE, compress=3)
        self.metadata.update({
            "feature_names": FEATURE_NAMES, "feature_labels": FEATURE_LABELS, "beta": self.beta,
            "champion": self.champion, "threshold": self.threshold, "selected_features": [FEATURE_NAMES[i] for i in self.selected_idx],
        })
        (directory / META_FILE).write_text(json.dumps(self.metadata, indent=2))
        (directory / METRICS_FILE).write_text(json.dumps(self.metrics, indent=2))
        return {p.name: round(p.stat().st_size / 1e6, 2) for p in directory.glob("*") if p.is_file()}

    @classmethod
    def load(cls, directory: str | Path = "models") -> "FraudDetectionSystem":
        directory = Path(directory)
        system = cls()
        layer1 = joblib.load(directory / MODEL_FILE)
        layers = joblib.load(directory / LAYERS_FILE)
        system.base_models, system.optimized = layer1["base_models"], layer1["optimized"]
        system.preprocessor = layers["preprocessor"]
        system.selected_idx = layers["selected_idx"]
        system.anomaly, system.ensembles, system.fusion = layers["anomaly"], layers["ensembles"], layers["fusion"]
        system.metadata = json.loads((directory / META_FILE).read_text())
        system.metrics = json.loads((directory / METRICS_FILE).read_text()) if (directory / METRICS_FILE).exists() else {}
        system.beta = float(system.metadata["beta"])
        system.champion = system.metadata["champion"]
        system.threshold = float(system.metadata["threshold"])
        for model in list(system.base_models.values()) + list(system.optimized.values()):
            if hasattr(model, "set_params") and "n_jobs" in model.get_params():
                model.set_params(n_jobs=1)  # single-row serving: threads only add latency
        if system.anomaly is not None:
            system.anomaly.forest.n_jobs = 1
        system.is_trained = True
        return system

    # ------------------------------------------------------------------ scoring core
    def _correct(self, p: np.ndarray) -> np.ndarray:
        return correct_prior(p, self.beta)

    def model_probabilities(self, Z: np.ndarray) -> dict[str, np.ndarray]:
        """Prior-corrected probability from every Layer 1 model and the tuned Layer 3 models."""
        probs = {name: self._correct(model.predict_proba(Z)[:, 1]) for name, model in self.base_models.items()}
        selected = Z[:, self.selected_idx]
        for name, model in self.optimized.items():
            probs[name] = self._correct(model.predict_proba(selected)[:, 1])
        return probs

    def layer2(self, probs: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
        P = np.column_stack([probs[name] for name in LAYER1])
        return {name: self.ensembles[name].predict(P) for name in LAYER2}

    def layer3(self, probs: dict[str, np.ndarray], ens: dict[str, np.ndarray], Z: np.ndarray):
        anomaly = self.anomaly.percentile(Z[:, self.selected_idx])
        fused = self.fusion.predict(self.fusion_inputs(probs, ens), anomaly)
        return fused, anomaly

    @staticmethod
    def fusion_inputs(probs: dict[str, np.ndarray], ens: dict[str, np.ndarray]) -> np.ndarray:
        return np.column_stack([ens["weighted_voting"], probs["xgboost_optimized"], probs["random_forest_optimized"]])

    def score_matrix(self, features: pd.DataFrame) -> dict:
        Z = self.preprocessor.transform(features)
        probs = self.model_probabilities(Z)
        ens = self.layer2(probs)
        fused, anomaly = self.layer3(probs, ens, Z)
        scores = {**probs, **ens, LAYER3: fused}
        return {"scores": scores, "anomaly": anomaly, "Z": Z}

    # ------------------------------------------------------------------ risk bands
    def risk_level(self, p: float) -> str:
        if p >= max(self.threshold, 0.8):
            return "High Risk"
        if p >= self.threshold:
            return "Medium Risk"
        if self.risk_score(p) >= 25:   # noticeably above the bulk of normal traffic, still below the threshold
            return "Low Risk"
        return "Very Low Risk"

    def risk_score(self, p: float, context_flags: bool = False) -> int:
        """One 0-100 number for dashboards that stays consistent with the model's decision.

        * probability >= threshold  ->  75..100   (the model flags it)
        * below the threshold       ->  0..74, log-scaled from 1e-8 so small differences stay visible
                                       (a rank-preserving index, NOT a probability - use fraud_probability for that)
        * any context alert         ->  at least 50 (needs a look, but the model did not flag it)
        """
        floor = 1e-8
        thr = self.threshold
        if p >= thr:
            score = 75 + 25 * (p - thr) / max(1.0 - thr, 1e-9)
        else:
            span = np.log10(thr) - np.log10(floor)
            score = 74 * (np.log10(max(p, floor)) - np.log10(floor)) / span
        if context_flags:
            score = max(score, 50)
        return int(round(min(max(score, 0), 100)))

    # ------------------------------------------------------------------ explanation
    def explain(self, Z_row: np.ndarray, feature_row: pd.Series, flagged: bool, low_confidence: bool = False,
                top_n: int = 5) -> dict:
        """Exact TreeSHAP from the XGBoost model, phrased with named features.

        Only *material* drivers (>= MATERIAL_LOG_ODDS and >= MATERIAL_SHARE_PCT of the total impact)
        are narrated; tiny positive/negative wiggles are listed in the table but not in the sentence.
        """
        booster = self.base_models["xgboost"].get_booster()
        contribs = booster.predict(xgb.DMatrix(Z_row.reshape(1, -1)), pred_contribs=True)[0]
        shap_values, bias = contribs[:-1], float(contribs[-1])
        if low_confidence:  # balances were imputed, so balance-derived signals are not evidence
            shap_values = np.where([n in BALANCE_FEATURES for n in FEATURE_NAMES], 0.0, shap_values)
        total = float(np.abs(shap_values).sum()) or 1.0
        order = np.argsort(-np.abs(shap_values))[:top_n]
        impacts = []
        for idx in order:
            name = FEATURE_NAMES[idx]
            value = float(feature_row[name])
            contribution = float(shap_values[idx])
            impacts.append({
                "feature": name,
                "label": FEATURE_LABELS[name],
                "value": value,
                "contribution": contribution,
                "impact_pct": round(abs(contribution) / total * 100, 1),
                "direction": "increases fraud risk" if contribution > 0 else "reduces fraud risk",
                "description": describe_feature(name, value, contribution),
            })

        def material(item: dict) -> bool:
            # "Balance reconciles exactly" is a PaySim artefact (simulated fraud is always tidy, while many
            # legitimate rows are not) and a real ledger always reconciles - never present it as evidence.
            if item["feature"] in ("orig_balance_error", "dest_balance_error") and abs(item["value"]) <= 0.01:
                return False
            return abs(item["contribution"]) >= MATERIAL_LOG_ODDS and item["impact_pct"] >= MATERIAL_SHARE_PCT

        raising = [i for i in impacts if i["contribution"] > 0 and material(i)][:3]
        calming = [i for i in impacts if i["contribution"] < 0 and material(i)][:2]
        if flagged and raising:
            reason = "Flagged mainly because: " + " ".join(i["description"] for i in raising)
        elif flagged:
            reason = "Flagged by the combined model; no single signal dominates."
        elif raising:
            reason = "Below the fraud threshold, but note: " + " ".join(i["description"] for i in raising)
        elif calming:
            reason = "No significant fraud signals. Reassuring: " + " ".join(i["description"] for i in calming)
        else:
            reason = "No significant fraud signals."
        if low_confidence:
            reason = "Sender balances were not supplied, so balance checks were skipped. " + reason
        return {
            "model": "xgboost", "method": "TreeSHAP (log-odds contributions)",
            "reason": reason, "feature_impacts": impacts, "base_value": bias,
        }

    # ------------------------------------------------------------------ public scoring API
    def score_named(self, payload: dict, explain: bool = True) -> dict:
        """Score one transaction described with named fields (see ``features.INPUT_ALIASES``)."""
        raw, warnings = normalize_payload(payload)
        features = engineer_features(pd.DataFrame([raw]))
        out = self.score_matrix(features)
        scores = {k: float(v[0]) for k, v in out["scores"].items()}
        probability = scores[self.champion]
        flagged = probability >= self.threshold

        low_confidence = not raw["sender_balances_known"]
        flags = evaluate_context(payload, raw["amount"])
        level = self.risk_level(probability)
        if flags and RISK_ORDER.index(level) < RISK_ORDER.index("Medium Risk"):
            level = "Medium Risk"
        result = {
            "fraud_probability": probability,
            "risk_score": self.risk_score(probability, bool(flags)),
            "is_fraudulent": bool(flagged),
            "risk_level": level,
            "review_required": bool(flagged or flags),
            "threshold": self.threshold,
            "champion_model": self.champion,
            "model_scores": scores,
            "quantum_enhanced_score": scores[LAYER3],
            "anomaly_score": float(out["anomaly"][0]),
            "context_flags": flags,
            "input_warnings": warnings,
            "low_confidence": low_confidence,
            "model_version": self.metadata.get("model_version"),
        }
        if explain:
            explanation = self.explain(out["Z"][0], features.iloc[0], flagged, low_confidence)
            if flags:
                explanation["reason"] += " Context alerts: " + "; ".join(f["label"] for f in flags) + "."
            result["explanation"] = explanation
        return result

    def score_batch(self, payloads: list[dict]) -> list[dict]:
        """Vectorised scoring without explanations (for CSV / bulk use)."""
        normalized = [normalize_payload(p) for p in payloads]
        features = engineer_features(pd.DataFrame([n[0] for n in normalized]))
        out = self.score_matrix(features)
        results = []
        for i, payload in enumerate(payloads):
            probability = float(out["scores"][self.champion][i])
            flags = evaluate_context(payload, normalized[i][0]["amount"])
            level = self.risk_level(probability)
            if flags and RISK_ORDER.index(level) < RISK_ORDER.index("Medium Risk"):
                level = "Medium Risk"
            results.append({
                "fraud_probability": probability,
                "risk_score": self.risk_score(probability, bool(flags)),
                "is_fraudulent": bool(probability >= self.threshold),
                "risk_level": level,
                "review_required": bool(probability >= self.threshold or flags),
                "model_scores": {k: float(v[i]) for k, v in out["scores"].items()},
                "context_flags": flags,
                "input_warnings": normalized[i][1],
                "low_confidence": not normalized[i][0]["sender_balances_known"],
            })
        return results

    def info(self) -> dict:
        return {
            "model_version": self.metadata.get("model_version"),
            "trained_at": self.metadata.get("trained_at"),
            "champion_model": self.champion,
            "threshold": self.threshold,
            "feature_names": FEATURE_NAMES,
            "selected_features": [FEATURE_NAMES[i] for i in self.selected_idx],
            "layers": {
                "layer1": LAYER1 + ["adaboost"],
                "layer2": LAYER2,
                "layer3": OPTIMIZED + ["anomaly_isolation_forest", LAYER3],
            },
            "available_models": list(self.base_models) + list(self.optimized) + LAYER2 + [LAYER3],
        }
