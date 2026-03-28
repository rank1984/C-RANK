"""
DAY-S-BOT v6 FINAL
===================
חדש בגרסה זו:
  • entry_type: ORB / VWAP / MOMENTUM / OVERSOLD
  • CSV עשיר לניתוח בעוד שבועיים
  • הודעת טלגרם מוכוונת-פעולה — ברור מה לעשות
"""
import os, csv, json, requests, yfinance as yf, pytz
from datetime import datetime, date

TOKEN      = os.getenv("TELEGRAM_TOKEN")
CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID")
BUDGET     = 250
MAX_TRADES = 2
MAX_DAILY_LOSS_PCT = 0.06          # $15 על $250
MIN_STARS_HUNT     = 4
STATE_FILE = f"state_{date.today()}.json"
LOG_FILE   = f"signals_{date.today()}.csv"

CATALYST_KEYWORDS = [
    "earnings","fda","contract","upgrade","partnership",
    "acquisition","merger","guidance","beat","approval",
    "clinical","revenue","profit","deal","award"
]
STOCKS = [
    "BITF","WULF","BTBT","NIO","SOUN","BBAI","LUNR",
    "MARA","RIOT","CLSK","NKLA","FUBO","TLRY","SNDL",
    "MULN","CLOV","INDO","VERB","IINN","KALI"
]

# ═══════════════════════════════════════════════
# STATE
# ═══════════════════════════════════════════════
def load_state():
    try:
        with open(STATE_FILE) as f: return json.load(f)
    except:
        return {"trades":0,"loss_usd":0.0,"killed":False,"last_signal":None}

def save_state(s):
    with open(STATE_FILE,"w") as f: json.dump(s,f,default=str)

def is_killed():
    st = load_state()
    if st.get("killed"):          return True,"🛑 Kill Switch פעיל היום"
    if st["loss_usd"] >= BUDGET * MAX_DAILY_LOSS_PCT:
        st["killed"] = True; save_state(st)
        return True,f"🛑 הפסד יומי מקסימלי (${BUDGET*MAX_DAILY_LOSS_PCT:.0f}) הושג"
    if st["trades"] >= MAX_TRADES: return True,f"🛑 {MAX_TRADES} עסקאות הושלמו היום"
    return False,""

# ═══════════════════════════════════════════════
# TELEGRAM
# ═══════════════════════════════════════════════
def send_msg(text):
    if not TOKEN or not CHAT_ID: print(text); return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id":CHAT_ID,"text":text,"parse_mode":"HTML"},
            timeout=10)
    except: pass

# ═══════════════════════════════════════════════
# INDICATORS
# ═══════════════════════════════════════════════
def calc_rsi(s,p=14):
    if len(s)<p+1: return 50.0
    d=s.diff(); ag=d.where(d>0,0.).ewm(alpha=1/p,adjust=False).mean()
    al=(-d.where(d<0,0.)).ewm(alpha=1/p,adjust=False).mean()
    rs=ag/al.replace(0,1e-10)
    return round(float(100-(100/(1+rs)).iloc[-1]),1)

def calc_rvol(hist,info,market_open):
    avg=info.get('averageVolume',0) or 0
    if not avg: return 0.0
    if market_open:
        pb=avg/390; return round(float(hist['Volume'].tail(10).mean()/pb),2) if pb else 0.
    return round(float((info.get('volume',0) or 0)/avg),2)

def calc_vwap(hist):
    try: return float((hist['Close']*hist['Volume']).cumsum()/hist['Volume'].cumsum().iloc[-1])
    except: return None

def get_market_mood():
    try:
        h=yf.Ticker("QQQ").history(period="2d")
        c=float((h['Close'].iloc[-1]-h['Close'].iloc[-2])/h['Close'].iloc[-2]*100)
        if c> 0.5: return "bull",  round(c,2)
        if c>-1.0: return "neutral",round(c,2)
        if c>-2.0: return "bear",  round(c,2)
        return "crash",round(c,2)
    except: return "neutral",0.0

