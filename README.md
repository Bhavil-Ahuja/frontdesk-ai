# 🦷 SmileCare Dental AI Voice Agent

A production-demo-ready AI-powered voice agent for dental offices. Handles inbound phone calls, answers patient questions, books/reschedules/cancels appointments, sends SMS confirmations, and provides a full admin dashboard — all powered by a local LLM.

## Architecture

```
┌──────────────┐     ┌───────────────┐     ┌──────────────────────┐
│  Patient      │     │   Vapi.ai     │     │   FastAPI Backend    │
│  Phone Call   │────▶│  (STT + TTS)  │────▶│   POST /webhook/vapi │
└──────────────┘     └───────────────┘     └──────────┬───────────┘
                                                       │
                          ┌────────────────────────────┼────────────────┐
                          │                            │                │
                          ▼                            ▼                ▼
                  ┌───────────────┐          ┌────────────────┐  ┌──────────┐
                  │  Ollama       │          │  Cal.com API   │  │  Twilio  │
                  │  qwen2.5:7b   │          │  (Scheduling)  │  │  (SMS)   │
                  │  (Local LLM)  │          └────────────────┘  └──────────┘
                  └───────────────┘
                          │
                          ▼
                  ┌───────────────┐          ┌────────────────────────────┐
                  │  PostgreSQL   │◀─────────│  React + Tailwind Dashboard│
                  │  (Docker)     │          │  (Admin Panel at /)        │
                  └───────────────┘          └────────────────────────────┘
```

## Features

- **AI Voice Receptionist** — Natural phone conversations powered by Ollama + qwen2.5:7b
- **Appointment Scheduling** — Book, reschedule, and cancel via Cal.com integration
- **SMS Notifications** — Automated confirmations and cancellations via Twilio
- **Emergency Triage** — Handles dental emergencies with appropriate urgency
- **Smart Escalation** — Transfers to humans when needed (billing disputes, distressed patients)
- **Admin Dashboard** — Real-time stats, call logs with transcripts, appointment calendar
- **Editable Knowledge Base** — Update office info, services, FAQs from the dashboard
- **Demo Mode** — Works fully offline with simulated SMS and calendar responses

## Prerequisites

| Requirement | Version | Purpose |
|---|---|---|
| Python | 3.11+ | Backend runtime |
| Node.js | 18+ | Frontend build |
| Docker | 20+ | PostgreSQL database |
| Ollama | Latest | Local LLM inference |

