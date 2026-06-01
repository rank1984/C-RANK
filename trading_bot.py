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
from itertools import product

# ══════════════════════════════════════════════════════════════════════
# DAYS-BOT V6.0 — Auto Optimization & Self-Learning Engine
# ══════════════════════════════════════════════════════════════════════
# ארכיטקטורה:
# 1. Scanner & Execution Engine (Slippage + Risk Framework)
# 2. Performance Logger & Math Expectancy Engine
# 3. Dynamic Regime Protection (Mode Switching Framework)
# 4. Auto Optimizer Loop (Grid Search + Stability Penalty Feedback)
# ══════════════════════════════════════════════════════════════════════

ALPACA_API_KEY    = os.environ.get("ALPACA_API_KEY", "").strip()
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "").strip()
TELEGRAM_TOKEN    = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID  = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
FINNHUB_API_KEY   = os.environ.get("FINNHUB_API_KEY", "").strip()

HEADERS = {
    "APCA-API-KEY-ID": ALPACA_API_KEY,
    "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
    "accept": "application/json"
}

# ── פרמטרי סריקה בסיסיים ומערך אופטימיזציה ──
MIN_PRICE            = 1.5
MAX_PRICE            = 25.0
MIN_VOLUME           = 500_000
MAX_FLOAT            = 200_000_000
AGGRESSIVE_THRESHOLD = 1_000.0

# קבצי מערכת
PORTFOLIO_FILE   = "portfolio_state.json"
STATE_FILE       = "active_trades.json"
LOG_FILE         = "trade_log.csv"
BEST_CONFIG_FILE = "best_config.json"

COOLDOWN_MINUTES = 60
MAX_DAILY_TRADES = 3  # PDT Protection

