# 🚀 RTS Monitoring Bot — Railway.app Deployment Guide

Pura code Railway.app par deploy karne ke liye ready hai! Neeche diye gaye simple steps follow karein:

---

## Step 1: GitHub par Repository banayein

1. [GitHub](https://github.com/new) par jayein.
2. Repository name daalein (e.g. `rts-monitoring-bot`).
3. Isko **Private** select karein aur **Create repository** par click karein.
4. Terminal / PowerShell me yeh commands chalayein:

```powershell
git init
git add .
git commit -m "Initial commit for RTS Monitoring Telegram Bot"
git branch -M main
git remote add origin https://github.com/<YOUR_GITHUB_USERNAME>/rts-monitoring-bot.git
git push -u origin main
```

---

## Step 2: Railway.app par Deploy karein

1. [Railway.app](https://railway.app) open karein aur login karein.
2. **`+ New Project`** button par click karein.
3. **`Deploy from GitHub repo`** select karein aur apni repo (`rts-monitoring-bot`) choose karein.
4. Railway automatically **Dockerfile** detect karke build start kar dega.

---

## Step 3: Railway me Environment Variables add karein

Railway project dashboard me **Variables** tab me jayein aur yeh keys add karein:

| Variable Name | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | `<YOUR_TELEGRAM_BOT_TOKEN>` |
| `TELEGRAM_GROUP_ID` | `<YOUR_TELEGRAM_GROUP_ID>` |
| `OPENROUTER_API_KEY` | `<YOUR_OPENROUTER_API_KEY>` |
| `OPENROUTER_MODEL` | `openai/gpt-5.6-luna` |
| `IT20_USERNAME` | `10250806` |
| `IT20_PASSWORD` | `<YOUR_PORTAL_PASSWORD>` |
| `IT20_BASE_URL` | `https://app.indiapost.gov.in/employeeportal/home` |
| `IT20_TRACK_URL` | `https://app.indiapost.gov.in/tracking/track/article` |
| `IT20_OTP_TIMEOUT_SEC` | `180` |

*(Aap apne `.env` file se exact values copy karke Railway Variables me paste kar sakte hain)*

> *Variables save hote hi Railway bot ko auto-redeploy kar dega!*

---

## Step 4: Telegram Group me Test karein

1. Bot ko apne group me add karein aur **Admin rights** dein.
2. Group me message bhejein:
   ```text
   start today work
   ```
3. Bot reply karega ki session start ho gaya hai.
4. Parcel ki photos bhejein (1-1 karke ya batch me).
5. Photos bhejne ke baad message karein:
   ```text
   complete
   ```
6. Bot AI se data extract karega, India Post portal par login karega, **Mobile OTP** select karke group me alert bhejega:
   *"📱 Registered mobile number par aaya hua 6-digit OTP code yahan reply karein..."*
7. User group me Mobile OTP code type karega (e.g. `285123`), bot turant login karke sabhi articles track karega.
8. Final Excel report directly Telegram group me deliver ho jayegi! 🎉
