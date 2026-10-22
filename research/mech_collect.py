#!/usr/bin/env python3
"""Слой point-in-time данных для проверки механизма тренда/пробоя (ветка mech/data-layer).

Источники (все бесплатные, без ключей):
  * Binance USDⓈ-M REST (fapi.binance.com) - вселенная, свечи, funding, текущий OI;
  * Binance Vision архив (data.binance.vision) - ДЕЛИСТНУТЫЕ контракты, история OI (metrics, 5m с 2020-09);
  * Bybit v5 REST - свечи, funding, open interest (вторая площадка для репликации).
Все шаги резюмируемые: результат по символу лежит шардом data/mech/raw/<датасет>/<биржа>/<символ>.parquet,
существующий шард пропускается (--force - перекачать). Итоговые файлы собирает шаг `build`.

Шаги: universe -> klines_d -> select -> klines_h -> funding -> oi -> bybit -> borrow -> liqprobe -> build
Запуск: .venv/bin/python research/mech_collect.py <шаг> [--force]
Только сбор данных; торговой логики и ордеров здесь нет.
"""
from __future__ import annotations

import io
import json
import re
import sys
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path("/home/hermes/crypto-bot")
MECH = ROOT / "data" / "mech"
RAW = MECH / "raw"
MARKET = ROOT / "data" / "market"
FAPI = "https://fapi.binance.com"
BYBIT = "https://api.bybit.com"
VISION = "https://data.binance.vision/"
S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
FORCE = "--force" in sys.argv
N_TOP = 40          # топ текущих перпов по обороту
N_SETTLED = 20      # топ делистнутых по историческому обороту (против survivorship)
OI_FROM = pd.Timestamp("2020-09-01", tz="UTC")  # metrics в архиве начинаются здесь

S = requests.Session()
S.headers["User-Agent"] = "mech-collect/0.1"
_lock = threading.Lock()
_last = {"t": 0.0}


def now_ms() -> int:
    return int(time.time() * 1000)


def get(url, params=None, gap=0.15, tries=6, raw=False):
    """GET с троттлингом, бэкоффом на 429/418 и учётом веса Binance."""
    for a in range(tries):
        with _lock:
            d = _last["t"] + gap - time.time()
            if d > 0:
                time.sleep(d)
            _last["t"] = time.time()
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
        w = r.headers.get("X-MBX-USED-WEIGHT-1M")
        if w and int(w) > 1800:          # лимит 2400/мин - не подходим близко
            time.sleep(35)
        return r if raw else r.json()
    raise RuntimeError(f"GET failed {url} {params}")


def shard(ds, ex, sym) -> Path:
    p = RAW / ds / ex
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{sym}.parquet"


def save(df, path):
    df.to_parquet(path, index=False, compression="zstd")


def todt(ms):
    return pd.to_datetime(ms, unit="ms", utc=True)


# ---------- S3 листинг архива ----------
def s3_list(prefix, delim="/"):
    out, tok = [], None
    while True:
        p = {"prefix": prefix, "max-keys": 1000, "list-type": 2}
        if delim:
            p["delimiter"] = delim
        if tok:
            p["continuation-token"] = tok
        t = get(S3, p, raw=True).text
        out += re.findall(r"<Prefix>(.*?)</Prefix>", t) if delim else re.findall(r"<Key>(.*?)</Key>", t)
        m = re.search(r"<NextContinuationToken>(.*?)</NextContinuationToken>", t)
        if not m:
            return out
        tok = m.group(1)


def vision_zip(key):
    r = get(VISION + key, raw=True, gap=0.0)
    if r is None:
        return None
    z = zipfile.ZipFile(io.BytesIO(r.content))
    return z.read(z.namelist()[0])


KCOLS = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume", "trades",
         "taker_buy_volume", "taker_buy_quote_volume", "ignore"]


def kl_frame(rows) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=KCOLS[:len(rows[0])] if rows else KCOLS).drop(columns=["ignore", "close_time"], errors="ignore")
    for c in df.columns:
        df[c] = pd.to_numeric(df[c])
    df["ts"] = todt(df.pop("open_time"))
    return df.rename(columns={"open": "o", "high": "h", "low": "l", "close": "c"}).drop_duplicates("ts").sort_values("ts")


