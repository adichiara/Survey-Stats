import numpy as np
import pandas as pd
import pytest

from survey_stats import config, loaders
from survey_stats.prepare import DataError, prepare, resolve_items


def cfg_for(source, **over):
    base = {"source": source, "items": {"columns": ["Q2_*"]}}
    base.update(over)
    return config.build(base)


def test_code_str_normalises():
    assert loaders.code_str(1.0) == "1" and loaders.code_str("2.0") == "2"
    assert loaders.code_str(np.nan) is None and loaders.code_str(" ") is None
    assert loaders.code_str("Good / Excellent") == "Good / Excellent"
    assert loaders.code_str(2.5) == "2.5"


def test_qualtrics_run_reads_labels_and_na_codes(qualtrics_run):
    ds = loaders.load_qualtrics_run(qualtrics_run)
    assert ds.value_labels["Q1"] == {"1": "Male", "2": "Female"}
    assert ds.variable_labels["Q2_1"] == "Standing"
    assert ds.non_substantive["Q2_1"] == {"6"} and ds.non_substantive["Q3"] == {"4"}


def test_qualtrics_run_without_na_fields_warns(qualtrics_run):
    import json
    cm = json.loads((qualtrics_run / "column_map.json").read_text())
    for r in cm:
        r.pop("non_substantive_codes", None)
    (qualtrics_run / "column_map.json").write_text(json.dumps(cm))
    assert "annotate-run" in loaders.load_qualtrics_run(qualtrics_run).source_description


def test_csv_with_qualtrics_headers(tmp_path):
    p = tmp_path / "raw.csv"
    p.write_text('Q1,Q2_1\n"Sex","Impact - Standing"\n"{""ImportId"":""QID1""}",x\n1,4\n2,5\n')
    ds = loaders.load_csv(p, qualtrics_headers=True)
    assert list(ds.data["Q2_1"]) == ["4", "5"]
    assert ds.variable_labels["Q2_1"] == "Impact - Standing"


def test_excel_loader(tmp_path, wide):
    p = tmp_path / "d.xlsx"
    wide.to_excel(p, index=False)
    ds = loaders.load_excel(p)
    assert ds.data.shape == wide.shape
    assert set(ds.data["Q1"].dropna()) == {"1", "2"}


def test_sav_loader_value_labels_and_user_missing(tmp_path):
    pyreadstat = pytest.importorskip("pyreadstat")
    df = pd.DataFrame({"sex": [1.0, 2.0, 1.0], "q1": [4.0, 9.0, 2.0]})
    p = tmp_path / "d.sav"
    pyreadstat.write_sav(
        df, str(p),
        column_labels={"sex": "Sex", "q1": "Standing"},
        variable_value_labels={"sex": {1.0: "Male", 2.0: "Female"}, "q1": {9.0: "N/A"}},
        missing_ranges={"q1": [9.0]},
    )
    ds = loaders.load_sav(p)
    assert ds.value_labels["sex"] == {"1": "Male", "2": "Female"}
    assert ds.variable_labels["q1"] == "Standing"
    assert ds.non_substantive["q1"] == {"9"}
    assert list(ds.data["q1"]) == ["4", "9", "2"]  # kept in the data


def test_resolve_items_globs_skip_text_and_report_missing():
    cols = ["Q2_1", "Q2_1_TEXT", "Q2_2", "Q3"]
    assert resolve_items(cols, ["Q2_*"]) == ["Q2_1", "Q2_2"]
    with pytest.raises(DataError):
        resolve_items(cols, ["Q9_*"])


def test_prepare_excludes_na_and_reports_it(qualtrics_run, wide):
    cfg = cfg_for({"type": "qualtrics_run", "path": str(qualtrics_run)},
                  factors=[{"column": "Q3", "name": "Fit"}])
    prep = prepare(loaders.load_qualtrics_run(qualtrics_run), cfg)
    ex = prep.exclusions.set_index("item")
    assert ex.loc["Q2_1", "n_non_substantive"] == (wide["Q2_1"] == "6").sum()
    assert ex.loc["Q2_1", "non_substantive_codes"] == "6 (N/A)"
    assert prep.long["value"].between(1, 5).all()
    # "Prefer not to say" (code 4, non-substantive) is not a level
    assert prep.factors[0].levels == ["Poor", "Fair", "Good"]
    fx = prep.factor_exclusions.iloc[0]
    assert fx["n_other_values"] == (wide["Q3"] == "4").sum()


def test_prepare_levels_by_code_label_and_display_names(qualtrics_run):
    cfg = cfg_for({"type": "qualtrics_run", "path": str(qualtrics_run)},
                  factors=[{"column": "Q1", "name": "Sex", "levels": ["2", "Male"],
                            "level_labels": {"Female": "Women", "1": "Men"}}])
    prep = prepare(loaders.load_qualtrics_run(qualtrics_run), cfg)
    assert prep.factors[0].levels == ["Women", "Men"]
    assert set(prep.long["Sex"].unique()) == {"Women", "Men"}


def test_prepare_unknown_level_errors(qualtrics_run):
    cfg = cfg_for({"type": "qualtrics_run", "path": str(qualtrics_run)},
                  factors=[{"column": "Q1", "levels": ["Female", "Other"]}])
    with pytest.raises(DataError, match="Other"):
        prepare(loaders.load_qualtrics_run(qualtrics_run), cfg)


def test_prepare_non_numeric_and_out_of_range(wide):
    ds = loaders.from_dataframe(wide)  # no metadata: 6 is just a number here
    src = {"type": "csv", "path": "x"}
    with pytest.raises(DataError, match="outside the scale"):
        prepare(ds, cfg_for(src))
    prep = prepare(ds, cfg_for(src, outcome={"exclude_codes": [6]}))
    assert prep.long["value"].max() <= 5
    prep = prepare(ds, cfg_for(src, outcome={"out_of_range": "exclude"}))
    assert prep.exclusions["n_out_of_range"].sum() == (wide.filter(like="Q2_").iloc[:, :3]
                                                       == "6").sum().sum()
    bad = wide.assign(Q2_2=wide["Q2_2"].replace("3", "three"))
    with pytest.raises(DataError, match="non-numeric"):
        prepare(loaders.from_dataframe(bad), cfg_for(src, outcome={"exclude_codes": [6]}))


def test_item_order_by_label(qualtrics_run):
    cfg = cfg_for({"type": "qualtrics_run", "path": str(qualtrics_run)},
                  items={"columns": ["Q2_*"], "order": ["crawling", "Standing", "Nope"]})
    prep = prepare(loaders.load_qualtrics_run(qualtrics_run), cfg)
    assert prep.items == ["Q2_3", "Q2_1", "Q2_2"]
    assert any("Nope" in w for w in prep.warnings)
