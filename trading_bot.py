"""
DAY-S-BOT v10.0 — DYNAMIC + SOCIAL WATCHLIST
==============================================
✅ מחירים מעוגלים
✅ Market Phase (Kill Zone / Normal / Power Hour)
✅ Explosion Candle
✅ שומר signals_log.csv + near_miss_log.csv
✅ טעינת watchlist דינמית מ-daily_watchlist.csv
✅ פרמטרים דינמיים מ-bot_config.json
✅ ניהול סיכון יומי (Daily Loss Limit)
"""

import os, csv, time, logging, json
from datetime import datetime, timezone, timedelta
import requests
import pandas as pd
import numpy as np

try:
    import yfinance as yf
except ImportError:
    raise SystemExit("pip install yfinance")

try:
    import pytz
    NY_TZ = pytz.timezone("America/New_York")
    def get_ny():
        return datetime.now(NY_TZ)
except ImportError:
    def get_ny():
        utc = datetime.now(timezone.utc)
        def ds(y):
            for d in range(8,15):
                dt=datetime(y,3,d,7,tzinfo=timezone.utc)
                if dt.weekday()==6: return dt
            return datetime(y,3,8,7,tzinfo=timezone.utc)
        def de(y):
            for d in range(1,8):
                dt=datetime(y,11,d,6,tzinfo=timezone.utc)
                if dt.weekday()==6: return dt
            return datetime(y,11,1,6,tzinfo=timezone.utc)
        off = -4 if ds(utc.year)<=utc<de(utc.year) else -5
        return utc+timedelta(hours=off)

# ══════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════
TOKEN    = os.environ.get("TELEGRAM_BOT_TOKEN","").strip()
CHAT_ID  = os.environ.get("TELEGRAM_CHAT_ID","").strip()

def _f(k,d):
    v=os.environ.get(k,"").strip()
    return float(v) if v else d

ACCOUNT   = _f("ACCOUNT_SIZE", 250.0)
RISK      = ACCOUNT * 0.03
BRAKE     = -1.5
DAILY_LOSS_LIMIT = ACCOUNT * 0.05   # 5% הפסד יומי מירבי

PHASES = {
    "KILL_ZONE":  {"alpha":80,"vol":140,"label":"🔥 Kill Zone (09:30–10:15)"},
    "NORMAL":     {"alpha":80,"vol":130,"label":"📊 Normal"},
    "POWER_HOUR": {"alpha":85,"vol":115,"label":"⚡ Power Hour (15:30–16:00)"},
}
MAX_GREEN = 2
MIN_PRICE, MAX_PRICE = 2.0, 20.0

CORE_LIST = [
    "MARA","RIOT","CLSK","CIFR","WULF","MSTR",
    "SOFI","HOOD","UPST","AFRM","NU",
    "RIVN","NIO","LCID",
    "SOUN","BBAI","IONQ","PLTR",
    "NKLA","PLUG","CHPT","OPEN","PTON","GME",
]

def load_dynamic_config():
    """טען פרמטרים מ-bot_config.json (למידה יומית)"""
    if os.path.exists("bot_config.json"):
        with open("bot_config.json", "r") as f:
            return json.load(f)
    return {"alpha_needed": 80, "vol_needed": 130}

def load_watchlist():
    """טען רשימת מעקב מ-daily_watchlist.csv (נוצר ע"י social_feeder)"""
    try:
        if os.path.exists("daily_watchlist.csv"):
            today = get_ny().strftime("%Y-%m-%d")
            syms = []
            with open("daily_watchlist.csv", "r") as f:
                for row in csv.DictReader(f):
                    if row.get("date") == today:
                        syms.append(row["symbol"])
            if syms:
                log.info(f"📋 Watchlist דינמי: {len(syms)} מניות")
                return syms
    except Exception as e:
        log.warning(f"⚠️ שגיאה בטעינת watchlist: {e}")
    log.warning("⚠️ Fallback → CORE_LIST")
    return CORE_LIST

SIGNALS_LOG = "signals_log.csv"
NEAR_LOG    = "near_miss_log.csv"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("v10.0")

WATCHLIST = load_watchlist()

# ══════════════════════════════════════════════
# LOGGERS
# ══════════════════════════════════════════════
SIG_FIELDS = [
    "date","time_il","symbol","phase",
    "price","stop","t1","t2","qty","risk_usd","max_entry",
    "score","vol_pct","rsi","vwap_pct","rs","is_explosion",
    "spy_day","result","pnl_usd","notes"
]
NEAR_FIELDS = [
    "date","time_il","symbol","phase",
    "price","score","vol_pct","rsi","rs","is_explosion",
    "alpha_needed","vol_needed","spy_day"
]

