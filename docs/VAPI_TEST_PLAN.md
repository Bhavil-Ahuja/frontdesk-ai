# Vapi Live Test Plan — Scheduler.ai Voice Agent

This document lists every scenario you should exercise on a real Vapi call,
grouped by category. It's the manual companion to the deterministic flow
suite at `tests/test_conversation_flows.py`.

---

## About the Vapi system prompt

**You do NOT need to configure a system prompt in Vapi.** The backend's
`llm_proxy.py` always discards whatever Vapi sends and injects our own
system prompt from `backend/prompts/agent_prompt.py`. Whatever you
type in Vapi's "System Prompt" field is irrelevant.

### Recommended Vapi assistant config

| Field              | Value                                                                 |
|--------------------|-----------------------------------------------------------------------|
| Provider           | Custom LLM                                                            |
| Model              | `qwen3:8b` (or your configured Ollama model)                         |
| Custom LLM URL     | `<your-lhr-url>/api/llm` (no trailing `/chat/completions`)            |
| System Prompt      | leave blank or `You are a receptionist.` — does not matter            |
| First Message Mode | Assistant speaks first                                                |
| First Message      | `Thank you for calling. How can I help you today?`                    |

---

## About response speed

Automated test results vs Vapi's ~20 s timeout:

| Scenario                                              | Avg latency | Status     |
|-------------------------------------------------------|-------------|------------|
| Simple chat (no tool)                                 | 1.2–1.5 s   | Comfortable|
| Single tool call + reply                              | 2.5–4 s     | Comfortable|
| Cold model load (first call after Ollama unloads)     | 8–12 s      | Risky      |

### Pre-warm Ollama before each demo session

Run this once before calling — keeps the model resident in RAM:

```bash
curl -s http://localhost:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3:8b","messages":[{"role":"user","content":"hi"}],"max_tokens":5}' >/dev/null
```

After that, Ollama keeps the model loaded for ~5 minutes of inactivity.

---

## Pre-flight checklist (run before every test session)

1. Backend running: `./start.sh`
2. SSH tunnel URL pasted into Vapi's "Custom LLM URL" field (minus `/chat/completions`)
3. Ollama warm (run the curl above)
4. Google Calendar open in browser to verify bookings
5. Real cell phone ready for SMS confirmation

---

## Category 1 — Information / Q&A
**Tools expected:** `get_office_info`. **Latency target:** 1–2 s per reply.

Run all of these in one call, listening for natural responses.

| Say                                  | Expect to hear (key elements)                                         | Should NOT happen                |
|--------------------------------------|-----------------------------------------------------------------------|----------------------------------|
| "Hi."                                | Friendly 1-line greeting, asks how to help                            | No transfer talk, no date/time   |
| "What are your hours?"               | Business hours from KB (varies per tenant)                            | No tool call delay               |
| "Where are you located?"             | Address from KB                                                       | —                                |
| "How much is a consultation?"        | Price range from KB                                                   | —                                |
| "What services do you offer?"        | Service list from KB                                                  | —                                |
| "What payment methods do you take?"  | Credit cards, HSA/FSA, financing options, etc.                        | —                                |
| "I'm really nervous about coming in."| Empathetic; mentions comfort, patience, breaks                        | No tool call                     |

**Pass criteria:** Each answer arrives in 1–2 seconds, sounds natural, no JSON or technical leaks.

---

## Category 2 — Scheduling Inquiry
**Tools expected:** `get_available_slots`. **Latency target:** 2–4 s.

Start a fresh call for clean conversation state.

| Say                                | Expect to hear                                            | Backend log should show                            |
|------------------------------------|-----------------------------------------------------------|----------------------------------------------------|
| "Do you have any slots Tuesday?"   | "Yes, on Tuesday we have 9 AM, 11 AM, 3 PM…"             | `get_available_slots(date="...")`                  |
| "Got any time tomorrow morning?"   | Lists tomorrow's morning slots                            | `get_available_slots(date="...")`                  |
| "Can I book for next Monday?"      | Lists Monday's slots                                      | `get_available_slots(date="...")`                  |
| "Anything today?"                  | "Sorry, no availability — try another day?"               | `get_available_slots(date="...")` returns 0         |

**Pass criteria:**
- Real calendar slots are spoken naturally
- **No JSON, no field names, no slot strings like `T09:00:00`**
- Reply in 2–4 seconds

---

## Category 3 — Full Booking Flow (THE BIG ONE)
**Tools expected:** `get_available_slots` then `book_appointment`. **Latency target:** 3–5 s per turn. Use a **fresh call**.

### Turn 1
**You say:** *"I'd like to book an appointment for Monday."*

- **Hear:** 2–3 Monday times offered (e.g. "9, 10, or 2 PM")
- **Backend log:** `get_available_slots(date="...", appointment_type="...")`
- **Watch for:** should NOT say "your appointment is booked" yet

### Turn 2
**You say:** *"10 AM works. My name is John Smith, born May 1st 1990, phone 512-555-1234."*

- **Hear:** "Booked for Monday at 10 AM. You'll get an SMS confirmation."
- **Backend log:** `book_appointment(...)` — then a real calendar booking is created
- **Twilio SMS** arrives at the phone number you gave (use **your real cell** for this test)

