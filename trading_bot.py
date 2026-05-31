import os
import time
import json
import logging
import pytz
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta

# ══════════════════════════════════════════════
# DAYS-BOT V4 — Dual-Mode Risk Engine
# ══════════════════════════════════════════════
# מצב 1 (AGGRESSIVE): תיק < $1,000 — סיכון גבוה, A+ בלבד, יחס 1:3
# מצב 2 (MODERATE):   תיק >= $1,000 — סיכון מתון, A ו-A+, יחס 1:2.5
# ══════════════════════════════════════════════

ALPACA_API_KEY    = os.environ.get("ALPACA_API_KEY", "").strip()
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "").strip()
TELEGRAM_TOKEN    = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID  = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

HEADERS = {
    "APCA-API-KEY-ID": ALPACA_API_KEY,
    "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
    "accept": "application/json"
}

# ── פרמטרי סריקה בסיסיים ──
MIN_PRICE   = 1.5
MAX_PRICE   = 25.0
MIN_VOLUME  = 500_000
MAX_FLOAT   = 200_000_000

# ── סף מעבר בין מצבים ──
AGGRESSIVE_THRESHOLD = 1_000.0   # מתחת ל-$1,000 = מצב אגרסיבי
PORTFOLIO_FILE       = "portfolio_state.json"
STATE_FILE           = "active_trades.json"
LOG_FILE             = "trade_log.csv"
COOLDOWN_MINUTES     = 60
MAX_DAILY_TRADES     = 3          # PDT Rule — מקסימום 3 Day Trades בשבוע

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("DAYS_BOT_V4")

alerted_symbols  = {}
daily_trade_count = {"date": "", "count": 0}


# ══════════════════════════════════════════════
# ניהול מצב התיק (Portfolio State)
# ══════════════════════════════════════════════

def load_portfolio():
    """טוען את מצב התיק הנוכחי מהקובץ"""
    defaults = {"balance": 250.0, "mode": "AGGRESSIVE", "peak_balance": 250.0}
    if not os.path.exists(PORTFOLIO_FILE):
        save_portfolio(defaults)
        return defaults
    try:
        with open(PORTFOLIO_FILE, "r") as f:
            return json.load(f)
    except:
        return defaults

def save_portfolio(data):
    with open(PORTFOLIO_FILE, "w") as f:
        json.dump(data, f, indent=4)

def get_risk_profile(balance: float) -> dict:
    """
    מחזיר את פרופיל הסיכון המתאים לפי יתרת התיק.
    מתחת ל-$1,000 → AGGRESSIVE
    מעל $1,000    → MODERATE
    """
    if balance < AGGRESSIVE_THRESHOLD:
        return {
            "mode":           "AGGRESSIVE",
            "risk_pct":       0.18,         # 18% מהתיק לעסקה
            "rr_ratio":       3.0,          # יחס סיכוי:סיכון 1:3
            "min_score":      10,           # A+ בלבד
            "min_grade":      "A+",
            "max_risk_pct":   0.12,         # ביטול עסקה אם סיכון > 12% ממחיר הכניסה
        }
    else:
        return {
            "mode":           "MODERATE",
            "risk_pct":       0.06,         # 6% מהתיק לעסקה
            "rr_ratio":       2.5,          # יחס סיכוי:סיכון 1:2.5
            "min_score":      8,            # A ו-A+
            "min_grade":      "A",
            "max_risk_pct":   0.08,
        }

