import os
import requests
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import pytz # ספרייה לניהול אזורי זמן

# הגדרות
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SECTORS = {
    "Crypto": ["MARA", "RIOT", "CLSK", "WULF", "BITF", "BTBT", "COIN", "MSTR"],
    "EV/Tech": ["TSLA", "NIO", "RIVN", "LCID", "NVDA", "AMD", "PLTR", "SOUN"],
    "Meme/Penny": ["GME", "AMC", "HOOD", "TLRY", "LUNR", "BBAI"]
}

def get_times():
    """מחזירה את הזמן הנוכחי בישראל ובניו יורק"""
    tz_il = pytz.timezone('Asia/Jerusalem')
    tz_ny = pytz.timezone('America/New_York')
    return datetime.now(tz_il), datetime.now(tz_ny)

def send_telegram_msg(msg):
    if not TOKEN or not CHAT_ID: return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=10)

def analyze_stock(symbol, sector):
    # שימוש ב-1d עם prepost=True כדי לקבל נתונים חיים כולל טרום מסחר
    ticker = yf.Ticker(symbol)
    hist = ticker.history(period="2d", interval="5m", prepost=True)
    if hist.empty: return None
    
    info = ticker.info
    curr_price = hist['Close'].iloc[-1]
    prev_close = ticker.history(period="2d")['Close'].iloc[-2]
    
    gap = ((hist['Open'].iloc[-1] - prev_close) / prev_close) * 100
    rvol = hist['Volume'].tail(10).mean() / (info.get('averageVolume', 1) / 78) # ווליום יחסי ל-5 דקות
    
    float_shares = info.get('floatShares', 500_000_000) / 1_000_000
    short_pct = info.get('shortPercentOfFloat', 0) * 100

    # תוכנית פעולה: כניסה 0.5% מעל המחיר הנוכחי
    entry = round(curr_price * 1.005, 2)
    stop = round(curr_price * 0.96, 2) # סטופ קבוע 4%
    target = round(curr_price * 1.12, 2) # יעד 12%

    score = 50
    if gap > 2: score += 20
    if rvol > 2: score += 20
    if float_shares < 100: score += 10
    
    return {
        "symbol": symbol, "score": score, "price": round(curr_price, 2),
        "gap": round(gap, 1), "rvol": round(rvol, 1), "float": round(float_shares, 1),
        "entry": entry, "target": target, "stop": stop, "sector": sector
    }

def main():
    time_il, time_ny = get_times()
    
    # בדיקה אם אנחנו בשעות הפעילות (16:30-23:00 ישראל)
    is_live = "🔴 PRE-MARKET"
    if time_ny.hour >= 9 and time_ny.minute >= 30 or time_ny.hour > 9:
        if time_ny.hour < 16:
            is_live = "🟢 LIVE MARKET"

    all_res = []
    for sector, tickers in SECTORS.items():
        for s in tickers:
            try:
                res = analyze_stock(s, sector)
                if res and res['gap'] > 1: all_res.append(res)
            except: continue

    top_picks = sorted(all_res, key=lambda x: x['score'], reverse=True)[:8]

    msg = f"🛡️ <b>C-RANK ELITE: {is_live}</b>\n"
    msg += f"🕒 IL: {time_il.strftime('%H:%M')} | 🗽 NY: {time_ny.strftime('%H:%M')}\n"
    msg += f"━━━━━━━━━━━━━━━━━━\n\n"

    for s in top_picks:
        msg += f"<b>{s['symbol']}</b> (ציון: {s['score']})\n"
        msg += f"📊 Gap: {s['gap']}% | RVOL: {s['rvol']}x | Float: {s['float']}M\n"
        msg += f"⚡ <b>פעולה:</b> קנה בפריצה מעל <code>${s['entry']}</code>\n"
        msg += f"🎯 יעד: <code>${s['target']}</code> | 🛑 סטופ: <code>${s['stop']}</code>\n\n"

    msg += "━━━━━━━━━━━━━━━━━━\n💡 <i>המתן לאישור מחיר בגרף 5 דקות לפני כניסה.</i>"
    send_telegram_msg(msg)

if __name__ == "__main__":
    main()
