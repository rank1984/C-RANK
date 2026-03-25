import os
import time
import requests
from datetime import datetime
from telegram import Bot

# ─────────────────────────────────────────────
# הגדרות
# ─────────────────────────────────────────────
TOKEN   = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
API_KEY = os.getenv("API_KEY")
MODE    = os.getenv("MODE", "morning_only")

if not TOKEN or not CHAT_ID or not API_KEY:
    raise ValueError("חסרים משתנים: TOKEN, CHAT_ID, API_KEY")

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
# משיכת נתונים — 4 מקורות + fallback
# ─────────────────────────────────────────────
def fetch_candidates():
    """
    מסדר עדיפות:
    1. gainers  — מניות שעלו הכי הרבה היום
    2. actives  — הכי נסחרות (נפח גבוה)
    3. losers   — לפעמים מניות losers חוזרות חזק
    4. premarket — נתוני פרי-מרקט
    fallback: אם כולם ריקים — מושך רשימה רחבה של מניות
    """
    endpoints = {
        "gainers":   f"https://financialmodelingprep.com/api/v3/stock_market/gainers?apikey={API_KEY}",
        "actives":   f"https://financialmodelingprep.com/api/v3/stock_market/actives?apikey={API_KEY}",
        "losers":    f"https://financialmodelingprep.com/api/v3/stock_market/losers?apikey={API_KEY}",
        "premarket": f"https://financialmodelingprep.com/api/v4/pre-post-market-change?apikey={API_KEY}",
    }

    combined = {}

    for source, url in endpoints.items():
        try:
            r = requests.get(url, timeout=10)
            if r.status_code != 200:
                print(f"API {source} returned {r.status_code}")
                continue
            data = r.json()
            if not isinstance(data, list) or len(data) == 0:
                print(f"API {source} returned empty or non-list")
                continue

            print(f"API {source}: {len(data)} מניות")

            for s in data:
                ticker = s.get("symbol", "")
                if not ticker or len(ticker) > 5 or "." in ticker:
                    continue

                price  = float(s.get("price", 0) or 0)
                raw_ch = str(s.get("changesPercentage", "0")).replace("%","").replace("+","").strip()
                try:
                    change = float(raw_ch)
                except:
                    change = 0.0

                volume = float(s.get("volume", 0) or 0)

                if price <= 0:
                    continue

                if ticker not in combined:
                    combined[ticker] = {
                        "price":            price,
                        "change":           change,
                        "volume":           volume,
                        "sources":          [],
                        "premarket_change": 0.0,
                        "name":             s.get("name", ticker),
                    }
                combined[ticker]["sources"].append(source)
                if source == "premarket":
                    combined[ticker]["premarket_change"] = change

        except Exception as e:
            print(f"שגיאה ב-{source}: {e}")

    # ── Fallback: אם כמעט ריק, מושך מניות ספציפיות ידועות ──
    if len(combined) < 5:
        print("מעט מדי נתונים — מפעיל fallback עם מניות ידועות")
        fallback_tickers = [
            "AAPL","TSLA","NVDA","AMD","AMZN","MSFT","META","GOOGL",
            "SPY","QQQ","SOFI","PLTR","RIVN","NIO","LCID","MARA",
            "RIOT","COIN","HOOD","RBLX","SNAP","UBER","LYFT","DKNG"
        ]
        batch = ",".join(fallback_tickers)
        try:
            url = f"https://financialmodelingprep.com/api/v3/quote/{batch}?apikey={API_KEY}"
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list):
                    for s in data:
                        ticker = s.get("symbol","")
                        price  = float(s.get("price", 0) or 0)
                        change = float(s.get("changesPercentage", 0) or 0)
                        volume = float(s.get("volume", 0) or 0)
                        if ticker and price > 0 and ticker not in combined:
                            combined[ticker] = {
                                "price": price, "change": change,
                                "volume": volume, "sources": ["fallback"],
                                "premarket_change": 0.0,
                                "name": s.get("name", ticker),
                            }
                    print(f"fallback הוסיף {len(data)} מניות")
        except Exception as e:
            print(f"שגיאת fallback: {e}")

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
        # שוק שקט / שינוי קטן — יעד שמרני
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
    vol_score     = min(30, (volume / 1_000_000) * 30)   # נורמל נמוך יותר
    price_score   = 25 if 5 <= price <= 40 else (12 if price < 5 else 18)
    multi_bonus   = 8  if len(sources) >= 2 else 0
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
    reasons_filtered = {"מחיר מחוץ לטווח": 0, "נפח נמוך": 0, "שינוי קיצוני": 0, "דירוג/RR נמוך": 0}

    for ticker, data in candidates.items():
        price  = data["price"]
        change = data["change"]
        volume = data["volume"]

        # ── פילטרים מרוחבים ──
        if not (1 <= price <= 50):
            reasons_filtered["מחיר מחוץ לטווח"] += 1
            continue
        if volume < 100_000:          # הורדנו מ-300K ל-100K
            reasons_filtered["נפח נמוך"] += 1
            continue
        if abs(change) > 80:
            reasons_filtered["שינוי קיצוני"] += 1
            continue
        # הסרנו מינימום שינוי — כולל מניות שקטות

        entry, target, stop, rr, expected = calculate_targets(price, change)
        score = ai_score(change, volume, price, data["sources"],
                         data.get("premarket_change", 0))

        if score < 40 or rr < 1.5:   # הורדנו מ-55/1.8 ל-40/1.5
            reasons_filtered["דירוג/RR נמוך"] += 1
            continue

        stocks.append({
            "ticker":   ticker,
            "name":     data["name"],
            "price":    price,
            "change":   change,
            "entry":    entry,
            "target":   target,
            "stop":     stop,
            "score":    score,
            "expected": expected,
            "rr":       rr,
            "volume":   volume,
            "sources":  data["sources"],
        })

    # מיון לפי עלייה צפויה
    stocks.sort(key=lambda x: x["expected"], reverse=True)
    top = stocks[:10]

    # ── בניית הודעה ──
    msg = (
        f"📊 <b>דוח מניות — {now_str}</b>\n"
        f"<i>נסרקו: {total_scanned} מניות | עברו פילטר: {len(stocks)}</i>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
    )

    if not top:
        # אין כלום — שלח דיאגנוסטיקה מלאה
        msg += "⚠️ <b>לא נמצאו מניות מתאימות.</b>\n\n"
        msg += "<b>סיבות:</b>\n"
        for reason, count in reasons_filtered.items():
            if count > 0:
                msg += f"  • {reason}: {count} מניות\n"

        if total_scanned == 0:
            msg += "\n❌ <b>ה-API החזיר 0 מניות.</b>\n"
            msg += "בדוק שה-API_KEY תקין ב-GitHub Secrets.\n"
            msg += "השוק האמריקאי פתוח 16:30–23:00 שעון ישראל."
        elif total_scanned < 10:
            msg += f"\n⚠️ API החזיר רק {total_scanned} מניות — ייתכן שהשוק סגור.\n"
            msg += "הזמן הטוב ביותר להרצה: 15:00–16:00 או 16:35–17:30."
        else:
            msg += f"\nנסרקו {total_scanned} מניות אבל אף אחת לא עמדה בכל הקריטריונים.\n"
            msg += "נסה שוב ב-16:35 אחרי פתיחת השוק."
        send(msg)
        return

    for i, s in enumerate(top, 1):
        icon = "🔥" if s["score"] >= 75 else ("⚡" if s["score"] >= 55 else "📈")
        pm_str = f" | פרי-מרקט מאומת" if "premarket" in s["sources"] else ""
        vol_fmt = f"{int(s['volume']):,}"
        msg += (
            f"{i}. {icon} <b>{s['ticker']}</b> | דירוג: <b>{s['score']}/100</b>{pm_str}\n"
            f"   💰 מחיר: ${s['price']}  →  כניסה: ${s['entry']}\n"
            f"   🎯 יעד: <b>${s['target']}</b>  (+{s['expected']}%)\n"
            f"   🛑 סטופ: ${s['stop']}  |  סיכוי/סיכון: 1:{s['rr']}\n"
            f"   📊 שינוי: {s['change']:+.1f}%  |  נפח: {vol_fmt}\n\n"
        )

    msg += (
        "━━━━━━━━━━━━━━━━━━\n"
        "💡 <b>טיפ:</b> חפש מניות שמופיעות גם בדוח הראשון וגם השני\n"
        "⚠️ <i>לא ייעוץ השקעות — כבד תמיד את הסטופ לוס</i>"
    )
    send(msg)
    print(f"נשלחו {len(top)} מניות מתוך {len(stocks)} שעברו פילטר")

# ─────────────────────────────────────────────
if __name__ == "__main__":
    print(f"מריץ בוט — {datetime.now().strftime('%H:%M:%S')}")
    candidates = fetch_candidates()
    print(f"סה״כ מניות שנמשכו: {len(candidates)}")
    send_morning_report(candidates)
    print("סיום.")
