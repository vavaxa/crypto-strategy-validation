"""Market-regime segmentation: hidden-state labelling + change-point detection.

Implements:
  * regime_segmentation -- HMM (or Gaussian-mixture fallback) state labels plus
    change-points (ruptures PELT, or a self-contained CUSUM fallback).

The function degrades gracefully: it prefers ``hmmlearn`` for the HMM and
``ruptures`` for change-points, but falls back to scikit-learn's
GaussianMixture and an own CUSUM implementation if those are unavailable.

Sources:
  Hamilton, J. D. (1989). "A New Approach to the Economic Analysis of
    Nonstationary Time Series and the Business Cycle." Econometrica, 57(2).
  Page, E. S. (1954). "Continuous Inspection Schemes." Biometrika, 41 (CUSUM).
  Killick, Fearnhead & Eckley (2012). "Optimal detection of changepoints with a
    linear computational cost" (PELT, used by ``ruptures``).
"""
from __future__ import annotations

import numpy as np

__all__ = ["regime_segmentation", "cusum_changepoints"]


def cusum_changepoints(x, threshold=None, drift=0.0):
    """Two-sided CUSUM mean-shift change-point detector (Page 1954).

    Maintains cumulative sums of deviations from the running mean:
        g_high = max(0, g_high + (x_t - mean - drift))
        g_low  = max(0, g_low  - (x_t - mean + drift))
    A change-point is flagged when either exceeds ``threshold``; the detector
    then resets. ``threshold`` defaults to 5 * std(x).

    Returns a sorted numpy array of change-point indices.
    """
    x = np.asarray(x, dtype=float)
    mean = x.mean()
    sd = x.std()
    if threshold is None:
        threshold = 5.0 * sd if sd > 0 else 1.0
    g_hi = 0.0
    g_lo = 0.0
    cps = []
    for t in range(x.size):
        g_hi = max(0.0, g_hi + (x[t] - mean - drift))
        g_lo = max(0.0, g_lo - (x[t] - mean + drift))
        if g_hi > threshold or g_lo > threshold:
            cps.append(t)
            g_hi = 0.0
            g_lo = 0.0
    return np.asarray(cps, dtype=int)


def _fit_hmm(feats, n_regimes, seed):
    from hmmlearn.hmm import GaussianHMM
    model = GaussianHMM(n_components=n_regimes, covariance_type="full",
                        n_iter=200, random_state=seed)
    model.fit(feats)
    labels = model.predict(feats)
    return labels, "hmm"


def _fit_gmm(feats, n_regimes, seed):
    from sklearn.mixture import GaussianMixture
    model = GaussianMixture(n_components=n_regimes, covariance_type="full",
                            n_init=5, random_state=seed)
    labels = model.fit_predict(feats)
    return labels, "gaussian_mixture"


def _changepoints_ruptures(signal, penalty):
    import ruptures as rpt
    algo = rpt.Pelt(model="rbf").fit(signal)
    bkps = algo.predict(pen=penalty)
    # ruptures returns breakpoints including the final index; drop it
    return np.asarray([b for b in bkps if b < len(signal)], dtype=int)


def regime_segmentation(series, n_regimes=2, use_vol=True, vol_window=20,
                        seed=0, cp_penalty=None):
    """Segment a return series into regimes and detect change-points.

    Parameters
    ----------
    series : 1-D array-like of returns (or a price-change / signal series).
    n_regimes : number of hidden regimes for the HMM / mixture.
    use_vol : if True, use [return, rolling-volatility] as the 2-D feature so
        that high-vol and low-vol regimes separate; else use returns only.
    vol_window : rolling window (obs) for the volatility feature.
    seed : random seed for reproducibility.
    cp_penalty : penalty for ruptures PELT; default log(n) * var(series).

    Returns
    -------
    dict:
      labels        -- (n,) integer regime label per observation,
      regime_method -- "hmm" or "gaussian_mixture",
      changepoints  -- indices where the mean/variance structure shifts,
      cp_method     -- "ruptures" or "cusum",
      regime_stats  -- per-label {mean, std, count}.
    """
    r = np.asarray(series, dtype=float).reshape(-1)
    n = r.size
    if n < max(10, n_regimes * 3):
        raise ValueError("series too short for the requested number of regimes.")

    # feature matrix
    if use_vol:
        vol = np.empty(n)
        for i in range(n):
            lo = max(0, i - vol_window + 1)
            vol[i] = r[lo:i + 1].std()
        vol = np.nan_to_num(vol)
        feats = np.column_stack([r, vol])
    else:
        feats = r.reshape(-1, 1)

    # --- regime labels: HMM, then Gaussian mixture fallback ---
    try:
        labels, regime_method = _fit_hmm(feats, n_regimes, seed)
    except Exception:
        labels, regime_method = _fit_gmm(feats, n_regimes, seed)

    # --- change-points: ruptures, then CUSUM fallback ---
    signal = feats
    if cp_penalty is None:
        cp_penalty = np.log(max(n, 2)) * (np.var(r) + 1e-12)
    try:
        changepoints = _changepoints_ruptures(signal, cp_penalty)
        cp_method = "ruptures"
    except Exception:
        changepoints = cusum_changepoints(r)
        cp_method = "cusum"

    # per-regime descriptive stats
    regime_stats = {}
    for lab in np.unique(labels):
        mask = labels == lab
        regime_stats[int(lab)] = {
            "mean": float(r[mask].mean()),
            "std": float(r[mask].std()),
            "count": int(mask.sum()),
        }

    return {
        "labels": labels,
        "regime_method": regime_method,
        "changepoints": np.asarray(changepoints, dtype=int),
        "cp_method": cp_method,
        "regime_stats": regime_stats,
    }
