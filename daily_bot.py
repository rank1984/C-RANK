import os
import requests
import yfinance as yf
from datetime import datetime

# ─────────────────────────────────────────────
# הגדרות - שימוש בשמות מה-GitHub Secrets
# ─────────────────────────────────────────────
TOKEN    = os.getenv("TELEGRAM_TOKEN")
CHAT_ID  = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram_msg(msg):
    """שליחה פשוטה וישירה דרך ה-API של טלגרם"""
    if not TOKEN or not CHAT_ID:
        print("❌ חסר TOKEN או CHAT_ID")
        return
    
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"}
    
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code == 200:
            print("✅ הודעה נשלחה בהצלחה לטלגרם!")
        else:
            print(f"❌ שגיאת טלגרם: {r.text}")
    except Exception as e:
        print(f"❌ תקלה בשליחה: {e}")

# ─────────────────────────────────────────────
# משיכת נתונים עם yfinance
# ─────────────────────────────────────────────
def get_stock_data():
    # רשימת מניות למעקב (אפשר להוסיף עוד)
    tickers = ["TSLA", "NVDA", "AAPL", "AMD", "MSFT", "META", "GOOGL", "PLTR", "MARA", "RIOT"]
    print(f"מושך נתונים עבור {len(tickers)} מניות...")
    
    results = []
    for symbol in tickers:
        try:
            ticker = yf.Ticker(symbol)
            # קבלת נתוני יום מסחר אחרון
            hist = ticker.history(period="2d")
            if len(hist) < 2: continue
            
            current_price = hist['Close'].iloc[-1]
            prev_price = hist['Close'].iloc[-2]
            change_pct = ((current_price - prev_price) / prev_price) * 100
            volume = hist['Volume'].iloc[-1]

            # פילטר בסיסי: רק מניות שזזו מעל 1%
            if abs(change_pct) > 1.0:
                results.append({
                    "symbol": symbol,
                    "price": round(current_price, 2),
                    "change": round(change_pct, 2),
                    "volume": volume
                })
        except Exception as e:
            print(f"שגיאה במניה {symbol}: {e}")
    return results

# ─────────────────────────────────────────────
# ניהול הדוח
# ─────────────────────────────────────────────
def main():
    print(f"🚀 מתחיל סריקה: {datetime.now().strftime('%H:%M:%S')}")
    
    stocks = get_stock_data()
    
    if not stocks:
        send_telegram_msg("🔎 הסריקה הסתיימה: לא נמצאו מניות מעניינות כרגע.")
        return

    msg = f"📊 <b>דוח מניות יומי - {datetime.now().strftime('%d/%m/%Y')}</b>\n\n"
    for s in stocks:
        icon = "🔥" if s['change'] > 0 else "📉"
        msg += f"{icon} <b>{s['symbol']}</b>\n"
        msg += f"מחיר: ${s['price']} | שינוי: {s['change']}% \n\n"
    
    msg += "━━━━━━━━━━━━━━\n💡 נשלח אוטומטית ע״י C-RANK"
    send_telegram_msg(msg)

if __name__ == "__main__":
    main()