def vision_klines(sym, itv):
    """Месячные архивы свечей (для контрактов, которых уже нет в exchangeInfo)."""
    keys = [k for k in s3_list(f"data/futures/um/monthly/klines/{sym}/{itv}/", None) if k.endswith(".zip")]
    frames = []
    for k in keys:
        b = vision_zip(k)
        df = pd.read_csv(io.BytesIO(b), header=None)
        if not str(df.iloc[0, 0]).isdigit():
            df = df.iloc[1:]
        frames.append(df.iloc[:, :11].values.tolist())
    rows = [r for f in frames for r in f]
    return kl_frame(rows) if rows else pd.DataFrame()


def rest_klines(sym, itv, start_ms, end_ms):
    """Свечи Binance REST со страницами по 1500 (вес 10 за запрос)."""
    rows, cur = [], start_ms
    while cur < end_ms:
        d = get(f"{FAPI}/fapi/v1/klines", dict(symbol=sym, interval=itv, startTime=cur, limit=1500))
        if not isinstance(d, list) or not d:
            break
        rows += [x[:11] for x in d]
        nxt = d[-1][0] + 1
        if nxt <= cur or len(d) < 1500:
            break
        cur = nxt
    return kl_frame(rows) if rows else pd.DataFrame()


# ---------- шаги ----------
def step_universe():
    """Вселенная Binance: exchangeInfo (TRADING/SETTLING/...) + архив Vision (контракты, исчезнувшие из API)."""
    info = get(f"{FAPI}/fapi/v1/exchangeInfo")["symbols"]
    cur = pd.DataFrame([dict(symbol=s["symbol"], base=s["baseAsset"], quote=s["quoteAsset"],
                             contract_type=s["contractType"], status=s["status"],
                             onboard_ts=todt(s["onboardDate"]), delivery_ts=todt(s["deliveryDate"]),
                             in_exchangeinfo=True) for s in info])
    arch = {p.split("/")[-2] for p in s3_list("data/futures/um/monthly/klines/")}
    extra = sorted(arch - set(cur.symbol))
    ex = pd.DataFrame(dict(symbol=extra, status="DELISTED_ARCHIVE_ONLY", in_exchangeinfo=False))
    ex["quote"] = ex.symbol.str.extract(r"(USDT|BUSD|USDC)")[0]
    ex["contract_type"] = ex.symbol.map(lambda s: "DATED_OR_SETTLED" if ("_" in s or s.endswith("SETTLED"))
                                        else "PERPETUAL")
    u = pd.concat([cur, ex], ignore_index=True)
    u["in_archive"] = u.symbol.isin(arch)
    u["is_usdt_perp"] = (u.quote == "USDT") & (u.contract_type.isin(["PERPETUAL", "TRADIFI_PERPETUAL"]))
    save(u, MECH / "universe_binance.parquet")
    print(u.groupby(["status", "contract_type"]).size())
    # Bybit: только то, что отдаёт API (по умолчанию - Trading; закрытые/делистнутые не отдаются)
    rows, cur_c = [], ""
    for st in ("Trading", "Closed", "PreLaunch", "Settling"):
        cur_c = ""
        while True:
            d = get(f"{BYBIT}/v5/market/instruments-info", dict(category="linear", limit=1000, cursor=cur_c, status=st))
            rows += [dict(symbol=i["symbol"], contract_type=i["contractType"], status=i["status"], base=i["baseCoin"],
                          quote=i["quoteCoin"], launch_ts=todt(int(i["launchTime"])),
                          delivery_ts=todt(int(i["deliveryTime"])) if i["deliveryTime"] != "0" else pd.NaT)
                     for i in d["result"]["list"]]
            cur_c = d["result"].get("nextPageCursor", "")
            if not cur_c:
                break
    b = pd.DataFrame(rows).drop_duplicates("symbol")
    save(b, MECH / "universe_bybit.parquet")
    print(b.groupby(["status", "contract_type"]).size())


def usdt_perps():
    u = pd.read_parquet(MECH / "universe_binance.parquet")
    return u[(u.quote == "USDT") & (u.contract_type == "PERPETUAL")]  # TRADIFI (акции/сырьё) не берём


def step_klines_d():
    """Дневные свечи ВСЕХ USDT-перпов (включая SETTLING и архивные) - основа PIT-ранжирования по обороту."""
    u = usdt_perps()
    for i, r in enumerate(u.itertuples()):
        p = shard("klines_1d", "binance", r.symbol)
        if p.exists() and not FORCE:
            continue
        if r.in_exchangeinfo:
            df = rest_klines(r.symbol, "1d", int(r.onboard_ts.timestamp() * 1000) - 86400000, now_ms())
        else:
            df = vision_klines(r.symbol, "1d")
        if len(df):
            # после делистинга REST отдаёт плоские нулевые бары - режем по delivery_ts и нулевому обороту
            if r.status == "SETTLING" and pd.notna(r.delivery_ts):
                df = df[df.ts <= r.delivery_ts]
            df = df[~((df.volume == 0) & (df.o == df.c) & (df.h == df.l))] if r.status != "TRADING" else df
            save(df, p)
        else:
            save(pd.DataFrame(columns=["ts"]), p)
        if i % 50 == 0:
            print("klines_d", i, len(u), r.symbol, flush=True)


