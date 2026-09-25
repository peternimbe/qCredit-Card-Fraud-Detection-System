"""Quantum-inspired optimisers (Layer 3).

These are *classical* algorithms that borrow ideas from quantum computing:
each candidate is a register of "Q-bits" whose angle theta gives the probability
sin^2(theta) of observing a 1.  A rotation gate nudges the angles toward the best
solution found so far, so the population gradually collapses onto good subsets
while keeping exploration alive.  No quantum hardware is used or claimed.

Three feature selectors are provided so they can be compared with one another:

1. ``select_kbest``               classical filter baseline (ANOVA F-score)
2. ``quantum_genetic_select``     Q-bit genetic algorithm (rotation gate + quantum mutation)
3. ``quantum_de_select``          quantum-inspired differential evolution (angle-space DE)

All three are scored by the *same* fitness function: average precision (PR-AUC)
of a small XGBoost model on a hold-out split, with a tiny parsimony penalty.  PR-AUC
is used instead of ROC-AUC because ROC-AUC saturates near 1.0 on rare-fraud data.
"""
from __future__ import annotations

import time
from typing import Callable

import numpy as np
from sklearn.feature_selection import SelectKBest, f_classif
from sklearn.metrics import average_precision_score
from sklearn.model_selection import StratifiedKFold, train_test_split
from xgboost import XGBClassifier

HALF_PI = np.pi / 2
THETA_MIN, THETA_MAX = 0.06, HALF_PI - 0.06


# ---------------------------------------------------------------- fitness
class SubsetFitness:
    """Cached hold-out fitness of a feature subset."""

    def __init__(self, X: np.ndarray, y: np.ndarray, seed: int = 42, penalty: float = 0.005, n_jobs: int = 2,
                 min_k: int = 1):
        self.n_features = X.shape[1]
        self.min_k = min_k  # subsets smaller than this are invalid (fitness 0): keeps explanations broad
        self.penalty = penalty
        self.seed = seed
        self.n_jobs = n_jobs
        self.Xtr, self.Xva, self.ytr, self.yva = train_test_split(
            X, y, test_size=0.3, stratify=y, random_state=seed
        )
        self.cache: dict[tuple, float] = {}
        self.evaluations = 0

    def average_precision(self, columns: np.ndarray) -> float:
        model = XGBClassifier(
            n_estimators=40, max_depth=3, learning_rate=0.3, subsample=0.9, tree_method="hist",
            n_jobs=self.n_jobs, random_state=self.seed, eval_metric="logloss", verbosity=0,
        )
        model.fit(self.Xtr[:, columns], self.ytr)
        return float(average_precision_score(self.yva, model.predict_proba(self.Xva[:, columns])[:, 1]))

    def __call__(self, mask: np.ndarray) -> float:
        columns = np.flatnonzero(np.asarray(mask) > 0)
        if columns.size < max(self.min_k, 1):
            return 0.0
        key = tuple(columns.tolist())
        if key not in self.cache:
            self.evaluations += 1
            self.cache[key] = self.average_precision(columns) - self.penalty * columns.size / self.n_features
        return self.cache[key]


def _result(columns: np.ndarray, fitness: SubsetFitness, started: float, history: list[float], params: dict) -> dict:
    columns = np.sort(np.asarray(columns, dtype=int))
    mask = np.zeros(fitness.n_features, dtype=int)
    mask[columns] = 1
    return {
        "features": columns.tolist(),
        "k": int(columns.size),
        "fitness": float(fitness(mask)),
        "holdout_average_precision": float(fitness.average_precision(columns)),
        "evaluations": int(fitness.evaluations),
        "runtime_s": round(time.time() - started, 2),
        "history": [round(h, 5) for h in history],
        "params": params,
    }


# ---------------------------------------------------------------- 1. classical baseline
def select_kbest(fitness: SubsetFitness, k: int) -> dict:
    started = time.time()
    fitness.evaluations = 0
    selector = SelectKBest(score_func=f_classif, k=min(k, fitness.n_features)).fit(
        np.vstack([fitness.Xtr, fitness.Xva]), np.concatenate([fitness.ytr, fitness.yva])
    )
    columns = selector.get_support(indices=True)
    return _result(columns, fitness, started, [], {"score_func": "f_classif", "k": int(k)})


# ---------------------------------------------------------------- 2. Q-bit genetic algorithm
def quantum_genetic_select(fitness: SubsetFitness, population: int = 16, iterations: int = 14,
                           rotation: float = 0.12, mutation_rate: float = 0.03, seed: int = 42) -> dict:
    """Han & Kim style quantum-inspired evolutionary algorithm for feature subsets."""
    rng = np.random.default_rng(seed)
    started = time.time()
    fitness.evaluations = 0
    n = fitness.n_features
    theta = np.full((population, n), np.pi / 4)  # sin^2(pi/4) = 0.5: uniform superposition

    def observe(angles: np.ndarray) -> np.ndarray:
        bits = (rng.random(angles.shape) < np.sin(angles) ** 2).astype(int)
        empty = bits.sum(axis=1) == 0
        bits[empty, rng.integers(0, n, empty.sum())] = 1
        return bits

    best_bits, best_score, history = None, -np.inf, []
    for it in range(iterations):
        bits = observe(theta)
        scores = np.array([fitness(b) for b in bits])
        top = int(scores.argmax())
        if scores[top] > best_score:
            best_score, best_bits = float(scores[top]), bits[top].copy()
        history.append(best_score)

        delta = rotation * (1 - it / iterations) + 0.02  # decaying rotation-gate step
        # Rotation gate: move every Q-bit toward the global best (or away if it disagrees).
        direction = np.where(best_bits[None, :] == 1, 1.0, -1.0)
        theta = np.clip(theta + delta * direction, THETA_MIN, THETA_MAX)
        # Quantum mutation: swap amplitudes (theta -> pi/2 - theta) for a few Q-bits.
        flip = rng.random(theta.shape) < mutation_rate
        theta = np.where(flip, HALF_PI - theta, theta)

    return _result(np.flatnonzero(best_bits), fitness, started, history,
                   {"population": population, "iterations": iterations, "rotation": rotation,
                    "mutation_rate": mutation_rate, "penalty": fitness.penalty})


