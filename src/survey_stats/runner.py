"""Run a whole report: load -> prepare -> analyse -> plots, CSVs, Word."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from . import config as config_mod
from .loaders import Dataset, load_source
from .plots import save_all
from .prepare import prepare
from .results import Results, analyze
from .word import build_report


@dataclass
class RunOutput:
    results: Results
    outdir: Path
    files: list[Path] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)


def run(
    cfg: dict[str, Any] | str | Path,
    dataset: Dataset | None = None,
    outdir: str | Path | None = None,
) -> RunOutput:
    """Run a report.

    ``cfg``: a config dict (merged with defaults if it is a raw user config) or a path to a
    JSON config. ``dataset``: data you already loaded (e.g. via
    :func:`survey_stats.loaders.from_dataframe`); otherwise ``cfg["source"]`` is read.
    """
    if isinstance(cfg, (str, Path)):
        cfg = config_mod.load(cfg)
    elif "_base_dir" not in cfg:
        if dataset is not None and not (cfg.get("source") or {}).get("path"):
            cfg = {**cfg, "source": {**cfg.get("source", {}), "path": "<dataframe>"}}
        cfg = config_mod.build(cfg)
    base = Path(cfg.get("_base_dir") or Path.cwd())
    ds = dataset or load_source(cfg["source"], base)

    msgs: list[str] = []
    if "column_map.json has no non_substantive_codes" in ds.source_description:
        msgs.append("WARNING:" + ds.source_description.split("[", 1)[1].rstrip("]"))
    prep = prepare(ds, cfg)
    msgs += [f"WARNING: {w}" for w in prep.warnings]
    res = analyze(prep, cfg)

    out = Path(outdir or cfg["output"]["dir"])
    if not out.is_absolute():
        out = base / out
    out.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []

    n_ex = int(prep.exclusions["n_non_substantive"].sum())
    if n_ex:
        msgs.append(f"Excluded {n_ex} non-substantive response(s) from analyses "
                    "(see exclusions.csv).")
    for row in prep.factor_exclusions.itertuples():
        if row.n_other_values:
            msgs.append(f"Factor '{row.factor}': {row.n_other_values} respondent(s) outside the "
                        f"levels were left out ({row.other_values}).")

    images = save_all(res, out / "plots") if cfg["plots"]["enabled"] else []
    files += [p for _, p in images]

    if cfg["output"]["csv"]:
        for name, frame in (
            ("descriptives.csv", res.descriptives),
            ("tests.csv", res.tests_table()),
            ("posthoc.csv", res.posthoc_table()),
            ("exclusions.csv", prep.exclusions),
            ("factor_exclusions.csv", prep.factor_exclusions),
        ):
            if name == "factor_exclusions.csv" and frame.empty:
                continue
            path = out / name
            pd.DataFrame(frame).round(6).to_csv(path, index=False)
            files.append(path)

    w = cfg["output"]["word"]
    if w["enabled"]:
        files.append(build_report(res, images, out / w["file"]))
    return RunOutput(res, out, files, msgs)
