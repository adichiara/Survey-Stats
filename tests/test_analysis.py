import numpy as np
import pandas as pd
import pytest
import statsmodels.formula.api as smf
from scipy import stats
from statsmodels.stats.anova import anova_lm

from survey_stats import analysis as an


@pytest.fixture
def unbalanced():
    rng = np.random.default_rng(9)
    n = 400
    d = pd.DataFrame({
        "A": rng.choice(["F", "M"], n, p=[0.7, 0.3]),
        "B": rng.choice(["lo", "mid", "hi"], n, p=[0.5, 0.3, 0.2]),
    })
    d["value"] = (3 + 0.4 * (d.A == "F") + 0.5 * (d.B == "hi")
                  + 0.6 * (d.A == "F") * (d.B == "lo") + rng.normal(0, 1, n))
    return d


def test_mean_ci_matches_t_interval():
    x = [1, 2, 3, 4, 5, 5]
    m, sd, half, n = an.mean_ci(x)
    lo, hi = stats.t.interval(0.95, len(x) - 1, loc=np.mean(x), scale=stats.sem(x))
    assert n == 6 and m == pytest.approx(np.mean(x)) and sd == pytest.approx(np.std(x, ddof=1))
    assert m - half == pytest.approx(lo) and m + half == pytest.approx(hi)


def test_mean_ci_single_value_has_no_interval():
    m, sd, half, n = an.mean_ci([3.0])
    assert (m, n) == (3.0, 1) and np.isnan(sd) and np.isnan(half)


def test_oneway_matches_ols_and_eta_squared(unbalanced):
    r = an.oneway(unbalanced, "B")
    tab = anova_lm(smf.ols("value ~ C(B)", unbalanced).fit())
    assert r.F == pytest.approx(tab.loc["C(B)", "F"])
    assert r.p == pytest.approx(tab.loc["C(B)", "PR(>F)"])
    assert (r.df1, r.df2) == (2, 397)
    ss_b, ss_e = tab.loc["C(B)", "sum_sq"], tab.loc["Residual", "sum_sq"]
    assert r.eta_sq == pytest.approx(ss_b / (ss_b + ss_e))


def test_twoway_interaction_matches_type3_model_comparison(unbalanced):
    """Type III interaction = full model vs model without the interaction (sum coding)."""
    r = an.twoway_interaction(unbalanced, "A", "B")
    full = smf.ols("value ~ C(A, Sum) * C(B, Sum)", unbalanced).fit()
    reduced = smf.ols("value ~ C(A, Sum) + C(B, Sum)", unbalanced).fit()
    F = ((reduced.ssr - full.ssr) / 2) / (full.ssr / full.df_resid)
    assert r.F == pytest.approx(F)
    assert r.p == pytest.approx(stats.f.sf(F, 2, full.df_resid))
    ss_int = reduced.ssr - full.ssr
    assert r.eta_sq == pytest.approx(ss_int / (ss_int + full.ssr))


def test_oneway_untestable_returns_nan():
    d = pd.DataFrame({"g": ["a", "a"], "value": [1.0, 2.0]})
    assert np.isnan(an.oneway(d, "g").p)


def test_compact_letters_known_patterns():
    # a > b > c, only a vs c differ -> a: "a", b: "ab", c: "b"
    assert an.compact_letters(["a", "b", "c"], {frozenset(("a", "c"))}) == {
        "a": "a", "b": "ab", "c": "b"}
    # all differ
    all_diff = {frozenset(p) for p in [("a", "b"), ("a", "c"), ("b", "c")]}
    assert an.compact_letters(["a", "b", "c"], all_diff) == {"a": "a", "b": "b", "c": "c"}
    # none differ
    assert set(an.compact_letters(["a", "b", "c"], set()).values()) == {"a"}


def test_oneway_with_posthoc_adds_tukey_for_three_levels(unbalanced):
    r = an.oneway_with_posthoc(unbalanced, "B", ["lo", "mid", "hi"])
    assert r.posthoc is not None and len(r.posthoc) == 3
    assert set(r.letters) == {"lo", "mid", "hi"}
    two = an.oneway_with_posthoc(unbalanced, "A", ["F", "M"])
    assert two.posthoc is None and two.letters == {}


def test_adjust_pvalues_methods():
    rs = [an.TestResult("t", "one-way", p=p) for p in (0.01, 0.02, 0.04, np.nan)]
    an.adjust_pvalues(rs, "bonferroni")
    assert [r.p_adj for r in rs[:3]] == pytest.approx([0.03, 0.06, 0.12])
    assert np.isnan(rs[3].p_adj)
    an.adjust_pvalues(rs, "none")
    assert rs[0].p_adj == 0.01


def test_formatting_helpers():
    assert an.fmt_p(0.0004) == "< .001" and an.fmt_p(0.0234) == ".023"
    assert an.stars(0.0004) == "***" and an.stars(0.03) == "*" and an.stars(0.2) == ""
    assert an.effect_label(0.005) == "Negligible" and an.effect_label(0.07) == "Medium"
    assert an.effect_label(0.2) == "Large" and an.effect_label(np.nan) == ""
