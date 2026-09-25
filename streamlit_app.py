"""Smart Detector dashboard (Streamlit).

Every number on the performance pages comes from the API's /metrics endpoint, i.e. from the
held-out test set evaluated at training time - nothing here is hard-coded.

    streamlit run streamlit_app.py            # API_URL defaults to http://localhost:8000
"""
import os

import pandas as pd
import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8000").rstrip("/")

st.set_page_config(page_title="Smart Detector", page_icon="🛡️", layout="wide")

RISK_ICON = {"High Risk": "🔴", "Medium Risk": "🟠", "Low Risk": "🟡", "Very Low Risk": "🟢"}
LAYER_NAMES = {"layer1": "Layer 1 - real-time screening", "layer2": "Layer 2 - ensembles", "layer3": "Layer 3 - quantum-inspired"}


@st.cache_data(ttl=60, show_spinner=False)
def api_get(path: str):
    response = requests.get(f"{API_URL}{path}", timeout=30)
    response.raise_for_status()
    return response.json()


def api_post(path: str, payload):
    response = requests.post(f"{API_URL}{path}", json=payload, timeout=60)
    response.raise_for_status()
    return response.json()


def api_ok() -> bool:
    try:
        return requests.get(f"{API_URL}/health", timeout=10).json().get("model_loaded", False)
    except Exception:
        return False


def pct(value) -> str:
    return f"{value * 100:.2f}%" if value is not None else "-"


# ------------------------------------------------------------------ pages
def page_single():
    st.header("Single transaction check")
    st.caption("Enter the transaction in plain terms. The model only uses named inputs such as balances and amounts.")
    with st.form("tx"):
        left, right = st.columns(2)
        with left:
            tx_type = st.selectbox("Transaction type", ["PAYMENT", "TRANSFER", "CASH_OUT", "CASH_IN", "DEBIT"])
            amount = st.number_input("Amount", min_value=0.0, value=250.0, step=10.0)
            before = st.number_input("Sender balance before", min_value=0.0, value=1000.0, step=10.0)
            after = st.number_input("Sender balance after", min_value=0.0, value=750.0, step=10.0)
            hour = st.slider("Hour of day", 0, 23, 14)
        with right:
            known = st.checkbox("Recipient balances are known", value=False)
            dest_before = st.number_input("Recipient balance before", min_value=0.0, value=0.0, step=10.0, disabled=not known)
            dest_after = st.number_input("Recipient balance after", min_value=0.0, value=0.0, step=10.0, disabled=not known)
            impossible = st.checkbox("Impossible travel detected (context rule)")
            new_device = st.checkbox("New device (context rule)")
        submitted = st.form_submit_button("🔍 Check for fraud", type="primary")

    if not submitted:
        return
    payload = {"transaction_type": tx_type, "amount": amount, "oldbalanceOrg": before, "newbalanceOrig": after,
               "hour_of_day": hour, "impossible_travel_flag": int(impossible), "is_new_device": int(new_device)}
    if known:
        payload.update(oldbalanceDest=dest_before, newbalanceDest=dest_after)
    try:
        result = api_post("/predict_named", payload)
    except Exception as error:
        st.error(f"Could not score the transaction: {error}")
        return

    icon = RISK_ICON.get(result["risk_level"], "")
    a, b, c = st.columns(3)
    a.metric("Fraud probability", pct(result["fraud_probability"]))
    b.metric("Risk level", f"{icon} {result['risk_level']}")
    c.metric("Decision threshold", pct(result["threshold"]))
    if result["is_fraudulent"]:
        st.error("🚨 The model flags this transaction as likely fraud.")
    elif result["review_required"]:
        st.warning("⚠️ Below the model threshold, but context rules ask for a manual review.")
    else:
        st.success("✅ Transaction appears legitimate.")

    explanation = result.get("explanation") or {}
    st.subheader("Why?")
    st.write(explanation.get("reason", ""))
    impacts = pd.DataFrame(explanation.get("feature_impacts", []))
    if not impacts.empty:
        st.dataframe(impacts[["label", "value", "impact_pct", "direction", "description"]]
                     .rename(columns={"label": "Signal", "value": "Value", "impact_pct": "Impact %",
                                      "direction": "Effect", "description": "In plain words"}),
                     hide_index=True, use_container_width=True)
        st.bar_chart(impacts.set_index("label")["contribution"])
    for flag in result.get("context_flags", []):
        st.warning(f"**{flag['label']}** - {flag['detail']}")
    for warning in result.get("input_warnings", []):
        st.info(warning)

    with st.expander("Scores from every model"):
        scores = pd.Series(result["model_scores"], name="fraud probability").sort_values(ascending=False)
        st.dataframe(scores.to_frame().assign(champion=lambda d: d.index == result["champion_model"]), use_container_width=True)


