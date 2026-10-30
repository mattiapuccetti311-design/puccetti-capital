"""Daily market data for the Markets page of Puccetti Capital Research.

Builds, in data/markets/:
  indices.json        five benchmark indices: level, returns, 1-year daily and
                      5-year monthly series, FX rates against the euro
  <index>.json        every constituent: name, sector, last price, returns,
                      market cap and analyst consensus (12-month targets)
  <index>-hist.json   5-year month-end total-return prices of every constituent,
                      used by the investment demo

Sources: constituents from Wikipedia (each page linked in the output),
prices, targets and FX from Yahoo Finance via the yfinance library.
Run: python tools/update_markets.py   (GitHub Actions runs it every weekday)

Each index is processed on its own: if one source fails, the previous file
for that index is kept and the others are still updated.
"""
import io
import json
import math
import os
import re
import sys
import time
from datetime import datetime, timezone

import pandas as pd
import requests
import yfinance as yf

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "markets")
UA = {"User-Agent": "PuccettiCapitalResearch/1.0 (https://mattiapuccetti311-design.github.io/puccetti-capital; data refresh)"}
TARGETS_PER_RUN = int(os.environ.get("TARGETS_PER_RUN", "1400"))
TARGET_MAX_AGE_DAYS = 7

INDICES = [
    {"id": "sp500", "name": "S&P 500", "market": "United States · NYSE and Nasdaq", "yahoo": "^GSPC", "currency": "USD", "symbol": "$",
     "wiki": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
     "official": "https://www.spglobal.com/spdji/en/indices/equity/sp-500/"},
    {"id": "ndx", "name": "Nasdaq-100", "market": "United States · Nasdaq", "yahoo": "^NDX", "currency": "USD", "symbol": "$",
     "wiki": "https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies",
     "official": "https://www.nasdaq.com/market-activity/quotes/nasdaq-ndx-index"},
    {"id": "csi300", "name": "CSI 300", "market": "China · Shanghai and Shenzhen", "yahoo": "000300.SS", "currency": "CNY", "symbol": "¥",
     "wiki": "https://en.wikipedia.org/wiki/CSI_300_Index",
     "official": "https://www.csindex.com.cn/en/indices/index-detail/000300",
     "proxy": "510300.SS", "proxyNote": "Yahoo Finance has little history for the CSI 300 index itself, so its level is tracked through the Huatai-PineBridge CSI 300 ETF (510300.SS)."},
    {"id": "nikkei225", "name": "Nikkei 225", "market": "Japan · Tokyo Stock Exchange", "yahoo": "^N225", "currency": "JPY", "symbol": "¥",
     "wiki": "https://en.wikipedia.org/wiki/Nikkei_225",
     "official": "https://indexes.nikkei.co.jp/en/nkave/index/component"},
    {"id": "euronext100", "name": "Euronext 100", "market": "Europe · Euronext (Paris, Amsterdam, Milan…)", "yahoo": "^N100", "currency": "EUR", "symbol": "€",
     "wiki": "https://en.wikipedia.org/wiki/Euronext_100",
     "official": "https://live.euronext.com/en/product/indices/FR0003502079-XPAR"},
]
FX = {"USD": "EURUSD=X", "CNY": "EURCNY=X", "JPY": "EURJPY=X"}  # local currency units per euro
SYM = {"USD": "$", "EUR": "€", "JPY": "¥", "CNY": "¥", "GBP": "£", "NOK": "kr ", "CHF": "CHF ", "DKK": "kr ", "SEK": "kr "}


def log(*a):
    print(*a, flush=True)


def clean(v, nd=4):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return round(f, nd)


def wiki_html(url):
    r = requests.get(url, headers=UA, timeout=40)
    r.raise_for_status()
    return r.text


def tables(url):
    return pd.read_html(io.StringIO(wiki_html(url)))


def col(df, *names):
    for c in df.columns:
        label = " ".join(map(str, c)) if isinstance(c, tuple) else str(c)
        if any(n.lower() in label.lower() for n in names):
            return c
    return None


