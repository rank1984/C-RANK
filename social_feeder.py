import praw
import requests
import feedparser
import pandas as pd
import os
from datetime import datetime

def get_reddit_trending():
    """מחזיר מילון {symbol: mentions_count} מ-reddit"""
    try:
        reddit = praw.Reddit(
            client_id=os.environ.get("REDDIT_CLIENT_ID", ""),
            client_secret=os.environ.get("REDDIT_SECRET", ""),
            user_agent="DayTradeBot/1.0"
        )
        subreddits = ["wallstreetbets", "pennystocks", "SmallCapStocks"]
        mentions = {}
        for sub in subreddits:
            for post in reddit.subreddit(sub).hot(limit=50):
                title = post.title.upper()
                words = title.split()
                for w in words:
                    if w.isalpha() and len(w) >= 2 and w.isupper() and w not in ["A","AN","THE","FOR","AND","OF","TO","IN","ON","AT"]:
                        mentions[w] = mentions.get(w, 0) + 1
        return mentions
    except Exception as e:
        print(f"Reddit error: {e}")
        return {}

def get_stocktwits_trending():
    try:
        url = "https://api.stocktwits.com/api/2/trending/symbols.json"
        r = requests.get(url, timeout=10)
        data = r.json()
        symbols = [item["symbol"] for item in data.get("symbols", [])[:30]]
        return {sym: 10 for sym in symbols}
    except:
        return {}

def get_news_symbols():
    url = "https://feeds.finance.yahoo.com/rss/2.0/headline?s=all&region=US&lang=en-US"
    feed = feedparser.parse(url)
    symbols = set()
    for entry in feed.entries[:20]:
        title = entry.title.upper()
        for word in title.split():
            if len(word) <= 5 and word.isalpha() and word.isupper():
                symbols.add(word)
    return {sym: 5 for sym in symbols}

def generate_watchlist():
    reddit = get_reddit_trending()
    st = get_stocktwits_trending()
    news = get_news_symbols()
    
    combined = {}
    for d in [reddit, st, news]:
        for sym, score in d.items():
            combined[sym] = combined.get(sym, 0) + score
    
    exclude = ["SPY", "QQQ", "AAPL", "MSFT", "AMZN", "GOOG", "TSLA", "META", "NVDA", "NFLX", "AMD", "INTC"]
    candidates = [(sym, scr) for sym, scr in combined.items() 
                  if scr >= 5 and sym not in exclude and len(sym) <= 5]
    candidates.sort(key=lambda x: x[1], reverse=True)
    
    core = ["MARA","RIOT","CLSK","CIFR","WULF","SOFI","NU","RIVN","LCID","SOUN","BBAI","PLUG","CHPT","OPEN","PTON","GME","IONQ","NKLA","HOOD","UPST","AFRM"]
    final_list = []
    for sym, _ in candidates[:30]:
        if sym not in final_list:
            final_list.append(sym)
    for sym in core:
        if sym not in final_list:
            final_list.append(sym)
    
    today = datetime.now().strftime("%Y-%m-%d")
    df = pd.DataFrame({"symbol": final_list, "date": today, "score": 1})
    df.to_csv("daily_watchlist.csv", index=False)
    print(f"✅ Watchlist נשמר: {len(final_list)} מניות")
    return final_list

if __name__ == "__main__":
    generate_watchlist()
