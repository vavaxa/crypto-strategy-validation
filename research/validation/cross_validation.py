"""Leakage-free cross-validation for time series with overlapping labels.

Implements:
  * purged_kfold        -- purged K-fold with embargo
  * purged_walk_forward -- anchored/rolling walk-forward with purge gap

Source:
  Lopez de Prado, M. (2018). "Advances in Financial Machine Learning",
    chapter 7 ("Cross-Validation in Finance").

Both return lists of (train_idx, test_idx) numpy index arrays so they can drive
any estimator without depending on project data.
"""
from __future__ import annotations

import numpy as np

__all__ = ["purged_kfold", "purged_walk_forward"]


def purged_kfold(n_samples, n_splits=5, embargo_pct=0.01, t1=None):
    """Purged K-fold cross-validation with embargo (Lopez de Prado 2018, ch.7).

    The T observations are split into ``n_splits`` CONTIGUOUS test folds. For
    each fold the training set is everything else, minus:
      * PURGE: training observations whose label span overlaps the test window.
        When label end-times ``t1`` are supplied, a train observation i is
        purged if its label interval [i, t1[i]] overlaps the test interval
        [test_start, test_end]. Without ``t1`` the test block itself is the only
        overlap removed.
      * EMBARGO: the first ``embargo = round(embargo_pct * T)`` training
        observations immediately AFTER the test block are dropped, because their
        features may still be correlated with test-window information.

    Parameters
    ----------
    n_samples : int, number of observations.
    n_splits : number of folds.
    embargo_pct : embargo size as a fraction of n_samples.
    t1 : optional (n_samples,) array of integer label end-indices for true
        purging of overlapping labels.

    Returns
    -------
    list of (train_idx, test_idx) numpy arrays.
    """
    if n_splits < 2:
        raise ValueError("n_splits must be >= 2")
    indices = np.arange(n_samples)
    embargo = int(round(n_samples * embargo_pct))
    fold_bounds = [(b[0], b[-1] + 1) for b in np.array_split(indices, n_splits)]
    if t1 is not None:
        t1 = np.asarray(t1)

    splits = []
    for start, stop in fold_bounds:            # test = [start, stop)
        test_idx = indices[start:stop]
        test_start, test_end = start, stop - 1

        train_mask = np.ones(n_samples, dtype=bool)
        train_mask[start:stop] = False

        if t1 is not None:
            # purge any train obs whose label [i, t1[i]] overlaps [start, end]
            overlap = (indices <= test_end) & (t1 >= test_start)
            train_mask[overlap] = False

        # embargo: drop observations right after the test block
        if embargo > 0:
            emb_end = min(stop + embargo, n_samples)
            train_mask[stop:emb_end] = False

        train_idx = indices[train_mask]
        splits.append((train_idx, test_idx))
    return splits


def purged_walk_forward(n_samples, n_splits=5, embargo_pct=0.01, anchored=True,
                        min_train=None):
    """Walk-forward cross-validation with a purge/embargo gap.

    Produces ``n_splits`` sequential test folds; training always precedes the
    test window in time (no look-ahead). A gap of ``embargo = round(embargo_pct
    * T)`` observations is left between the end of the training window and the
    start of the test window to purge overlap/serial dependence.

    ``anchored=True`` grows the training window from index 0 (expanding);
    ``anchored=False`` uses a rolling fixed-size window.

    Returns
    -------
    list of (train_idx, test_idx) numpy arrays, in chronological order.
    """
    indices = np.arange(n_samples)
    embargo = int(round(n_samples * embargo_pct))
    fold_bounds = [(b[0], b[-1] + 1) for b in np.array_split(indices, n_splits + 1)]
    # first block is the initial training seed; remaining blocks are test folds
    test_blocks = fold_bounds[1:]
    seed_end = fold_bounds[0][1]
    if min_train is None:
        min_train = seed_end

    splits = []
    for start, stop in test_blocks:            # test = [start, stop)
        train_end = start - embargo            # leave the embargo gap
        if train_end <= 0:
            continue
        if anchored:
            train_start = 0
        else:
            train_start = max(0, train_end - min_train)
        if train_end - train_start < 1:
            continue
        train_idx = indices[train_start:train_end]
        test_idx = indices[start:stop]
        splits.append((train_idx, test_idx))
    return splits
