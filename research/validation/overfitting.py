"""Probability of Backtest Overfitting via Combinatorially Symmetric
Cross-Validation (CSCV).

Implements:
  * pbo_cscv -- Bailey, Borwein, Lopez de Prado & Zhu (2017)

Source:
  Bailey, D. H., Borwein, J. M., Lopez de Prado, M., & Zhu, Q. J. (2017).
    "The Probability of Backtest Overfitting." Journal of Computational
    Finance, 20(4), 39-69.
"""
from __future__ import annotations

from itertools import combinations

import numpy as np

__all__ = ["pbo_cscv", "sharpe_perf"]


def sharpe_perf(block):
    """Default CSCV performance metric: per-column Sharpe ratio of a (t x N)
    block of returns (mean / std, population std to stay defined for 1 row)."""
    block = np.asarray(block, dtype=float)
    mu = block.mean(axis=0)
    sd = block.std(axis=0, ddof=0)
    sd = np.where(sd <= 1e-15, 1e-15, sd)
    return mu / sd


def pbo_cscv(returns_matrix, n_splits=16, perf_fn=sharpe_perf):
    """Probability of Backtest Overfitting via CSCV.

    Parameters
    ----------
    returns_matrix : (T, N) array; T time observations, N strategy configs.
    n_splits : number of disjoint submatrices S (must be even). All C(S, S/2)
        train/test partitions are evaluated.
    perf_fn : callable (block -> (N,) performance vector); default Sharpe.

    Algorithm (Bailey et al. 2017)
    ------------------------------
    1. Split the T rows into S disjoint submatrices of equal size.
    2. For every way of choosing S/2 submatrices as the IN-SAMPLE (train) set J
       (complement = OUT-OF-SAMPLE test set J_bar):
         a. n* = argmax_n perf(J)           -> best config in sample.
         b. rank perf(J_bar) across configs; omega = relative rank of n* in
            (0, 1), omega = rank(n*) / (N + 1), rank in 1..N.
         c. logit lambda = ln( omega / (1 - omega) ).
    3. PBO = P[lambda <= 0] = fraction of partitions where the IS-best config
       lands below the OOS median.  lambda ~ 0.5 split -> PBO ~ 0.5 means the
       strategy selection is no better than chance (pure overfitting).

    Returns
    -------
    dict: pbo, logits (array), omegas (relative ranks), n_combinations.
    """
    M = np.asarray(returns_matrix, dtype=float)
    if M.ndim != 2:
        raise ValueError("returns_matrix must be 2-D (T x N).")
    T, N = M.shape
    if n_splits % 2 != 0:
        raise ValueError("n_splits (S) must be even.")
    if n_splits > T:
        raise ValueError("n_splits cannot exceed number of rows T.")

    # 1. disjoint, (approximately) equal submatrices by row index
    row_blocks = np.array_split(np.arange(T), n_splits)

    logits = []
    omegas = []
    all_sets = range(n_splits)
    for train_sets in combinations(all_sets, n_splits // 2):
        train_sets = set(train_sets)
        train_rows = np.concatenate([row_blocks[s] for s in all_sets if s in train_sets])
        test_rows = np.concatenate([row_blocks[s] for s in all_sets if s not in train_sets])

        r_is = perf_fn(M[train_rows])     # (N,)
        r_oos = perf_fn(M[test_rows])     # (N,)

        n_star = int(np.argmax(r_is))
        # relative rank of n_star among OOS performances (1 = worst .. N = best)
        # rank via average ranking to handle ties
        order = np.argsort(np.argsort(r_oos)) + 1  # ranks 1..N
        rank_nstar = order[n_star]
        omega = rank_nstar / (N + 1.0)
        omega = min(max(omega, 1e-6), 1.0 - 1e-6)
        omegas.append(omega)
        logits.append(np.log(omega / (1.0 - omega)))

    logits = np.asarray(logits, dtype=float)
    omegas = np.asarray(omegas, dtype=float)
    pbo = float(np.mean(logits <= 0.0))
    return {
        "pbo": pbo,
        "logits": logits,
        "omegas": omegas,
        "n_combinations": logits.size,
    }
