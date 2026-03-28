import os, requests, yfinance as yf, pandas as pd, pytz, csv
from datetime import datetime, date

# ─── הגדרות ───────────────────────────────────────────────
TOKEN    = os.getenv("TELEGRAM_TOKEN")
CHAT_ID  = os.getenv("TELEGRAM_CHAT_ID")
BUDGET   = 250   # $ תקציב כולל

STOCKS = [
    "BITF","WULF","BTBT","NIO","SOUN","BBAI","LUNR",
    "MARA","RIOT","CLSK","NKLA","FUBO","TLRY","SNDL",
    "MULN","CLOV","INDO","VERB","IINN","KALI"
]

# ─── טלגרם ────────────────────────────────────────────────
def send_telegram_msg(msg):
    if not TOKEN or not CHAT_ID:
        print(msg); return
    requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"}
    )

# ─── RSI אמיתי (Wilder's Method) ──────────────────────────
def calc_rsi(series, period=14):
    """
    RSI לפי השיטה המקורית של Wilder - לא ממוצע פשוט!
    זה מה שכל פלטפורמת מסחר מחשבת.
    """
    if len(series) < period + 1:
        return 50.0  # ערך נייטרלי אם אין מספיק נתונים
    delta = series.diff()
    gain  = delta.where(delta > 0, 0.0)
    loss  = -delta.where(delta < 0, 0.0)
    # EWM עם alpha=1/period = שיטת Wilder
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-10)
    return round(float(100 - (100 / (1 + rs)).iloc[-1]), 1)

# ─── RVOL מדויק ───────────────────────────────────────────
def calc_rvol(hist, avg_volume):
    """
    Volume יחסי: כמה פעמים יותר גדול מהממוצע לאותה שעה.
    avg_volume = נפח יומי ממוצע / 390 דקות = נפח לנר 1 דקה.
    """
    if avg_volume == 0: return 0.0
    recent_vol = hist['Volume'].tail(10).mean()
    baseline   = avg_volume / 390  # נפח ממוצע לנר אחד
    return round(float(recent_vol / baseline), 2) if baseline > 0 else 0.0

# ─── דירוג כוכבים משודרג ──────────────────────────────────
def calculate_stars(gap, rvol, rsi, price_change_pct):
    """
    מערכת ניקוד:
      RVOL  → המדד הכי חשוב לדייטריידינג (עד 4 נקודות)
      RSI   → נקודות קיצון לפוטנציאל היפוך (עד 3 נקודות)
      Gap   → חוזק הפתיחה (עד 3 נקודות)
      מומנטום → תוספת מניע (1 נקודה)
    סה"כ: 0-11 נקודות → 1-5 כוכבים
    """
    score = 0

    # RVOL — מנוע ההזדמנות
    if   rvol > 5.0: score += 4
    elif rvol > 3.0: score += 3
    elif rvol > 2.0: score += 2
    elif rvol > 1.5: score += 1

    # RSI — נקודות קיצון
    if   rsi < 20: score += 3   # אוברסולד עמוק - הכי חזק
    elif rsi < 30: score += 2   # אוברסולד
    elif rsi < 40: score += 1   # חולשה עם פוטנציאל
    elif rsi > 75: score -= 1   # אוברבוט - סכנה

    # Gap
    if   gap > 8: score += 3
    elif gap > 5: score += 2
    elif gap > 2: score += 1

    # מומנטום מחיר יומי
    if price_change_pct > 5: score += 1

    # המרה ל-1-5
    if   score >= 9: return 5
    elif score >= 7: return 4
    elif score >= 5: return 3
    elif score >= 3: return 2
    else:            return 1