def step_select():
    """Выбор набора для часовых/funding/OI: топ-40 по обороту + data/market + топ делистнутых по ИСТОРИЧЕСКОМУ обороту."""
    u = usdt_perps()
    t = pd.DataFrame(get(f"{FAPI}/fapi/v1/ticker/24hr"))
    t["q"] = t.quoteVolume.astype(float)
    live = u[(u.status == "TRADING") & (u.contract_type == "PERPETUAL")].merge(t[["symbol", "q"]], on="symbol")
    top = live.sort_values("q", ascending=False).head(N_TOP).symbol.tolist()
    mk = sorted({f.name.split("-")[0] for f in MARKET.glob("*-1d.csv.gz")})
    life = []
    for r in u[u.status.isin(["SETTLING", "DELISTED_ARCHIVE_ONLY"])].itertuples():
        p = shard("klines_1d", "binance", r.symbol)
        if p.exists():
            d = pd.read_parquet(p)
            if len(d) > 30:
                life.append((r.symbol, d.quote_volume.sum()))
    settled = [s for s, _ in sorted(life, key=lambda x: -x[1])[:N_SETTLED]]
    reason = {}
    for s in top: reason.setdefault(s, []).append("top_live_volume")
    for s in mk: reason.setdefault(s, []).append("in_data_market")
    for s in settled: reason.setdefault(s, []).append("top_delisted_lifetime_volume")
    sel = {"asof": datetime.now(timezone.utc).isoformat(), "symbols": sorted(reason), "reason": reason}
    (MECH / "selected.json").write_text(json.dumps(sel, indent=1))
    print(len(sel["symbols"]), "selected; settled:", settled)


def selected():
    return json.loads((MECH / "selected.json").read_text())["symbols"]


def step_klines_h():
    u = usdt_perps().set_index("symbol")
    for s in selected():
        p = shard("klines_1h", "binance", s)
        if (p.exists() and not FORCE) or s not in u.index:
            continue
        r = u.loc[s]
        if r.in_exchangeinfo:
            df = rest_klines(s, "1h", int(r.onboard_ts.timestamp() * 1000) - 3600000, now_ms())
            if r.status != "TRADING" and pd.notna(r.delivery_ts):
                df = df[df.ts <= r.delivery_ts]
            if r.status != "TRADING" and len(df):
                df = df[~((df.volume == 0) & (df.o == df.c) & (df.h == df.l))]
        else:
            df = vision_klines(s, "1h")
        save(df, p)
        print("klines_h", s, len(df), flush=True)


def step_funding():
    u = usdt_perps().set_index("symbol")
    for s in selected():
        p = shard("funding", "binance", s)
        if (p.exists() and not FORCE) or s not in u.index:
            continue
        r = u.loc[s]
        rows = []
        if r.in_exchangeinfo:
            cur = int(r.onboard_ts.timestamp() * 1000) - 1000
            while True:
                d = get(f"{FAPI}/fapi/v1/fundingRate", dict(symbol=s, startTime=cur, limit=1000), gap=0.7)
                if not d:
                    break
                rows += [(todt(x["fundingTime"]), float(x["fundingRate"]), float(x["markPrice"] or "nan")) for x in d]
                if len(d) < 1000:
                    break
                cur = d[-1]["fundingTime"] + 1
        else:
            for k in s3_list(f"data/futures/um/monthly/fundingRate/{s}/", None):
                if k.endswith(".zip"):
                    df = pd.read_csv(io.BytesIO(vision_zip(k)))
                    rows += [(todt(int(a)), float(b), float("nan")) for a, b in zip(df.iloc[:, 0], df.iloc[:, 2])]
        df = pd.DataFrame(rows, columns=["ts", "funding_rate", "mark_price"]).drop_duplicates("ts").sort_values("ts")
        save(df, p)
        print("funding", s, len(df), flush=True)


