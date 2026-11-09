# Survey-Stats

Group comparisons for survey rating data. It produces mean ± 95% CI error-bar plots,
ANOVA tables with effect sizes, and a Word report. Every survey is configured with one
small JSON file.

Survey-Stats **only analyses**: it reads data that has already been extracted and
processed, and never recodes or removes responses. N/A-type answers stay in the data. They
are left out of means and tests, and every exclusion is reported.

```bash
pip install -e '.[all]'                  # .[spss] for .sav, .[excel] for .xlsx
survey-stats init --type qualtrics_run --path runs/fit_study -o fit_study.json
# edit fit_study.json: pick items and factors
survey-stats validate fit_study.json
survey-stats run fit_study.json
```

## Contents

- [Data sources](#data-sources) · [Configuration](#configuration) ·
  [Non-substantive responses](#non-substantive-responses-na)
- [What gets produced](#what-gets-produced) · [Statistics](#statistics) ·
  [Python API](#python-api) · [Development](#development)

## Data sources

The data is **wide**: one row per respondent and one column per question. Each rating
item is a column, and so is each grouping variable.

| `source.type` | Reads | Labels and N/A codes from |
|---|---|---|
| `qualtrics_run` | A [qualtrics-analysis](https://github.com/adichiara/Qualtrics-analysis) run folder (`responses_clean.csv` + `column_map.json`) | `column_map.json`: `response_labels`, question/sub-question text, `non_substantive_codes` |
| `sav` | An SPSS `.sav` file | Value labels, variable labels, user-missing values |
| `csv` | Any CSV. Set `qualtrics_headers: true` for a raw Qualtrics export with 3 header rows | Question text (header row 2) when `qualtrics_headers` is set |
| `excel` | An `.xlsx` sheet (`sheet`: name or index) | — (use the config) |

For a source without labels, give display names in the config (`items.labels`,
`factors[].level_labels`). Codes are compared as text, so `1`, `1.0` and `"1"` all match.

## Configuration

`survey-stats init` writes a starter config listing every column, its label, and the
columns that could be factors with their values. Keys starting with `_` are comments.
Unknown keys and invalid values are errors, so a typo can't silently change a report.
`survey-stats validate` checks the config and the data without producing anything.

A full example is in [`examples/fit_study.json`](examples/fit_study.json). The settings:

| Setting | Default | Meaning |
|---|---|---|
| `source.type` / `path` | — | See [Data sources](#data-sources). Paths are relative to the config file. |
| `items.columns` | — | Item columns: names or glob patterns (`"Q2.7_*"`). `*_TEXT` columns never match. |
| `items.labels` | `{}` | `column → display label`. These override labels from the source. |
| `items.order` | `[]` | Display order, by column or label (case/spacing ignored). Unlisted items follow; unknown names give a warning. |
| `outcome.scale` | `[1, 5]` | Rating range; sets the axis. |
| `outcome.axis_label` | `"Mean Rating"` | |
| `outcome.exclude_codes` | `[]` | Extra non-substantive codes for every item (e.g. `99`). |
| `outcome.exclude_codes_by_column` | `{}` | `column → codes`, for item-specific codes. |
| `outcome.use_source_exclusions` | `true` | Use N/A codes from `column_map.json` / SPSS user-missing values. |
| `outcome.out_of_range` | `"error"` | `exclude` to drop values outside `scale` instead of stopping. |
| `factors` | `[]` | 0, 1 or 2 grouping factors (below). |
| `stats.alpha` | `0.05` | |
| `stats.confidence` | `0.95` | Confidence level of the error bars and CIs. |
| `stats.p_adjust` | `"none"` | `fdr_bh`, `holm` or `bonferroni`: adjusts each effect across all items. |
| `stats.effect_size_thresholds` | `.01 / .06 / .14` | Cut-offs for the small/medium/large labels (Cohen, 1988). |
| `stats.posthoc` | `"tukey"` | Tukey HSD for factors with 3+ levels; `none` to skip. |
| `plots.factor_title` / `interaction_title` | `"By {factor}"` / `"By {a} & {b}"` | Panel titles; significance stars are appended. |
| `plots.fig_width`, `panel_height`, `font_size`, `title_size`, `dpi` | 13, 4, 15, 16, 300 | Figure size in inches. Word scales each figure to `plot_width_in`, so a narrower figure gives bigger-looking text. |
| `plots.show_stars`, `show_letters`, `footnote` | true, true, false | `footnote` puts the key under every image. |
| `plots.neutral_color`, `axis_pad`, `file_format` | `#555555`, 0.4, `png` | `axis_pad` keeps the lowest rating off the y-axis. |
| `output.dir` | `survey_stats_output` | Relative to the config file. |
| `output.csv` | `true` | Write the CSVs below. |
| `output.word.*` | | `file`, `landscape`, `margin_in`, `plot_width_in`, `include_plots`, `plot_headings`, `end_note`, `summary_table`, `detail_tables`, `first_table_number`. |

Each factor:

```json
{
  "column": "Q1.3",
  "name": "Sex",
  "levels": ["Female", "Male"],
  "level_labels": {"Female": "Women"},
  "colors": {"Female": "#ff7f0e", "Male": "#1f77b4"},
  "wrap": 10
}
```

- `levels`: order and selection, by label or code. Respondents with any other value
  (including the factor's own N/A codes) are left out, and this is reported. If omitted,
  every observed value except N/A codes is used, in code order.
- `level_labels`: rename levels for display.
- `colors`: per level. Levels without a colour use `neutral_color`, or the default
  palette in the interaction panel.
- `wrap`: wrap long level labels at this many characters (`"Poor / Fair"` breaks after
  the slash).

## Non-substantive responses (N/A)

A response is left out of means and tests when its code is in any of:

1. `column_map.json` → `non_substantive_codes` (qualtrics-analysis marks options flagged
   *Exclude from analysis* in Qualtrics, and labels such as N/A, Not applicable, Don't
   know, Prefer not to answer). For runs exported before that field existed, run
   `python -m qualtrics_pipeline.export --annotate-run runs/<run>`. Survey-Stats warns if
   it is missing.
2. SPSS user-missing values (Variable View → Missing).
3. `outcome.exclude_codes` / `exclude_codes_by_column`.

A factor's N/A codes (e.g. "Prefer not to say") are also never treated as groups.
`exclusions.csv` lists, per item, how many responses were excluded and which codes they
had. `factor_exclusions.csv` lists respondents outside the factor levels.

## What gets produced

In `output.dir`:

- `plots/`, depending on the number of factors:
  - **No factors:** one chart of every item's mean.
  - **1–2 factors:** one figure per item, numbered in display order, with a panel per
    factor. With two factors, a third panel shows factor 2 clustered by factor 1; it
    carries the only legend.
  - Panel titles get `*`/`**`/`***`, and factors with 3+ levels get Tukey letters.
- `report.docx`:
  - the plots, then the footnote once;
  - **Summary table**: for each item and effect, p and an effect-size label, with blanks
    for non-significant effects;
  - **One-way table**: n, M, SD, 95% CI, Tukey letters, p and η² per group;
  - **Two-way table**: the same per cell, with the interaction p and partial η².
  - Tables follow APA layout: header rows repeat on each page, rows never split across a
    page, and items are banded.
- CSVs:
  - `descriptives.csv`: every group's n, M, SD and CI;
  - `tests.csv`: F, df, p, adjusted p and η² for every test;
  - `posthoc.csv`: Tukey pairs;
  - `exclusions.csv` and `factor_exclusions.csv`.

## Statistics

Each item is analysed separately (between-groups):

| Factors | Tests |
|---|---|
| 0 | Descriptives only |
| 1 | One-way ANOVA, η² = SS between / SS total; Tukey HSD + compact letters for 3+ levels |
| 2 | One-way ANOVA for each factor (as above) and the A × B interaction from a two-way ANOVA with Type III sums of squares (SPSS's default), partial η² = SS A×B / (SS A×B + SS error) |

- **Means and CIs:** t-based (`mean ± t × SE`).
- **The two-way main effects** are not used in the report. They differ from the one-way
  results whenever the groups are unbalanced.
- **Tukey letters:** groups sharing a letter do not differ significantly. They are shown
  only when the ANOVA is significant.
- **Repeated measures:** if the same respondents rate every item, items are not
  independent. Tests are per item and are not comparisons between items.

## Python API

Use it from your own code, e.g. straight after a processing step:

```python
from survey_stats import from_dataframe, run

ds = from_dataframe(
    df,                                         # wide DataFrame
    value_labels={"sex": {1: "Male", 2: "Female"}},
    variable_labels={"q1": "Standing"},
    non_substantive={"q1": [99]},
)
out = run({"items": {"columns": ["q*"]}, "factors": [{"column": "sex", "name": "Sex"}],
           "output": {"dir": "out"}}, dataset=ds)
out.results.tests_table()                       # pandas DataFrame
```

`run("config.json")` runs a config file. The result also holds `descriptives`,
`posthoc_table()`, the prepared long data (`results.prep.long`) and messages about
exclusions.

## Development

```bash
pip install -e '.[dev]'
pytest
ruff check .
```

The statistics are tested against independent calculations (statsmodels OLS, scipy
t-intervals, Type III model comparison), not only against this package's own output.
