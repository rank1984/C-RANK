"""
DAY-S-BOT — Premarket Scanner
רץ 06:15 ET. בונה daily_watchlist.csv.
"""
import csv, time, logging
from datetime import datetime
import pytz
import yfinance as yf

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("premarket")

NY_TZ          = pytz.timezone('America/New_York')
MIN_PRICE      = 2.0
MAX_PRICE      = 30.0
MIN_GAP_PCT    = 4.0
MAX_WATCHLIST  = 20
WATCHLIST_FILE = "daily_watchlist.csv"

CORE_LIST = [
    "MARA","RIOT","CLSK","CIFR","WULF","MSTR",
    "SOFI","HOOD","UPST","AFRM","NU",
    "RIVN","NIO","LCID",
    "SOUN","BBAI","IONQ","PLTR",
    "NKLA","PLUG","CHPT","OPEN","PTON","GME",
]

SEED_UNIVERSE = [
    "MARA","RIOT","CLSK","CIFR","WULF","MSTR","HUT","BTBT","COIN",
    "SOFI","HOOD","UPST","AFRM","NU","LC","DAVE",
    "RIVN","NIO","LCID","GOEV","NKLA","SOLO",
    "SOUN","BBAI","IONQ","PLTR",
    "AGEN","GOVX","SAVA","HIMS","ARQT","PRTA",
    "PLUG","CHPT","CLNE","FCEL","BE","SPWR","RUN",
    "GME","AMC","CLOV","WKHS","KOSS",
    "OPEN","PTON","VIEW","SPCE",
    "TLRY","SNDL","CGC",
]

BAD_TICKERS = {
    "TQQQ","SQQQ","SPXS","UVXY","SVXY","VXX",
    "SPY","QQQ","DIA","IWM","GLD","SLV",
    "SOXL","SOXS","LABU","LABD","FNGU","FNGD",
}

def is_weekday():
    return datetime.now(NY_TZ).weekday() < 5

def today_str():
    return datetime.now(NY_TZ).strftime("%Y-%m-%d")

def get_premarket_data(sym):
    try:
        t          = yf.Ticker(sym)
        fi         = t.fast_info
        pre_price  = getattr(fi, 'pre_market_price', None)
        prev_close = getattr(fi, 'previous_close', None)
        if not pre_price or not prev_close or prev_close == 0:
            return None
        gap_pct    = (pre_price - prev_close) / prev_close * 100
        hist       = t.history(period="5d", interval="1d")
        avg_vol    = int(hist["Volume"].mean()) if not hist.empty else 0
        return {
            "symbol":     sym,
            "pre_price":  round(pre_price, 2),
            "prev_close": round(prev_close, 2),
            "gap_pct":    round(gap_pct, 2),
            "avg_volume": avg_vol,
        }
    except Exception as e:
        log.debug(f"{sym}: {e}")
        return None

def score_candidate(c):
    gap       = min(c["gap_pct"], 50)
    vol_score = min(c["avg_volume"] / 1_000_000, 1.0) * 100
    price     = c["pre_price"]
    p_score   = 100 if 5 <= price <= 15 else (70 if price < 5 else 80)
    return round(min(gap*0.4 + vol_score*0.3 + p_score*0.2 + min(gap*10,100)*0.1, 100), 1)

def build_watchlist():
    seen, universe = set(), []
    for s in SEED_UNIVERSE:
        if s not in seen and s not in BAD_TICKERS:
            seen.add(s); universe.append(s)

    candidates = []
    for sym in universe:
        data = get_premarket_data(sym)
        if not data: continue
        if not (MIN_PRICE <= data["pre_price"] <= MAX_PRICE): continue
        if data["gap_pct"] < MIN_GAP_PCT: continue
        data["score"] = score_candidate(data)
        candidates.append(data)
        log.info(f"  ✅ {sym}: ${data['pre_price']} gap={data['gap_pct']:+.1f}% score={data['score']}")
        time.sleep(0.25)

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:MAX_WATCHLIST]

def save_watchlist(candidates, today):
    fields = ["date","symbol","pre_price","prev_close","gap_pct","avg_volume","score"]
    with open(WATCHLIST_FILE, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for c in candidates:
            w.writerow({"date": today, **{k: c[k] for k in fields if k != "date"}})

def save_fallback(today):
    fields = ["date","symbol","pre_price","prev_close","gap_pct","avg_volume","score"]
    with open(WATCHLIST_FILE, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for sym in CORE_LIST:
            w.writerow({"date":today,"symbol":sym,"pre_price":0,
                        "prev_close":0,"gap_pct":0,"avg_volume":0,"score":0})

def run():
    if not is_weekday():
        log.info("🔴 סוף שבוע — דולג"); return
    today = today_str()
    log.info(f"🚀 Premarket Scanner — {today}")
    candidates = build_watchlist()
    if candidates:
        save_watchlist(candidates, today)
        log.info(f"📋 {len(candidates)} מניות נשמרו")
    else:
        save_fallback(today)
        log.info("⚠️ Fallback — CORE_LIST נשמר")

if __name__ == "__main__":
    run()
