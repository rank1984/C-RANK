"""
DAY-S-BOT — FINAL COMPLETE
===========================
קובץ: day_s_bot_FINAL.py
"""
import os, csv, json, requests, yfinance as yf, pytz
from datetime import datetime, date

TOKEN              = os.getenv("TELEGRAM_TOKEN")
CHAT_ID            = os.getenv("TELEGRAM_CHAT_ID")
BUDGET             = 250
MAX_TRADES         = 2
MAX_DAILY_LOSS_PCT = 0.06
MIN_STARS_HUNT     = 4
STATE_FILE         = f"state_{date.today()}.json"
LOG_FILE           = f"signals_{date.today()}.csv"

CATALYST_KEYWORDS = [
    "earnings","fda","contract","upgrade","partnership",
    "acquisition","merger","beat","approval","revenue","deal"
]
STOCKS = [
    "BITF","WULF","BTBT","NIO","SOUN","BBAI","LUNR",
    "MARA","RIOT","CLSK","NKLA","FUBO","TLRY","SNDL",
    "MULN","CLOV","INDO","VERB","IINN","KALI"
]

# ═══════════════════════════════════════════════════
# STATE
# ═══════════════════════════════════════════════════
def load_state():
    try:
        with open(STATE_FILE) as f: return json.load(f)
    except:
        return {"trades":0,"loss_usd":0.0,"killed":False,"last_signal":None}

def save_state(s):
    with open(STATE_FILE,"w") as f: json.dump(s, f, default=str)

def is_killed():
    st = load_state()
    if st.get("killed"): return True
    if st["loss_usd"] >= BUDGET * MAX_DAILY_LOSS_PCT:
        st["killed"] = True; save_state(st); return True
    if st["trades"] >= MAX_TRADES: return True
    return False

def trades_done():
    return load_state().get("trades", 0)

# ═══════════════════════════════════════════════════
# TELEGRAM
# ═══════════════════════════════════════════════════
def send_msg(text):
    if not TOKEN or not CHAT_ID: print(text); return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10)
    except: pass

def send_csv():
    if not os.path.exists(LOG_FILE):
        send_msg("📂 אין נתונים היום."); return
    with open(LOG_FILE) as f:
        rows = sum(1 for _ in f) - 1
    caption = (
        f"📊 <b>CSV יומי | {date.today()}</b>\n"
        f"{rows} סיגנלים\n\n"
        f"מלא אחרי כל עסקה:\n"
        f"actual_exit · actual_pnl_pct · notes"
    )
    with open(LOG_FILE, 'rb') as f:
        try:
            requests.post(
                f"https://api.telegram.org/bot{TOKEN}/sendDocument",
                data={"chat_id": CHAT_ID, "caption": caption, "parse_mode": "HTML"},
                files={"document": (LOG_FILE, f, "text/csv")},
                timeout=15)
        except: pass

# ═══════════════════════════════════════════════════
# INDICATORS
# ═══════════════════════════════════════════════════
def calc_rsi(s, p=14):
    if len(s) < p+1: return 50.0
    d  = s.diff()
    ag = d.where(d>0, 0.).ewm(alpha=1/p, adjust=False).mean()
    al = (-d.where(d<0, 0.)).ewm(alpha=1/p, adjust=False).mean()
    rs = ag / al.replace(0, 1e-10)
    return round(float(100-(100/(1+rs)).iloc[-1]), 1)

def calc_rvol(hist, info, market_open):
    avg = info.get('averageVolume', 0) or 0
    if not avg: return 0.0
    if market_open:
        pb = avg / 390
        return round(float(hist['Volume'].tail(10).mean() / pb), 2) if pb else 0.
    return round(float((info.get('volume',0) or 0) / avg), 2)

def calc_vwap(hist):
    try:
        return float((hist['Close']*hist['Volume']).cumsum().iloc[-1]
                     / hist['Volume'].cumsum().iloc[-1])
    except: return None

