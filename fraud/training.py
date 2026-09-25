"""End-to-end training of the three-layer system on the named-feature PaySim splits.

Baseline = the old project's algorithms with their original hyper-parameters
(LogisticRegression, DecisionTree depth 10, XGBoost 100/6/0.1, RandomForest 100/10, AdaBoost
stumps, soft/weighted voting, stacking, SelectKBest / quantum-genetic / QDE feature selection,
optimised XGBoost + RF, isolation-forest anomaly score).

What is improved on top of that baseline
  * named, arithmetic features (balance mismatches, drained account, ...) instead of PCA
  * leakage-safe splits with *natural-prevalence* validation/test sets and prior correction
  * PR-AUC (not ROC-AUC) as the search objective, F1-optimal decision threshold from validation
  * genuine Q-bit selectors / hyper-parameter search with caching and a parsimony penalty
  * stacking and risk fusion fitted out-of-fold, champion picked on validation, judged on test
  * a like-for-like comparison against the old configuration written to metrics.json
"""
from __future__ import annotations

import datetime as dt
import platform
import time

import numpy as np
import pandas as pd
import sklearn
import xgboost as xgb
from sklearn.ensemble import AdaBoostClassifier, IsolationForest, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.tree import DecisionTreeClassifier

from . import __version__, quantum
from .ensembles import (AdaptiveEnsemble, AnomalyScorer, RiskFusion, SoftVoting, StackingMeta, WeightedVoting, logit)
from .features import FEATURE_LABELS, FEATURE_NAMES, Preprocessor, engineer_features
from .system import LAYER1, LAYER2, LAYER3, OPTIMIZED, FraudDetectionSystem, correct_prior

# Order in which ties (within validation noise) are resolved: prefer the richer models.
CHAMPION_PREFERENCE = ["quantum_enhanced", "weighted_voting", "stacking", "adaptive_ensemble", "soft_voting",
                       "xgboost_optimized", "random_forest_optimized", "xgboost", "random_forest",
                       "decision_tree", "adaboost", "logistic_regression"]

XGB_GRID = {"max_depth": [3, 4, 5, 6, 8], "learning_rate": [0.03, 0.05, 0.1, 0.2],
            "n_estimators": [100, 200, 300], "subsample": [0.7, 0.85, 1.0],
            "min_child_weight": [1, 5, 10, 20]}  # larger leaves guard against over-confident, saturated trees
RF_GRID = {"n_estimators": [80, 120, 160], "max_depth": [8, 10, 12, 14],
           "min_samples_leaf": [3, 5, 10], "max_features": ["sqrt", 0.5]}


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


# ---------------------------------------------------------------- helpers
def old_baseline_models(seed: int, n_jobs: int) -> dict:
    """Exactly the hyper-parameters used by the old project's ``train_base_models``."""
    return {
        "logistic_regression": LogisticRegression(random_state=seed, max_iter=1000),
        "decision_tree": DecisionTreeClassifier(random_state=seed, max_depth=10),
        "xgboost": xgb.XGBClassifier(random_state=seed, n_estimators=100, max_depth=6, learning_rate=0.1,
                                     objective="binary:logistic", tree_method="hist", n_jobs=n_jobs, eval_metric="logloss"),
        "random_forest": RandomForestClassifier(random_state=seed, n_estimators=100, max_depth=10, n_jobs=n_jobs),
    }


def build_z(system: FraudDetectionSystem, raw: pd.DataFrame, chunk: int = 250_000) -> np.ndarray:
    parts = [system.preprocessor.transform(engineer_features(raw.iloc[i:i + chunk])) for i in range(0, len(raw), chunk)]
    return np.vstack(parts)


def _merge(parts: list[dict]) -> dict:
    return {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}


def chunked_base_probs(system: FraudDetectionSystem, Z: np.ndarray, chunk: int = 200_000) -> dict:
    return _merge([system.model_probabilities(Z[i:i + chunk]) for i in range(0, len(Z), chunk)])


def chunked_anomaly(system: FraudDetectionSystem, Z: np.ndarray, chunk: int = 200_000) -> np.ndarray:
    sel = system.selected_idx
    return np.concatenate([system.anomaly.percentile(Z[i:i + chunk, sel]) for i in range(0, len(Z), chunk)])


