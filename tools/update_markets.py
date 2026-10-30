"""Daily market data for the Markets page of Puccetti Capital Research.

Builds, in data/markets/:
  indices.json        twenty benchmark indices: level, returns, 1-year daily and
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
TARGETS_PER_RUN = int(os.environ.get("TARGETS_PER_RUN", "2800"))
TARGET_MAX_AGE_DAYS = 7

INDICES = [
    {"id": "sp500", "region": "Americas", "name": "S&P 500", "market": "United States · NYSE and Nasdaq", "yahoo": "^GSPC", "currency": "USD", "symbol": "$",
     "wiki": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
     "official": "https://www.spglobal.com/spdji/en/indices/equity/sp-500/"},
    {"id": "ndx", "region": "Americas", "name": "Nasdaq-100", "market": "United States · Nasdaq", "yahoo": "^NDX", "currency": "USD", "symbol": "$",
     "wiki": "https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies",
     "official": "https://www.nasdaq.com/market-activity/quotes/nasdaq-ndx-index"},
    {"id": "csi300", "region": "Asia-Pacific", "name": "CSI 300", "market": "China · Shanghai and Shenzhen", "yahoo": "000300.SS", "currency": "CNY", "symbol": "¥",
     "wiki": "https://en.wikipedia.org/wiki/CSI_300_Index",
     "official": "https://www.csindex.com.cn/en/indices/index-detail/000300",
     "proxy": "510300.SS", "proxyNote": "Yahoo Finance has little history for the CSI 300 index itself, so its level is tracked through the Huatai-PineBridge CSI 300 ETF (510300.SS)."},
    {"id": "nikkei225", "region": "Asia-Pacific", "name": "Nikkei 225", "market": "Japan · Tokyo Stock Exchange", "yahoo": "^N225", "currency": "JPY", "symbol": "¥",
     "wiki": "https://en.wikipedia.org/wiki/Nikkei_225",
     "official": "https://indexes.nikkei.co.jp/en/nkave/index/component"},
    {"id": "euronext100", "region": "Europe", "name": "Euronext 100", "market": "Europe · Euronext (Paris, Amsterdam, Milan…)", "yahoo": "^N100", "currency": "EUR", "symbol": "€",
     "wiki": "https://en.wikipedia.org/wiki/Euronext_100",
     "official": "https://live.euronext.com/en/product/indices/FR0003502079-XPAR"},
    # ---- 15 further markets (generic Wikipedia table reader, see cons_generic) ----
    {"id": "ftse100", "name": "FTSE 100", "market": "United Kingdom · London Stock Exchange", "region": "Europe", "yahoo": "^FTSE", "currency": "GBP", "symbol": "£",
     "wiki": "https://en.wikipedia.org/wiki/FTSE_100_Index", "official": "https://www.lseg.com/en/ftse-russell/indices/uk", "suffix": ".L", "min": 90},
    {"id": "dax", "name": "DAX 40", "market": "Germany · Xetra, Frankfurt", "region": "Europe", "yahoo": "^GDAXI", "currency": "EUR", "symbol": "€",
     "wiki": "https://en.wikipedia.org/wiki/DAX", "official": "https://www.stoxx.com/index/DAX", "suffix": ".DE", "min": 35},
    {"id": "cac40", "name": "CAC 40", "market": "France · Euronext Paris", "region": "Europe", "yahoo": "^FCHI", "currency": "EUR", "symbol": "€",
     "wiki": "https://en.wikipedia.org/wiki/CAC_40", "official": "https://live.euronext.com/en/product/indices/FR0003500008-XPAR", "suffix": ".PA", "min": 35},
    {"id": "ftsemib", "name": "FTSE MIB", "market": "Italy · Borsa Italiana, Milan", "region": "Europe", "yahoo": "FTSEMIB.MI", "currency": "EUR", "symbol": "€",
     "wiki": "https://en.wikipedia.org/wiki/FTSE_MIB", "official": "https://www.borsaitaliana.it/borsa/indici/indici-in-continua/dettaglio.html?indexCode=FTSEMIB", "suffix": ".MI", "min": 35},
    {"id": "ibex35", "name": "IBEX 35", "market": "Spain · Bolsa de Madrid", "region": "Europe", "yahoo": "^IBEX", "currency": "EUR", "symbol": "€",
     "wiki": "https://en.wikipedia.org/wiki/IBEX_35", "official": "https://www.bolsasymercados.es/bme-exchange/en/Indices/Ibex", "suffix": ".MC", "min": 30},
    {"id": "smi", "name": "SMI", "market": "Switzerland · SIX Swiss Exchange", "region": "Europe", "yahoo": "^SSMI", "currency": "CHF", "symbol": "CHF ",
     "wiki": "https://en.wikipedia.org/wiki/Swiss_Market_Index", "official": "https://www.six-group.com/en/market-data/indices/switzerland/blue-chip.html", "suffix": ".SW", "min": 18},
    {"id": "aex", "name": "AEX", "market": "Netherlands · Euronext Amsterdam", "region": "Europe", "yahoo": "^AEX", "currency": "EUR", "symbol": "€",
     "wiki": "https://en.wikipedia.org/wiki/AEX_index", "official": "https://live.euronext.com/en/product/indices/NL0000000107-XAMS", "suffix": ".AS", "min": 22},
    {"id": "omxs30", "name": "OMX Stockholm 30", "market": "Sweden · Nasdaq Stockholm", "region": "Europe", "yahoo": "^OMX", "currency": "SEK", "symbol": "kr ",
     "wiki": "https://en.wikipedia.org/wiki/OMX_Stockholm_30", "official": "https://indexes.nasdaqomx.com/Index/Overview/OMXS30", "suffix": ".ST", "min": 25},
    {"id": "hsi", "name": "Hang Seng", "market": "Hong Kong · HKEX", "region": "Asia-Pacific", "yahoo": "^HSI", "currency": "HKD", "symbol": "HK$",
     "wiki": "https://en.wikipedia.org/wiki/Hang_Seng_Index", "official": "https://www.hsi.com.hk/eng/indexes/all-indexes/hsi", "suffix": ".HK", "min": 70, "numeric": 4},
    {"id": "asx200", "name": "S&P/ASX 200", "market": "Australia · ASX", "region": "Asia-Pacific", "yahoo": "^AXJO", "currency": "AUD", "symbol": "A$",
     "wiki": "https://en.wikipedia.org/wiki/S%26P/ASX_200", "official": "https://www.spglobal.com/spdji/en/indices/equity/sp-asx-200/", "suffix": ".AX", "min": 180},
    {"id": "nifty50", "name": "Nifty 50", "market": "India · National Stock Exchange", "region": "Asia-Pacific", "yahoo": "^NSEI", "currency": "INR", "symbol": "₹",
     "wiki": "https://en.wikipedia.org/wiki/NIFTY_50", "official": "https://www.niftyindices.com/indices/equity/broad-based-indices/NIFTY--50", "suffix": ".NS", "min": 45},
    {"id": "sti", "name": "Straits Times Index", "market": "Singapore · SGX", "region": "Asia-Pacific", "yahoo": "^STI", "currency": "SGD", "symbol": "S$",
     "wiki": "https://en.wikipedia.org/wiki/Straits_Times_Index", "official": "https://www.sgx.com/indices/products/sti", "suffix": ".SI", "min": 25},
    {"id": "tsx60", "name": "S&P/TSX 60", "market": "Canada · Toronto Stock Exchange", "region": "Americas", "yahoo": "^GSPTSE", "currency": "CAD", "symbol": "C$",
     "wiki": "https://en.wikipedia.org/wiki/S%26P/TSX_60", "official": "https://www.spglobal.com/spdji/en/indices/equity/sp-tsx-60-index/", "suffix": ".TO", "min": 55,
     "levelNote": "Level shown: S&P/TSX Composite, the broad Toronto index (Yahoo has no history for the TSX 60)."},
    {"id": "ibovespa", "name": "Ibovespa", "market": "Brazil · B3, São Paulo", "region": "Americas", "yahoo": "^BVSP", "currency": "BRL", "symbol": "R$",
     "wiki": "https://en.wikipedia.org/wiki/List_of_companies_listed_on_B3", "wiki2": "https://en.wikipedia.org/wiki/%C3%8Dndice_Bovespa", "official": "https://www.b3.com.br/en_us/market-data-and-indices/indices/broad-indices/ibovespa.htm", "suffix": ".SA", "min": 60},
    {"id": "ipc", "name": "S&P/BMV IPC", "market": "Mexico · Bolsa Mexicana de Valores", "region": "Americas", "yahoo": "^MXX", "currency": "MXN", "symbol": "MX$",
     "wiki": "https://en.wikipedia.org/wiki/S%26P/BMV_IPC", "official": "https://www.spglobal.com/spdji/en/indices/equity/sp-bmv-ipc/", "suffix": ".MX", "min": 30},
]
FX = {c: f"EUR{c}=X" for c in ["USD", "CNY", "JPY", "GBP", "CHF", "SEK", "NOK", "DKK", "HKD", "AUD", "INR", "SGD", "CAD", "BRL", "MXN", "KRW", "TWD", "ZAR", "PLN", "ILS"]}  # local currency units per euro
SYM = {"USD": "$", "EUR": "€", "JPY": "¥", "CNY": "¥", "GBP": "£", "GBp": "p", "NOK": "kr ", "CHF": "CHF ", "DKK": "kr ", "SEK": "kr ",
       "HKD": "HK$", "AUD": "A$", "INR": "₹", "SGD": "S$", "CAD": "C$", "BRL": "R$", "MXN": "MX$"}
DIAG = {}  # per-index diagnostics, written to data/markets/build-log.json


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


TICK_COLS = ("ticker", "symbol", "code", "epic", "stock code", "nse symbol", "asx code")
NAME_COLS = ("company", "name", "constituent", "security", "issuer")
SECTOR_COLS = ("sector", "industry", "gics", "icb", "segment")


def norm_ticker(raw, ix):
    t = re.sub(r"\[.*?\]", "", str(raw)).strip()
    t = re.sub(r"^(SEHK|HKEX|LSE|NSE|BSE|ASX|TSX|SGX|BMV|B3|BMAD|BIT|XETRA|FWB|SIX|OMX|Euronext|EPA|AMS)\s*:\s*", "", t, flags=re.I)
    if ix.get("suffix") == ".ST":
        t = re.sub(r"\s+([A-Z])$", r"-\1", t)
    t = t.split()[0] if t.split() else ""
    if not t or t.lower() == "nan":
        return None
    if ix.get("numeric"):
        m = re.search(r"\d+", t)
        return (m.group(0).lstrip("0").zfill(ix["numeric"]) + ix["suffix"]) if m else None
    suf = ix["suffix"]
    if t.upper().endswith(suf.upper()):
        return t[: -len(suf)].replace(".", "-") + suf
    if any(t.upper().endswith(x) for x in (".AS", ".PA", ".MI", ".MC", ".DE", ".SW", ".ST", ".BR", ".LS", ".IR", ".HE", ".CO", ".OL")) and suf != ".L":
        return t  # already carries an exchange suffix (e.g. a foreign listing)
    t = t.rstrip(".")
    if suf == ".L":
        t = t.replace(".", "-")
    elif suf in (".TO", ".ST", ".SA", ".MX"):
        t = t.replace(".", "-")
    return t + suf


def cons_generic(ix):
    """Find the constituents table: a ticker-like column, a name column, enough rows."""
    seen_heads = []
    for url in [ix["wiki"]] + ([ix["wiki2"]] if ix.get("wiki2") else []):
        for df in tables(url):
            heads = [" ".join(map(str, c)) if isinstance(c, tuple) else str(c) for c in df.columns]
            seen_heads.append(f"{len(df)} rows: " + " | ".join(heads)[:200])
            if len(df) < ix.get("min", 20) * 0.8:
                continue
            tc = next((c for c, h in zip(df.columns, heads) if any(k == h.lower().strip() or h.lower().startswith(k) for k in TICK_COLS)), None)
            nc = next((c for c, h in zip(df.columns, heads) if any(k in h.lower() for k in NAME_COLS) and c is not tc), None)
            if tc is None or nc is None:
                continue
            sc = next((c for c, h in zip(df.columns, heads) if any(k in h.lower() for k in SECTOR_COLS)), None)
            out, seen = [], set()
            for _, r in df.iterrows():
                t = norm_ticker(r[tc], ix)
                n = re.sub(r"\[.*?\]", "", str(r[nc])).strip()
                if t and t not in seen and n and n.lower() != "nan":
                    seen.add(t)
                    out.append({"t": t, "n": n, "s": re.sub(r"\[.*?\]", "", str(r[sc])).strip() if sc is not None and str(r[sc]) != "nan" else ""})
            if len(out) >= ix.get("min", 20) * 0.8:
                return out
    DIAG.setdefault(ix["id"], {})["tables"] = seen_heads[:12]
    raise RuntimeError(f"no constituents table found ({len(seen_heads)} tables seen)")


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
    due = [t for t in due if now - cache.get(t, {}).get("ts", 0) > TARGET_MAX_AGE_DAYS * 86400 or cache.get(t, {}).get("v") != 2][:TARGETS_PER_RUN]
    log(f"analyst data: refreshing {len(due)} of {len(tickers)} tickers")
    fails = 0
    for k, t in enumerate(due):
        try:
            info = yf.Ticker(t).info or {}
            cache[t] = {
                "ts": now, "v": 2,
                "cur": info.get("currency"), "fcur": info.get("financialCurrency"),
                "rev": clean(info.get("totalRevenue"), 0), "cash": clean(info.get("totalCash"), 0),
                "ni": clean(info.get("netIncomeToCommon"), 0), "emp": info.get("fullTimeEmployees"),
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
            members[ix["id"]] = CONS.get(ix["id"], cons_generic)(ix)
            DIAG.setdefault(ix["id"], {})["constituents"] = len(members[ix["id"]])
            log(f"{ix['name']}: {len(members[ix['id']])} constituents")
        except Exception as e:
            log(f"{ix['name']}: constituents FAILED ({e}); keeping previous list")
            DIAG.setdefault(ix["id"], {})["error"] = str(e)[:300]
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
    # Yahoo Finance stopped serving Sustainalytics scores (0 of 1,231 found on 30 Oct 2026); off unless FETCH_ESG=1.
    esg = refresh_esg(all_t, {}) if os.environ.get("FETCH_ESG") == "1" else load(esg_path, {})
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
            "count": len(members.get(ix["id"], [])), "note": note or ix.get("levelNote", ""), "region": ix.get("region", ""),
        })

    fx_now = {c: v[-1][1] for c, v in fx.items() if v}

    def to_eur(v, cur):
        if v is None or not cur:
            return None
        if cur == "EUR":
            return v
        if cur == "GBp":
            return v / 100 / fx_now["GBP"] if "GBP" in fx_now else None
        r = fx_now.get(cur)
        return v / r if r else None

    screener = {}
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
            row.update({"mcapE": clean(to_eur(c.get("mcap"), cur), 0), "revE": clean(to_eur(c.get("rev"), c.get("fcur") or cur), 0),
                        "cashE": clean(to_eur(c.get("cash"), c.get("fcur") or cur), 0), "niE": clean(to_eur(c.get("ni"), c.get("fcur") or cur), 0), "emp": c.get("emp")})
            e = esg.get(t, {})
            if e.get("tot") is not None:
                row.update({"esg": e["tot"], "esgE": e.get("e"), "esgS": e.get("s"), "esgG": e.get("g"), "cont": e.get("cont"), "esgPct": e.get("pct")})
            rows.append(row)
        rows.sort(key=lambda r: -(r.get("mcap") or 0))
        if not rows:
            continue
        for r in rows:
            if r["t"] in screener:
                screener[r["t"]]["ix"].append(ix["id"])
            else:
                screener[r["t"]] = {k: r.get(k) for k in ("t", "n", "s", "sym", "cur", "p", "r1d", "rytd", "r1y", "r5y", "mcapE", "revE", "cashE", "niE", "tm", "na")} | {"ix": [ix["id"]]}
        DIAG.setdefault(ix["id"], {}).update({"rows": len(rows), "priced": sum(1 for r in rows if r.get("p")), "targets": sum(1 for r in rows if r.get("tm")), "revenue": sum(1 for r in rows if r.get("revE"))})
        save(os.path.join(OUT, ix["id"] + ".json"), {"id": ix["id"], "name": ix["name"], "updated": today, "source": ix["wiki"], "rows": rows})
        save(os.path.join(OUT, ix["id"] + "-hist.json"), {"id": ix["id"], "updated": today, "series": hist})
        log(f"{ix['name']}: wrote {len(rows)} rows, {sum(1 for r in rows if 'tm' in r)} with analyst targets")

    try:
        covered_history(today)
    except Exception as e:
        log("covered history failed:", e)
    save(os.path.join(OUT, "screener.json"), {"updated": today, "fields": "revE, cashE, niE, mcapE in euros at today's rates; returns as decimals",
                                              "rows": [{k: v for k, v in r.items() if v is not None} for r in screener.values()]})
    save(os.path.join(OUT, "build-log.json"), {"updated": today, "indices": DIAG})
    save(os.path.join(OUT, "indices.json"), {"updated": today, "fx": fx, "fxNote": "Month-end euro reference rates from Yahoo Finance (local currency per €1).", "indices": out_ix})
    if not out_ix:
        log("No index data at all: check the network or Yahoo Finance.")
        sys.exit(1)


if __name__ == "__main__":
    main()
