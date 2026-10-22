"""Known-answer and behavioural unit tests for research.validation.

Run with the project interpreter from inside the package directory:
    .venv/bin/python research/validation/test_validation.py
or via pytest:
    .venv/bin/python -m pytest research/validation/test_validation.py
"""
from __future__ import annotations

import os
import sys

import numpy as np
from scipy import stats

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sharpe import (  # noqa: E402
    sharpe_ratio,
    probabilistic_sharpe_ratio,
    expected_max_sharpe,
    deflated_sharpe_ratio,
    sharpe_lo,
)
from overfitting import pbo_cscv  # noqa: E402
from data_snooping import whites_reality_check, hansen_spa  # noqa: E402
from bootstrap import stationary_bootstrap_indices, block_bootstrap_ci  # noqa: E402
from cross_validation import purged_kfold, purged_walk_forward  # noqa: E402
from regimes import regime_segmentation, cusum_changepoints  # noqa: E402

EULER = 0.5772156649015329


# ----------------------------------------------------------------------------
# PSR / DSR
# ----------------------------------------------------------------------------
def test_psr_known_answer():
    """PSR matches the closed-form Bailey-Lopez de Prado formula exactly."""
    sr, T, skew, kurt, bench = 0.1, 101, 0.0, 3.0, 0.0
    res = probabilistic_sharpe_ratio(sr, T, skew, kurt, bench)
    # independent recomputation
    denom = np.sqrt(1 - skew * sr + (kurt - 1) / 4 * sr ** 2)
    z = (sr - bench) * np.sqrt(T - 1) / denom
    expected = stats.norm.cdf(z)
    assert abs(res["psr"] - expected) < 1e-12, res
    # numeric sanity: ~0.8413 here
    assert abs(res["psr"] - 0.84134) < 1e-3, res["psr"]


def test_psr_monotone():
    """Longer track record with the same SR -> higher PSR (more confident)."""
    p_short = probabilistic_sharpe_ratio(0.1, 50)["psr"]
    p_long = probabilistic_sharpe_ratio(0.1, 500)["psr"]
    assert p_long > p_short


def test_psr_nonnormality_penalty():
    """Negative skew and fat tails LOWER the PSR (riskier track record)."""
    p_normal = probabilistic_sharpe_ratio(0.15, 200, skew=0.0, kurt=3.0)["psr"]
    p_fat = probabilistic_sharpe_ratio(0.15, 200, skew=-1.0, kurt=8.0)["psr"]
    assert p_fat < p_normal


def test_expected_max_sharpe_known():
    """expected_max matches the closed-form E[max] for N trials, var=1."""
    N = 100
    emax = expected_max_sharpe(N, var_sr=1.0)
    z1 = stats.norm.ppf(1 - 1 / N)
    z2 = stats.norm.ppf(1 - 1 / (N * np.e))
    expected = (1 - EULER) * z1 + EULER * z2
    assert abs(emax - expected) < 1e-12
    # grows with N
    assert expected_max_sharpe(1000, 1.0) > expected_max_sharpe(10, 1.0)
    assert expected_max_sharpe(1, 1.0) == 0.0


def test_dsr_deflates_with_trials():
    """More trials -> higher deflated benchmark -> lower DSR."""
    base = dict(sr_observed=0.2, T=250, skew=0.0, kurt=3.0, var_sr=0.02)
    dsr_few = deflated_sharpe_ratio(n_trials=1, **base)
    dsr_many = deflated_sharpe_ratio(n_trials=500, **base)
    assert dsr_few["dsr"] > dsr_many["dsr"]
    # with 1 trial DSR == PSR vs the raw benchmark (expected_max == 0)
    assert abs(dsr_few["dsr"] - dsr_few["psr"]) < 1e-12
    # p-value is the complement
    assert abs(dsr_many["p_value"] - (1 - dsr_many["dsr"])) < 1e-12


def test_dsr_synthetic_true_edge_survives():
    """A strong genuine edge (few trials) keeps a high DSR; the same SR claimed
    after snooping thousands of configs gets deflated toward rejection."""
    rng = np.random.default_rng(7)
    r = rng.normal(0.15, 1.0, size=1500)   # real positive drift, strong record
    sr = sharpe_ratio(r)
    skew = stats.skew(r)
    kurt = stats.kurtosis(r, fisher=False)
    honest = deflated_sharpe_ratio(sr, n_trials=1, T=r.size, skew=skew, kurt=kurt)
    snooped = deflated_sharpe_ratio(sr, n_trials=5000, T=r.size, skew=skew, kurt=kurt)
    assert honest["dsr"] > snooped["dsr"]
    assert honest["dsr"] > 0.9  # genuine edge is convincing when not snooped