# ── רשת אופטימיזציה (Param Grid V6) ──
PARAM_GRID = {
    "rvol_min":   [2.5, 3.0, 4.0],
    "gap_min":    [5.0, 10.0, 15.0],
    "float_max":  [50_000_000, 100_000_000, 200_000_000],
    "risk_pct":   [0.05, 0.10, 0.15],
    "rr_ratio":   [2.0, 2.5, 3.0],
    "score_min":  [7, 8, 9]
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("DAYS_BOT_V6_0")

alerted_symbols   = {}
daily_trade_count = {"date": "", "count": 0}


# ══════════════════════════════════════════════════════════════════════
# 🔥 רכיב 4 החדש: מנוע האופטימיזציה האוטונומי (Auto Optimizer Core)
# ══════════════════════════════════════════════════════════════════════

def run_auto_optimization():
    """סורק את היסטוריית העסקאות האמיתית, מריץ סימולציות ומוצא את הסטאפ המנצח"""
    log.info("🧠 Auto Optimizer: Starting parameter matrix optimization...")
    if not os.path.exists(LOG_FILE):
        log.info("🧠 Auto Optimizer: No trade history found yet. Skipping simulation.")
        return None, 0.0

    try:
        df = pd.read_csv(LOG_FILE).dropna()
        # מניעת Overfitting על מדגם קטן מדי - דורש לפחות 10 עסקאות סגורות
        if len(df) < 10:
            log.info(f"🧠 Auto Optimizer: Insufficient data ({len(df)}/10 trades). Cold-start protection active.")
            return None, 0.0

        keys = list(PARAM_GRID.keys())
        values = list(PARAM_GRID.values())

        best_score = -999.0
        best_config = None

        # ריצה על מכפלת כל הקומבינציות האפשריות ברשת
        for combo in product(*values):
            config = dict(zip(keys, combo))
            
            # סימולציית פילטרים מקומית על ה-Dataframe
            filtered = df[
                (df["rvol"] >= config["rvol_min"]) &
                (df["gap"] >= config["gap_min"]) &
                (df["float"] <= config["float_max"]) &
                (df["score"] >= config["score_min"])
            ]

            if len(filtered) == 0:
                continue

            wins_count = len(filtered[filtered["outcome"] == "WIN"])
            win_rate = wins_count / len(filtered)

            avg_win = filtered[filtered["outcome"] == "WIN"]["pnl"].mean() if wins_count > 0 else 0.0
            avg_loss = abs(filtered[filtered["outcome"] == "LOSS"]["pnl"].mean()) if len(filtered) > wins_count else 0.0

            # חישוב תוחלת מתמטית מותאמת
            expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)

            # קנס יציבות (Stability Penalty) لمنע התאמת יתר לפלחים קטנים מדי
            stability_penalty = np.log(len(filtered) + 1)
            score = expectancy * stability_penalty

            if score > best_score:
                best_score = score
                best_config = config

        if best_config:
            # שמירת הקונפיגורציה האופטימלית לקובץ מערכת
            output = {"best_config": best_config, "score": float(best_score), "optimized_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
            with open(BEST_CONFIG_FILE, "w") as f:
                json.dump(output, f, indent=4)
            log.info(f"🧠 Auto Optimizer: Success! New configuration saved. Score: {best_score:.2f}")
            return best_config, best_score

    except Exception as e:
        log.error(f"🧠 Auto Optimizer Error: {e}")
    
    return None, 0.0

def load_optimized_config():
    """טוען את החוקים המשופרים שהמערכת גזרה מהמסחר של עצמה"""
    if not os.path.exists(BEST_CONFIG_FILE):
        return None
    try:
        with open(BEST_CONFIG_FILE, "r") as f:
            return json.load(f).get("best_config")
    except:
        return None


# ══════════════════════════════════════════════════════════════════════
# ניהול מצב התיק ופרופילי סיכון (Regime Detector & Balance Control)
# ══════════════════════════════════════════════════════════════════════

def load_portfolio():
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
    """קביעת פרופיל סיכון בסיסי במקרה שאין עדיין קונפיגורציה מאופטמזת"""
    if balance < AGGRESSIVE_THRESHOLD:
        return {
            "mode":           "AGGRESSIVE",
            "risk_pct":       0.18,
            "rr_ratio":       3.0,
            "min_score":      10,
            "min_grade":      "A+",
            "max_risk_pct":   0.12,
        }
    else:
        return {
            "mode":           "MODERATE",
            "risk_pct":       0.06,
            "rr_ratio":       2.5,
            "min_score":      8,
            "min_grade":      "A",
            "max_risk_pct":   0.08,
        }

def update_balance_after_trade(pnl: float):
    portfolio = load_portfolio()
    old_balance = portfolio["balance"]
    old_mode    = portfolio["mode"]

    portfolio["balance"] = round(portfolio["balance"] + pnl, 2)

    if portfolio["balance"] > portfolio.get("peak_balance", old_balance):
        portfolio["peak_balance"] = portfolio["balance"]

    new_profile = get_risk_profile(portfolio["balance"])
    portfolio["mode"] = new_profile["mode"]

    save_portfolio(portfolio)

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

def can_trade_today() -> bool:
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


# ══════════════════════════════════════════════════════════════════════
# מנוע News Catalyst משודרג (Finnhub API Core)
# ══════════════════════════════════════════════

def check_news_catalyst(sym: str):
    keywords = ["earnings", "revenue", "contract", "fda", "buyout", "merger",
                "partnership", "deal", "quarterly", "approval", "alliance",
                "guidance", "upgrade", "acquisition"]
    
    if FINNHUB_API_KEY:
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            url = f"https://finnhub.io/api/v1/company-news?symbol={sym}&from={yesterday}&to={today}&token={FINNHUB_API_KEY}"
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                news_feed = resp.json()
                for item in news_feed[:10]:
                    title = item.get('headline', '').lower()
                    if any(kw in title for kw in keywords):
                        return True, item.get('headline')
                return False, "No Finnhub Catalyst"
        except Exception as e:
            log.warning(f"Finnhub error for {sym}, falling back to yfinance: {e}")

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


# ══════════════════════════════════════════════════════════════════════
# סריקת גיינרים דינמית וחישוב ביטחון AI
# ══════════════════════════════════════════════════════════════════════
def get_dynamic_gainers():
    url = "https://data.alpaca.markets/v1beta1/screener/stocks/movers?market_type=stocks"
    try:
        res = requests.get(url, headers=HEADERS)
        if res.status_code != 200:
            log.error(f"Alpaca API Error {res.status_code}: {res.text}")
            return []
        
        data = res.json()
        gainers = data.get('gainers', [])
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
        data = res.json()
        gainers = data.get('gainers', [])
        # ... (שאר הקוד נשאר אותו דבר)

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

def calculate_ai_confidence(rvol: float, gap: float, float_shares: float, has_news: bool, above_vwap: bool, above_pm_high: bool) -> int:
    confidence = 50.0
    if has_news:                  confidence += 15
    if rvol > 5.0:                confidence += 12
    elif rvol > 3.0:              confidence += 7
    if float_shares < 20_000_000: confidence += 15
    elif float_shares < 50_000_000: confidence += 10
    if above_vwap and above_pm_high: confidence += 10
    elif above_vwap:              confidence += 4
    if 15.0 <= gap <= 35.0:       confidence += 8
    elif gap > 35.0:              confidence += 3

    if has_news and rvol > 5.0 and float_shares < 50_000_000:
        confidence += 12  
    return int(min(max(confidence, 10), 99))


# ══════════════════════════════════════════════════════════════════════
# ניתוח טכני משולב אופטימיזציה ולוגיקת ביצוע ריאלית
# ══════════════════════════════════════════════════════════════════════

def analyze_and_score_stock(sym: str, profile: dict):
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
        raw_price = cur['Close']
        last_vwap  = cur['VWAP']

        df['Datetime'] = pd.to_datetime(df['Datetime']).dt.tz_convert('US/Eastern')
        df.set_index('Datetime', inplace=True)
        premarket = df.between_time('04:00', '09:30')
        pm_high   = premarket['High'].max() if not premarket.empty else df['Open'].iloc[0]

        avg_vol   = df['Volume'].rolling(10).mean().iloc[-1]
        rvol      = cur['Volume'] / avg_vol if avg_vol > 0 else 0

        # ── 🔥 שילוב מנוע הלימוד העצמי (V6 Optimization Engine Filter) ──
        opt_config = load_optimized_config()
        if opt_config:
            if rvol < opt_config["rvol_min"]:
                log.info(f"🧠 Filter Blocked [{sym}]: RVOL {rvol:.1f} < Optimal {opt_config['rvol_min']}")
                return None
            if gap_pct < opt_config["gap_min"]:
                log.info(f"🧠 Filter Blocked [{sym}]: Gap {gap_pct:.1f}% < Optimal {opt_config['gap_min']}%")
                return None
            if float_shares > opt_config["float_max"]:
                log.info(f"🧠 Filter Blocked [{sym}]: Float {float_shares:,} > Optimal {opt_config['float_max']:,}")
                return None
            
            # החלת ניהול סיכונים ויעדים שעברו אופטימיזציה
            current_risk_pct = opt_config["risk_pct"]
            current_rr_ratio = opt_config["rr_ratio"]
            current_min_score = opt_config["score_min"]
        else:
            # Fallback בטוח לפרמטרים הדינמיים של התיק מ-V5
            current_risk_pct = profile["risk_pct"]
            current_rr_ratio = profile["rr_ratio"]
            current_min_score = profile["min_score"]

        # חישוב הציון הטכני
        score = 0
        if rvol > 3.0:                score += 2
        if raw_price > last_vwap:     score += 2
        if raw_price > pm_high:       score += 2
        if float_shares < 50_000_000:  score += 2
        if gap_pct > 10.0:            score += 2

        has_news, news_title = check_news_catalyst(sym)
        if has_news:
            score += 2

        if score < current_min_score:
            return None

        grade = "A+" if score >= 10 else "A"

        # החלת קנס Slippage ריאלי של 0.15% על פקודת המרקט
        slippage_pct = 0.0015
        entry_price  = round(raw_price * (1 + slippage_pct), 2)

        stop_loss   = cur['Low'] - 0.02
        risk_amount = entry_price - stop_loss
        if risk_amount <= 0:
            return None

        # מניעת עסקאות עם סיכון טכני קיצוני מדי לפי פרופיל השוק
        max_allowed_risk = profile["max_risk_pct"] if not opt_config else 0.12
        if risk_amount / entry_price > max_allowed_risk:
            return None

        above_vwap    = entry_price > last_vwap
        above_pm_high = entry_price > pm_high
        ai_pct = calculate_ai_confidence(rvol, gap_pct, float_shares, has_news, above_vwap, above_pm_high)

        portfolio   = load_portfolio()
        dollar_risk = portfolio["balance"] * current_risk_pct
        shares      = int(dollar_risk / risk_amount)
        if shares == 0:
            return None

        cost   = round(shares * entry_price, 2)
        target = round(entry_price + (risk_amount * current_rr_ratio), 2)

        return {
            "symbol":        sym,
            "raw_price":     round(raw_price, 2),
            "price":         entry_price,
            "pm_high":       round(pm_high, 2),
            "vwap":          round(last_vwap, 2),
            "stop":          round(stop_loss, 2),
            "target":        target,
            "shares":        shares,
            "cost":          cost,
            "score":         score,
            "grade":         grade,
            "ai_pct":        ai_pct,
            "rvol":          round(rvol, 1),
            "float":         float_shares,
            "gap":           round(gap_pct, 1),
            "news_title":    news_title if has_news else "No Catalyst",
            "mode":          profile["mode"],
            "rr_ratio":      current_rr_ratio,
            "slippage_paid": round(entry_price - raw_price, 3)
        }
    except Exception as e:
        log.error(f"Analysis error {sym}: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════
# מעקב פוזיציות וניהול קבצים
# ══════════════════════════════════════════════════════════════════════

def load_active_trades():
    if not os.path.exists(STATE_FILE): return {}
    try:
        with open(STATE_FILE, "r") as f: return json.load(f)
    except: return {}

def save_active_trades(trades):
    with open(STATE_FILE, "w") as f: json.dump(trades, f, indent=4)

def track_open_positions():
    active = load_active_trades()
    if not active: return

    try:
        url      = f"https://data.alpaca.markets/v2/stocks/snapshots?symbols={','.join(active.keys())}&feed=iex"
        snap_res = requests.get(url, headers=HEADERS).json()

        for sym in list(active.keys()):
            if sym not in snap_res or not snap_res[sym]: continue
            cur_price = snap_res[sym]['dailyBar'].get('c', 0)
            if cur_price == 0: continue

            trade = active[sym]
            win   = cur_price >= trade['target']
            loss  = cur_price <= trade['stop']

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
                    "ai_pct":          trade.get('ai_pct', 50),
                    "rvol":            trade['rvol'],
                    "gap":             trade['gap'],
                    "float":           trade['float'],
                    "entry_price":     trade['price'],
                    "stop_loss":       trade['stop'],
                    "target":          trade['target'],
                    "exit_price":      round(cur_price, 2),
                    "duration_min":    duration,
                    "outcome":         outcome,
                    "pnl":             round(pnl, 2),
                    "rr_ratio":        trade.get('rr_ratio', 2.5),
                }
                log_trade(log_data)
                update_balance_after_trade(pnl)

                portfolio = load_portfolio()
                emoji     = "💰" if win else "🛑"
                msg = (f"{emoji} *עסקה נסגרה: {sym} ({outcome})*\n"
                       f"━━━━━━━━━━━━━━━━━\n"
                       f"🚪 *יציאה:* `${round(cur_price, 2)}` | כניסה ריאלית: `${trade['price']}`\n"
                       f"💵 *רווח/הפסד:* `${round(pnl, 2)}`\n"
                       f"⏱️ *זמן בעסקה:* `{duration} דקות`\n"
                       f"━━━━━━━━━━━━━━━━━\n"
                       f"💼 *יתרת תיק:* `${portfolio['balance']}` | מצב: `{portfolio['mode']}`")
                send_telegram(msg)
                del active[sym]

        save_active_trades(active)
    except Exception as e:
        log.error(f"Tracking error: {e}")


# ══════════════════════════════════════════════════════════════════════
# דשבורד ותשתיות עזר
# ══════════════════════════════════════════════════════════════════════

def send_daily_dashboard():
    if not os.path.exists(LOG_FILE): return
    try:
        df = pd.read_csv(LOG_FILE).dropna()
        if df.empty: return

        total   = len(df)
        wins_df = df[df['outcome'] == 'WIN']
        loss_df = df[df['outcome'] == 'LOSS']
        wr      = (len(wins_df) / total) * 100 if total > 0 else 0
        pnl_sum = df['pnl'].sum()

        avg_win   = wins_df['pnl'].mean() if not wins_df.empty else 0
        avg_loss  = abs(loss_df['pnl'].mean()) if not loss_df.empty else 0
        expectancy = ((len(wins_df)/total) * avg_win) - ((len(loss_df)/total) * avg_loss) if total > 0 else 0

        portfolio = load_portfolio()
        opt_status = "✅ פעיל ומעודכן" if os.path.exists(BEST_CONFIG_FILE) else "⏳ בהרצה (צובר דאטה)"
        
        msg = (f"📊 *DAYS-BOT V6.0 — DASHBOARD יומי*\n"
               f"━━━━━━━━━━━━━━━━━\n"
               f"📈 סה''כ עסקאות: `{total}` | Win Rate: `{wr:.1f}%`\n"
               f"💰 רווח מצטבר: `${pnl_sum:.2f}`\n"
               f"🎲 *תוחלת מתמטית:* `${expectancy:.2f}` לעסקה\n"
               f"🤖 *מנוע אופטימיזציה:* `{opt_status}`\n"
               f"💼 יתרת תיק: `${portfolio['balance']}` | מצב: `{portfolio['mode']}`\n"
               f"━━━━━━━━━━━━━━━━━\n"
               f"כולל סימולציית Slippage מובנית של 0.15% בכל כניסה.")
        send_telegram(msg)
    except Exception as e:
        log.error(f"Dashboard error: {e}")

def market_status() -> bool:
    ny = datetime.now(pytz.timezone("US/Eastern"))
    if ny.weekday() > 4: return False
    return (ny.hour > 9 or (ny.hour == 9 and ny.minute >= 30)) and ny.hour < 16

def send_telegram(msg: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                      json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
    except: pass

def log_trade(data: dict):
    try: pd.DataFrame([data]).to_csv(LOG_FILE, mode='a', header=not os.path.exists(LOG_FILE), index=False)
    except: pass


# ══════════════════════════════════════════════════════════════════════
# לולאת ריצה ראשית ומחזור אופטימיזציה יומי
# ══════════════════════════════════════════════════════════════════════

def run_scanner():
    log.info("🚀 DAYS-BOT V6.0 — Autonomous Auto-Optimization Core Is Active")
    portfolio = load_portfolio()
    profile   = get_risk_profile(portfolio["balance"])

    send_telegram(
        f"🔥 *DAYS-BOT V6.0 Active & Learning*\n"
        f"💼 יתרת תיק: `${portfolio['balance']}` ({profile['mode']})\n"
        f"⚙️ מודל למידה: `Self-Correcting Parameter Grid`\n"
        f"📊 הגנת מ样本: `Cold-Start Protection (Min 10 trades)`"
    )

    last_scan_time = 0
    last_optimization_time = 0
    dashboard_sent = False
    candidates = []

    while True:
        try:
            ny_time = datetime.now(pytz.timezone("US/Eastern"))

            if time.time() - last_optimization_time > 86400:
                opt_config, opt_score = run_auto_optimization()
                if opt_config:
                    send_telegram(
                        f"🧠 *V6 AUTO-OPTIMIZATION COMPLETE*\n"
                        f"━━━━━━━━━━━━━━━━━\n"
                        f"🎯 ציון מותאם חדש: `{opt_score:.2f}`\n"
                        f"📈 יחס סיכון/סיכוי אופטימלי: `1:{opt_config['rr_ratio']}`\n"
                        f"🛡️ סיכון תיק מומלץ: `{opt_config['risk_pct']*100:.1f}%`\n"
                        f"⚙️ פילטרים עודכנו לבסיס הרווחי ביותר בהיסטוריה."
                    )
                last_optimization_time = time.time()

            if ny_time.hour == 16 and ny_time.minute == 5 and not dashboard_sent:
                send_daily_dashboard()
                dashboard_sent = True
            if ny_time.hour != 16:
                dashboard_sent = False

            if not market_status():
                time.sleep(30)
                continue

            track_open_positions()

            if time.time() - last_scan_time > 300:
                candidates = get_dynamic_gainers()
                last_scan_time = time.time()

            if not can_trade_today():
                time.sleep(60)
                continue

            portfolio = load_portfolio()
            profile   = get_risk_profile(portfolio["balance"])

            for sym, price in candidates:
                active = load_active_trades()
                if sym in active: continue
                if sym in alerted_symbols:
                    if datetime.now() - alerted_symbols[sym] < timedelta(minutes=COOLDOWN_MINUTES):
                        continue

                setup = analyze_and_score_stock(sym, profile)
                if setup:
                    alerted_symbols[sym] = datetime.now()
                    setup['timestamp']   = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                    active[sym] = setup
                    save_active_trades(active)
                    register_trade()

                    ai_emoji = "🤖🔥" if setup['ai_pct'] >= 85 else "🤖"
                    msg = (
                        f"🦅 *🚨 איתות קנייה: {setup['symbol']} (Grade {setup['grade']})*\n"
                        f"━━━━━━━━━━━━━━━━━\n"
                        f"{ai_emoji} *התאמת מנוע AI:* `{setup['ai_pct']}%` \n"
                        f"📊 *ציון טכני:* `{setup['score']}/12` | קו: `{setup['mode']}`\n"
                        f"📰 *קטליזטור:* `{setup['news_title']}`\n\n"
                        f"💵 *מחיר מקור:* `${setup['raw_price']}`\n"
                        f"⚡ *כניסה מבוצעת (Slippage):* `${setup['price']}`\n"
                        f"🛑 *סטופ:* `${setup['stop']}` | 🎯 *יעד:* `${setup['target']}`\n"
                        f"━━━━━━━━━━━━━━━━━\n"
                        f"📦 *מניות לקנייה:* {setup['shares']} | עלות פוזיציה: `${setup['cost']}`"
                    )
                    
                    send_telegram(msg)
                    log.info(f"💥 Live Trade Executed & Optimally Logged: {sym}")
                    
            time.sleep(20)
            
        except Exception as e:
            log.error(f"Loop error: {e}")
            time.sleep(20)

if __name__ == "__main__":
    run_scanner()