### External accounts (for production — not needed in demo mode):
- [Vapi.ai](https://vapi.ai) — Voice call handling
- [Cal.com](https://cal.com) — Appointment scheduling
- [Twilio](https://twilio.com) — SMS notifications

## Quick Start

### 1. Clone and configure

```bash
cd dental-voice-agent
cp .env.example .env
# Edit .env with your API keys (or leave empty for demo mode)
```

### 2. Pull the LLM model

```bash
ollama pull qwen2.5:7b
```

### 3. Start the database

```bash
docker-compose up -d
```

### 4. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 5. Seed demo data

```bash
python seed_data.py
```

### 6. Build the frontend

```bash
cd frontend
npm install
npm run build
cd ..
```

### 7. Start the server

```bash
python -m backend.main
```

Open http://localhost:8000 for the dashboard.

### 8. Expose for Vapi webhooks (production)

Vapi needs a public URL to send webhook events to your backend. We use **localhost.run** — zero install, just SSH:

```bash
ssh -R 80:localhost:8000 nokey@localhost.run
```

You'll see output like:
```
Connect to http://localhost:8000 or https://abc123.lhr.life
```

Copy the `https://...lhr.life` URL and update your `.env`:
```
SERVER_BASE_URL=https://abc123.lhr.life
```

Then restart the backend so Vapi registers the new webhook URL:
```bash
python -m backend.main
```

> **Tip:** The localhost.run URL changes every time you reconnect. For a stable
> subdomain, create a free account at [localhost.run](https://localhost.run) and
> use `ssh -R 80:localhost:8000 your-token@localhost.run`.

<details>
<summary>Other tunnel options (if localhost.run isn't available)</summary>

**Cloudflare Tunnel (free, requires install):**
```bash
brew install cloudflared
cloudflared tunnel --url http://localhost:8000
# → https://random-words.trycloudflare.com
```

**Deploy directly to Railway / Render (free tier):**
See the Deployment section below — no tunnel needed.
</details>

## Getting API Keys

### Vapi.ai
1. Sign up at [vapi.ai](https://vapi.ai)
2. Go to **Dashboard → Organization → API Keys**
3. Copy your API key → `VAPI_API_KEY`
4. Go to **Phone Numbers** → Buy or bring a number → Copy ID → `VAPI_PHONE_NUMBER_ID`
5. The assistant ID will be auto-created on first startup

### Cal.com
1. Sign up at [cal.com](https://cal.com)
2. Go to **Settings → Developer → API Keys**
3. Create a key → `CALCOM_API_KEY`
4. Create event types for each appointment type (New Patient, Cleaning, Emergency, Consultation)
5. Copy each event type ID from the URL (e.g., `/event-types/123`) into the corresponding `.env` variable

### Twilio
1. Sign up at [twilio.com](https://twilio.com)
2. Go to **Console → Account Info**
3. Copy Account SID → `TWILIO_ACCOUNT_SID`
4. Copy Auth Token → `TWILIO_AUTH_TOKEN`
5. Buy a phone number → `TWILIO_PHONE_NUMBER` (format: `+15551234567`)

## Customization for Real Dental Offices

### 1. Update `.env`
- Change `OFFICE_NAME` to the practice name
- Set `OFFICE_TIMEZONE` to the correct timezone
- Set `ESCALATION_PHONE_NUMBER` to the office's real number
- Set `DEMO_MODE=false` for production

### 2. Edit the Knowledge Base
Either use the dashboard UI at `/knowledge` or directly edit:
```
backend/knowledge/dental_kb.json
```

Update:
- Office name, address, phone, hours
- Insurance providers accepted
- Services and pricing
- FAQs specific to the practice

### 3. Customize the System Prompt
Edit `backend/prompts/dental_agent.py` to:
- Change the agent's name (default: "Sarah")
- Adjust personality traits
- Add practice-specific policies
- Modify emergency protocols

## Demo Walkthrough

1. **Start everything** (steps 1-7 above)
2. **Open the dashboard** at http://localhost:8000
3. **Explore the Overview** — see call stats, charts, and agent status
4. **Check Call Logs** — click any row to see full conversation transcripts
5. **View Appointments** — navigate the weekly calendar, click cards for details
6. **Edit Knowledge Base** — change pricing, add FAQs, test the response preview
7. **Configure the Agent** — toggle active/paused, change voice, set business hours

### Testing a Live Call (with Vapi)
1. Ensure Vapi is configured and your server is publicly accessible
2. Call the Vapi phone number
3. Talk to "Sarah" — try booking an appointment
4. Watch the call appear in real-time on the dashboard
5. Check SMS delivery (or logs in demo mode)

## Deployment (Railway / Render)

### Railway (Free Tier)
1. Push code to GitHub
2. Go to [railway.app](https://railway.app) → **New Project → Deploy from GitHub**
3. Add a PostgreSQL service
4. Set environment variables in the Railway dashboard
5. Railway auto-detects Python and deploys
6. Use the Railway-provided URL as `SERVER_BASE_URL`

### Render (Free Tier)
1. Push code to GitHub
2. Go to [render.com](https://render.com) → **New → Web Service**
3. Connect your repo, set:
   - **Build Command:** `pip install -r requirements.txt && cd frontend && npm install && npm run build`
   - **Start Command:** `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
4. Add a PostgreSQL database from the Render dashboard
5. Set all environment variables
6. Use the Render-provided URL as `SERVER_BASE_URL`

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `GET` | `/api/dashboard/stats` | Dashboard overview statistics |
| `GET` | `/api/calls` | Paginated call logs |
| `GET` | `/api/calls/{id}` | Single call with transcript |
| `GET` | `/api/calls/export` | Export calls as CSV |
| `GET` | `/api/appointments` | List appointments |
| `POST` | `/api/appointments/{id}/cancel` | Cancel appointment |
| `GET` | `/api/knowledge` | Get knowledge base |
| `PUT` | `/api/knowledge` | Update knowledge base |
| `GET` | `/api/config` | Get agent config |
| `PUT` | `/api/config` | Update agent config |
| `POST` | `/webhook/vapi` | Vapi webhook handler |

## Tech Stack

- **Backend:** Python 3.11+, FastAPI, SQLAlchemy (async), Pydantic
- **LLM:** Ollama + qwen2.5:7b (local, OpenAI-compatible API)
- **Voice:** Vapi.ai (STT, TTS, phone call orchestration)
- **Scheduling:** Cal.com v2 API
- **SMS:** Twilio
- **Database:** PostgreSQL 15 (Docker)
- **Frontend:** React 18, Tailwind CSS, Recharts, Lucide Icons
- **Build:** Vite

## License

MIT
