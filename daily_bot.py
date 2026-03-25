import os
import time
from datetime import datetime
import yfinance as yf
from telegram import Bot

# ─────────────────────────────────────────────
# הגדרות
# ─────────────────────────────────────────────
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
    raise ValueError("❌ חסרים TELEGRAM_TOKEN או TELEGRAM_CHAT_ID")

bot = Bot(token=TELEGRAM_TOKEN)

# ─────────────────────────────────────────────
# שליחת הודעה
# ─────────────────────────────────────────────
def send(msg):
    MAX = 4000
    for chunk in [msg[i:i+MAX] for i in range(0, len(msg), MAX)]:
        try:
            bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=chunk, parse_mode='HTML')
            time.sleep(0.3)
        except Exception as e:
            print(f"שגיאת טלגרם: {e}")

# ─────────────────────────────────────────────
# משיכת מניות מ-YFinance
# ─────────────────────────────────────────────
def fetch_candidates():
    # רשימת מניות לדוגמה (ניתן להרחיב)
    tickers_list = [
        "AAPL","TSLA","NVDA","AMD","AMZN","MSFT","META","GOOGL",
        "SPY","QQQ","SOFI","PLTR","RIVN","NIO","LCID","MARA",
        "RIOT","COIN","HOOD","RBLX","SNAP","UBER","LYFT","DKNG"
    ]

    combined = {}

    for ticker in tickers_list:
        try:
            t = yf.Ticker(ticker)
            info = t.info
            price = info.get("regularMarketPrice") or 0
            change = info.get("regularMarketChangePercent") or 0
            volume = info.get("volume") or 0
            name = info.get("shortName") or ticker

            if price <= 0:
                continue

            combined[ticker] = {
                "price": price,
                "change": change,
                "volume": volume,
                "sources": ["yfinance"],
                "premarket_change": 0.0,
                "name": name,
            }

        except Exception as e:
            print(f"שגיאה במניה {ticker}: {e}")

    print(f"CANDIDATES: {combined}")
    return combined

# ─────────────────────────────────────────────
# חישוב יעדים
# ─────────────────────────────────────────────
def calculate_targets(price, change):
    v = abs(change)
    entry = round(price * 1.003, 2)
    if v >= 15:
        target, stop = round(entry * 1.15,2), round(entry * 0.955,2)
    elif v >= 8:
        target, stop = round(entry * 1.10,2), round(entry * 0.965,2)
    elif v >= 3:
        target, stop = round(entry * 1.07,2), round(entry * 0.972,2)
    else:
        target, stop = round(entry * 1.05,2), round(entry * 0.975,2)
    risk = entry - stop
    reward = target - entry
    rr = round(reward/risk,1) if risk>0 else 0
    expected = round((target-price)/price*100,1)
    return entry, target, stop, rr, expected

# ─────────────────────────────────────────────
# דירוג AI
# ─────────────────────────────────────────────
def ai_score(change, volume, price, sources, premarket_change=0):
    momentum = min(35, abs(change)*2.5)
    vol_score = min(30, (volume/1_000_000)*30)
    price_score = 25 if 5 <= price <= 50 else (12 if price < 5 else 18)
    multi_bonus = 8 if len(sources)>=2 else 0
    pm_bonus = min(12, abs(premarket_change)*0.6)
    total = momentum + vol_score + price_score + multi_bonus + pm_bonus
    return min(100, round(total))

# ─────────────────────────────────────────────
# בניית דוח ושליחה
# ─────────────────────────────────────────────
def send_morning_report(candidates):
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    total_scanned = len(candidates)

    stocks = []
    reasons_filtered = {"מחיר מחוץ לטווח":0,"נפח נמוך":0,"דירוג נמוך":0}

    for ticker,data in candidates.items():
        price = data["price"]
        change = data["change"]
        volume = data["volume"]

        # פילטרים
        if not (1<=price<=50):
            reasons_filtered["מחיר מחוץ לטווח"]+=1
            continue
        if volume < 100_000:
            reasons_filtered["נפח נמוך"]+=1
            continue

        entry, target, stop, rr, expected = calculate_targets(price, change)
        score = ai_score(change, volume, price, data["sources"])

        if score<40 or rr<1.5:
            reasons_filtered["דירוג נמוך"]+=1
            continue

        stocks.append({
            "ticker": ticker,
            "name": data["name"],
            "price": price,
            "change": change,
            "entry": entry,
            "target": target,
            "stop": stop,
            "score": score,
            "expected": expected,
            "rr": rr,
            "volume": volume,
            "sources": data["sources"]
        })

    stocks.sort(key=lambda x: x["expected"], reverse=True)
    top = stocks[:10]

    # ── בניית הודעה
    msg = f"📊 <b>דוח מניות — {now_str}</b>\n"
    msg += f"<i>נסרקו: {total_scanned} מניות | עברו פילטר: {len(stocks)}</i>\n"
    msg += "━━━━━━━━━━━━━━━━━━\n\n"

    if not top:
        msg += "⚠️ <b>לא נמצאו מניות מתאימות.</b>\n"
        for reason,count in reasons_filtered.items():
            if count>0:
                msg += f"  • {reason}: {count}\n"
        send(msg)
        return

    for i,s in enumerate(top,1):
        icon = "🔥" if s["score"]>=75 else ("⚡" if s["score"]>=55 else "📈")
        vol_fmt = f"{int(s['volume']):,}"
        msg += (
            f"{i}. {icon} <b>{s['ticker']}</b>\n"
            f"   💰 מחיר: ${s['price']}  → כניסה: ${s['entry']}\n"
            f"   🎯 יעד: ${s['target']}  (+{s['expected']}%)\n"
            f"   🛑 סטופ: ${s['stop']}  |  סיכוי/סיכון: 1:{s['rr']}\n"
            f"   📊 שינוי: {s['change']:+.1f}%  | נפח: {vol_fmt}\n\n"
        )

    msg += "━━━━━━━━━━━━━━━━━━\n💡 <b>טיפ:</b> זה לא ייעוץ השקעות — תמיד כבד את הסטופ לוס"
    send(msg)
    print(f"נשלחו {len(top)} מניות מתוך {len(stocks)} שעברו פילטר")

# ─────────────────────────────────────────────
if __name__=="__main__":
    print(f"מריץ בוט — {datetime.now().strftime('%H:%M:%S')}")
    # Force test הודעה כדי לוודא שהחיבור לטלגרם תקין
    send("✅ בדיקת חיבור טלגרם — הבוט פעיל!")
    candidates = fetch_candidates()
    send_morning_report(candidates)
    print("סיום.")
