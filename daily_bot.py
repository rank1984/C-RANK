import os
import time
from datetime import datetime
from telegram import Bot
import yfinance as yf

# ─────────────────────────────────────────────
# הגדרות
# ─────────────────────────────────────────────
TOKEN   = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not TOKEN or not CHAT_ID:
    raise ValueError("❌ חסרים TELEGRAM_TOKEN או TELEGRAM_CHAT_ID")

bot = Bot(token=TOKEN)

# ─────────────────────────────────────────────
# שליחת הודעה
# ─────────────────────────────────────────────
def send(msg):
    MAX = 4000
    for chunk in [msg[i:i+MAX] for i in range(0, len(msg), MAX)]:
        try:
            bot.send_message(chat_id=CHAT_ID, text=chunk, parse_mode='HTML')
            time.sleep(0.3)
        except Exception as e:
            print(f"שגיאת טלגרם: {e}")

# ─────────────────────────────────────────────
# משיכת נתונים מ-YFINANCE
# ─────────────────────────────────────────────
def fetch_candidates():

    tickers = [
        "AAPL","TSLA","NVDA","AMD","AMZN","MSFT","META","GOOGL",
        "SPY","QQQ","SOFI","PLTR","RIVN","NIO","LCID","MARA",
        "RIOT","COIN","HOOD","RBLX","SNAP","UBER","LYFT","DKNG",
        "F","AAL","CCL","PBR","XPEV","NKLA","BB","OPEN"
    ]

    combined = {}

    for ticker in tickers:
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="2d")

            if hist.empty or len(hist) < 2:
                continue

            price = float(hist["Close"].iloc[-1])
            prev  = float(hist["Close"].iloc[-2])
            change = ((price - prev) / prev) * 100
            volume = float(hist["Volume"].iloc[-1])

            combined[ticker] = {
                "price": price,
                "change": change,
                "volume": volume,
                "sources": ["yfinance"],
                "premarket_change": 0.0,
                "name": ticker
            }

        except Exception as e:
            print(f"שגיאה ב-{ticker}: {e}")

    return combined

# ─────────────────────────────────────────────
# חישוב יעדים
# ─────────────────────────────────────────────
def calculate_targets(price, change):
    v = abs(change)
    entry = round(price * 1.003, 2)

    if v >= 15:
        target, stop = round(entry * 1.15, 2), round(entry * 0.955, 2)
    elif v >= 8:
        target, stop = round(entry * 1.10, 2), round(entry * 0.965, 2)
    elif v >= 3:
        target, stop = round(entry * 1.07, 2), round(entry * 0.972, 2)
    else:
        target, stop = round(entry * 1.05, 2), round(entry * 0.975, 2)

    risk   = entry - stop
    reward = target - entry
    rr     = round(reward / risk, 1) if risk > 0 else 0
    expected = round((target - price) / price * 100, 1)

    return entry, target, stop, rr, expected

# ─────────────────────────────────────────────
# דירוג AI
# ─────────────────────────────────────────────
def ai_score(change, volume, price, sources, premarket_change=0):
    momentum      = min(35, abs(change) * 2.5)
    vol_score     = min(30, (volume / 1_000_000) * 30)
    price_score   = 25 if 5 <= price <= 40 else (12 if price < 5 else 18)
    multi_bonus   = 8  if len(sources) >= 1 else 0
    pm_bonus      = min(12, abs(premarket_change) * 0.6)

    total = momentum + vol_score + price_score + multi_bonus + pm_bonus
    return min(100, round(total))

# ─────────────────────────────────────────────
# בניית דוח ושליחה
# ─────────────────────────────────────────────
def send_morning_report(candidates):

    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    total_scanned = len(candidates)

    stocks = []

    for ticker, data in candidates.items():

        price  = data["price"]
        change = data["change"]
        volume = data["volume"]

        # פילטרים
        if not (1 <= price <= 50):
            continue
        if volume < 100_000:
            continue

        entry, target, stop, rr, expected = calculate_targets(price, change)
        score = ai_score(change, volume, price, data["sources"])

        if score < 40 or rr < 1.5:
            continue

        stocks.append({
            "ticker": ticker,
            "price": price,
            "change": change,
            "entry": entry,
            "target": target,
            "stop": stop,
            "score": score,
            "expected": expected,
            "rr": rr,
            "volume": volume
        })

    stocks.sort(key=lambda x: x["expected"], reverse=True)
    top = stocks[:10]

    msg = f"📊 <b>דוח מניות — {now_str}</b>\n\n"

    if not top:
        msg += "⚠️ לא נמצאו מניות מתאימות כרגע"
        send(msg)
        return

    for i, s in enumerate(top, 1):
        icon = "🔥" if s["score"] >= 75 else ("⚡" if s["score"] >= 55 else "📈")

        msg += (
            f"{i}. {icon} <b>{s['ticker']}</b>\n"
            f"מחיר: ${s['price']} → כניסה: ${s['entry']}\n"
            f"יעד: ${s['target']} (+{s['expected']}%)\n"
            f"סטופ: ${s['stop']} | RR: {s['rr']}\n"
            f"שינוי: {s['change']:.1f}% | נפח: {int(s['volume']):,}\n\n"
        )

    send(msg)

# ─────────────────────────────────────────────
if __name__ == "__main__":
    print("מריץ בוט...")
    candidates = fetch_candidates()
    print(f"נמצאו {len(candidates)} מניות")
    send_morning_report(candidates)
    print("סיום")