def page_batch():
    st.header("Batch analysis")
    st.caption("Upload a CSV with named columns: transaction_type, amount, oldbalanceOrg, newbalanceOrig "
               "(optional: oldbalanceDest, newbalanceDest, hour_of_day).")
    upload = st.file_uploader("CSV file", type="csv")
    if upload is None:
        return
    frame = pd.read_csv(upload)
    st.dataframe(frame.head(), use_container_width=True)
    if not st.button("Analyze batch", type="primary"):
        return
    records = frame.where(frame.notna(), None).to_dict("records")
    predictions = []
    for start in range(0, len(records), 2000):
        predictions += api_post("/predict_batch", records[start:start + 2000])["predictions"]
    out = frame.copy()
    out["fraud_probability"] = [p["fraud_probability"] for p in predictions]
    out["is_fraudulent"] = [p["is_fraudulent"] for p in predictions]
    out["risk_level"] = [p["risk_level"] for p in predictions]
    st.metric("Flagged as fraud", f"{int(out['is_fraudulent'].sum()):,} of {len(out):,}")
    st.dataframe(out.sort_values("fraud_probability", ascending=False), use_container_width=True)
    st.download_button("Download results", out.to_csv(index=False), "scored_transactions.csv")


def metrics_table(block: dict) -> pd.DataFrame:
    rows = []
    for name, m in block.items():
        rows.append({"Model": name, "PR-AUC": m["average_precision"], "ROC-AUC": m["roc_auc"], "Precision": m["precision"],
                     "Recall": m["recall"], "F1": m["f1"], "False-positive rate": m["false_positive_rate"],
                     "Precision@100": m.get("precision_at_100"), "Layer": m.get("layer", "")})
    return pd.DataFrame(rows).sort_values("PR-AUC", ascending=False)


