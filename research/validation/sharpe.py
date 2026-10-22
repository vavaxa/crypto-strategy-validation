"""Sharpe-ratio based edge metrics robust to selection bias and non-normality.

Implements:
  * probabilistic_sharpe_ratio (PSR)    -- Bailey & Lopez de Prado (2012)
  * expected_max_sharpe                 -- Bailey & Lopez de Prado (2014)
  * deflated_sharpe_ratio (DSR)         -- Bailey & Lopez de Prado (2014)
  * sharpe_lo                           -- Lo (2002), Newey-West / HAC SE

Convention for all Sharpe inputs (sr_observed, sr_benchmark, var_sr):
  Sharpe ratios are expressed PER OBSERVATION (non-annualized), consistent with
  the number of observations ``T``.  ``kurt`` is the NON-EXCESS kurtosis
  (a Gaussian has kurt = 3, skew = 0).

Sources:
  Bailey, D. H., & Lopez de Prado, M. (2012). "The Sharpe Ratio Efficient
    Frontier." Journal of Risk, 15(2), 3-44.
  Bailey, D. H., & Lopez de Prado, M. (2014). "The Deflated Sharpe Ratio:
    Correcting for Selection Bias, Backtest Overfitting, and Non-Normality."
    Journal of Portfolio Management, 40(5), 94-107.
  Lo, A. W. (2002). "The Statistics of Sharpe Ratios." Financial Analysts
    Journal, 58(4), 36-52.
"""
from __future__ import annotations

import numpy as np
from scipy import stats

__all__ = [
    "sharpe_ratio",
    "probabilistic_sharpe_ratio",
    "expected_max_sharpe",
    "deflated_sharpe_ratio",
    "sharpe_lo",
]

_EULER_MASCHERONI = 0.5772156649015329


def sharpe_ratio(returns: np.ndarray, ddof: int = 1) -> float:
    """Per-observation (non-annualized) Sharpe ratio mean(r) / std(r)."""
    r = np.asarray(returns, dtype=float)
    sd = r.std(ddof=ddof)
    if sd == 0:
        return 0.0
    return float(r.mean() / sd)


def _sr_estimator_variance(sr: float, T: int, skew: float, kurt: float) -> float:
    """Sampling variance of the Sharpe-ratio estimator (Mertens / Lo).

    Var(SR_hat) = (1 - skew*SR + (kurt-1)/4 * SR**2) / (T - 1)

    ``kurt`` is non-excess (Gaussian = 3).  Under Gaussian IID this reduces to
    (1 + SR**2 / 2) / (T - 1), the classic Lo (2002) result.
    """
    return (1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr) / (T - 1.0)


def probabilistic_sharpe_ratio(sr_observed, T, skew=0.0, kurt=3.0, sr_benchmark=0.0):
    """Probabilistic Sharpe Ratio -- Bailey & Lopez de Prado (2012), eq. (3).

    PSR(SR*) = Phi( (SR_hat - SR*) * sqrt(T - 1)
                    / sqrt(1 - g3*SR_hat + (g4 - 1)/4 * SR_hat**2) )

    where Phi is the standard-normal CDF, g3 = skew, g4 = kurt (non-excess),
    T = number of return observations, SR* = sr_benchmark.

    PSR estimates the probability that the TRUE Sharpe ratio exceeds the
    benchmark ``sr_benchmark`` given the track record, correcting for the
    track-record length and the non-normality (skew/kurt) of returns.

    Returns
    -------
    dict with keys: psr, z (test statistic), sr_std (estimator SE),
    p_value (= 1 - psr, H0: true SR <= sr_benchmark).
    """
    sr = float(sr_observed)
    var = _sr_estimator_variance(sr, T, skew, kurt)
    if var <= 0:
        raise ValueError("Non-positive Sharpe-estimator variance; check skew/kurt/T.")
    sr_std = np.sqrt(var)
    z = (sr - sr_benchmark) / sr_std
    psr = float(stats.norm.cdf(z))
    return {
        "psr": psr,
        "z": float(z),
        "sr_std": float(sr_std),
        "p_value": float(1.0 - psr),
    }


