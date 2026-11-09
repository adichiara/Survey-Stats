"""Statistics: means with CIs, one-/two-way ANOVA, effect sizes, Tukey HSD, letters.

Everything here works on a *long* DataFrame with one row per (respondent, item) rating:
columns ``value`` (float) plus one column per grouping factor. Non-substantive responses
must already be removed (see :mod:`survey_stats.prepare`).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import stats

# Cohen (1988) benchmarks for eta squared / partial eta squared.
DEFAULT_EFFECT_THRESHOLDS = {"small": 0.01, "medium": 0.06, "large": 0.14}


@dataclass
class TestResult:
    """One ANOVA effect for one item."""

    test: str  # e.g. "Sex", "Fit", "Sex x Fit"
    kind: str  # "one-way" | "two-way interaction"
    F: float = np.nan
    df1: float = np.nan
    df2: float = np.nan
    p: float = np.nan
    eta_sq: float = np.nan  # eta squared (one-way) or partial eta squared (interaction)
    p_adj: float = np.nan  # after multiple-comparison adjustment (= p when none)
    posthoc: pd.DataFrame | None = None  # Tukey HSD pairs (factors with 3+ levels)
    letters: dict[str, str] = field(default_factory=dict)  # compact letter display


def mean_ci(values, conf: float = 0.95) -> tuple[float, float, float, int]:
    """Mean, SD and t-based CI half-width of ``values`` (NaNs ignored)."""
    x = pd.Series(values, dtype=float).dropna()
    n = len(x)
    if n == 0:
        return np.nan, np.nan, np.nan, 0
    m = float(x.mean())
    if n < 2:
        return m, np.nan, np.nan, n
    sd = float(x.std(ddof=1))
    half = float(stats.sem(x) * stats.t.ppf((1 + conf) / 2, n - 1))
    return m, sd, half, n


def describe(d: pd.DataFrame, by: list[str], conf: float = 0.95) -> pd.DataFrame:
    """n, M, SD and CI for each combination of ``by`` (empty ``by`` = whole item)."""
    rows = []
    groups = [((), d)] if not by else d.groupby(by, observed=True, sort=False)
    for keys, g in groups:
        keys = keys if isinstance(keys, tuple) else (keys,)
        m, sd, half, n = mean_ci(g["value"], conf)
        rows.append(
            {
                **dict(zip(by, keys, strict=False)),
                "n": n,
                "mean": m,
                "sd": sd,
                "ci_low": m - half if n > 1 else np.nan,
                "ci_high": m + half if n > 1 else np.nan,
            }
        )
    return pd.DataFrame(rows, columns=[*by, "n", "mean", "sd", "ci_low", "ci_high"])


def oneway(d: pd.DataFrame, factor: str) -> TestResult:
    """One-way between-groups ANOVA of ``value`` by ``factor``; eta squared."""
    res = TestResult(test=factor, kind="one-way")
    groups = [g["value"].to_numpy(float) for _, g in d.groupby(factor, observed=True)]
    groups = [g for g in groups if len(g)]
    n = sum(len(g) for g in groups)
    if len(groups) < 2 or n <= len(groups):
        return res
    F, p = stats.f_oneway(*groups)
    allv = np.concatenate(groups)
    grand = allv.mean()
    ss_between = sum(len(g) * (g.mean() - grand) ** 2 for g in groups)
    ss_total = float(((allv - grand) ** 2).sum())
    res.F, res.p = float(F), float(p)
    res.df1, res.df2 = len(groups) - 1, n - len(groups)
    res.eta_sq = ss_between / ss_total if ss_total > 0 else np.nan
    res.p_adj = res.p
    return res


def twoway_interaction(d: pd.DataFrame, a: str, b: str) -> TestResult:
    """A x B interaction from a two-way between-groups ANOVA (Type III SS, as SPSS).

    Returns the interaction effect with partial eta squared.
    """
    import statsmodels.formula.api as smf
    from statsmodels.stats.anova import anova_lm

    res = TestResult(test=f"{a} x {b}", kind="two-way interaction")
    if d[a].nunique() < 2 or d[b].nunique() < 2:
        return res
    data = pd.DataFrame(
        {"y": d["value"].astype(float), "A": d[a].astype(str), "B": d[b].astype(str)}
    )
    try:
        model = smf.ols("y ~ C(A, Sum) * C(B, Sum)", data=data).fit()
        tab = anova_lm(model, typ=3)
    except (ValueError, np.linalg.LinAlgError):
        return res
    row = "C(A, Sum):C(B, Sum)"
    if row not in tab.index or not np.isfinite(tab.loc[row, "F"]):
        return res
    ss, ss_err = tab.loc[row, "sum_sq"], tab.loc["Residual", "sum_sq"]
    res.F = float(tab.loc[row, "F"])
    res.df1, res.df2 = float(tab.loc[row, "df"]), float(tab.loc["Residual", "df"])
    res.p = float(tab.loc[row, "PR(>F)"])
    res.eta_sq = float(ss / (ss + ss_err))
    res.p_adj = res.p
    return res


def tukey(d: pd.DataFrame, factor: str, alpha: float = 0.05) -> pd.DataFrame:
    """Tukey HSD pairwise comparisons: columns group1, group2, meandiff, p_adj, reject."""
    from statsmodels.stats.multicomp import pairwise_tukeyhsd

    sub = d[[factor, "value"]].dropna()
    hsd = pairwise_tukeyhsd(sub["value"].astype(float), sub[factor].astype(str), alpha=alpha)
    tab = pd.DataFrame(hsd.summary().data[1:], columns=hsd.summary().data[0])
    return pd.DataFrame(
        {
            "group1": tab["group1"].astype(str),
            "group2": tab["group2"].astype(str),
            "meandiff": tab["meandiff"].astype(float),
            "p_adj": tab["p-adj"].astype(float),
            "reject": tab["reject"].astype(bool),
        }
    )


def compact_letters(levels_by_mean: list[str], different: set[frozenset[str]]) -> dict[str, str]:
    """Compact letter display: levels sharing a letter do not differ significantly.

    ``levels_by_mean`` orders the levels (highest mean first gets "a"); ``different``
    holds the pairs that differ significantly. Uses insert-and-absorb (Piepho, 2004).
    """
    groups: list[set[str]] = [set(levels_by_mean)]
    for pair in different:
        i, j = tuple(pair)
        new: list[set[str]] = []
        for g in groups:
            if i in g and j in g:
                new += [g - {i}, g - {j}]
            else:
                new.append(g)
        # absorb: drop empty groups and groups contained in another group
        uniq: list[set[str]] = []
        for g in sorted(new, key=len, reverse=True):
            if g and not any(g <= h for h in uniq):
                uniq.append(g)
        groups = uniq
    rank = {lvl: k for k, lvl in enumerate(levels_by_mean)}
    groups.sort(key=lambda g: min(rank[x] for x in g))
    letters = {lvl: "" for lvl in levels_by_mean}
    for k, g in enumerate(groups):
        ch = chr(ord("a") + k) if k < 26 else f"[{k}]"
        for lvl in g:
            letters[lvl] += ch
    return {lvl: "".join(sorted(s)) for lvl, s in letters.items()}


def oneway_with_posthoc(
    d: pd.DataFrame, factor: str, levels: list[str], alpha: float = 0.05
) -> TestResult:
    """One-way ANOVA plus, for 3+ levels, Tukey HSD and compact letters."""
    res = oneway(d, factor)
    present = [lvl for lvl in levels if (d[factor] == lvl).any()]
    if len(present) >= 3 and np.isfinite(res.p):
        hsd = tukey(d, factor, alpha)
        res.posthoc = hsd
        means = d.groupby(factor, observed=True)["value"].mean()
        order = sorted(present, key=lambda lvl: -means.get(lvl, -np.inf))
        diff = {
            frozenset((r.group1, r.group2)) for r in hsd.itertuples() if bool(r.reject)
        }
        res.letters = compact_letters(order, diff)
    return res


def adjust_pvalues(results: list[TestResult], method: str | None) -> None:
    """Fill ``p_adj`` across one family of tests (e.g. one effect over all items)."""
    ps = np.array([r.p for r in results], dtype=float)
    ok = np.isfinite(ps)
    adj = ps.copy()
    if method and method != "none" and ok.any():
        from statsmodels.stats.multitest import multipletests

        adj[ok] = multipletests(ps[ok], method=method)[1]
    for r, a in zip(results, adj, strict=True):
        r.p_adj = float(a)


def stars(p: float, alpha: float = 0.05) -> str:
    if p is None or not np.isfinite(p):
        return ""
    if p < 0.001:
        return "***"
    if p < 0.01:
        return "**"
    if p < alpha:
        return "*"
    return ""


def effect_label(eta: float, thresholds: dict[str, float] | None = None) -> str:
    t = thresholds or DEFAULT_EFFECT_THRESHOLDS
    if eta is None or not np.isfinite(eta):
        return ""
    if eta >= t["large"]:
        return "Large"
    if eta >= t["medium"]:
        return "Medium"
    if eta >= t["small"]:
        return "Small"
    return "Negligible"


def fmt_p(p: float) -> str:
    """APA style: no leading zero, '< .001' for small values."""
    if p is None or not np.isfinite(p):
        return "–"
    if p < 0.001:
        return "< .001"
    return f"{p:.3f}".lstrip("0")


def fmt_eta(x: float) -> str:
    if x is None or not np.isfinite(x):
        return "–"
    return f"{x:.3f}".lstrip("0") if x < 1 else f"{x:.3f}"
