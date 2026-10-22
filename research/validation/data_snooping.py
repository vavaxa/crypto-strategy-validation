"""Data-snooping tests: White's Reality Check and Hansen's SPA.

Both test the null hypothesis that NONE of the candidate strategies beats the
benchmark, accounting for the fact that the best of many strategies was selected
(multiple-testing / data-snooping bias).  Dependence is handled by the
stationary bootstrap (Politis-Romano 1994).

Implements:
  * whites_reality_check -- White (2000)
  * hansen_spa           -- Hansen (2005)

Sources:
  White, H. (2000). "A Reality Check for Data Snooping." Econometrica, 68(5),
    1097-1126.
  Hansen, P. R. (2005). "A Test for Superior Predictive Ability." Journal of
    Business & Economic Statistics, 23(4), 365-380.
"""
from __future__ import annotations

import numpy as np

try:
    from .bootstrap import stationary_bootstrap_indices
except ImportError:  # running as a bare script / tests from inside the package
    from bootstrap import stationary_bootstrap_indices

__all__ = ["whites_reality_check", "hansen_spa"]


def _relative_perf(strategy_returns, benchmark_returns):
    """Per-period out-performance d_{l,t} = strat_l - benchmark, shape (T, L)."""
    s = np.asarray(strategy_returns, dtype=float)
    if s.ndim == 1:
        s = s[:, None]
    b = np.asarray(benchmark_returns, dtype=float).reshape(-1)
    if b.size != s.shape[0]:
        raise ValueError("benchmark length must match strategy rows (T).")
    return s - b[:, None]


def whites_reality_check(strategy_returns, benchmark_returns, n_boot=1000,
                         block_len=None, rng=None):
    """White's (2000) Reality Check for data snooping.

    Let d_{l,t} = strategy_l return - benchmark return, f_l = mean_t d_{l,t}.
    Test statistic (White, 2000):

        V = max_l  sqrt(T) * f_l

    H0: max_l E[d_l] <= 0  (no strategy out-performs the benchmark).
    Stationary-bootstrap resamples give V*_b = max_l sqrt(T)*(f*_l - f_l)
    (recentered on the sample means).  The p-value is the fraction of V*_b >= V.

    Parameters
    ----------
    strategy_returns : (T,) or (T, L) returns of the L candidate strategies.
    benchmark_returns : (T,) benchmark returns.
    n_boot : bootstrap resamples.
    block_len : expected block length; default max(1, round(T**(1/3))).

    Returns
    -------
    dict: statistic (V), p_value, best (argmax strategy), f (mean outperf.),
    boot (array of V*_b).
    """
    d = _relative_perf(strategy_returns, benchmark_returns)
    T, L = d.shape
    if block_len is None:
        block_len = max(1, int(round(T ** (1.0 / 3.0))))
    f = d.mean(axis=0)                      # (L,)
    sqrtT = np.sqrt(T)
    V = float(np.max(sqrtT * f))

    idx = stationary_bootstrap_indices(T, block_len, n_boot, rng=rng)
    boot = np.empty(n_boot, dtype=float)
    for bix in range(n_boot):
        fb = d[idx[bix]].mean(axis=0)       # bootstrap means
        boot[bix] = np.max(sqrtT * (fb - f))
    p_value = float(np.mean(boot >= V))
    return {
        "statistic": V,
        "p_value": p_value,
        "best": int(np.argmax(f)),
        "f": f,
        "boot": boot,
    }


def hansen_spa(strategy_returns, benchmark_returns, n_boot=1000, block_len=None,
               rng=None):
    """Hansen's (2005) Test for Superior Predictive Ability (SPA_c).

    Studentized version of the Reality Check with a data-dependent recentering
    that removes strategies known to be poor, giving a less conservative, more
    powerful test.  With f_l = mean_t d_{l,t} and omega_l^2 the bootstrap
    estimate of Var(sqrt(T) f_l):

        T_SPA = max_l  max( sqrt(T) * f_l / omega_l , 0 )

    Consistent recentering (SPA_c): the bootstrap distribution is centered on
        g_l = f_l * 1{ sqrt(T) f_l / omega_l >= -sqrt(2 log log T) }
    and the bootstrap statistic is
        T*_b = max_l  max( sqrt(T) (f*_l - g_l) / omega_l , 0 ).
    p-value = fraction of T*_b >= T_SPA.

    Returns
    -------
    dict: statistic (T_SPA), p_value, best, f, omega, boot.
    """
    d = _relative_perf(strategy_returns, benchmark_returns)
    T, L = d.shape
    if block_len is None:
        block_len = max(1, int(round(T ** (1.0 / 3.0))))
    f = d.mean(axis=0)
    sqrtT = np.sqrt(T)

    idx = stationary_bootstrap_indices(T, block_len, n_boot, rng=rng)
    fb = np.empty((n_boot, L), dtype=float)
    for bix in range(n_boot):
        fb[bix] = d[idx[bix]].mean(axis=0)

    # omega_l^2 = bootstrap variance of sqrt(T) * f_l
    omega = np.sqrt(T * fb.var(axis=0, ddof=1))
    omega = np.where(omega <= 1e-12, 1e-12, omega)

    z = sqrtT * f / omega
    T_SPA = float(max(0.0, np.max(z)))

    # consistent recentering threshold
    thr = -np.sqrt(2.0 * np.log(np.log(T))) if T > np.e else 0.0
    g = np.where(z >= thr, f, 0.0)

    boot = np.empty(n_boot, dtype=float)
    for bix in range(n_boot):
        zb = sqrtT * (fb[bix] - g) / omega
        boot[bix] = max(0.0, np.max(zb))
    p_value = float(np.mean(boot >= T_SPA))
    return {
        "statistic": T_SPA,
        "p_value": p_value,
        "best": int(np.argmax(z)),
        "f": f,
        "omega": omega,
        "boot": boot,
    }
