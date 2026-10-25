"""Reproducible synthetic-only experiment. Never trains on user uploads."""
import json
import random
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import precision_score, recall_score, f1_score, confusion_matrix
from sklearn.model_selection import GroupShuffleSplit
from backend.documents import FEATURE_NAMES, feature_vector

root = Path(__file__).resolve().parents[1]
rng = random.Random(42)
features, labels, groups = [], [], []
for template in range(20):
    for i in range(24):
        lines = [f"{['Certificate of Completion','Academic Achievement','Professional Training Record','Continuing Education Certificate'][template % 4]} - Template {template}", f"Certificate ID: AT-{template:02d}-{i:04d}", f"Recipient: Example Learner {i}", f"Course: {['Data Science','Computer Engineering','Digital Systems','Applied Mathematics'][template % 4]}", "Issue Date: 2025-06-12", f"Issued by Sample Institution {template}", "This document recognizes successful completion of the required programme."]
        label = i % 2
        if label:
            mutation = rng.randrange(5)
            if mutation == 0: lines[1] = "Certificate ID: ?"
            elif mutation == 1: lines[4] = "Issue Date: 2025-99-88"
            elif mutation == 2: lines[2] = "Recipient: "
            elif mutation == 3: lines[3] = "Course: "
            else: lines.append("UNOFFICIAL PLACEHOLDER edited copy")
        text = "\n".join(lines)
        features.append(feature_vector(text)); labels.append(label); groups.append(template)
x, y, g = np.array(features), np.array(labels), np.array(groups)
train, test = next(GroupShuffleSplit(n_splits=1, test_size=.25, random_state=42).split(x, y, g))
model = RandomForestClassifier(n_estimators=120, max_depth=6, class_weight="balanced", random_state=42, n_jobs=1)
model.fit(x[train], y[train]); predicted = model.predict(x[test])
metrics = {"dataset": "480 generated text examples across 20 template groups", "train_samples": len(train), "test_samples": len(test), "train_groups": sorted(set(g[train].tolist())), "test_groups": sorted(set(g[test].tolist())), "precision": precision_score(y[test], predicted, zero_division=0), "recall": recall_score(y[test], predicted, zero_division=0), "f1": f1_score(y[test], predicted, zero_division=0), "confusion_matrix": confusion_matrix(y[test], predicted).tolist(), "features": FEATURE_NAMES, "seed": 42, "limitations": "Synthetic text anomalies only. High scores reflect the simple generated task. Templates share vocabulary; this is not evidence of generalization to real forgeries, visual manipulation, seals or signatures. A changed name may receive no AI warning. Collect a consented real dataset before making fraud-detection claims."}
(root / ".local").mkdir(exist_ok=True)
joblib.dump(model, root / ".local/model.joblib")
(root / ".local/model-metrics.json").write_text(json.dumps(metrics, indent=2))
print(json.dumps(metrics, indent=2))
