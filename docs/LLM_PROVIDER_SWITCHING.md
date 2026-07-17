# LLM Provider Switching Reference

This project supports **four** LLM providers, selectable entirely via `.env` — no
code changes needed to switch. Nothing is hardcoded; all four branches coexist
in the codebase.

There are **two independent LLM paths**, each with its own provider switch:

| Path | Used by | Env var | Code |
|------|---------|---------|------|
| **Voice** | Phone calls via LiveKit agent | `VOICE_LLM_PROVIDER` + `VOICE_LLM_MODEL` | `backend/agents/voice_agent.py` → `_build_llm()` |
| **Text** | Browser UI chat, SMS auto-replies | `LLM_PROVIDER` (+ provider-specific model vars) | `backend/services/llm_service.py` → `_process_message()` |

> You can run them on **different** providers if you want (e.g. voice on
> SambaNova, text chat on Gemini). They're fully independent.

---

## Current setup (as of Jul 2026)

```dotenv
# Text path (UI chat + SMS)
LLM_PROVIDER=sambanova

# Voice path (phone calls)
VOICE_LLM_PROVIDER=sambanova
VOICE_LLM_MODEL=Meta-Llama-3.3-70B-Instruct

# SambaNova credentials
SAMBANOVA_API_KEY=<key>
SAMBANOVA_MODEL=Meta-Llama-3.3-70B-Instruct
SAMBANOVA_BASE_URL=https://api.sambanova.ai/v1
```

---

## How to switch — copy/paste blocks

### → SambaNova (current — fast, reliable tool calls, paid credits)
```dotenv
LLM_PROVIDER=sambanova
VOICE_LLM_PROVIDER=sambanova
VOICE_LLM_MODEL=Meta-Llama-3.3-70B-Instruct
SAMBANOVA_API_KEY=<your-key>
```
- Base URL `https://api.sambanova.ai/v1` (OpenAI-compatible)
- ~98ms first token, proper `tool_calls`, streaming ✓
- Model IDs: `Meta-Llama-3.3-70B-Instruct` (verified via `/v1/models`)
- Cost: ~$0.02/call. Watch credit at dashboard.

### → Gemini (Google free tier — no cost, but thinking-model quirks)
```dotenv
LLM_PROVIDER=gemini
GEMINI_API_KEY=<your-key>
GEMINI_MODEL=gemini-2.5-flash        # text path model

VOICE_LLM_PROVIDER=gemini
VOICE_LLM_MODEL=gemini-2.5-flash     # voice path model
```
- Voice path sets `thinking_config={"thinking_budget": 0}` automatically to
  disable chain-of-thought (otherwise it leaks into TTS + adds 20-30s latency).
- Model availability rotates with quota. Known-good fallbacks tried:
  - `gemini-2.5-flash` — works, thinking model (budget=0 needed)
  - `gemini-2.5-flash-lite` — lighter, occasionally 503 (transient)
  - `gemini-2.0-flash` / `gemini-2.0-flash-lite` — hit 429 quota exhaustion
- **Avoid** `gemma-*` thinking models for voice — they stream reasoning to TTS.
- Free tier: ~15 RPM, 1500 req/day.

### → Ollama (fully local, free, but weak tool calling)
```dotenv
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b

VOICE_LLM_PROVIDER=ollama
VOICE_LLM_MODEL=qwen2.5:7b
```
- Requires `ollama serve` running locally with the model pulled.
- ⚠️ Known issue: `qwen2.5:7b` (and similar 7-8B models) **fabricate tool
  results** — they say "booked!" without emitting a `book_appointment` call,
  and time out 20-40s per turn. Fine for pipeline/plumbing tests, NOT for
  real booking flows. Use a hosted provider for anything user-facing.

### → Groq (fast, cheap — needs a Groq key, not currently provisioned)
```dotenv
VOICE_LLM_PROVIDER=groq
VOICE_LLM_MODEL=meta-llama/llama-4-scout-17b-16e-instruct   # or llama-3.3-70b-versatile
GROQ_API_KEY=<your-key>
```
- Base URL `https://api.groq.com/openai/v1` (OpenAI-compatible)
- Voice path only (no text-path branch wired — add one in `llm_service.py`
  mirroring the SambaNova pattern if you want Groq for UI chat too).
- Model options: `llama-4-scout-17b-16e-instruct` (cheapest, 594 tok/s),
  `llama-3.3-70b-versatile` (most reliable tool calls, 394 tok/s).

---

## Where the code lives (for future edits)

### Voice path — `backend/agents/voice_agent.py`, `_build_llm()`
Provider branches in priority order: `groq` → `sambanova` → `gemini` → `ollama`
(fallthrough default). Each returns an `lk_openai.LLM` (OpenAI-compatible) or
`lk_google.LLM` (Gemini). To add a provider, add another `if provider == "x"`
block returning `lk_openai.LLM(base_url=..., api_key=..., model=...)`.

### Text path — `backend/config.py` + `backend/services/llm_service.py`
- `config.py` defines `openai_compat_base` / `openai_compat_key` /
  `openai_compat_model` properties that switch between Ollama and SambaNova
  based on `LLM_PROVIDER`. Gemini has its own dedicated client
  (`_get_gemini_client`, google-genai SDK).
- `llm_service._process_message()` (line ~562) routes: `if LLM_PROVIDER ==
  "gemini"` → Gemini SDK path; **else** → OpenAI-compatible path (serves both
  ollama and sambanova via the `openai_compat_*` properties).
- To add another OpenAI-compatible provider (e.g. Groq) to the text path:
  extend the `openai_compat_*` properties in `config.py` with another branch.

### Config knobs — `backend/config.py`
```python
LLM_PROVIDER            # text path: ollama | gemini | sambanova
OLLAMA_BASE_URL / OLLAMA_MODEL
GEMINI_API_KEY / GEMINI_MODEL
SAMBANOVA_API_KEY / SAMBANOVA_MODEL / SAMBANOVA_BASE_URL
# derived (auto-switch for the OpenAI-compatible text path):
openai_compat_base / openai_compat_key / openai_compat_model
```

---

## Why we ended up on SambaNova (decision log)

1. **Bolna** (original) — no custom LLM support → dropped.
2. **Ollama `qwen2.5:7b`** — free/local but fabricates tool calls + 30s timeouts.
3. **Gemini `gemma-4-26b` / `2.5-flash`** — thinking models leak reasoning to
   TTS; `2.0-flash` hit quota 429.
4. **Groq** — great option but no API key provisioned at the time.
5. **SambaNova `Meta-Llama-3.3-70B-Instruct`** — $5 free credit, OpenAI-compatible,
   fast (~98ms first token), and **passed the function-calling test** that the
   others failed. Current choice.

After switching providers, restart both processes:
```bash
./start.sh                              # backend (text path)
python -m backend.agents.voice_agent dev  # voice agent
```
