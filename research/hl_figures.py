"""Render the HLP equity-vs-cumulative-PnL chart as a dependency-free SVG.

The gap between the two lines is net depositor capital; shading it makes the central point
of Finding 3 visual: the 2025-09 -> now contraction is depositors leaving (the gap collapsing),
not trading losses (cumulative PnL keeps rising). Reads data/hl/hl_snapshot_latest.json,
writes reports/hl_equity_vs_pnl.svg. Pure stdlib.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAP = ROOT / "data" / "hl" / "hl_snapshot_latest.json"
OUT = ROOT / "reports" / "hl_equity_vs_pnl.svg"

W, H = 900, 440
ML, MR, MT, MB = 70, 20, 54, 48           # margins
PW, PH = W - ML - MR, H - MT - MB


def main():
    snap = json.loads(SNAP.read_text())
    d = {n: v for n, v in snap["hlp_vaultDetails"]["portfolio"]}["allTime"]
    t = [x[0] for x in d["accountValueHistory"]]
    eq = [float(x[1]) / 1e6 for x in d["accountValueHistory"]]
    pnl = [float(x[1]) / 1e6 for x in d["pnlHistory"]]
    t0, t1 = t[0], t[-1]
    ymax = max(max(eq), max(pnl)) * 1.08

    def X(ms): return ML + (ms - t0) / (t1 - t0) * PW
    def Y(val): return MT + (1 - val / ymax) * PH

    def pts(ys): return " ".join(f"{X(t[i]):.1f},{Y(ys[i]):.1f}" for i in range(len(ys)))

    # shaded gap (net deposits) = polygon eq-line over pnl-line
    gap = ([f"{X(t[i]):.1f},{Y(eq[i]):.1f}" for i in range(len(eq))] +
           [f"{X(t[i]):.1f},{Y(pnl[i]):.1f}" for i in range(len(pnl) - 1, -1, -1)])

    def year_ticks():
        out = []
        for yr in range(2023, 2027):
            ms = int(datetime(yr, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
            if t0 <= ms <= t1:
                out.append((X(ms), yr))
        return out

    def ylab():
        out = []
        step = 100
        y = 0
        while y <= ymax:
            out.append((Y(y), y)); y += step
        return out

    peak_i = eq.index(max(eq))
    svg = []
    svg.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
               f'font-family="system-ui,Segoe UI,Helvetica,Arial,sans-serif">')
    svg.append(f'<rect width="{W}" height="{H}" fill="#ffffff"/>')
    svg.append(f'<text x="{ML}" y="26" font-size="16" font-weight="700" fill="#111">'
               'HLP: equity vs cumulative PnL — the 2025-09 contraction is withdrawals, not losses</text>')
    svg.append(f'<text x="{ML}" y="44" font-size="12" fill="#555">'
               'shaded = net depositor capital (equity − cumulative PnL)</text>')
    # grid + y labels
    for yy, val in ylab():
        svg.append(f'<line x1="{ML}" y1="{yy:.1f}" x2="{W-MR}" y2="{yy:.1f}" stroke="#eee"/>')
        svg.append(f'<text x="{ML-8}" y="{yy+4:.1f}" font-size="11" fill="#888" text-anchor="end">${val}M</text>')
    # x ticks
    for xx, yr in year_ticks():
        svg.append(f'<line x1="{xx:.1f}" y1="{MT}" x2="{xx:.1f}" y2="{H-MB}" stroke="#f3f3f3"/>')
        svg.append(f'<text x="{xx:.1f}" y="{H-MB+18}" font-size="11" fill="#888" text-anchor="middle">{yr}</text>')
    # gap fill
    svg.append(f'<polygon points="{" ".join(gap)}" fill="#3b82f6" fill-opacity="0.10"/>')
    # lines
    svg.append(f'<polyline points="{pts(pnl)}" fill="none" stroke="#16a34a" stroke-width="2"/>')
    svg.append(f'<polyline points="{pts(eq)}" fill="none" stroke="#2563eb" stroke-width="2"/>')
    # peak marker
    svg.append(f'<circle cx="{X(t[peak_i]):.1f}" cy="{Y(eq[peak_i]):.1f}" r="3.5" fill="#2563eb"/>')
    svg.append(f'<text x="{X(t[peak_i]):.1f}" y="{Y(eq[peak_i])-8:.1f}" font-size="11" '
               f'fill="#2563eb" text-anchor="middle">peak ${eq[peak_i]:.0f}M</text>')
    # legend
    lx, ly = W - MR - 200, MT + 6
    svg.append(f'<rect x="{lx}" y="{ly}" width="186" height="46" fill="#fff" stroke="#ddd" rx="6"/>')
    svg.append(f'<line x1="{lx+12}" y1="{ly+16}" x2="{lx+34}" y2="{ly+16}" stroke="#2563eb" stroke-width="3"/>')
    svg.append(f'<text x="{lx+40}" y="{ly+20}" font-size="12" fill="#333">equity (depositor capital)</text>')
    svg.append(f'<line x1="{lx+12}" y1="{ly+34}" x2="{lx+34}" y2="{ly+34}" stroke="#16a34a" stroke-width="3"/>')
    svg.append(f'<text x="{lx+40}" y="{ly+38}" font-size="12" fill="#333">cumulative PnL</text>')
    svg.append('</svg>')
    OUT.write_text("\n".join(svg))
    print(f"wrote {OUT}  ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