def oi_day(sym, day):
    b = vision_zip(f"data/futures/um/daily/metrics/{sym}/{sym}-metrics-{day}.zip")
    if b is None:
        return None
    df = pd.read_csv(io.BytesIO(b))
    df["ts"] = pd.to_datetime(df["create_time"], utc=True)
    df = df[df.ts.dt.minute == 0]          # часовая выборка из 5-минутных строк
    return df.drop(columns=["create_time", "symbol"])


def step_oi():
    """OI + доп. метрики (long/short ratio, taker ratio) из ежедневных архивов Vision, с 2020-09, час."""
    u = usdt_perps().set_index("symbol")
    for s in selected():
        p = shard("oi_1h", "binance", s)
        if (p.exists() and not FORCE) or s not in u.index:
            continue
        keys = [k for k in s3_list(f"data/futures/um/daily/metrics/{s}/", None) if k.endswith(".zip")]
        with ThreadPoolExecutor(32) as ex:
            parts = list(ex.map(lambda k: oi_day(s, k.split("-metrics-")[1][:10]), keys))
        parts = [x for x in parts if x is not None and len(x)]
        df = pd.concat(parts).sort_values("ts").drop_duplicates("ts") if parts else pd.DataFrame(columns=["ts"])
        # кусок после последнего дня архива - из REST (окно ~30 дней, вес мал)
        if s in u.index and u.loc[s].in_exchangeinfo and u.loc[s].status == "TRADING":
            d = get(f"{FAPI}/futures/data/openInterestHist", dict(symbol=s, period="1h", limit=500), gap=0.7)
            if isinstance(d, list) and d:
                r = pd.DataFrame(d)
                r["ts"] = todt(r.timestamp.astype("int64"))
                r = r.rename(columns={"sumOpenInterest": "sum_open_interest", "sumOpenInterestValue": "sum_open_interest_value"})
                r = r[["ts", "sum_open_interest", "sum_open_interest_value"]].astype({"sum_open_interest": float, "sum_open_interest_value": float})
                if len(df):
                    r = r[r.ts > df.ts.max()]
                df = pd.concat([df, r]).sort_values("ts")
        save(df, p)
        print("oi", s, len(df), df.ts.min() if len(df) else None, flush=True)


def bybit_pages(path, params, listkey="list", tskey=None, cap=2000, end_param="endTime", end0=None):
    """Листаем Bybit назад по времени (новые -> старые) до пустой страницы."""
    rows, end = [], end0
    for _ in range(cap):
        q = dict(params)
        if end:
            q[end_param] = end
        d = get(BYBIT + path, q, gap=0.12)
        if d.get("retCode") != 0:
            raise RuntimeError(str(d)[:200])
        lst = d["result"][listkey]
        if not lst:
            break
        rows += lst
        oldest = min(int(x[0] if isinstance(x, list) else x[tskey]) for x in lst)
        if end == oldest - 1:
            break
        end = oldest - 1
        if len(lst) < params.get("limit", 1000):
            break
    return rows


def step_bybit():
    """Bybit: свечи 1d/1h, funding, OI 1d/1h для тех из selected, что есть на Bybit (linear USDT perp)."""
    bu = pd.read_parquet(MECH / "universe_bybit.parquet")
    bp = bu[(bu.contract_type == "LinearPerpetual") & (bu.quote == "USDT")]
    names = set(bp.symbol)
    # у закрытых контрактов якорим пагинацию на дату делистинга (иначе первая страница пустая)
    anchor = {r.symbol: int(r.delivery_ts.timestamp() * 1000) + 3600000
              for r in bp.itertuples() if r.status != "Trading" and pd.notna(r.delivery_ts)}
    for s in selected():
        if s not in names:
            continue
        for ds, fn in (("klines_1d", lambda: bk_klines(s, "D", anchor.get(s))), ("klines_1h", lambda: bk_klines(s, "60", anchor.get(s))),
                       ("funding", lambda: bk_funding(s, anchor.get(s))), ("oi_1d", lambda: bk_oi(s, "1d", anchor.get(s))),
                       ("oi_1h", lambda: bk_oi(s, "1h", anchor.get(s)))):
            p = shard(ds, "bybit", s)
            if p.exists() and not FORCE:
                continue
            try:
                df = fn()
            except RuntimeError as e:      # разовые сбои Bybit (svc error) - пропуск, повтор при перезапуске
                print("bybit FAIL", ds, s, str(e)[:100], flush=True)
                continue
            save(df, p)
            print("bybit", ds, s, len(df), df.ts.min() if len(df) else None, flush=True)


