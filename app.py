import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import data_delta as dd
import data_fyers as dfy
import indicators as ind


def n1_icon():
    try:
        from PIL import Image, ImageDraw, ImageFont
        im = Image.new("RGB", (128, 128), "#2962ff")
        f = ImageFont.load_default(size=64)
        ImageDraw.Draw(im).text((64, 64), "N1", fill="white", font=f, anchor="mm")
        return im
    except Exception:
        return "📈"


st.set_page_config(page_title="N1", page_icon=n1_icon(), layout="wide")


def secret(key):
    try:
        return st.secrets.get(key, "")
    except Exception:
        return ""


TF = {"1m": 1, "2m": 2, "3m": 3, "5m": 5, "10m": 10, "15m": 15, "25m": 25, "30m": 30,
      "35m": 35, "1h": 60, "75m": 75, "77m": 77, "2h": 120, "4h": 240,
      "1d": "D", "1w": "W", "1M": "M", "1Y": "Y"}
CTYPES = ["Candlestick", "Bar", "Line", "Step line", "Heikin Ashi"]
DELTA_PRESETS = {"BTC": "BTCUSD", "ETH": "ETHUSD", "Gold": "XAUTUSD",
                 "Silver": "SLVONUSD", "Oil": "OILUSD"}

# ---------------- sidebar: credentials ----------------
st.sidebar.title("N1")
CID = st.sidebar.text_input("Fyers client id (APPID-100)", secret("FYERS_CLIENT_ID"))
TOK = st.sidebar.text_input("Fyers access token (रोज़ नया)", secret("FYERS_TOKEN"), type="password")


# ---------------- data loaders ----------------
@st.cache_data(ttl=60, show_spinner=False)
def raw_delta(sym, base, days):
    return dd.candles(sym, base, days)


@st.cache_data(ttl=60, show_spinner=False)
def raw_fyers(sym, res, days, cid, tok):
    return dfy.candles(dfy.client(cid, tok), sym, res, days)


@st.cache_data(ttl=120, show_spinner=False)
def raw_yf(sym, base, days):
    import yfinance as yf
    if base == "1m":
        d = yf.download(sym, interval="1m", period=f"{min(days, 7)}d", progress=False, auto_adjust=False)
    else:
        d = yf.download(sym, interval="1d", period="10y", progress=False, auto_adjust=False).tail(days)
    if isinstance(d.columns, pd.MultiIndex):
        d.columns = d.columns.get_level_values(0)
    d.columns = [c.lower() for c in d.columns]
    d.index = pd.to_datetime(d.index, utc=True)
    if "volume" not in d:
        d["volume"] = 0.0
    return d[["open", "high", "low", "close", "volume"]].astype(float)


@st.cache_data(ttl=60, show_spinner=False)
def delta_chain(und):
    return dd.option_chain(und)


@st.cache_data(ttl=60, show_spinner=False)
def fy_chain(sym, strikes, ts, cid, tok):
    return dfy.chain(dfy.client(cid, tok), sym, strikes, ts)


def fetch(exch, sym, base, days):
    if exch == "delta":
        return raw_delta(sym, base, days)
    if exch == "fyers":
        if base == "1m":
            return raw_fyers(sym, "1", min(days, 100), CID, TOK)
        return raw_fyers(sym, "D", min(days, 365), CID, TOK)
    return raw_yf(sym, base, days)


