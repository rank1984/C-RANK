import os
import requests
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta

# ─────────────────────────────────────────────
# הגדרות ומשתני סביבה
# ─────────────────────────────────────────────
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram_msg(msg):
    if not TOKEN or not CHAT_ID: return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Error sending: {e}")

# ─────────────────────────────────────────────
# חישוב RSI (מדד חוזק יחסי)
# ─────────────────────────────────────────────
def calculate_rsi(data, window=14):
    delta = data.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

# ─────────────────────────────────────────────
# לוגיקה פיננסית משופרת
# ─────────────────────────────────────────────
def calculate_metrics(price, change, volume, rsi_value):
    entry = round(price * 1.003, 2)
    target = round(entry * 1.12, 2)
    stop = round(entry * 0.96, 2)
    risk = entry - stop
    reward = target - entry
    rr = round(reward / risk, 1) if risk > 0 else 0
    expected_gain = round(((target - price) / price) * 100, 1)
    
    # דירוג AI משופר (0-100)
    score = 0
    if 2 <= price <= 50: score += 20
    if abs(change) > 4: score += 25
    if volume > 1_000_000: score += 20
    
    # פילטר RSI:
    if 40 <= rsi_value <= 65: 
        score += 35  # אידיאלי לפריצה
    elif rsi_value > 75:
        score -= 20  # קניית יתר - מסוכן!
    elif rsi_value < 30:
        score += 15  # מכירת יתר - פוטנציאל לזינוק (Reversal)
        
    return entry, target, stop, rr, expected_gain, max(0, min(score, 100))

# ─────────────────────────────────────────────
# סריקה וניתוח
# ─────────────────────────────────────────────
def scan_markets():
    watch_list = [
        "MARA", "RIOT", "CLSK", "WULF", "PLTR", "SOFI", "NIO", "RIVN", 
        "LCID", "TSLA", "AMD", "NVDA", "TQQQ", "SQ", "PYPL", "HOOD", 
        "AMC", "GME", "BBAI", "SOUN", "LUNR", "TLRY", "BITF", "BTBT"
    ]
    
    candidates = []
    for symbol in watch_list:
        try:
            t = yf.Ticker(symbol)
            # מושכים 30 יום כדי לחשב RSI של 14 יום בצורה מדויקת
            hist = t.history(period="30d")
            if len(hist) < 20: continue
            
            # חישוב RSI
            rsi_series = calculate_rsi(hist['Close'])
            current_rsi = round(rsi_series.iloc[-1], 1)
            
            price = hist['Close'].iloc[-1]
            prev_close = hist['Close'].iloc[-2]
            change = ((price - prev_close) / prev_close) * 100
            volume = hist['Volume'].iloc[-1]

            if not (1.5 <= price <= 100): continue # טווח גמיש מעט יותר
            
            entry, target, stop, rr, exp, score = calculate_metrics(price, change, volume, current_rsi)
            
            candidates.append({
                "symbol": symbol, "price": round(price, 2), "change": round(change, 2),
                "volume": volume, "entry": entry, "target": target, "stop": stop,
                "rr": rr, "expected": exp, "score": score, "rsi": current_rsi
            })
        except: continue
            
    candidates.sort(key=lambda x: x['score'], reverse=True)
    return candidates[:10]

# ─────────────────────────────────────────────
# הרצה ראשית
# ─────────────────────────────────────────────
def main():
    # התאמת זמן לישראל (הוספת 3 שעות לזמן השרת)
    israel_time = datetime.now() + timedelta(hours=3)
    time_str = israel_time.strftime("%H:%M")
    date_str = israel_time.strftime("%d/%m/%Y")

    found_stocks = scan_markets()
    
    if not found_stocks:
        send_telegram_msg(f"⚠️ לא נמצאו מניות מתאימות ב-{time_str}")
        return

    msg = f"🎯 <b>C-RANK: דוח מסחר ישראל</b>\n"
    msg += f"📅 {date_str} | ⏰ {time_str} (שעון IL)\n"
    msg += f"━━━━━━━━━━━━━━━━━━\n\n"

    for i, s in enumerate(found_stocks, 1):
        # אייקון לפי RSI
        rsi_icon = "⚠️" if s['rsi'] > 70 else "✅"
        icon = "🔥" if s['score'] >= 85 else "⚡"
        
        msg += f"{i}. {icon} <b>{s['symbol']}</b> | ציון: <b>{s['score']}</b>\n"
        msg += f"💰 מחיר: <code>${s['price']}</code> ({s['change']:+.1f}%)\n"
        msg += f"📊 RSI: {s['rsi']} {rsi_icon}\n"
        msg += f"🟢 כניסה: <b>${s['entry']}</b> | 🎯 יעד: <b>${s['target']}</b>\n"
        msg += f"🛑 סטופ: <code>${s['stop']}</code> | ⚖️ RR: 1:{s['rr']}\n\n"

    msg += "━━━━━━━━━━━━━━━━━━\n"
    msg += "💡 <i>RSI מעל 70 מעיד על קניית יתר (סיכון גבוה).</i>"
    
    send_telegram_msg(msg)

if __name__ == "__main__":
    main()
