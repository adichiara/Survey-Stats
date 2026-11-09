"""Run every test for every item and collect tidy results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from . import analysis as an
from .prepare import Prepared


@dataclass
class Results:
    prep: Prepared
    descriptives: pd.DataFrame  # item, label, analysis, <factor cols>, n, mean, sd, ci_low, ci_high
    tests: dict[str, dict[str, an.TestResult]]  # item -> test name -> result
    test_names: list[str]  # in display order, e.g. ["Sex", "Fit", "Sex x Fit"]
    cfg: dict[str, Any]

    def tests_table(self) -> pd.DataFrame:
        rows = []
        alpha = self.cfg["stats"]["alpha"]
        thr = self.cfg["stats"]["effect_size_thresholds"]
        for item in self.prep.items:
            for name in self.test_names:
                r = self.tests[item][name]
                rows.append(
                    {
                        "item": item,
                        "label": self.prep.item_labels[item],
                        "test": name,
                        "kind": r.kind,
                        "F": r.F,
                        "df1": r.df1,
                        "df2": r.df2,
                        "p": r.p,
                        "p_adj": r.p_adj,
                        "eta_sq": r.eta_sq,
                        "effect_size": an.effect_label(r.eta_sq, thr),
                        "significant": bool(r.p_adj < alpha) if pd.notna(r.p_adj) else False,
                        "tukey_letters": "; ".join(f"{k}: {v}" for k, v in r.letters.items()),
                    }
                )
        return pd.DataFrame(rows)

    def posthoc_table(self) -> pd.DataFrame:
        frames = []
        for item in self.prep.items:
            for name in self.test_names:
                ph = self.tests[item][name].posthoc
                if ph is not None:
                    frames.append(ph.assign(item=item, test=name))
        if not frames:
            return pd.DataFrame(columns=["item", "test", "group1", "group2", "meandiff", "p_adj"])
        cols = ["item", "test", "group1", "group2", "meandiff", "p_adj", "reject"]
        return pd.concat(frames, ignore_index=True)[cols]


def analyze(prep: Prepared, cfg: dict[str, Any]) -> Results:
    st = cfg["stats"]
    alpha, conf = st["alpha"], st["confidence"]
    names = [f.name for f in prep.factors]
    desc_frames = []
    tests: dict[str, dict[str, an.TestResult]] = {}
    test_names = list(names)
    if len(names) == 2:
        test_names.append(f"{names[0]} x {names[1]}")

    for item in prep.items:
        d = prep.long[prep.long["item"] == item]
        meta = {"item": item, "label": prep.item_labels[item]}
        desc_frames.append(an.describe(d, [], conf).assign(analysis="Overall", **meta))
        tests[item] = {}
        for fac in prep.factors:
            desc_frames.append(an.describe(d, [fac.name], conf).assign(analysis=fac.name, **meta))
            if st["posthoc"] == "tukey":
                res = an.oneway_with_posthoc(d, fac.name, fac.levels, alpha)
            else:
                res = an.oneway(d, fac.name)
            tests[item][fac.name] = res
        if len(names) == 2:
            a, b = names
            desc_frames.append(
                an.describe(d, [b, a], conf).assign(analysis=f"{a} x {b}", **meta)
            )
            tests[item][f"{a} x {b}"] = an.twoway_interaction(d, a, b)

    # multiple-comparison adjustment: one family per effect, across items
    for name in test_names:
        an.adjust_pvalues([tests[i][name] for i in prep.items], st["p_adjust"])

    desc = pd.concat(desc_frames, ignore_index=True)
    lead = ["item", "label", "analysis", *names]
    desc = desc[[c for c in lead if c in desc.columns] + ["n", "mean", "sd", "ci_low", "ci_high"]]
    return Results(prep, desc, tests, test_names, cfg)
