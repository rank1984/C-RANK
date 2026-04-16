"""
PREMARKET SCANNER v1.0 — DAY-S-BOT Add-on
==========================================
מטרה: לסרוק לפני פתיחת השוק ולבנות daily_watchlist.csv דינמי.
הבוט הראשי (v10.x) קורא ממנו אוטומטית דרך load_watchlist().

מתי להריץ: בין 08:30–09:15 NY (15:30–16:15 IL בקיץ)
GitHub Actions: ראה הערות בתחתית הקובץ
"""

import os, csv, time, logging
from datetime import datetime, timezone, timedelta

import requests
import pandas as pd

try:
    import yfinance as yf
except ImportError:
    raise SystemExit("pip install yfinance")

# ══════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════
TOKEN   = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

MIN_PRICE     = 2.0
MAX_PRICE     = 20.0
MIN_GAP_PCT   = 2.0    # גאפ מינימום מסגירה אתמול
MIN_PM_VOL    = 30_000  # וולום premarket מינימום
MAX_WATCHLIST = 20     # כמות מניות מקסימום ברשימה הסופית

WATCHLIST_FILE = "daily_watchlist.csv"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("premarket")

# ══════════════════════════════════════════════
# UNIVERSE — בסיס רחב לסריקה
# ══════════════════════════════════════════════
# קטגוריה א': ליבה — מניות תנודתיות שתמיד על הרדאר
CORE = [
    "MARA","RIOT","CLSK","CIFR","WULF","MSTR",      # ביטקוין / קריפטו
    "SOFI","HOOD","UPST","AFRM","NU","OPEN",         # פינטק
    "RIVN","NIO","LCID","NKLA","CHPT","BLNK",        # EV
    "SOUN","BBAI","IONQ","PLTR","AI","ARQQ",         # AI
    "PLUG","BE","FCEL","RUN","NOVA",                 # אנרגיה ירוקה
    "PTON","GME","AMC","BBBY","CLOV",                # מם
    "SPCE","RKLB","ASTS","LUNR",                     # חלל
    "TLRY","SNDL","CGON","ACB",                      # קנאביס
    "LUMN","BABA","JD","PDD","XPEV","LI",            # כללי תנודתי
]

# קטגוריה ב': מניות שיתווספו רק אם יש להן גאפ + נפח (חיפוש דינמי)
EXTENDED = [
    "NVAX","OCGN","ATOS","CTXR","IDEX","IMVT",
    "KOSS","EXPR","NAKD","WKHS","RIDE","GOEV",
    "PSFE","OPAD","SPRT","IRNT","GFAI","MULN",
    "ILUS","INPX","IINN","SLXN","EFTR","TPVG",
    "PRTY","ANY","DPRO","ONDS","NURO","BFRI",
]

# ══════════════════════════════════════════════
# TIME HELPERS
# ══════════════════════════════════════════════
def get_ny():
    try:
        import pytz
        return datetime.now(pytz.timezone("America/New_York"))
    except ImportError:
        utc = datetime.now(timezone.utc)
        def ds(y):
            for d in range(8, 15):
                dt = datetime(y, 3, d, 7, tzinfo=timezone.utc)
                if dt.weekday() == 6: return dt
        def de(y):
            for d in range(1, 8):
                dt = datetime(y, 11, d, 6, tzinfo=timezone.utc)
                if dt.weekday() == 6: return dt
        off = -4 if ds(utc.year) <= utc < de(utc.year) else -5
        return utc + timedelta(hours=off)

def il_now():
    utc = datetime.now(timezone.utc)
    off = 3 if 3 < utc.month < 10 else 2
    return utc + timedelta(hours=off)

def il_str():
    return il_now().strftime("%H:%M")

def today_str():
    return get_ny().strftime("%Y-%m-%d")

