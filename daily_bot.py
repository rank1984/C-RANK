import os
import time
import requests
from datetime import datetime
from telegram import Bot

TOKEN   = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
API_KEY = os.getenv("API_KEY")
MODE    = os.getenv("MODE", "live_loop")

if not TOKEN or not CHAT_ID or not API_KEY:
    raise ValueError("חסרים משתנים: TOKEN, CHAT_ID, API_KEY")

bot = Bot(token=TOKEN)

alerted_entry = {}
active_trades = {}

def send(msg):
    MAX = 4000
    for chunk in [msg[i:i+MAX] for i in range(0, len(msg), MAX)]:
        try:
            bot.send_message(chat_id=CHAT_ID, text=chunk, parse_mode='HTML')
            time.sleep(0.3)
        except Exception as e:
            print(f"שגיאת טלגרם: {e}")

def fetch_candidates():
    endpoints = {
        "gainers":   f"https://financialmodelingprep.com/api/v3/stock_market/gainers?apikey={API_KEY}",
        "actives":   f"https://financialmodelingprep.com/api/v3/stock_market/actives?apikey={API_KEY}",
        "premarket": f"https://financialmodelingprep.com/api/v4/pre-post-market-change?apikey={API_KEY}",
    }
    combined = {}
    for source, url in endpoints.items():
        try:
            r = requests.get(url, timeout=8)
            if r.status_code != 200:
                continue
            data = r.json()
            if not isinstance(data, list):
                continue
            for s in data:
                ticker = s.get("symbol", "")
                if not ticker or len(ticker) > 5:
                    continue
                price  = float(s.get("price", 0) or 0)
                change = float(str(s.get("changesPercentage", "0")).replace("%", "") or 0)
                volume = float(s.get("volume", 0) or 0)
                if ticker not in combined:
                    combined[ticker] = {"price": price, "change": change,
                                        "volume": volume, "sources": [],
                                        "premarket_change": 0,
                                        "name": s.get("name", ticker)}
                combined[ticker]["sources"].append(source)
                if source == "premarket":
                    combined[ticker]["premarket_change"] = change
        except Exception as e:
            print(f"שגיאה ב-{source}: {e}")
    return combined

def calculate_targets(price, change):
    v = abs(change)
    entry = round(price * 1.003, 2)
    if v >= 15:
        target, stop = round(entry * 1.15, 2), round(entry * 0.955, 2)
    elif v >= 8:
        target, stop = round(entry * 1.10, 2), round(entry * 0.965, 2)
    else:
        target, stop = round(entry * 1.07, 2), round(entry * 0.975, 2)
    rr = round((target - entry) / (entry - stop), 1) if entry > stop else 0
    expected = round((target - price) / price * 100, 1)
    return entry, target, stop, rr, expected

def ai_score(change, volume, price, sources, premarket_change=0):
    return min(100, round(
        min(35, abs(change) * 2) +
        min(30, (volume / 2_000_000) * 30) +
        (25 if 8 <= price <= 40 else (10 if price < 8 else 18)) +
        (10 if len(sources) >= 2 else 0) +
        min(10, abs(premarket_change) * 0.5)
    ))

def send_entry_alert(ticker, data, entry, target, stop, score, expected, rr):
    pm_str = f"\n🌅 פרי-מרקט:     <b>{data['premarket_change']:+.1f}%</b>" if data.get("premarket_change") else ""
    send(
        f"🚀 <b>כניסה מומלצת — {ticker}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 מחיר נוכחי:  <b>${data['price']}</b>\n"
        f"📥 נקודת כניסה: <b>${entry}</b>\n"
        f"🎯 יעד רווח:    <b>${target}</b>  (+{expected}%)\n"
        f"🛑 סטופ לוס:    <b>${stop}</b>\n"
        f"📊 דירוג AI:    <b>{score}/100</b>\n"
        f"⚖️  סיכוי/סיכון: <b>1:{rr}</b>\n"
        f"📈 שינוי היום:  <b>{data['change']:+.1f}%</b>{pm_str}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ <i>כבד תמיד את הסטופ לוס</i>"
    )

def send_exit_alert(ticker, reason, price, entry_price, pnl_pct):
    emoji  = "🏆" if pnl_pct > 0 else "🛑"
    result = f"✅ רווח של {pnl_pct:+.1f}%!" if pnl_pct > 0 else f"❌ הפסד של {pnl_pct:.1f}% — עצרת בזמן"
    send(
        f"{emoji} <b>צא מ-{ticker} עכשיו!</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📍 סיבה:         <b>{reason}</b>\n"
        f"💲 מחיר נוכחי:  <b>${price}</b>\n"
        f"📥 מחיר כניסה:  <b>${entry_price}</b>\n"
        f"📊 תוצאה:       <b>{result}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"המשך לעסקה הבאה 💪"
    )

