"""
DAY-S-BOT v11.1 — TEST & SWING MODE
==============================================================
"""

import os, csv, time, logging, requests
from datetime import datetime, timezone, timedelta
import pandas as pd
import numpy as np
import yfinance as yf

# ══════════════════════════════════════════════
# הגדרות וסודות (Secrets)
# ══════════════════════════════════════════════
TOKEN    = os.environ.get("TELEGRAM_BOT_TOKEN","").strip()
CHAT_ID  = os.environ.get("TELEGRAM_CHAT_ID","").strip()

ACCOUNT_SIZE = 250.0
RISK_PER_TRADE = ACCOUNT_SIZE * 0.10 
MIN_PRICE, MAX_PRICE = 2.0, 30.0

# שמות קבצים - לוודא התאמה לסורק שלך
WATCHLIST_FILE = "daily_watchlist.csv" 

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("v11.1")

# ══════════════════════════════════════════════
# פונקציות עזר
# ══════════════════════════════════════════════
def send_telegram(msg):
    if not TOKEN or not CHAT_ID: 
        print("❌ שגיאה: TOKEN או CHAT_ID לא מוגדרים ב-Secrets!")
        return
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        res = requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})
        if res.status_code != 200:
            print(f"❌ טלגרם החזיר שגיאה: {res.text}")
    except Exception as e:
        print(f"❌ שגיאה בשליחה: {e}")

def get_swing_bars(sym):
    try:
        ticker = yf.Ticker(sym)
        df = ticker.history(period="1mo", interval="1h", timeout=10)
        if df.empty: return pd.DataFrame()
        df.columns = [c.lower() for c in df.columns]
        return df.dropna()
    except: return pd.DataFrame()

# ══════════════════════════════════════════════
# לוגיקת סריקה וניתוח
# ══════════════════════════════════════════════
def analyze_stock(sym):
    df = get_swing_bars(sym)
    if len(df) < 20: return None
    
    price = round(float(df["close"].iloc[-1]), 2)
    ema20 = float(df["close"].ewm(span=20, adjust=False).mean().iloc[-1])
    
    # בבדיקה היום (ראשון) הציון יהיה נמוך כי אין מסחר, אז נוריד את הרף
    score = 50 
    if price > ema20: score += 30
    
    return {"price": price, "score": score, "ema": ema20}

# ══════════════════════════════════════════════
# הריצה הראשית
# ══════════════════════════════════════════════
def run():
    log.info("🚀 מתחיל הרצה...")
    
    # בדיקת חיבור מיידית לטלגרם
    send_telegram(f"🤖 הבוט התחיל לעבוד!\nזמן: {datetime.now().strftime('%H:%M:%S')}\nבודק מניות...")

    # אם הקובץ לא קיים, ניצור רשימה זמנית לבדיקה
    if not os.path.exists(WATCHLIST_FILE):
        log.warning(f"קובץ {WATCHLIST_FILE} לא נמצא. משתמש ברשימת דגימה.")
        watchlist = ["TSLA", "AAPL", "AMD", "NVDA"] # רשימת בדיקה
    else:
        try:
            df_w = pd.read_csv(WATCHLIST_FILE)
            watchlist = df_w["symbol"].tolist()
        except:
            watchlist = ["AAPL"]

    found_anything = False
    for sym in watchlist[:10]: # נבדוק רק את ה-10 הראשונות לבדיקה
        res = analyze_stock(sym)
        if res and res["score"] >= 70:
            msg = (f"🎯 *איתות בדיקה: {sym}*\n"
                   f"מחיר: ${res['price']}\n"
                   f"ציון: {res['score']}\n"
                   f"מגמה: {'חיובית' if res['price'] > res['ema'] else 'שלילית'}")
            send_telegram(msg)
            found_anything = True
            time.sleep(1)
            
    if not found_anything:
        send_telegram("✅ הסריקה הסתיימה. לא נמצאו הזדמנויות חריגות כרגע (שוק סגור).")

if __name__ == "__main__":
    run()
