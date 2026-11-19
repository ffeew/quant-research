"""H3 weekly news-sentiment cross-section -> next-week returns, as importable library code.

Pure functions over in-memory inputs (no file or network IO here):

- ``config``  parameters from ``configs/sentiment_returns.toml`` [h3]; design choices that are not settled are
  explicit optional parameters with no committed value, and code paths that need them raise ``ConfigError``.
- ``weeks``   weekly decision dates from a session list, 15:30 ET cutoffs, month padding.
- ``signal``  per-name relevance-weighted window score and the weekly qualifying cross-section.
- ``book``    80/60 band book (and plain quintile variant), equal weights, drift, turnover, costs.
- ``stats``   one-sided Newey-West test, sector-demeaned IC, per-variant summary and the DEV gate.

The draft runner stays in ``sentiment_returns/h3_dev_runner.py``; this package is a refactor for reuse.
"""
from .config import H3Params, load_h3_params
from .errors import H3ConfigError

__all__ = ["H3ConfigError", "H3Params", "load_h3_params"]
