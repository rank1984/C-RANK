import os, csv, time, logging
from datetime import datetime, timezone, timedelta
import requests
import pandas as pd
import yfinance as yf

TOKEN   = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

# התאמה מדויקת לדרישות שלך: מניות מ-2$ עד 30$
MIN_PRICE     = 2.0
MAX_PRICE     = 30.0  
MIN_GAP_PCT   = 2.0    
MIN_PM_VOL    = 50_000 # ווליום קריטי למניות קטנות
MAX_WATCHLIST = 15     # נתמקד רק ב-15 ההכי חמות

WATCHLIST_FILE = "daily_watchlist.csv"
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("premarket")

CORE = [
    "MARA","RIOT","CLSK","CIFR","WULF","SOFI","HOOD","UPST","AFRM","NU",
    "RIVN","NIO","LCID","SOUN","BBAI","IONQ","PLTR","NKLA","PLUG","CHPT",
    "OPEN","PTON","GME","AMC","BB","LUMN","XPEV","LI","TLRY","SNDL"
]

def get_ny():
    try:
        import pytz
        return datetime.now(pytz.timezone("America/New_York"))
    except:
        utc = datetime.now(timezone.utc)
        return utc - timedelta(hours=4) # קיץ

def today_str():
    return get_ny().strftime("%Y-%m-%d")

def scan_symbol(sym):
    try:
        t = yf.Ticker(sym)
        hist = t.history(period="5d", interval="1d")
        if len(hist) < 2: return None
        prev_close = float(hist["Close"].iloc[-2])
        
        pm = t.history(period="1d", interval="5m", prepost=True)
        if pm.empty: return None
        curr_price = float(pm["Close"].iloc[-1])
        pm_vol = int(pm["Volume"].sum())

        if curr_price < MIN_PRICE or curr_price > MAX_PRICE: return None
        if pm_vol < MIN_PM_VOL: return None

        gap = round((curr_price - prev_close) / prev_close * 100, 1)
        if gap < MIN_GAP_PCT: return None

        score = min(100, int(gap * 2 + (pm_vol / 100000)))
        
        return {
            "symbol": sym, "price": round(curr_price, 2), "prev_close": prev_close,
            "gap_pct": gap, "pm_vol": pm_vol, "pm_score": score, "date": today_str()
        }
    except:
        return None

def run():
    log.info("🚀 מתחיל סריקת פרי-מרקט למניות 2$-30$...")
    movers = []
    
    # חיפוש דינמי מ-Finviz לפרי-מרקט
    try:
        url = "https://finviz.com/screener.ashx?v=111&s=ta_topgainers&f=sh_price_u30,sh_price_o2,sh_avgvol_o200"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=10)
        from html.parser import HTMLParser
        class TickerParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.tickers, self._in_ticker = [], False
            def handle_starttag(self, tag, attrs):
                if tag == "a" and dict(attrs).get("class", "").startswith("screener-link-primary"):
                    self._in_ticker = True
            def handle_data(self, data):
                if self._in_ticker and data.strip().isupper() and len(data.strip()) <= 5:
                    self.tickers.append(data.strip())
                self._in_ticker = False
        parser = TickerParser()
        parser.feed(resp.text)
        universe = list(set(CORE + parser.tickers[:30]))
    except Exception as e:
        universe = CORE

    for sym in universe:
        res = scan_symbol(sym)
        if res: movers.append(res)
        time.sleep(0.2)

    movers.sort(key=lambda x: x["pm_score"], reverse=True)
    final = movers[:MAX_WATCHLIST]

    if final:
        df = pd.DataFrame(final)
        df.to_csv(WATCHLIST_FILE, index=False)
        
        msg = f"🌅 *Premarket Scanner - רשימה מוכנה!*\n━━━━━━━━━━━━━━━━━\n"
        for i, m in enumerate(final[:10], 1):
            msg += f"*{i}. {m['symbol']}* 📈 +{m['gap_pct']}% | ${m['price']} | Vol: {m['pm_vol']//1000}K\n"
        
        if TOKEN and CHAT_ID:
            requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})
        log.info(f"✅ נשמרו {len(final)} מניות ל-Watchlist.")

if __name__ == "__main__":
    run()
