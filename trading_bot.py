import os
import time
import logging
import pytz
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta

# ══════════════════════════════════════════════
# הגדרות מערכת וניהול סיכונים
# ══════════════════════════════════════════════
ALPACA_API_KEY = os.environ.get("ALPACA_API_KEY", "").strip()
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "").strip()
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

HEADERS = {
    "APCA-API-KEY-ID": ALPACA_API_KEY,
    "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
    "accept": "application/json"
}

MIN_PRICE = 2.0
MAX_PRICE = 20.0
RISK_PER_TRADE = 12.0      
MAX_FLOAT = 100_000_000    
COOLDOWN_MINUTES = 120     
LOG_FILE = "trade_log.csv"

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("C_RANK_PRO")

alerted_symbols = {}

# ══════════════════════════════════════════════
# פונקציות סינון ויציבות (yfinance)
# ══════════════════════════════════════════════
def check_filters_and_spread(sym):
    """בדיקת ספרייד ונתוני פלואוט בצורה בטוחה"""
    try:
        ticker = yf.Ticker(sym)
        # שימוש ב-fast_info למניעת קריסות
        fast = ticker.fast_info
        
        # 1. פילטר ספרייד - שלא יעלה על 1% מחיר מניה
        ask = fast.get('ask', 0)
        bid = fast.get('bid', 0)
        price = fast.get('last_price', 0)
        
        if price > 0 and ask > 0 and bid > 0:
            spread_pct = (ask - bid) / price
            if spread_pct > 0.01:
                log.info(f"⏩ {sym} נפסלה: Spread גבוה מדי ({spread_pct:.2%})")
                return False
        
        # 2. פילטר פלואוט (נתון פונדמנטלי)
        float_shares = ticker.info.get('floatShares', float('inf'))
        if float_shares > MAX_FLOAT:
            log.info(f"⏩ {sym} נפסלה: Float כבד מדי ({float_shares:,})")
            return False
            
        return True
    except Exception as e:
        log.warning(f"שגיאה בבדיקת פילטרים עבור {sym}: {e}")
        return False

def is_market_crashing():
    try:
        spy = yf.Ticker("SPY")
        hist = spy.history(period="1d")
        if hist.empty: return False
        open_p = hist['Open'].iloc[-1]
        current_p = hist['Close'].iloc[-1]
        drop = ((current_p - open_p) / open_p) * 100
        return drop < -1.5
    except:
        return False

def market_status():
    ny_tz = pytz.timezone("US/Eastern")
    ny_time = datetime.now(ny_tz)
    if ny_time.weekday() > 4: return False
    market_open = (ny_time.hour > 9) or (ny_time.hour == 9 and ny_time.minute >= 30)
    market_close = ny_time.hour < 16
    return market_open and market_close

def send_telegram(msg):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try: requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    except: pass

def log_trade(data):
    try:
        df = pd.DataFrame([data])
        df.to_csv(LOG_FILE, mode='a', header=not os.path.exists(LOG_FILE), index=False)
    except Exception as e:
        log.error(f"Error logging to CSV: {e}")

# ══════════════════════════════════════════════
# מנוע הניתוח: פריצה, נר סגור, ווליום ו-ATR
# ══════════════════════════════════════════════
def get_top_gainers():
    url = "https://data.alpaca.markets/v1beta1/screener/stocks/movers?market_type=stocks"
    try:
        res = requests.get(url, headers=HEADERS).json()
        return [s['symbol'] for s in res.get('gainers', []) if s['percent_change'] > 5]
    except:
        return []

