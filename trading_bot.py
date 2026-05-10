"""
DAY-S-BOT v11.0 — SWING AGGRESSIVE MODE (1-3 Days Holding)
==============================================================
מטרה: הגדלת תקציב מ-250$ ל-1000$ באמצעות מהלכים של ימים.
טווח מחירים: 2$ - 30$.
"""

import os, csv, time, logging, json
from datetime import datetime, timezone, timedelta
import requests
import pandas as pd
import numpy as np
import yfinance as yf

# ══════════════════════════════════════════════
# CONFIG & RISK MANAGEMENT
# ══════════════════════════════════════════════
TOKEN    = os.environ.get("TELEGRAM_BOT_TOKEN","").strip()
CHAT_ID  = os.environ.get("TELEGRAM_CHAT_ID","").strip()

ACCOUNT_SIZE = float(os.environ.get("ACCOUNT_SIZE", 250.0))
RISK_PER_TRADE = ACCOUNT_SIZE * 0.10  # סיכון אגרסיבי של 10% מהתיק לעסקה
MIN_PRICE, MAX_PRICE = 2.0, 30.0

WATCHLIST_FILE = "daily_watchlist.csv"
SIGNALS_LOG    = "signals_log.csv"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("v11.0-Swing")

# ══════════════════════════════════════════════
# TIME HELPERS
# ══════════════════════════════════════════════
def get_ny_time():
    utc = datetime.now(timezone.utc)
    return utc - timedelta(hours=4) # NY Summer Time

def il_str():
    utc = datetime.now(timezone.utc)
    return (utc + timedelta(hours=3)).strftime("%H:%M")

# ══════════════════════════════════════════════
# DATA & SCORING (SWING LOGIC)
# ══════════════════════════════════════════════
def get_swing_bars(sym):
    try:
        ticker = yf.Ticker(sym)
        # לוקחים אינטרוול של שעה כדי לזהות מגמה של ימים
        df = ticker.history(period="1mo", interval="1h", timeout=10)
        if df.empty or len(df) < 30: return pd.DataFrame()
        df.columns = [c.lower() for c in df.columns]
        return df.dropna()
    except Exception as e:
        log.warning(f"Error fetching {sym}: {e}")
        return pd.DataFrame()

def calculate_swing_score(df):
    price = round(float(df["close"].iloc[-1]), 2)
    if price < MIN_PRICE or price > MAX_PRICE: return None

    # ממוצע נע 20 - אם המחיר מעליו, המגמה הרב-יומית חיובית
    ema20 = float(df["close"].ewm(span=20, adjust=False).mean().iloc[-1])
    
    # RSI שעתי - מחפשים עוצמה (מעל 55)
    d = df["close"].diff()
    gain = d.clip(lower=0).rolling(14).mean()
    loss = (-d.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs.iloc[-1]))

    # ווליום יחסי - האם נכנס כסף "חכם"?
    vol_recent = df["volume"].iloc[-8:].mean() # ממוצע של יום מסחר אחרון
    vol_avg = df["volume"].iloc[-40:].mean()
    vol_ratio = vol_recent / vol_avg if vol_avg > 0 else 1

    # ציון סופי
    score = 40
    if price > ema20: score += 25
    if rsi > 55:      score += 15
    if vol_ratio > 1.2: score += 20
    
    # ATR למדידת תנודתיות (לצורך סטופ לוס)
    atr = float(df["close"].rolling(14).std().iloc[-1])

    return {
        "price": price, "rsi": round(rsi, 1), "ema20": round(ema20, 2),
        "vol_pct": int(vol_ratio * 100), "score": score, "atr": atr
    }

def get_swing_levels(price, atr):
    # ב-Swing נותנים למניה יותר אוויר: סטופ של 6-8%
    stop_dist = max(atr * 2.5, price * 0.07) 
    stop = round(price - stop_dist, 2)
    t1 = round(price + (stop_dist * 2.5), 2) # יעד ראשון: ~15-20%
    t2 = round(price + (stop_dist * 4.5), 2) # יעד שני: ~30%+
    
    qty = int(RISK_PER_TRADE / stop_dist)
    if qty * price > ACCOUNT_SIZE * 0.8: # הגבלה שלא לקנות יותר מדי
        qty = int((ACCOUNT_SIZE * 0.8) / price)
        
    return {"stop": stop, "t1": t1, "t2": t2, "qty": max(1, qty), "risk": round(qty * stop_dist, 2)}

# ══════════════════════════════════════════════
# MESSAGING
# ══════════════════════════════════════════════
def send_telegram(msg):
    if not TOKEN or not CHAT_ID: return
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", 
                      json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    except: pass

def swing_msg(sym, m, lv):
    return (
        f"🎯 *SWING SIGNAL: {sym}* (1-3 Days)\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"💰 כניסה: `${m['price']}`\n"
        f"🎯 יעד 1: `${lv['t1']}` (+{round((lv['t1']/m['price']-1)*100,1)}%)\n"
        f"🎯 יעד 2: `${lv['t2']}` (+{round((lv['t2']/m['price']-1)*100,1)}%)\n"
        f"🛑 סטופ: `${lv['stop']}`\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"📦 כמות: {lv['qty']} מניות\n"
        f"📊 ציון עוצמה: {m['score']}/100\n"
        f"📈 מגמה: {'חיובית (Above EMA20)' if m['price'] > m['ema20'] else 'דשדוש'}\n"
        f"🕐 זמן: {il_str()} IL\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"⚠️ *למסחר של ימים - לא למכור מייד!*"
    )

# ══════════════════════════════════════════════
# MAIN RUNNER
# ══════════════════════════════════════════════
def run():
    log.info("🤖 מפעיל בוט סווינג אגרסיבי...")
    
    # טעינת רשימת מעקב מהסורק
    watchlist = []
    if os.path.exists(WATCHLIST_FILE):
        with open(WATCHLIST_FILE, "r") as f:
            reader = csv.DictReader(f)
            watchlist = [row["symbol"] for row in reader]
    
    if not watchlist:
        log.warning("Watchlist ריק. מחכה לסורק.")
        return

    sent_today = [] # למנוע כפילויות

    for sym in watchlist:
        df = get_swing_bars(sym)
        if df.empty: continue
        
        m = calculate_swing_score(df)
        if not m or m["score"] < 75: continue # רק מניות חזקות באמת
        
        lv = get_swing_levels(m["price"], m["atr"])
        
        # איתות ירוק
        if sym not in sent_today:
            msg = swing_msg(sym, m, lv)
            send_telegram(msg)
            sent_today.append(sym)
            log.info(f"✅ סיגנל נשלח: {sym}")
            time.sleep(1)

if __name__ == "__main__":
    run()