def update_balance_after_trade(pnl: float):
    """מעדכן את יתרת התיק לאחר סגירת עסקה ומחליף מצב במידת הצורך"""
    portfolio = load_portfolio()
    old_balance = portfolio["balance"]
    old_mode    = portfolio["mode"]

    portfolio["balance"] += pnl
    portfolio["balance"]  = round(portfolio["balance"], 2)

    # עדכון שיא התיק
    if portfolio["balance"] > portfolio.get("peak_balance", old_balance):
        portfolio["peak_balance"] = portfolio["balance"]

    # קביעת מצב חדש
    new_profile = get_risk_profile(portfolio["balance"])
    portfolio["mode"] = new_profile["mode"]

    save_portfolio(portfolio)

    # שליחת הודעה אם יש מעבר בין מצבים
    if old_mode != portfolio["mode"]:
        emoji = "🟢" if portfolio["mode"] == "MODERATE" else "🔴"
        msg = (f"{emoji} *מעבר מצב סיכון!*\n"
               f"━━━━━━━━━━━━━━━━━\n"
               f"מ: `{old_mode}` → `{portfolio['mode']}`\n"
               f"💰 יתרת תיק: `${portfolio['balance']}`\n"
               f"📌 מהיום הבוט יפעל בפרמטרים החדשים")
        send_telegram(msg)
        log.info(f"MODE SWITCH: {old_mode} → {portfolio['mode']}")

    return portfolio


# ══════════════════════════════════════════════
# PDT Rule — מעקב מספר עסקאות יומי
# ══════════════════════════════════════════════

def can_trade_today() -> bool:
    """מוודא שלא חרגנו מ-3 Day Trades בשבוע (PDT Rule)"""
    global daily_trade_count
    today = datetime.now().strftime("%Y-%m-%d")
    if daily_trade_count["date"] != today:
        daily_trade_count = {"date": today, "count": 0}
    return daily_trade_count["count"] < MAX_DAILY_TRADES

def register_trade():
    global daily_trade_count
    today = datetime.now().strftime("%Y-%m-%d")
    if daily_trade_count["date"] != today:
        daily_trade_count = {"date": today, "count": 0}
    daily_trade_count["count"] += 1


# ══════════════════════════════════════════════
# מנוע News Catalyst
# ══════════════════════════════════════════════

def check_news_catalyst(sym: str):
    keywords = ["earnings", "revenue", "contract", "fda", "buyout", "merger",
                "partnership", "deal", "quarterly", "approval", "alliance",
                "guidance", "upgrade", "acquisition"]
    try:
        ticker     = yf.Ticker(sym)
        news_feed  = ticker.news
        if not news_feed:
            return False, "No News"
        now_ts = time.time()
        for item in news_feed:
            pub_time = item.get('providerPublishTime', 0)
            if now_ts - pub_time < 86400:
                title = item.get('title', '').lower()
                if any(kw in title for kw in keywords):
                    return True, item.get('title')
        return False, "No Catalyst Found"
    except Exception as e:
        return False, f"News Error: {e}"


# ══════════════════════════════════════════════
# סריקת גיינרים דינמית
# ══════════════════════════════════════════════

def get_dynamic_gainers():
    url = "https://data.alpaca.markets/v1beta1/screener/stocks/movers?market_type=stocks"
    try:
        res     = requests.get(url, headers=HEADERS).json()
        gainers = res.get('gainers', [])
        symbols = [s['symbol'] for s in gainers if s['percent_change'] > 3]
        if not symbols:
            return []

        snap_url = f"https://data.alpaca.markets/v2/stocks/snapshots?symbols={','.join(symbols)}&feed=iex"
        snap_res = requests.get(snap_url, headers=HEADERS).json()

        candidates = []
        for sym, data in snap_res.items():
            if not data or 'dailyBar' not in data:
                continue
            price = data['dailyBar'].get('c', 0)
            vol   = data['dailyBar'].get('v', 0)
            if (MIN_PRICE <= price <= MAX_PRICE) and (vol >= MIN_VOLUME):
                candidates.append((sym, price))
        return candidates
    except Exception as e:
        log.error(f"Error fetching gainers: {e}")
        return []


# ══════════════════════════════════════════════
# ניתוח טכני + מערכת ניקוד דינמית
# ══════════════════════════════════════════════

