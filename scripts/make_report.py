"""Render docs/RESULTS.md from models/metrics.json + metadata.json (never hand-edit the numbers).

    python scripts/make_report.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
meta = json.loads((ROOT / "models" / "metadata.json").read_text())
rep = json.loads((ROOT / "models" / "metrics.json").read_text())
test, base = rep["test_metrics"], rep["baseline_old_configuration"]["test_metrics"]
champ = meta["champion"]


def pct(x): return f"{x * 100:.2f}%"


def row(name, m, extra=""):
    return f"| {name} | {m['average_precision']:.4f} | {m['roc_auc']:.4f} | {pct(m['precision'])} | {pct(m['recall'])} | {pct(m['f1'])} |{extra}"


HEAD = "| Model | PR-AUC | ROC-AUC | Precision | Recall | F1 |"
SEP = "|---|---|---|---|---|---|"
out = []
ds = meta["dataset"]
out += [f"# Results ({meta['model_version']})", "",
        f"Trained {meta['trained_at']} on PaySim. Test set: **{ds['test_rows']:,} transactions, {ds['test_frauds']:,} frauds "
        f"({ds['natural_fraud_rate_test'] * 100:.3f}% - the natural rate)**. Validation and test were never re-balanced; only the "
        "training split was under-sampled, and probabilities are corrected back to the natural prior.", "",
        f"**Champion:** `{champ}` (chosen on validation PR-AUC, ties resolved toward the richer model) - decision threshold "
        f"{meta['threshold']:.4f}, the F1-optimal point on validation.", "",
        "> PaySim is a simulation in which fraud almost always empties the sender's account (97.6% of frauds). Scores are therefore "
        "optimistic compared with real traffic; use them to compare pipelines, not as a production forecast.", "",
        "## Old configuration vs improved", "",
        f"Old = the original project's algorithms and hyper-parameters on raw amount/balances/type/hour. Improved = named, "
        "arithmetic features + prior correction + threshold tuning + Layer 2/3.", "", HEAD, SEP]
out += [row(f"Old `{n}`", m) for n, m in base.items()]
out += [row(f"**Improved `{champ}`**", test[champ])]
out += ["", "## All models on the test set", "", HEAD + " Layer |", SEP + "---|"]
for n, m in sorted(test.items(), key=lambda kv: -kv[1]["average_precision"]):
    out.append(row(f"`{n}`", m, f" {m['layer']} |"))

fs = rep["feature_selection"]
out += ["", "## Feature selection: SelectKBest vs quantum-inspired methods", "",
        "Same fitness for all three: PR-AUC of a small XGBoost on a hold-out split, minus a tiny parsimony penalty. "
        "`Test PR-AUC` re-trains a fixed XGBoost on the full training split with only that subset.", "",
        "| Method | k | Search fitness | Test PR-AUC | Evaluations | Runtime (s) | Features |", "|---|---|---|---|---|---|---|"]
for n, m in fs["methods"].items():
    out.append(f"| {n} | {m['k']} | {m['fitness']:.4f} | {m['test_average_precision']:.4f} | {m['evaluations']} | "
               f"{m['runtime_s']} | {', '.join(m['feature_names'])} |")
meths = {n: m for n, m in fs["methods"].items() if n != "all_features_reference"}
cheapest = min(meths, key=lambda n: meths[n]["runtime_s"])
out += ["", f"Chosen for the Layer 3 models: **{fs['chosen_method']}**. Test PR-AUC differs by only "
        f"{max(m['test_average_precision'] for m in meths.values()) - min(m['test_average_precision'] for m in meths.values()):.4f} "
        "across the three methods (the signal sits in a handful of features), so the comparison is mostly about cost and "
        f"compactness. Fastest: `{cheapest}` ({meths[cheapest]['runtime_s']} s); slowest: "
        f"`{max(meths, key=lambda n: meths[n]['runtime_s'])}` ({max(m['runtime_s'] for m in meths.values())} s).", "",
        "## Quantum-inspired hyper-parameter search", ""]
for n, s in rep["hyperparameter_search"].items():
    out.append(f"* **{n}** - best `{s['best_params']}`, CV PR-AUC {s['best_score']:.4f}, {s['evaluations']} evaluations, {s['runtime_s']} s")

if rep.get("quality_gate"):
    out += ["", "## Quality gate", "", "A tuned model that ranks clearly worse than its untuned sibling on validation is replaced by the "
            "sibling's settings (an earlier run produced a collapsed XGBoost this way):", ""]
    out += [f"* `{n}`: validation PR-AUC {g['validation_ap']:.4f} vs sibling {g['sibling_ap']:.4f} -> "
            f"{'fell back to defaults' if g['fell_back_to_defaults'] else 'kept'}" for n, g in rep["quality_gate"].items()]
rob = rep["robustness"]["recipient_balances_unknown"]
out += ["", "## Robustness: recipient balances unknown", "",
        "The sandbox app does not track recipient balances. Re-scoring the test set with them removed: "
        f"PR-AUC {rob['average_precision']:.4f}, precision {pct(rob['precision'])}, recall {pct(rob['recall'])}.", "",
        "## Global importance (mean |SHAP|, fraud-enriched sample)", "", "| Feature | Mean abs SHAP |", "|---|---|"]
out += [f"| {g['label']} | {g['mean_abs_shap']:.3f} |" for g in rep["global_importance"]]
best_name, best = max(test.items(), key=lambda kv: kv[1]["average_precision"])
top = [n for n, m in test.items() if m["average_precision"] >= best["average_precision"] - 0.002]
honest = (f"{len(top)} models are within 0.002 PR-AUC of the best on the test set ({', '.join(f'`{n}`' for n in top)}), i.e. "
          "statistically indistinguishable on this data. The jump over the old configuration comes from the named, arithmetic "
          "features and the threshold/prior handling; the ensembles and Layer 3 add diversity and robustness rather than "
          "measurable extra accuracy here.")
out += ["", "## How to read this", "", honest, "", "## Notes", ""] + [f"* {n}" for n in meta["notes"]]
(ROOT / "docs").mkdir(exist_ok=True)
(ROOT / "docs" / "RESULTS.md").write_text("\n".join(out) + "\n", encoding="utf-8")
print("wrote docs/RESULTS.md")
