import json

import pytest
from docx import Document

from survey_stats import config, from_dataframe, run
from survey_stats.cli import main


def test_config_rejects_unknown_and_bad_values():
    with pytest.raises(config.ConfigError) as e:
        config.build({"source": {"type": "parquet", "path": "x"}, "items": {"columns": ["a"]},
                      "outcome": {"scael": [1, 5]}, "factors": [{"column": "g", "colour": {}}]})
    msg = str(e.value)
    assert "outcome.scael" in msg and "factors[0].colour" in msg


def test_config_comments_and_free_form_keys_are_allowed():
    cfg = config.build({
        "_note": "comment", "source": {"type": "csv", "path": "x", "_c": 1},
        "items": {"columns": ["Q*"], "labels": {"Q1": "Standing"}},
        "factors": [{"column": "g", "colors": {"Any level": "#000"}, "level_labels": {"1": "A"}}],
    })
    assert cfg["items"]["labels"] == {"Q1": "Standing"}
    assert cfg["factors"][0]["name"] == "g"
    with pytest.raises(config.ConfigError, match="at most 2"):
        config.build({"source": {"type": "csv", "path": "x"}, "items": {"columns": ["Q*"]},
                      "factors": [{"column": c} for c in "abc"]})


def test_two_factor_run_writes_everything(two_factor_cfg):
    out = run(two_factor_cfg)
    names = {p.name for p in out.files}
    assert {"descriptives.csv", "tests.csv", "exclusions.csv", "report.docx"} <= names
    assert len([p for p in out.files if p.suffix == ".png"]) == 3
    tests = out.results.tests_table()
    assert set(tests["test"]) == {"Sex", "Fit", "Sex x Fit"}
    assert tests.loc[tests.test == "Sex", "significant"].all()  # built-in Sex effect
    doc = Document(str(out.outdir / "report.docx"))
    assert len(doc.tables) == 3  # summary, one-way, two-way
    assert len(doc.inline_shapes) == 3
    assert any("Prefer not to say" in m for m in out.messages)


def test_one_factor_and_no_factor_runs(two_factor_cfg, tmp_path):
    one = {**two_factor_cfg, "factors": two_factor_cfg["factors"][:1],
           "output": {"dir": str(tmp_path / "one")}}
    out = run(one)
    assert set(out.results.tests_table()["test"]) == {"Sex"}
    assert len(Document(str(out.outdir / "report.docx")).tables) == 2

    none = {**two_factor_cfg, "factors": [], "output": {"dir": str(tmp_path / "none")}}
    out = run(none)
    assert [p.name for p in out.files if p.suffix == ".png"] == ["item_means.png"]
    assert len(Document(str(out.outdir / "report.docx")).tables) == 1


def test_p_adjust_and_word_options(two_factor_cfg, tmp_path):
    cfg = {**two_factor_cfg, "stats": {"p_adjust": "holm"},
           "output": {"dir": str(tmp_path / "o"), "word": {"include_plots": False,
                                                            "summary_table": False}}}
    out = run(cfg)
    t = out.results.tests_table()
    assert (t["p_adj"] >= t["p"] - 1e-12).all()
    doc = Document(str(out.outdir / "report.docx"))
    assert len(doc.inline_shapes) == 0 and len(doc.tables) == 2
    assert "p (adj.)" in doc.tables[0].rows[0].cells[-2].text


def test_dataframe_api(wide, tmp_path):
    ds = from_dataframe(wide, value_labels={"Q1": {1: "Male", 2: "Female"}},
                        non_substantive={c: [6] for c in ["Q2_1", "Q2_2", "Q2_3"]})
    out = run({"items": {"columns": ["Q2_*"]}, "factors": [{"column": "Q1", "name": "Sex"}],
               "plots": {"enabled": False}, "output": {"dir": str(tmp_path / "df")}}, dataset=ds)
    assert set(out.results.prep.factors[0].levels) == {"Male", "Female"}


def test_cli_init_validate_run(qualtrics_run, tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["init", "--type", "qualtrics_run", "--path", str(qualtrics_run),
                 "-o", "c.json"]) == 0
    cfg = json.loads((tmp_path / "c.json").read_text())
    assert cfg["_columns"]["Q2_1"].startswith("Standing")
    assert cfg["_possible_factors"]["Q1"] == ["Male", "Female"]
    cfg["items"]["columns"] = ["Q2_*"]
    cfg["factors"] = [{"column": "Q1", "name": "Sex"}]
    cfg["plots"] = {"enabled": False}
    (tmp_path / "c.json").write_text(json.dumps(cfg))
    assert main(["validate", "c.json"]) == 0
    assert "3 item(s), 1 factor(s)" in capsys.readouterr().out
    assert main(["run", "c.json"]) == 0
    assert (tmp_path / "survey_stats_output" / "report.docx").exists()
    (tmp_path / "bad.json").write_text(json.dumps({"source": {"type": "csv"}}))
    assert main(["validate", "bad.json"]) == 1


def test_example_configs_are_valid():
    from pathlib import Path

    for path in (Path(__file__).parents[1] / "examples").glob("*.json"):
        config.load(path)  # raises ConfigError if a setting is unknown or invalid


def test_run_without_install_script(qualtrics_run, tmp_path):
    """run_survey_stats.py works from another folder, using this repo's src/."""
    import subprocess
    import sys
    from pathlib import Path

    script = Path(__file__).parents[1] / "run_survey_stats.py"
    cfg = {"source": {"type": "qualtrics_run", "path": str(qualtrics_run)},
           "items": {"columns": ["Q2_*"]}, "plots": {"enabled": False},
           "output": {"dir": "out"}}
    (tmp_path / "c.json").write_text(json.dumps(cfg))
    done = subprocess.run([sys.executable, str(script), "run", "c.json"], cwd=tmp_path,
                          capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
    assert (tmp_path / "out" / "report.docx").exists()
