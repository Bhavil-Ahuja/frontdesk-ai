"""
Centralized defaults for the Scheduler.ai platform.

Application-level fallback values only. Import from here instead of
hardcoding values in service modules.

NOTE: Vapi-platform configs (voice provider, voice ID, stability,
similarity boost, end-call phrases) are NOT kept here — those are
Vapi assistant settings managed on the Vapi side. They live in
vapi_service.py where they belong.
"""

# Agent
DEFAULT_AGENT_NAME = "Sarah"
DEFAULT_BUSINESS_NAME = "Our Office"
DEFAULT_GREETING = "Thank you for calling. How can I help you today?"

# Scheduling
DEFAULT_TIMEZONE = "America/Chicago"
DEFAULT_SLOT_INTERVAL_MINUTES = 30
DEFAULT_APPOINTMENT_DURATION_MINUTES = 60
DEFAULT_BUSINESS_HOURS = {
    "monday": {"open": "08:00", "close": "18:00"},
    "tuesday": {"open": "08:00", "close": "18:00"},
    "wednesday": {"open": "08:00", "close": "18:00"},
    "thursday": {"open": "08:00", "close": "18:00"},
    "friday": {"open": "08:00", "close": "18:00"},
    "saturday": {"open": "09:00", "close": "14:00"},
    "sunday": None,
}

# Test data
DEFAULT_TEST_PATIENT_NAME = "Alex Johnson"