def _ensure(file, fields):
    if not os.path.exists(file):
        with open(file,"w",newline="") as f:
            csv.DictWriter(f,fieldnames=fields).writeheader()

def log_signal(row):
    _ensure(SIGNALS_LOG, SIG_FIELDS)
    r = {k: row.get(k,"") for k in SIG_FIELDS}
    with open(SIGNALS_LOG,"a",newline="") as f:
        csv.DictWriter(f,fieldnames=SIG_FIELDS).writerow(r)

def log_near(row):
    _ensure(NEAR_LOG, NEAR_FIELDS)
    r = {k: row.get(k,"") for k in NEAR_FIELDS}
    with open(NEAR_LOG,"a",newline="") as f:
        csv.DictWriter(f,fieldnames=NEAR_FIELDS).writerow(r)

# ══════════════════════════════════════════════
# MARKET PHASE + TIME
# ══════════════════════════════════════════════
def get_phase():
    ny = get_ny()
    h, m = ny.hour, ny.minute
    if not is_open(): return "CLOSED"
    if (h==9 and m>=30) or (h==10 and m<15): return "KILL_ZONE"
    if h==15 and m>=30:                       return "POWER_HOUR"
    return "NORMAL"

def is_open():
    ny = get_ny()
    if ny.weekday()>=5: return False
    o = ny.replace(hour=9, minute=30,second=0,microsecond=0)
    c = ny.replace(hour=16,minute=0, second=0,microsecond=0)
    return o<=ny<=c

def il_now():
    utc = datetime.now(timezone.utc)
    off = 3 if 3<utc.month<10 else 2
    return utc+timedelta(hours=off)

def il_str():
    return il_now().strftime("%H:%M")

def il_date():
    return il_now().strftime("%Y-%m-%d")

def time_status():
    ny  = get_ny()
    ils = il_str()
    if ny.weekday()>=5: return "🔴 סוף שבוע"
    ph = get_phase()
    if ph!="CLOSED":
        mins = (16*60)-(ny.hour*60+ny.minute)
        return f"🟢 {PHASES[ph]['label']} — {ils} IL | {mins} דק' לסגירה"
    if ny.hour<9 or (ny.hour==9 and ny.minute<30):
        diff=(9*60+30)-(ny.hour*60+ny.minute)
        return f"🟡 לפני פתיחה — {ils} IL | {diff} דק'"
    return f"🔴 שוק סגור — {ils} IL"

# ══════════════════════════════════════════════
# TELEGRAM
# ══════════════════════════════════════════════
def send(msg):
    if not TOKEN or not CHAT_ID:
        print(msg); return
    try:
        r=requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id":CHAT_ID,"text":msg,"parse_mode":"Markdown"},
            timeout=10)
        if r.status_code!=200:
            log.error(f"TG {r.status_code}")
    except Exception as e:
        log.error(f"TG: {e}")

# ══════════════════════════════════════════════
# DATA
# ══════════════════════════════════════════════
def get_bars(sym, period="5d", interval="5m"):
    try:
        df=yf.Ticker(sym).history(period=period,interval=interval)
        if df.empty: return pd.DataFrame()
        df.columns=[c.lower() for c in df.columns]
        return df[["open","high","low","close","volume"]].dropna().tail(80).reset_index(drop=True)
    except Exception as e:
        log.warning(f"yf {sym}: {e}")
        return pd.DataFrame()

def get_spy():
    try:
        df=yf.Ticker("SPY").history(period="1d",interval="5m")
        if len(df)<2: return 0.0,0.0
        day=float((df["Close"].iloc[-1]-df["Open"].iloc[0])/df["Open"].iloc[0]*100)
        m5 =float((df["Close"].iloc[-1]/df["Close"].iloc[-2]-1)*100)
        return round(day,2),round(m5,4)
    except:
        return 0.0,0.0

