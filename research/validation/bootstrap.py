"""Block / stationary bootstrap tools for dependent time series.

Implements:
  * stationary_bootstrap_indices -- Politis & Romano (1994) index generator
  * block_bootstrap_ci           -- confidence interval of an arbitrary statistic

Source:
  Politis, D. N., & Romano, J. P. (1994). "The Stationary Bootstrap."
    Journal of the American Statistical Association, 89(428), 1303-1313.
"""
from __future__ import annotations

import numpy as np

__all__ = ["stationary_bootstrap_indices", "block_bootstrap_ci"]


def stationary_bootstrap_indices(n, block_len, n_boot, rng=None):
    """Generate (n_boot x n) resampling indices via the stationary bootstrap.

    Blocks have random (geometric) length with mean ``block_len``; a new block
    starts with probability p = 1 / block_len at each step, otherwise the index
    advances by one (circularly, modulo n).  This yields a strictly stationary
    resampled series and preserves short-range dependence.

    Parameters
    ----------
    n : length of the original series.
    block_len : expected block length (>= 1).  p = 1 / block_len.
    n_boot : number of bootstrap resamples.
    rng : optional numpy Generator / seed.
    """
    rng = np.random.default_rng(rng)
    if block_len < 1:
        raise ValueError("block_len must be >= 1")
    p = 1.0 / block_len
    idx = np.empty((n_boot, n), dtype=np.int64)
    for b in range(n_boot):
        out = np.empty(n, dtype=np.int64)
        cur = rng.integers(0, n)
        for t in range(n):
            if t == 0 or rng.random() < p:
                cur = rng.integers(0, n)   # start a fresh block
            else:
                cur = (cur + 1) % n        # continue current block
            out[t] = cur
        idx[b] = out
    return idx


def block_bootstrap_ci(returns, stat_fn, block_len=None, n_boot=1000,
                       alpha=0.05, rng=None):
    """Confidence interval of an arbitrary statistic via stationary bootstrap.

    Resamples the series ``n_boot`` times with the Politis-Romano stationary
    bootstrap, recomputes ``stat_fn`` on each resample, and returns the two-sided
    percentile confidence interval at level (1 - alpha).

    Parameters
    ----------
    returns : 1-D array-like series.
    stat_fn : callable mapping a 1-D array to a float (e.g. np.mean, a Sharpe).
    block_len : expected block length; default max(1, round(n**(1/3))).
    n_boot : number of resamples.
    alpha : two-sided significance (0.05 -> 95% CI).

    Returns
    -------
    dict: point (stat on original), ci_low, ci_high, se (bootstrap std),
    boot (array of bootstrap statistics).
    """
    r = np.asarray(returns, dtype=float)
    n = r.size
    if block_len is None:
        block_len = max(1, int(round(n ** (1.0 / 3.0))))
    point = float(stat_fn(r))
    idx = stationary_bootstrap_indices(n, block_len, n_boot, rng=rng)
    boot = np.array([stat_fn(r[idx[b]]) for b in range(n_boot)], dtype=float)
    lo = float(np.percentile(boot, 100.0 * (alpha / 2.0)))
    hi = float(np.percentile(boot, 100.0 * (1.0 - alpha / 2.0)))
    return {
        "point": point,
        "ci_low": lo,
        "ci_high": hi,
        "se": float(boot.std(ddof=1)),
        "boot": boot,
    }
