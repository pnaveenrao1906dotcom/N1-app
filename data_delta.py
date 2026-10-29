import re
import time
import pandas as pd
import requests

BASE = "https://api.delta.exchange/v2"
S = requests.Session()


def _get(path, params=None):
    r = S.get(BASE + path, params=params, timeout=20)
    r.raise_for_status()
    return r.json().get("result", [])


def candles(symbol, resolution="1m", days=5):
    end = int(time.time())
    start = end - days * 86400
    step = {"1m": 60, "5m": 300, "1d": 86400}[resolution] * 2000
    out, t = [], start
    while t < end:
        t2 = min(t + step, end)
        out += _get("/history/candles", {"symbol": symbol, "resolution": resolution,
                                         "start": t, "end": t2})
        t = t2
    df = pd.DataFrame(out)
    if df.empty:
        return df
    df = df.drop_duplicates("time").sort_values("time")
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    return df.set_index("time")[["open", "high", "low", "close", "volume"]].astype(float)


def option_chain(underlying):
    rows = _get("/tickers", {"contract_types": "call_options,put_options",
                             "underlying_asset_symbols": underlying})
    recs = []
    for t in rows:
        m = re.match(r"([CP])-([A-Z0-9]+)-(\d+(?:\.\d+)?)-(\d{6})$", t.get("symbol", ""))
        if not m:
            continue
        g = t.get("greeks") or {}
        q = t.get("quotes") or {}
        recs.append({
            "symbol": t["symbol"],
            "type": "CALL" if m.group(1) == "C" else "PUT",
            "strike": float(m.group(3)),
            "expiry": pd.to_datetime(m.group(4), format="%d%m%y").date(),
            "ltp": t.get("close"), "oi": t.get("oi"), "volume": t.get("volume"),
            "iv": q.get("mark_iv"), "delta": g.get("delta"), "gamma": g.get("gamma"),
            "theta": g.get("theta"), "vega": g.get("vega"),
        })
    df = pd.DataFrame(recs)
    if df.empty:
        return df
    num = ["ltp", "oi", "volume", "iv", "delta", "gamma", "theta", "vega"]
    df[num] = df[num].apply(pd.to_numeric, errors="coerce")
    return df
