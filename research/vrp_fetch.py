"""Fetch Deribit DVOL daily (public API) -> data/mech/dvol_{btc,eth}.parquet. Pages backward via continuation."""
import time, sys, json, urllib.request
import pandas as pd
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
URL = "https://www.deribit.com/api/v2/public/get_volatility_index_data?currency=%s&start_timestamp=%d&end_timestamp=%d&resolution=86400"

def fetch(cur, start="2021-03-01"):
    s = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
    e = int(pd.Timestamp.now(tz="UTC").timestamp() * 1000)
    rows = []; ncall = 0
    while True:
        with urllib.request.urlopen(urllib.request.Request(URL % (cur, s, e), headers={"User-Agent": "vrp-study"}), timeout=60) as r:
            res = json.load(r)["result"]
        ncall += 1
        rows += res["data"]
        cont = res.get("continuation")
        print(cur, "call", ncall, "got", len(res["data"]), "cont", cont, flush=True)
        if not cont or not res["data"] or cont <= s: break
        e = int(cont); time.sleep(0.2)
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close"]).drop_duplicates("ts").sort_values("ts")
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df.reset_index(drop=True)

if __name__ == "__main__":
    for cur in ("BTC", "ETH"):
        df = fetch(cur); df.to_parquet(ROOT / f"data/mech/dvol_{cur.lower()}.parquet")
        print(cur, len(df), df.ts.min(), df.ts.max(), df.close.min(), df.close.max())
