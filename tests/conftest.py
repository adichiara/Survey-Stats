import json

import numpy as np
import pandas as pd
import pytest


def make_wide(n=240, seed=1, na_code="6"):
    """Wide survey data: Q1 sex (1/2), Q3 fit (1-3, 4 = prefer not to say), items Q2_1..3."""
    rng = np.random.default_rng(seed)
    sex = rng.choice(["1", "2"], n)
    fit = rng.choice(["1", "2", "3", "4"], n, p=[0.3, 0.3, 0.3, 0.1])
    data = {"ResponseId": [f"R_{i}" for i in range(n)], "Q1": sex, "Q3": fit}
    for k in range(1, 4):
        mu = 3 + 0.6 * (sex == "2") - 0.5 * (fit == "1") + 0.1 * k
        v = np.clip(np.round(rng.normal(mu, 1)), 1, 5).astype(int).astype(str).astype(object)
        v[rng.random(n) < 0.08] = na_code
        v[rng.random(n) < 0.03] = ""
        data[f"Q2_{k}"] = v
    data["Q2_1_TEXT"] = ["text"] * n
    return pd.DataFrame(data)


@pytest.fixture
def wide():
    return make_wide()


@pytest.fixture
def qualtrics_run(tmp_path, wide):
    run = tmp_path / "run"
    run.mkdir()
    wide.to_csv(run / "responses_clean.csv", index=False)
    cmap = [
        {"column": "ResponseId", "is_metadata": True, "response_labels": {}},
        {"column": "Q1", "question_text": "Sex", "response_labels": {"1": "Male", "2": "Female"},
         "non_substantive_codes": []},
        {"column": "Q3", "question_text": "Fit",
         "response_labels": {"1": "Poor", "2": "Fair", "3": "Good", "4": "Prefer not to say"},
         "non_substantive_codes": ["4"]},
    ]
    for k, lab in enumerate(["Standing", "Walking", "Crawling"], start=1):
        cmap.append({"column": f"Q2_{k}", "question_text": "Impact",
                     "sub_question_text": lab, "response_labels": {"6": "N/A"},
                     "non_substantive_codes": ["6"]})
    (run / "column_map.json").write_text(json.dumps(cmap), encoding="utf-8")
    return run


@pytest.fixture
def two_factor_cfg(qualtrics_run):
    return {
        "source": {"type": "qualtrics_run", "path": str(qualtrics_run)},
        "items": {"columns": ["Q2_*"]},
        "factors": [
            {"column": "Q1", "name": "Sex", "levels": ["Female", "Male"],
             "colors": {"Female": "#ff7f0e", "Male": "#1f77b4"}},
            {"column": "Q3", "name": "Fit"},
        ],
        "plots": {"dpi": 60},
        "output": {"dir": str(qualtrics_run.parent / "out")},
    }
