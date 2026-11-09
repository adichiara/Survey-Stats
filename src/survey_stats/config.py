"""Report configuration: one JSON file per report.

Keys starting with ``_`` are comments and ignored everywhere (the same convention as
qualtrics-analysis). :func:`validate` checks names and types before anything runs, so a
typo fails loudly instead of quietly producing a different report.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, Any] = {
    "source": {
        "type": "csv",  # qualtrics_run | csv | excel | sav
        "path": "",
        "sheet": 0,  # excel only
        "qualtrics_headers": False,  # csv only: raw Qualtrics export with 3 header rows
        "data_file": None,  # qualtrics_run only; default from run_manifest.json
    },
    "items": {
        "columns": [],  # names or glob patterns, e.g. ["Q12_*"]
        "labels": {},  # column -> display label (overrides labels from the source)
        "order": [],  # columns or labels in display order; others follow in data order
    },
    "outcome": {
        "scale": [1, 5],  # [min, max] of the rating scale (axis range)
        "axis_label": "Mean Rating",
        "exclude_codes": [],  # codes left out of every item (e.g. 99 = N/A)
        "exclude_codes_by_column": {},  # column -> codes, for item-specific codes
        "use_source_exclusions": True,  # N/A codes from column_map.json / SPSS missing
        "out_of_range": "error",  # error | exclude: values outside `scale`
    },
    "factors": [],  # 0, 1 or 2 grouping factors; see FACTOR_DEFAULTS
    "stats": {
        "alpha": 0.05,
        "confidence": 0.95,
        "p_adjust": "none",  # none | fdr_bh | holm | bonferroni (per effect, across items)
        "effect_size_thresholds": {"small": 0.01, "medium": 0.06, "large": 0.14},
        "posthoc": "tukey",  # tukey | none (factors with 3+ levels)
    },
    "plots": {
        "enabled": True,
        "factor_title": "By {factor}",  # {factor} = factor name
        "interaction_title": "By {a} & {b}",
        "show_stars": True,
        "show_letters": True,  # Tukey letters beside 3+ level groups
        "fig_width": 13.0,
        "panel_height": 4.0,  # grows with the number of levels
        "dpi": 300,
        "font_size": 15,
        "title_size": 16,
        "neutral_color": "#555555",
        "axis_pad": 0.4,
        "footnote": False,  # footnote under every image
        "file_format": "png",
    },
    "output": {
        "dir": "survey_stats_output",
        "csv": True,  # descriptives.csv, tests.csv, exclusions.csv
        "word": {
            "enabled": True,
            "file": "report.docx",
            "landscape": False,
            "margin_in": 0.75,
            "plot_width_in": 7.0,
            "include_plots": True,
            "plot_headings": False,  # a heading above each plot
            "end_note": True,  # footnote once after the last plot
            "summary_table": True,
            "detail_tables": True,
            "first_table_number": 1,
        },
    },
}

FACTOR_DEFAULTS: dict[str, Any] = {
    "column": "",
    "name": None,  # display name; default = column
    "levels": [],  # labels (or codes) in display order; others are excluded
    "level_labels": {},  # code or label -> display text
    "colors": {},  # level -> colour; empty = neutral colour
    "wrap": None,  # wrap level labels at this many characters
}

ALLOWED = {
    "source.type": {"qualtrics_run", "csv", "excel", "sav"},
    "stats.p_adjust": {"none", "fdr_bh", "holm", "bonferroni"},
    "stats.posthoc": {"tukey", "none"},
    "outcome.out_of_range": {"error", "exclude"},
    "plots.file_format": {"png", "svg", "pdf"},
}


class ConfigError(ValueError):
    pass


def _strip_comments(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _strip_comments(v) for k, v in obj.items() if not str(k).startswith("_")}
    if isinstance(obj, list):
        return [_strip_comments(v) for v in obj]
    return obj


def _merge(defaults: dict, user: dict, path: str, errors: list[str]) -> dict:
    out = copy.deepcopy(defaults)
    for key, val in user.items():
        here = f"{path}.{key}" if path else key
        if key not in defaults:
            errors.append(f"Unknown setting '{here}'")
            continue
        dflt = defaults[key]
        # dict-valued settings whose keys are user data (labels, codes) are not recursed
        free_form = here in {
            "items.labels",
            "outcome.exclude_codes_by_column",
            "stats.effect_size_thresholds",
        } or (path.startswith("factors[") and key in {"colors", "level_labels"})
        if isinstance(dflt, dict) and not free_form:
            if not isinstance(val, dict):
                errors.append(f"'{here}' must be an object")
                continue
            out[key] = _merge(dflt, val, here, errors)
        else:
            out[key] = val
    return out


def _check_types(cfg: dict, errors: list[str]) -> None:
    for dotted, allowed in ALLOWED.items():
        sect, key = dotted.split(".")
        if cfg[sect][key] not in allowed:
            errors.append(f"'{dotted}' must be one of {sorted(allowed)}, got {cfg[sect][key]!r}")
    if not cfg["source"]["path"]:
        errors.append("'source.path' is required")
    scale = cfg["outcome"]["scale"]
    if not (isinstance(scale, list) and len(scale) == 2 and scale[0] < scale[1]):
        errors.append("'outcome.scale' must be [min, max] with min < max")
    if not cfg["items"]["columns"]:
        errors.append("'items.columns' must list at least one column or pattern")
    if not isinstance(cfg["factors"], list) or len(cfg["factors"]) > 2:
        errors.append("'factors' must be a list of at most 2 factors")
    a = cfg["stats"]["alpha"]
    if not (isinstance(a, (int, float)) and 0 < a < 1):
        errors.append("'stats.alpha' must be between 0 and 1")
    t = cfg["stats"]["effect_size_thresholds"]
    if set(t) != {"small", "medium", "large"} or not t["small"] <= t["medium"] <= t["large"]:
        errors.append("'stats.effect_size_thresholds' needs small <= medium <= large")


def build(user_cfg: dict[str, Any]) -> dict[str, Any]:
    """Merge a user config over the defaults and validate it. Raises ConfigError."""
    errors: list[str] = []
    user_cfg = _strip_comments(user_cfg)
    cfg = _merge(DEFAULTS, user_cfg, "", errors)
    factors = []
    for k, f in enumerate(cfg.get("factors") or []):
        if not isinstance(f, dict):
            errors.append(f"'factors[{k}]' must be an object")
            continue
        merged = _merge(FACTOR_DEFAULTS, f, f"factors[{k}]", errors)
        if not merged["column"]:
            errors.append(f"'factors[{k}].column' is required")
        merged["name"] = merged["name"] or merged["column"]
        factors.append(merged)
    cfg["factors"] = factors
    if not errors:
        _check_types(cfg, errors)
    if len({f["name"] for f in factors}) < len(factors):
        errors.append("factor names must differ")
    if errors:
        raise ConfigError("Invalid config:\n  - " + "\n  - ".join(errors))
    return cfg


def load(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path}: not valid JSON ({exc})") from exc
    cfg = build(raw)
    cfg["_base_dir"] = str(path.parent.resolve())
    return cfg
