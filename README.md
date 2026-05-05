# trustgram-bot

TrustGram backend — Telegram Bot + API server.

## Stack
- Python / FastAPI
- aiogram 3
- Hosted on Render

## Deploy
Production: https://trustgram-bot.onrender.com

Automatic deployment on push to `main` via Render.

## Environment Variables
| Variable | Description |
|----------|-------------|
| `TOKEN` | Telegram Bot Token (from @BotFather) |
| `WEBAPP_URL` | Frontend URL (https://trustgram-ui.pages.dev) |

## Webhook Setup
After deploy, register webhook:
```
https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://trustgram-bot.onrender.com/webhook
```