# ---------- constituents ----------
def cons_sp500(ix):
    for df in tables(ix["wiki"]):
        s, n = col(df, "Symbol"), col(df, "Security")
        if s is not None and n is not None and len(df) > 400:
            g = col(df, "GICS Sector")
            return [{"t": str(r[s]).replace(".", "-"), "n": str(r[n]), "s": str(r[g]) if g is not None else ""} for _, r in df.iterrows()]
    raise RuntimeError("S&P 500 table not found")


def cons_ndx(ix):
    for df in tables(ix["wiki"]):
        s, n = col(df, "Ticker", "Symbol"), col(df, "Company")
        if s is not None and n is not None and len(df) > 90:
            g = col(df, "ICB Industry", "GICS Sector", "Industry")
            return [{"t": str(r[s]).replace(".", "-"), "n": str(r[n]), "s": str(r[g]) if g is not None else ""} for _, r in df.iterrows()]
    raise RuntimeError("Nasdaq-100 table not found")


def cons_csi300(ix):
    for df in tables(ix["wiki"]):
        s, n = col(df, "Ticker"), col(df, "Company")
        if s is not None and n is not None and len(df) > 250:
            g, ex = col(df, "Segment", "Sector"), col(df, "Exchange")
            out = []
            for _, r in df.iterrows():
                raw = str(r[s])
                m = re.search(r"(\d{6})", raw)
                if not m:
                    continue
                code = m.group(1)
                exch = (str(r[ex]) if ex is not None else "") + " " + raw
                suffix = ".SZ" if ("Shenzhen" in exch or "SZSE" in exch or code[0] in "03") else ".SS"
                out.append({"t": code + suffix, "n": str(r[n]), "s": str(r[g]) if g is not None else ""})
            return out
    raise RuntimeError("CSI 300 table not found")


def cons_nikkei(ix):
    from html.parser import HTMLParser

    class P(HTMLParser):
        def __init__(self):
            super().__init__()
            self.items, self.sector, self.in_li, self.in_h, self.buf = [], "", 0, False, ""

        def handle_starttag(self, tag, a):
            if tag in ("h3", "h4"):
                self.in_h, self.buf = True, ""
            if tag == "li":
                self.in_li += 1
                if self.in_li == 1:
                    self.buf = ""

        def handle_endtag(self, tag):
            if tag in ("h3", "h4") and self.in_h:
                self.in_h = False
                self.sector = re.sub(r"\[.*?\]", "", self.buf).strip()
            if tag == "li" and self.in_li:
                self.in_li -= 1
                if self.in_li == 0:
                    m = re.search(r"^(.*?)\s*\(TYO:\s*([0-9A-Z]{4})\)", self.buf.strip())
                    if m:
                        self.items.append({"t": m.group(2) + ".T", "n": m.group(1).strip(), "s": self.sector})

        def handle_data(self, d):
            if self.in_h or self.in_li:
                self.buf += d

    p = P()
    p.feed(wiki_html(ix["wiki"]))
    seen, out = set(), []
    for it in p.items:
        if it["t"] not in seen:
            seen.add(it["t"])
            out.append(it)
    if len(out) < 200:
        raise RuntimeError(f"Nikkei 225: only {len(out)} components parsed")
    return out


def cons_euronext(ix):
    for df in tables(ix["wiki"]):
        s, n = col(df, "Ticker"), col(df, "Name")
        if s is not None and n is not None and len(df) > 80:
            return [{"t": str(r[s]).strip(), "n": str(r[n]), "s": ""} for _, r in df.iterrows() if str(r[s]).strip() not in ("", "nan")]
    raise RuntimeError("Euronext 100 table not found")


CONS = {"sp500": cons_sp500, "ndx": cons_ndx, "csi300": cons_csi300, "nikkei225": cons_nikkei, "euronext100": cons_euronext}