MOOD_ICON={"bull":"🟢","neutral":"🟡","bear":"🔴","crash":"💀"}
MOOD_NAME={"bull":"חיובי","neutral":"נייטרלי","bear":"שלילי","crash":"קריסה"}

def check_catalyst(t):
    try:
        news=t.news; cutoff=datetime.now().timestamp()-86400
        recent=[n for n in (news or []) if n.get('providerPublishTime',0)>cutoff]
        if not recent: return None
        text=str(recent).lower()
        return "strong" if any(k in text for k in CATALYST_KEYWORDS) else "weak"
    except: return None

def float_data(info):
    f=info.get('floatShares',0) or 0
    if not f:       return 0,"❓"
    if f<10_000_000:return 2,"🔥<10M"
    if f<30_000_000:return 1,"✅<30M"
    if f<100_000_000:return 0,"😐<100M"
    return -1,"⚠️ ענק"

# ═══════════════════════════════════════════════
# ENTRY TYPE — הלב של הבאקטסט
# ═══════════════════════════════════════════════
def classify_entry(orb_break, vol_spike, confirm_break, near_vwap, rvol, rsi, higher_high):
    """
    מסווג את סוג הכניסה — ישמר ב-CSV ויאפשר השוואה בעוד שבועיים:
    ORB_CONFIRMED  — פריצת ORB עם ווליום + אישור (הכי חזק)
    ORB_WEAK       — פריצת ORB בלי ווליום מספיק
    VWAP_PULLBACK  — כניסה על Pullback ל-VWAP
    MOMENTUM       — Higher High + RVOL גבוה
    OVERSOLD       — RSI נמוך + RVOL
    MIXED          — שילוב
    """
    if orb_break and vol_spike and confirm_break: return "ORB_CONFIRMED"
    if orb_break and vol_spike:                   return "ORB_VOL"
    if orb_break:                                 return "ORB_WEAK"
    if near_vwap and rvol > 2:                    return "VWAP_PULLBACK"
    if higher_high and rvol > 3:                  return "MOMENTUM"
    if rsi < 30 and rvol > 2:                     return "OVERSOLD"
    return "MIXED"

# ═══════════════════════════════════════════════
# SCORING
# ═══════════════════════════════════════════════
def calc_stars(p):
    s=0
    if   p['rvol']>6: s+=5
    elif p['rvol']>5: s+=4
    elif p['rvol']>3: s+=3
    elif p['rvol']>2: s+=2
    elif p['rvol']>1.5:s+=1
    if   p['rsi']<20: s+=3
    elif p['rsi']<30: s+=2
    elif p['rsi']<40: s+=1
    elif p['rsi']>75: s-=1
    if   p['gap']>8: s+=3
    elif p['gap']>5: s+=2
    elif p['gap']>2: s+=1
    if p['chg']>5: s+=1
    s+=p['f_score']
    if   p['cat']=="strong": s+=2
    elif p['cat']=="weak":   s+=1
    if p['orb_break'] and p['vol_spike'] and p['confirm_break']: s+=6
    elif p['orb_break'] and p['vol_spike']:  s+=4
    elif p['orb_break']:                     s+=1
    if p['near_vwap'] and p['rvol']>2:       s+=2
    if p['higher_high']:                     s+=2
    if p['fake_move']:                       s-=3
    s+=p['spread_pen']
    if p['mood']=="bear"  and not p['near_vwap']: s-=2
    elif p['mood']=="bull":  s+=1
    elif p['mood']=="crash": s-=3
    if   s>=18: return 5
    elif s>=13: return 4
    elif s>=9:  return 3
    elif s>=5:  return 2
    return 1

