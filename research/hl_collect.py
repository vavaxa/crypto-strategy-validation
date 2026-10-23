"""Hyperliquid public-API collector for the HLP backstop risk study.

Pulls, from the keyless public `info` endpoint (https://api.hyperliquid.xyz/info):
  * per-asset leverage caps / isolation flags            (type="meta")
  * per-asset open interest / funding / mark & oracle px (type="metaAndAssetCtxs")
  * the HLP vault's equity & cumulative-PnL history       (type="vaultDetails")
  * the HLP vault's live perp account and spot balances   (type="clearinghouseState",
    type="spotClearinghouseState") -- the authoritative cross-check that the vault's perp slot
    equals its perp account, and that its spot balances are empty.

Everything is point-in-time as served by the API; we store the raw payloads under
``data/hl/`` (git-ignored) so the downstream analysis is reproducible from a snapshot.

Note on granularity (documented honestly, not worked around): vaultDetails exposes only fixed windows
(day/week/month/allTime). The all-history curve is ~14-day, so daily tail resolution for older incidents
is not available from this endpoint -- the analysis states this limit rather than inventing precision.
"""
from __future__ import annotations
import json, time, urllib.request
from pathlib import Path

API = "https://api.hyperliquid.xyz/info"
HLP_VAULT = "0xdfc24b077bc1425ad1dea75bcb6f8158e10df303"  # Hyperliquidity Provider (HLP)
OUT = Path(__file__).resolve().parents[1] / "data" / "hl"


def info(payload: dict, retries: int = 3) -> dict | list:
    """POST a single `info` query; small polite retry/backoff."""
    body = json.dumps(payload).encode()
    for attempt in range(retries):
        try:
            req = urllib.request.Request(API, data=body,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(1.5 * (attempt + 1))


def collect() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())

    meta = info({"type": "meta"})
    meta_ctx = info({"type": "metaAndAssetCtxs"})
    vault = info({"type": "vaultDetails", "vaultAddress": HLP_VAULT})
    clearinghouse = info({"type": "clearinghouseState", "user": HLP_VAULT})
    spot = info({"type": "spotClearinghouseState", "user": HLP_VAULT})

    snapshot = {"collected_utc": stamp, "meta": meta, "metaAndAssetCtxs": meta_ctx,
                "hlp_vaultDetails": vault, "hlp_clearinghouseState": clearinghouse,
                "hlp_spotClearinghouseState": spot}
    raw_path = OUT / f"hl_snapshot_{stamp}.json"
    raw_path.write_text(json.dumps(snapshot))
    (OUT / "hl_snapshot_latest.json").write_text(json.dumps(snapshot))
    print(f"saved {raw_path}  ({raw_path.stat().st_size/1e6:.2f} MB)")
    return snapshot


if __name__ == "__main__":
    collect()