def expected_max_sharpe(n_trials, var_sr):
    """Expected maximum Sharpe ratio across ``n_trials`` independent trials.

    E[max SR] ~= sqrt(var_sr) * [ (1 - gamma) * Z^-1(1 - 1/N)
                                  + gamma * Z^-1(1 - 1/(N*e)) ]

    gamma = Euler-Mascheroni constant, Z^-1 = inverse standard-normal CDF,
    var_sr = cross-sectional variance of the trials' Sharpe ratios, N = n_trials.
    Bailey & Lopez de Prado (2014), eq. (5).
    """
    if n_trials < 1:
        raise ValueError("n_trials must be >= 1")
    if n_trials == 1:
        return 0.0
    N = float(n_trials)
    z1 = stats.norm.ppf(1.0 - 1.0 / N)
    z2 = stats.norm.ppf(1.0 - 1.0 / (N * np.e))
    maxz = (1.0 - _EULER_MASCHERONI) * z1 + _EULER_MASCHERONI * z2
    return float(np.sqrt(var_sr) * maxz)


def deflated_sharpe_ratio(sr_observed, n_trials, T, skew=0.0, kurt=3.0,
                          sr_benchmark=0.0, var_sr=None):
    """Deflated Sharpe Ratio -- Bailey & Lopez de Prado (2014).

    DSR = PSR(SR*) where the benchmark is deflated to the expected maximum
    Sharpe achievable by chance across ``n_trials`` configurations:

        SR* = sr_benchmark + E[max SR | n_trials, var_sr]

    and DSR = Phi( (SR_hat - SR*) * sqrt(T - 1)
                   / sqrt(1 - g3*SR_hat + (g4 - 1)/4 * SR_hat**2) ).

    ``var_sr`` is the cross-sectional variance of the Sharpe ratios of the
    trials that were actually tried.  When it is unknown (``None``) we fall back
    to the null model in which every trial has true Sharpe = 0 and the observed
    dispersion of trial Sharpes is pure estimation noise, i.e.
    var_sr = Var(SR_hat) = (1 - skew*SR + (kurt-1)/4 * SR**2) / (T - 1).

    Returns
    -------
    dict: dsr, p_value (= 1 - dsr, H0: no edge beyond the deflated benchmark),
    sr_star (deflated benchmark), psr (vs raw sr_benchmark), expected_max,
    var_sr (used).
    """
    sr = float(sr_observed)
    if var_sr is None:
        var_sr = _sr_estimator_variance(sr, T, skew, kurt)
    emax = expected_max_sharpe(n_trials, var_sr)
    sr_star = sr_benchmark + emax
    dsr = probabilistic_sharpe_ratio(sr, T, skew, kurt, sr_benchmark=sr_star)
    psr_raw = probabilistic_sharpe_ratio(sr, T, skew, kurt, sr_benchmark=sr_benchmark)
    return {
        "dsr": dsr["psr"],
        "p_value": dsr["p_value"],
        "sr_star": float(sr_star),
        "expected_max": float(emax),
        "psr": psr_raw["psr"],
        "var_sr": float(var_sr),
    }


def _newey_west_cov(g: np.ndarray, lag: int) -> np.ndarray:
    """Newey-West (1987) HAC covariance of a (T x k) array of influence terms.

    S = Gamma_0 + sum_{j=1}^{lag} (1 - j/(lag+1)) (Gamma_j + Gamma_j')
    Gamma_j = (1/T) sum_t g_t g_{t-j}'.
    """
    g = np.asarray(g, dtype=float)
    T = g.shape[0]
    g = g - g.mean(axis=0, keepdims=True)
    S = (g.T @ g) / T
    for j in range(1, lag + 1):
        w = 1.0 - j / (lag + 1.0)
        gamma = (g[j:].T @ g[:-j]) / T
        S += w * (gamma + gamma.T)
    return S