# ─── ניהול פוזיציה לפי תקציב ──────────────────────────────
def calc_position(price, stars):
    """
    כמה לשים על כל מניה בהתאם לדירוג ולתקציב של $250.
    ⭐⭐⭐⭐⭐ = 25% מהתקציב ($62)
    ⭐⭐⭐⭐  = 20%          ($50)
    ⭐⭐⭐   = 15%          ($37)
    ⭐⭐    = 10%          ($25)
    ⭐     = 5%           ($12) — בדיקה בלבד
    """
    risk = {5: 0.25, 4: 0.20, 3: 0.15, 2: 0.10, 1: 0.05}
    dollars = round(BUDGET * risk.get(stars, 0.05), 2)
    shares  = int(dollars / price) if price > 0 else 0
    return {"dollars": dollars, "shares": shares}

# ─── ניתוח מניה ───────────────────────────────────────────
def analyze_stock(symbol, is_live=False):
    try:
        t        = yf.Ticker(symbol)
        interval = "1m" if is_live else "5m"
        hist     = t.history(period="5d", interval=interval, prepost=True)

        if hist.empty or len(hist) < 20:
            return None

        curr_price = float(hist['Close'].iloc[-1])
        if curr_price > 12 or curr_price < 0.5:
            return None  # פילטר תקציב: $0.5–$12

        info       = t.info
        avg_volume = info.get('averageVolume', 1) or 1

        # RSI אמיתי
        rsi = calc_rsi(hist['Close'])

        # RVOL
        rvol = calc_rvol(hist, avg_volume)

        # גאפ
        daily = t.history(period="5d")
        if len(daily) < 2:
            return None
        prev_close = float(daily['Close'].iloc[-2])

        market_h = hist.between_time('09:30', '16:00')
        open_p   = float(market_h['Open'].iloc[0]) if not market_h.empty else curr_price
        gap      = round(((open_p - prev_close) / prev_close) * 100, 1)

        # שינוי יומי
        price_change = round(((curr_price - prev_close) / prev_close) * 100, 1)

        # ממוצע נע 9 (לטרנד מהיר)
        ma9       = float(hist['Close'].tail(9).mean())
        above_ma9 = curr_price > ma9

        stars    = calculate_stars(gap, rvol, rsi, price_change)
        position = calc_position(curr_price, stars)

        return {
            "symbol":    symbol,
            "price":     round(curr_price, 3),
            "gap":       gap,
            "rsi":       rsi,
            "rvol":      rvol,
            "change":    price_change,
            "above_ma9": above_ma9,
            "target":    round(curr_price * 1.04, 2),  # +4%
            "stop":      round(curr_price * 0.96, 2),  # -4% סטופ קשיח
            "stars":     stars,
            "position":  position
        }
    except Exception:
        return None