def analyze_and_score_stock(sym: str, profile: dict):
    """
    מנתח מניה ומחשב ציון.
    הסף המינימלי לכניסה מגיע מה-profile (8 במצב MODERATE, 10 במצב AGGRESSIVE).
    """
    try:
        ticker      = yf.Ticker(sym)
        info        = ticker.info
        float_shares = info.get('floatShares', float('inf')) or float('inf')

        hist_2d   = ticker.history(period="2d")
        if len(hist_2d) < 2:
            return None
        prev_close  = hist_2d['Close'].iloc[-2]
        open_today  = hist_2d['Open'].iloc[-1]
        gap_pct     = ((open_today - prev_close) / prev_close) * 100

        start_date = (datetime.now(pytz.timezone("US/Eastern"))
                      .replace(hour=4, minute=0, second=0)
                      .strftime('%Y-%m-%dT%H:%M:%SZ'))
        url  = (f"https://data.alpaca.markets/v2/stocks/bars"
                f"?symbols={sym}&timeframe=5Min&start={start_date}&limit=1000&feed=iex")
        resp = requests.get(url, headers=HEADERS).json()

        if 'bars' not in resp or not resp['bars'].get(sym):
            return None
        df = pd.DataFrame(resp['bars'][sym])
        df.rename(columns={'t':'Datetime','o':'Open','h':'High',
                            'l':'Low','c':'Close','v':'Volume'}, inplace=True)
        if len(df) < 10:
            return None

        # VWAP
        df['TP']   = (df['High'] + df['Low'] + df['Close']) / 3
        df['TPV']  = df['TP'] * df['Volume']
        df['VWAP'] = df['TPV'].cumsum() / df['Volume'].cumsum()

        cur       = df.iloc[-1]
        last_close = cur['Close']
        last_vwap  = cur['VWAP']

        df['Datetime'] = pd.to_datetime(df['Datetime']).dt.tz_convert('US/Eastern')
        df.set_index('Datetime', inplace=True)
        premarket = df.between_time('04:00', '09:30')
        pm_high   = premarket['High'].max() if not premarket.empty else df['Open'].iloc[0]

        avg_vol   = df['Volume'].rolling(10).mean().iloc[-1]
        rvol      = cur['Volume'] / avg_vol if avg_vol > 0 else 0

        # ── ניקוד ──
        score = 0
        if rvol > 3.0:               score += 2
        if last_close > last_vwap:   score += 2
        if last_close > pm_high:     score += 2
        if float_shares < 50_000_000: score += 2
        if gap_pct > 10.0:           score += 2

        has_news, news_title = check_news_catalyst(sym)
        if has_news:
            score += 2
            log.info(f"📰 Catalyst: {sym} — {news_title}")

        # סף מינימלי דינמי לפי מצב
        if score < profile["min_score"]:
            return None

        grade = "A+" if score >= 10 else "A"

        # ── ניהול סיכונים ──
        stop_loss   = cur['Low'] - 0.02
        risk_amount = last_close - stop_loss
        if risk_amount <= 0:
            return None

        # ביטול עסקה אם הסטופ רחוק מדי ביחס למחיר
        if risk_amount / last_close > profile["max_risk_pct"]:
            return None

        portfolio = load_portfolio()
        balance   = portfolio["balance"]
        dollar_risk = balance * profile["risk_pct"]
        shares    = int(dollar_risk / risk_amount)
        if shares == 0:
            return None

        cost   = round(shares * last_close, 2)
        target = round(last_close + (risk_amount * profile["rr_ratio"]), 2)

        return {
            "symbol":     sym,
            "price":      last_close,
            "pm_high":    round(pm_high, 2),
            "vwap":       round(last_vwap, 2),
            "stop":       round(stop_loss, 2),
            "target":     target,
            "shares":     shares,
            "cost":       cost,
            "score":      score,
            "grade":      grade,
            "rvol":       round(rvol, 1),
            "float":      float_shares,
            "gap":        round(gap_pct, 1),
            "news_title": news_title if has_news else "No Catalyst",
            "mode":       profile["mode"],
            "rr_ratio":   profile["rr_ratio"],
        }
    except Exception as e:
        log.error(f"Analysis error {sym}: {e}")
        return None


# ══════════════════════════════════════════════
# מעקב פוזיציות פתוחות
# ══════════════════════════════════════════════

def load_active_trades():
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_active_trades(trades):
    with open(STATE_FILE, "w") as f:
        json.dump(trades, f, indent=4)