# ══════════════════════════════════════════════
# TELEGRAM
# ══════════════════════════════════════════════
def send(msg):
    if not TOKEN or not CHAT_ID:
        print(msg)
        return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"},
            timeout=10,
        )
        if r.status_code != 200:
            log.error(f"TG {r.status_code}: {r.text[:100]}")
    except Exception as e:
        log.error(f"TG error: {e}")

# ══════════════════════════════════════════════
# CORE SCANNER — גאפ + נפח + מחיר
# ══════════════════════════════════════════════
def scan_symbol(sym: str) -> dict | None:
    """
    מחזיר מידע על מניה אם עומדת בקריטריוני premarket.
    None = לא רלוונטית.
    """
    try:
        t = yf.Ticker(sym)

        # מחיר סגירה אתמול — אמין
        hist = t.history(period="5d", interval="1d")
        if len(hist) < 2:
            return None
        prev_close = float(hist["Close"].iloc[-2])

        # נתוני premarket (prepost=True כולל שעות מסחר מורחבות)
        pm = t.history(period="1d", interval="5m", prepost=True)
        if pm.empty:
            return None

        curr_price = float(pm["Close"].iloc[-1])
        pm_vol     = int(pm["Volume"].sum())

        # פילטרים בסיסיים
        if curr_price < MIN_PRICE or curr_price > MAX_PRICE:
            return None
        if pm_vol < MIN_PM_VOL:
            return None

        gap = round((curr_price - prev_close) / prev_close * 100, 1)
        if gap < MIN_GAP_PCT:
            return None

        # ATR מהיסטוריה יומית — אומד תנודתיות
        if len(hist) >= 5:
            hl = hist["High"] - hist["Low"]
            atr_d = float(hl.tail(5).mean())
        else:
            atr_d = curr_price * 0.04

        # חדשות (yfinance מחזיר עד 10 כותרות אחרונות)
        news = []
        try:
            raw_news = t.news or []
            news = [n.get("title", "") for n in raw_news[:3]]
        except Exception:
            pass

        has_catalyst = _detect_catalyst(sym, news)

        # ציון עצמאי לסקאן
        score = _pm_score(gap, pm_vol, has_catalyst, atr_d, curr_price)

        return {
            "symbol":       sym,
            "price":        round(curr_price, 2),
            "prev_close":   round(prev_close, 2),
            "gap_pct":      gap,
            "pm_vol":       pm_vol,
            "has_catalyst": has_catalyst,
            "catalyst_hint":news[0][:60] if news else "",
            "atr_daily":    round(atr_d, 3),
            "pm_score":     score,
            "date":         today_str(),
        }

    except Exception as e:
        log.debug(f"scan_symbol {sym}: {e}")
        return None


def _detect_catalyst(sym: str, news: list[str]) -> bool:
    """
    בודק אם יש קטליסט ברור: earnings / FDA / partnership / upgrade / short squeeze
    """
    keywords = [
        "earn", "revenue", "guidance", "beat", "miss",
        "fda", "approval", "trial", "data",
        "deal", "partner", "acqui", "merger",
        "upgrade", "downgrade", "target",
        "short", "squeeze", "gamma",
        "launch", "contract",
    ]
    combined = " ".join(news).lower()
    return any(kw in combined for kw in keywords)


def _pm_score(gap: float, pm_vol: int, has_catalyst: bool,
              atr_d: float, price: float) -> int:
    """
    ציון 0–100 לדירוג מניות הפרה-מרקט.
    גבוה יותר = עדיפות גבוהה יותר לכניסה לרשימה.
    """
    s = 0

    # גאפ
    if gap >= 10: s += 30
    elif gap >= 5: s += 20
    elif gap >= 3: s += 12
    else:         s += 5

    # נפח premarket
    if pm_vol >= 500_000: s += 30
    elif pm_vol >= 200_000: s += 20
    elif pm_vol >= 100_000: s += 12
    elif pm_vol >= 50_000:  s += 6
    else:                   s += 2

    # קטליסט
    if has_catalyst: s += 25

    # תנודתיות יחסית (ATR/price — כמה המניה "זה")
    rel_atr = atr_d / price
    if rel_atr >= 0.06: s += 15
    elif rel_atr >= 0.04: s += 8
    elif rel_atr >= 0.02: s += 4

    return min(100, s)

