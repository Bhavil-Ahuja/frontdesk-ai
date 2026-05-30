"""
Centralized defaults for the Scheduler.ai platform.

Application-level fallback values only. Import from here instead of
hardcoding values in service modules.

NOTE: Vapi-platform configs (voice provider, voice ID, stability,
similarity boost, end-call phrases) are NOT kept here — those are
Vapi assistant settings managed on the Vapi side. They live in
vapi_service.py where they belong.
"""

import re


def slugify_appointment_type(value: str) -> str:
    """
    Canonical slug for appointment type codes.

    Converts any input — display name, mixed-case code, or raw user text —
    into the lowercase, underscore-separated code used throughout the system.

        "Dental Cleaning"  → "dental_cleaning"
        "Follow-up"        → "follow_up"
        "NEW PATIENT VISIT" → "new_patient_visit"
        "consultation"     → "consultation"

    Every place that compares, stores, or resolves an appointment type code
    MUST use this function so slugs are consistent everywhere.
    """
    return re.sub(r"[^a-z0-9]+", "_", (value or "").lower().strip()).strip("_") or "appointment"

# Agent
DEFAULT_AGENT_NAME = "Sarah"
DEFAULT_BUSINESS_NAME = "Our Office"
DEFAULT_GREETING = "Thank you for calling. How can I help you today?"

# Scheduling
DEFAULT_TIMEZONE = "America/Chicago"
DEFAULT_SLOT_INTERVAL_MINUTES = 15
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
