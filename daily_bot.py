import os
import requests
import yfinance as yf
import pandas as pd
from datetime import datetime
import pytz

# הגדרות
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SECTORS = {
    "Crypto": ["MARA", "RIOT", "CLSK", "WULF", "BITF", "BTBT", "COIN", "MSTR"],
    "EV/Tech": ["TSLA", "NIO", "RIVN", "LCID", "NVDA", "AMD", "PLTR", "SOUN"],
    "Meme/Penny": ["GME", "AMC", "HOOD", "TLRY", "LUNR", "BBAI"]
}

def send_telegram_msg(msg):
    if not TOKEN or not CHAT_ID: return
    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", 
                  json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"})

def calculate_rsi(series, window=14):
    if len(series) < window: return pd.Series([50] * len(series))
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def analyze_stock(symbol, sector, is_live=False):
    ticker = yf.Ticker(symbol)
    # בזמן אמת (16:50) נשתמש בנרות של דקה אחת לדיוק מקסימלי
    hist = ticker.history(period="2d", interval="1m" if is_live else "5m", prepost=True)
    if hist.empty: return None
    
    info = ticker.info
    curr_price = hist['Close'].iloc[-1]
    
    # זיהוי מחיר הפתיחה הרשמי (09:30 NY)
    regular_session = hist.between_time('09:30', '16:00')
    open_price = regular_session['Open'].iloc[0] if not regular_session.empty else curr_price
    
    rsi_vals = calculate_rsi(hist['Close'])
    rsi_val = round(rsi_vals.iloc[-1], 1)
    
    prev_close = ticker.history(period="2d")['Close'].iloc[-2]
    gap = round(((open_price - prev_close) / prev_close) * 100, 1)
    
    # RVOL: ווליום ב-15 הדקות האחרונות מול ממוצע דקה יומי
    rvol = round(hist['Volume'].tail(15).mean() / (info.get('averageVolume', 1) / 390), 2)
    
    return {
        "symbol": symbol, "price": round(curr_price, 2), "open": round(open_price, 2),
        "gap": gap, "rvol": rvol, "rsi": rsi_val,
        "float": round(info.get('floatShares', 0) / 1_000_000, 1),
        "sector": sector, "entry": round(curr_price * 1.005, 2), "stop": round(curr_price * 0.96, 2)
    }

def main():
    # סנכרון זמן מוחלט לניו יורק
    tz_ny = pytz.timezone('America/New_York')
    time_ny = datetime.now(tz_ny)
    
    # הגדרת "זמן זהב" - 20 דקות אחרי הפתיחה (09:50 בניו יורק)
    is_gold_time = time_ny.hour == 9 and time_ny.minute >= 45

    all_res = []
    for sector, tickers in SECTORS.items():
        for s in tickers:
            try:
                res = analyze_stock(s, sector, is_live=is_gold_time)
                if res: all_res.append(res)
            except: continue

    if is_gold_time:
        # פילטר צייד: מחזיקה גאפ, ווליום גבוה, מחיר מעל הפתיחה
        gold_signals = [s for s in all_res if s['price'] > s['open'] and s['rvol'] > 1.8 and s['gap'] > 2.5]
        
        if gold_signals:
            msg = f"🌟 <b>סיגנל זהב: כניסה בזמן אמת</b>\n"
            msg += f"🗽 NY: {time_ny.strftime('%H:%M')} | IL: {datetime.now(pytz.timezone('Asia/Jerusalem')).strftime('%H:%M')}\n"
            msg += f"━━━━━━━━━━━━━━━━━━\n\n"
            for s in gold_signals:
                rsi_warn = "⚠️" if s['rsi'] > 75 else "✅"
                msg += f"<b>{s['symbol']}</b> | RSI: {s['rsi']} {rsi_warn}\n"
                msg += f"📊 Gap: {s['gap']}% | RVOL: {s['rvol']}x\n"
                msg += f"🟢 <b>כניסה עכשיו: ${s['price']}</b>\n\n"
            send_telegram_msg(msg)
        
        # שמירת הנתונים כולל RSI ליומן
        df = pd.DataFrame(all_res)
        df['date'] = time_ny.strftime('%Y-%m-%d %H:%M')
        df.to_csv('trade_journal.csv', mode='a', header=not os.path.exists('trade_journal.csv'), index=False)
    
    else:
        # דוח אליט (16:30) - המפה ליום המסחר
        top_picks = sorted(all_res, key=lambda x: x['gap'], reverse=True)[:10]
        msg = f"🛡️ <b>C-RANK ELITE: דוח פתיחה</b>\n"
        msg += f"🕒 IL: 16:30 | 🗽 NY: 09:30\n━━━━━━━━━━━━━━━━━━\n\n"
        for s in top_picks:
            msg += f"<b>{s['symbol']}</b> | Gap: {s['gap']}% | RSI: {s['rsi']}\n"
            msg += f"🟢 פריצה מעל: <b>${s['entry']}</b>\n\n"
        msg += "━━━━━━━━━━━━━━━━━━\n💡 המתן לסיגנל הזהב ב-16:50 לאישור."
        send_telegram_msg(msg)

if __name__ == "__main__":
    main()
