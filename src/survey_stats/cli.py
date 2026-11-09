"""Command line: ``survey-stats run|validate|init``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import config as config_mod
from .loaders import load_source
from .prepare import DataError

MAX_LISTED_LEVELS = 12


def _starter_config(source: dict[str, Any], base: Path) -> dict[str, Any]:
    """A self-documenting config listing the data's columns, labels and candidate factors."""
    ds = load_source(source, base)
    cols = list(ds.data.columns)
    columns_doc, factor_doc = {}, {}
    for c in cols:
        values = ds.data[c].dropna()
        n_distinct = values.nunique()
        label = ds.variable_labels.get(c, "")
        doc = label[:90] if label else ""
        if ds.non_substantive.get(c):
            doc += f"  [N/A codes: {', '.join(sorted(ds.non_substantive[c]))}]"
        columns_doc[c] = doc.strip() or f"({n_distinct} distinct values)"
        if 2 <= n_distinct <= MAX_LISTED_LEVELS and not c.endswith("_TEXT"):
            vl = ds.value_labels.get(c, {})
            levels = sorted(values.unique(), key=lambda v: (len(v), v))
            factor_doc[c] = [vl.get(v, v) for v in levels]
    return {
        "_about": "survey-stats config. Keys starting with '_' are comments. Fill in items "
        "and factors, then run: survey-stats run <this file>",
        "_columns": columns_doc,
        "_possible_factors": factor_doc,
        "source": source,
        "items": {"columns": [], "labels": {}, "order": []},
        "outcome": {"scale": [1, 5], "axis_label": "Mean Rating", "exclude_codes": []},
        "factors": [],
        "_factor_example": {"column": "Q1", "name": "Sex", "levels": ["Female", "Male"],
                            "colors": {"Female": "#ff7f0e", "Male": "#1f77b4"}, "wrap": 12},
        "output": {"dir": "survey_stats_output"},
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="survey-stats", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="Run a report from a JSON config")
    r.add_argument("config")
    r.add_argument("--outdir", help="Override output.dir")
    v = sub.add_parser("validate", help="Check a config (and that its data loads) without running")
    v.add_argument("config")
    i = sub.add_parser("init", help="Write a starter config that lists the data's columns")
    i.add_argument("--type", required=True, choices=sorted(config_mod.ALLOWED["source.type"]))
    i.add_argument("--path", required=True, help="Data file, or qualtrics-analysis run folder")
    i.add_argument("--sheet", default=0, help="Excel sheet")
    i.add_argument("--qualtrics-headers", action="store_true", help="CSV with 3 header rows")
    i.add_argument("-o", "--output", default="survey_stats_config.json")
    args = p.parse_args(argv)

    try:
        if args.cmd == "init":
            source = {"type": args.type, "path": args.path}
            if args.type == "excel":
                source["sheet"] = args.sheet
            if args.qualtrics_headers:
                source["qualtrics_headers"] = True
            out = Path(args.output)
            if out.exists():
                print(f"{out} exists; not overwriting.", file=sys.stderr)
                return 1
            cfg = _starter_config(source, Path.cwd())
            out.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"Wrote {out}")
            return 0

        cfg = config_mod.load(args.config)
        if args.cmd == "validate":
            from .prepare import prepare

            ds = load_source(cfg["source"], Path(cfg["_base_dir"]))
            prep = prepare(ds, cfg)
            print(f"OK: {len(prep.items)} item(s), {len(prep.factors)} factor(s), "
                  f"{prep.long['respondent'].nunique()} respondent(s) with usable ratings.")
            for w in prep.warnings:
                print(f"WARNING: {w}")
            return 0

        from .runner import run

        result = run(cfg, outdir=args.outdir)
        for m in result.messages:
            print(m)
        print(f"Wrote {len(result.files)} file(s) to {result.outdir}")
        return 0
    except (config_mod.ConfigError, DataError, FileNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