# ---------- prices ----------
def download(tickers, **kw):
    """Batched yf.download returning a dict ticker -> pd.Series of adjusted closes."""
    out = {}
    for i in range(0, len(tickers), 150):
        batch = tickers[i:i + 150]
        for attempt in range(3):
            try:
                df = yf.download(batch, auto_adjust=True, progress=False, threads=True, group_by="ticker", **kw)
                break
            except Exception as e:  # network hiccup: retry
                log("  download retry", attempt, e)
                time.sleep(5 * (attempt + 1))
        else:
            continue
        for t in batch:
            try:
                s = df[t]["Close"] if len(batch) > 1 else df["Close"]
                if isinstance(s, pd.DataFrame):
                    s = s.iloc[:, 0]
                s = s.dropna()
                if len(s):
                    out[t] = s
            except Exception:
                pass
        time.sleep(1)
    return out


def monthly(s):
    """Month-end series as [["YYYY-MM", value], ...]; the last point is the latest close."""
    m = s.groupby(s.index.to_period("M")).last()
    return [[str(p), clean(v)] for p, v in m.items() if clean(v) is not None]


def ret(s, days=None, ytd=False):
    if s is None or len(s) < 2:
        return None
    last_d, last = s.index[-1], s.iloc[-1]
    if ytd:
        prev = s[s.index.year < last_d.year]
    else:
        prev = s[s.index <= last_d - pd.Timedelta(days=days)]
    if not len(prev):
        return None
    return clean(last / prev.iloc[-1] - 1, 5)


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


# ---------- analyst targets (cached, refreshed in rotation) ----------
def refresh_targets(tickers, cache):
    now = time.time()
    due = sorted(tickers, key=lambda t: cache.get(t, {}).get("ts", 0))
    due = [t for t in due if now - cache.get(t, {}).get("ts", 0) > TARGET_MAX_AGE_DAYS * 86400][:TARGETS_PER_RUN]
    log(f"analyst data: refreshing {len(due)} of {len(tickers)} tickers")
    fails = 0
    for k, t in enumerate(due):
        try:
            info = yf.Ticker(t).info or {}
            cache[t] = {
                "ts": now,
                "cur": info.get("currency"),
                "mcap": clean(info.get("marketCap"), 0),
                "low": clean(info.get("targetLowPrice")),
                "mean": clean(info.get("targetMeanPrice")),
                "med": clean(info.get("targetMedianPrice")),
                "high": clean(info.get("targetHighPrice")),
                "n": info.get("numberOfAnalystOpinions"),
                "rec": info.get("recommendationKey"),
                "sector": info.get("sector"),
                "name": info.get("longName") or info.get("shortName"),
            }
            fails = 0
        except Exception as e:
            fails += 1
            log("  info failed", t, str(e)[:120])
            if fails >= 15:  # probably rate limited: stop, the next run continues
                log("  too many failures in a row, stopping target refresh for this run")
                break
            time.sleep(3)
        if k % 50 == 49:
            log(f"  {k + 1} done")
        time.sleep(0.35)
    return cache


def refresh_esg(tickers, cache):
    """Sustainalytics ESG risk scores as published on Yahoo Finance (refreshed monthly)."""
    now = time.time()
    due = sorted(tickers, key=lambda t: cache.get(t, {}).get("ts", 0))
    due = [t for t in due if now - cache.get(t, {}).get("ts", 0) > 30 * 86400][:TARGETS_PER_RUN]
    log(f"ESG data: refreshing {len(due)} of {len(tickers)} tickers")
    fails = found = 0
    for k, t in enumerate(due):
        try:
            df = yf.Ticker(t).sustainability
            rec = {"ts": now}
            if df is not None and len(df):
                col0 = df.columns[0]
                g = lambda key: df.loc[key, col0] if key in df.index else None
                rec.update({"tot": clean(g("totalEsg"), 1), "e": clean(g("environmentScore"), 1), "s": clean(g("socialScore"), 1),
                            "g": clean(g("governanceScore"), 1), "cont": clean(g("highestControversy"), 0), "pct": clean(g("percentile"), 0),
                            "peer": str(g("peerGroup")) if g("peerGroup") is not None else None})
                if rec.get("tot") is not None:
                    found += 1
            cache[t] = rec
            fails = 0
        except Exception as e:
            fails += 1
            cache[t] = {"ts": now}
            if fails >= 25:
                log("  too many ESG failures in a row, stopping for this run")
                break
            time.sleep(2)
        if k % 100 == 99:
            log(f"  {k + 1} done, {found} with scores")
        time.sleep(0.3)
    log(f"ESG data: {found} scores found this run")
    return cache


