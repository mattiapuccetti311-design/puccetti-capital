"""Macro, rates and crypto data for the Markets page of Puccetti Capital Research.

Builds data/markets/macro.json: interest rates, bond yields, inflation,
unemployment and the two largest crypto-assets, each with its latest value,
changes over one month and one year, and a 5-year month-end series.

All sources are free and need no API key (found through the public-apis list,
https://github.com/public-apis/public-apis):
  ECB Data Portal   https://data.ecb.europa.eu        policy rates, €STR, euro area yields, unemployment
  Eurostat          https://ec.europa.eu/eurostat      HICP inflation (euro area, Italy, Germany, France)
  FRED (St. Louis Fed) https://fred.stlouisfed.org     US rates, Treasury yields, US CPI and unemployment,
                                                     German and Italian 10-year yields
  CoinGecko         https://www.coingecko.com          bitcoin and ether in euros

Run: python tools/update_macro.py   (GitHub Actions runs it after update_markets.py)
Each series is fetched on its own: if one source fails, the previous value of
that series is kept and the others are still updated.
"""
import csv
import io
import json
import os
import time
from datetime import date, datetime, timedelta, timezone

import requests

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "markets", "macro.json")
UA = {"User-Agent": "PuccettiCapitalResearch/1.0 (https://mattiapuccetti311-design.github.io/puccetti-capital; data refresh)"}
START = (date.today() - timedelta(days=5 * 366 + 31)).isoformat()

ECB = "https://data-api.ecb.europa.eu/service/data/"
FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id="
EUROSTAT = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/prc_hicp_minr"

SRC = {
    "ecb": ("ECB Data Portal", "https://data.ecb.europa.eu/"),
    "eurostat": ("Eurostat", "https://ec.europa.eu/eurostat/web/hicp"),
    "fred": ("FRED, Federal Reserve Bank of St. Louis", "https://fred.stlouisfed.org/"),
    "coingecko": ("CoinGecko", "https://www.coingecko.com/"),
}

# group, id, name, kind, key, unit
SERIES = [
    ("Policy rates", "ecb-dfr", "ECB deposit facility rate", "ecb", "FM/D.U2.EUR.4F.KR.DFR.LEV", "%"),
    ("Policy rates", "estr", "€STR (euro short-term rate)", "ecb", "EST/B.EU000A2X2A25.WT", "%"),
    ("Policy rates", "us-ffr", "US federal funds rate (effective)", "fred", "DFF", "%"),
    ("Bond yields", "ea-10y", "Euro area 10-year yield (AAA curve)", "ecb", "YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y", "%"),
    ("Bond yields", "de-10y", "Germany 10-year Bund yield", "fred", "IRLTLT01DEM156N", "%"),
    ("Bond yields", "it-10y", "Italy 10-year BTP yield", "fred", "IRLTLT01ITM156N", "%"),
    ("Bond yields", "us-2y", "US 2-year Treasury yield", "fred", "DGS2", "%"),
    ("Bond yields", "us-10y", "US 10-year Treasury yield", "fred", "DGS10", "%"),
    ("Inflation", "hicp-ea", "Euro area inflation (HICP, y/y)", "eurostat", "EA", "%"),
    ("Inflation", "hicp-it", "Italy inflation (HICP, y/y)", "eurostat", "IT", "%"),
    ("Inflation", "hicp-de", "Germany inflation (HICP, y/y)", "eurostat", "DE", "%"),
    ("Inflation", "hicp-fr", "France inflation (HICP, y/y)", "eurostat", "FR", "%"),
    ("Inflation", "us-cpi", "US inflation (CPI, y/y)", "fred-yoy", "CPIAUCSL", "%"),
    ("Labour", "ea-unemp", "Euro area unemployment rate", "ecb", "LFSI/M.I9.S.UNEHRT.TOTAL0.15_74.T", "%"),
    ("Labour", "us-unemp", "US unemployment rate", "fred", "UNRATE", "%"),
    ("Crypto", "btc", "Bitcoin", "coingecko", "bitcoin", "€"),
    ("Crypto", "eth", "Ether", "coingecko", "ethereum", "€"),
]


def log(*a):
    print(*a, flush=True)


def get(url, **kw):
    for attempt in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=60, **kw)
            if r.status_code == 429:
                time.sleep(20 * (attempt + 1))
                continue
            r.raise_for_status()
            return r
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"{url}: rate limited")


def num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def iso(t):
    """ECB/Eurostat periods: 2026-11-03 (daily) or 2026-10 (monthly) -> date string."""
    return t if len(t) == 10 else t + "-01"


def ecb(key):
    r = get(ECB + key, params={"startPeriod": START, "format": "csvdata"})
    rows = list(csv.DictReader(io.StringIO(r.text)))
    return [(iso(x["TIME_PERIOD"]), num(x["OBS_VALUE"])) for x in rows if num(x["OBS_VALUE"]) is not None]


def fred(key, start=START):
    r = get(FRED + key, params={"cosd": start})
    rows = list(csv.reader(io.StringIO(r.text)))[1:]
    return [(d, num(v)) for d, v in rows if num(v) is not None]


def fred_yoy(key):
    s = fred(key, (date.fromisoformat(START) - timedelta(days=400)).isoformat())
    by = {d[:7]: v for d, v in s}
    out = []
    for d, v in s:
        y, m = int(d[:4]), d[5:7]
        prev = by.get(f"{y - 1}-{m}")
        if prev and d >= START:
            out.append((d, (v / prev - 1) * 100))
    return out


_EUROSTAT = {}