def get_market_mood():
    try:
        h   = yf.Ticker("QQQ").history(period="2d")
        chg = float((h['Close'].iloc[-1]-h['Close'].iloc[-2])
                    /h['Close'].iloc[-2]*100)
        if   chg >  0.5: return "bull",   round(chg,2)
        elif chg > -1.0: return "neutral", round(chg,2)
        elif chg > -2.0: return "bear",   round(chg,2)
        else:            return "crash",  round(chg,2)
    except: return "neutral", 0.0

def check_catalyst(t):
    try:
        news   = t.news
        cutoff = datetime.now().timestamp() - 86400
        recent = [n for n in (news or []) if n.get('providerPublishTime',0) > cutoff]
        if not recent: return None
        text = str(recent).lower()
        return "strong" if any(k in text for k in CATALYST_KEYWORDS) else "weak"
    except: return None

def float_data(info):
    f = info.get('floatShares', 0) or 0
    if not f:           return 0,  "❓"
    if f < 10_000_000:  return 2,  "🔥 פלואט נמוך"
    if f < 30_000_000:  return 1,  "✅ פלואט בינוני"
    if f < 100_000_000: return 0,  "😐 פלואט גבוה"
    return -1, "⚠️ פלואט ענק"

def classify_entry(orb_break, vol_spike, confirm_break, near_vwap, rvol, rsi, higher_high):
    if orb_break and vol_spike and confirm_break: return "ORB_CONFIRMED"
    if orb_break and vol_spike:                   return "ORB_VOL"
    if orb_break:                                 return "ORB_WEAK"
    if near_vwap and rvol > 2:                    return "VWAP_PULLBACK"
    if higher_high and rvol > 3:                  return "MOMENTUM"
    if rsi < 30 and rvol > 2:                     return "OVERSOLD"
    return "MIXED"

# ═══════════════════════════════════════════════════
# SCORING
# ═══════════════════════════════════════════════════
def calc_stars(p):
    s = 0
    if   p['rvol'] > 6:   s += 5
    elif p['rvol'] > 5:   s += 4
    elif p['rvol'] > 3:   s += 3
    elif p['rvol'] > 2:   s += 2
    elif p['rvol'] > 1.5: s += 1
    if   p['rsi'] < 20: s += 3
    elif p['rsi'] < 30: s += 2
    elif p['rsi'] < 40: s += 1
    elif p['rsi'] > 75: s -= 1
    if   p['gap'] > 8: s += 3
    elif p['gap'] > 5: s += 2
    elif p['gap'] > 2: s += 1
    if p['chg'] > 5: s += 1
    s += p['f_score']
    if   p['cat'] == "strong": s += 2
    elif p['cat'] == "weak":   s += 1
    if   p['orb_break'] and p['vol_spike'] and p['confirm_break']: s += 6
    elif p['orb_break'] and p['vol_spike']:                        s += 4
    elif p['orb_break']:                                           s += 1
    if p['near_vwap'] and p['rvol'] > 2: s += 2
    if p['higher_high']:                 s += 2
    if p['fake_move']:                   s -= 3
    s += p['spread_pen']
    if   p['mood'] == "bear"  and not p['near_vwap']: s -= 2
    elif p['mood'] == "bull":  s += 1
    elif p['mood'] == "crash": s -= 3
    if   s >= 18: return 5
    elif s >= 13: return 4
    elif s >= 9:  return 3
    elif s >= 5:  return 2
    return 1

