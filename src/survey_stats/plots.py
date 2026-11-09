"""Horizontal mean ± CI error-bar plots.

- 0 factors: one overview figure, every item's mean on one chart.
- 1 or 2 factors: one figure per item, a panel per factor; with 2 factors, a third
  panel shows factor 2 on the y-axis clustered by factor 1 (with the only legend).
"""

from __future__ import annotations

import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from . import analysis as an
from .results import Results

_PALETTE = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2"]


def safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", str(text)).strip("_")[:80] or "item"


def _rc(p: dict) -> dict:
    fs = p["font_size"]
    return {
        "font.size": fs,
        "axes.titlesize": fs,
        "axes.labelsize": fs,
        "xtick.labelsize": fs,
        "ytick.labelsize": fs,
        "legend.fontsize": fs,
        "legend.title_fontsize": fs,
    }


def _errbar(ax, y, m, h, color, label=None):
    ax.errorbar(m, y, xerr=h, fmt="o", color=color, ecolor=color, capsize=7, markersize=8,
                elinewidth=2, capthick=2, label=label)


def _style_axis(ax, res: Results, n_rows: int):
    p, (lo, hi) = res.cfg["plots"], res.cfg["outcome"]["scale"]
    ax.set_ylim(n_rows - 0.4, -0.6)  # first row on top
    ax.set_xlim(lo - p["axis_pad"], hi + p["axis_pad"])
    step = 1 if hi - lo <= 10 else max(1, round((hi - lo) / 10))
    ax.set_xticks(np.arange(lo, hi + 0.001, step))
    ax.set_xlabel(res.cfg["outcome"]["axis_label"])
    ax.grid(axis="x", alpha=0.3)
    ax.spines[["top", "right"]].set_visible(False)


def _title(text: str, result: an.TestResult | None, res: Results) -> str:
    if result is None or not res.cfg["plots"]["show_stars"]:
        return text
    st = an.stars(result.p_adj, res.cfg["stats"]["alpha"])
    return f"{text} {st}" if st else text


def _ci_half(row):
    return (row["ci_high"] - row["mean"]) if np.isfinite(row["ci_high"]) else np.nan


def footnote_lines(res: Results) -> list[str]:
    conf = round(res.cfg["stats"]["confidence"] * 100)
    lines = [f"Error bars = {conf}% confidence intervals.   * p < .05   ** p < .01   *** p < .001"]
    names = [f.name for f in res.prep.factors]
    if names:
        lines.append(f"{', '.join(names)}: one-way ANOVA main effects.")
    if len(names) == 2:
        lines.append(f"{names[0]} & {names[1]}: two-way ANOVA interaction effect.")
    if any(len(f.levels) > 2 for f in res.prep.factors) and res.cfg["stats"]["posthoc"] == "tukey":
        lines.append("Groups sharing a letter do not differ significantly (Tukey HSD).")
    if res.cfg["stats"]["p_adjust"] != "none":
        lines.append(f"p-values adjusted across items ({res.cfg['stats']['p_adjust']}).")
    return lines


