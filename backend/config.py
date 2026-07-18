"""
Application configuration — loads all settings from environment variables.
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    """Central configuration loaded from .env file."""

    # ── LLM Backend ───────────────────────────────────────────────────────
    # LLM_PROVIDER: "ollama" (local), "gemini" (Google free tier),
    # "sambanova" (SambaNova Cloud), or "groq" (Groq LPU — fastest free option)
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "ollama")

    # Ollama (local LLM)
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")

    # SambaNova Cloud (OpenAI-compatible)
    SAMBANOVA_API_KEY: str = os.getenv("SAMBANOVA_API_KEY", "")
    SAMBANOVA_MODEL: str = os.getenv("SAMBANOVA_MODEL", "Meta-Llama-3.3-70B-Instruct")
    SAMBANOVA_BASE_URL: str = os.getenv("SAMBANOVA_BASE_URL", "https://api.sambanova.ai/v1")

    # Groq (LPU inference — ~800 tok/s, generous free tier: 14,400 RPD)
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"

    # Gemini — use gemini-3.1-flash-lite (cheapest) or gemini-3-flash for better quality
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
    # Max chat-history messages sent to Gemini per request. The full transcript
    # is still saved in the session — only what's *forwarded* to the model is
    # trimmed. Keeping this low (20) is critical for cost control: on every LLM
    # turn the entire history is re-sent, so a 200-message history on a long call
    # can multiply token costs 5–10x. 20 messages (10 turns) is sufficient for
    # natural conversation continuity in a scheduling/support context.
    GEMINI_HISTORY_MAX_MESSAGES: int = int(os.getenv("GEMINI_HISTORY_MAX_MESSAGES", "20"))
    # Enable explicit context caching for the system prompt + tools. When True,
    # we create a CachedContent per tenant and reuse it across calls. Cuts
    # per-call cost ~75% on the cached prefix. May not be supported by all
    # models — leave False if you see "caching not supported" errors.
    GEMINI_USE_CONTEXT_CACHE: bool = os.getenv("GEMINI_USE_CONTEXT_CACHE", "false").lower() == "true"
    # TTL (seconds) for explicit context caches. Default 1 hour.
    GEMINI_CACHE_TTL_SECONDS: int = int(os.getenv("GEMINI_CACHE_TTL_SECONDS", "3600"))

    # ── LiveKit (voice call infrastructure) ──────────────────────────────
    # Used by the LiveKit agent worker process (backend/agents/voice_agent.py).
    # The live values are stored in platform_config DB and editable via admin.
    LIVEKIT_URL: str = os.getenv("LIVEKIT_URL", "ws://localhost:7880")
    LIVEKIT_API_KEY: str = os.getenv("LIVEKIT_API_KEY", "devkey")
    LIVEKIT_API_SECRET: str = os.getenv("LIVEKIT_API_SECRET", "devsecret")

    # ── Exotel (Indian telephony + SMS) ───────────────────────────────────
    EXOTEL_SID: str = os.getenv("EXOTEL_SID", "")
    EXOTEL_API_KEY: str = os.getenv("EXOTEL_API_KEY", "")
    EXOTEL_TOKEN: str = os.getenv("EXOTEL_TOKEN", "")
    EXOTEL_SUBDOMAIN: str = os.getenv("EXOTEL_SUBDOMAIN", "api.exotel.com")
    EXOTEL_NUMBER: str = os.getenv("EXOTEL_NUMBER", "")       # default caller ID / SMS from-number
    EXOTEL_SENDER_ID: str = os.getenv("EXOTEL_SENDER_ID", "") # DLT-registered 6-char sender header for Indian SMS (e.g. "BRTFTR")
    EXOTEL_DLT_ENTITY_ID: str = os.getenv("EXOTEL_DLT_ENTITY_ID", "")
    EXOTEL_DLT_TEMPLATE_ID: str = os.getenv("EXOTEL_DLT_TEMPLATE_ID", "")

    # ── ElevenLabs (voice preview) ───────────────────────────────────────
    ELEVENLABS_API_KEY: str = os.getenv("ELEVENLABS_API_KEY", "")
    TTS_PROVIDER: str = os.getenv("TTS_PROVIDER", "cartesia")

    # ── PostgreSQL ────────────────────────────────────────────────────────
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://scheduler_user:scheduler_pass@localhost:5432/scheduler_ai",
    )

    # ── App ───────────────────────────────────────────────────────────────
    # ESCALATION_PHONE_NUMBER → number that receives the SMS alert when a
    #   caller asks for a human. Set this to the office cell / manager's phone.
    # ESCALATION_TRANSFER_NUMBER → if set, Vapi will live-transfer the caller
    #   to this number via the `transferCall` predefined tool. Leave blank to
    #   instead end the call gracefully with a "we'll call you back" message
    #   (recommended unless you have a real staff member on the other end).
    ESCALATION_PHONE_NUMBER: str = os.getenv("ESCALATION_PHONE_NUMBER", "")
    ESCALATION_TRANSFER_NUMBER: str = os.getenv("ESCALATION_TRANSFER_NUMBER", "")
    OFFICE_TIMEZONE: str = os.getenv("OFFICE_TIMEZONE", "America/Chicago")
    OFFICE_NAME: str = os.getenv("OFFICE_NAME", "FrontDesk AI")
    DEMO_MODE: bool = os.getenv("DEMO_MODE", "true").lower() == "true"
    SERVER_BASE_URL: str = os.getenv("SERVER_BASE_URL", "http://localhost:8000")

    # ── Google Calendar OAuth (platform-level — ONE app for all tenants) ──
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_REDIRECT_URI: str = os.getenv(
        "GOOGLE_REDIRECT_URI", "http://localhost:8000/api/integrations/google/callback"
    )

    # ── Feature flags (global kill switches) ────────────────────────────
    # When False, the feature is unavailable for ALL tenants regardless of
    # their own per-tenant setting. Useful for running the platform in
    # text-only mode when SMS isn't licensed.
    FEATURE_SMS_ENABLED: bool = os.getenv("FEATURE_SMS_ENABLED", "true").lower() == "true"

    # ── Local chat mode ───────────────────────────────────────────────────
    # When True, the frontend exposes a /chat page that talks to the same
    # LLM + tool pipeline, but via text instead of voice. Useful for local
    # dev. Responses are streamed back as SSE.
    LOCAL_CHAT_MODE: bool = os.getenv("LOCAL_CHAT_MODE", "false").lower() == "true"

    # ── Derived ───────────────────────────────────────────────────────────
    @property
    def ollama_openai_base(self) -> str:
        """OpenAI-compatible base URL for Ollama."""
        return f"{self.OLLAMA_BASE_URL}/v1"

    # The OpenAI-compatible text path (llm_service) serves both Ollama and
    # SambaNova. These properties return the right base/key/model for whichever
    # provider is active, so the "else" (non-gemini) branch works for both.
    @property
    def openai_compat_base(self) -> str:
        if self.LLM_PROVIDER == "sambanova":
            return self.SAMBANOVA_BASE_URL
        if self.LLM_PROVIDER == "groq":
            return self.GROQ_BASE_URL
        return self.ollama_openai_base

    @property
    def openai_compat_key(self) -> str:
        if self.LLM_PROVIDER == "sambanova":
            return self.SAMBANOVA_API_KEY
        if self.LLM_PROVIDER == "groq":
            return self.GROQ_API_KEY
        return "ollama"  # Ollama ignores the key but the SDK requires one

    @property
    def openai_compat_model(self) -> str:
        if self.LLM_PROVIDER == "sambanova":
            return self.SAMBANOVA_MODEL
        if self.LLM_PROVIDER == "groq":
            return self.GROQ_MODEL
        return self.OLLAMA_MODEL



settings = Settings()