# ══════════════════════════════════════════════
# SCORING
# ══════════════════════════════════════════════
def score(df, spy_5m=0.0):
    if len(df)<25: return None
    price=round(float(df["close"].iloc[-1]),2)
    if price<MIN_PRICE or price>MAX_PRICE: return None

    d=df["close"].diff()
    ag=d.clip(lower=0).ewm(alpha=1/14,min_periods=14,adjust=False).mean()
    al=(-d.clip(upper=0)).ewm(alpha=1/14,min_periods=14,adjust=False).mean()
    rsi_s=(100-100/(1+ag/al.replace(0,np.nan))).iloc[-1]
    rsi=float(rsi_s) if not np.isnan(rsi_s) else 50.0

    sma20=float(df["close"].rolling(20).mean().iloc[-1])
    tp=(df["high"]+df["low"]+df["close"])/3
    vwap=float((tp*df["volume"]).cumsum().iloc[-1]/df["volume"].cumsum().iloc[-1])
    vwap_pct=round((price-vwap)/vwap*100,2)

    vn=df["volume"].iloc[-5:].mean()
    vb=df["volume"].iloc[-30:-5].mean()
    vol_pct=int(vn/vb*100) if vb>0 else 100

    stock_5m=float((df["close"].iloc[-1]/df["close"].iloc[-2]-1)*100) if len(df)>=2 else 0.0
    rs=round(stock_5m-spy_5m,2)

    hl=df["high"]-df["low"]
    hc=(df["high"]-df["close"].shift()).abs()
    lc=(df["low"] -df["close"].shift()).abs()
    atr=float(pd.concat([hl,hc,lc],axis=1).max(axis=1).ewm(span=14,adjust=False).mean().iloc[-1])

    last=df.iloc[-1]
    avg10=df["volume"].iloc[-10:].mean()
    explosion=bool(
        last["volume"]>avg10*2.5
        and last["close"]>last["open"]
        and (last["close"]-last["open"])/last["open"]>0.005
    )

    day_high  = float(df["high"].max())
    prev_high = float(df["high"].iloc[:-1].max())
    avg_vol_1h = float(df["volume"].tail(12).mean())
    rvol_1h   = float(last["volume"] / avg_vol_1h) if avg_vol_1h > 0 else 0
    hod_break = price >= prev_high and price >= day_high * 0.998

    s=40
    if 50<rsi<=72: s+=15
    elif rsi>72:   s+=8
    if price>sma20:          s+=10
    if 0<vwap_pct<3:         s+=15
    if vol_pct>=150:         s+=20
    elif vol_pct>=110:       s+=10
    if rs>0.2:               s+=min(10,int(rs*3))
    if explosion:            s+=12
    if rsi>80:               s-=10
    if vol_pct<80:           s-=10
    if hod_break:            s+=18
    if rvol_1h>=2.0:         s+=12
    elif rvol_1h>=1.5:       s+=6

    return {
        "price":price,"rsi":round(rsi,1),"sma20":round(sma20,2),
        "vwap":round(vwap,2),"vwap_pct":vwap_pct,
        "vol_pct":vol_pct,"rs":rs,"atr":atr,
        "score":max(0,min(100,s)),"explosion":explosion,
        "hod_break":hod_break,"rvol_1h":round(rvol_1h,1),
    }

def levels(price, atr):
    sd   = max(atr*1.5, price*0.02)
    stop = round(price-sd,2)
    t1   = round(price+sd*2,2)
    t2   = round(price+sd*4,2)
    qty  = max(1,int(RISK/sd))
    if qty*price>ACCOUNT*0.45:
        qty=max(1,int(ACCOUNT*0.45/price))
    me   = round((t1+1.5*stop)/2.5,2)
    rr   = round((t1-price)/sd,1) if sd>0 else 0
    risk = round(qty*sd,2)
    profit_t1 = round(qty*(t1-price),2)
    return {"stop":stop,"t1":t1,"t2":t2,"qty":qty,
            "rr":rr,"risk":risk,"profit_t1":profit_t1,"max_entry":me}

