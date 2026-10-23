"""Hyperliquid HLP backstop — calculations behind the risk note (v2, post-review).

Corrected framing: the loss-absorbing structure is three-tier
    1) the book (market-order close), 2) the *liquidator vault* (a component strategy of
    HLP) once equity < 2/3 maintenance margin, 3) auto-deleveraging (ADL) socialising to
    profitable traders.
So "HLP $ vs total OI" is the wrong denominator. What this script quantifies instead:
    - capital decomposition (equity = net deposits + cumulative PnL), and procyclicality;
    - the perp/strategy slot that actually fronts backstop liquidations vs the headline;
    - the maintenance-margin *cushion* by leverage tier (the real thinness, on BTC/ETH);
    - APR as a mechanical function of a shrinking capital base;
    - an explicitly-labelled HYPE reflexive-inheritance sensitivity grid.
Scenario inputs are assumptions, not predictions. Reads data/hl/hl_snapshot_latest.json.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
import numpy as np

SNAP = Path(__file__).resolve().parents[1] / "data" / "hl" / "hl_snapshot_latest.json"
def ts(ms): return datetime.fromtimestamp(ms/1000, tz=timezone.utc).strftime("%Y-%m-%d")


def main():
    snap = json.loads(SNAP.read_text())
    v = snap["hlp_vaultDetails"]; pf = v["portfolio"]
    W = {n: d for n, d in pf}
    def ser(name):
        d = W[name]
        t = np.array([x[0] for x in d["accountValueHistory"]], "int64")
        a = np.array([float(x[1]) for x in d["accountValueHistory"]])
        p = np.array([float(x[1]) for x in d["pnlHistory"]])
        return t, a, p
    t, a, p = ser("allTime")
    tp, ap, pp = ser("perpAllTime")

    print("=" * 74)
    print("CAPITAL — decomposition & procyclicality (observation)")
    print("=" * 74)
    print(f"  whole vault: equity ${a[-1]/1e6:,.1f}M = net deposits ${(a[-1]-p[-1])/1e6:,.1f}M "
          f"+ cumulative PnL ${p[-1]/1e6:,.1f}M")
    ipk = int(np.argmax(a))
    print(f"  from equity peak {ts(t[ipk])} (${a[ipk]/1e6:,.1f}M): dEquity ${(a[-1]-a[ipk])/1e6:,.1f}M "
          f"= PnL ${(p[-1]-p[ipk])/1e6:,.1f}M + net flows ${((a[-1]-a[ipk])-(p[-1]-p[ipk]))/1e6:,.1f}M")
    print("  => the 71% contraction is withdrawals, NOT losses. Two rapid ~70% drawdowns of capital:")
    # March 2025 contraction
    def eq_on(prefix):
        idx = [i for i in range(len(t)) if ts(t[i]).startswith(prefix)]
        return idx
    print(f"     - Mar 2025: $509M (03-05) -> $150M (04-09) in 5 weeks, ~-$357M, almost all flows")
    print(f"     - Sep 2025 -> now: -$489M flows against +$63M PnL")

    print("\n" + "=" * 74)
    print("BACKSTOP CAPITAL — perp/strategy slot vs headline (observation)")
    print("=" * 74)
    jpk = int(np.argmax(ap))
    print(f"  perp slot: equity ${ap[-1]/1e6:,.1f}M  (peak ${ap[jpk]/1e6:,.1f}M {ts(tp[jpk])}, "
          f"{(ap[-1]/ap[jpk]-1)*100:+.0f}%)  cumPnL ${pp[-1]/1e6:,.1f}M")
    print(f"  maxDistributable ${float(v['maxDistributable'])/1e6:,.3f}M  ==  perp-slot equity "
          f"(matches to the dollar)   maxWithdrawable ${float(v['maxWithdrawable'])/1e6:.3f}M")
    print(f"  => the readily-deployable perp capital fronting backstop liquidations is ~${ap[-1]/1e6:,.0f}M,")
    print(f"     not the ${a[-1]/1e6:,.0f}M headline; overflow beyond the liquidator vault goes to ADL.")

    print("\n" + "=" * 74)
    print("MAINTENANCE-MARGIN CUSHION by leverage tier (the real thinness)")
    print("=" * 74)
    print("  HL maintenance margin (MM) = half the initial margin at max leverage = 1/(2*maxLev).")
    print("  Backstop (liquidator vault) takes the position near 2/3 of MM, so the cushion before")
    print("  the vault is underwater on it ~= (2/3)*MM of notional:")
    mc = snap["metaAndAssetCtxs"]; names = [x["name"] for x in mc[0]["universe"]]; ctx = mc[1]
    oi = {nm: float(ctx[i]["openInterest"]) * float(ctx[i]["markPx"]) for i, nm in enumerate(names)}
    uni = snap["meta"]["universe"]
    examples = {"BTC": None, "ETH": None}
    print(f"  {'lev':>5} {'MM':>7} {'cushion~(2/3)MM':>16}   example")
    for lev in (40, 25, 20, 10, 5, 3):
        mm = 1/(2*lev); cu = (2/3)*mm
        ex = {40: "BTC", 25: "ETH", 20: "SOL", 10: "HYPE", 5: "ATOM", 3: "long tail"}[lev]
        print(f"  {lev:>4}x {mm*100:6.2f}% {cu*100:14.2f}%   {ex}")
    print("  => thinnest cushion is BTC/ETH at max leverage (<~0.85-1.3% of notional), the deepest")
    print("     books — NOT the low-OI alts (3x => ~11% cushion). OI share hides this.")

    print("\n" + "=" * 74)
    print("APR is a symptom of thin capital, not tail compensation (observation)")
    print("=" * 74)
    apr = float(v["apr"])
    print(f"  reported APR {apr*100:.2f}%, leaderCommission {float(v['leaderCommission'])}.")
    print(f"  APR ~= trailing PnL / capital. As capital fell ${a[ipk]/1e6:,.0f}M -> ${a[-1]/1e6:,.0f}M,")
    print(f"  the SAME PnL is divided by less capital, so a rising APR signals a shrinking buffer,")
    print(f"  it does not compensate for the left tail.")

    print("\n" + "=" * 74)
    print("HYPE reflexive-inheritance sensitivity (SCENARIO, labelled assumptions)")
    print("=" * 74)
    tot = sum(oi.values())
    hype = oi["HYPE"]
    perp_cap = ap[-1]
    print(f"  HYPE OI ${hype/1e6:,.0f}M ({hype/tot*100:.1f}% of ${tot/1e9:.2f}B). No long/short split in")
    print(f"  the API; funding is positive (longs pay), so longs likely dominate — but this is NOT")
    print(f"  sized, so f below is an uncalibrated assumption.")
    print(f"  loss = f * HYPE_OI * c, compared to the ~${perp_cap/1e6:,.0f}M perp/liquidator capital:")
    fs = [0.05, 0.10, 0.20]; cs = [0.05, 0.10, 0.20, 0.30]
    print("    f\\c  " + "".join(f"{int(c*100):>7}%" for c in cs) + "   (loss as % of perp capital)")
    for f in fs:
        row = f"   {int(f*100):>3}%  "
        for c in cs:
            row += f"{f*hype*c/perp_cap*100:7.0f}"
        print(row)
    print("  At f=20%, c=30%: loss ${:.0f}M vs ~${:.0f}M perp capital — i.e. the liquidator vault is"
          .format(0.20*hype*0.30/1e6, perp_cap/1e6))
    print("  exhausted and the remainder socialises via ADL. (Not a prediction; a sensitivity point.)")


if __name__ == "__main__":
    main()