### Pass criteria
- Google Calendar shows a new booking
- SMS arrives within 5 seconds of "booked" being spoken
- Agent does **not** ask for your email (the server fills it in automatically)
- Total flow finishes in under 30 seconds wall-clock

### Failure modes to listen for
- "Confirmed" said in Turn 1 before you gave any info (false confirm)
- Wrong day-of-week label
- "What's your email?" — should never be asked

---

## Category 4 — Escalation (Explicit Human Request)
**Tools expected:** `escalate_to_human`. **Latency target:** <500 ms (server short-circuits the LLM).

Each in a fresh call:

| Say                                       | Expect to hear                                             | Backend log                       |
|-------------------------------------------|------------------------------------------------------------|-----------------------------------|
| "Can I speak to a real person please?"    | "Of course — let me transfer you. Please hold."            | `escalate_to_human(reason=...)`   |
| "Transfer me to a human."                 | Same                                                       | Same                              |
| "I want to talk to someone."              | Same                                                       | Same                              |

**Pass criteria:** Response is **near-instant** because the server detects the phrase and calls the tool itself, bypassing the LLM entirely.

---

## Category 5 — Emergency Triage
**Tools expected:** maybe `escalate_to_human` for severe cases, otherwise pure conversation. **Latency target:** 1–3 s.

| Say                                          | Expect to hear                                                              |
|----------------------------------------------|-----------------------------------------------------------------------------|
| "I'm in really bad pain and need to be seen." | Sympathetic; offers same-day emergency slot OR escalates                   |
| "I'm having a severe allergic reaction."      | Treats as urgent; advises ER if severe; offers same-day                    |
| "I have chest pain."                         | Should escalate immediately (chest pain is in the prompt's escalation triggers) |
| "It's an emergency, can I come in today?"     | Prioritizes urgency, checks for same-day availability                       |

**Pass criteria:** Empathy first, then action. Never diagnoses. Never sounds robotic during a stressful scenario.

---

## Category 6 — Tricky / Failure-Mode Probes
These exercise the guardrails. Use a fresh call for each.

| Say                                             | What we're testing                            | Expect                                                 |
|-------------------------------------------------|------------------------------------------------|--------------------------------------------------------|
| "Book me an appointment." (no date, no info)    | False-confirm guard                            | Asks for day/time, doesn't fake-book                   |
| "Book me Tuesday 10 AM, name John."             | Server-side missing-fields validation          | Asks for missing DOB and phone                         |
| "Got time on the 32nd of February?"             | Bad date handling                              | Politely says it can't find that date                  |
| "I want to cancel my appointment."              | Cancel flow                                    | Asks for booking details                               |
| "Actually, never mind. Bye."                    | Graceful exit                                  | Friendly goodbye                                       |
| "uhhhh… I dunno what I want."                   | Ambiguous input                                | Offers options conversationally; doesn't tool-call     |
| "Are you a robot?"                              | Honest response                                | Should be honest — "Yes, I'm an AI assistant"          |

---

## Demo-Day Happy Path — single call (~3 minutes)

If you want one continuous call that demonstrates everything:

```
1. "Hi."
2. "What are your hours?"
3. "Do you accept Aetna?"
4. "Do you have any slots Tuesday?"
5. "Actually, can I do tomorrow morning instead?"
6. "10 AM works. My name is John Smith, born May 1st 1990, phone <YOUR REAL CELL>."
7. (wait for confirmation + SMS to land)
8. "Thank you, that's all."
```

Watch the backend logs in your other terminal — exactly **2 tool calls** should fire in this whole conversation:

1. `get_available_slots` (when you ask about Tuesday or tomorrow)
2. `book_appointment` (when you give your info)

Plus optionally `escalate_to_human` if you trigger a transfer scenario.

---

## When something fails on a live call

1. **Capture the backend log line for the failing turn** — note the model output, tool calls, and any warnings.
2. **Reproduce in the deterministic suite:**
   ```bash
   cd dental-voice-agent
   venv/bin/python tests/test_conversation_flows.py
   ```
3. If the suite passes but the live call failed → it's likely a model flake or Vapi/SSH layer issue (network, cold-start, audio transcription mishearing).
4. If the suite fails → add a new flow that captures your scenario, find the bug at the LLM-proxy layer, fix it, then retest.

---

## What's currently bullet-proofed (server-side guards)

- **Empty/missing fields on `book_appointment`** — server rejects with a corrective message; LLM has to ask for what's missing.
- **Wrong day-of-week → date** — server resolves "Monday" / "tomorrow" / "next Tuesday" from the user's actual message and overrides the model.
- **Email asked of caller** — system prompt forbids it; server fills `noemail@<tenant>.scheduler.ai` automatically.
- **Wrong year in slot_time** — server forces `datetime.now().year` and matches by hour-of-day.
- **Wrong timezone format** — smart slot matcher finds the matching real calendar slot ignoring the timezone the LLM emitted.
- **Explicit human request** — server short-circuits the LLM, calls `escalate_to_human` directly.
- **Tool-eagerness on greetings** — server suppresses tool definitions for short non-scheduling messages.
- **`<think>` tag leaks** — server strips them before returning (defensive against model swap).
- **Vapi's generic system prompt** — server always replaces with the tenant-parameterised prompt.