# ══════════════════════════════════════════════
# FINVIZ SCRAPER — Pre-Market Gainers (גיבוי)
# ══════════════════════════════════════════════
def get_finviz_pm_gainers() -> list[str]:
    """
    מושך את Top Gainers מ-Finviz (ללא API key).
    מחזיר רשימת סימבולים בלבד.
    """
    try:
        url = "https://finviz.com/screener.ashx?v=111&s=ta_topgainers&f=sh_price_u20,sh_price_o2,sh_avgvol_o200"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            log.warning(f"Finviz: status {resp.status_code}")
            return []

        # מחלץ סימבולים מה-HTML (td class="screener-body-table-nw")
        from html.parser import HTMLParser

        class TickerParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.tickers = []
                self._in_ticker = False

            def handle_starttag(self, tag, attrs):
                attrs_d = dict(attrs)
                if (tag == "a" and
                        attrs_d.get("class", "").startswith("screener-link-primary")):
                    self._in_ticker = True

            def handle_data(self, data):
                if self._in_ticker:
                    t = data.strip()
                    if t and t.isupper() and len(t) <= 5:
                        self.tickers.append(t)
                    self._in_ticker = False

        parser = TickerParser()
        parser.feed(resp.text)
        tickers = list(dict.fromkeys(parser.tickers))  # dedupe, שמור סדר
        log.info(f"Finviz gainers: {tickers[:15]}")
        return tickers[:30]

    except Exception as e:
        log.warning(f"Finviz scraper: {e}")
        return []

# ══════════════════════════════════════════════
# WRITE WATCHLIST
# ══════════════════════════════════════════════
FIELDS = ["date","symbol","price","prev_close","gap_pct",
          "pm_vol","has_catalyst","catalyst_hint",
          "atr_daily","pm_score"]