# ─── לוג CSV לניתוח עתידי ─────────────────────────────────
def log_signal(data):
    """
    שומר כל סיגנל ל-CSV.
    אחרי שבוע תוכל לראות: אילו כוכבים באמת הרוויחו?
    """
    filename    = f"signals_{date.today()}.csv"
    fields      = ["symbol","price","gap","rsi","rvol","change","stars","target","stop"]
    file_exists = os.path.exists(filename)
    with open(filename, 'a', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        if not file_exists:
            writer.writeheader()
        writer.writerow({k: data[k] for k in fields})

# ─── MAIN ─────────────────────────────────────────────────
def main():
    time_ny = datetime.now(pytz.timezone('America/New_York'))
    hour, minute = time_ny.hour, time_ny.minute

    # זיהוי מצב הפעלה
    is_morning_scan = (hour == 9 and 15 <= minute <= 29)                    # לפני פתיחה
    is_hunting      = (hour == 9 and 45 <= minute <= 59) or \
                      (hour == 10 and minute <= 15)                          # מצב ציד חם
    is_prep         = (hour == 16 and 25 <= minute <= 40)                   # הכנה לפתיחה מחר

    # סריקה
    results = []
    for s in STOCKS:
        res = analyze_stock(s, is_live=is_hunting)
        if res:
            results.append(res)

    if not results:
        send_telegram_msg("⚠️ DAY-S-BOT: לא נמצאו מניות מתאימות כרגע.")
        return

    # ══════════════════════════════════════════
    # 🏹 מצב ציד (9:45–10:15 NY)
    # ══════════════════════════════════════════
    if is_hunting:
        signals = [s for s in results if s['stars'] >= 3]
        if signals:
            msg = "🏹 <b>צייד ה-5 כוכבים | סיגנל זהב</b>\n━━━━━━━━━━━━━━━━━━\n\n"
            for s in sorted(signals, key=lambda x: x['stars'], reverse=True):
                stars_str = "⭐" * s['stars']
                trend     = "📈" if s['above_ma9'] else "📉"
                msg += (
                    f"<b>{s['symbol']}</b> {stars_str}\n"
                    f"💰 ${s['price']} {trend} שינוי: {s['change']}%\n"
                    f"📊 RVOL: {s['rvol']}x | RSI: {s['rsi']} | גאפ: {s['gap']}%\n"
                    f"🎯 יעד: ${s['target']} | 🛑 סטופ: ${s['stop']}\n"
                    f"💼 קנה: {s['position']['shares']} מניות (${s['position']['dollars']})\n"
                    f"──────────────────\n"
                )
                log_signal(s)
            send_telegram_msg(msg)
        else:
            send_telegram_msg("🔍 <b>מצב ציד:</b> אין סיגנל חזק מספיק כרגע.\nהמתן לנר הבא.")

    # ══════════════════════════════════════════
    # 🌅 סריקת בוקר (9:15–9:30 NY) — פרי-מרקט
    # ══════════════════════════════════════════
    elif is_morning_scan:
        top = sorted(results, key=lambda x: x['stars'], reverse=True)[:8]
        msg = "🌅 <b>סריקת בוקר | לפני פתיחה</b>\n━━━━━━━━━━━━━━━━━━\n\n"
        for s in top:
            stars_str = "⭐" * s['stars']
            alert = " ← 👀 תעקוב" if s['stars'] >= 4 else ""
            msg += (
                f"<b>{s['symbol']}</b> {stars_str}{alert}\n"
                f"   ${s['price']} | Gap: {s['gap']}% | RVOL: {s['rvol']}x | RSI: {s['rsi']}\n"
            )
        msg += f"\n💰 תקציב: ${BUDGET} | פוזיציה מקסימלית: ${round(BUDGET*0.25,0)}"
        send_telegram_msg(msg)

    # ══════════════════════════════════════════
    # 📝 הכנה לפתיחה מחר (16:25–16:40 NY)
    # ══════════════════════════════════════════
    elif is_prep:
        top = sorted(results, key=lambda x: x['stars'], reverse=True)[:6]
        msg = "📝 <b>דירוג הכנה | פתיחה מחר</b>\n━━━━━━━━━━━━━━━━━━\n\n"
        for s in top:
            stars_str = "⭐" * s['stars']
            msg += f"<b>{s['symbol']}</b> {stars_str} | ${s['price']} | Gap: {s['gap']}% | RVOL: {s['rvol']}x | RSI: {s['rsi']}\n"
        msg += f"\n⏰ הציד מתחיל מחר ב-9:45 NY (16:45 ישראל)"
        send_telegram_msg(msg)

    # ══════════════════════════════════════════
    # 📊 דוח שגרתי (כל הרצה אחרת)
    # ══════════════════════════════════════════
    else:
        top = sorted(results, key=lambda x: x['stars'], reverse=True)[:5]
        msg = f"📊 <b>DAY-S-BOT | {time_ny.strftime('%H:%M')} NY</b>\n━━━━━━━━━━━━━━━━━━\n\n"
        for s in top:
            stars_str = "⭐" * s['stars']
            msg += f"<b>{s['symbol']}</b> {stars_str} | ${s['price']} | RVOL: {s['rvol']}x | RSI: {s['rsi']}\n"
        send_telegram_msg(msg)

if __name__ == "__main__":
    main()