def item_figure(res: Results, item: str):
    cfg, p = res.cfg, res.cfg["plots"]
    facs = res.prep.factors
    d = res.descriptives[res.descriptives["item"] == item]
    n_panels = len(facs) + (1 if len(facs) == 2 else 0)
    max_lv = max(len(f.levels) for f in facs)
    height = p["panel_height"] + 0.55 * max(0, max_lv - 2)
    with plt.rc_context(_rc(p)):
        fig, axes = plt.subplots(1, n_panels, figsize=(p["fig_width"], height), squeeze=False)
        axes = axes[0]
        alpha = cfg["stats"]["alpha"]
        for ax, fac in zip(axes, facs, strict=False):
            sub = d[d["analysis"] == fac.name].set_index(fac.name)
            result = res.tests[item][fac.name]
            show_letters = (
                p["show_letters"] and result.letters and np.isfinite(result.p_adj)
                and result.p_adj < alpha
            )
            for i, lvl in enumerate(fac.levels):
                if lvl not in sub.index:
                    continue
                row = sub.loc[lvl]
                color = fac.colors.get(lvl, p["neutral_color"])
                _errbar(ax, i, row["mean"], _ci_half(row), color)
                if show_letters:
                    end = row["ci_high"] if np.isfinite(row["ci_high"]) else row["mean"]
                    ax.text(end + 0.12, i, result.letters.get(lvl, ""), va="center",
                            fontsize=p["font_size"] - 2, color="#333333")
            ax.set_yticks(range(len(fac.levels)), [fac.tick_label(lv) for lv in fac.levels])
            _style_axis(ax, res, len(fac.levels))
            ax.set_title(_title(p["factor_title"].format(factor=fac.name), result, res))

        if len(facs) == 2:
            a, b = facs
            ax = axes[2]
            name = f"{a.name} x {b.name}"
            sub = d[d["analysis"] == name].set_index([b.name, a.name])
            k = len(a.levels)
            offsets = np.linspace(-0.3, 0.3, k) if k > 1 else [0.0]
            for j, lvl_a in enumerate(a.levels):
                ys, ms, hs = [], [], []
                for i, lvl_b in enumerate(b.levels):
                    if (lvl_b, lvl_a) in sub.index:
                        row = sub.loc[(lvl_b, lvl_a)]
                        ys.append(i + offsets[j])
                        ms.append(row["mean"])
                        hs.append(_ci_half(row))
                color = a.colors.get(lvl_a, _PALETTE[j % len(_PALETTE)])
                if ys:
                    _errbar(ax, ys, ms, hs, color, label=a.tick_label(lvl_a).replace("\n", " "))
            ax.set_yticks(range(len(b.levels)), [b.tick_label(lv) for lv in b.levels])
            _style_axis(ax, res, len(b.levels))
            ax.legend(title=a.name, loc="center left", bbox_to_anchor=(1.01, 0.5), frameon=False)
            title = p["interaction_title"].format(a=a.name, b=b.name)
            ax.set_title(_title(title, res.tests[item][name], res))

        fig.suptitle(res.prep.item_labels[item], fontsize=p["title_size"], fontweight="bold")
        if p["footnote"]:
            fig.text(0.5, -0.01, "\n".join(footnote_lines(res)), ha="center", va="top",
                     fontsize=p["font_size"] - 1, color="gray", linespacing=1.4)
        fig.tight_layout(rect=(0, 0.03, 1, 1))
    return fig


def overview_figure(res: Results):
    """No factors: every item's overall mean on one chart."""
    p = res.cfg["plots"]
    items = res.prep.items
    d = res.descriptives[res.descriptives["analysis"] == "Overall"].set_index("item")
    with plt.rc_context(_rc(p)):
        fig, ax = plt.subplots(figsize=(p["fig_width"] * 0.7, 1.0 + 0.42 * len(items)))
        for i, item in enumerate(items):
            if item in d.index:
                row = d.loc[item]
                _errbar(ax, i, row["mean"], _ci_half(row), p["neutral_color"])
        ax.set_yticks(range(len(items)), [res.prep.item_labels[c] for c in items])
        _style_axis(ax, res, len(items))
        fig.tight_layout()
    return fig


def save_all(res: Results, outdir: Path) -> list[tuple[str, Path]]:
    """Write the figures; returns [(caption, path)] in display order."""
    p = res.cfg["plots"]
    outdir.mkdir(parents=True, exist_ok=True)
    saved = []
    if not res.prep.factors:
        fig = overview_figure(res)
        path = outdir / f"item_means.{p['file_format']}"
        fig.savefig(path, dpi=p["dpi"], bbox_inches="tight")
        plt.close(fig)
        return [("Item means", path)]
    for k, item in enumerate(res.prep.items, start=1):
        fig = item_figure(res, item)
        path = outdir / f"{k:02d}_{safe_name(res.prep.item_labels[item])}.{p['file_format']}"
        fig.savefig(path, dpi=p["dpi"], bbox_inches="tight")
        plt.close(fig)
        saved.append((res.prep.item_labels[item], path))
    return saved
