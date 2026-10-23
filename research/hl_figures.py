"""Render the HLP equity / cumulative-PnL / net-deposits chart as a dependency-free SVG.

The point of Finding 2 is visual: equity (blue) fell from ~$604M to ~$177M, but cumulative PnL (green)
kept rising — the collapse is the net-deposits line (orange = equity - cumPnL) draining from its peak to
~$38.6M. The shaded gap is that same net-depositor capital. Reads data/hl/hl_snapshot_latest.json,
writes reports/hl_equity_vs_pnl.svg. Pure stdlib.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAP = ROOT / "data" / "hl" / "hl_snapshot_latest.json"
OUT = ROOT / "reports" / "hl_equity_vs_pnl.svg"

W, H = 920, 460
ML, MR, MT, MB = 74, 120, 56, 50          # wide right margin for end-labels
PW, PH = W - ML - MR, H - MT - MB


def main():
    snap = json.loads(SNAP.read_text())
    d = {n: v for n, v in snap["hlp_vaultDetails"]["portfolio"]}["allTime"]
    t = [x[0] for x in d["accountValueHistory"]]
    eq = [float(x[1]) / 1e6 for x in d["accountValueHistory"]]
    pnl = [float(x[1]) / 1e6 for x in d["pnlHistory"]]
    nd = [eq[i] - pnl[i] for i in range(len(eq))]          # net deposits
    t0, t1 = t[0], t[-1]
    ymax = max(max(eq), max(pnl), max(nd)) * 1.08

    def X(ms): return ML + (ms - t0) / (t1 - t0) * PW
    def Y(v): return MT + (1 - v / ymax) * PH
    def poly(ys): return " ".join(f"{X(t[i]):.1f},{Y(ys[i]):.1f}" for i in range(len(ys)))

    peak_i = eq.index(max(eq))
    mar = int(datetime(2025, 3, 5, tzinfo=timezone.utc).timestamp() * 1000)

    s = []
    s.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
             f'font-family="system-ui,Segoe UI,Helvetica,Arial,sans-serif">')
    s.append(f'<rect width="{W}" height="{H}" fill="#ffffff"/>')
    s.append(f'<text x="{ML}" y="26" font-size="15" font-weight="700" fill="#111">'
             'HLP: the 2025 contraction is withdrawals, not losses</text>')
    s.append(f'<text x="{ML}" y="44" font-size="12" fill="#555">'
             'net depositor capital (orange) = equity − cumulative PnL; falls via withdrawals, not losses</text>')
    # y grid + labels
    v = 0
    while v <= ymax:
        s.append(f'<line x1="{ML}" y1="{Y(v):.1f}" x2="{ML+PW}" y2="{Y(v):.1f}" stroke="#eee"/>')
        s.append(f'<text x="{ML-8}" y="{Y(v)+4:.1f}" font-size="10" fill="#888" text-anchor="end">{v:.0f}</text>')
        v += 100
    s.append(f'<text x="16" y="{MT+PH/2:.1f}" font-size="11" fill="#666" '
             f'transform="rotate(-90 16 {MT+PH/2:.1f})" text-anchor="middle">USD ($M)</text>')
    # x year ticks
    for yr in range(2023, 2027):
        ms = int(datetime(yr, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
        if t0 <= ms <= t1:
            s.append(f'<line x1="{X(ms):.1f}" y1="{MT}" x2="{X(ms):.1f}" y2="{H-MB}" stroke="#f4f4f4"/>')
            s.append(f'<text x="{X(ms):.1f}" y="{H-MB+18}" font-size="11" fill="#888" text-anchor="middle">{yr}</text>')
    # Mar-2025 marker
    if t0 <= mar <= t1:
        s.append(f'<line x1="{X(mar):.1f}" y1="{MT}" x2="{X(mar):.1f}" y2="{H-MB}" '
                 'stroke="#d97706" stroke-width="1.2" stroke-dasharray="5 3"/>')
        s.append(f'<text x="{X(mar)+5:.1f}" y="{MT+PH-6:.1f}" font-size="10.5" fill="#b45309">'
                 'Mar-2025: −$360M in 5 weeks, PnL flat</text>')
    # lines (no fill: orange net-deposits line is the single encoding)
    s.append(f'<polyline points="{poly(nd)}" fill="none" stroke="#ea580c" stroke-width="2"/>')
    s.append(f'<polyline points="{poly(pnl)}" fill="none" stroke="#16a34a" stroke-width="2"/>')
    s.append(f'<polyline points="{poly(eq)}" fill="none" stroke="#2563eb" stroke-width="2"/>')
    # peak marker
    s.append(f'<circle cx="{X(t[peak_i]):.1f}" cy="{Y(eq[peak_i]):.1f}" r="3.5" fill="#2563eb"/>')
    s.append(f'<text x="{X(t[peak_i]):.1f}" y="{Y(eq[peak_i])-8:.1f}" font-size="11" '
             f'fill="#2563eb" text-anchor="middle">sampled peak ${eq[peak_i]:.0f}M</text>')
    # end-value labels (right margin)
    ex = ML + PW + 6
    for val, col, lab in ((eq[-1], "#2563eb", "equity"), (pnl[-1], "#16a34a", "cum PnL"),
                          (nd[-1], "#ea580c", "net deposits")):
        s.append(f'<text x="{ex}" y="{Y(val)+4:.1f}" font-size="11" fill="{col}">${val:.0f}M {lab}</text>')
    s.append('</svg>')
    OUT.write_text("\n".join(s))
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes); end eq ${eq[-1]:.0f}M pnl ${pnl[-1]:.0f}M nd ${nd[-1]:.1f}M")


if __name__ == "__main__":
    main()
