"""
DAY-S-BOT v12.0 — MASTER SWING EDITION (1-3 Days Hold)
==============================================================
מטרה: מעבר מ-250$ ל-1000$ דרך מהלכים של 15%-30% ביומיים.
"""

import os, requests, logging, time
import pandas as pd
import yfinance as yf
from datetime import datetime

# ══════════════════════════════════════════════
# הגדרות מערכת וניהול סיכונים
# ══════════════════════════════════════════════
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
WATCHLIST_FILE = "daily_watchlist.csv"

ACCOUNT_SIZE = 250.0
RISK_PER_TRADE = ACCOUNT_SIZE * 0.10  # מסכנים 25$ בעסקה
MIN_PRICE, MAX_PRICE = 2.0, 30.0

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("SwingMaster")

def send_telegram(msg):
    if not TOKEN or not CHAT_ID: return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    except Exception as e:
        log.error(f"Telegram error: {e}")

# ══════════════════════════════════════════════
# מנוע האנליזה (Swing Logic)
# ══════════════════════════════════════════════
def analyze_swing_setup(sym):
    try:
        ticker = yf.Ticker(sym)
        # משיכת נתונים שעתיים אחורה כדי לזהות מגמה של ימים
        df = ticker.history(period="1mo", interval="1h", timeout=10)
        if df.empty or len(df) < 20: return None
        
        # מחיר נוכחי
        price = round(float(df["Close"].iloc[-1]), 2)
        if price < MIN_PRICE or price > MAX_PRICE: return None
        
        # אינדיקטורים של סווינג
        ema20 = float(df["Close"].ewm(span=20, adjust=False).mean().iloc[-1])
        
        # RSI לזיהוי עוצמה (רוצים בין 55 ל-75 - עוצמה מתפרצת אבל לא קנויה מדי)
        delta = df["Close"].diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs.iloc[-1]))
        
        # חישוב שינוי מ-2 ימי המסחר האחרונים (בערך 14 שעות מסחר)
        change_2days = ((price / df["Close"].iloc[-14]) - 1) * 100

        # קריטריונים נוקשים לכניסה
        is_uptrend = price > ema20
        is_strong = change_2days > 4.0  # עלתה לפחות 4% ביומיים האחרונים
        has_momentum = 55 < rsi < 85

        if is_uptrend and is_strong and has_momentum:
            return {
                "price": price,
                "ema": round(ema20, 2),
                "rsi": round(rsi, 1),
                "change_2d": round(change_2days, 1)
            }
        return None
    except Exception as e:
        log.warning(f"Error analyzing {sym}: {e}")
        return None

# ══════════════════════════════════════════════
# חישוב יעדים וניהול טרייד (Risk/Reward)
# ══════════════════════════════════════════════
def calculate_trade(price):
    # בסווינג נותנים למניה מקום לנשום - סטופ של 8%
    stop_loss = round(price * 0.92, 2)
    risk_per_share = price - stop_loss
    
    # יעדים אגרסיביים ל-1-3 ימים
    target_1 = round(price + (risk_per_share * 2), 2)  # יחס 1:2 (~16% רווח)
    target_2 = round(price + (risk_per_share * 3.5), 2) # יחס 1:3.5 (~28% רווח)
    
    # כמה מניות לקנות בלי לפוצץ את החשבון
    shares = int(RISK_PER_TRADE / risk_per_share)
    cost = shares * price
    if cost > (ACCOUNT_SIZE * 0.8): # לא נכנסים ביותר מ-80% מהתיק למניה אחת
        shares = int((ACCOUNT_SIZE * 0.8) / price)
        
    return {"stop": stop_loss, "t1": target_1, "t2": target_2, "shares": shares, "cost": round(shares * price, 2)}

# ══════════════════════════════════════════════
# הריצה הראשית
# ══════════════════════════════════════════════
def run():
    log.info("🚀 מתחיל סריקת סווינג...")
    
    if not os.path.exists(WATCHLIST_FILE):
        log.info("Watchlist עדיין לא קיים. מחכה לסורק.")
        return

    try:
        df_w = pd.read_csv(WATCHLIST_FILE)
        watchlist = df_w["symbol"].tolist()
    except:
        log.error("שגיאה בקריאת קובץ הרשימה.")
        return
        
    found_any = False
    for sym in watchlist:
        setup = analyze_swing_setup(sym)
        
        if setup:
            trade = calculate_trade(setup["price"])
            
            msg = (f"🦅 *SWING ALERT: {sym}*\n"
                   f"━━━━━━━━━━━━━━━━━\n"
                   f"💰 *כניסה:* `${setup['price']}`\n"
                   f"🛑 *סטופ לוס קשיח:* `${trade['stop']}`\n"
                   f"🎯 *יעד 1 (חצי כמות):* `${trade['t1']}`\n"
                   f"🎯 *יעד 2 (שארית):* `${trade['t2']}`\n"
                   f"━━━━━━━━━━━━━━━━━\n"
                   f"📦 כמות קנייה מומלצת: {trade['shares']} מניות\n"
                   f"💵 עלות כוללת: ${trade['cost']}\n"
                   f"📈 מומנטום קונים (RSI): {setup['rsi']}\n"
                   f"⏱ *זמן החזקה צפוי: 1 עד 3 ימים*\n"
                   f"⚠️ *לא למכור ברווח קטן - תן למניה לעבוד!*")
            
            send_telegram(msg)
            found_any = True
            time.sleep(2) # מניעת חסימות מטלגרם
            
    if not found_any:
        log.info("אין כרגע עסקאות שעומדות בקריטריונים לסווינג.")

if __name__ == "__main__":
    run()
