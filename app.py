"""Backward-compatible entry point.

The three-layer system now lives in the ``fraud`` package:

    fraud/features.py   named feature contract (single source of truth for training and serving)
    fraud/quantum.py    quantum-inspired feature selectors + hyper-parameter search
    fraud/ensembles.py  Layer 2 ensembles and the Layer 3 risk-fusion head
    fraud/system.py     scoring, SHAP explanations, save / load
    fraud/training.py   the training pipeline

``python app.py`` (re)trains the system from paysim.csv, exactly like the two scripts below.
"""
import subprocess
import sys
from pathlib import Path

from fraud.system import FraudDetectionSystem  # noqa: F401  (re-exported for old imports)

ROOT = Path(__file__).parent

if __name__ == "__main__":
    for script in ("prepare_data.py", "train_pipeline.py"):
        subprocess.run([sys.executable, str(ROOT / "scripts" / script), *sys.argv[1:]], check=True)
