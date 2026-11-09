"""Turn wide survey data + config into the long table the analysis uses.

Nothing here changes the source data. It decides, and records in an exclusions table:

- which columns are items (explicit names or glob patterns),
- which responses are left out of means and tests (N/A-type codes, out-of-range values),
- which respondents fall outside the configured factor levels.
"""

from __future__ import annotations

import fnmatch
import textwrap
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from .loaders import Dataset, code_str


@dataclass
class Factor:
    name: str
    column: str
    levels: list[str]  # display labels, in order
    colors: dict[str, str]
    wrap: int | None = None

    def tick_label(self, level: str) -> str:
        if not self.wrap:
            return level
        text = level.replace(" / ", " /\n")
        return "\n".join(textwrap.fill(part, self.wrap) for part in text.split("\n"))


@dataclass
class Prepared:
    items: list[str]  # item columns, in display order
    item_labels: dict[str, str]
    factors: list[Factor]
    long: pd.DataFrame  # item, respondent, value, <factor names...>
    exclusions: pd.DataFrame  # per item: what was left out and why
    factor_exclusions: pd.DataFrame  # per factor: respondents outside the levels
    warnings: list[str] = field(default_factory=list)


class DataError(ValueError):
    pass


def _key(s: Any) -> str:
    return " ".join(str(s).split()).lower()


def resolve_items(columns: list[str], specs: list[str]) -> list[str]:
    """Item columns from names/glob patterns, in data order; ``*_TEXT`` never matches."""
    chosen: list[str] = []
    missing = []
    for spec in specs:
        if any(ch in spec for ch in "*?["):
            hits = [c for c in columns if fnmatch.fnmatchcase(c, spec) and not c.endswith("_TEXT")]
        else:
            hits = [spec] if spec in columns else []
        if not hits:
            missing.append(spec)
        chosen += [c for c in hits if c not in chosen]
    if missing:
        raise DataError(f"items.columns: no columns match {missing}")
    order = {c: k for k, c in enumerate(columns)}
    return sorted(chosen, key=order.get)


def order_items(items: list[str], labels: dict[str, str], order: list[str], warnings: list[str]):
    if not order:
        return items
    lookup = {}
    for c in items:
        lookup[_key(c)] = c
        lookup.setdefault(_key(labels[c]), c)
    ordered, unknown = [], []
    for entry in order:
        c = lookup.get(_key(entry))
        if c is None:
            unknown.append(entry)
        elif c not in ordered:
            ordered.append(c)
    if unknown:
        warnings.append(f"items.order: not found among the items, ignored: {unknown}")
    rest = [c for c in items if c not in ordered]
    if rest and ordered:
        warnings.append(f"items.order: {len(rest)} item(s) not listed were added at the end")
    return ordered + rest


def _code_sort_key(code: str):
    try:
        return (0, float(code), "")
    except ValueError:
        return (1, 0.0, code)


def build_factor(ds: Dataset, spec: dict[str, Any], exclude: set[str]) -> tuple[Factor, pd.Series]:
    """Map the factor column's raw codes to display levels; returns (Factor, levels series)."""
    col = spec["column"]
    if col not in ds.data.columns:
        raise DataError(f"factor column '{col}' is not in the data")
    labels = ds.value_labels.get(col, {})
    disp = {_key(k): v for k, v in (spec.get("level_labels") or {}).items()}

    def display(code: str) -> str:
        label = labels.get(code, code)
        return disp.get(_key(code)) or disp.get(_key(label)) or label

    raw = ds.data[col]
    codes_present = sorted({c for c in raw.dropna()}, key=_code_sort_key)
    code_of_text: dict[str, str] = {}
    for code in set(codes_present) | set(labels):
        for text in (code, labels.get(code, code), display(code)):
            code_of_text.setdefault(_key(text), code)

    if spec.get("levels"):
        levels, bad = [], []
        for lvl in spec["levels"]:
            code = code_of_text.get(_key(code_str(lvl) or lvl))
            if code is None:
                bad.append(lvl)
            else:
                levels.append(display(code))
        if bad:
            known = sorted({display(c) for c in codes_present})
            raise DataError(f"factor '{spec['name']}': levels {bad} not found; data has {known}")
    else:
        levels = [display(c) for c in codes_present if c not in exclude]
        levels = list(dict.fromkeys(levels))

    mapped = raw.map(lambda c: display(c) if c is not None else None)
    mapped = mapped.where(mapped.isin(levels))
    colors = {}
    for k, v in (spec.get("colors") or {}).items():
        code = code_of_text.get(_key(k))
        colors[display(code) if code else k] = v
    return Factor(spec["name"], col, levels, colors, spec.get("wrap")), mapped