# ---------------------------------------------------------------- 3. quantum-inspired differential evolution
def quantum_de_select(fitness: SubsetFitness, k: int, population: int = 12, iterations: int = 12,
                      mutation_factor: float = 0.8, crossover_rate: float = 0.9,
                      rotation: float = 0.05, seed: int = 42) -> dict:
    """Differential evolution in Q-bit angle space; a subset is the top-k most probable bits."""
    rng = np.random.default_rng(seed)
    started = time.time()
    fitness.evaluations = 0
    n = fitness.n_features
    k = min(k, n)

    def decode(angles: np.ndarray) -> np.ndarray:
        mask = np.zeros(n, dtype=int)
        mask[np.argsort(-np.sin(angles) ** 2, kind="stable")[:k]] = 1
        return mask

    pop = rng.uniform(THETA_MIN, THETA_MAX, size=(population, n))
    scores = np.array([fitness(decode(p)) for p in pop])
    history = [float(scores.max())]

    for _ in range(iterations):
        best_angles = pop[scores.argmax()]
        for i in range(population):
            a, b, c = pop[rng.choice([j for j in range(population) if j != i], 3, replace=False)]
            mutant = a + mutation_factor * (b - c)
            cross = rng.random(n) < crossover_rate
            cross[rng.integers(n)] = True
            trial = np.where(cross, mutant, pop[i])
            # Rotation gate toward the global best keeps the quantum-inspired pressure on.
            trial = trial + rotation * np.sign(best_angles - trial)
            trial = np.clip(trial, THETA_MIN, THETA_MAX)
            trial_score = fitness(decode(trial))
            if trial_score >= scores[i]:
                pop[i], scores[i] = trial, trial_score
        history.append(float(scores.max()))

    best = decode(pop[scores.argmax()])
    return _result(np.flatnonzero(best), fitness, started, history,
                   {"population": population, "iterations": iterations, "mutation_factor": mutation_factor,
                    "crossover_rate": crossover_rate, "rotation": rotation, "target_k": int(k),
                    "penalty": fitness.penalty})


# ---------------------------------------------------------------- hyper-parameter search
def quantum_inspired_search(grid: dict[str, list], objective: Callable[[dict], float], population: int = 5,
                            iterations: int = 4, learning_rate: float = 0.35, seed: int = 42) -> dict:
    """Quantum-inspired evolutionary search over a discrete hyper-parameter grid.

    Each parameter is a register whose basis states are the grid values.  A state's
    probability is |amplitude|^2; observing the register samples a value.  After each
    generation the amplitudes rotate toward the best configuration found so far.
    """
    rng = np.random.default_rng(seed)
    started = time.time()
    names = list(grid)
    probs = {name: np.full(len(grid[name]), 1.0 / len(grid[name])) for name in names}
    cache: dict[tuple, float] = {}
    best, best_score, history = None, -np.inf, []

    def evaluate(choice: dict[str, int]) -> float:
        key = tuple(choice[n] for n in names)
        if key not in cache:
            cache[key] = float(objective({n: grid[n][choice[n]] for n in names}))
        return cache[key]

    for _ in range(iterations):
        for _ in range(population):
            choice = {n: int(rng.choice(len(grid[n]), p=probs[n])) for n in names}
            score = evaluate(choice)
            if score > best_score:
                best_score, best = score, choice
        history.append(best_score)
        for n in names:  # rotation toward the best state, floored so no state vanishes
            target = np.zeros(len(grid[n]))
            target[best[n]] = 1.0
            amplitude = np.sqrt(probs[n])
            amplitude = (1 - learning_rate) * amplitude + learning_rate * np.sqrt(target)
            probs[n] = np.maximum(amplitude ** 2, 0.02)
            probs[n] /= probs[n].sum()

    return {
        "best_params": {n: grid[n][best[n]] for n in names},
        "best_score": float(best_score),
        "evaluations": len(cache),
        "runtime_s": round(time.time() - started, 2),
        "history": [round(h, 5) for h in history],
        "grid": grid,
    }


def cv_average_precision(make_model: Callable[[], object], X: np.ndarray, y: np.ndarray, folds: int = 3, seed: int = 42) -> float:
    scores = []
    for train_idx, valid_idx in StratifiedKFold(folds, shuffle=True, random_state=seed).split(X, y):
        model = make_model()
        model.fit(X[train_idx], y[train_idx])
        scores.append(average_precision_score(y[valid_idx], model.predict_proba(X[valid_idx])[:, 1]))
    return float(np.mean(scores))