def all_scores(system: FraudDetectionSystem, Z: np.ndarray) -> tuple[dict, np.ndarray]:
    probs = chunked_base_probs(system, Z)
    anomaly = chunked_anomaly(system, Z)
    ens = system.layer2(probs)
    fused = system.fusion.predict(system.fusion_inputs(probs, ens), anomaly)
    return {**probs, **ens, LAYER3: fused}, anomaly


def subsample(y: np.ndarray, n_max: int, seed: int, positive_share: float = 0.3) -> np.ndarray:
    rng = np.random.default_rng(seed)
    pos, neg = np.flatnonzero(y == 1), np.flatnonzero(y == 0)
    n_pos = min(len(pos), int(n_max * positive_share))
    n_neg = min(len(neg), n_max - n_pos)
    return np.sort(np.concatenate([rng.choice(pos, n_pos, replace=False), rng.choice(neg, n_neg, replace=False)]))


def best_f1_threshold(y: np.ndarray, p: np.ndarray) -> tuple[float, float]:
    precision, recall, thresholds = precision_recall_curve(y, p)
    f1 = 2 * precision[:-1] * recall[:-1] / np.maximum(precision[:-1] + recall[:-1], 1e-12)
    best = int(np.argmax(f1))
    return float(thresholds[best]), float(f1[best])


def evaluate(y: np.ndarray, p: np.ndarray, threshold: float) -> dict:
    pred = p >= threshold
    tp, fp = int((pred & (y == 1)).sum()), int((pred & (y == 0)).sum())
    fn, tn = int((~pred & (y == 1)).sum()), int((~pred & (y == 0)).sum())
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    order = np.argsort(-p, kind="stable")
    n_pos = int(y.sum())
    return {
        "average_precision": float(average_precision_score(y, p)),
        "roc_auc": float(roc_auc_score(y, p)),
        "threshold": float(threshold),
        "precision": precision, "recall": recall,
        "f1": 2 * precision * recall / max(precision + recall, 1e-12),
        "false_positive_rate": fp / max(fp + tn, 1),
        "confusion_matrix": [[tn, fp], [fn, tp]],
        "precision_at_100": float(y[order[:100]].mean()),
        "precision_at_1000": float(y[order[:1000]].mean()),
        "precision_at_n_frauds": float(y[order[:n_pos]].mean()),
    }


def raw_baseline_matrix(raw: pd.DataFrame) -> np.ndarray:
    """The 'old' un-engineered inputs: type dummies, amount, four balances, hour."""
    cols = raw[["amount", "oldbalanceOrg", "newbalanceOrig", "oldbalanceDest", "newbalanceDest", "hour_of_day"]].fillna(0.0)
    types = pd.get_dummies(raw["transaction_type"]).reindex(columns=["CASH_OUT", "DEBIT", "PAYMENT", "TRANSFER"], fill_value=0)
    return np.hstack([cols.to_numpy(dtype=np.float32), types.to_numpy(dtype=np.float32)])