def bk_klines(s, itv, end0=None):
    rows = bybit_pages("/v5/market/kline", dict(category="linear", symbol=s, interval=itv, limit=1000), end_param="end", end0=end0)
    df = pd.DataFrame(rows, columns=["ts", "o", "h", "l", "c", "volume", "quote_volume"])
    df["ts"] = todt(df.ts.astype("int64"))
    return df.astype({k: float for k in "ohlc"} | {"volume": float, "quote_volume": float}).drop_duplicates("ts").sort_values("ts")


def bk_funding(s, end0=None):
    rows = bybit_pages("/v5/market/funding/history", dict(category="linear", symbol=s, limit=200), tskey="fundingRateTimestamp", end0=end0)
    df = pd.DataFrame(rows)
    df["ts"] = todt(df.fundingRateTimestamp.astype("int64"))
    df["funding_rate"] = df.fundingRate.astype(float)
    return df[["ts", "funding_rate"]].drop_duplicates("ts").sort_values("ts")


def bk_oi(s, itv, end0=None):
    # у OI пагинация курсором, не endTime
    rows, cur = [], ""
    for _ in range(3000):
        q = dict(category="linear", symbol=s, intervalTime=itv, limit=200)
        if end0:
            q["endTime"] = end0
        if cur:
            q["cursor"] = cur
        d = get(BYBIT + "/v5/market/open-interest", q, gap=0.12)
        if d.get("retCode") != 0:
            raise RuntimeError(str(d)[:200])
        rows += d["result"]["list"]
        cur = d["result"].get("nextPageCursor", "")
        if not cur or not d["result"]["list"]:
            break
    df = pd.DataFrame(rows)
    if not len(df):
        return pd.DataFrame(columns=["ts"])
    df["ts"] = todt(df.timestamp.astype("int64"))
    df["open_interest"] = df.openInterest.astype(float)
    return df[["ts", "open_interest"]].drop_duplicates("ts").sort_values("ts")


def step_borrow():
    """Стоимость заёма (P4): только СНИМОК публичных ставок Bybit; история требует ключа -> пробел."""
    d = get(f"{BYBIT}/v5/spot-margin-trade/data")
    rows = []
    ts = pd.Timestamp.now(tz="UTC")
    for grp in d["result"]["vipCoinList"]:
        for c in grp["list"]:
            rows.append(dict(snap_ts=ts, currency=c["currency"], hourly_borrow_rate=float(c["hourlyBorrowRate"] or "nan"),
                             borrowable=c["borrowable"], max_borrowing=float(c["maxBorrowingAmount"] or "nan")))
    df = pd.DataFrame(rows)
    out = MECH / "borrow_snapshots.parquet"
    if out.exists():
        df = pd.concat([pd.read_parquet(out), df])
    save(df, out)
    print("borrow snapshot rows", len(df))


def step_liqprobe():
    """Фиксируем, что реально отдаётся по ликвидациям бесплатно (результат идёт в манифест)."""
    res = {}
    res["binance_allForceOrders"] = S.get(f"{FAPI}/fapi/v1/allForceOrders", params=dict(symbol="BTCUSDT"), timeout=30).status_code
    res["vision_liquidationSnapshot_keys"] = len(s3_list("data/futures/um/daily/liquidationSnapshot/", None))
    res["coinalyze_noauth"] = S.get("https://api.coinalyze.net/v1/liquidation-history", timeout=30).status_code
    res["coinglass_noauth"] = S.get("https://open-api.coinglass.com/public/v2/liquidation_history", timeout=30).text[:60]
    res["probe_ts"] = datetime.now(timezone.utc).isoformat()
    (MECH / "liquidation_probe.json").write_text(json.dumps(res, indent=1))
    print(res)


def step_build():
    """Склейка шардов в итоговые parquet: data/mech/<датасет>_<биржа>.parquet (+ колонка symbol)."""
    for d in sorted(RAW.iterdir()):
        for e in sorted(d.iterdir()):
            fr = []
            for f in sorted(e.glob("*.parquet")):
                x = pd.read_parquet(f)
                if len(x):
                    x.insert(0, "symbol", f.stem)
                    fr.append(x)
            if fr:
                df = pd.concat(fr, ignore_index=True)
                save(df, MECH / f"{d.name}_{e.name}.parquet")
                print(d.name, e.name, df.symbol.nunique(), "sym", len(df), "rows", df.ts.min(), df.ts.max())


if __name__ == "__main__":
    step = sys.argv[1]
    globals()["step_" + step]()
