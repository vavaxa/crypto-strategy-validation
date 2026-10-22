#!/usr/bin/env python3
"""Сбор SPOT-свечей (1d, 1h) Binance и Bybit для тех же символов, что в perp-исследовании (basis = perp/spot - 1).

Источники бесплатные, без ключей: Binance api.binance.com/api/v3/klines (+ data.binance.vision spot-архив для
делистнутых пар), Bybit v5 market/kline category=spot.
Шаги: discover -> klines_d -> klines_h -> build.   Запуск: .venv/bin/python research/spot_collect.py <шаг> [--force]
Шарды: data/mech/raw/spot_<exch>/{1d,1h}/<perp_symbol>.parquet (пропускаются, если есть; --force - перекачать).
Колонки как в mech klines: symbol (= PERP-символ, ключ для join), ts (UTC), o,h,l,c, volume, quote_volume.
spot_symbol / scale хранятся в data/mech/spot_map.json; scale=1000 для 1000XUSDT-перпов: perp_price/1000 ~ spot (basis
считать как perp/(spot*scale) - 1). Пробелы (нет споту) НЕ угадываются - только явное соответствие base (и 1000X->X).
Только сбор данных; торговой логики нет.
"""
from __future__ import annotations

import io
import json
import re
import sys
import time
import zipfile
from pathlib import Path

import pandas as pd
import requests

ROOT = Path("/home/hermes/crypto-bot")
MECH = ROOT / "data" / "mech"
RAW = MECH / "raw"
BAPI = "https://api.binance.com"
BYBIT = "https://api.bybit.com"
VISION = "https://data.binance.vision/"
S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
FORCE = "--force" in sys.argv
GAP = {"binance": 0.2, "bybit": 0.15}
S = requests.Session()
S.headers["User-Agent"] = "spot-collect/0.1"
_last = {"binance": 0.0, "bybit": 0.0}
COLS = ["symbol", "ts", "o", "h", "l", "c", "volume", "quote_volume"]


def now_ms():
    return int(time.time() * 1000)


def get(url, params=None, ex="binance", tries=6, raw=False):
    for a in range(tries):
        d = _last[ex] + GAP[ex] - time.time()
        if d > 0:
            time.sleep(d)
        _last[ex] = time.time()
        try:
            r = S.get(url, params=params, timeout=40)
        except requests.RequestException:
            time.sleep(2 * (a + 1))
            continue
        if r.status_code in (429, 418):
            time.sleep(float(r.headers.get("Retry-After", 15 * (a + 1))))
            continue
        if r.status_code == 404 and raw:
            return None
        if r.status_code >= 500:
            time.sleep(3 * (a + 1))
            continue
        w = r.headers.get("x-mbx-used-weight-1m")
        if w and int(w) > 4800:          # лимит 6000/мин
            time.sleep(35)
        if raw:
            return r
        j = r.json()
        if ex == "bybit" and j.get("retCode") == 10006:   # rate limit
            time.sleep(5 * (a + 1))
            continue
        return j
    raise RuntimeError(f"GET failed {url} {params}")


def shard(ex, itv, sym) -> Path:
    p = RAW / f"spot_{ex}" / itv
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{sym}.parquet"


def save(df, path):
    df.to_parquet(path, index=False, compression="zstd")


def todt(ms):
    return pd.to_datetime(ms, unit="ms", utc=True)


def perp_syms():
    return json.loads((MECH / "selected.json").read_text())["symbols"]


def spot_name(perp):
    """1000FLOKIUSDT -> FLOKIUSDT; остальное - как есть."""
    m = re.match(r"^1000(.+USDT)$", perp)
    return (m.group(1), 1000) if m else (perp, 1)


def s3_keys(prefix):
    out, tok = [], None
    while True:
        p = {"prefix": prefix, "max-keys": 1000, "list-type": 2}
        if tok:
            p["continuation-token"] = tok
        t = get(S3, p, raw=True).text
        out += re.findall(r"<Key>(.*?)</Key>", t)
        m = re.search(r"<NextContinuationToken>(.*?)</NextContinuationToken>", t)
        if not m:
            return out
        tok = m.group(1)