def write_watchlist(movers: list[dict]):
    today = today_str()

    # שמור שורות ישנות (מימים קודמים) + כתוב את היום
    old_rows = []
    if os.path.exists(WATCHLIST_FILE):
        with open(WATCHLIST_FILE, "r", newline="") as f:
            for row in csv.DictReader(f):
                if row.get("date") != today:
                    old_rows.append(row)

    with open(WATCHLIST_FILE, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for row in old_rows:
            w.writerow({k: row.get(k, "") for k in FIELDS})
        for m in movers:
            w.writerow({k: m.get(k, "") for k in FIELDS})

    log.info(f"✅ נכתבו {len(movers)} מניות ל-{WATCHLIST_FILE}")

# ══════════════════════════════════════════════
# TELEGRAM SUMMARY
# ══════════════════════════════════════════════
def build_summary(movers: list[dict]) -> str:
    lines = [
        f"🌅 *Premarket Scanner — {il_str()} IL*",
        f"━━━━━━━━━━━━━━━━━",
        f"📋 *{len(movers)} מניות נבחרו לרשימת היום*",
        f"━━━━━━━━━━━━━━━━━",
    ]

    for i, m in enumerate(movers[:10], 1):
        cat = "🔥" if m["has_catalyst"] else ("⬆️" if m["gap_pct"] >= 5 else "📈")
        vol_k = m["pm_vol"] // 1000
        hint = f"\n   💬 _{m['catalyst_hint'][:50]}_" if m["has_catalyst"] and m["catalyst_hint"] else ""
        lines.append(
            f"*{i}. {m['symbol']}* {cat} +{m['gap_pct']}% | ${m['price']} | {vol_k}K vol{hint}"
        )

    if len(movers) > 10:
        rest = [m["symbol"] for m in movers[10:]]
        lines.append(f"\n+עוד: {', '.join(rest)}")

    lines += [
        f"━━━━━━━━━━━━━━━━━",
        f"⏰ *סיגנל ירוק רק אחרי 17:15 IL (10:15 NY)*",
        f"🤖 הבוט ירוץ עם הרשימה הזו",
    ]
    return "\n".join(lines)

# ══════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════
def run():
    ny = get_ny()
    log.info(f"🌅 Premarket Scanner | NY: {ny.strftime('%H:%M')} | IL: {il_str()}")

    # ── שלב 1: אסוף יקום רחב ──────────────────
    universe = list(dict.fromkeys(CORE + EXTENDED))  # dedupe

    # הוסף מניות מ-Finviz (top gainers של אתמול / premarket)
    finviz_syms = get_finviz_pm_gainers()
    for sym in finviz_syms:
        if sym not in universe:
            universe.append(sym)

    log.info(f"🔍 סורק {len(universe)} מניות...")

    # ── שלב 2: סרוק כל מניה ──────────────────
    movers = []
    for i, sym in enumerate(universe, 1):
        result = scan_symbol(sym)
        if result:
            movers.append(result)
            log.info(
                f"  ✅ {sym}: +{result['gap_pct']}% | ${result['price']} | "
                f"vol={result['pm_vol']//1000}K | score={result['pm_score']}"
                f"{' 💡catalyst' if result['has_catalyst'] else ''}"
            )
        else:
            log.debug(f"  ⬜ {sym}: לא עובר פילטר")

        # rate limiting — לא להיחסם
        time.sleep(0.3)
        if i % 20 == 0:
            log.info(f"  ... {i}/{len(universe)} סרוקו, {len(movers)} מועמדים עד כה")

    # ── שלב 3: מיין ובחר Top 20 ──────────────
    movers.sort(key=lambda x: x["pm_score"], reverse=True)

    # עדיפות נוספת: מניות עם קטליסט
    with_cat  = [m for m in movers if m["has_catalyst"]]
    without   = [m for m in movers if not m["has_catalyst"]]

    # 60% קטליסט, 40% גאפ/נפח טהור
    n_cat  = min(len(with_cat),  int(MAX_WATCHLIST * 0.6))
    n_pure = min(len(without),   MAX_WATCHLIST - n_cat)
    final  = with_cat[:n_cat] + without[:n_pure]
    final  = final[:MAX_WATCHLIST]

    # ── שלב 4: שמור + שלח ──────────────────
    if not final:
        msg = (f"🌅 *Premarket Scanner — {il_str()} IL*\n"
               f"לא נמצאו מועמדים שעוברים קריטריונים.\n"
               f"הבוט ישתמש ברשימת הבסיס (CORE_LIST).")
        send(msg)
        log.warning("אין מועמדים — הבוט ישתמש ב-CORE_LIST כ-fallback.")
        return

    write_watchlist(final)
    summary = build_summary(final)
    send(summary)

    log.info(f"✅ סיום: {len(final)} מניות ב-{WATCHLIST_FILE}")


if __name__ == "__main__":
    run()


# ══════════════════════════════════════════════
# הוראות GitHub Actions
# ══════════════════════════════════════════════
"""
הוסף ל-.github/workflows/bot.yml:

  premarket:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -r requirements.txt
      - run: python premarket_scanner.py
        env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID:   ${{ secrets.TELEGRAM_CHAT_ID }}
    # מריץ ב-08:30 NY = 15:30 IL (קיץ)
    # schedule: - cron: '30 12 * * 1-5'   ← UTC

  main_bot:
    needs: premarket          # ← הבוט הראשי מחכה לסיום הסקאן!
    runs-on: ubuntu-latest
    ...

תזמון מומלץ:
  premarket_scanner: cron '30 12 * * 1-5'  (08:30 NY)
  bot_main:          cron '15 14 * * 1-5'  (10:15 NY) ← אחרי 45 דק' ייצוב
                     cron '00 15 * * 1-5'  (11:00 NY)
                     cron '00 17 * * 1-5'  (13:00 NY)
                     cron '30 19 * * 1-5'  (15:30 NY) — Power Hour
"""