# ---------------------------------------------------------------- pipeline
def train_system(splits: dict, seed: int = 42, n_jobs: int = 2, quick: bool = False) -> FraudDetectionSystem:
    started = time.time()
    (raw_tr, y_tr), (raw_va, y_va), (raw_te, y_te) = splits["train"], splits["val"], splits["test"]
    beta = splits["beta"]
    system = FraudDetectionSystem()
    system.beta = beta
    report: dict = {}

    log(f"train rows {len(y_tr):,} (frauds {int(y_tr.sum()):,}) | val {len(y_va):,} ({int(y_va.sum()):,}) | "
        f"test {len(y_te):,} ({int(y_te.sum()):,}) | beta={beta:.4f}")
    system.preprocessor = Preprocessor().fit(engineer_features(raw_tr))
    Z_tr, Z_va, Z_te = (build_z(system, raw) for raw in (raw_tr, raw_va, raw_te))

    # ---- Layer 1 -----------------------------------------------------------------
    log("Layer 1: fitting base models (old hyper-parameters)")
    for name, model in old_baseline_models(seed, n_jobs).items():
        t = time.time()
        system.base_models[name] = model.fit(Z_tr, y_tr)
        log(f"  {name:<20s} {time.time() - t:5.1f}s")
    system.base_models["adaboost"] = AdaBoostClassifier(
        estimator=DecisionTreeClassifier(max_depth=1), n_estimators=50, random_state=seed
    ).fit(Z_tr, y_tr)

    # ---- Layer 3a: feature selection ------------------------------------------------
    log("Layer 3: quantum-inspired feature selection (3 methods, same fitness)")
    fs_idx = subsample(y_tr, 20_000 if quick else 50_000, seed)
    fitness = quantum.SubsetFitness(Z_tr[fs_idx], y_tr[fs_idx], seed=seed, n_jobs=n_jobs, min_k=8)
    k = max(8, round(0.65 * len(FEATURE_NAMES)))
    qk = dict(population=6, iterations=4) if quick else {}
    qd = dict(population=8, iterations=4) if quick else {}
    selectors = {
        "selectkbest": quantum.select_kbest(fitness, k),
        "quantum_genetic": quantum.quantum_genetic_select(fitness, seed=seed, **qk),
        "quantum_differential_evolution": quantum.quantum_de_select(fitness, k, seed=seed, **qd),
    }
    all_mask = np.ones(len(FEATURE_NAMES), dtype=int)
    selectors["all_features_reference"] = {
        "features": list(range(len(FEATURE_NAMES))), "k": len(FEATURE_NAMES), "fitness": float(fitness(all_mask)),
        "holdout_average_precision": float(fitness.average_precision(np.arange(len(FEATURE_NAMES)))),
        "evaluations": 1, "runtime_s": 0.0, "history": [], "params": {},
    }
    for name, result in selectors.items():
        cols = np.array(result["features"])
        ref = xgb.XGBClassifier(n_estimators=100, max_depth=4, learning_rate=0.2, tree_method="hist", n_jobs=n_jobs,
                                random_state=seed, eval_metric="logloss", verbosity=0).fit(Z_tr[:, cols], y_tr)
        result["test_average_precision"] = float(average_precision_score(y_te, ref.predict_proba(Z_te[:, cols])[:, 1]))
        result["feature_names"] = [FEATURE_NAMES[i] for i in cols]
        log(f"  {name:<32s} k={result['k']:>2d} fitness={result['fitness']:.4f} "
            f"test AP={result['test_average_precision']:.4f} ({result['runtime_s']}s, {result['evaluations']} evals)")
    contenders = {n: r for n, r in selectors.items() if n != "all_features_reference"}
    chosen = max(contenders, key=lambda n: (round(contenders[n]["fitness"], 4), -contenders[n]["k"]))
    system.selected_idx = sorted(contenders[chosen]["features"])
    report["feature_selection"] = {"chosen_method": chosen, "methods": selectors, "target_k": k}
    log(f"  -> chosen: {chosen} ({len(system.selected_idx)} features)")
    sel = system.selected_idx

    # ---- Layer 3b: quantum-inspired hyper-parameter search -------------------------------
    log("Layer 3: quantum-inspired hyper-parameter search (XGBoost, Random Forest)")
    hp_idx = subsample(y_tr, 12_000 if quick else 40_000, seed + 1, positive_share=0.10)
    Zs, ys = Z_tr[hp_idx][:, sel], y_tr[hp_idx]
    budget = dict(population=3, iterations=2) if quick else dict(population=5, iterations=4)
    xgb_search = quantum.quantum_inspired_search(
        XGB_GRID, lambda p: quantum.cv_average_precision(
            lambda: xgb.XGBClassifier(**p, tree_method="hist", n_jobs=n_jobs, random_state=seed, eval_metric="logloss", verbosity=0),
            Zs, ys), seed=seed, **budget)
    log(f"  xgboost best {xgb_search['best_params']} cv AP={xgb_search['best_score']:.4f} ({xgb_search['runtime_s']}s)")
    rf_search = quantum.quantum_inspired_search(
        RF_GRID, lambda p: quantum.cv_average_precision(
            lambda: RandomForestClassifier(**p, n_jobs=n_jobs, random_state=seed), Zs, ys), seed=seed, **budget)
    log(f"  random forest best {rf_search['best_params']} cv AP={rf_search['best_score']:.4f} ({rf_search['runtime_s']}s)")
    system.optimized["xgboost_optimized"] = xgb.XGBClassifier(
        **xgb_search["best_params"], tree_method="hist", n_jobs=n_jobs, random_state=seed, eval_metric="logloss"
    ).fit(Z_tr[:, sel], y_tr)
    system.optimized["random_forest_optimized"] = RandomForestClassifier(
        **rf_search["best_params"], n_jobs=n_jobs, random_state=seed).fit(Z_tr[:, sel], y_tr)
    report["hyperparameter_search"] = {"xgboost": xgb_search, "random_forest": rf_search}

    # ---- Layer 3c: anomaly detector on normal traffic ---------------------------------------
    normal = Z_tr[y_tr == 0][:, sel]
    forest = IsolationForest(n_estimators=100, random_state=seed, n_jobs=n_jobs).fit(normal[:100_000])
    system.anomaly = AnomalyScorer(forest, -forest.score_samples(normal[:50_000]))

    # ---- validation scores & Layer 2 ---------------------------------------------------------
    log("Scoring validation split (natural prevalence)")
    P_va = chunked_base_probs(system, Z_va)
    an_va = chunked_anomaly(system, Z_va)
    # Quality gate: a tuned model that ranks far worse than its untuned sibling on the natural-prevalence
    # validation set (e.g. saturated trees) is replaced by the sibling's original settings, and this is recorded.
    report["quality_gate"] = {}
    for tuned, sibling, make in (
        ("xgboost_optimized", "xgboost", lambda: old_baseline_models(seed, n_jobs)["xgboost"]),
        ("random_forest_optimized", "random_forest", lambda: old_baseline_models(seed, n_jobs)["random_forest"]),
    ):
        tuned_ap = float(average_precision_score(y_va, P_va[tuned]))
        sibling_ap = float(average_precision_score(y_va, P_va[sibling]))
        degraded = tuned_ap < sibling_ap - 0.02
        report["quality_gate"][tuned] = {"validation_ap": tuned_ap, "sibling_ap": sibling_ap, "fell_back_to_defaults": degraded}
        if degraded:
            log(f"  QUALITY GATE: {tuned} val AP {tuned_ap:.4f} << {sibling} {sibling_ap:.4f}; refitting with default settings")
            system.optimized[tuned] = make().fit(Z_tr[:, sel], y_tr)
            P_va[tuned] = correct_prior(system.optimized[tuned].predict_proba(Z_va[:, sel])[:, 1], beta)
    P4_va = np.column_stack([P_va[n] for n in LAYER1])
    weights = np.array([average_precision_score(y_va, P_va[n]) for n in LAYER1])
    cv = StratifiedKFold(5, shuffle=True, random_state=seed)

    system.ensembles = {
        "soft_voting": SoftVoting(), "weighted_voting": WeightedVoting(weights),
        "adaptive_ensemble": AdaptiveEnsemble(weights), "stacking": StackingMeta().fit(P4_va, y_va),
    }
    ens_va = {n: system.ensembles[n].predict(P4_va) for n in ("soft_voting", "weighted_voting", "adaptive_ensemble")}
    ens_va["stacking"] = cross_val_predict(LogisticRegression(max_iter=1000), logit(P4_va), y_va, cv=cv,
                                           method="predict_proba")[:, 1]
    fusion_in = system.fusion_inputs(P_va, ens_va)
    system.fusion = RiskFusion().fit(fusion_in, an_va, y_va)
    fused_oof = cross_val_predict(LogisticRegression(max_iter=1000), RiskFusion.design(fusion_in, an_va), y_va, cv=cv,
                                  method="predict_proba")[:, 1]
    val_scores = {**P_va, **ens_va, LAYER3: fused_oof}  # meta-learners are out-of-fold => honest

    val_ap = {n: float(average_precision_score(y_va, s)) for n, s in val_scores.items()}
    best_ap = max(val_ap.values())
    system.champion = next(n for n in CHAMPION_PREFERENCE if val_ap.get(n, 0) >= best_ap - 0.002)
    system.threshold, val_f1 = best_f1_threshold(y_va, val_scores[system.champion])
    log(f"Champion (validation AP within 0.002 of best, ties -> richer model): {system.champion} "
        f"AP={val_ap[system.champion]:.4f} threshold={system.threshold:.4f} F1={val_f1:.4f}")

    # ---- test evaluation --------------------------------------------------------------------
    log("Scoring test split")
    test_scores, an_te = all_scores(system, Z_te)
    per_model = {}
    for name, scores in test_scores.items():
        thr, _ = best_f1_threshold(y_va, val_scores[name]) if name in val_scores else (system.threshold, 0.0)
        per_model[name] = evaluate(y_te, scores, system.threshold if name == system.champion else thr)
        per_model[name]["layer"] = ("layer1" if name in LAYER1 or name == "adaboost" else
                                    "layer2" if name in LAYER2 else "layer3")
        per_model[name]["validation_average_precision"] = val_ap.get(name)
    report["test_metrics"] = per_model
    champion_test = per_model[system.champion]
    log(f"TEST {system.champion}: AP={champion_test['average_precision']:.4f} AUC={champion_test['roc_auc']:.4f} "
        f"precision={champion_test['precision']:.4f} recall={champion_test['recall']:.4f} F1={champion_test['f1']:.4f}")

    # ---- like-for-like: old configuration on raw (un-engineered) inputs ---------------------------
    log("Baseline: old algorithms & hyper-parameters on raw inputs")
    Xb_tr, Xb_va, Xb_te = (raw_baseline_matrix(r) for r in (raw_tr, raw_va, raw_te))
    base_va, base_te = {}, {}
    for name, model in old_baseline_models(seed, n_jobs).items():
        model.fit(Xb_tr, y_tr)
        base_va[name] = correct_prior(model.predict_proba(Xb_va)[:, 1], beta)
        base_te[name] = correct_prior(model.predict_proba(Xb_te)[:, 1], beta)
    base_va["soft_voting"] = np.mean([base_va[n] for n in LAYER1], axis=0)
    base_te["soft_voting"] = np.mean([base_te[n] for n in LAYER1], axis=0)
    baseline = {}
    for name in base_te:
        thr, _ = best_f1_threshold(y_va, base_va[name])
        baseline[name] = evaluate(y_te, base_te[name], thr)
    report["baseline_old_configuration"] = {
        "description": "Old algorithms/hyper-parameters, raw amount+balances+type+hour, no engineered features",
        "test_metrics": baseline,
    }
    log(f"  baseline soft_voting AP={baseline['soft_voting']['average_precision']:.4f} "
        f"recall={baseline['soft_voting']['recall']:.4f} | improved champion AP={champion_test['average_precision']:.4f} "
        f"recall={champion_test['recall']:.4f}")

    # ---- robustness: sandbox that cannot supply recipient balances --------------------------------
    hidden = raw_te.copy()
    hidden["oldbalanceDest"] = np.nan
    hidden["newbalanceDest"] = np.nan
    Z_hidden = build_z(system, hidden)
    hidden_scores, _ = all_scores(system, Z_hidden)
    report["robustness"] = {"recipient_balances_unknown": evaluate(y_te, hidden_scores[system.champion], system.threshold)}
    log(f"  recipient balances hidden -> AP={report['robustness']['recipient_balances_unknown']['average_precision']:.4f} "
        f"recall={report['robustness']['recipient_balances_unknown']['recall']:.4f}")

    # ---- global explanation (mean |SHAP| on a fraud-enriched test sample) -----------------------
    g_idx = subsample(y_te, 3000, seed, positive_share=0.5)
    contribs = system.base_models["xgboost"].get_booster().predict(xgb.DMatrix(Z_te[g_idx]), pred_contribs=True)[:, :-1]
    importance = np.abs(contribs).mean(axis=0)
    report["global_importance"] = sorted(
        ({"feature": n, "label": FEATURE_LABELS[n], "mean_abs_shap": float(v)} for n, v in zip(FEATURE_NAMES, importance)),
        key=lambda d: -d["mean_abs_shap"])

    # ---- metadata ---------------------------------------------------------------------------------
    system.metrics = report
    system.metadata = {
        "model_version": f"{__version__}-{dt.date.today().isoformat()}",
        "trained_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "dataset": {"name": "PaySim (synthetic mobile-money transactions)", "train_rows": int(len(y_tr)),
                    "val_rows": int(len(y_va)), "test_rows": int(len(y_te)), "test_frauds": int(y_te.sum()),
                    "natural_fraud_rate_test": float(y_te.mean())},
        "environment": {"python": platform.python_version(), "scikit_learn": sklearn.__version__,
                        "xgboost": xgb.__version__, "numpy": np.__version__, "pandas": pd.__version__},
        "notes": [
            "Only real PaySim signals are used: type, amount, balances, hour. Location/device/history are "
            "handled by the transparent rule layer (fraud.context), not by the model.",
            "Probabilities are prior-corrected to the natural fraud rate; threshold maximises F1 on validation.",
            "PaySim frauds almost always empty the sender's account; expect optimistic scores versus real traffic.",
        ],
        "quick_run": bool(quick),
    }
    log(f"Training finished in {(time.time() - started) / 60:.1f} min")
    system.is_trained = True
    return system