def step_discover():
    bi = {s["symbol"]: s["status"] for s in get(f"{BAPI}/api/v3/exchangeInfo")["symbols"]}
    by = {i["symbol"]: i["status"] for i in get(f"{BYBIT}/v5/market/instruments-info", dict(category="spot", limit=1000), ex="bybit")["result"]["list"]}
    m = {}
    for p in perp_syms():
        sp, sc = spot_name(p)
        rec = dict(spot_symbol=sp, scale=sc, binance=bi.get(sp), bybit=by.get(sp), binance_archive=False)
        if sp not in bi:
            rec["binance_archive"] = bool(s3_keys(f"data/spot/monthly/klines/{sp}/1d/"))
        m[p] = rec
        print(p, rec, flush=True)
    (MECH / "spot_map.json").write_text(json.dumps(m, indent=1))
    nb = [p for p, r in m.items() if not (r["binance"] or r["binance_archive"])]
    ny = [p for p, r in m.items() if not r["bybit"]]
    print("NO binance spot:", nb)
    print("NO bybit spot:", ny)


def frame(rows, qv_idx):
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=COLS)
    df[0] = df[0].astype("int64")
    df[0] = df[0].where(df[0] < 10**14, df[0] // 1000)   # spot-архив с 2025: микросекунды
    out = pd.DataFrame(dict(ts=todt(df[0].astype("int64")), o=df[1], h=df[2], l=df[3], c=df[4], volume=df[5],
                            quote_volume=df[qv_idx] if qv_idx is not None else float("nan")))
    for c in ["o", "h", "l", "c", "volume", "quote_volume"]:
        out[c] = pd.to_numeric(out[c])
    return out.drop_duplicates("ts").sort_values("ts")


def binance_rest(sp, itv):
    rows, cur = [], 0
    while True:
        d = get(f"{BAPI}/api/v3/klines", dict(symbol=sp, interval=itv, startTime=cur, limit=1000))
        if not isinstance(d, list) or not d:
            break
        rows += [x[:8] for x in d]
        nxt = d[-1][0] + 1
        if len(d) < 1000 or nxt <= cur:
            break
        cur = nxt
    return frame(rows, 7)


def binance_vision(sp, itv):
    rows = []
    for k in s3_keys(f"data/spot/monthly/klines/{sp}/{itv}/"):
        if not k.endswith(".zip"):
            continue
        r = get(VISION + k, raw=True)
        z = zipfile.ZipFile(io.BytesIO(r.content))
        df = pd.read_csv(io.BytesIO(z.read(z.namelist()[0])), header=None)
        rows += df.iloc[:, :8].values.tolist()
    df = frame(rows, 7)
    return df


def bybit_rest(sp, itv):
    rows, end = [], now_ms()
    while True:
        j = get(f"{BYBIT}/v5/market/kline", dict(category="spot", symbol=sp, interval=itv, end=end, limit=1000), ex="bybit")
        lst = j.get("result", {}).get("list", [])
        if not lst:
            break
        rows += [[int(x[0])] + x[1:7] for x in lst]
        oldest = min(int(x[0]) for x in lst)
        if len(lst) < 1000 or oldest >= end:
            break
        end = oldest - 1
    return frame(rows, 6)


def run(itv_tag):
    bi_itv, by_itv = ("1d", "D") if itv_tag == "1d" else ("1h", "60")
    m = json.loads((MECH / "spot_map.json").read_text())
    for p, r in m.items():
        sp = r["spot_symbol"]
        for ex in ("binance", "bybit"):
            if not (r[ex] or (ex == "binance" and r["binance_archive"])):
                continue
            path = shard(ex, itv_tag, p)
            if path.exists() and not FORCE:
                continue
            if ex == "binance":
                df = binance_rest(sp, bi_itv) if r["binance"] else binance_vision(sp, bi_itv)
            else:
                df = bybit_rest(sp, by_itv)
            if len(df):
                df.insert(0, "symbol", p)
            save(df if len(df) else pd.DataFrame(columns=COLS), path)
            print(itv_tag, ex, p, len(df), flush=True)


def step_klines_d():
    run("1d")


def step_klines_h():
    run("1h")


def step_build():
    for ex in ("binance", "bybit"):
        for itv in ("1d", "1h"):
            fs = sorted((RAW / f"spot_{ex}" / itv).glob("*.parquet")) if (RAW / f"spot_{ex}" / itv).exists() else []
            parts = [d for d in (pd.read_parquet(f) for f in fs) if len(d)]
            if not parts:
                continue
            df = pd.concat(parts, ignore_index=True)[COLS]
            out = MECH / f"spot_klines_{itv}_{ex}.parquet"
            save(df, out)
            print(out.name, len(df), df.symbol.nunique(), df.ts.min(), df.ts.max())


if __name__ == "__main__":
    step = next((a for a in sys.argv[1:] if not a.startswith("--")), "")
    {"discover": step_discover, "klines_d": step_klines_d, "klines_h": step_klines_h, "build": step_build}[step]()
