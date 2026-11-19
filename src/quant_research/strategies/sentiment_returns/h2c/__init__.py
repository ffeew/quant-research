"""H2-C earnings-call tone surprise -> post-event beta-adjusted returns, as importable library code.

Pure functions over in-memory inputs (no file or network IO here):

- ``config``   parameters and partitions (from ``configs/sentiment_returns.toml`` [h2c]); holdout expectations are
  runtime inputs only (``QR_H2C_HOLDOUT_EXPECTED`` file), never committed.
- ``schema``   validators for AV price / earnings / transcript payloads and sha256sum-format listings.
- ``events``   event construction, timing filters, straddle-purge counts.
- ``signal``   call tone and tone surprise.
- ``target``   252-day beta and beta-adjusted forward return.
- ``stats``    Newey-West t, per-quarter L/S metrics, G1 (DEV) and G2 (holdout) gates.
- ``gating``   generic partition / purge / expected-count checks.
- ``pipeline`` end-to-end ``run_h2c`` over one partition.

The frozen pre-registered runner stays in ``sentiment_returns/h2c_dev_run.py``; this package is a refactor for reuse.

Pre-2010 transcript exclusion and the ``excl_before_partition`` status for pre-partition holdout earnings rows are unverified against main_holdout; not for holdout use.
"""

from .config import H2CParams, HoldoutExpectations, Partition, load_h2c_params, load_holdout_expectations
from .errors import H2CError
from .pipeline import run_h2c

__all__ = [
    "H2CError",
    "H2CParams",
    "HoldoutExpectations",
    "Partition",
    "load_h2c_params",
    "load_holdout_expectations",
    "run_h2c",
]
