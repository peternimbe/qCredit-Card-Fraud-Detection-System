# Results (2.0.0-2026-09-19)

Trained 2026-09-19T21:41:10+00:00 on PaySim. Test set: **1,272,800 transactions, 1,676 frauds (0.132% - the natural rate)**. Validation and test were never re-balanced; only the training split was under-sampled, and probabilities are corrected back to the natural prior.

**Champion:** `quantum_enhanced` (chosen on validation PR-AUC, ties resolved toward the richer model) - decision threshold 0.5611, the F1-optimal point on validation.

> PaySim is a simulation in which fraud almost always empties the sender's account (97.6% of frauds). Scores are therefore optimistic compared with real traffic; use them to compare pipelines, not as a production forecast.

## Old configuration vs improved

Old = the original project's algorithms and hyper-parameters on raw amount/balances/type/hour. Improved = named, arithmetic features + prior correction + threshold tuning + Layer 2/3.

| Model | PR-AUC | ROC-AUC | Precision | Recall | F1 |
|---|---|---|---|---|---|
| Old `logistic_regression` | 0.6290 | 0.9893 | 81.56% | 49.88% | 61.90% |
| Old `decision_tree` | 0.7300 | 0.9923 | 84.59% | 78.58% | 81.47% |
| Old `xgboost` | 0.9401 | 0.9991 | 93.36% | 83.83% | 88.34% |
| Old `random_forest` | 0.8824 | 0.9984 | 92.16% | 82.04% | 86.81% |
| Old `soft_voting` | 0.8972 | 0.9989 | 95.34% | 78.16% | 85.90% |
| **Improved `quantum_enhanced`** | 0.9975 | 0.9992 | 100.00% | 99.46% | 99.73% |

## All models on the test set

| Model | PR-AUC | ROC-AUC | Precision | Recall | F1 | Layer |
|---|---|---|---|---|---|---|
| `xgboost` | 0.9976 | 0.9994 | 100.00% | 99.46% | 99.73% | layer1 |
| `quantum_enhanced` | 0.9975 | 0.9992 | 100.00% | 99.46% | 99.73% | layer3 |
| `adaptive_ensemble` | 0.9975 | 0.9992 | 99.94% | 99.40% | 99.67% | layer2 |
| `soft_voting` | 0.9975 | 0.9992 | 100.00% | 99.34% | 99.67% | layer2 |
| `weighted_voting` | 0.9975 | 0.9992 | 100.00% | 99.34% | 99.67% | layer2 |
| `stacking` | 0.9974 | 0.9992 | 100.00% | 99.16% | 99.58% | layer2 |
| `random_forest` | 0.9974 | 0.9993 | 100.00% | 99.34% | 99.67% | layer1 |
| `random_forest_optimized` | 0.9973 | 0.9993 | 99.40% | 99.52% | 99.46% | layer3 |
| `xgboost_optimized` | 0.9973 | 0.9991 | 99.34% | 99.52% | 99.43% | layer3 |
| `adaboost` | 0.9948 | 0.9990 | 99.52% | 98.09% | 98.80% | layer1 |
| `logistic_regression` | 0.9940 | 0.9984 | 99.28% | 98.87% | 99.07% | layer1 |
| `decision_tree` | 0.9525 | 0.9992 | 95.48% | 99.64% | 97.52% | layer1 |

## Feature selection: SelectKBest vs quantum-inspired methods

Same fitness for all three: PR-AUC of a small XGBoost on a hold-out split, minus a tiny parsimony penalty. `Test PR-AUC` re-trains a fixed XGBoost on the full training split with only that subset.

