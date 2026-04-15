import requests
import feedparser
import pandas as pd
import os
import re
from datetime import datetime

# ============================================================
# SOCIAL FEEDER – VERSION 2 (FIXED)
# No Reddit API required – runs fine without keys
# ============================================================

def get_reddit_optional():
    """אופציונלי – מדלג בשקט אם אין מפתחות"""
    reddit_client = os.environ.get("REDDIT_CLIENT_ID", "").strip()
    reddit_secret = os.environ.get("REDDIT_SECRET", "").strip()
    if not reddit_client or not reddit_secret:
        return {}
    try:
        import praw
        reddit = praw.Reddit(client_id=reddit_client, client_secret=reddit_secret, user_agent="DayTradeBot/1.0")
        mentions = {}
        for sub in ["wallstreetbets", "pennystocks", "SmallCapStocks"]:
            for post in reddit.subreddit(sub).hot(limit=30):
                for w in post.title.upper().split():
                    if w.isalpha() and 2 <= len(w) <= 5 and w not in ["A","AN","THE","FOR","AND","OF","TO","IN","ON","AT"]:
                        mentions[w] = mentions.get(w, 0) + 1
        return mentions
    except:
        return {}

def get_stocktwits_trending():
    """Stocktwits – מטפל בשגיאות JSON"""
    try:
        url = "https://api.stocktwits.com/api/2/trending/symbols.json"
        r = requests.get(url, timeout=8)
        if r.status_code != 200 or not r.text.strip():
            return {}
        data = r.json()
        symbols = [item["symbol"] for item in data.get("symbols", [])[:20]]
        return {sym: 10 for sym in symbols}
    except:
        return {}

def get_news_symbols():
    """Yahoo Finance RSS"""
    try:
        url = "https://feeds.finance.yahoo.com/rss/2.0/headline?s=all&region=US&lang=en-US"
        feed = feedparser.parse(url)
        symbols = set()
        for entry in feed.entries[:20]:
            for w in re.findall(r'\b[A-Z]{2,5}\b', entry.title.upper()):
                symbols.add(w)
        return {sym: 5 for sym in symbols}
    except:
        return {}

def generate_watchlist():
    # שליפת נתונים
    reddit = get_reddit_optional()
    st = get_stocktwits_trending()
    news = get_news_symbols()
    
    # מיזוג ניקוד
    combined = {}
    for d in [reddit, st, news]:
        for sym, score in d.items():
            combined[sym] = combined.get(sym, 0) + score
    
    # סינון מניות גדולות
    exclude = ["SPY","QQQ","AAPL","MSFT","AMZN","GOOG","TSLA","META","NVDA","NFLX","AMD","INTC"]
    candidates = [(sym, scr) for sym, scr in combined.items() 
                  if scr >= 3 and sym not in exclude and len(sym) <= 5 and sym.isalpha()]
    candidates.sort(key=lambda x: x[1], reverse=True)
    
    # ✅ רשימת הליבה – חובה להגדיר!
    core = ["MARA","RIOT","CLSK","CIFR","WULF","SOFI","NU","RIVN","LCID","SOUN","BBAI","PLUG","CHPT","OPEN","PTON","GME","IONQ","NKLA","HOOD","UPST","AFRM"]
    
    # בנה רשימה קצרה: 15 ליבה + עד 5 מועמדים חדשים
    core_short = core[:15]
    extra = [sym for sym, _ in candidates[:5] if sym not in core_short]
    final_list = core_short + extra
    
    # שמירה
    today = datetime.now().strftime("%Y-%m-%d")
    df = pd.DataFrame({"symbol": final_list, "date": today})
    df.to_csv("daily_watchlist.csv", index=False)
    print(f"✅ Watchlist נשמר: {len(final_list)} מניות")
    print(f"   {', '.join(final_list[:10])}...")

if __name__ == "__main__":
    generate_watchlist()
