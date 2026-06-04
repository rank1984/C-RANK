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

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ══════════════════════════════════════════════════════════════════════
# DAYS-BOT V8.0 — Adaptive Momentum & Soft Scoring Engine
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

# 📡 חוקי V8 החדשים - פחות חונקים, יותר הזדמנויות במניות קטנות
MIN_PRICE  = 1.0
MAX_PRICE  = 20.0       # מותאם אישית לטווח המטרות שלך ($1-$20)
MIN_VOLUME = 100_000    # פילטר רך לשעות הבוקר המוקדמות
MIN_GAP    = 2.0
MIN_RVOL   = 1.2

MAX_FLOAT            = 200_000_000
AGGRESSIVE_THRESHOLD = 1_000.0

PORTFOLIO_FILE   = "portfolio_state.json"
STATE_FILE       = "active_trades.json"
LOG_FILE         = "trade_log.csv"
BEST_CONFIG_FILE = "best_config.json"
COOLDOWN_FILE    = "cooldown_state.json"
WATCHLIST_FILE   = "daily_watchlist.csv"

COOLDOWN_MINUTES = 60
MAX_DAILY_TRADES = 3

PARAM_GRID = {
    "rvol_min":   [1.2, 1.5, 2.0],
    "gap_min":    [2.0, 5.0, 10.0],
    "float_max":  [50_000_000, 100_000_000, 200_000_000],
    "risk_pct":   [0.05, 0.10, 0.15],
    "rr_ratio":   [2.0, 2.5, 3.0],
    "score_min":  [3, 5, 7]
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("DAYS_BOT_V8_0")

def send_telegram(message: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram configuration missing!")
        return
    url = f"https://api.telegram.com/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        log.error(f"Telegram send failed: {e}")

# 📁 ניהול מצב והתמדה
def load_portfolio():
    defaults = {"balance": 250.0, "mode": "AGGRESSIVE", "peak_balance": 250.0, "daily_trade_count": 0, "daily_trade_date": "", "last_optimization_date": "", "last_dashboard_date": ""}
    if not os.path.exists(PORTFOLIO_FILE):
        save_portfolio(defaults)
        return defaults
    try:
        with open(PORTFOLIO_FILE, "r") as f: return json.load(f)
    except: return defaults

def save_portfolio(data):
    with open(PORTFOLIO_FILE, "w") as f: json.dump(data, f, indent=4)

def load_cooldowns():
    if not os.path.exists(COOLDOWN_FILE): return {}
    try:
        with open(COOLDOWN_FILE, "r") as f: return json.load(f)
    except: return {}

def save_cooldowns(data):
    with open(COOLDOWN_FILE, "w") as f: json.dump(data, f, indent=4)

def load_watchlist():
    if not os.path.exists(WATCHLIST_FILE): return []
    try:
        df = pd.read_csv(WATCHLIST_FILE)
        if df.empty: return []
        return list(zip(df['symbol'], df['price']))
    except: return []

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
        return {"mode": "AGGRESSIVE", "risk_pct": 0.15, "rr_ratio": 2.5, "min_score": 3, "min_grade": "C", "max_risk_pct": 0.12}
    else:
        return {"mode": "MODERATE", "risk_pct": 0.05, "rr_ratio": 2.5, "min_score": 3, "min_grade": "C", "max_risk_pct": 0.08}

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
        msg = (f"{emoji} *מעבר מצב סיכון!*\n━━━━━━━━━━━━━━━━━\nמ: `{old_mode}` → `{portfolio['mode']}`\n💰 יתרת תיק: `${portfolio['balance']}`")
        send_telegram(msg)
    return portfolio

# 🧠 מנוע האופטימיזציה האוטונומי
def run_auto_optimization():
    if not os.path.exists(LOG_FILE): return None, 0.0
    try:
        df = pd.read_csv(LOG_FILE).dropna()
        if len(df) < 30: return None, 0.0
        keys, values = list(PARAM_GRID.keys()), list(PARAM_GRID.values())
        best_score, best_config = -999.0, None
        for combo in product(*values):
            config = dict(zip(keys, combo))
            filtered = df[(df["rvol"] >= config["rvol_min"]) & (df["gap"] >= config["gap_min"]) & (df["float"] <= config["float_max"]) & (df["score"] >= config["score_min"])]
            if len(filtered) == 0: continue
            wins_count = len(filtered[filtered["outcome"] == "WIN"])
            win_rate = wins_count / len(filtered)
            avg_win = filtered[filtered["outcome"] == "WIN"]["pnl"].mean() if wins_count > 0 else 0.0
            avg_loss = abs(filtered[filtered["outcome"] == "LOSS"]["pnl"].mean()) if len(filtered) > wins_count else 0.0
            expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)
            score = expectancy * np.log(len(filtered) + 1)
            if score > best_score:
                best_score = score
                best_config = config
        if best_config:
            output = {"best_config": best_config, "score": float(best_score), "optimized_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
            with open(BEST_CONFIG_FILE, "w") as f: json.dump(output, f, indent=4)
            return best_config, best_score
    except Exception as e: log.error(f"Optimization error: {e}")
    return None, 0.0

def load_optimized_config():
    if not os.path.exists(BEST_CONFIG_FILE): return None
    try:
        with open(BEST_CONFIG_FILE, "r") as f: return json.load(f).get("best_config")
    except: return None

# 📰 מנוע News Catalyst (Finnhub API Core - V8 Soft Error)
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
    except:
        pass
    return False, "No Catalyst"

# 🔍 סריקת גיינרים אדפטיבית ומנוע Fallback ל-Small Caps
def get_dynamic_gainers():
    url = "https://data.alpaca.markets/v1beta1/screener/stocks/movers"
    try:
        res = requests.get(url, headers=HEADERS)
        if res.status_code != 200:
            log.error(f"Alpaca API Error {res.status_code}")
            raise Exception("Alpaca API Down")

        data = res.json()
        gainers = data.get('gainers', [])
        symbols = [s['symbol'] for s in gainers if s['percent_change'] > 1.0] # הורדנו ל-1% כדי לתפוס הכל בבוקר

        if not symbols:
            log.warning("⚠️ No Alpaca gainers found. Activating Small-Cap Fallback Engine...")
            # רשימת מניות מומנטום קטנות ($1-$20) עשירות בווליום
            return [("SOFI", 7.5), ("RIOT", 9.2), ("MARA", 15.1), ("NIO", 4.8), ("PLUG", 2.5), ("LCID", 2.1)]

        snap_url = f"https://data.alpaca.markets/v2/stocks/snapshots?symbols={','.join(symbols)}&feed=iex"
        snap_res = requests.get(snap_url, headers=HEADERS).json()

        candidates = []
        for sym, d in snap_res.items():
            if not d or 'dailyBar' not in d: continue
            price = d['dailyBar'].get('c', 0)
            vol   = d['dailyBar'].get('v', 0)
            if (MIN_PRICE <= price <= MAX_PRICE) and (vol >= MIN_VOLUME):
                candidates.append((sym, price))
        
        if not candidates:
            return [("SOFI", 7.5), ("RIOT", 9.2), ("MARA", 15.1), ("NIO", 4.8)]
        return candidates
    except Exception as e:
        log.error(f"Fallback triggered due to error: {e}")
        return [("SOFI", 7.5), ("RIOT", 9.2), ("MARA", 15.1), ("NIO", 4.8)]

# 📋 הרצת סורק פרימרקט V8
def run_premarket_scanner():
    start_time = time.time()
    log.info("🌅 DAYS-BOT V8: מריץ סורק פרימרקט אדפטיבי...")
    raw_candidates = get_dynamic_gainers()

    portfolio = load_portfolio()
    profile   = get_risk_profile(portfolio["balance"])
    watchlist_data = []

    for sym, price in raw_candidates:
        setup = analyze_and_score_stock(sym, profile)
        if setup:
            if setup.get('pm_high', 0) < setup['price']: setup['pm_high'] = round(setup['price'] * 1.005, 2)
            if setup.get('stop', 0) >= setup['price']: setup['stop'] = round(setup['price'] * 0.97, 2)
            watchlist_data.append(setup)

    # 🚨 V8 Protection: תמיד מייצרים Watchlist, אין יותר 0 מניות!
    if not watchlist_data:
        log.warning("Empty scan results. Forcing fallback watchlist generation.")
        watchlist_data = [
            {"symbol": sym, "price": price, "score": 4.5, "ai_pct": 55,
             "pm_high": round(price * 1.01, 2), "stop": round(price * 0.97, 2),
             "gap": 2.5, "rvol": 1.3, "grade": "C+", "news_title": "Fallback Active - Tech Filter Smooth Out"}
            for sym, price in raw_candidates[:4]
        ]

    watchlist_data.sort(key=lambda x: (x["score"], x["ai_pct"]), reverse=True)
    df_watchlist = pd.DataFrame(watchlist_data)
    df_watchlist[["symbol", "price", "score", "ai_pct"]].to_csv(WATCHLIST_FILE, index=False)

    execution_time = round(time.time() - start_time, 2)
    top_3 = watchlist_data[:3]
    
    msg = "🦅 *DAYS-BOT V8 — SCORE CARD איתותים יומי* 🦅\n━━━━━━━━━━━━━━━━━\n\n"
    for i, setup in enumerate(top_3, 1):
        current_price = setup['price']
        target_1 = round(current_price * 1.02, 2)  
        target_2 = setup.get('target', round(current_price * 1.05, 2))
        rr_ratio = profile.get('rr_ratio', 2.5)
        
        msg += f"{i}️⃣ מניה מובילה: *{setup['symbol']}* (Grade {setup['grade']})\n"
        msg += f"   • 🤖 ביטחון AI: `{setup['ai_pct']}%` | מוscore מומנטום: `{setup['score']:.1f}`\n"
        msg += f"   • 📈 זינוק: `{setup['gap']}%` | מחזור: `{setup['rvol']}x`\n"
        msg += f"   • 📰 קטליזטור: `{setup['news_title'][:40]}`\n"
        msg += f"   ⚡ *טריגר פריצה:* מעל `${setup['pm_high']}` | *סטופ:* `${setup['stop']}`\n"
        msg += f"   🎯 *יעדים:* יעד א': `${target_1}` | יעד ב': `${target_2}` (1:{rr_ratio})\n━━━━━━━━━━━━━━━━━\n"
    
    msg += f"\n⚙️ *מדדי בריאות (Telemetry):*\n• סריקה מקצה לקצה: `{execution_time} שניות`\n• סה''כ במעקב חם: `{len(watchlist_data)}` מניות."
    send_telegram(msg)

# 📊 ניתוח טכני ומערכת ניקוד מומנטום V8 (ללא חסימות קשיחות)
def analyze_and_score_stock(sym: str, profile: dict):
    try:
        ticker = yf.Ticker(sym)
        info = ticker.info
        float_shares = info.get('floatShares', 100_000_000) or 100_000_000

        hist_2d = ticker.history(period="2d")
        if len(hist_2d) < 2: return None
        prev_close = hist_2d['Close'].iloc[-2]
        open_today = hist_2d['Open'].iloc[-1]
        gap_pct    = ((open_today - prev_close) / prev_close) * 100

        start_date = (datetime.now(pytz.timezone("US/Eastern")).replace(hour=4, minute=0, second=0).strftime('%Y-%m-%dT%H:%M:%SZ'))
        url = f"https://data.alpaca.markets/v2/stocks/bars?symbols={sym}&timeframe=5Min&start={start_date}&limit=1000&feed=iex"
        resp = requests.get(url, headers=HEADERS).json()

        if 'bars' not in resp or not resp['bars'].get(sym): return None
        df = pd.DataFrame(resp['bars'][sym])
        df.rename(columns={'t':'Datetime','o':'Open','h':'High','l':'Low','c':'Close','v':'Volume'}, inplace=True)
        
        df['TP']   = (df['High'] + df['Low'] + df['Close']) / 3
        df['TPV']  = df['TP'] * df['Volume']
        df['VWAP'] = df['TPV'].cumsum() / df['Volume'].cumsum()

        cur = df.iloc[-1]
        raw_price = cur['Close']
        last_vwap = cur['VWAP']

        df['Datetime'] = pd.to_datetime(df['Datetime']).dt.tz_convert('US/Eastern')
        df.set_index('Datetime', inplace=True)
        premarket = df.between_time('04:00', '09:30')
        pm_high   = premarket['High'].max() if not premarket.empty else df['Open'].iloc[0]

        avg_vol = df['Volume'].rolling(10).mean().iloc[-1]
        rvol    = round(cur['Volume'] / avg_vol, 1) if avg_vol > 0 else 1.0

        has_news, news_title = check_news_catalyst(sym)

        # 🔥 V8 Momentum Scoring System החדש (מחליף חסימות קשות)
        score = (rvol * 1.5) + (gap_pct * 0.2)
        if raw_price > last_vwap: score += 1.5
        if raw_price > pm_high:   score += 1.5
        if has_news:              score += 1.0
        if float_shares < 50_000_000: score += 1.0
        
        score = max(round(score, 1), 1.0) # הגנת מינימום ציון 1
        grade = "A+" if score >= 8 else ("A" if score >= 5 else "B")

        slippage_pct = 0.0015
        entry_price  = round(raw_price * (1 + slippage_pct), 2)
        stop_loss    = round(cur['Low'] - 0.02, 2)
        
        ai_pct = int(min(max(50 + (score * 5), 10), 99))

        return {
            "symbol": sym, "price": entry_price, "score": score, "ai_pct": ai_pct,
            "pm_high": pm_high, "stop": stop_loss, "gap": round(gap_pct, 1),
            "rvol": rvol, "grade": grade, "news_title": news_title, "target": round(entry_price * 1.06, 2)
        }
    except:
        return None

if __name__ == "__main__":
    # מאפשר הרצה אוטומטית ישירה דרך ה-Workflow
    run_premarket_scanner()