def analyze_stock_pro(sym):
    try:
        # משיכת נרות 5 דקות מהיום
        start_date = datetime.now(pytz.timezone("US/Eastern")).replace(hour=4, minute=0, second=0).strftime('%Y-%m-%dT%H:%M:%SZ')
        url = f"https://data.alpaca.markets/v2/stocks/bars?symbols={sym}&timeframe=5Min&start={start_date}&limit=1000&feed=iex"
        
        response = requests.get(url, headers=HEADERS).json()
        if 'bars' not in response or not response['bars'].get(sym): return None
        
        df = pd.DataFrame(response['bars'][sym])
        df.rename(columns={'t': 'Datetime', 'o': 'Open', 'h': 'High', 'l': 'Low', 'c': 'Close', 'v': 'Volume'}, inplace=True)
        df['Datetime'] = pd.to_datetime(df['Datetime']).dt.tz_convert('US/Eastern')
        df.set_index('Datetime', inplace=True)
        
        if len(df) < 20: return None
        
        # 1. חישוב שיא פרה-מרקט
        premarket = df.between_time('04:00', '09:30')
        if premarket.empty: return None
        pm_high = premarket['High'].max()
        
        # נתונים הנוכחיים (נר סגור אחרון ונר קודם)
        last_close = df['Close'].iloc[-1]
        prev_close = df['Close'].iloc[-2]
        last_volume = df['Volume'].iloc[-1]
        
        if last_close < MIN_PRICE or last_close > MAX_PRICE: return None
        
        # 2. אישור נר סגור (Candle Close Confirmation)
        is_breaking = (last_close > pm_high) and (prev_close <= pm_high)
        is_extended = last_close > (pm_high * 1.10) # פסילה אם ברחה מעל 10%
        
        if not is_breaking or is_extended: return None
        
        # 3. אישור ווליום חזק (Volume Confirmation)
        avg_volume = df['Volume'].rolling(20).mean().iloc[-1]
        if last_volume < (avg_volume * 2): return None
        
        # 4. פילטר תנועתיות (ATR בסיסי על נרות תוך יומיים)
        high_low = df['High'] - df['Low']
        high_cp = (df['High'] - df['Close'].shift()).abs()
        low_cp = (df['Low'] - df['Close'].shift()).abs()
        tr = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1)
        atr = tr.rolling(14).mean().iloc[-1]
        if atr < 0.15: return None
        
        # חישוב כמויות וסטופ לוס (4% קשיח)
        stop_loss = round(last_close * 0.96, 2)
        risk_amount = last_close - stop_loss
        shares = int(RISK_PER_TRADE / risk_amount) if risk_amount > 0 else 0
        cost = round(shares * last_close, 2)
        target = round(last_close * 1.10, 2)
        
        return {
            "symbol": sym, "price": last_close, "pm_high": round(pm_high, 2),
            "stop": stop_loss, "shares": shares, "cost": cost, "target": target,
            "atr": round(atr, 2), "volume_mult": round(last_volume / avg_volume, 1)
        }
    except:
        return None

# ══════════════════════════════════════════════
# לולאת ריצה ראשית
# ══════════════════════════════════════════════
def run_scanner():
    log.info("🚀 C RANK Pro Engine is starting up...")
    send_telegram("🟢 *C RANK Pro Active* | המערכת עלתה לאוויר ב-Railway ומאזינה לשוק.")
    
    while True:
        try:
            if not market_status():
                log.info("השוק סגור כעת. ממתין 5 דקות...")
                time.sleep(300)
                continue
                
            if is_market_crashing():
                log.warning("השוק במגמת קריסה חדה. השהיית סיגנלים ל-15 דקות.")
                time.sleep(900)
                continue
                
            gainers = get_top_gainers()
            for sym in gainers:
                # בדיקת Cooldown במילון השרת
                if sym in alerted_symbols:
                    if datetime.now() - alerted_symbols[sym] < timedelta(minutes=COOLDOWN_MINUTES):
                        continue
                        
                # פילטרים מהירים (Float + Spread)
                if not check_filters_and_spread(sym):
                    continue
                    
                # ניתוח פריצה מורכב
                setup = analyze_stock_pro(sym)
                if setup:
                    alerted_symbols[sym] = datetime.now()
                    
                    # רישום ב-Database המקומי
                    setup['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    log_trade(setup)
                    
                    # שליחת הודעת צלף לטלגרם
                    msg = (f"🦅 *C RANK A+ SETUP: {setup['symbol']}*\n"
                           f"━━━━━━━━━━━━━━━━━\n"
                           f"🔥 *CONFIRMED BREAKOUT (נר נסגר)*\n\n"
                           f"💰 *כניסה (Close):* `${setup['price']}`\n"
                           f"🛑 *סטופ לוס (4%):* `${setup['stop']}`\n"
                           f"🎯 *יעד (10%):* `${setup['target']}`\n"
                           f"━━━━━━━━━━━━━━━━━\n"
                           f"📦 *מניות לקנייה:* {setup['shares']}\n"
                           f"💵 *עלות פוזיציה:* `${setup['cost']}`\n"
                           f"⚡ *עוצמת ווליום:* {setup['volume_mult']}x\n"
                           f"📊 *מדד תנודתיות ATR:* {setup['atr']}")
                    
                    send_telegram(msg)
                    log.info(f"💥 ALERT SENT FOR {sym}")
                    
            time.sleep(60) # סריקה כל דקה
            
        except Exception as e:
            log.error(f"שגיאה בלולאה הראשית: {e}")
            time.sleep(60)

if __name__ == "__main__":
    run_scanner()
