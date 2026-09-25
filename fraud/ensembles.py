"""Layer 2 ensembles and the Layer 3 risk-fusion head.

Each ensemble is a small object that maps a matrix of *base-model probabilities*
``P`` (rows = transactions, columns = base models in a fixed order) to one fused
probability.  Working on probabilities means the (heavy) base models run once per
transaction no matter how many ensembles are served.

Baseline (old project)            ->  here
-------------------------------------------------------------------------------
VotingClassifier(soft)            ->  SoftVoting
VotingClassifier(weights=CV AUC)  ->  WeightedVoting  (weights = validation PR-AUC)
StackingClassifier(LR meta)       ->  StackingMeta    (LR on log-odds, out-of-fold)
AdaBoost of stumps ("adaptive")   ->  AdaptiveEnsemble (per-transaction confidence
                                       weighting) - AdaBoost is still trained and
                                       reported as ``adaboost`` for comparison.
"""
from __future__ import annotations

import numpy as np
from sklearn.linear_model import LogisticRegression

EPS = 1e-6


def logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=float), EPS, 1 - EPS)
    return np.log(p / (1 - p))


class SoftVoting:
    def predict(self, P: np.ndarray) -> np.ndarray:
        return P.mean(axis=1)


class WeightedVoting:
    def __init__(self, weights: np.ndarray):
        weights = np.asarray(weights, dtype=float)
        self.weights = weights / weights.sum()

    def predict(self, P: np.ndarray) -> np.ndarray:
        return P @ self.weights


class AdaptiveEnsemble:
    """Weights each model per transaction by how confident it is (its log-odds margin).

    A model that is sure (very high or very low probability) dominates the vote; models
    that sit near the fence are down-weighted.  Static weights (validation PR-AUC) are
    kept as a prior so a weak-but-loud model cannot take over.
    """

    def __init__(self, weights: np.ndarray, temperature: float = 4.0):
        weights = np.asarray(weights, dtype=float)
        self.weights = weights / weights.sum()
        self.temperature = temperature

    def predict(self, P: np.ndarray) -> np.ndarray:
        confidence = np.abs(logit(P))
        gate = np.exp((confidence - confidence.max(axis=1, keepdims=True)) / self.temperature) * self.weights
        gate /= gate.sum(axis=1, keepdims=True)
        return (P * gate).sum(axis=1)


class StackingMeta:
    """Logistic-regression meta-learner on the base models' log-odds."""

    def __init__(self, C: float = 1.0):
        self.model = LogisticRegression(C=C, max_iter=1000)

    def fit(self, P: np.ndarray, y: np.ndarray) -> "StackingMeta":
        self.model.fit(logit(P), y)
        return self

    def predict(self, P: np.ndarray) -> np.ndarray:
        return self.model.predict_proba(logit(P))[:, 1]


class RiskFusion:
    """Layer 3 head: fuses ensemble output, optimised models and the anomaly score.

    Inputs (columns): log-odds of each supplied probability plus the anomaly percentile.
    """

    def __init__(self, C: float = 1.0):
        self.model = LogisticRegression(C=C, max_iter=1000)

    @staticmethod
    def design(P: np.ndarray, anomaly: np.ndarray) -> np.ndarray:
        return np.column_stack([logit(P), np.asarray(anomaly, dtype=float)])

    def fit(self, P: np.ndarray, anomaly: np.ndarray, y: np.ndarray) -> "RiskFusion":
        self.model.fit(self.design(P, anomaly), y)
        return self

    def predict(self, P: np.ndarray, anomaly: np.ndarray) -> np.ndarray:
        return self.model.predict_proba(self.design(P, anomaly))[:, 1]


class AnomalyScorer:
    """Isolation Forest turned into a 0-1 percentile against normal (legitimate) traffic."""

    def __init__(self, forest, reference_scores: np.ndarray):
        self.forest = forest
        self.reference = np.sort(np.asarray(reference_scores, dtype=float))

    def raw(self, X: np.ndarray) -> np.ndarray:
        return -self.forest.score_samples(X)  # higher = more unusual

    def percentile(self, X: np.ndarray) -> np.ndarray:
        return np.searchsorted(self.reference, self.raw(X)) / max(len(self.reference), 1)