# ═══════════════════════════════════════════════════
# POSITION
# ═══════════════════════════════════════════════════
def build_pos(price, stars):
    stop       = round(price * 0.96, 3)
    risk_share = price - stop
    risk_usd   = max(5, round(BUDGET * {5:.10,4:.07,3:.05,2:.04,1:.02}.get(stars,.02), 1))
    shares     = max(1, int(risk_usd / risk_share)) if risk_share > 0 else 1
    cost       = round(shares * price, 1)
    if cost > BUDGET * 0.30:
        shares = max(1, int(BUDGET * 0.30 / price))
        cost   = round(shares * price, 1)
    half = max(1, shares // 2)
    rest = shares - half
    return {
        "shares":shares,"half":half,"rest":rest,"cost":cost,
        "risk":round(risk_usd,1),"stop":stop,
        "stop_be":round(price*1.001,3),
        "t1":round(price*1.04,2),
        "t2":round(price*1.08,2),
    }

# ═══════════════════════════════════════════════════
# ANALYZE
# ═══════════════════════════════════════════════════
def analyze(symbol, market_open, mood):
    try:
        t    = yf.Ticker(symbol)
        hist = t.history(period="5d", interval="1m" if market_open else "5m", prepost=True)
        if hist.empty or len(hist) < 20: return None
        info  = t.info
        price = float(hist['Close'].iloc[-1])
        if price > 12 or price < 0.5: return None

        rsi  = calc_rsi(hist['Close'])
        rvol = calc_rvol(hist, info, market_open)
        vwap = calc_vwap(hist)

        bid = info.get('bid',0) or 0
        ask = info.get('ask',0) or 0
        spread     = round(((ask-bid)/ask)*100, 2) if ask > bid > 0 else 0.
        spread_pen = -1 if spread > 3 else 0

        daily  = t.history(period="5d")
        if len(daily) < 2: return None
        prev   = float(daily['Close'].iloc[-2])
        mh     = hist.between_time('09:30','16:00')
        open_p = float(mh['Open'].iloc[0]) if not mh.empty else price
        gap    = round(((open_p-prev)/prev)*100, 1)
        chg    = round(((price-prev)/prev)*100, 1)

        orb_w     = hist.between_time('09:30','09:45')
        orb_high  = float(orb_w['High'].max()) if not orb_w.empty else None
        orb_break = orb_high is not None and price > orb_high
        va        = hist['Volume'].rolling(20).mean().iloc[-1]
        vol_spike = float(hist['Volume'].iloc[-1]) > float(va)*2 if (va and va > 0) else False
        confirm_break = (float(hist['Close'].iloc[-1]) > float(hist['High'].iloc[-2])
                         if len(hist) >= 3 else False)

        upper_wick = float(hist['High'].iloc[-1] - hist['Close'].iloc[-1])
        body       = abs(float(hist['Close'].iloc[-1] - hist['Open'].iloc[-1]))
        fake_move  = upper_wick > body * 2 if body > 0 else False

        near_vwap   = (abs(price-vwap)/price < 0.01) if vwap else False
        higher_high = (float(hist['High'].iloc[-1]) > float(hist['High'].iloc[-6:-1].max())
                       if len(hist) >= 6 else False)

        f_score, f_lbl = float_data(info)
        cat            = check_catalyst(t)

        params = dict(
            rvol=rvol, rsi=rsi, gap=gap, chg=chg, f_score=f_score, cat=cat,
            orb_break=orb_break, vol_spike=vol_spike, confirm_break=confirm_break,
            fake_move=fake_move, near_vwap=near_vwap, higher_high=higher_high,
            spread_pen=spread_pen, mood=mood
        )
        stars      = calc_stars(params)
        entry_type = classify_entry(orb_break, vol_spike, confirm_break,
                                    near_vwap, rvol, rsi, higher_high)
        pos = build_pos(price, stars)
        return dict(
            symbol=symbol, price=round(price,3), gap=gap, rsi=rsi, rvol=rvol, chg=chg,
            spread=spread, orb_break=orb_break, vol_spike=vol_spike,
            confirm_break=confirm_break, fake_move=fake_move,
            near_vwap=near_vwap, higher_high=higher_high,
            catalyst=cat, f_lbl=f_lbl,
            vwap=round(vwap,3) if vwap else None,
            entry_type=entry_type, stars=stars, pos=pos,
            entry_time=datetime.now(pytz.timezone('America/New_York')).strftime('%H:%M')
        )
    except: return None

# ═══════════════════════════════════════════════════
# CSV LOG
# ═══════════════════════════════════════════════════
CSV_COLS = [
    "date","entry_time","symbol","stars","entry_type",
    "price","gap","rvol","rsi","chg","spread",
    "orb_break","vol_spike","confirm_break","fake_move",
    "near_vwap","higher_high","catalyst",
    "target_t1","target_t2","stop",
    "actual_exit","actual_pnl_pct","mae","mfe","notes"
]

def log_signal(r):
    exists = os.path.exists(LOG_FILE)
    p = r['pos']
    with open(LOG_FILE, 'a', newline='') as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLS, extrasaction='ignore')
        if not exists: w.writeheader()
        w.writerow({
            "date":str(date.today()), "entry_time":r['entry_time'],
            "symbol":r['symbol'], "stars":r['stars'], "entry_type":r['entry_type'],
            "price":r['price'], "gap":r['gap'], "rvol":r['rvol'],
            "rsi":r['rsi'], "chg":r['chg'], "spread":r['spread'],
            "orb_break":r['orb_break'], "vol_spike":r['vol_spike'],
            "confirm_break":r['confirm_break'], "fake_move":r['fake_move'],
            "near_vwap":r['near_vwap'], "higher_high":r['higher_high'],
            "catalyst":r['catalyst'] or "",
            "target_t1":p['t1'], "target_t2":p['t2'], "stop":p['stop'],
            "actual_exit":"","actual_pnl_pct":"","mae":"","mfe":"","notes":""
        })