def resample(df, tf, nse):
    v = TF[tf]
    if df.empty or v == 1 or tf == "1d":
        return df
    tz = "Asia/Kolkata" if nse else "UTC"
    x = df.tz_convert(tz)
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    if isinstance(v, int):
        mins = x.index.hour * 60 + x.index.minute - (555 if nse else 0)
        key = [x.index.normalize(), mins // v]
        out = x.groupby(key).agg(agg)
        ts = x.index.to_series().groupby(key).first()
        out.index = pd.DatetimeIndex(ts.values, tz="UTC")
        return out.sort_index().dropna(subset=["close"])
    rule = {"W": "W-SUN", "M": "MS", "Y": "YS"}[v]
    return x.resample(rule).agg(agg).dropna(subset=["close"]).tz_convert("UTC")


# ---------------- sidebar: instrument ----------------
srcname = st.sidebar.radio("Source", ["Delta", "Fyers", "EURUSD"], horizontal=True)
exch = {"Delta": "delta", "Fyers": "fyers", "EURUSD": "yf"}[srcname]
legs, chain_view = [], None

if srcname == "Delta":
    mode = st.sidebar.radio("Type", ["Perp/Future", "Option", "Strangle"], horizontal=True)
    if mode == "Perp/Future":
        pr = st.sidebar.selectbox("Instrument", list(DELTA_PRESETS))
        legs = [st.sidebar.text_input("Symbol", DELTA_PRESETS[pr], key=f"ds_{pr}")]
    else:
        und = st.sidebar.text_input("Options underlying", "BTC").upper()
        st.sidebar.caption("BTC, ETH; गोल्ड के लिए XAUT आज़माएँ")
        ch = delta_chain(und)
        if ch.empty:
            st.sidebar.error("ऑप्शन चेन नहीं मिली, underlying का नाम चेक करें")
        else:
            ex = st.sidebar.selectbox("Expiry", sorted(ch.expiry.unique()))
            c = ch[ch.expiry == ex]
            chain_view = c
            calls, puts = c[c.type == "CALL"], c[c.type == "PUT"]
            if mode == "Option":
                t = st.sidebar.radio("Call/Put", ["CALL", "PUT"], horizontal=True)
                d = calls if t == "CALL" else puts
                k = st.sidebar.selectbox("Strike", sorted(d.strike.unique()))
                legs = [d[d.strike == k].symbol.iloc[0]]
            else:
                kc = st.sidebar.selectbox("Call strike", sorted(calls.strike.unique()))
                kp = st.sidebar.selectbox("Put strike", sorted(puts.strike.unique()))
                legs = [calls[calls.strike == kc].symbol.iloc[0], puts[puts.strike == kp].symbol.iloc[0]]

elif srcname == "Fyers":
    mode = st.sidebar.radio("Type", ["Index/Future/Symbol", "Option", "Strangle"], horizontal=True)
    if mode == "Index/Future/Symbol":
        legs = [st.sidebar.text_input("Symbol", "NSE:NIFTY50-INDEX")]
        st.sidebar.caption("फ्यूचर्स का उदाहरण: NSE:NIFTY26NOVFUT")
    elif CID and TOK:
        try:
            _, exps, _, _ = fy_chain("NSE:NIFTY50-INDEX", 15, "", CID, TOK)
            labels = [e["date"] for e in exps]
            sel = st.sidebar.selectbox("Expiry", labels)
            ts = str(next(e["expiry"] for e in exps if e["date"] == sel))
            cdf, _, co, po = fy_chain("NSE:NIFTY50-INDEX", 15, ts, CID, TOK)
            if cdf.empty:
                st.sidebar.error("चेन खाली आई")
            else:
                chain_view = (cdf, co, po)
                calls, puts = cdf[cdf.option_type == "CE"], cdf[cdf.option_type == "PE"]
                if mode == "Option":
                    t = st.sidebar.radio("Call/Put", ["CE", "PE"], horizontal=True)
                    d = calls if t == "CE" else puts
                    k = st.sidebar.selectbox("Strike", sorted(d.strike_price.unique()))
                    legs = [d[d.strike_price == k].symbol.iloc[0]]
                else:
                    kc = st.sidebar.selectbox("Call strike", sorted(calls.strike_price.unique()))
                    kp = st.sidebar.selectbox("Put strike", sorted(puts.strike_price.unique()))
                    legs = [calls[calls.strike_price == kc].symbol.iloc[0],
                            puts[puts.strike_price == kp].symbol.iloc[0]]
        except Exception as e:
            st.sidebar.error(f"Fyers: {e}")
    else:
        st.sidebar.warning("Fyers client id और token डालें")
else:
    legs = ["EURUSD=X"]

extras_txt = st.sidebar.text_area(
    "Extra symbols (हर लाइन में एक)", placeholder="delta:BTCUSD\nfyers:NSE:NIFTY50-INDEX\nyf:EURUSD=X",
    help="Spread, Sum और Relative Strength के लिए")
auto = st.sidebar.toggle("Auto refresh (60s)", False)

# ---------------- top controls ----------------
c1, c2, c3 = st.columns([2, 2, 2])
tf = c1.selectbox("Timeframe", list(TF), index=list(TF).index("5m"))
ctype = c2.selectbox("Chart", CTYPES)
intraday = isinstance(TF[tf], int)
base = "1m" if intraday else "1d"
days = c3.slider("Days of data", 1, 30, 5) if intraday else c3.slider("Days of data", 30, 3650, 730)

if not legs:
    st.info("साइडबार में इंस्ट्रूमेंट चुनें")
    st.stop()

# ---------------- load data ----------------
nse = exch == "fyers"
try:
    frames = [fetch(exch, s, base, days) for s in legs]
    if len(frames) == 2:
        idx = frames[0].index.intersection(frames[1].index)
        raw = frames[0].loc[idx] + frames[1].loc[idx]
    else:
        raw = frames[0]
except Exception as e:
    st.error(f"डेटा नहीं मिला: {e}")
    st.stop()
if raw.empty:
    st.warning("इस सिंबल/रेंज का डेटा खाली है")
    st.stop()
df = resample(raw, tf, nse)

symbols = {"MAIN": df}
for line in extras_txt.splitlines():
    if ":" not in line:
        continue
    ex_, sym_ = line.strip().split(":", 1)
    ex_ = {"delta": "delta", "fyers": "fyers", "yf": "yf"}.get(ex_.lower())
    if ex_:
        try:
            symbols[line.strip()] = resample(fetch(ex_, sym_, base, days), tf, ex_ == "fyers")
        except Exception as e:
            st.warning(f"{line}: {e}")

comp_name = None
if len(symbols) > 1:
    comp_name = st.sidebar.selectbox("Relative Strength comparison", [k for k in symbols if k != "MAIN"])
ctx = {"symbols": symbols, "comp": symbols[comp_name]["close"] if comp_name else None}

# ---------------- indicators UI ----------------
active = {}
with c1.popover("fx  Indicators"):
    for name, spec in ind.REG.items():
        if st.checkbox(name, key=f"on_{name}"):
            with st.container(border=True):
                p = {}
                for k, v in spec["params"].items():
                    key = f"{name}_{k}"
                    if k.startswith("sym"):
                        opts = ["—"] + list(symbols)
                        p[k] = st.selectbox(k, opts, index=opts.index(v) if v in opts else 0, key=key)
                    elif k in ind.CHOICES:
                        opts = ind.CHOICES[k]
                        p[k] = st.selectbox(k, opts, index=opts.index(v), key=key)
                    elif isinstance(v, bool):
                        p[k] = st.checkbox(k, v, key=key)
                    elif isinstance(v, int):
                        p[k] = st.number_input(k, value=v, step=1, key=key)
                    elif isinstance(v, float):
                        p[k] = st.number_input(k, value=v, step=0.1, format="%.3f", key=key)
                    else:
                        p[k] = st.text_input(k, v, key=key)
                p["colors"] = [st.color_picker(f"colour {i + 1}", col, key=f"{name}_c{i}")
                               for i, col in enumerate(spec["colors"])]
            active[name] = p


# ---------------- build chart payload ----------------
def tsec(idx):
    t = idx.tz_convert("Asia/Kolkata").tz_localize(None)
    return ((t - pd.Timestamp("1970-01-01")) // pd.Timedelta(seconds=1)).astype("int64")


def pts(times, s, colors=None):
    out = []
    for i, (t, v) in enumerate(zip(times, s.values)):
        if v is None or np.isnan(v):
            continue
        d = {"time": int(t), "value": float(v)}
        if colors is not None:
            d["color"] = colors[i]
        out.append(d)
    return out


def heikin(d):
    c = (d.open + d.high + d.low + d.close) / 4
    o = np.zeros(len(d))
    if len(d):
        o[0] = (d.open.iloc[0] + d.close.iloc[0]) / 2
    for i in range(1, len(d)):
        o[i] = (o[i - 1] + c.iloc[i - 1]) / 2
    o = pd.Series(o, index=d.index)
    return pd.DataFrame({"open": o, "high": pd.concat([d.high, o, c], axis=1).max(axis=1),
                         "low": pd.concat([d.low, o, c], axis=1).min(axis=1), "close": c}, index=d.index)


times = tsec(df.index)
plot_df = heikin(df) if ctype == "Heikin Ashi" else df
payload = {"times": [int(t) for t in times],
           "type": {"Candlestick": "candle", "Heikin Ashi": "candle", "Bar": "bar",
                    "Line": "line", "Step line": "step"}[ctype]}
if payload["type"] in ("candle", "bar"):
    payload["ohlc"] = [{"time": int(t), "open": float(o), "high": float(h), "low": float(l), "close": float(c)}
                       for t, o, h, l, c in zip(times, plot_df.open, plot_df.high, plot_df.low, plot_df.close)]
else:
    payload["line"] = [{"time": int(t), "value": float(c)} for t, c in zip(times, df.close)]

series, hl_main, pane_i = [], [], 0
for name, p in active.items():
    try:
        lines = ind.REG[name]["fn"](df, p, ctx)
    except Exception as e:
        st.warning(f"{name}: {e}")
        continue
    if not lines and name == "Relative Strength":
        st.warning("Relative Strength के लिए Extra symbols में एक सिंबल डालें")
    if any(l["pane"] == "sub" for l in lines):
        pane_i += 1
    for l in lines:
        if l.get("data") is None:
            hl_main += l.get("hlines", [])
            continue
        s = l["data"].reindex(df.index)
        series.append({"name": l["name"], "kind": l.get("kind", "line"), "color": l["color"],
                       "width": l.get("width", 1), "pane": pane_i if l["pane"] == "sub" else 0,
                       "data": pts(times, s, l.get("colors_pt")), "hlines": l.get("hlines", [])})
payload["ind"], payload["hlines"] = series, hl_main

# ---------------- tabs ----------------
tab1, tab2 = st.tabs(["Chart", "Option chain"])
with tab1:
    html = Path(__file__).with_name("chart.html").read_text(encoding="utf-8")
    html = html.replace("__PAYLOAD__", json.dumps(payload, default=float))
    components.html(html, height=520 + 170 * pane_i, scrolling=False)

with tab2:
    if chain_view is None:
        st.info("Option या Strangle मोड चुनें")
    elif srcname == "Delta":
        c = chain_view
        cc, pp = c[c.type == "CALL"].set_index("strike"), c[c.type == "PUT"].set_index("strike")
        cols = ["ltp", "oi", "volume", "iv", "delta", "gamma", "theta", "vega"]
        tbl = cc[cols].add_prefix("C_").join(pp[cols].add_prefix("P_"), how="outer").sort_index()
        a, b = st.columns(2)
        a.metric("PCR (OI)", round(pp.oi.sum() / max(cc.oi.sum(), 1e-9), 3))
        b.metric("PCR (Volume)", round(pp.volume.sum() / max(cc.volume.sum(), 1e-9), 3))
        st.dataframe(tbl, use_container_width=True)
    else:
        cdf, co, po = chain_view
        a, b = st.columns(2)
        a.metric("PCR (OI)", round(po / max(co, 1), 3))
        b.metric("Call OI / Put OI", f"{co:,} / {po:,}")
        cols = [c for c in ["strike_price", "option_type", "ltp", "oi", "volume", "symbol"] if c in cdf]
        st.dataframe(cdf[cols].sort_values(["strike_price", "option_type"]), use_container_width=True)

if auto:
    time.sleep(60)
    st.rerun()
