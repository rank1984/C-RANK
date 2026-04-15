import pandas as pd
import json
import os
from datetime import datetime, timedelta

CONFIG_FILE = "bot_config.json"

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {"alpha_needed": 80, "vol_needed": 130, "rsi_upper": 72, "rsi_lower": 50}

def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

def compute_success_rate(df, col, threshold, direction="ge"):
    if direction == "ge":
        mask = df[col] >= threshold
    else:
        mask = df[col] <= threshold
    subset = df[mask]
    if len(subset) == 0:
        return None
    wins = (subset["pnl_usd"] > 0).sum()
    return wins / len(subset)

def learn():
    yesterday = (datetime.now() - timedelta(1)).strftime("%Y-%m-%d")
    try:
        df = pd.read_csv("signals_log.csv")
        df = df[df["date"] == yesterday]
        df["pnl_usd"] = pd.to_numeric(df["pnl_usd"], errors="coerce")
        df = df.dropna(subset=["pnl_usd"])
        if len(df) < 3:
            print("לא מספיק סיגנלים ביום הקודם, דילוג על למידה")
            return
    except Exception as e:
        print(f"שגיאה בקריאת signals_log: {e}")
        return

    cfg = load_config()
    best_alpha = cfg["alpha_needed"]
    best_rate = 0
    for a in range(60, 91, 5):
        rate = compute_success_rate(df, "score", a, "ge")
        if rate and rate > best_rate:
            best_rate = rate
            best_alpha = a
    
    best_vol = cfg["vol_needed"]
    best_vrate = 0
    for v in range(100, 201, 20):
        rate = compute_success_rate(df, "vol_pct", v, "ge")
        if rate and rate > best_vrate:
            best_vrate = rate
            best_vol = v
    
    cfg["alpha_needed"] = best_alpha
    cfg["vol_needed"] = best_vol
    cfg["last_updated"] = datetime.now().isoformat()
    save_config(cfg)
    print(f"📈 למידה: alpha_needed={best_alpha}, vol_needed={best_vol}, success_rate={best_rate:.0%}")

if __name__ == "__main__":
    learn()
