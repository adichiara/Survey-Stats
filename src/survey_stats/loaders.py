"""Read wide survey data (one row per respondent) from different sources.

Every loader returns a :class:`Dataset`: the raw data plus whatever metadata the
source carries (value labels, question text, non-substantive codes). Loaders only
read; they never recode or drop responses.

Codes are normalised to strings (``1.0`` -> ``"1"``) so labels and exclusion codes match
however the source stored them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class Dataset:
    data: pd.DataFrame  # one row per respondent; values as codes (strings)
    value_labels: dict[str, dict[str, str]] = field(default_factory=dict)  # col -> code -> label
    variable_labels: dict[str, str] = field(default_factory=dict)  # col -> question/item text
    non_substantive: dict[str, set[str]] = field(default_factory=dict)  # col -> codes to exclude
    source_description: str = ""


def code_str(v: Any) -> str | None:
    """Normalise a raw value to a code string; None for missing."""
    if v is None:
        return None
    if isinstance(v, float):
        if np.isnan(v):
            return None
        return str(int(v)) if v.is_integer() else repr(v)
    if isinstance(v, (int, np.integer)):
        return str(int(v))
    if isinstance(v, np.floating):
        return code_str(float(v))
    s = str(v).strip()
    if s == "":
        return None
    try:  # "1.0" -> "1" so CSV/Excel codes match labels keyed "1"
        f = float(s)
        if f.is_integer() and s.replace(".", "", 1).lstrip("-").isdigit():
            return str(int(f))
    except ValueError:
        pass
    return s


def _normalise_frame(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    for c in df.columns:
        df[c] = df[c].map(code_str).astype(object)
    return df


def _norm_labels(labels: dict[Any, Any]) -> dict[str, str]:
    return {code_str(k): str(v) for k, v in (labels or {}).items() if code_str(k) is not None}


# --------------------------------------------------------------------------- loaders


def load_qualtrics_run(run_dir: str | Path, data_file: str | None = None) -> Dataset:
    """A qualtrics-analysis run folder: responses_clean.csv + column_map.json."""
    run_dir = Path(run_dir)
    if data_file is None:
        manifest = run_dir / "run_manifest.json"
        data_file = "responses_clean.csv"
        if manifest.exists():
            data_file = json.loads(manifest.read_text(encoding="utf-8")).get("data_file", data_file)
    df = pd.read_csv(run_dir / data_file, dtype=str, keep_default_na=False)
    cmap = json.loads((run_dir / "column_map.json").read_text(encoding="utf-8"))

    value_labels, variable_labels, non_sub = {}, {}, {}
    missing_fields = False
    for row in cmap:
        col = row["column"]
        if row.get("response_labels"):
            value_labels[col] = _norm_labels(row["response_labels"])
        text = row.get("sub_question_text") or row.get("question_text") or ""
        if text:
            variable_labels[col] = text
        if "non_substantive_codes" not in row and not row.get("is_metadata"):
            missing_fields = True
        codes = {code_str(c) for c in row.get("non_substantive_codes") or []}
        if codes:
            non_sub[col] = codes
    ds = Dataset(_normalise_frame(df), value_labels, variable_labels, non_sub, str(run_dir))
    if missing_fields:
        ds.source_description += (
            " [column_map.json has no non_substantive_codes: run "
            "`python -m qualtrics_pipeline.export --annotate-run` on it, or list N/A codes "
            "in the config's exclude_codes]"
        )
    return ds


def load_csv(path: str | Path, qualtrics_headers: bool = False, **read_kw: Any) -> Dataset:
    """A CSV file. ``qualtrics_headers``: a raw Qualtrics export with 3 header rows
    (names, question text, ImportId); the question text becomes the variable labels."""
    path = Path(path)
    variable_labels: dict[str, str] = {}
    if qualtrics_headers:
        head = pd.read_csv(path, dtype=str, nrows=2, keep_default_na=False, **read_kw)
        variable_labels = {
            str(c).strip(): str(t).strip() for c, t in head.iloc[0].items() if str(t).strip()
        }
        df = pd.read_csv(path, dtype=str, skiprows=[1, 2], keep_default_na=False, **read_kw)
    else:
        df = pd.read_csv(path, dtype=str, keep_default_na=False, **read_kw)
    return Dataset(_normalise_frame(df), {}, variable_labels, {}, str(path))


def load_excel(path: str | Path, sheet: str | int = 0, **read_kw: Any) -> Dataset:
    df = pd.read_excel(path, sheet_name=sheet, dtype=str, keep_default_na=False, **read_kw)
    return Dataset(_normalise_frame(df), {}, {}, {}, f"{path} [{sheet}]")


def load_sav(path: str | Path) -> Dataset:
    """An SPSS .sav file: value labels, variable labels and user-missing values.

    SPSS user-missing values (Variable View > Missing) are treated as non-substantive.
    """
    try:
        import pyreadstat
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise SystemExit(
            "Reading .sav files needs pyreadstat: pip install 'survey-stats[spss]'"
        ) from exc
    df, meta = pyreadstat.read_sav(str(path), user_missing=True, apply_value_formats=False)
    value_labels = {c: _norm_labels(v) for c, v in (meta.variable_value_labels or {}).items()}
    variable_labels = {
        c: lab for c, lab in (meta.column_names_to_labels or {}).items() if lab
    }
    non_sub: dict[str, set[str]] = {}
    for col, vals in (getattr(meta, "missing_user_values", None) or {}).items():
        non_sub.setdefault(col, set()).update(code_str(v) for v in vals if code_str(v))
    for col, ranges in (getattr(meta, "missing_ranges", None) or {}).items():
        # discrete user-missing values are reported as lo == hi ranges
        for r in ranges:
            lo, hi = r.get("lo"), r.get("hi")
            if lo == hi and code_str(lo):
                non_sub.setdefault(col, set()).add(code_str(lo))
            elif col in value_labels:
                for code in value_labels[col]:
                    try:
                        if float(lo) <= float(code) <= float(hi):
                            non_sub.setdefault(col, set()).add(code)
                    except (TypeError, ValueError):
                        continue
    return Dataset(_normalise_frame(df), value_labels, variable_labels, non_sub, str(path))


def from_dataframe(
    df: pd.DataFrame,
    value_labels: dict[str, dict[Any, str]] | None = None,
    variable_labels: dict[str, str] | None = None,
    non_substantive: dict[str, list[Any]] | None = None,
) -> Dataset:
    """Wrap a DataFrame you already have (e.g. from your own pipeline)."""
    return Dataset(
        _normalise_frame(df),
        {c: _norm_labels(v) for c, v in (value_labels or {}).items()},
        dict(variable_labels or {}),
        {c: {code_str(x) for x in v if code_str(x)} for c, v in (non_substantive or {}).items()},
        "DataFrame",
    )


def load_source(source: dict[str, Any], base_dir: Path | None = None) -> Dataset:
    """Dispatch on ``source["type"]``: qualtrics_run, csv, excel, sav."""
    base_dir = base_dir or Path.cwd()
    kind = source["type"]
    path = Path(source["path"])
    if not path.is_absolute():
        path = base_dir / path
    if kind == "qualtrics_run":
        return load_qualtrics_run(path, source.get("data_file"))
    if kind == "csv":
        return load_csv(path, qualtrics_headers=bool(source.get("qualtrics_headers")))
    if kind == "excel":
        return load_excel(path, source.get("sheet", 0))
    if kind == "sav":
        return load_sav(path)
    raise ValueError(f"Unknown source type: {kind!r}")