def sharpe_lo(returns, q=1, nw_lag=None, ddof=1):
    """Autocorrelation-corrected Sharpe ratio and HAC standard error -- Lo (2002).

    Annualization under IID uses sqrt(q); Lo (2002) shows that with serially
    correlated returns the correct multi-period scaling factor is

        eta(q) = q / sqrt( q + 2 * sum_{k=1}^{q-1} (q - k) * rho_k )

    where rho_k is the lag-k autocorrelation of returns.  The annualized Sharpe
    is eta(q) * SR, versus the naive sqrt(q) * SR.

    The standard error of the (per-period) Sharpe ratio is obtained by the GMM /
    delta-method of Lo (2002, Prop. 2) using a Newey-West HAC estimator of the
    moment covariance, so it is robust to autocorrelation and non-normality.
    With moments theta = (mu, m2) where m2 = E[r^2] and SR = mu / sqrt(m2 - mu^2),
    gradient d = (dSR/dmu, dSR/dm2):
        dSR/dmu = (1/sigma) * (1 + SR^2)      ... wait see code; computed exactly
        dSR/dm2 = -SR / (2 * sigma^2)
    Var(SR_hat) = d' S d / T, S = HAC cov of (r - mu, r^2 - m2).

    Parameters
    ----------
    returns : array of per-period returns.
    q : annualization horizon (e.g. 12 monthly->annual, 252 daily->annual).
    nw_lag : Newey-West lag; default max(q - 1, 0).

    Returns
    -------
    dict: sharpe (per-period), sharpe_annual (eta-adjusted), sharpe_annual_naive
    (sqrt(q)), eta, se (HAC SE of per-period Sharpe), t_stat, p_value (two-sided).
    """
    r = np.asarray(returns, dtype=float)
    T = r.size
    if T < 3:
        raise ValueError("Need at least 3 observations.")
    mu = r.mean()
    sigma = r.std(ddof=ddof)
    if sigma == 0:
        raise ValueError("Zero return variance.")
    sr = mu / sigma

    # eta(q) autocorrelation adjustment
    if nw_lag is None:
        nw_lag = max(q - 1, 0)
    if q <= 1:
        eta = 1.0
    else:
        rc = r - mu
        denom_acf = np.sum(rc * rc)
        acc = 0.0
        for k in range(1, q):
            if k >= T:
                break
            rho_k = np.sum(rc[k:] * rc[:-k]) / denom_acf
            acc += (q - k) * rho_k
        eta = q / np.sqrt(q + 2.0 * acc)

    # HAC standard error via GMM delta method on (mu, m2)
    m2 = np.mean(r ** 2)
    sig2 = m2 - mu ** 2  # population variance
    g = np.column_stack([r - mu, r ** 2 - m2])
    S = _newey_west_cov(g, nw_lag)
    # gradient of SR = mu * (m2 - mu^2)^(-1/2)
    sig = np.sqrt(sig2)
    dSR_dmu = 1.0 / sig + mu ** 2 / sig ** 3   # = (1/sig)(1 + SR^2)
    dSR_dm2 = -mu / (2.0 * sig ** 3)           # = -SR/(2 sig^2)
    d = np.array([dSR_dmu, dSR_dm2])
    var_sr = float(d @ S @ d) / T
    se = np.sqrt(var_sr)
    t_stat = sr / se if se > 0 else np.inf
    p_value = float(2.0 * (1.0 - stats.norm.cdf(abs(t_stat))))
    return {
        "sharpe": float(sr),
        "sharpe_annual": float(eta * sr),
        "sharpe_annual_naive": float(np.sqrt(q) * sr),
        "eta": float(eta),
        "se": float(se),
        "t_stat": float(t_stat),
        "p_value": p_value,
    }
