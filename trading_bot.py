def get_dynamic_gainers():
    # כתובת מעודכנת ללא הפרמטר שגרם לשגיאה
    url = "https://data.alpaca.markets/v1beta1/screener/stocks/movers"
    try:
        res = requests.get(url, headers=HEADERS)
        if res.status_code != 200:
            log.error(f"Alpaca API Error {res.status_code}: {res.text}")
            return []
        
        data = res.json()
        gainers = data.get('gainers', [])
        
        # סינון סמלים עם שינוי חיובי מעל 3%
        symbols = [s['symbol'] for s in gainers if s['percent_change'] > 3]
        if not symbols:
            return []

        # בקשת Snapshot רק עבור הסמלים שמצאנו
        snap_url = f"https://data.alpaca.markets/v2/stocks/snapshots?symbols={','.join(symbols)}&feed=iex"
        snap_res = requests.get(snap_url, headers=HEADERS).json()

        candidates = []
        for sym, data in snap_res.items():
            # בדיקת תקינות המידע
            if not data or 'dailyBar' not in data:
                continue
                
            price = data['dailyBar'].get('c', 0)
            vol   = data['dailyBar'].get('v', 0)
            
            # בדיקת תנאי מחיר ו-Volume שהגדרת למעלה בקוד
            if (MIN_PRICE <= price <= MAX_PRICE) and (vol >= MIN_VOLUME):
                candidates.append((sym, price))
        
        return candidates
    except Exception as e:
        log.error(f"Error fetching gainers: {e}")
        return []