# ═══════════════════════════════════════════════════
# MESSAGES
# ═══════════════════════════════════════════════════
def _action_block(r):
    p  = r['pos']
    et = r['entry_type']
    if r['fake_move']:
        return (
            "🚫 <b>אל תיכנס — זוהתה מלכודת (TRAP)</b>\n"
            "   זנב עליון = מוכרים חזקים דחפו חזרה\n"
            "   עבור למניה הבאה"
        )
    if et == "ORB_CONFIRMED":
        return (
            f"✅ <b>קנה עכשיו ב-Limit ${r['price']}</b>\n"
            f"   {p['shares']} מניות = ${p['cost']} | סיכון מקסימלי: ${p['risk']}\n"
            f"   פריצה + ווליום + אישור = הסיגנל הכי חזק"
        )
    if et == "ORB_VOL":
        return (
            f"✅ <b>קנה ב-Limit ${r['price']}</b>\n"
            f"   {p['shares']} מניות = ${p['cost']} | סיכון: ${p['risk']}\n"
            f"   פריצה עם ווליום — המתן לסגירת נר לאישור"
        )
    if et == "VWAP_PULLBACK":
        vwap_str = f"${r['vwap']}" if r['vwap'] else "VWAP"
        return (
            f"🎯 <b>המתן ל-{vwap_str} ואז קנה ב-Limit</b>\n"
            f"   {p['shares']} מניות = ${p['cost']} | סיכון: ${p['risk']}\n"
            f"   Pullback = כניסה מדויקת בסיכון נמוך יותר"
        )
    if et in ("MOMENTUM","OVERSOLD"):
        confirm = round(r['price']*1.005, 3)
        return (
            f"⚡ <b>קנה רק אם עובר ${confirm} ב-Limit</b>\n"
            f"   {p['shares']} מניות = ${p['cost']} | סיכון: ${p['risk']}\n"
            f"   חכה לפריצה — אל תיכנס לפניה"
        )
    return (
        "👀 <b>עקוב בלבד — אין כניסה ברורה</b>\n"
        "   הוסף לרשימת מעקב\n"
        "   אל תיכנס עדיין"
    )

def _plan_block(p):
    return (
        f"📋 <b>תוכנית יציאה:</b>\n"
        f"   🟡 T1 +4% → <b>${p['t1']}</b>  מכור {p['half']} מניות\n"
        f"          אז הזז סטופ ל-${p['stop_be']} (לא תפסיד)\n"
        f"   🟢 T2 +8% → <b>${p['t2']}</b>  מכור {p['rest']} מניות\n"
        f"   🔴 Stop   → <b>${p['stop']}</b>  צא מהכל מיד!"
    )

