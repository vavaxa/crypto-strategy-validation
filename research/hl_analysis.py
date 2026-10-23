"""Hyperliquid HLP backstop risk — factual summary from a collected snapshot.

Reads ``data/hl/hl_snapshot_latest.json`` (produced by hl_collect.py) and prints the
numbers the write-up is built on. No modelling claims here — just what the public data
says, with explicit granularity caveats.
"""
from __future__ import annotations
import json, sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np

SNAP = Path(__file__).resolve().parents[1] / "data" / "hl" / "hl_snapshot_latest.json"


def ts(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def window(portfolio, name):
    for w in portfolio:
        if w[0] == name:
            return w[1]
    return None


def pnl_series(portfolio, name):
    d = window(portfolio, name)
    if not d or not d.get("pnlHistory"):
        return None, None
    hist = d["pnlHistory"]
    t = np.array([h[0] for h in hist], dtype="int64")
    v = np.array([float(h[1]) for h in hist])
    return t, v


def drawdowns(t, cum_pnl, top=5):
    """Peak-to-trough declines of the cumulative-PnL curve (how much HLP gave back)."""
    peak = np.maximum.accumulate(cum_pnl)
    dd = cum_pnl - peak                       # <= 0
    # find local trough episodes: scan for the deepest points separated by new peaks
    episodes = []
    i = 0
    n = len(cum_pnl)
    while i < n:
        if dd[i] < 0:
            j = i
            trough = i
            while j < n and cum_pnl[j] < peak[i]:
                if cum_pnl[j] < cum_pnl[trough]:
                    trough = j
                j += 1
            episodes.append((peak[i] - cum_pnl[trough], ts(t[i]), ts(t[trough]), peak[i]))
            i = j
        else:
            i += 1
    episodes.sort(reverse=True)
    return episodes[:top]


def main():
    snap = json.loads(SNAP.read_text())
    print(f"# snapshot collected: {snap['collected_utc']}\n")

    v = snap["hlp_vaultDetails"]
    pf = v["portfolio"]
    print("=== HLP vault ===")
    print(f"name: {v['name']}  apr: {float(v.get('apr', 0))*100:.1f}%")
    print(f"maxWithdrawable: ${float(v.get('maxWithdrawable', 0))/1e6:,.1f}M  "
          f"maxDistributable: ${float(v.get('maxDistributable', 0))/1e6:,.1f}M")

    # equity curve
    av = window(pf, "allTime").get("accountValueHistory", [])
    if av:
        eq = np.array([float(a[1]) for a in av]); te = np.array([a[0] for a in av], "int64")
        print(f"equity: inception {ts(te[0])} -> {ts(te[-1])}  "
              f"current ${eq[-1]/1e6:,.1f}M  peak ${eq.max()/1e6:,.1f}M")

    # cumulative PnL (allTime, ~weekly)
    t, cum = pnl_series(pf, "allTime")
    print(f"\n=== HLP cumulative PnL (allTime, {len(cum)} pts ~weekly) ===")
    print(f"span {ts(t[0])} -> {ts(t[-1])}   total PnL ${cum[-1]/1e6:,.1f}M")
    d = np.diff(cum)   # per-interval PnL
    print(f"per-interval PnL (n={len(d)}): mean ${d.mean()/1e6:.2f}M  std ${d.std()/1e6:.2f}M")
    print(f"  worst interval ${d.min()/1e6:,.2f}M ({ts(t[np.argmin(d)])})   "
          f"best ${d.max()/1e6:,.2f}M ({ts(t[np.argmax(d)])})")
    sk = float(((d - d.mean())**3).mean() / (d.std()**3 + 1e-12))
    # skew is dominated by a single windfall interval; report it with that interval removed
    j = int(np.argmax(d)); mask = np.ones(len(d), bool); mask[j] = False
    d2 = d[mask]; sk2 = float(((d2 - d2.mean())**3).mean() / (d2.std()**3 + 1e-12))
    print(f"  skew {sk:+.2f} (n={len(d)}); without the single max interval {sk2:+.2f}  "
          f"-> the positive skew is essentially one windfall, not a stable property")
    print("  NOTE: ~14-day resolution over full history smooths intra-event moves (e.g. JELLY);")
    print("  interval nets are NOT event losses (see report).")
    print("  worst 5 drawdowns of the PnL curve (peak-to-trough, how much HLP gave back):")
    for mag, d0, dt, pk in drawdowns(t, cum):
        print(f"    -${mag/1e6:6.1f}M   {d0} -> {dt}   (from PnL peak ${pk/1e6:,.1f}M, "
              f"{mag/ (pk+1e-9)*100:4.1f}% of peak PnL)")

    # finer recent window
    tm, cm = pnl_series(pf, "month")
    if cm is not None and len(cm) > 2:
        dm = np.diff(cm)
        print(f"\n=== recent month ({len(cm)} pts, finer) ===")
        print(f"  worst interval ${dm.min()/1e6:,.2f}M ({ts(tm[np.argmin(dm)])})   "
              f"net month ${ (cm[-1]-cm[0])/1e6:,.1f}M")

    # leverage caps across universe
    uni = snap["meta"]["universe"]
    caps = {}
    iso = 0
    for a in uni:
        caps[a.get("maxLeverage")] = caps.get(a.get("maxLeverage"), 0) + 1
        iso += 1 if a.get("onlyIsolated") else 0
    print(f"\n=== leverage caps across {len(uni)} perps ===")
    for k in sorted(caps, key=lambda x: (x is None, x)):
        print(f"  {k}x: {caps[k]} assets")
    print(f"  onlyIsolated: {iso}")

    # open interest (notional) top 10
    mc = snap["metaAndAssetCtxs"]
    names = [a["name"] for a in mc[0]["universe"]]
    ctxs = mc[1]
    oi = []
    for i, c in enumerate(ctxs):
        try:
            notional = float(c["openInterest"]) * float(c["markPx"])
            oi.append((notional, names[i]))
        except Exception:
            pass
    oi.sort(reverse=True)
    tot = sum(x[0] for x in oi)
    print(f"\n=== open interest (notional), total ${tot/1e6:,.0f}M, top 10 ===")
    for notional, nm in oi[:10]:
        print(f"  {nm:<8} ${notional/1e6:,.1f}M  ({notional/tot*100:4.1f}% of OI)")


if __name__ == "__main__":
    main()