def page_performance():
    st.header("Model performance")
    try:
        report = api_get("/metrics")
    except Exception as error:
        st.error(f"Could not load metrics: {error}")
        return
    meta, test = report["metadata"], report["test_metrics"]
    champion = meta["champion"]
    ds = meta["dataset"]
    st.caption(f"Model {meta['model_version']} - trained {meta['trained_at'][:10]} - evaluated on {ds['test_rows']:,} unseen "
               f"transactions ({ds['test_frauds']:,} frauds, natural rate {ds['natural_fraud_rate_test'] * 100:.3f}%).")
    champ = test[champion]
    baseline = report["baseline_old_configuration"]["test_metrics"]["soft_voting"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Champion", champion)
    c2.metric("PR-AUC", f"{champ['average_precision']:.4f}", f"{champ['average_precision'] - baseline['average_precision']:+.4f} vs old")
    c3.metric("Fraud recall", pct(champ["recall"]), f"{(champ['recall'] - baseline['recall']) * 100:+.1f} pts vs old")
    c4.metric("Precision", pct(champ["precision"]), f"{(champ['precision'] - baseline['precision']) * 100:+.1f} pts vs old")
    st.info("PaySim is a simulation in which fraud almost always empties the sender's account, so scores here are "
            "optimistic compared with real-world traffic. Treat them as a benchmark for the pipeline, not a promise.")

    tab_all, tab_base, tab_fs, tab_hp, tab_imp, tab_rob = st.tabs(
        ["All models", "Old vs improved", "Feature selection", "Hyper-parameter search", "Global importance", "Robustness"])
    with tab_all:
        table = metrics_table(test)
        st.dataframe(table.style.format({c: "{:.4f}" for c in table.columns if c not in ("Model", "Layer")}),
                     hide_index=True, use_container_width=True)
    with tab_base:
        old = metrics_table(report["baseline_old_configuration"]["test_metrics"]).assign(Configuration="Old (raw inputs)")
        new = metrics_table({k: v for k, v in test.items() if k in old["Model"].values}).assign(Configuration="Improved (named features)")
        combined = pd.concat([old, new])
        st.caption(report["baseline_old_configuration"]["description"])
        st.dataframe(combined[["Configuration", "Model", "PR-AUC", "Precision", "Recall", "F1"]]
                     .style.format({c: "{:.4f}" for c in ("PR-AUC", "Precision", "Recall", "F1")}),
                     hide_index=True, use_container_width=True)
        st.bar_chart(combined.pivot(index="Model", columns="Configuration", values="Recall"))
    with tab_fs:
        methods = report["feature_selection"]["methods"]
        rows = [{"Method": n, "Features kept": m["k"], "Search fitness": m["fitness"], "Test PR-AUC": m["test_average_precision"],
                 "Evaluations": m["evaluations"], "Runtime (s)": m["runtime_s"], "Selected": ", ".join(m["feature_names"])}
                for n, m in methods.items()]
        st.write(f"Chosen for Layer 3: **{report['feature_selection']['chosen_method']}**")
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    with tab_hp:
        for name, search in report["hyperparameter_search"].items():
            st.subheader(name)
            st.json({"best_params": search["best_params"], "cv_average_precision": search["best_score"],
                     "evaluations": search["evaluations"], "runtime_s": search["runtime_s"]})
    with tab_imp:
        importance = pd.DataFrame(report["global_importance"]).set_index("label")["mean_abs_shap"]
        st.caption("Mean |SHAP| of the XGBoost model on a fraud-enriched sample of the test set.")
        st.bar_chart(importance)
    with tab_rob:
        rob = report["robustness"]["recipient_balances_unknown"]
        st.write("Champion re-scored on the test set with **recipient balances removed** (what a sandbox that does not "
                 "track recipients sends).")
        st.dataframe(pd.DataFrame([{"PR-AUC": rob["average_precision"], "Precision": rob["precision"], "Recall": rob["recall"],
                                    "F1": rob["f1"]}]), hide_index=True)


def page_architecture():
    st.header("System architecture")
    info = api_get("/model-info")
    for layer, models in info["layers"].items():
        st.subheader(LAYER_NAMES[layer])
        st.write(", ".join(f"`{m}`" for m in models))
    st.markdown(f"""
**Named features ({len(info['feature_names'])}):** {', '.join(f'`{f}`' for f in info['feature_names'])}

**Selected by the quantum-inspired search:** {', '.join(f'`{f}`' for f in info['selected_features'])}

**Explanations:** exact TreeSHAP on the XGBoost model, phrased in plain English.

**Context rules:** location, device and activity signals are evaluated by transparent rules
(`fraud/context.py`) and shown beside - never mixed into - the model probability.
""")
    st.graphviz_chart("""
    digraph { rankdir=LR; node [shape=box, style=filled, fillcolor=lightblue];
      T [label="Transaction\\n(named fields)"]; F [label="Feature engineering\\n(balance checks, ...)"];
      L1 [label="Layer 1\\nLR / DT / XGB / RF"]; L2 [label="Layer 2\\nvoting / stacking / adaptive"];
      L3 [label="Layer 3\\nquantum-selected features,\\ntuned models, anomaly, fusion"];
      R [label="Score + SHAP reason\\n+ context flags"];
      T -> F -> L1 -> L2 -> L3 -> R; }
    """)


def main():
    st.title("🛡️ Smart Detector")
    st.caption("Three-layer, explainable fraud detection with quantum-inspired optimisation.")
    if api_ok():
        st.sidebar.success("✅ API connected")
    else:
        st.sidebar.error("❌ API not reachable")
        st.error(f"Cannot reach the API at {API_URL}. Start it with `uvicorn api:app --port 8000` "
                 "or set the API_URL environment variable.")
        st.stop()
    page = st.sidebar.radio("Page", ["Single transaction", "Batch analysis", "Model performance", "Architecture"])
    {"Single transaction": page_single, "Batch analysis": page_batch,
     "Model performance": page_performance, "Architecture": page_architecture}[page]()


if __name__ == "__main__":
    main()