# ----------------------------------------------------------------------------
# PBO / CSCV
# ----------------------------------------------------------------------------
def test_pbo_noise_half():
    """Pure IID noise -> no real edge -> PBO ~ 0.5."""
    rng = np.random.default_rng(1)
    M = rng.normal(0, 1, size=(240, 20))
    res = pbo_cscv(M, n_splits=10)
    assert 0.35 < res["pbo"] < 0.65, res["pbo"]
    assert res["n_combinations"] == 252  # C(10,5)


def test_pbo_dominant_strategy_low():
    """One genuinely superior config -> IS-best stays best OOS -> low PBO."""
    rng = np.random.default_rng(2)
    M = rng.normal(0, 1, size=(240, 20))
    M[:, 0] += 0.35   # config 0 has a true edge in every period
    res = pbo_cscv(M, n_splits=10)
    assert res["pbo"] < 0.2, res["pbo"]


# ----------------------------------------------------------------------------
# Reality Check / SPA
# ----------------------------------------------------------------------------
def test_reality_check_noise_not_rejected():
    """Noise strategies vs a noise benchmark -> do not reject H0 (large p)."""
    rng = np.random.default_rng(3)
    strat = rng.normal(0, 1, size=(300, 15))
    bench = rng.normal(0, 1, size=300)
    rc = whites_reality_check(strat, bench, n_boot=500, rng=rng)
    spa = hansen_spa(strat, bench, n_boot=500, rng=rng)
    assert rc["p_value"] > 0.10, rc["p_value"]
    assert spa["p_value"] > 0.10, spa["p_value"]


def test_reality_check_true_edge_rejected():
    """One strategy with a real edge -> reject H0 (small p)."""
    rng = np.random.default_rng(4)
    strat = rng.normal(0, 1, size=(300, 15))
    strat[:, 3] += 0.25            # genuine out-performance
    bench = np.zeros(300)
    rc = whites_reality_check(strat, bench, n_boot=500, rng=rng)
    spa = hansen_spa(strat, bench, n_boot=500, rng=rng)
    assert rc["p_value"] < 0.05, rc["p_value"]
    assert spa["p_value"] < 0.05, spa["p_value"]
    assert rc["best"] == 3 and spa["best"] == 3


def test_spa_more_powerful_than_rc():
    """With many bad strategies and one good one, SPA's p <= RC's p (power)."""
    rng = np.random.default_rng(5)
    strat = rng.normal(-0.02, 1, size=(300, 30))   # mostly poor
    strat[:, 0] += 0.22
    bench = np.zeros(300)
    rc = whites_reality_check(strat, bench, n_boot=600, rng=rng)
    spa = hansen_spa(strat, bench, n_boot=600, rng=rng)
    assert spa["p_value"] <= rc["p_value"] + 1e-9


# ----------------------------------------------------------------------------
# Sharpe-Lo
# ----------------------------------------------------------------------------
def test_sharpe_lo_iid_matches_lo_se():
    """IID normal: eta ~ sqrt(q) and HAC SE ~ Lo's (1 + SR^2/2)/T."""
    rng = np.random.default_rng(6)
    r = rng.normal(0.05, 1.0, size=4000)
    q = 12
    res = sharpe_lo(r, q=q)
    assert abs(res["eta"] - np.sqrt(q)) < 0.15 * np.sqrt(q)  # no autocorr
    sr = res["sharpe"]
    lo_iid_se = np.sqrt((1 + sr ** 2 / 2) / r.size)
    assert abs(res["se"] - lo_iid_se) < 0.25 * lo_iid_se, (res["se"], lo_iid_se)


def test_sharpe_lo_positive_autocorr_shrinks_eta():
    """Positive AR(1) autocorrelation: corrected annual Sharpe < naive sqrt(q)."""
    rng = np.random.default_rng(8)
    n = 4000
    eps = rng.normal(0, 1, n)
    r = np.empty(n)
    r[0] = eps[0]
    phi = 0.4
    for t in range(1, n):
        r[t] = 0.03 + phi * r[t - 1] + eps[t]
    res = sharpe_lo(r, q=12)
    assert res["eta"] < np.sqrt(12), res["eta"]
    assert res["sharpe_annual"] < res["sharpe_annual_naive"]


