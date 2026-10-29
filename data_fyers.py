import datetime as dt
import pandas as pd
from fyers_apiv3 import fyersModel


def client(client_id, token):
    return fyersModel.FyersModel(client_id=client_id, token=token,
                                 is_async=False, log_path="")


def candles(fy, symbol, resolution="1", days=5):
    to = dt.date.today()
    fr = to - dt.timedelta(days=days)
    r = fy.history({"symbol": symbol, "resolution": resolution, "date_format": "1",
                    "range_from": fr.strftime("%Y-%m-%d"),
                    "range_to": to.strftime("%Y-%m-%d"), "cont_flag": "1"})
    if r.get("s") != "ok":
        raise RuntimeError(str(r))
    df = pd.DataFrame(r["candles"], columns=["time", "open", "high", "low", "close", "volume"])
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    return df.set_index("time").astype(float)


def chain(fy, symbol="NSE:NIFTY50-INDEX", strikes=15, expiry_ts=""):
    r = fy.optionchain({"symbol": symbol, "strikecount": strikes, "timestamp": expiry_ts})
    if r.get("s") != "ok":
        raise RuntimeError(str(r))
    d = r["data"]
    df = pd.DataFrame([x for x in d.get("optionsChain", [])
                       if x.get("option_type") in ("CE", "PE")])
    return df, d.get("expiryData", []), d.get("callOi", 0), d.get("putOi", 0)