# ══════════════════════════════════════════════
# MESSAGES
# ══════════════════════════════════════════════
def green_msg(sym, m, lv, phase):
    pt1  = round((lv["t1"]-m["price"])/m["price"]*100,1)
    pst  = round((m["price"]-lv["stop"])/m["price"]*100,1)
    vi   = "🔥🔥" if m["vol_pct"]>=200 else "🔥"
    exp  = "\n💥 *EXPLOSION CANDLE*" if m["explosion"] else ""
    hod  = "\n🏆 *HOD BREAKOUT*" if m.get("hod_break") else ""
    rv   = f"\n⚡ RVOL 1H: {m.get('rvol_1h',0)}x" if m.get("rvol_1h",0)>=1.5 else ""
    ph   = PHASES.get(phase,{}).get("label","")
    return (
        f"🚀 *{sym}* — סיגנל תקיפה\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"💰 כניסה:       `${m['price']}`\n"
        f"🚫 *מקס:*       `${lv['max_entry']}`\n"
        f"🎯 T1:           `${lv['t1']}` (+{pt1}%)\n"
        f"🎯 T2:           `${lv['t2']}`\n"
        f"🛑 סטופ:        `${lv['stop']}` (-{pst}%)\n"
        f"📐 R:R:          {lv['rr']}\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"📦 כמות:        *{lv['qty']} מניות*\n"
        f"💵 סיכון:       ${lv['risk']}\n"
        f"💰 רווח T1:    +${lv['profit_t1']}\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"⚡ Alpha:       *{m['score']}/100*\n"
        f"📊 RSI: {m['rsi']}  VWAP+{m['vwap_pct']}%\n"
        f"{vi} Volume: {m['vol_pct']}%{exp}{hod}{rv}\n"
        f"🔗 RS vs SPY: {m['rs']:+.2f}%\n"
        f"🕐 {ph}\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"⚠️ *סיגנל בלבד — ההחלטה שלך*"
    )

def yellow_msg(sym, m, lv, an, vn):
    exp = " 💥" if m["explosion"] else ""
    hod = " 🏆HOD" if m.get("hod_break") else ""
    return (
        f"🟡 *{sym}* — מתחמם (עקוב){exp}{hod}\n"
        f"💰 `${m['price']}` | סטופ: `${lv['stop']}` | T1: `${lv['t1']}`\n"
        f"📊 Alpha: {m['score']}/{an} | Vol: {m['vol_pct']}%/{vn}% | RS: {m['rs']:+.2f}%\n"
        f"👀 מחכים לווליום ≥{vn}%"
    )

def startup_msg(spy_day, phase):
    cfg  = PHASES.get(phase, PHASES["NORMAL"])
    brake= spy_day<BRAKE
    mode = "🛑 מצב צפייה" if brake else "🟢 מחפש כניסות"
    bl   = f"\n🔻 *MACRO BRAKE* — SPY {spy_day:+.1f}%" if brake else ""
    return (
        f"🤖 *DAY-S-BOT v10.0*\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"⏰ {time_status()}\n"
        f"💼 ${ACCOUNT:.0f} | סיכון: ${RISK:.0f}/עסקה\n"
        f"🎯 Alpha ≥ {cfg['alpha']} + Volume ≥ {cfg['vol']}%\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"📈 SPY: {spy_day:+.1f}%{bl}\n"
        f"🔍 {mode} | {len(WATCHLIST)} מניות..."
    )

def fallback_msg(top3):
    if not top3:
        return "🔍 *שוק שקט* — אין מועמדים. חוף הים מנצח 🏖️"
    lines="🔍 *אין סיגנל — Near Miss Top 3*\n━━━━━━━━━━━━━━━━━\n"
    for i,c in enumerate(top3,1):
        vi="🔥" if c["vol_pct"]>=150 else ("🟡" if c["vol_pct"]>=110 else "⚪")
        ei=" 💥" if c.get("explosion") else ""
        hi=" 🏆" if c.get("hod_break") else ""
        lines+=(
            f"*{i}. {c['sym']}* — Alpha {c['score']}{ei}{hi}\n"
            f"   💰 ${c['price']} | RS: {c['rs']:+.2f}% | Vol: {c['vol_pct']}% {vi}\n"
            f"   T1: ${c['t1']} | סטופ: ${c['stop']}\n\n"
        )
    lines+="💡 מחכים לפיצוץ וולום → סיגנל ירוק"
    return lines

