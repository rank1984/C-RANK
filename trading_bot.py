import os
import sys
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
from dotenv import load_dotenv  # הוספנו את הספרייה הזו

# טעינת משתני הסביבה (חשוב להריץ לפני שקוראים ל-os.environ)
load_dotenv()

# ══════════════════════════════════════════════════════════════════════
# DAYS-BOT V7.0 — Unified Market Watchlist & Execution Engine
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

# פרמטרי סריקה בסיסיים
MIN_PRICE            = 1.5
MAX_PRICE            = 25.0
MIN_VOLUME           = 500_000
MAX_FLOAT            = 200_000_000
AGGRESSIVE_THRESHOLD = 1_000.0

# קבצי מערכת קשיחים
PORTFOLIO_FILE   = "portfolio_state.json"
STATE_FILE       = "active_trades.json"
LOG_FILE         = "trade_log.csv"
BEST_CONFIG_FILE = "best_config.json"
COOLDOWN_FILE    = "cooldown_state.json"
WATCHLIST_FILE   = "daily_watchlist.csv"

COOLDOWN_MINUTES = 60
MAX_DAILY_TRADES = 3  # הגנת PDT

# רשת אופטימיזציה (Param Grid V6)
PARAM_GRID = {
    "rvol_min":   [2.5, 3.0, 4.0],
    "gap_min":    [5.0, 10.0, 15.0],
    "float_max":  [50_000_000, 100_000_000, 200_000_000],
    "risk_pct":   [0.05, 0.10, 0.15],
    "rr_ratio":   [2.0, 2.5, 3.0],
    "score_min":  [7, 8, 9]
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("DAYS_BOT_V7_0")


# ══════════════════════════════════════════════════════════════════════
# 📁 ניהול מצב והתמדה (Persistence Layers)
# ══════════════════════════════════════════════════════════════════════

def load_portfolio():
    defaults = {
        "balance": 250.0, 
        "mode": "AGGRESSIVE", 
        "peak_balance": 250.0,
        "daily_trade_count": 0,
        "daily_trade_date": "",
        "last_optimization_date": "",
        "last_dashboard_date": ""
    }
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

def load_cooldowns():
    if not os.path.exists(COOLDOWN_FILE):
        return {}
    try:
        with open(COOLDOWN_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_cooldowns(data):
    with open(COOLDOWN_FILE, "w") as f:
        json.dump(data, f, indent=4)

def load_watchlist():
    if not os.path.exists(WATCHLIST_FILE):
        return []
    try:
        df = pd.read_csv(WATCHLIST_FILE)
        if df.empty:
            return []
        return list(zip(df['symbol'], df['price']))
    except:
        return []

def log_trade(data):
    file_exists = os.path.exists(LOG_FILE)
    df = pd.DataFrame([data])
    df.to_csv(LOG_FILE, mode='a', header=not file_exists, index=False)

def can_trade_today() -> bool:
    portfolio = load_portfolio()
    today = datetime.now().strftime("%Y-%m-%d")
    if portfolio.get("daily_trade_date") != today:
        portfolio["daily_trade_date"] = today
        portfolio["daily_trade_count"] = 0
        save_portfolio(portfolio)
    return portfolio["daily_trade_count"] < MAX_DAILY_TRADES

def register_trade():
    portfolio = load_portfolio()
    today = datetime.now().strftime("%Y-%m-%d")
    if portfolio.get("daily_trade_date") != today:
        portfolio["daily_trade_date"] = today
        portfolio["daily_trade_count"] = 1
    else:
        portfolio["daily_trade_count"] += 1
    save_portfolio(portfolio)

def get_risk_profile(balance: float) -> dict:
    if balance < AGGRESSIVE_THRESHOLD:
        return {
            "mode":           "AGGRESSIVE",
            "risk_pct":       0.15,
            "rr_ratio":       2.5,
            "min_score":      7,       
            "min_grade":      "B+",
            "max_risk_pct":   0.12,
        }
    else:
        return {
            "mode":           "MODERATE",
            "risk_pct":       0.05,
            "rr_ratio":       2.5,
            "min_score":      7,       
            "min_grade":      "B+",
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


# ══════════════════════════════════════════════════════════════════════
# 🧠 מנוע האופטימיזציה האוטונומי (Auto Optimizer Core)
# ══════════════════════════════════════════════════════════════════════

def run_auto_optimization():
    log.info("🧠 Auto Optimizer: Starting parameter matrix optimization...")
    if not os.path.exists(LOG_FILE):
        log.info("🧠 Auto Optimizer: No trade history found yet. Skipping simulation.")
        return None, 0.0

    try:
        df = pd.read_csv(LOG_FILE).dropna()
        if len(df) < 30:
            log.info(f"🧠 Auto Optimizer: Insufficient data ({len(df)}/30 trades). Cold-start protection active.")
            return None, 0.0

        keys = list(PARAM_GRID.keys())
        values = list(PARAM_GRID.values())

        best_score = -999.0
        best_config = None

        for combo in product(*values):
            config = dict(zip(keys, combo))
            
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

            expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)
            stability_penalty = np.log(len(filtered) + 1)
            score = expectancy * stability_penalty

            if score > best_score:
                best_score = score
                best_config = config

        if best_config:
            output = {
                "best_config": best_config, 
                "score": float(best_score), 
                "optimized_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            with open(BEST_CONFIG_FILE, "w") as f:
                json.dump(output, f, indent=4)
            log.info(f"🧠 Auto Optimizer: Success! New configuration saved. Score: {best_score:.2f}")
            return best_config, best_score

    except Exception as e:
        log.error(f"🧠 Auto Optimizer Error: {e}")
    
    return None, 0.0

def load_optimized_config():
    if not os.path.exists(BEST_CONFIG_FILE):
        return None
    try:
        with open(BEST_CONFIG_FILE, "r") as f:
            return json.load(f).get("best_config")
    except:
        return None


# ══════════════════════════════════════════════════════════════════════
# 📰 מנוע News Catalyst (Finnhub API Core)
# ══════════════════════════════════════════════════════════════════════

def check_news_catalyst(sym: str):
    if not FINNHUB_API_KEY:
        return False, "No Finnhub Key"
    try:
        today_str = datetime.now().strftime('%Y-%m-%d')
        yesterday_str = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        url = f"https://finnhub.io/api/v1/company-news?symbol={sym}&from={yesterday_str}&to={today_str}&token={FINNHUB_API_KEY}"
        res = requests.get(url, timeout=7)
        if res.status_code == 200:
            news_list = res.json()
            if news_list and len(news_list) > 0:
                latest_headline = news_list[0].get('headline', 'Catalyst Found').replace('"', "'")
                return True, latest_headline
    except Exception as e:
        log.error(f"Error checking news for {sym}: {e}")
    return False, "No Catalyst"


# ══════════════════════════════════════════════════════════════════════
# 📋 ניהול רשימת מעקב וסריקת פרימרקט (Watchlist V6.1)
# ══════════════════════════════════════════════════════════════════════

def run_premarket_scanner():
    log.info("🌅 DAYS-BOT: מריץ סורק פרימרקט ומייצר Watchlist ממוקד...")
    raw_candidates = get_dynamic_gainers()
    if not raw_candidates:
        log.info("🌅 לא נמצאו מניות עולות בפרימרקט.")
        return

    portfolio = load_portfolio()
    profile   = get_risk_profile(portfolio["balance"])
    watchlist_data = []
    
    for sym, price in raw_candidates:
        setup = analyze_and_score_stock(sym, profile)
        if setup:
            if setup.get('pm_high', 0) < setup['price']:
                setup['pm_high'] = round(setup['price'] * 1.005, 2)
            
            if setup.get('stop', 0) >= setup['price']:
                setup['stop'] = round(setup['price'] * 0.97, 2)
                
            watchlist_data.append(setup)

    if not watchlist_data:
        log.info("🌅 אף מניה לא עברה את פילטר הסינון הקשיח עבור ה-Watchlist.")
        if os.path.exists(WATCHLIST_FILE):
            os.remove(WATCHLIST_FILE)
        return

    watchlist_data.sort(key=lambda x: (x["score"], x["ai_pct"]), reverse=True)
    
    df_watchlist = pd.DataFrame(watchlist_data)
    df_watchlist[["symbol", "price", "score", "ai_pct"]].to_csv(WATCHLIST_FILE, index=False)
    log.info(f"💾 ה-Watchlist נשמר בהצלחה! מכיל {len(watchlist_data)} מניות מובילות.")

    top_3 = watchlist_data[:3]
    msg = "🦅 *DAYS-BOT — SCORE CARD איתותים יומי* 🦅\n"
    msg += "━━━━━━━━━━━━━━━━━\n\n"
    
    for i, setup in enumerate(top_3, 1):
        current_price = setup['price']
        target_1 = round(current_price * 1.02, 2)  
        
        pm_high = setup['pm_high']
        stop_loss = setup['stop']
        target_2 = setup.get('target', round(current_price * 1.05, 2))
        rr_ratio = setup.get('rr_ratio', profile.get('rr_ratio', 2.5))
        
        raw_rvol = setup.get('rvol', 1.5)
        try:
            rvol_val = float(raw_rvol)
            rvol_str = f"{rvol_val}x"
            if rvol_val < 1.0:
                rvol_str += " ⚠️ (ווליום חלש!)"
        except:
            rvol_str = f"{raw_rvol}x"
        
        expected_min = setup['gap'] * 0.8
        expected_max = setup['gap'] * 1.5
        
        msg += f"{i}️⃣ המניה המובילה: *{setup['symbol']}* (Grade {setup['grade']})\n"
        msg += f"   • 🤖 ביטחון AI: `{setup['ai_pct']}%` | ציון טכני: `{setup['score']}/12`\n"
        msg += f"   • 📈 זינוק (Gap): `{setup['gap']}%` | מחזור (RVOL): `{rvol_str}`\n"
        msg += f"   • 📰 קטליזטור: `{setup['news_title'][:45]}`\n\n"
        msg += f"   📋 *תוכנית עבודה מוצעת למסחר (Score Card):*\n"
        msg += f"   • ⚡ *טריגר כניסה (פריצה):* מעל `${pm_high}`\n"
        msg += f"   • 🛑 *סטופ לוס (הגנה):* `${stop_loss}`\n"
        msg += f"   • 🎯 *יעד 1 (נעילת 50% רווח):* `${target_1}` (+2.0%)\n"
        msg += f"   • 🎯 *יעד 2 (ריצה עם השאר):* `${target_2}` (יחס 1:{rr_ratio})\n"
        msg += f"   📊 *צפי תנועה יומי ממוצע:* `{expected_min:.1f}% עד {expected_max:.1f}%`\n"
        msg += "━━━━━━━━━━━━━━━━━\n\n"
    
    msg += f"📋 סה''כ מניות חמות במעקב חם להיום: `{len(watchlist_data)}`"
    send_telegram(msg)


# ══════════════════════════════════════════════════════════════════════
# 🔍 סריקת גיינרים וחישוב ביטחון AI
# ══════════════════════════════════════════════════════════════════════

def get_dynamic_gainers():
    url = "https://data.alpaca.markets/v1beta1/screener/stocks/movers"
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
# 📊 ניתוח טכני וסימולציית Slippage ריאלית
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

        # חישוב קו VWAP
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

        # שילוב מנוע הלימוד האוטונומי (V6 Optimal Filters)
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
            
            current_risk_pct = opt_config["risk_pct"]
            current_rr_ratio = opt_config["rr_ratio"]
            current_min_score = opt_config["score_min"]
        else:
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

        # 🚀 [שדרוג 3 - חלק א']: הוספת תנאי Runner Mode מתחת להגדרת ה-Grade
        runner = (
            score >= 8 and
            rvol >= 3 and
            gap_pct >= 20 and
            float_shares <= 50_000_000 and
            has_news
        )

        # החלת קנס Slippage ריאלי של 0.15% בכניסת מרקט
        slippage_pct = 0.0015
        entry_price  = round(raw_price * (1 + slippage_pct), 2)

        stop_loss   = cur['Low'] - 0.02
        risk_amount = entry_price - stop_loss
        if risk_amount <= 0:
            return None

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

        # 🚀 [שדרוג 3 - חלק ב']: החלפת חישוב ה-Target הרגיל ביעד מותאם מבוסס Runner
        if runner:
            target = round(entry_price * 1.30, 2)
        else:
            target = round(
                entry_price +
                (risk_amount * current_rr_ratio),
                2
            )

        # 🚀 [שדרוג 3 - חלק ג']: הוספת מפתח "runner" לתוך מילון ה-return
        return {
            "symbol":        sym,
            "raw_price":     round(raw_price, 2),
            "price":         entry_price,
            "pm_high":       round(pm_high, 2),
            "vwap":          round(last_vwap, 2),
            "stop":          round(stop_loss, 2),
            "target":        target,
            "runner":        runner,
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
# 🔍 מעקב פוזיציות וניהול עסקאות פתוחות
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
# 📊 דשבורד, זמנים ותקשורת
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
        
        msg = (f"📊 *DAYS-BOT — DASHBOARD יומי*\n"
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


# 🚀 [שדרוג 1]: החלפת פונקציית הטלגרם הישנה במנגנון Logging מורחב ומאובטח
def send_telegram(msg: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.error("Telegram credentials missing")
        return

    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": msg,
                "parse_mode": "Markdown"
            },
            timeout=15
        )

        if r.status_code != 200:
            log.error(f"Telegram Error: {r.text}")
        else:
            log.info("Telegram message sent")

    except Exception as e:
        log.error(f"Telegram Exception: {e}")


# 🚀 [שדרוג 2 - חלק א']: הוספת פילטר הגנת דקות הפתיחה (Opening Bell Filter)
def opening_bell_filter():
    ny = datetime.now(pytz.timezone("US/Eastern"))

    if ny.hour == 9 and ny.minute < 35:
        return False

    return True


# ══════════════════════════════════════════════════════════════════════
# 🚀 פונקציית הניהול הראשית (GitHub Actions Single-Run Handler)
# ══════════════════════════════════════════════════════════════════════

def run_scanner():
    log.info("🚀 DAYS-BOT — Running Scheduled Scan Step")
    portfolio = load_portfolio()
    profile   = get_risk_profile(portfolio["balance"])
    today_str = datetime.now().strftime("%Y-%m-%d")
    ny_time   = datetime.now(pytz.timezone("US/Eastern"))
    cooldowns = load_cooldowns()

    # 1. מנוע אופטימיזציה אוטונומי
    if portfolio.get("last_optimization_date") != today_str:
        opt_config, opt_score = run_auto_optimization()
        if opt_config:
            send_telegram(
                f"🧠 *AUTO-OPTIMIZATION COMPLETE*\n"
                f"━━━━━━━━━━━━━━━━━\n"
                f"🎯 ציון מותאם חדש: `{opt_score:.2f}`\n"
                f"📈 יחס סיכון/סיכוי אופטימלי: `1:{opt_config['rr_ratio']}`\n"
                f"🛡️ סיכון תיק מומלץ: `{opt_config['risk_pct']*100:.1f}%`\n"
                f"⚙️ פילטרים עודכנו לבסיס הרווחי ביותר בהיסטוריה."
            )
        portfolio["last_optimization_date"] = today_str
        save_portfolio(portfolio)

    # 2. שליחת דשבורד יומי בסגירת המסחר
    if ny_time.hour == 16 and 0 <= ny_time.minute <= 15:
        if portfolio.get("last_dashboard_date") != today_str:
            send_daily_dashboard()
            portfolio["last_dashboard_date"] = today_str
            save_portfolio(portfolio)

    # 3. בדיקת שעות מסחר
    if not market_status():
        log.info("💤 הבורסה סגורה כרגע. יוצאים וממתינים למחזור ה-Cron הבא.")
        return

    # 4. מעקב פוזיציות פתוחות
    track_open_positions()

    # 🚀 [שדרוג 2 - חלק ב']: הטמעת חסימת הפעילות בדקות הפתיחה מיד אחרי המעקב
    if not opening_bell_filter():
        log.info("Opening Bell Protection Active")
        return

    # 5. בדיקת הגנת PDT מבוססת JSON
    if not can_trade_today():
        log.info("🛑 הגנת PDT פעילה: הגעת למגבלת העסקאות היומית. מדלג על סריקה.")
        return

    # 6. טעינת רשימת המעקב
    candidates = load_watchlist()
    if not candidates:
        log.info("📋 ה-Watchlist ריק או לא קיים. אין מניות למעקב במחזור הנוכחי.")
        return

    updated_cooldowns = False

    for sym, price in candidates:
        active = load_active_trades()
        if sym in active: 
            continue
            
        # בדיקת Cooldown מבוססת קובץ קשיח
        if sym in cooldowns:
            last_alert_time = datetime.strptime(cooldowns[sym], '%Y-%m-%d %H:%M:%S')
            if datetime.now() - last_alert_time < timedelta(minutes=COOLDOWN_MINUTES):
                continue

        setup = analyze_and_score_stock(sym, profile)
        if setup:
            now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            setup['timestamp'] = now_str
            cooldowns[sym] = now_str
            updated_cooldowns = True

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
            
            if setup.get("runner", False):
                msg += "\n🚀 *⚡ מניית RUNNER זוהתה! יעד רווח מוגדל ל-30%.*"
            
            send_telegram(msg)
            log.info(f"💥 Live Trade Executed & Optimally Logged for {sym}")

    if updated_cooldowns:
        save_cooldowns(cooldowns)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--premarket":
        run_premarket_scanner()
    else:
        run_scanner()
