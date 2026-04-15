import requests
import feedparser
import pandas as pd
import os
import re
from datetime import datetime

# ============================================================
# ALTERNATIVE SOCIAL SCREENER – NO REDDIT API REQUIRED
# Uses: Stocktwits API + Yahoo Finance RSS + optional Reddit (if keys exist)
# ============================================================

def get_reddit_optional():
    """אופציונלי – רץ רק אם יש מפתחות Reddit"""
    reddit_client = os.environ.get("REDDIT_CLIENT_ID", "").strip()
    reddit_secret = os.environ.get("REDDIT_SECRET", "").strip()
    
    if not reddit_client or not reddit_secret:
        print("⚠️ Reddit: אין מפתחות API – מדלג על Reddit (אופציונלי)")
        return {}
    
    try:
        import praw
        reddit = praw.Reddit(
            client_id=reddit_client,
            client_secret=reddit_secret,
            user_agent="DayTradeBot/1.0"
        )
        subreddits = ["wallstreetbets", "pennystocks", "SmallCapStocks"]
        mentions = {}
        for sub in subreddits:
            for post in reddit.subreddit(sub).hot(limit=30):
                title = post.title.upper()
                words = title.split()
                for w in words:
                    if w.isalpha() and len(w) >= 2 and w.isupper() and w not in ["A","AN","THE","FOR","AND","OF","TO","IN","ON","AT","THIS","THAT","WITH","FROM"]:
                        mentions[w] = mentions.get(w, 0) + 1
        print(f"✅ Reddit: {len(mentions)} סימבולים זוהו")
        return mentions
    except Exception as e:
        print(f"⚠️ Reddit API error: {e} – ממשיך ללא Reddit")
        return {}

def get_stocktwits_trending():
    """Stocktwits – חינמי, לא דורש מפתח"""
    try:
        url = "https://api.stocktwits.com/api/2/trending/symbols.json"
        r = requests.get(url, timeout=10)
        data = r.json()
        symbols = [item["symbol"] for item in data.get("symbols", [])[:30]]
        print(f"✅ Stocktwits: {len(symbols)} סימבולים חמים")
        return {sym: 10 for sym in symbols}
    except Exception as e:
        print(f"⚠️ Stocktwits error: {e}")
        return {}

def get_news_symbols():
    """Yahoo Finance RSS – חינמי, לא דורש מפתח"""
    try:
        url = "https://feeds.finance.yahoo.com/rss/2.0/headline?s=all&region=US&lang=en-US"
        feed = feedparser.parse(url)
        symbols = set()
        for entry in feed.entries[:25]:
            title = entry.title.upper()
            # חיפוש סימבולים לפי דפוס: מילה באורך 2-5 אותיות גדולות
            words = re.findall(r'\b[A-Z]{2,5}\b', title)
            for w in words:
                if len(w) >= 2 and w.isalpha():
                    symbols.add(w)
        print(f"✅ Yahoo News: {len(symbols)} סימבולים מחדשות")
        return {sym: 5 for sym in symbols}
    except Exception as e:
        print(f"⚠️ Yahoo RSS error: {e}")
        return {}

def generate_watchlist():
    """מיזוג כל המקורות + רשימת ליבה"""
    
    # שליפת נתונים (Reddit אופציונלי)
    reddit = get_reddit_optional()
    st = get_stocktwits_trending()
    news = get_news_symbols()
    
    # מיזוג ניקוד
    combined = {}
    for d in [reddit, st, news]:
        for sym, score in d.items():
            combined[sym] = combined.get(sym, 0) + score
    
    # סינון מניות לא רלוונטיות
    exclude = ["SPY", "QQQ", "AAPL", "MSFT", "AMZN", "GOOG", "TSLA", "META", "NVDA", 
               "NFLX", "AMD", "INTC", "BA", "DIS", "V", "JPM", "WMT", "JNJ", "PG", "UNH", "HD", "MA", "PYPL", "ADBE", "CRM"]
    
    candidates = [(sym, scr) for sym, scr in combined.items() 
                  if scr >= 3 and sym not in exclude and len(sym) <= 5 and sym.isalpha()]
    candidates.sort(key=lambda x: x[1], reverse=True)
    
    # רשימת ליבה קבועה
    core = ["MARA","RIOT","CLSK","CIFR","WULF","SOFI","NU","RIVN","LCID","SOUN","BBAI","PLUG","CHPT","OPEN","PTON","GME","IONQ","NKLA","HOOD","UPST","AFRM"]
    
    # בניית רשימה סופית
    final_list = []
    for sym, _ in candidates[:30]:
        if sym not in final_list:
            final_list.append(sym)
    for sym in core:
        if sym not in final_list:
            final_list.append(sym)
    
    # שמירה לקובץ
    today = datetime.now().strftime("%Y-%m-%d")
    df = pd.DataFrame({"symbol": final_list, "date": today, "score": 1})
    df.to_csv("daily_watchlist.csv", index=False)
    print(f"✅ Watchlist נשמר: {len(final_list)} מניות")
    return final_list

if __name__ == "__main__":
    generate_watchlist()
final_list = core[:15] + [sym for sym, _ in candidates[:10] if sym not in core[:15]]