def fmt_hunting(signals, mood, mood_chg, done):
    rem  = MAX_TRADES - done
    mi   = {"bull":"🟢","neutral":"🟡","bear":"🔴","crash":"💀"}[mood]
    time_str = datetime.now(pytz.timezone('America/New_York')).strftime('%H:%M')

    lines = [
        f"🏹 <b>ציד פעיל | {time_str} NY</b>",
        f"{mi} שוק {mood_chg:+.1f}%   עסקאות היום: {done}/{MAX_TRADES}",
        "━" * 22,
    ]

    shown = 0
    for r in sorted(signals, key=lambda x: x['stars'], reverse=True):
        if shown >= rem: break
        p = r['pos']

        lines.append(f"\n<b>{r['symbol']}</b> {'⭐'*r['stars']}")
        lines.append(f"💲 ${r['price']}  {r['chg']:+.1f}%  |  RVOL {r['rvol']}x  RSI {r['rsi']}  גאפ {r['gap']:+.1f}%")
        lines.append(f"{r['f_lbl']}")

        if r['spread'] > 1.5:
            lines.append(f"⚠️ ספרד {r['spread']}% — <b>Limit Order חובה!</b>")

        if r['catalyst'] == "strong": lines.append("📰🔥 יש חדשות חשובות!")
        elif r['catalyst'] == "weak": lines.append("📰 יש חדשות")

        lines.append("")
        lines.append(_action_block(r))
        lines.append("")
        lines.append(_plan_block(p))
        lines.append("─" * 22)
        shown += 1

    lines.append("⚠️ <b>Limit Order בלבד — אף פעם לא Market!</b>")
    lines.append("הפסדת? שלח: <code>/loss [סכום]</code>")
    return "\n".join(lines)

def fmt_follow_up(ls, time_ny):
    p = ls['pos']
    return "\n".join([
        f"⏱️ <b>בדיקה: {ls['symbol']} | {time_ny.strftime('%H:%M')} NY</b>",
        f"כניסה הייתה ב-${ls['price']}",
        "━" * 22,
        "",
        f"📈 עלה מעל ${p['t1']} (+4%)?",
        f"   → מכור {p['half']} מניות עכשיו",
        f"   → הזז סטופ ל-${p['stop_be']}",
        "",
        f"😐 עדיין מתחת ל-${p['t1']}?",
        f"   → החזק. סטופ נשאר ב-${p['stop']}",
        "",
        f"📉 ירד מתחת ל-${p['stop']}?",
        f"   → <b>צא מיד!</b> שלח: /loss [סכום]",
        "",
        "─" * 22,
        f"📊 רשום ב-CSV: entry_type={ls.get('entry_type','?')}",
    ])

def fmt_prep(results, mood, mood_chg, time_ny):
    top = sorted(results, key=lambda x: x['stars'], reverse=True)[:5]
    mi  = {"bull":"🟢","neutral":"🟡","bear":"🔴","crash":"💀"}[mood]
    mn  = {"bull":"חיובי","neutral":"נייטרלי","bear":"שלילי","crash":"קריסה"}[mood]
    lines = [
        f"📋 <b>הכנה למחר | {time_ny.strftime('%H:%M')} NY</b>",
        f"{mi} שוק {mn} ({mood_chg:+.1f}%)",
        "━" * 22,
    ]
    for i, r in enumerate(top, 1):
        trap = " ⚠️TRAP" if r['fake_move'] else ""
        cat  = " 📰🔥" if r['catalyst']=="strong" else " 📰" if r['catalyst']=="weak" else ""
        lines.append(
            f"\n{i}. <b>{r['symbol']}</b> {'⭐'*r['stars']}{trap}{cat}\n"
            f"   💲${r['price']}  RVOL {r['rvol']}x  RSI {r['rsi']}  גאפ {r['gap']:+.1f}%\n"
            f"   {r['f_lbl']}"
        )
    lines += [
        "", "━" * 22,
        "⏰ ציד מחר: 9:45–10:15 NY = 16:45–17:15 ישראל",
        f"📌 כניסה רק ב-{MIN_STARS_HUNT}⭐+  ·  מקסימום {MAX_TRADES} עסקאות",
        f"🛑 Stop אוטומטי: ${BUDGET*MAX_DAILY_LOSS_PCT:.0f} הפסד יומי",
    ]
    return "\n".join(lines)

