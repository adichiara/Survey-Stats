"""Run Survey-Stats straight from this folder, without installing it.

Use this when you can't (or don't want to) pip-install the package: no executables
are created and no virtual environment is needed. It only needs the libraries
listed in pyproject.toml (pandas, numpy, scipy, statsmodels, matplotlib,
python-docx; plus pyreadstat for .sav and openpyxl for .xlsx).

    python run_survey_stats.py init --type qualtrics_run --path runs/my_run -o my_report.json
    python run_survey_stats.py validate my_report.json
    python run_survey_stats.py run my_report.json

Run it from anywhere: paths in the commands are relative to where you run it, and
paths inside a config are relative to the config file.
"""

import sys
from pathlib import Path

# Use the code in this folder's src/, ahead of any installed copy.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from survey_stats.cli import main

if __name__ == "__main__":
    sys.exit(main())