# ══════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════
def run():
    log.info("🤖 DAY-S-BOT v10.0")
    if not TOKEN or not CHAT_ID:
        raise SystemExit("❌ TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID חסרים")

    _ensure(SIGNALS_LOG, SIG_FIELDS)
    _ensure(NEAR_LOG, NEAR_FIELDS)

    # טעינת פרמטרים דינמיים (למידה יומית)
    dyn_cfg = load_dynamic_config()
    base_alpha = dyn_cfg.get("alpha_needed", 80)
    base_vol   = dyn_cfg.get("vol_needed", 130)

    # Anti-spam — טוען סיגנלים שנשלחו היום
    sent_today = set()
    try:
        today_check = il_date()
        with open(SIGNALS_LOG, "r") as f:
            for row in csv.DictReader(f):
                if row.get("date") == today_check:
                    sent_today.add(row.get("symbol",""))
    except Exception:
        pass

    spy_day, spy_5m = get_spy()
    phase           = get_phase()
    cfg_phase       = PHASES.get(phase, PHASES["NORMAL"])
    
    # התאמת דרישות לפי שלב השוק (דינמי)
    alpha_req = base_alpha
    vol_req   = base_vol
    if phase == "KILL_ZONE":
        alpha_req = max(65, base_alpha - 10)
        vol_req   = max(100, base_vol - 20)
    elif phase == "POWER_HOUR":
        alpha_req = min(90, base_alpha + 5)
        vol_req   = max(80, base_vol - 10)
    
    today           = il_date()
    now_str         = il_str()

    send(startup_msg(spy_day, phase))

    if not is_open():
        log.info("שוק סגור"); return

    if spy_day < BRAKE:
        send(f"🔻 *MACRO HANDBRAKE*\nSPY {spy_day:+.1f}% מהפתיחה\nלא מחפש כניסות היום 🏖️")
        return

    # ניהול סיכון יומי – קריאת הפסד מצטבר מהיום
    daily_loss = 0.0
    try:
        df_log = pd.read_csv(SIGNALS_LOG)
        df_log = df_log[df_log["date"] == today]
        df_log["pnl_usd"] = pd.to_numeric(df_log["pnl_usd"], errors="coerce")
        daily_loss = df_log["pnl_usd"].sum()
    except:
        pass
    
    if daily_loss <= -DAILY_LOSS_LIMIT:
        send(f"🛑 *עצירת יומית* – הפסד מצטבר של ${abs(daily_loss):.0f} (מעל 5% מהקפיטל). מפסיק מסחר להיום.")
        return

    green_cnt = yellow_cnt = 0
    candidates = []

    for sym in WATCHLIST:
        try:
            df = get_bars(sym)
            if df.empty or len(df)<25: continue

            m = score(df, spy_5m)
            if m is None: continue

            lv = levels(m["price"], m["atr"])
            log.info(
                f"  {sym}: ${m['price']} sc={m['score']} "
                f"vol={m['vol_pct']}% rs={m['rs']:+.2f}%"
                f"{' 💥' if m['explosion'] else ''}"
                f"{' 🏆' if m.get('hod_break') else ''}"
            )

            base_row = {
                "date":today,"time_il":now_str,"symbol":sym,"phase":phase,
                "price":m["price"],"score":m["score"],"vol_pct":m["vol_pct"],
                "rsi":m["rsi"],"rs":m["rs"],"is_explosion":m["explosion"],
                "spy_day":spy_day,
            }

            if (m["score"]>=alpha_req and m["vol_pct"]>=vol_req
                    and lv["rr"]>=1.5 and green_cnt<MAX_GREEN):
                if sym in sent_today:
                    log.info(f"  ⏭️ {sym}: כבר נשלח היום")
                    continue
                send(green_msg(sym, m, lv, phase))
                log_signal({
                    **base_row,
                    "stop":lv["stop"],"t1":lv["t1"],"t2":lv["t2"],
                    "qty":lv["qty"],"risk_usd":lv["risk"],
                    "max_entry":lv["max_entry"],"vwap_pct":m["vwap_pct"],
                    "result":"","pnl_usd":"","notes":"",
                })
                green_cnt+=1
                log.info(f"  ✅ GREEN: {sym}")
                time.sleep(2)

            elif (m["score"]>=alpha_req-10
                    and m["vol_pct"]>=vol_req-20
                    and yellow_cnt<2):
                send(yellow_msg(sym, m, lv, alpha_req, vol_req))
                log_near({**base_row,"alpha_needed":alpha_req,"vol_needed":vol_req})
                yellow_cnt+=1
                time.sleep(1)

            elif m["score"]>=55:
                candidates.append({**m,"sym":sym,"t1":lv["t1"],"stop":lv["stop"]})
                log_near({**base_row,"alpha_needed":alpha_req,"vol_needed":vol_req})

            time.sleep(0.3)

        except Exception as e:
            log.error(f"❌ {sym}: {e}")

    if green_cnt==0 and yellow_cnt==0:
        top3=sorted(
            candidates,
            key=lambda x: x["score"]*0.45+min(x["vol_pct"],200)*0.3+x["rs"]*10*0.25,
            reverse=True
        )[:3]
        send(fallback_msg(top3))

    log.info(f"סיום: {green_cnt} ירוקים, {yellow_cnt} צהובים")

if __name__=="__main__":
    run()
