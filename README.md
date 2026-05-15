# EVALON WINNERS — Telegram Support Bot v5.0

A professional Telegram support bot for EVALON WINNERS trading services.

## Features

- ✅ Delete-then-Send (melt effect)
- ✅ 24h cooldown reminder
- ✅ Channel membership check
- ✅ Two-way messaging (admin ↔ user)
- ✅ Broadcast (text, photo, video, voice, document)
- ✅ Admin approve/decline join requests
- ✅ 12 languages
- ✅ PostgreSQL database (persistent on Railway)
- ✅ Referral system
- ✅ Urgency messages
- ✅ Testimonials / social proof
- ✅ Welcome bonus for new users
- ✅ Daily stats report (8AM)

## Deploy on Railway (Hatua Rahisi)

1. Push repo hii GitHub
2. Nenda railway.app → New Project → Deploy from GitHub repo
3. Chagua repo yako
4. Click **+ New** → **Database** → **Add PostgreSQL**
5. Nenda kwenye bot service → **Variables** tab → Ongeza:
   - `BOT_TOKEN` = token yako ya bot
   - `DATABASE_URL` = (Railway inajaza hii automatically kutoka PostgreSQL)
   - `BOT_USERNAME` = username ya bot yako (bila @)
6. Railway itaanzisha bot automatically ✅

## Admin Commands

| Command | Description |
|---------|-------------|
| `/broadcast msg` | Send message to all users |
| `/stats` | View bot statistics |
| `/sessions` | Manage support sessions |
| `/getid` | Get photo file_id |