def send_morning_report(candidates):
    stocks = []
    for ticker, data in candidates.items():
        price, change, volume = data["price"], data["change"], data["volume"]
        if not (1 <= price <= 50) or volume < 300_000: continue
        if change > 80 or change < 4: continue
        entry, target, stop, rr, expected = calculate_targets(price, change)
        score = ai_score(change, volume, price, data["sources"], data.get("premarket_change", 0))
        if score < 55 or rr < 1.8: continue
        stocks.append({"ticker": ticker, "price": price, "entry": entry,
                        "target": target, "stop": stop, "score": score,
                        "expected": expected, "rr": rr})
    stocks.sort(key=lambda x: x["expected"], reverse=True)
    top = stocks[:8]
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    msg = (f"📊 <b>דוח בוקר — מניות מומלצות</b>\n"
           f"<i>{now} | $1–$50 | מיון לפי עלייה צפויה</i>\n"
           f"━━━━━━━━━━━━━━━━━━\n\n")
    if not top:
        msg += "⚠️ לא נמצאו מניות מתאימות כרגע.\nהבוט ממשיך לסרוק..."
        send(msg)
        return
    for i, s in enumerate(top, 1):
        icon = "🔥" if s["score"] >= 80 else ("⚡" if s["score"] >= 65 else "📈")
        msg += (f"{i}. {icon} <b>{s['ticker']}</b> | דירוג: <b>{s['score']}/100</b>\n"
                f"   💰 ${s['price']}  →  כניסה: ${s['entry']}\n"
                f"   🎯 יעד: <b>${s['target']}</b> (+{s['expected']}%)  "
                f"🛑 סטופ: ${s['stop']}\n\n")
    msg += ("━━━━━━━━━━━━━━━━━━\n"
            "💡 מקסימום 10% מהתיק לעסקה | כבד את הסטופ\n"
            "⚠️ <i>זה לא ייעוץ השקעות</i>")
    send(msg)

def run_morning_only():
    print("מצב GitHub Actions — דוח בוקר חד-פעמי")
    candidates = fetch_candidates()
    send_morning_report(candidates)
    print("הדוח נשלח.")

def run_live_loop():
    send(
        "🤖 <b>בוט הטריידינג הופעל!</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⏱ סריקה כל 5 דקות\n"
        "💹 טווח מחירים: $1–$50\n"
        "📡 gainers + actives + pre-market\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "ממתין להזדמנויות... 🎯"
    )
    scan_count = 0
    morning_sent = False
    while True:
        now = datetime.now()
        scan_count += 1
        if now.hour == 9 and now.minute < 5 and not morning_sent:
            candidates = fetch_candidates()
            send_morning_report(candidates)
            morning_sent = True
        if now.hour == 10:
            morning_sent = False
        candidates = fetch_candidates()
        for ticker, data in candidates.items():
            price, change, volume = data["price"], data["change"], data["volume"]
            if not (1 <= price <= 50) or volume < 300_000: continue
            if change > 80 or change < 2: continue
            entry, target, stop, rr, expected = calculate_targets(price, change)
            score = ai_score(change, volume, price, data["sources"], data.get("premarket_change", 0))
            if score >= 65 and rr >= 2.0 and ticker not in alerted_entry and ticker not in active_trades:
                alerted_entry[ticker] = entry
                active_trades[ticker] = {"entry": entry, "target": target,
                                          "stop": stop, "entry_price": price}
                send_entry_alert(ticker, data, entry, target, stop, score, expected, rr)
            if ticker in active_trades:
                tr = active_trades[ticker]
                if price >= tr["target"]:
                    pnl = round((price - tr["entry_price"]) / tr["entry_price"] * 100, 1)
                    send_exit_alert(ticker, "הגעת ליעד הרווח 🎯", price, tr["entry_price"], pnl)
                    del active_trades[ticker]
                elif price <= tr["stop"]:
                    pnl = round((price - tr["entry_price"]) / tr["entry_price"] * 100, 1)
                    send_exit_alert(ticker, "הגעת לסטופ לוס", price, tr["entry_price"], pnl)
                    del active_trades[ticker]
        if scan_count % 6 == 0:
            trades_str = "".join(f"\n  • {t}: כניסה ${tr['entry']} → יעד ${tr['target']}"
                                 for t, tr in active_trades.items()) or "\n  אין עסקאות פתוחות"
            send(f"📡 <b>דוח סריקה</b> — {now.strftime('%H:%M')}\n"
                 f"סריקות: {scan_count} | מניות: {len(candidates)}\n"
                 f"<b>עסקאות פתוחות:</b>{trades_str}")
        time.sleep(300)

if __name__ == "__main__":
    if MODE == "morning_only":
        run_morning_only()
    else:
        run_live_loop()
