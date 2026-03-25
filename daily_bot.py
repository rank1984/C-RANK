import os
import requests
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta

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
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=10)

def get_market_context():
    """בודק את מצב הנאסדאק כרגע"""
    qqq = yf.Ticker("QQQ").history(period="2d")
    change = ((qqq['Close'].iloc[-1] - qqq['Close'].iloc[-2]) / qqq['Close'].iloc[-2]) * 100
    if change > 0.5: return f"🟢 שוק חזק ({change:+.1f}%) - אישור כניסה מלא"
    if change < -0.5: return f"🔴 שוק חלש ({change:+.1f}%) - זהירות כפולה!"
    return f"🟡 שוק יציב ({change:+.1f}%)"

def analyze_stock(symbol, hist, sector):
    curr, prev = hist.iloc[-1], hist.iloc[-2]
    gap = ((curr['Open'] - prev['Close']) / prev['Close']) * 100
    change = ((curr['Close'] - prev['Close']) / prev['Close']) * 100
    rvol = curr['Volume'] / hist['Volume'].tail(10).mean()
    
    # חישוב RSI פשוט
    delta = hist['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rsi = 100 - (100 / (1 + (gain/loss))).iloc[-1]

    # נתוני Float (במיליונים)
    info = yf.Ticker(symbol).info
    float_shares = info.get('floatShares', 500_000_000) / 1_000_000
    short_pct = info.get('shortPercentOfFloat', 0) * 100

    # RR דינמי
    stop_pct = 0.06 if abs(change) > 8 else 0.04
    target_pct = 0.15 if abs(change) > 8 else 0.10
    
    entry = round(curr['Close'] * 1.003, 2)
    
    score = 40
    tags = []
    if gap > 3: score += 20; tags.append("🚀 Gap")
    if rvol > 2.5: score += 20; tags.append("📊 RVOL")
    if float_shares < 50: score += 10; tags.append("💎 LowFloat")
    if short_pct > 15: score += 10; tags.append("🩳 Squeeze")

    return {
        "symbol": symbol, "score": min(score, 100), "price": round(curr['Close'], 2),
        "gap": round(gap, 1), "rvol": round(rvol, 1), "rsi": round(rsi, 1),
        "entry": entry, "target": round(entry*(1+target_pct), 2), "stop": round(entry*(1-stop_pct), 2),
        "tags": tags, "sector": sector, "change": round(change, 1), "float": round(float_shares, 1)
    }

def main():
    market_status = get_market_context()
    all_res = []
    sector_heat = {}

    for sector, tickers in SECTORS.items():
        count = 0
        for s in tickers:
            try:
                res = analyze_stock(s, yf.Ticker(s).history(period="20d"), sector)
                all_res.append(res)
                if res['change'] > 2: count += 1
            except: continue
        sector_heat[sector] = count

    top_picks = sorted(all_res, key=lambda x: x['score'], reverse=True)[:8]
    
    # שמירה ליומן
    pd.DataFrame(top_picks).to_csv('trade_journal.csv', mode='a', header=not os.path.exists('trade_journal.csv'), index=False)

    msg = f"🛡️ <b>C-RANK ELITE REPORT</b>\n"
    msg += f"📊 <b>מצב שוק:</b> {market_status}\n"
    msg += f"📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"
    msg += f"━━━━━━━━━━━━━━━━━━\n\n"

    for s in top_picks:
        heat = "🔥" if sector_heat[s['sector']] >= 3 else ""
        msg += f"<b>{s['symbol']}</b> {heat} | ציון: {s['score']}\n"
        msg += f"💡 {' | '.join(s['tags'])}\n"
        msg += f"📊 Gap: {s['gap']}% | RVOL: {s['rvol']}x | Float: {s['float']}M\n"
        msg += f"🟢 כניסה: <b>${s['entry']}</b> | 🎯 יעד: <b>${s['target']}</b>\n"
        msg += f"🛑 סטופ: ${s['stop']}\n\n"

    msg += "━━━━━━━━━━━━━━━━━━\n💡 <i>כניסה רק מעל מחיר ה-Entry בגרף 5 דקות.</i>"
    send_telegram_msg(msg)

if __name__ == "__main__":
    main()