BBG = {"FP": ".PA", "NA": ".AS", "IM": ".MI", "GY": ".DE", "LN": ".L", "SM": ".MC", "BB": ".BR", "SW": ".SW", "US": ""}


def covered_history(today):
    """5-year month-end total-return history for the listed companies in our notes, plus the CAC 40."""
    mk = load(os.path.join(os.path.dirname(OUT), "market.json"), {})
    want = {}
    for slug, c in mk.get("companies", {}).items():
        if c.get("type") != "listed":
            continue
        y = c.get("yahoo")
        if not y and c.get("ticker"):
            parts = c["ticker"].split()
            if len(parts) == 2 and parts[1] in BBG:
                y = parts[0] + BBG[parts[1]]
        if y:
            want[slug] = y
    px = download(sorted(set(want.values())) + ["^FCHI"], period="6y", interval="1d")
    cut = lambda s: monthly(s[s.index > s.index[-1] - pd.Timedelta(days=5 * 366)])
    out = {"updated": today, "series": {slug: {"yahoo": y, "s": cut(px[y])} for slug, y in want.items() if y in px},
           "bench": {"name": "CAC 40", "yahoo": "^FCHI", "s": cut(px["^FCHI"])} if "^FCHI" in px else None,
           "note": "Month-end closes adjusted for dividends and splits (total return), Yahoo Finance."}
    save(os.path.join(OUT, "covered-hist.json"), out)
    log(f"covered companies: 5-year history for {len(out['series'])} of {len(want)}")


