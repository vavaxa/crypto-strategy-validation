"""Basis-carry net return vs the square-root-impact coefficient k (dependency-free SVG).

The whole verdict is linear in k: net(k) = (gross - fees) - (impact_at_k0.5 / 0.5) * k.
From reports/basis_carry.md (impact_k=0.5, $1M book): gross-before-costs 1280, fees -671,
impact(both legs) -9697, NET -9091 bps/yr. So intercept = -9091 + 9697 = 606, slope = -19394,
zero crossing at k = 606/19394 = 0.0313 (the report's breakeven 0.031). The sensitivity grid
that was actually run spanned 0.125-2 -- entirely to the right of the crossing. This chart makes
the point: the published FAIL sat on an uncalibrated parameter; the realistic band straddles zero.
"""
from __future__ import annotations
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "reports" / "impact_sensitivity_basis.svg"
INTERCEPT, SLOPE = 606.0, -19394.0        # bps/yr ; from basis_carry.md
def net(k): return INTERCEPT + SLOPE * k

W, H = 860, 430
ML, MR, MT, MB = 76, 20, 58, 54
PW, PH = W - ML - MR, H - MT - MB
KMAX = 0.10
YMIN, YMAX = -1400.0, 800.0               # bps/yr view (stub k=0.5 is far off-chart, annotated)
BAND = (0.015, 0.06)                      # realistic per-symbol k = Y*sigma band
BREAK = 0.0313

def X(k): return ML + k / KMAX * PW
def Y(v): return MT + (1 - (v - YMIN) / (YMAX - YMIN)) * PH

s = []
s.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
         f'font-family="system-ui,Segoe UI,Helvetica,Arial,sans-serif">')
s.append(f'<rect width="{W}" height="{H}" fill="#ffffff"/>')
s.append(f'<text x="{ML}" y="26" font-size="15" font-weight="700" fill="#111">'
         'Delta-neutral basis carry: net return vs impact coefficient k</text>')
s.append(f'<text x="{ML}" y="44" font-size="12" fill="#555">'
         'the published FAIL used k=0.5 (a ~20-30x-overstated stub); the deciding region was never swept</text>')
# realistic band
s.append(f'<rect x="{X(BAND[0]):.1f}" y="{MT}" width="{X(BAND[1])-X(BAND[0]):.1f}" height="{PH}" '
         'fill="#f59e0b" fill-opacity="0.12"/>')
s.append(f'<text x="{(X(BAND[0])+X(BAND[1]))/2:.1f}" y="{MT+14}" font-size="11" fill="#b45309" '
         'text-anchor="middle">realistic k = Y·σ (~0.015–0.06)</text>')
# zero line
s.append(f'<line x1="{ML}" y1="{Y(0):.1f}" x2="{W-MR}" y2="{Y(0):.1f}" stroke="#bbb" stroke-dasharray="4 3"/>')
s.append(f'<text x="{W-MR}" y="{Y(0)-5:.1f}" font-size="11" fill="#999" text-anchor="end">net = 0</text>')
# y ticks
for v in (-1200,-800,-400,0,400,800):
    s.append(f'<line x1="{ML}" y1="{Y(v):.1f}" x2="{ML-4}" y2="{Y(v):.1f}" stroke="#999"/>')
    s.append(f'<text x="{ML-8}" y="{Y(v)+4:.1f}" font-size="10" fill="#888" text-anchor="end">{v}</text>')
s.append(f'<text x="18" y="{MT+PH/2:.1f}" font-size="11" fill="#666" '
         f'transform="rotate(-90 18 {MT+PH/2:.1f})" text-anchor="middle">net bps/yr</text>')
# x ticks
for k in (0,0.02,0.04,0.06,0.08,0.10):
    s.append(f'<line x1="{X(k):.1f}" y1="{H-MB}" x2="{X(k):.1f}" y2="{H-MB+4}" stroke="#999"/>')
    s.append(f'<text x="{X(k):.1f}" y="{H-MB+18}" font-size="10" fill="#888" text-anchor="middle">{k:g}</text>')
s.append(f'<text x="{ML+PW/2:.1f}" y="{H-14}" font-size="11" fill="#666" text-anchor="middle">impact coefficient k</text>')
# net(k) line (clipped to view)
x0,y0 = X(0), Y(min(max(net(0),YMIN),YMAX))
kx = (INTERCEPT-YMIN)/-SLOPE  # k where net hits YMIN
x1,y1 = X(min(kx,KMAX)), Y(net(min(kx,KMAX)))
s.append(f'<line x1="{x0:.1f}" y1="{y0:.1f}" x2="{x1:.1f}" y2="{y1:.1f}" stroke="#dc2626" stroke-width="2.5"/>')
# breakeven marker
s.append(f'<circle cx="{X(BREAK):.1f}" cy="{Y(0):.1f}" r="4" fill="#dc2626"/>')
s.append(f'<text x="{X(BREAK)+6:.1f}" y="{Y(0)-8:.1f}" font-size="11" fill="#dc2626">breakeven k ≈ 0.031</text>')
# stub annotation
s.append(f'<text x="{W-MR}" y="{MT+PH-8:.1f}" font-size="11" fill="#777" text-anchor="end">'
         'stub k=0.5 → net −9091 bps/yr (far below axis)</text>')
s.append('</svg>')
OUT.write_text("\n".join(s))
print(f"wrote {OUT} ({OUT.stat().st_size} bytes); net(0.02)={net(0.02):.0f}, breakeven k={INTERCEPT/-SLOPE:.4f}")