def track_open_positions():
    active = load_active_trades()
    if not active:
        return

    symbols_str = ",".join(active.keys())
    try:
        url      = f"https://data.alpaca.markets/v2/stocks/snapshots?symbols={symbols_str}&feed=iex"
        snap_res = requests.get(url, headers=HEADERS).json()

        for sym in list(active.keys()):
            if sym not in snap_res or not snap_res[sym]:
                continue
            cur_price = snap_res[sym]['dailyBar'].get('c', 0)
            if cur_price == 0:
                continue

            trade  = active[sym]
            target = trade['target']
            stop   = trade['stop']
            win    = cur_price >= target
            loss   = cur_price <= stop

            if win or loss:
                entry_time = datetime.strptime(trade['timestamp'], '%Y-%m-%d %H:%M:%S')
                duration   = round((datetime.now() - entry_time).total_seconds() / 60, 1)
                pnl        = (cur_price - trade['price']) * trade['shares']
                outcome    = "WIN" if win else "LOSS"

                log_data = {
                    "timestamp":       trade['timestamp'],
                    "exit_timestamp":  datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    "symbol":          sym,
                    "mode":            trade.get('mode', 'UNKNOWN'),
                    "score":           trade['score'],
                    "grade":           trade['grade'],
                    "rvol":            trade['rvol'],
                    "gap":             trade['gap'],
                    "float":           trade['float'],
                    "entry_price":     trade['price'],
                    "stop_loss":       stop,
                    "target":          target,
                    "exit_price":      round(cur_price, 2),
                    "duration_min":    duration,
                    "outcome":         outcome,
                    "pnl":             round(pnl, 2),
                    "rr_ratio":        trade.get('rr_ratio', 2.5),
                }
                log_trade(log_data)

                # עדכון יתרת תיק — זה יחליף מצב אוטומטית אם צריך
                update_balance_after_trade(pnl)

                portfolio = load_portfolio()
                emoji     = "💰" if win else "🛑"
                msg = (f"{emoji} *עסקה נסגרה: {sym} ({outcome})*\n"
                       f"━━━━━━━━━━━━━━━━━\n"
                       f"🚪 *יציאה:* `${round(cur_price, 2)}` | כניסה: `${trade['price']}`\n"
                       f"💵 *רווח/הפסד:* `${round(pnl, 2)}`\n"
                       f"⏱️ *זמן בעסקה:* `{duration} דקות`\n"
                       f"📊 *ציון:* `{trade['score']}/12` (Grade {trade['grade']})\n"
                       f"━━━━━━━━━━━━━━━━━\n"
                       f"💼 *יתרת תיק:* `${portfolio['balance']}` | מצב: `{portfolio['mode']}`")
                send_telegram(msg)
                del active[sym]

        save_active_trades(active)
    except Exception as e:
        log.error(f"Tracking error: {e}")


# ══════════════════════════════════════════════
# Dashboard סטטיסטי
# ══════════════════════════════════════════════

def send_daily_dashboard():
    if not os.path.exists(LOG_FILE):
        return
    try:
        df = pd.read_csv(LOG_FILE)
        if df.empty or 'outcome' not in df.columns:
            return

        total   = len(df)
        wins    = len(df[df['outcome'] == 'WIN'])
        wr      = (wins / total) * 100 if total > 0 else 0
        pnl_sum = df['pnl'].sum() if 'pnl' in df.columns else 0

        grade_lines = ""
        for g in ['A+', 'A']:
            sub = df[df['grade'] == g]
            if not sub.empty:
                sw = len(sub[sub['outcome'] == 'WIN'])
                grade_lines += f"• Grade {g}: `WR {(sw/len(sub))*100:.1f}%` ({len(sub)} עסקאות)\n"

        # פילוח לפי מצב AGGRESSIVE / MODERATE
        mode_lines = ""
        if 'mode' in df.columns:
            for m in ['AGGRESSIVE', 'MODERATE']:
                sub = df[df['mode'] == m]
                if not sub.empty:
                    sw = len(sub[sub['outcome'] == 'WIN'])
                    mp = sub['pnl'].sum()
                    mode_lines += f"• {m}: `WR {(sw/len(sub))*100:.1f}%` | `${mp:.2f}` ({len(sub)} עסקאות)\n"

        portfolio = load_portfolio()
        msg = (f"📊 *DAYS-BOT V4 — DASHBOARD יומי*\n"
               f"━━━━━━━━━━━━━━━━━\n"
               f"📈 סה''כ עסקאות: `{total}` | Win Rate: `{wr:.1f}%`\n"
               f"💰 רווח/הפסד מצטבר: `${pnl_sum:.2f}`\n"
               f"💼 יתרת תיק: `${portfolio['balance']}` | מצב: `{portfolio['mode']}`\n\n"
               f"🎯 *לפי ציון:*\n{grade_lines}\n"
               f"⚙️ *לפי מצב מערכת:*\n{mode_lines}"
               f"━━━━━━━━━━━━━━━━━\n"
               f"המערכת מתייעלת אוטומטית לפי ביצועים.")
        send_telegram(msg)
    except Exception as e:
        log.error(f"Dashboard error: {e}")


