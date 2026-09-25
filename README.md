# Smart Detector - explainable, three-layer fraud detection

Credit-card / mobile-money fraud detection with **multiple machine-learning algorithms**, **quantum-inspired
optimisation** and **explanations a security analyst can read** - wired to the SimplePay sandbox app and ready to
host on Render.

## Why this version exists

The first version trained on the Kaggle `creditcard.csv`, whose inputs are PCA components (`V1`-`V28`). The model could
say "V14 is high" but nobody could say what V14 *is*, and the sandbox could not build V1-V28 from a real payment form.
This version keeps the same architecture but runs on **named features** - amounts, balances, transaction type, hour of
day and simple arithmetic on those ("the sender's account was emptied") - so every decision is explained in plain words
and the sandbox can send exactly what the model needs.

## Architecture

| Layer | What | Where |
|---|---|---|
| **1 - real-time screening** | Logistic Regression, Decision Tree, XGBoost, Random Forest (+ AdaBoost baseline), original hyper-parameters | `fraud/training.py` |
| **2 - ensembles** | Soft voting, weighted voting (validation PR-AUC), stacking (out-of-fold LR), adaptive ensemble (per-transaction confidence) | `fraud/ensembles.py` |
| **3 - quantum-inspired** | Feature selection: SelectKBest vs Q-bit genetic vs quantum DE; Q-bit hyper-parameter search; Isolation-Forest anomaly score; risk fusion (`quantum_enhanced`) | `fraud/quantum.py` |
| **Context rules** | Impossible travel, new device + high value, burst / rapid withdrawals, optional country watch-list - transparent rules shown *beside* the ML score | `fraud/context.py` |
| **Explanations** | Exact TreeSHAP on XGBoost, phrased with named features, only *material* drivers are narrated | `fraud/system.py` |

"Quantum-inspired" means classical algorithms borrowing ideas from quantum computing (Q-bit angles, rotation gates,
quantum mutation). No quantum hardware is involved or claimed.

## Results (held-out test set, natural 0.13 % fraud rate)

| | PR-AUC | Precision | Fraud recall |
|---|---|---|---|
| Old configuration (raw inputs, original algorithms) | 0.897 | 95.3 % | 78.2 % |
| **This version (`quantum_enhanced` champion)** | **0.9975** | **100 %** (0 false alarms in 1.27 M) | **99.5 %** (9 of 1,676 missed) |
| ...with recipient balances hidden (what the sandbox sends) | 0.996 | 100 % | 97.3 % |

Read [docs/RESULTS.md](docs/RESULTS.md) (generated from `models/metrics.json`) before quoting these. **PaySim is a
simulation in which fraud almost always empties the sender's account**, so scores are optimistic versus real traffic,
and eight models tie within noise - the gain over the old configuration comes from the named features, not from
extra layers.

## Quick start (local)

```bash
pip install -r requirements.txt           # API + models (pinned)
uvicorn api:app --reload --port 8000      # http://localhost:8000/docs
pip install -r requirements-dashboard.txt
streamlit run streamlit_app.py            # dashboard, talks to the API
python scripts/smoke_test.py              # end-to-end check
```

XAMPP: keep the repo under `htdocs`, start Apache + MySQL, import `php_backend/schema.sql`, then open `http://localhost/<folder>/app/signin.html`. The sandbox calls the API at
`http://<host>:8000` unless `app/runtime-config.js` says otherwise.

## Retraining

```bash
pip install -r requirements-train.txt
python scripts/prepare_data.py            # streams paysim.csv -> data/cache/paysim_splits.npz (~5 min, low memory)
python scripts/train_pipeline.py          # ~20 min on 4 cores; writes models/ (~1 MB)
python scripts/make_report.py             # regenerates docs/RESULTS.md
python scripts/train_pipeline.py --quick --out models_quick   # 1-minute pipeline check
```

Splits are 70 / 10 / 20 %. Only the training split is under-sampled; validation and test keep the natural fraud rate
and probabilities are corrected back to it. The decision threshold maximises F1 on validation; the test set is only used
for the final report.

## API

`POST /predict_named` - send whatever you know, aliases are accepted (`GET /feature-schema` lists them):

```json
{ "transaction_type": "send", "amount": 1500, "balance_before": 1500, "balance_after": 0, "hour_of_day": 3,
  "impossible_travel_flag": 0, "is_new_device": 1 }
```

Response (abridged):

