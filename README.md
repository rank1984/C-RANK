# C-RANK    # 🤖 בוט טריידינג יומי — מדריך הגדרה מלא

## מה יש בפרויקט

| קובץ | תפקיד |
|------|--------|
| `daily_bot.py` | קוד הבוט המלא |
| `requirements.txt` | ספריות Python |
| `Dockerfile` | לפריסה על Railway/Render |
| `.github/workflows/run_bot.yml` | GitHub Actions — דוח בוקר יומי |

---

## שלב 1 — יצירת בוט טלגרם

1. פתח טלגרם → חפש `@BotFather`
2. שלח `/newbot`
3. תן שם לבוט (לדוגמה: `MyTradingBot`)
4. תקבל **TOKEN** — שמור אותו

### קבלת CHAT_ID
1. חפש `@userinfobot` בטלגרם
2. שלח `/start`
3. תקבל את ה-**CHAT_ID** שלך

---

## שלב 2 — מפתח FMP API (חינמי)

1. היכנס ל: https://financialmodelingprep.com/developer/docs
2. לחץ "Get Free API Key"
3. הירשם עם אימייל
4. תקבל **API_KEY**

> הגרסה החינמית מאפשרת ~250 קריאות/יום — מספיק לדוח בוקר.
> לסריקה כל 5 דקות — דרוש פלאן בתשלום ($14/חודש) או Polygon.io (חינמי עם הגבלות).

---

## שלב 3 — הגדרת GitHub Secrets

1. גש לפרויקט ב-GitHub
2. Settings → Secrets and variables → Actions
3. לחץ "New repository secret" והוסף:

| שם | ערך |
|----|-----|
| `TOKEN` | ה-TOKEN מהבוט שיצרת |
| `CHAT_ID` | ה-CHAT_ID שלך |
| `API_KEY` | המפתח מ-FMP |

---

## שלב 4 — העלאה ל-GitHub

```bash
git init
git add .
git commit -m "Initial trading bot"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/trading-bot.git
git push -u origin main
```

### הרצה ידנית
GitHub → Actions → Trading Bot Morning Scan → Run workflow

---

## שלב 5 — שדרוג ל-Railway (סריקה כל 5 דקות — חינמי!)

### הרשמה ל-Railway
1. היכנס ל: https://railway.app
2. Sign up with GitHub
3. New Project → Deploy from GitHub repo
4. בחר את הפרויקט שלך

### הגדרת משתנים ב-Railway
Variables → Add Variable:
- `TOKEN` = הטוקן שלך
- `CHAT_ID` = ה-CHAT_ID שלך
- `API_KEY` = המפתח מ-FMP
- `MODE` = `live_loop`

### Railway חינמי — $5 קרדיט/חודש
לבוט פשוט זה מספיק לכ-500 שעות הפעלה בחודש.

---

## כלים חינמיים — סיכום

| כלי | שימוש | מחיר |
|-----|--------|-------|
| GitHub | אחסון קוד + CI/CD | חינם |
| Railway | שרת תמיד דולק | $5/חודש (או חינם עם הגבלה) |
| FMP API | נתוני מניות | חינם (250 קריאות/יום) |
| Telegram Bot | התראות | חינם |
| Polygon.io | חלופה ל-FMP | חינם (אך נתוני realtime עולים) |

---

## מבנה ההודעות בטלגרם

### דוח בוקר (09:00 בבוקר)
```
📊 דוח בוקר — מניות מומלצות
1. 🔥 TICKER | דירוג: 85/100
   💰 $12.5  → כניסה: $12.54
   🎯 יעד: $13.88 (+10.5%)  🛑 סטופ: $12.10
```

### התראת כניסה
```
🚀 כניסה מומלצת — TICKER
💰 מחיר נוכחי: $12.5
📥 נקודת כניסה: $12.54
🎯 יעד רווח: $13.88 (+10.5%)
🛑 סטופ לוס: $12.10
📊 דירוג AI: 85/100
⚖️ סיכוי/סיכון: 1:2.8
```

### התראת יציאה
```
🏆 צא מ-TICKER עכשיו!
📍 סיבה: הגעת ליעד הרווח 🎯
💲 מחיר נוכחי: $13.95
📊 תוצאה: ✅ רווח של +11.2%!
```

---

## תוכנית הגדלת תקציב

| שלב | תקציב | מטרה | טיפ |
|-----|--------|-------|-----|
| 1 | $250 → $500 | 3% ממוצע/יום | מקסימום עסקה אחת |
| 2 | $500 → $2,000 | 2 עסקאות במקביל | רשום יומן עסקאות |
| 3 | $2K → $10K+ | Prop trading / מרג'ין | רק אחרי track record |

---

## אזהרה חשובה ⚠️
הבוט הוא כלי עזר בלבד. הוא לא מחליט בשבילך ולא מבצע עסקאות.
תמיד כבד את הסטופ לוס. אל תסכן יותר מ-10% מהתיק בעסקה אחת.
**זה לא ייעוץ השקעות.**
