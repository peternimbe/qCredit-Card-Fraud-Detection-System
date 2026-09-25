# Feature selection: classical baseline vs two quantum-inspired methods

Numbers for the current model are in [RESULTS.md](RESULTS.md) (generated). This page explains the three methods.
All three are scored by the same fitness: PR-AUC of a small XGBoost on a hold-out split, minus a tiny parsimony
penalty, with a minimum subset size of 8 so explanations stay broad.

| | SelectKBest (baseline) | Quantum-inspired genetic (Q-bit GA) | Quantum-inspired differential evolution (QDE) |
|---|---|---|---|
| Idea | Rank each feature alone by ANOVA F-score, keep the top *k* | Each feature is a Q-bit with angle theta, P(keep) = sin^2(theta); a rotation gate pulls angles toward the best subset found; quantum mutation swaps amplitudes | DE (mutation + crossover + greedy selection) in Q-bit angle space; a subset is the *k* most probable bits, with a rotation gate toward the global best |
| Uses feature interactions | No | Yes (subsets are evaluated with a model) | Yes |
| Subset size | fixed *k* | free (>= 8) | fixed *k* |
| Cost | one pass | ~10^2 model fits | ~10^2 model fits |
| Randomness | none | yes (seeded) | yes (seeded) |
| Easy to explain to non-specialists | very | moderate | least |

**What we actually found:** on PaySim the three methods end within about 0.001 test PR-AUC of each other, because the
signal sits in a handful of features (balances, recipient state, transaction type). The quantum-inspired searches are
several times slower for essentially the same accuracy here; they earn their keep only when interactions matter
and the feature set is large. "Quantum-inspired" means classical algorithms that borrow quantum ideas - no quantum
hardware is used.