def prepare(ds: Dataset, cfg: dict[str, Any]) -> Prepared:
    warnings: list[str] = []
    data = ds.data
    out_cfg = cfg["outcome"]
    lo, hi = out_cfg["scale"]

    items = resolve_items(list(data.columns), cfg["items"]["columns"])
    labels = {c: cfg["items"]["labels"].get(c) or ds.variable_labels.get(c) or c for c in items}
    items = order_items(items, labels, cfg["items"]["order"], warnings)

    global_ex = {code_str(c) for c in out_cfg["exclude_codes"]}
    by_col = {
        col: {code_str(c) for c in codes}
        for col, codes in (out_cfg["exclude_codes_by_column"] or {}).items()
    }
    use_src = out_cfg["use_source_exclusions"]

    # ---- factors
    factors: list[Factor] = []
    factor_cols: dict[str, pd.Series] = {}
    f_ex_rows = []
    for spec in cfg["factors"]:
        ex = global_ex | by_col.get(spec["column"], set())
        if use_src:
            ex |= ds.non_substantive.get(spec["column"], set())
        fac, mapped = build_factor(ds, spec, ex)
        factors.append(fac)
        factor_cols[fac.name] = mapped
        outside = data[spec["column"]][mapped.isna()]
        f_ex_rows.append(
            {
                "factor": fac.name,
                "column": fac.column,
                "levels": " | ".join(fac.levels),
                "n_in_levels": int(mapped.notna().sum()),
                "n_blank": int(outside.isna().sum()),
                "n_other_values": int(outside.notna().sum()),
                "other_values": ", ".join(
                    f"{ds.value_labels.get(fac.column, {}).get(v, v)} ({n})"
                    for v, n in outside.dropna().value_counts().items()
                ),
            }
        )

    # ---- items: exclusions and numeric values
    frames, ex_rows = [], []
    for col in items:
        codes = data[col]
        ex = global_ex | by_col.get(col, set())
        if use_src:
            ex |= ds.non_substantive.get(col, set())
        is_ex = codes.isin(ex)
        values = pd.to_numeric(codes.where(~is_ex), errors="coerce")
        bad = codes[~is_ex & codes.notna() & values.isna()]
        if len(bad):
            raise DataError(
                f"item '{col}' has non-numeric values {sorted(set(bad))[:5]}; "
                "list them in outcome.exclude_codes if they are N/A-type codes"
            )
        oor = values.notna() & ((values < lo) | (values > hi))
        if oor.any():
            if out_cfg["out_of_range"] == "error":
                raise DataError(
                    f"item '{col}' has values outside the scale {lo}–{hi}: "
                    f"{sorted(set(values[oor]))[:5]} (set outcome.out_of_range to 'exclude', "
                    "or add them to outcome.exclude_codes)"
                )
            values = values.where(~oor)
        vl = ds.value_labels.get(col, {})
        ex_rows.append(
            {
                "item": col,
                "label": labels[col],
                "n_answered": int(codes.notna().sum()),
                "n_non_substantive": int(is_ex.sum()),
                "non_substantive_codes": ", ".join(
                    f"{c} ({vl[c]})" if c in vl else c
                    for c in sorted(set(codes[is_ex]), key=_code_sort_key)
                ),
                "n_out_of_range": int(oor.sum()),
                "n_valid": int(values.notna().sum()),
            }
        )
        f = pd.DataFrame({"item": col, "respondent": data.index, "value": values})
        for name, series in factor_cols.items():
            f[name] = series.to_numpy()
        frames.append(f)

    long = pd.concat(frames, ignore_index=True).dropna(subset=["value"])
    for fac in factors:
        long = long[long[fac.name].notna()]
        long[fac.name] = pd.Categorical(long[fac.name], categories=fac.levels, ordered=True)
    return Prepared(
        items,
        labels,
        factors,
        long.reset_index(drop=True),
        pd.DataFrame(ex_rows),
        pd.DataFrame(f_ex_rows),
        warnings,
    )