```json
{ "fraud_probability": 0.9363, "risk_score": 96, "is_fraudulent": true, "risk_level": "High Risk", "review_required": true,
  "threshold": 0.561, "champion_model": "quantum_enhanced", "model_scores": { "xgboost": 0.99, "...": 0 },
  "context_flags": [], "low_confidence": false,
  "explanation": { "reason": "Flagged mainly because: The sender's account was emptied ...",
                   "feature_impacts": [ { "label": "Account emptied", "impact_pct": 41.2, "direction": "increases fraud risk" } ] } }
```

Also: `POST /predict_batch` (<= 5000 rows), `POST /explain_named`, `GET /model-info`, `GET /metrics`, `GET /health`,
`POST /predict_simple` (kept for older clients).

`risk_score` (0-100) is what dashboards should show: **75 or more = the model flags it**; below that it is a log-scaled
index of the (tiny) fraud probability so ordering stays visible; any context alert lifts it to at least 50. It is an
index, not a probability - `fraud_probability` is the calibrated number.

Sender balances are needed for reliable answers; without them the response has `low_confidence: true` and balance
checks are left out of the explanation. Recipient balances are optional.

## Deploy on Render

1. Push this repository to GitHub (`models/` **must** be committed - it is ~1 MB; `paysim*.csv` and `_legacy/` are git-ignored).
2. **MySQL:** Render has no managed MySQL. Create one elsewhere (Aiven, TiDB Cloud, PlanetScale, ...), then import
   `php_backend/schema.sql` (a complete schema; the old `transactions.sql` dump is stale and lacks columns the PHP writes).
3. Render dashboard -> **New + -> Blueprint** -> select the repo. `render.yaml` creates three services:
   `smartdetector-api`, `smartdetector-dashboard`, `smartdetector-web` (Docker, PHP + Apache).
4. Fill the prompted environment variables:
   * dashboard: `API_URL` = `https://<your-api>.onrender.com`
   * web: `API_URL` (same), `APP_BASE_URL` (= `https://<your-web>.onrender.com/app`), `DB_HOST`, `DB_USER`, `DB_PASSWORD`
     (`DB_NAME` defaults to `fraud_detection`, `DB_SSL=1`); optional `SMTP_USERNAME` / `SMTP_PASSWORD` for alert e-mails.
   * api: optionally restrict `ALLOWED_ORIGINS` to the web + dashboard URLs.
5. Verify: `python scripts/smoke_test.py https://<your-api>.onrender.com`, then open `https://<your-web>.onrender.com`.

Notes: free instances sleep after ~15 min idle (first request takes ~1 min). The API needs roughly 300-400 MB RAM; if it
is killed for memory, use the Starter plan. Python is pinned to 3.10.11 and libraries to the versions the models were
trained with - do not bump scikit-learn/xgboost without retraining.

## What to expect in the sandbox

The model learned PaySim's fraud signature: **the sender's account is emptied** by a transfer or cash-out (97.6 % of
PaySim fraud), often to an empty recipient account. So:

| Try this in the sandbox | Result |
|---|---|
| Everyday payments, deposits, sends that keep a balance | risk score 0-40, "Safe" |
| Send or withdraw **the entire balance** | risk score 90+, flagged, pop-up with the reason |
| Send 99 % of the balance | score ~40, "Low Risk", *not* flagged (the account was not emptied) |
| Any transaction with a context alert (impossible travel, 3 withdrawals in an hour, new device + >= 5000) | at least 50, "Medium Risk", pop-up asks for review |

A wall of 0 % on the dashboard therefore means "nothing here looks like emptying an account", not "the model is off".
Context rules never change `is_fraudulent`; they only ask for a review.

## Project layout

```
api.py                     FastAPI service            streamlit_app.py     dashboard
fraud/                     features, quantum, ensembles, system, training, context, data
scripts/                   prepare_data, train_pipeline, make_report, smoke_test
models/                    trained artifacts + metrics.json (committed, ~1 MB)
app/                       SimplePay sandbox + admin pages (static, call the API)
php_backend/               storage API, auth, alerts (MySQL); schema.sql = full schema
docker/, render.yaml       Render deployment
docs/RESULTS.md            generated evaluation report
_legacy/                   previous scripts and the RF-only model (git-ignored, safe to delete)
```

## Honest limitations

* PaySim has **no real location, device or per-customer history** (almost every account appears once), so those signals
  are *rules*, not learned. The old `feature_engineer.py` generated them randomly; fraud rate was flat across the fake
  "countries", so the model was learning noise. They were removed from the model.
* Scores are optimistic because PaySim fraud is easy to separate. Validate on real, labelled data before any real use.
* A legitimate customer who empties their own account looks like PaySim fraud and will be flagged for review.
* This is a research/education prototype, not a certified fraud-prevention product.