# ----------------------------------------------------------------------------
# Stationary bootstrap / CI
# ----------------------------------------------------------------------------
def test_bootstrap_indices_valid():
    idx = stationary_bootstrap_indices(50, block_len=5, n_boot=100, rng=0)
    assert idx.shape == (100, 50)
    assert idx.min() >= 0 and idx.max() < 50


def test_block_bootstrap_ci_covers_mean():
    """CI of the mean for centered noise contains 0 and brackets the point."""
    rng = np.random.default_rng(9)
    r = rng.normal(0.0, 1.0, size=2000)
    res = block_bootstrap_ci(r, np.mean, block_len=10, n_boot=800, alpha=0.05, rng=rng)
    assert res["ci_low"] < res["point"] < res["ci_high"]
    assert res["ci_low"] < 0.0 < res["ci_high"]


# ----------------------------------------------------------------------------
# Purged CV
# ----------------------------------------------------------------------------
def test_purged_kfold_embargo_and_disjoint():
    """Train/test disjoint and the embargo region after a test fold is removed."""
    n, k, emb = 100, 5, 0.05
    splits = purged_kfold(n, n_splits=k, embargo_pct=emb)
    assert len(splits) == k
    embargo = int(round(n * emb))  # = 5
    # middle fold (index 2): test = [40,60)
    train, test = splits[2]
    assert set(train).isdisjoint(set(test))
    # the embargo window [60, 65) must be absent from train
    embargo_region = set(range(60, 60 + embargo))
    assert embargo_region.isdisjoint(set(train)), sorted(embargo_region & set(train))
    # union of train, test and embargo covers the space (nothing else dropped)
    assert set(train) | set(test) | embargo_region == set(range(n))


def test_purged_kfold_label_purging():
    """With label end-times, train obs whose labels overlap the test are purged."""
    n = 60
    t1 = np.arange(n) + 3   # each label spans 3 extra bars
    splits = purged_kfold(n, n_splits=3, embargo_pct=0.0, t1=t1)
    train, test = splits[1]                 # test = [20, 40)
    # obs 18,19 have labels reaching into [20, ...] -> purged
    assert 18 not in set(train) and 19 not in set(train)
    assert set(train).isdisjoint(set(test))


def test_purged_walk_forward_no_lookahead():
    """Every training index precedes its test window by at least the embargo gap."""
    n, k, emb = 120, 4, 0.05
    splits = purged_walk_forward(n, n_splits=k, embargo_pct=emb)
    embargo = int(round(n * emb))
    assert len(splits) >= 1
    for train, test in splits:
        assert train.max() < test.min()
        assert test.min() - train.max() - 1 >= embargo - 1  # gap respected


# ----------------------------------------------------------------------------
# Regimes
# ----------------------------------------------------------------------------
def test_regime_segmentation_two_vol_regimes():
    """A low-vol then high-vol series yields 2 regimes and a change-point."""
    rng = np.random.default_rng(10)
    r = np.concatenate([rng.normal(0, 0.5, 200), rng.normal(0, 3.0, 200)])
    res = regime_segmentation(r, n_regimes=2, seed=0)
    assert len(res["labels"]) == r.size
    assert len(np.unique(res["labels"])) == 2
    assert len(res["changepoints"]) >= 1
    # the dominant label should flip across the true boundary (index 200)
    first_half = stats.mode(res["labels"][:200], keepdims=False).mode
    second_half = stats.mode(res["labels"][200:], keepdims=False).mode
    assert first_half != second_half


def test_cusum_detects_mean_shift():
    """CUSUM flags a change when the mean jumps."""
    x = np.concatenate([np.zeros(100), np.ones(100) * 5]) + \
        np.random.default_rng(11).normal(0, 0.1, 200)
    cps = cusum_changepoints(x)
    assert len(cps) >= 1
    assert any(90 <= c <= 140 for c in cps), cps


# ----------------------------------------------------------------------------
# runner
# ----------------------------------------------------------------------------
def _run_all():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f"FAIL  {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return failures


if __name__ == "__main__":
    sys.exit(1 if _run_all() else 0)
