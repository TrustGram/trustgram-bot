# trustgram-bot

The backend and Telegram bot for [TrustGram](https://github.com/trustgram).

Its primary role is to act as a **Zero-Trust Key Server and Message Relay**. It stores encrypted message blobs and public cryptographic bundles, but never sees plaintext or private keys.

## Core Responsibilities

1. **Key Server (X3DH)**: Stores and distributes users' public key bundles (Identity Key, Signed PreKey, One-time PreKeys).
2. **Message Relay**: Provides a store-and-forward mechanism for encrypted message blobs (inboxes).
3. **Telegram Interface**: Serves as the entry point via the Telegram Mini App button and sends real-time notifications.

## Tech Stack

- **Framework**: [FastAPI](https://fastapi.tiangolo.com/) (High-performance API)
- **Telegram Logic**: [aiogram](https://docs.aiogram.dev/) (Asynchronous TG Bot API)
- **Database**: [SQLite](https://www.sqlite.org/) (for MVP) / [PostgreSQL](https://www.postgresql.org/) (for production)
- **ORM**: [SQLAlchemy](https://www.sqlalchemy.org/) or [Tortoise-ORM](https://tortoise.github.io/)
- **Hosting**: [Render](https://render.com/)

## API Endpoints (v1)

### 🔑 Key Management

- `POST /api/v1/keys/register`: Initial upload of the public bundle.
- `GET /api/v1/keys/{telegram_id}`: Fetch Bob's bundle to start an X3DH session.
- `POST /api/v1/keys/otk`: Refill one-time pre-keys when they run low.

### ✉️ Messaging

- `POST /api/v1/chat/send`: Upload an encrypted blob for a recipient.
- `GET /api/v1/chat/inbox`: Fetch pending encrypted messages.
- `DELETE /api/v1/chat/message/{id}`: Acknowledge and remove message from server.

## Database Schema (MVP)

- **Users**: `telegram_id`, `username`, `registration_date`.
- **PublicBundles**: `user_id`, `identity_key`, `signed_pre_key`, `signature`.
- **OneTimeKeys**: `user_id`, `key_id`, `public_key`.
- **Messages**: `id`, `recipient_id`, `sender_id`, `encrypted_payload`, `timestamp`.

## Getting Started

### Prerequisites

- **Python 3.10+** — verify with `python --version`
- **Telegram Bot Token** — create one via [@BotFather](https://t.me/BotFather)
- **Mini App URL** — the deployed `trustgram-ui` URL (Cloudflare Pages or localhost for dev)

### 1. Clone & navigate

```bash
git clone https://github.com/trustgram/trustgram-bot.git
cd trustgram-bot
```

### 2. Create virtual environment

```bash
python -m venv venv
```

Activate it:

```powershell
# Windows (PowerShell)
.\venv\Scripts\Activate.ps1
```

```bash
# macOS / Linux
source venv/bin/activate
```

> **Note:** If PowerShell blocks the script, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` first.

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Copy the template and fill in your values:

```bash
cp .env.example .env
```

Then edit `.env`:

```env
BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
WEBAPP_URL=https://your-mini-app-url.com
DATABASE_URL=sqlite+aiosqlite:///./trustgram.db
```

| Variable | Required | Description |
| --- | --- | --- |
| `BOT_TOKEN` | ✅ | Telegram bot token from @BotFather |
| `WEBAPP_URL` | ✅ | Public URL of the TrustGram Mini App |
| `DATABASE_URL` | ❌ | Defaults to local SQLite file (`trustgram.db`) |

### 5. Run the server

```bash
uvicorn app.main:app --reload
```

The server starts at **<http://127.0.0.1:8000>**. On first launch, SQLite tables are created automatically.

### 6. Verify

```bash
curl http://127.0.0.1:8000/health
# → {"status":"ok","service":"TrustGram"}
```

## Testing the API (Frontend-Free)

You can test all endpoints directly using the interactive documentation:

1. **Swagger UI**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
2. **ReDoc**: [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)

### Authentication
To test endpoints that require authentication, you must provide a valid `X-Init-Data` header containing the `initData` string from the Telegram Mini App.

## Running Tests

The project includes an automated test suite powered by `pytest`. The tests use an isolated in-memory SQLite database and mock the Telegram WebApp authentication, so they won't affect your local database.

### Running the Suite

First, ensure you have the test dependencies installed:

```bash
pip install -r requirements-dev.txt
```

Execute the tests (you'll need to provide a mock bot token since `aiogram` validates it on startup):

```bash
# Linux / macOS
BOT_TOKEN="mock_token" pytest tests -v

# Windows (PowerShell)
$env:BOT_TOKEN="mock_token"; pytest tests -v
```

## Security Design

- **No Plaintext**: The server never receives unencrypted message content.
- **Rate Limiting**: Protection against spam and key-exhaustion attacks.
- **Telegram Validation**: Every API request is validated using `initData` hash from Telegram WebApp.