def main():
    os.makedirs(OUT, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prev_ix = {i["id"]: i for i in load(os.path.join(OUT, "indices.json"), {}).get("indices", [])}
    cache_path = os.path.join(OUT, "targets-cache.json")
    cache = load(cache_path, {})

    # 1. constituents
    members = {}
    for ix in INDICES:
        try:
            members[ix["id"]] = CONS[ix["id"]](ix)
            log(f"{ix['name']}: {len(members[ix['id']])} constituents")
        except Exception as e:
            log(f"{ix['name']}: constituents FAILED ({e}); keeping previous list")
            old = load(os.path.join(OUT, ix["id"] + ".json"), {})
            members[ix["id"]] = [{"t": r["t"], "n": r["n"], "s": r.get("s", "")} for r in old.get("rows", [])]

    all_t = sorted({m["t"] for v in members.values() for m in v})

    # 2. indices, FX and constituent prices (5 years, daily, then made monthly)
    idx_px = download([i["yahoo"] for i in INDICES] + [i["proxy"] for i in INDICES if i.get("proxy")] + list(FX.values()), period="6y", interval="1d")
    px = download(all_t, period="6y", interval="1d")
    log(f"prices: {len(px)} of {len(all_t)} tickers")

    # 3. analyst targets, in rotation
    cache = refresh_targets(all_t, cache)
    save(cache_path, cache)
    esg_path = os.path.join(OUT, "esg-cache.json")
    esg = refresh_esg(all_t, load(esg_path, {}))
    save(esg_path, esg)

    fx = {cur: monthly(idx_px[t]) for cur, t in FX.items() if t in idx_px}
    out_ix = []
    for ix in INDICES:
        s = idx_px.get(ix["yahoo"])
        note = ""
        if ix.get("proxy") and (s is None or len(s) < 250) and ix["proxy"] in idx_px:
            s, note = idx_px[ix["proxy"]], ix["proxyNote"]
        if s is None:
            if ix["id"] in prev_ix:
                out_ix.append(prev_ix[ix["id"]])
            continue
        d1 = s[s.index > s.index[-1] - pd.Timedelta(days=366)]
        out_ix.append({
            **{k: ix[k] for k in ("id", "name", "market", "yahoo", "currency", "symbol", "wiki", "official")},
            "quote": "https://finance.yahoo.com/quote/" + requests.utils.quote(ix["yahoo"]),
            "last": clean(s.iloc[-1], 2), "lastDate": s.index[-1].strftime("%Y-%m-%d"),
            "r1d": clean(s.iloc[-1] / s.iloc[-2] - 1, 5) if len(s) > 1 else None,
            "r1m": ret(s, 30), "rytd": ret(s, ytd=True), "r1y": ret(s, 365), "r3y": ret(s, 3 * 365), "r5y": ret(s, 5 * 365),
            "daily": [[d.strftime("%Y-%m-%d"), clean(v, 2)] for d, v in d1.items()],
            "monthly": monthly(s[s.index > s.index[-1] - pd.Timedelta(days=5 * 366)]),
            "count": len(members.get(ix["id"], [])), "note": note,
        })

    for ix in INDICES:
        rows, hist = [], {}
        for m in members.get(ix["id"], []):
            t = m["t"]
            s = px.get(t)
            c = cache.get(t, {})
            cur = c.get("cur") or ix["currency"]
            row = {"t": t, "n": m["n"] if m["n"] and m["n"] != "nan" else (c.get("name") or t), "s": m.get("s") or c.get("sector") or "",
                   "cur": cur, "sym": SYM.get(cur, cur + " "), "mcap": c.get("mcap")}
            if s is not None and len(s) > 1:
                row.update({"p": clean(s.iloc[-1]), "d": s.index[-1].strftime("%Y-%m-%d"), "r1d": clean(s.iloc[-1] / s.iloc[-2] - 1, 5),
                            "rytd": ret(s, ytd=True), "r1y": ret(s, 365), "r5y": ret(s, 5 * 365)})
                hist[t] = monthly(s[s.index > s.index[-1] - pd.Timedelta(days=5 * 366)])
            if c.get("n"):
                row.update({"tl": c.get("low"), "tm": c.get("med") or c.get("mean"), "th": c.get("high"), "na": c.get("n"), "rec": c.get("rec"),
                            "tAsOf": datetime.fromtimestamp(c["ts"], timezone.utc).strftime("%Y-%m-%d")})
            e = esg.get(t, {})
            if e.get("tot") is not None:
                row.update({"esg": e["tot"], "esgE": e.get("e"), "esgS": e.get("s"), "esgG": e.get("g"), "cont": e.get("cont"), "esgPct": e.get("pct")})
            rows.append(row)
        rows.sort(key=lambda r: -(r.get("mcap") or 0))
        if not rows:
            continue
        save(os.path.join(OUT, ix["id"] + ".json"), {"id": ix["id"], "name": ix["name"], "updated": today, "source": ix["wiki"], "rows": rows})
        save(os.path.join(OUT, ix["id"] + "-hist.json"), {"id": ix["id"], "updated": today, "series": hist})
        log(f"{ix['name']}: wrote {len(rows)} rows, {sum(1 for r in rows if 'tm' in r)} with analyst targets")

    try:
        covered_history(today)
    except Exception as e:
        log("covered history failed:", e)
    save(os.path.join(OUT, "indices.json"), {"updated": today, "fx": fx, "fxNote": "Month-end euro reference rates from Yahoo Finance (local currency per €1).", "indices": out_ix})
    if not out_ix:
        log("No index data at all: check the network or Yahoo Finance.")
        sys.exit(1)


if __name__ == "__main__":
    main()
