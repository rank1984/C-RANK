import yfinance as yf
import pandas as pd
import time
from datetime import datetime

MIN_PRICE = 2
MAX_PRICE = 20

MIN_GAP = 2.0          # מינימום % גאפ
MIN_VOL = 100_000      # ווליום פרה-מרקט מינימלי

MAX_RESULTS = 25

UNIVERSE = [
    "AAPL","TSLA","NVDA","AMD","META","AMZN",
    "MARA","RIOT","CLSK","CIFR","WULF",
    "SOFI","HOOD","UPST","AFRM",
    "RIVN","NIO","LCID",
    "PLTR","IONQ","SOUN","BBAI",
    "NKLA","PLUG","CHPT","OPEN","PTON",
    "GME","AMC","BB"
]

def get_gap_and_volume(sym):
    try:
        t = yf.Ticker(sym)

        # יומי
        hist = t.history(period="5d", interval="1d")
        if len(hist) < 2:
            return None

        prev_close = float(hist["Close"].iloc[-2])

        # פרה מרקט
        pm = t.history(period="1d", interval="5m", prepost=True)
        if pm.empty:
            return None

        curr_price = float(pm["Close"].iloc[-1])
        volume = int(pm["Volume"].sum())

        gap = (curr_price - prev_close) / prev_close * 100

        return {
            "symbol": sym,
            "price": round(curr_price,2),
            "gap": round(gap,2),
            "volume": volume
        }

    except:
        return None

def scan():
    results = []

    print("🚀 Morning Scan Started...\n")

    for sym in UNIVERSE:
        data = get_gap_and_volume(sym)
        if not data:
            continue

        if data["price"] < MIN_PRICE or data["price"] > MAX_PRICE:
            continue

        if data["gap"] < MIN_GAP:
            continue

        if data["volume"] < MIN_VOL:
            continue

        print(f"{sym} | GAP {data['gap']}% | Vol {data['volume']}")
        results.append(data)

        time.sleep(0.3)

    # מיון לפי GAP + Volume
    results = sorted(results,
        key=lambda x: (x["gap"], x["volume"]),
        reverse=True
    )

    return results[:MAX_RESULTS]

def save_watchlist(results):
    df = pd.DataFrame(results)
    df["date"] = datetime.now().strftime("%Y-%m-%d")
    df.to_csv("daily_watchlist.csv", index=False)

    print("\n✅ Saved daily_watchlist.csv")

if __name__ == "__main__":
    data = scan()

    if not data:
        print("❌ No strong movers today")
    else:
        save_watchlist(data)

        print("\n🔥 TOP MOVERS:")
        for i, s in enumerate(data,1):
            print(f"{i}. {s['symbol']} | {s['gap']}% | {s['volume']}")