# ═══════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════
def main():
    tz      = pytz.timezone('America/New_York')
    time_ny = datetime.now(tz)
    h, m    = time_ny.hour, time_ny.minute

    is_hunting  = (h == 9  and m >= 45) or (h == 10 and m <= 15)
    is_followup = (h == 10 and 16 <= m <= 30)
    is_morning  = (h == 9  and 15 <= m <= 29)
    is_prep     = (h == 16 and 25 <= m <= 40)
    market_open = (9 <= h < 16)
    dead_zone   = (h == 11 and m >= 30) or h in [12, 13]

    mood, mood_chg = get_market_mood()

    if mood == "crash" and is_hunting:
        send_msg(
            f"💀 <b>קריסת שוק | QQQ {mood_chg:.1f}%</b>\n\n"
            f"🚫 לא צדים היום.\nשמור את ה-${BUDGET}."
        ); return

    if is_killed() and (is_hunting or is_followup):
        st = load_state()
        if st['trades'] >= MAX_TRADES:
            send_msg(f"🛑 <b>{MAX_TRADES}/{MAX_TRADES} עסקאות הושלמו</b>\nסיימת להיום. מחר מחדש ב-9:45 NY.")
        else:
            send_msg(f"🛑 <b>הפסד יומי מקסימלי (${BUDGET*MAX_DAILY_LOSS_PCT:.0f})</b>\nהפסק לצוד היום. מחר מחדש.")
        return

    if is_followup:
        st = load_state()
        if st.get("last_signal"):
            send_msg(fmt_follow_up(st["last_signal"], time_ny))
        return

    if dead_zone and not (is_morning or is_prep):
        send_msg(
            f"😴 <b>שעת דמדומים | {time_ny.strftime('%H:%M')} NY</b>\n"
            f"11:30–14:00 = ווליום נמוך, פריצות שווא\n"
            f"לא צדים. הבוט במצב עוקב."
        ); return

    results = []
    for sym in STOCKS:
        r = analyze(sym, market_open, mood)
        if r: results.append(r)

    if not results:
        send_msg("⚠️ לא נמצאו נתונים. בדוק חיבור."); return

    for r in results:
        if r['stars'] >= 3: log_signal(r)

    if is_hunting:
        done    = trades_done()
        signals = [s for s in results if s['stars'] >= MIN_STARS_HUNT]
        if signals:
            send_msg(fmt_hunting(signals, mood, mood_chg, done))
            top = sorted(signals, key=lambda x: x['stars'], reverse=True)[0]
            st  = load_state()
            st["trades"] = done + 1
            st["last_signal"] = {
                "symbol":top['symbol'], "price":top['price'],
                "entry_type":top['entry_type'], "pos":top['pos'],
                "vwap":top['vwap']
            }
            save_state(st)
        else:
            send_msg(
                f"🔍 <b>ציד | {time_ny.strftime('%H:%M')} NY</b>\n"
                f"אין סיגנל {MIN_STARS_HUNT}⭐+ נקי עכשיו.\n"
                f"ממתין לפריצה עם ווליום..."
            )

    elif is_morning or is_prep:
        send_msg(fmt_prep(results, mood, mood_chg, time_ny))
        if is_prep: send_csv()

    else:
        top  = sorted(results, key=lambda x: x['stars'], reverse=True)[:4]
        mi   = {"bull":"🟢","neutral":"🟡","bear":"🔴","crash":"💀"}[mood]
        rows = [f"{'⭐'*r['stars']} <b>{r['symbol']}</b>  ${r['price']}  RVOL {r['rvol']}x" for r in top]
        send_msg(
            f"📊 <b>{time_ny.strftime('%H:%M')} NY</b>  {mi} {mood_chg:+.1f}%\n"
            f"{'━'*20}\n" + "\n".join(rows)
        )

if __name__ == "__main__":
    main()
