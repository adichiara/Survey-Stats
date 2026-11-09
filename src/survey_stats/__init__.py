"""Group-comparison statistics, error-bar plots and Word tables for wide survey data."""

from .loaders import Dataset, from_dataframe, load_source
from .runner import RunOutput, run

__all__ = ["Dataset", "RunOutput", "from_dataframe", "load_source", "run"]
__version__ = "0.1.0"