def eurostat(geo):
    if not _EUROSTAT:
        params = [("unit", "RCH_A"), ("coicop18", "TOTAL"), ("sinceTimePeriod", START[:7])] + [("geo", g) for _, _, _, k, g, _ in SERIES if k == "eurostat"]
        d = get(EUROSTAT, params=params).json()
        times = sorted(d["dimension"]["time"]["category"]["index"].items(), key=lambda x: x[1])
        geos = d["dimension"]["geo"]["category"]["index"]
        n = len(times)
        for g, gi in geos.items():
            _EUROSTAT[g] = [(iso(t), d["value"][str(gi * n + ti)]) for t, ti in times if str(gi * n + ti) in d["value"]]
    return _EUROSTAT[geo]


def coingecko(coin):
    time.sleep(3)  # the free API allows a few calls per minute
    d = get(f"https://api.coingecko.com/api/v3/coins/{coin}/market_chart", params={"vs_currency": "eur", "days": "365", "interval": "daily"}).json()
    s = {}
    for ms, v in d["prices"]:
        s[datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")] = v
    return sorted(s.items())


def before(s, d):
    """Last value on or before date d."""
    v = None
    for x, y in s:
        if x > d:
            break
        v = y
    return v


def monthly(s):
    m = {}
    for d, v in s:
        m[d[:7]] = v
    return [[k, round(v, 4)] for k, v in sorted(m.items())]


def build(group, sid, name, kind, key, unit):
    s = {"ecb": ecb, "fred": fred, "fred-yoy": fred_yoy, "eurostat": eurostat, "coingecko": coingecko}[kind](key)
    if not s:
        raise RuntimeError("no observations")
    last_d, last = s[-1]
    ld = date.fromisoformat(last_d)
    m1 = before(s, (ld - timedelta(days=30)).isoformat())
    y1 = before(s, (ld - timedelta(days=365)).isoformat())
    if y1 is None and (date.fromisoformat(s[0][0]) - (ld - timedelta(days=365))).days <= 3:
        y1 = s[0][1]  # a 365-day history starts on, or a day after, the same date last year
    monthly_freq = all(d.endswith("-01") for d, _ in s[-6:])  # monthly series: date is the first of the reference month
    src = SRC["fred" if kind == "fred-yoy" else kind]
    page = {"ecb": "https://data.ecb.europa.eu/data/datasets/" + key.replace("/", "/" + key.split("/")[0] + ".", 1),
            "fred": "https://fred.stlouisfed.org/series/" + key, "fred-yoy": "https://fred.stlouisfed.org/series/" + key,
            "eurostat": "https://ec.europa.eu/eurostat/databrowser/view/prc_hicp_minr/default/table",
            "coingecko": "https://www.coingecko.com/en/coins/" + key}[kind]
    out = {"group": group, "id": sid, "name": name, "unit": unit, "last": round(last, 4), "lastDate": last_d[:7] if monthly_freq else last_d,
           "freq": "monthly" if monthly_freq else "daily", "source": src[0], "url": page, "monthly": monthly(s)}
    if unit == "%":  # changes in percentage points
        out.update({"ch1m": round(last - m1, 4) if m1 is not None and not monthly_freq else None, "ch1y": round(last - y1, 4) if y1 is not None else None})
        if monthly_freq and len(s) > 1:
            out["ch1m"] = round(last - s[-2][1], 4)
    else:  # prices: changes in per cent, plus the last year of daily closes
        out.update({"r1d": round(last / s[-2][1] - 1, 5) if len(s) > 1 else None, "r1m": round(last / m1 - 1, 5) if m1 else None,
                    "r1y": round(last / y1 - 1, 5) if y1 else None, "daily": [[d, round(v, 2)] for d, v in s[-366:]]})
    return out


def main():
    try:
        with open(OUT, encoding="utf-8") as f:
            prev = {x["id"]: x for x in json.load(f).get("series", [])}
    except Exception:
        prev = {}
    series, failed = [], []
    for spec in SERIES:
        try:
            x = build(*spec)
            series.append(x)
            log(f"{x['name']}: {x['last']:.2f}{'' if x['unit'] == '%' else ' €'} ({x['lastDate']})")
        except Exception as e:
            log(f"{spec[2]}: FAILED ({e}); keeping previous value")
            failed.append(spec[1])
            if spec[1] in prev:
                series.append({**prev[spec[1]], "stale": True})
    # spread: Italian over German 10-year yield, in basis points, from the two FRED monthly series
    by = {x["id"]: x for x in series}
    if "it-10y" in by and "de-10y" in by:
        de = dict(by["de-10y"]["monthly"])
        sp = [[m, round((v - de[m]) * 100, 1)] for m, v in by["it-10y"]["monthly"] if m in de]
        if sp:
            series.insert(series.index(by["it-10y"]) + 1, {
                "group": "Bond yields", "id": "btp-bund", "name": "BTP–Bund spread (Italy minus Germany, 10-year)", "unit": "bp",
                "last": sp[-1][1], "lastDate": sp[-1][0], "freq": "monthly", "ch1m": round(sp[-1][1] - sp[-2][1], 1) if len(sp) > 1 else None,
                "ch1y": round(sp[-1][1] - sp[-13][1], 1) if len(sp) > 12 else None, "source": SRC["fred"][0],
                "url": "https://fred.stlouisfed.org/series/IRLTLT01ITM156N", "monthly": sp})
    if not series:
        raise SystemExit("No macro data at all: check the network.")
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "failed": failed,
                   "sources": [{"name": n, "url": u} for n, u in SRC.values()], "series": series}, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, OUT)
    log(f"macro.json: {len(series)} series, {len(failed)} failed")


if __name__ == "__main__":
    main()