# ═══════════════════════════════════════════════
# POSITION
# ═══════════════════════════════════════════════
def build_pos(price, stars):
    stop=round(price*0.96,3)
    risk_usd=max(5,round(BUDGET*{5:.10,4:.07,3:.05,2:.04,1:.02}.get(stars,.02),1))
    shares=max(1,int(risk_usd/(price-stop))) if price>stop else 1
    cost=round(shares*price,1)
    if cost>BUDGET*.30: shares=max(1,int(BUDGET*.30/price)); cost=round(shares*price,1)
    half=max(1,shares//2); rest=shares-half
    return {"shares":shares,"half":half,"rest":rest,"cost":cost,
            "risk":round(risk_usd,1),"stop":stop,
            "stop_be":round(price*1.001,3),
            "t1":round(price*1.04,2),
            "t2":round(price*1.08,2)}

# ═══════════════════════════════════════════════
# ANALYZE
# ═══════════════════════════════════════════════
def analyze(symbol, market_open, mood):
    try:
        t=yf.Ticker(symbol)
        hist=t.history(period="5d",interval="1m" if market_open else "5m",prepost=True)
        if hist.empty or len(hist)<20: return None
        info=t.info
        price=float(hist['Close'].iloc[-1])
        if price>12 or price<0.5: return None

        rsi=calc_rsi(hist['Close'])
        avg=info.get('averageVolume',0) or 0
        rvol=calc_rvol(hist,info,market_open)
        vwap=calc_vwap(hist)

        bid=info.get('bid',0) or 0; ask=info.get('ask',0) or 0
        spread=round(((ask-bid)/ask)*100,2) if ask>bid>0 else 0.
        spread_pen=-1 if spread>3 else 0
        spread_lbl=(f"🔴 ספרד {spread}% Limit חובה!" if spread>3
                    else f"⚠️ ספרד {spread}%" if spread>1.5
                    else f"✅ {spread}%" if spread>0 else "")

        daily=t.history(period="5d")
        if len(daily)<2: return None
        prev=float(daily['Close'].iloc[-2])
        mh=hist.between_time('09:30','16:00')
        open_p=float(mh['Open'].iloc[0]) if not mh.empty else price
        gap=round(((open_p-prev)/prev)*100,1)
        chg=round(((price-prev)/prev)*100,1)

        orb_w=hist.between_time('09:30','09:45')
        orb_high=float(orb_w['High'].max()) if not orb_w.empty else None
        orb_break=orb_high is not None and price>orb_high
        va=hist['Volume'].rolling(20).mean().iloc[-1]
        vol_spike=float(hist['Volume'].iloc[-1])>float(va)*2 if va and va>0 else False
        confirm_break=(float(hist['Close'].iloc[-1])>float(hist['High'].iloc[-2])
                       if len(hist)>=3 else False)
        upper_wick=float(hist['High'].iloc[-1]-hist['Close'].iloc[-1])
        body=abs(float(hist['Close'].iloc[-1]-hist['Open'].iloc[-1]))
        fake_move=upper_wick>body*2 if body>0 else False
        near_vwap=(abs(price-vwap)/price<0.01) if vwap else False
        higher_high=(float(hist['High'].iloc[-1])>float(hist['High'].iloc[-6:-1].max())
                     if len(hist)>=6 else False)

        f_score,f_lbl=float_data(info)
        cat=check_catalyst(t)

        params=dict(rvol=rvol,rsi=rsi,gap=gap,chg=chg,f_score=f_score,cat=cat,
                    orb_break=orb_break,vol_spike=vol_spike,confirm_break=confirm_break,
                    fake_move=fake_move,near_vwap=near_vwap,higher_high=higher_high,
                    spread_pen=spread_pen,mood=mood)
        stars=calc_stars(params)
        entry_type=classify_entry(orb_break,vol_spike,confirm_break,near_vwap,rvol,rsi,higher_high)
        pos=build_pos(price,stars)

        return dict(symbol=symbol,price=round(price,3),gap=gap,rsi=rsi,rvol=rvol,chg=chg,
                    spread=spread,spread_lbl=spread_lbl,
                    orb_break=orb_break,vol_spike=vol_spike,confirm_break=confirm_break,
                    fake_move=fake_move,near_vwap=near_vwap,higher_high=higher_high,
                    catalyst=cat,f_lbl=f_lbl,vwap=round(vwap,3) if vwap else None,
                    entry_type=entry_type,stars=stars,pos=pos,
                    entry_time=datetime.now(pytz.timezone('America/New_York')).strftime('%H:%M'))
    except: return None

# ═══════════════════════════════════════════════
# CSV — עשיר לבאקטסט
# ═══════════════════════════════════════════════
CSV_COLS = [
    "date","entry_time","symbol","stars","entry_type",
    "price","gap","rvol","rsi","chg","spread",
    "orb_break","vol_spike","confirm_break","fake_move",
    "near_vwap","higher_high","catalyst",
    "target_t1","target_t2","stop",
    # ← ימולאו ידנית אחרי סגירת עסקה:
    "actual_exit","actual_pnl_pct","mae","mfe","notes"
]

def log_signal(r):
    exists=os.path.exists(LOG_FILE)
    p=r['pos']
    with open(LOG_FILE,'a',newline='') as f:
        w=csv.DictWriter(f,fieldnames=CSV_COLS,extrasaction='ignore')
        if not exists: w.writeheader()
        w.writerow({
            "date":str(date.today()),"entry_time":r['entry_time'],
            "symbol":r['symbol'],"stars":r['stars'],"entry_type":r['entry_type'],
            "price":r['price'],"gap":r['gap'],"rvol":r['rvol'],"rsi":r['rsi'],
            "chg":r['chg'],"spread":r['spread'],
            "orb_break":r['orb_break'],"vol_spike":r['vol_spike'],
            "confirm_break":r['confirm_break'],"fake_move":r['fake_move'],
            "near_vwap":r['near_vwap'],"higher_high":r['higher_high'],
            "catalyst":r['catalyst'] or "",
            "target_t1":p['t1'],"target_t2":p['t2'],"stop":p['stop'],
            "actual_exit":"","actual_pnl_pct":"","mae":"","mfe":"","notes":""
        })

# ═══════════════════════════════════════════════
# MESSAGES — מוכוון פעולה
# ═══════════════════════════════════════════════
SEP="─"*24
MOOD_ICON={"bull":"🟢","neutral":"🟡","bear":"🔴","crash":"💀"}
MOOD_NAME={"bull":"חיובי","neutral":"נייטרלי","bear":"שלילי","crash":"קריסה"}

def _entry_badge(r):
    t=r['entry_type']
    if t=="ORB_CONFIRMED": return "🚀🚀 ORB מאושר"
    if t=="ORB_VOL":       return "🚀 ORB+VOL"
    if t=="ORB_WEAK":      return "⚠️ ORB חלש"
    if t=="VWAP_PULLBACK": return "🎯 VWAP Pullback"
    if t=="MOMENTUM":      return "📈 Momentum"
    if t=="OVERSOLD":      return "🔄 Oversold"
    return "📊 Mixed"

def _action_line(r):
    """שורת פעולה אחת — ברור מה לעשות"""
    p=r['pos']
    if r['fake_move']:
        return "❌ <b>דלג — TRAP מזוהה</b>"
    if r['entry_type'] in ("ORB_CONFIRMED","ORB_VOL"):
        return f"✅ <b>קנה עכשיו</b> {p['shares']} מניות ב-Limit ${r['price']}"
    if r['entry_type']=="VWAP_PULLBACK":
        return f"✅ <b>קנה על Pullback</b> — המתן ל-${r['vwap']} ואז Limit"
    if r['entry_type'] in ("MOMENTUM","OVERSOLD"):
        return f"⚡ <b>קנה אם שובר</b> ${round(r['price']*1.005,3)} (אישור)"
    return f"👀 <b>עקוב</b> — אין כניסה ברורה עדיין"

def fmt_hunting(signals, mood, mood_chg, st):
    done=st.get("trades",0); rem=MAX_TRADES-done
    loss=st.get("loss_usd",0); max_loss=BUDGET*MAX_DAILY_LOSS_PCT
    sign="+" if mood_chg>=0 else ""

    header=(f"🏹 <b>מצב ציד | {datetime.now(pytz.timezone('America/New_York')).strftime('%H:%M')} NY</b>\n"
            f"{MOOD_ICON[mood]} QQQ {sign}{mood_chg}%  |  "
            f"עסקאות: <b>{done}/{MAX_TRADES}</b>  |  הפסד: <b>${loss:.0f}/${max_loss:.0f}</b>\n")

    blocks=[]
    for r in sorted(signals,key=lambda x:x['stars'],reverse=True)[:rem]:
        p=r['pos']
        sign2="+" if r['chg']>=0 else ""
        sp=f"\n{r['spread_lbl']}" if r['spread_lbl'] else ""
        blocks.append(
            f"\n{SEP}\n"
            f"<b>{r['symbol']}</b> {'⭐'*r['stars']}  {_entry_badge(r)}\n"
            f"💲 <b>${r['price']}</b>  {sign2}{r['chg']}%  RVOL <b>{r['rvol']}x</b>  RSI <b>{r['rsi']}</b>{sp}\n"
            f"פלואט: {r['f_lbl']}  |  VWAP: {r['vwap'] or '?'}\n\n"
            f"👉 {_action_line(r)}\n\n"
            f"📋 <b>תוכנית:</b>\n"
            f"  ▸ T1 +4%  → <b>${p['t1']}</b>  מכור {p['half']} מניות\n"
            f"  ▸ T2 +8%  → <b>${p['t2']}</b>  מכור {p['rest']} מניות\n"
            f"  ▸ Stop    → <b>${p['stop']}</b>  צא מהכל\n"
            f"  ▸ אחרי T1 → הזז סטופ ל-<b>${p['stop_be']}</b>\n"
            f"  ▸ כניסה   → <b>{p['shares']} מניות ≈ ${p['cost']}</b>  סיכון: ${p['risk']}"
        )

    footer=f"\n{SEP}\n⚠️ Limit Order בלבד  |  /loss [סכום] לדיווח הפסד"
    return header+"".join(blocks)+footer

def fmt_follow_up(ls, time_ny):
    p=ls['pos']
    return (
        f"⏱️ <b>Follow-Up: {ls['symbol']} — 15 דקות אחרי כניסה</b>\n"
        f"📍 כניסה: ${ls['price']}  |  {time_ny.strftime('%H:%M')} NY\n{SEP}\n"
        f"בדוק עכשיו:\n\n"
        f"📈 <b>עלה מעל ${ls['pos']['t1']} (+4%)?</b>\n"
        f"   → מכור {p['half']} מניות מיד\n"
        f"   → הזז סטופ ל-${p['stop_be']} (Breakeven)\n\n"
        f"😐 <b>עדיין בין כניסה ל-T1?</b>\n"
        f"   → החזק. סטופ נשאר ב-${p['stop']}\n\n"
        f"📉 <b>ירד מתחת ל-${p['stop']} (-4%)?</b>\n"
        f"   → <b>צא מיד!</b> ואז שלח: /loss [סכום]\n{SEP}\n"
        f"📊 רשום ב-CSV: entry_type={ls.get('entry_type','?')} | actual_exit=?"
    )

def fmt_prep(results, mood, mood_chg, time_ny):
    top=sorted(results,key=lambda x:x['stars'],reverse=True)[:6]
    sign="+" if mood_chg>=0 else ""
    rows=[]
    for i,r in enumerate(top,1):
        trap=" ⚠️TRAP" if r['fake_move'] else ""
        sp=f" | {r['spread_lbl']}" if r['spread']>1.5 else ""
        rows.append(
            f"{i}. <b>{r['symbol']}</b> {'⭐'*r['stars']}  {_entry_badge(r)}{trap}\n"
            f"   💲${r['price']} | RVOL {r['rvol']}x | RSI {r['rsi']} | גאפ {r['gap']}%\n"
            f"   {r['f_lbl']}{sp}"
        )
    return (
        f"📋 <b>DAY-S-BOT | {time_ny.strftime('%H:%M')} NY — הכנה למחר</b>\n"
        f"{MOOD_ICON[mood]} QQQ: {MOOD_NAME[mood]} ({sign}{mood_chg}%)\n"
        f"{'━'*24}\n\n"
        +"\n\n".join(rows)+
        f"\n\n{'━'*24}\n"
        f"⏰ ציד: מחר 9:45–10:15 NY (16:45–17:15 ישראל)\n"
        f"📌 רק {MIN_STARS_HUNT}⭐+  |  מקסימום {MAX_TRADES} עסקאות  |  Limit בלבד\n"
        f"🛑 Kill Switch: ${BUDGET*MAX_DAILY_LOSS_PCT:.0f} הפסד יומי = עצור\n"
        f"📊 מלא CSV אחרי כל עסקה: actual_exit + actual_pnl_pct"
    )

def fmt_routine(results, mood, mood_chg, time_ny, dead_zone):
    top=sorted(results,key=lambda x:x['stars'],reverse=True)[:5]
    sign="+" if mood_chg>=0 else ""
    rows=[f"{'⭐'*r['stars']} <b>{r['symbol']}</b>  💲${r['price']}  {_entry_badge(r)}"
          +(" ⚠️TRAP" if r['fake_move'] else "")
          for r in top]
    dz="\n⏰ <b>שעת דמדומים</b> — עוקב בלבד." if dead_zone else ""
    return (
        f"📊 <b>DAY-S-BOT | {time_ny.strftime('%H:%M')} NY</b>\n"
        f"{MOOD_ICON[mood]} QQQ {sign}{mood_chg}%{dz}\n"
        f"{'━'*24}\n\n"+"\n".join(rows)+
        f"\n\n/loss [סכום] לדיווח הפסד"
    )

# ═══════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════
def main():
    tz=pytz.timezone('America/New_York')
    time_ny=datetime.now(tz)
    h,m=time_ny.hour,time_ny.minute

    is_hunting =(h==9 and m>=45) or (h==10 and m<=15)
    is_followup=(h==10 and 16<=m<=30)
    is_morning =(h==9  and 15<=m<=29)
    is_prep    =(h==16 and 25<=m<=40)
    market_open=(9<=h<16)
    dead_zone  =(h==11 and m>=30) or h in [12,13] or (h==14 and m==0)

    mood,mood_chg=get_market_mood()

    if mood=="crash" and is_hunting:
        send_msg(f"💀 <b>קריסה בשוק</b>\nQQQ: {mood_chg}%\n\n🚫 לא צדים. שמור על ה-${BUDGET}.")
        return

    killed,kill_reason=is_killed()
    if killed and (is_hunting or is_followup):
        send_msg(f"{kill_reason}\n\n⚡ שמור על ההון. מחר מחדש.")
        return

    st=load_state()

    # Follow-Up — 15 דק אחרי כניסה
    if is_followup and st.get("last_signal"):
        send_msg(fmt_follow_up(st["last_signal"],time_ny))
        return

    results=[]
    for sym in STOCKS:
        r=analyze(sym,market_open,mood)
        if r: results.append(r)

    if not results:
        send_msg("⚠️ <b>DAY-S-BOT</b>: לא נמצאו נתונים."); return

    for r in results:
        if r['stars']>=3: log_signal(r)

    if is_hunting:
        signals=[s for s in results if s['stars']>=MIN_STARS_HUNT]
        if signals:
            send_msg(fmt_hunting(signals,mood,mood_chg,st))
            top=sorted(signals,key=lambda x:x['stars'],reverse=True)[0]
            st["trades"]=st.get("trades",0)+1
            st["last_signal"]={
                "symbol":top['symbol'],"price":top['price'],
                "entry_type":top['entry_type'],"pos":top['pos'],
                "vwap":top['vwap']
            }
            save_state(st)
        else:
            send_msg(
                f"🔍 <b>ציד | {time_ny.strftime('%H:%M')} NY</b>\n"
                f"{MOOD_ICON[mood]} {MOOD_NAME[mood]}\n\n"
                f"אין סיגנל {MIN_STARS_HUNT}⭐+ עם Volume + Confirm.\n"
                f"<i>ממתין לסיגנל מושלם...</i>"
            )
    elif is_morning or is_prep:
        send_msg(fmt_prep(results,mood,mood_chg,time_ny))
    else:
        send_msg(fmt_routine(results,mood,mood_chg,time_ny,dead_zone))

if __name__=="__main__":
    main()