| Method | k | Search fitness | Test PR-AUC | Evaluations | Runtime (s) | Features |
|---|---|---|---|---|---|---|
| selectkbest | 12 | 0.9946 | 0.9974 | 1 | 14.81 | amount, oldbalanceOrg, newbalanceOrig, is_night, orig_balance_error, dest_balance_error, amount_to_balance_ratio, orig_drained, amount_exceeds_balance, dest_empty_before, dest_unchanged, type_TRANSFER |
| quantum_genetic | 8 | 0.9956 | 0.9966 | 131 | 56.42 | oldbalanceOrg, newbalanceDest, orig_balance_error, dest_balance_error, amount_to_balance_ratio, dest_empty_before, dest_unchanged, type_PAYMENT |
| quantum_differential_evolution | 12 | 0.9950 | 0.9976 | 106 | 44.99 | amount, oldbalanceOrg, newbalanceOrig, oldbalanceDest, hour_of_day, is_night, orig_balance_error, orig_drained, amount_exceeds_balance, dest_empty_before, type_CASH_OUT, type_TRANSFER |
| all_features_reference | 19 | 0.9929 | 0.9975 | 1 | 0.0 | amount, oldbalanceOrg, newbalanceOrig, oldbalanceDest, newbalanceDest, dest_balance_known, hour_of_day, is_night, orig_balance_error, dest_balance_error, amount_to_balance_ratio, orig_drained, amount_exceeds_balance, dest_empty_before, dest_unchanged, type_CASH_OUT, type_DEBIT, type_PAYMENT, type_TRANSFER |

Chosen for the Layer 3 models: **quantum_genetic**. Test PR-AUC differs by only 0.0010 across the three methods (the signal sits in a handful of features), so the comparison is mostly about cost and compactness. Fastest: `selectkbest` (14.81 s); slowest: `quantum_genetic` (56.42 s).

## Quantum-inspired hyper-parameter search

* **xgboost** - best `{'max_depth': 6, 'learning_rate': 0.05, 'n_estimators': 300, 'subsample': 0.85, 'min_child_weight': 1}`, CV PR-AUC 0.9984, 14 evaluations, 57.0 s
* **random_forest** - best `{'n_estimators': 80, 'max_depth': 10, 'min_samples_leaf': 5, 'max_features': 0.5}`, CV PR-AUC 0.9986, 8 evaluations, 62.23 s

## Quality gate

A tuned model that ranks clearly worse than its untuned sibling on validation is replaced by the sibling's settings (an earlier run produced a collapsed XGBoost this way):

* `xgboost_optimized`: validation PR-AUC 0.9972 vs sibling 0.9981 -> kept
* `random_forest_optimized`: validation PR-AUC 0.9981 vs sibling 0.9989 -> kept

## Robustness: recipient balances unknown

The sandbox app does not track recipient balances. Re-scoring the test set with them removed: PR-AUC 0.9963, precision 100.00%, recall 97.32%.

## Global importance (mean |SHAP|, fraud-enriched sample)

| Feature | Mean abs SHAP |
|---|---|
| Sender balance mismatch | 3.805 |
| Account emptied | 2.264 |
| Recipient balance mismatch | 1.211 |
| Transaction amount | 0.878 |
| Sender balance after | 0.636 |
| Transaction type: cash-out / withdrawal | 0.577 |
| Share of balance being moved | 0.557 |
| Hour of day | 0.518 |
| Recipient account was empty | 0.437 |
| Sender balance before | 0.396 |
| Recipient balance before | 0.269 |
| Recipient balance did not change | 0.230 |
| Transaction type: payment | 0.208 |
| Transaction type: transfer | 0.152 |
| Recipient balance after | 0.077 |
| Amount exceeds available balance | 0.031 |
| Recipient balance available | 0.013 |
| Night-time transaction | 0.000 |
| Transaction type: debit | 0.000 |

## How to read this

9 models are within 0.002 PR-AUC of the best on the test set (`xgboost`, `random_forest`, `xgboost_optimized`, `random_forest_optimized`, `soft_voting`, `weighted_voting`, `stacking`, `adaptive_ensemble`, `quantum_enhanced`), i.e. statistically indistinguishable on this data. The jump over the old configuration comes from the named, arithmetic features and the threshold/prior handling; the ensembles and Layer 3 add diversity and robustness rather than measurable extra accuracy here.

## Notes

* Only real PaySim signals are used: type, amount, balances, hour. Location/device/history are handled by the transparent rule layer (fraud.context), not by the model.
* Probabilities are prior-corrected to the natural fraud rate; threshold maximises F1 on validation.
* PaySim frauds almost always empty the sender's account; expect optimistic scores versus real traffic.
