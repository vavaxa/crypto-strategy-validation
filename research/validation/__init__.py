"""research.validation -- reusable statistical validation of a trading edge.

Pure numpy/pandas statistical functions (series of returns or a matrix of
configurations) that do NOT depend on any project data, designed to be robust
to self-deception (selection bias, backtest overfitting, data snooping,
autocorrelation, non-stationarity).

Modules
-------
sharpe            PSR, Deflated Sharpe Ratio, Lo (2002) autocorrelation-adjusted
                  Sharpe with Newey-West SE.
overfitting       Probability of Backtest Overfitting via CSCV.
data_snooping     White's Reality Check, Hansen's SPA.
bootstrap         Politis-Romano stationary bootstrap + CI of any statistic.
cross_validation  Purged K-fold and walk-forward with embargo.
regimes           HMM / Gaussian-mixture regime labels + change-point detection.
"""
from .sharpe import (
    sharpe_ratio,
    probabilistic_sharpe_ratio,
    expected_max_sharpe,
    deflated_sharpe_ratio,
    sharpe_lo,
)
from .overfitting import pbo_cscv, sharpe_perf
from .data_snooping import whites_reality_check, hansen_spa
from .bootstrap import stationary_bootstrap_indices, block_bootstrap_ci
from .cross_validation import purged_kfold, purged_walk_forward
from .regimes import regime_segmentation, cusum_changepoints

__all__ = [
    "sharpe_ratio",
    "probabilistic_sharpe_ratio",
    "expected_max_sharpe",
    "deflated_sharpe_ratio",
    "sharpe_lo",
    "pbo_cscv",
    "sharpe_perf",
    "whites_reality_check",
    "hansen_spa",
    "stationary_bootstrap_indices",
    "block_bootstrap_ci",
    "purged_kfold",
    "purged_walk_forward",
    "regime_segmentation",
    "cusum_changepoints",
]