# ══════════════════════════════════════════════
# תשתיות עזר
# ══════════════════════════════════════════════

def market_status() -> bool:
    ny = pytz.timezone("US/Eastern")
    t  = datetime.now(ny)
    if t.weekday() > 4:
        return False
    after_open  = (t.hour > 9) or (t.hour == 9 and t.minute >= 30)
    before_close = t.hour < 16
    return after_open and before_close

def send_telegram(msg: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID,
                                 "text": msg, "parse_mode": "Markdown"}, timeout=10)
    except:
        pass

def log_trade(data: dict):
    try:
        pd.DataFrame([data]).to_csv(
            LOG_FILE, mode='a',
            header=not os.path.exists(LOG_FILE), index=False)
    except:
        pass


# ══════════════════════════════════════════════
# לולאת ריצה ראשית
# ══════════════════════════════════════════════

def run_scanner():
    log.info("🚀 DAYS-BOT V4 — Dual-Mode Risk Engine Live")
    portfolio = load_portfolio()
    profile   = get_risk_profile(portfolio["balance"])

    send_telegram(
        f"🟢 *DAYS-BOT V4 Active*\n"
        f"💼 יתרת תיק: `${portfolio['balance']}`\n"
        f"⚙️ מצב: `{profile['mode']}`\n"
        f"📌 סיכון לעסקה: `{profile['risk_pct']*100:.0f}%` | "
        f"יחס R:R: `1:{profile['rr_ratio']}`\n"
        f"🎯 ציון מינימלי: `{profile['min_score']}/12`"
    )

    last_scan_time = 0
    dashboard_sent = False
    candidates     = []

    while True:
        try:
            ny_tz   = pytz.timezone("US/Eastern")
            ny_time = datetime.now(ny_tz)

            # Dashboard יומי בסיום מסחר
            if ny_time.hour == 16 and ny_time.minute == 5 and not dashboard_sent:
                send_daily_dashboard()
                dashboard_sent = True
            if ny_time.hour != 16:
                dashboard_sent = False

            if not market_status():
                time.sleep(30)
                continue

            # מעקב פוזיציות פתוחות
            track_open_positions()

            # סריקה כל 5 דקות
            if time.time() - last_scan_time > 300:
                candidates     = get_dynamic_gainers()
                last_scan_time = time.time()

            # לא חורגים מ-PDT Rule
            if not can_trade_today():
                time.sleep(60)
                continue

            # טעינת פרופיל עדכני (ייתכן שהתיק השתנה)
            portfolio = load_portfolio()
            profile   = get_risk_profile(portfolio["balance"])

            for sym, price in candidates:
                active = load_active_trades()
                if sym in active:
                    continue
                if sym in alerted_symbols:
                    elapsed = datetime.now() - alerted_symbols[sym]
                    if elapsed < timedelta(minutes=COOLDOWN_MINUTES):
                        continue

                setup = analyze_and_score_stock(sym, profile)
                if setup:
                    alerted_symbols[sym] = datetime.now()
                    setup['timestamp']   = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                    active[sym] = setup
                    save_active_trades(active)
                    register_trade()

                    rr_label = f"1:{setup['rr_ratio']}"
                    msg = (f"🦅 *🚨 איתות קנייה: {setup['symbol']} (Grade {setup['grade'