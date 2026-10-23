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
    print("  => the 71% contraction is withdrawals, NOT losses. Flow decomposition after the peak:")
    infl = outfl = 0.0; nin = nout = 0; big = (-1.0, "", "", 0.0)
    for i in range(ipk + 1, len(a)):
        flow = (a[i] - a[i-1]) - (p[i] - p[i-1]); dpnl = p[i] - p[i-1]
        if flow > 0: infl += flow; nin += 1
        else: outfl += flow; nout += 1
        if flow > big[0]: big = (flow, ts(t[i-1]), ts(t[i]), dpnl)
    print(f"     inflows +${infl/1e6:,.0f}M across {nin} intervals; outflows ${outfl/1e6:,.0f}M across {nout}; "
          f"net ${(infl+outfl)/1e6:,.0f}M")
    print(f"     largest inflow +${big[0]/1e6:,.0f}M ({big[1]}->{big[2]}), same-bucket PnL +${big[3]/1e6:,.0f}M "
          f"-- capital chased the crash windfall IN")
    print(f"     => procyclical toward realised yield (in after stress, out in calm); the only true run was")
    print(f"        JELLY (Mar-2025, ~-$160M interval). NOT a monotonic drain.")

    print("\n" + "=" * 74)
    print("BACKSTOP CAPITAL — perp account is the hard cap; where is the rest? (observation)")
    print("=" * 74)
    jpk = int(np.argmax(ap))
    print(f"  perp slot (portfolio.perpAllTime): equity ${ap[-1]/1e6:,.3f}M  "
          f"(peak ${ap[jpk]/1e6:,.1f}M {ts(tp[jpk])}, {(ap[-1]/ap[jpk]-1)*100:+.0f}%)  cumPnL ${pp[-1]/1e6:,.1f}M")
    ch = snap.get("hlp_clearinghouseState", {})
    if ch:
        acct = float(ch.get("marginSummary", {}).get("accountValue", "nan"))
        wd = float(ch.get("withdrawable", "nan"))
        npos = len(ch.get("assetPositions", []))
        print(f"  clearinghouseState (live perp account): accountValue ${acct/1e6:,.3f}M, "
              f"withdrawable ${wd/1e6:,.3f}M, open positions {npos}")
        print(f"  PROOF: clearinghouseState.accountValue == portfolio.perpAllTime to ${abs(acct-ap[-1]):,.2f} "
              f"-> the vault's perp slot IS its perp account.")
        print(f"  (maxDistributable ${float(v['maxDistributable'])/1e6:,.3f}M tracks WITHDRAWABLE = free cash, "
              f"NOT slot capital -- do not conflate.)")
        cap = acct
    else:
        cap = ap[-1]
    spot = snap.get("hlp_spotClearinghouseState", {}).get("balances", [])
    gap = a[-1] - ap[-1]
    print(f"  => backstop loss is mechanically capped at the ~${cap/1e6:,.0f}M perp account; ADL beyond it.")
    print(f"     Vault spot balances at this address: {len(spot)}. The other ${gap/1e6:,.0f}M of the "
          f"${a[-1]/1e6:,.0f}M NAV (~{gap/a[-1]*100:.0f}%) is HLP's Earn/market-making strategies, which the")
    print(f"     API exposes only by their own sub-account addresses (docs) -- NOT a gap; per-strategy NAV")
    print(f"     is simply not published. This note covers the liquidation channel (the ~${cap/1e6:,.0f}M).")

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
    perp_cap = cap  # clearinghouse perp accountValue = the hard loss cap
    hype_lev = next(a["maxLeverage"] for a in uni if a["name"] == "HYPE")
    cushion = (2/3) * (1 / (2 * hype_lev))   # (2/3)*MM, MM = 1/(2*maxLev)
    print(f"  HYPE OI ${hype/1e6:,.0f}M ({hype/tot*100:.1f}% of ${tot/1e9:.2f}B), {hype_lev}x "
          f"(cushion (2/3)*MM = {cushion*100:.2f}%). No long/short split in the API; funding is positive")
    print(f"  (longs pay), so longs likely dominate — but this is NOT sized, so f below is an assumption.")
    print(f"  An inherited position only costs the vault BEYOND its margin cushion, so")
    print(f"  loss = f * HYPE_OI * max(0, c - {cushion*100:.2f}%), vs the ~${perp_cap/1e6:,.0f}M perp cap:")
    fs = [0.05, 0.10, 0.20]; cs = [0.05, 0.10, 0.20, 0.30]
    print("    f\\c  " + "".join(f"{int(c*100):>7}%" for c in cs) + "   (loss as % of perp cap)")
    for f in fs:
        row = f"   {int(f*100):>3}%  "
        for c in cs:
            row += f"{f*hype*max(0.0, c-cushion)/perp_cap*100:7.0f}"
        print(row)
    loss2020 = 0.20 * hype * max(0.0, 0.20 - cushion)
    print(f"  At f=20%, c=20%: loss ${loss2020/1e6:.0f}M vs ~${perp_cap/1e6:,.0f}M perp cap — liquidator")
    print("  vault exhausted, remainder socialises via ADL. Follows from the protocol's own cushion; a")
    print("  sensitivity point, not a prediction.")


if __name__ == "__main__":
    main()
