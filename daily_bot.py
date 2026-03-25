import os
import requests
import yfinance as yf
import pandas as pd
from datetime import datetime

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
# לוגיקה פיננסית: חישוב יעד, סטופ ודירוג AI
# ─────────────────────────────────────────────
def calculate_metrics(price, change, volume):
    # מחיר כניסה: 0.3% מעל המחיר הנוכחי (כניסה בפריצה)
    entry = round(price * 1.003, 2)
    
    # יעד: שואפים ל-12% (לפי הבקשה שלך ל-10-15%)
    target = round(entry * 1.12, 2)
    
    # סטופ לוס: 4% מתחת לכניסה
    stop = round(entry * 0.96, 2)
    
    # חישוב RR (סיכוי מול סיכון)
    risk = entry - stop
    reward = target - entry
    rr = round(reward / risk, 1) if risk > 0 else 0
    expected_gain = round(((target - price) / price) * 100, 1)
    
    # דירוג AI פנימי (0-100)
    score = 0
    if 2 <= price <= 30: score += 25  # בונוס למניות זולות "Sweet Spot"
    if abs(change) > 5: score += 30    # בונוס על מומנטום חזק
    if volume > 1_000_000: score += 25 # בונוס על נזילות גבוהה
    if volume > 5_000_000: score += 10 # בונוס נוסף על ווליום חריג
    if change > 0: score += 10         # עדיפות למניות בעלייה
    
    return entry, target, stop, rr, expected_gain, min(score, 100)

# ─────────────────────────────────────────────
# סריקת מניות
# ─────────────────────────────────────────────
def scan_markets():
    # רשימה רחבה של מניות קטנות/בינוניות פופולריות למסחר יומי
    # (אפשר להחליף את זה בסורק שמביא את כל ה-Russell 2000 אם רוצים)
    watch_list = [
        "MARA", "RIOT", "SOFI", "PLTR", "NIO", "RIVN", "LCID", "FSR", "NKLA",
        "HOOD", "AMC", "GME", "BBAI", "SOUN", "SERV", "LUNR", "CLSK", "BTBT",
        "UPST", "AFRM", "RUN", "PLUG", "TLRY", "SNDL", "BITF", "WULF"
    ]
    
    print(f"סורק {len(watch_list)} מניות פוטנציאליות...")
    candidates = []

    for symbol in watch_list:
        try:
            t = yf.Ticker(symbol)
            # נתונים ליומיים כדי לחשב שינוי אחוזים מדויק
            hist = t.history(period="2d")
            if len(hist) < 2: continue
            
            price = hist['Close'].iloc[-1]
            prev_close = hist['Close'].iloc[-2]
            change = ((price - prev_close) / prev_close) * 100
            volume = hist['Volume'].iloc[-1]

            # --- פילטרים לפי הדרישות שלך ---
            if not (2 <= price <= 50): continue  # טווח מחירים
            if volume < 200_000: continue       # נפח מינימלי
            
            entry, target, stop, rr, exp, score = calculate_metrics(price, change, volume)
            
            candidates.append({
                "symbol": symbol,
                "price": round(price, 2),
                "change": round(change, 2),
                "volume": volume,
                "entry": entry,
                "target": target,
                "stop": stop,
                "rr": rr,
                "expected": exp,
                "score": score
            })
        except:
            continue
            
    # מיון לפי הדירוג הגבוה ביותר ופוטנציאל רווח
    candidates.sort(key=lambda x: (x['score'], x['expected']), reverse=True)
    return candidates[:10]

# ─────────────────────────────────────────────
# בניית הדוח המפורט
# ─────────────────────────────────────────────
def main():
    start_time = datetime.now().strftime("%H:%M")
    found_stocks = scan_markets()
    
    if not found_stocks:
        send_telegram_msg(f"⚠️ <b>סריקה {start_time}</b>\nלא נמצאו מניות שעומדות בקריטריונים כרגע.")
        return

    msg = f"🎯 <b>C-RANK: דוח מסחר יומי</b>\n"
    msg += f"📅 {datetime.now().strftime('%d/%m/%Y')} | ⏰ {start_time}\n"
    msg += f"━━━━━━━━━━━━━━━━━━\n\n"

    for i, s in enumerate(found_stocks, 1):
        icon = "🔥" if s['score'] > 70 else "⚡"
        vol_m = f"{s['volume']/1000000:.1f}M"
        
        msg += f"{i}. {icon} <b>{s['symbol']}</b> | דירוג AI: <b>{s['score']}</b>\n"
        msg += f"💰 מחיר: <code>${s['price']}</code> ({s['change']:+.1f}%)\n"
        msg += f"🟢 כניסה: <b>${s['entry']}</b>\n"
        msg += f"🎯 יעד: <b>${s['target']}</b> (+{s['expected']}%)\n"
        msg += f"🛑 סטופ: <code>${s['stop']}</code> | ⚖️ RR: 1:{s['rr']}\n"
        msg += f"📊 נפח: {vol_m} | תקציב: ~250$\n\n"

    msg += "━━━━━━━━━━━━━━━━━━\n"
    msg += "⚠️ <i>הנתונים מבוססים על יום המסחר האחרון. פעל באחריות.</i>"
    
    send_telegram_msg(msg)

if __name__ == "__main__":
    main()
