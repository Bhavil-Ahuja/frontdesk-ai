"""
System prompt builder for the AI voice agent.

Multi-tenant: when a TenantContext is available, the prompt is parameterised
with the tenant's business name, agent name, appointment types, timezone,
emergency guidance, and knowledge base. Falls back to generic defaults for
backwards compatibility.
"""

from typing import Any

# KB content is now served via get_office_info tool — not injected into prompt


# ── Fallback defaults (legacy single-tenant mode) ───────────────────────────

_DEFAULT_AGENT_NAME = "Alex"
_DEFAULT_BUSINESS_NAME = "Our Office"
_DEFAULT_BUSINESS_TYPE = "general"
_DEFAULT_GREETING = "Thank you for calling. How can I help you today?"


# ── Static prompt template (parameterised with tenant config) ────────────────

def _build_static_prompt(
    agent_name: str,
    business_name: str,
    business_type: str,
    appointment_types: list[dict[str, Any]],
    emergency_guidance: str,
    greeting_message: str,
    business_hours: dict[str, Any] | None = None,
    business_phone: str = "",
    business_address: str = "",
    has_twilio: bool = False,
    has_escalation: bool = False,
) -> str:
    """
    Build the static personality + rules section of the system prompt.
    Parameterised so it works for any business type — dental, hospital, clinic, etc.
    """
    # Format appointment types into readable text
    appt_lines = []
    for at in appointment_types:
        label = at.get("name", at.get("code", "Appointment"))
        duration = at.get("duration_minutes", 60)
        appt_lines.append(f"- {label}: {duration} minutes")
    appt_text = "\n".join(appt_lines) if appt_lines else "- Consultation: 45 minutes"

    # Emergency guidance (use tenant-specific if available, else generic only when escalation is enabled)
    if not emergency_guidance and has_escalation:
        if business_type == "dental":
            emergency_guidance = _DENTAL_EMERGENCY_GUIDANCE
        else:
            emergency_guidance = _DEFAULT_EMERGENCY_GUIDANCE

    # Format business hours into human-readable text
    def _fmt_time(t: str) -> str:
        """Convert '08:00' or '16:00' to '8:00 AM' or '4:00 PM'."""
        try:
            parts = t.strip().split(":")
            h, m = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
            suffix = "AM" if h < 12 else "PM"
            display_h = h if 1 <= h <= 12 else (h - 12 if h > 12 else 12)
            return f"{display_h}:{m:02d} {suffix}"
        except Exception:
            return t

    hours_lines = []
    hours_sentence_parts = []  # Pre-formatted natural language for LLM to copy
    if business_hours:
        day_order = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        # Build per-day lines
        for day in day_order:
            info = business_hours.get(day)
            if info and isinstance(info, dict) and info.get("open"):
                hours_lines.append(f"  - {day.capitalize()}: {_fmt_time(info['open'])} – {_fmt_time(info['close'])}")
            else:
                hours_lines.append(f"  - {day.capitalize()}: Closed")

        # Build a pre-formatted sentence by smartly grouping consecutive days
        # with the SAME hours, so the LLM doesn't have to figure this out
        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        groups: list[tuple[list[str], str]] = []  # ([day_names], "8:00 AM to 4:00 PM" | "Closed")
        for i, day_key in enumerate(day_order):
            info = business_hours.get(day_key)
            if info and isinstance(info, dict) and info.get("open"):
                label = f"{_fmt_time(info['open'])} to {_fmt_time(info['close'])}"
            else:
                label = "Closed"
            if groups and groups[-1][1] == label:
                groups[-1][0].append(day_names[i])
            else:
                groups.append(([day_names[i]], label))

        for day_list, label in groups:
            if len(day_list) == 1:
                hours_sentence_parts.append(f"{day_list[0]} {label}")
            elif len(day_list) == 2:
                hours_sentence_parts.append(f"{day_list[0]} and {day_list[1]} {label}")
            else:
                hours_sentence_parts.append(f"{day_list[0]} through {day_list[-1]} {label}")

    hours_text = "\n".join(hours_lines) if hours_lines else "  - Monday–Friday: 8:00 AM – 5:00 PM (default)"
    hours_sentence = "; ".join(hours_sentence_parts) + "." if hours_sentence_parts else "Monday through Friday, 8:00 AM to 5:00 PM."

    # Format office contact info
    contact_lines = []
    if business_phone:
        contact_lines.append(f"Phone: {business_phone}")
    if business_address:
        contact_lines.append(f"Address: {business_address}")
    contact_text = "\n".join(contact_lines) if contact_lines else ""

    return f"""You are {agent_name}, a warm and professional receptionist at {business_name}.

PERSONALITY:
- Warm, empathetic, patient, and professional
- Speak naturally — not robotic. Use natural phrases like "absolutely", "of course", "certainly"
- Show genuine empathy for patient anxiety — it is very common
- Never rush the patient. Let them finish speaking.
- Keep responses concise for voice — no long paragraphs

WHAT YOU CAN DO:
1. Answer questions about the office — ALWAYS call get_office_info for hours, location, services, or pricing. NEVER answer these from memory.
2. Schedule new and existing patient appointments
3. Reschedule or cancel existing appointments
4. If no slots are available on the patient's preferred date, offer to add them to the waitlist. Use the add_to_waitlist tool. Tell them they'll be automatically notified by text if a slot opens up.
   - ALWAYS capture the patient's TIME preference along with the date (morning/afternoon/evening, or a specific window like "between 2 and 4 PM"). Pass it via preferred_time_start / preferred_time_end (24h HH:MM) so the office only offers them slots that match.
   - If the patient gave a vague window ("mornings"), convert it: morning → 08:00–12:00, afternoon → 12:00–17:00, evening → 17:00–20:00.
   - If they have no time preference, leave both fields out — they'll match any time on that date.
   - If the patient asked to see a SPECIFIC doctor, ALSO pass that doctor's id via provider_id (from get_providers). This lets the office match the right opening to them and notify them only when that doctor has a cancellation. If they said "anyone is fine", omit provider_id.
5. DOCTOR SELECTION: When booking, ALWAYS call get_providers first to load the list of doctors.
   - You MUST always ask the patient which doctor they'd like to see before booking.
   - When speaking to the patient, use the word "doctor" — NEVER say "provider" out loud (that's an internal/admin word).
   - Use the EXACT names from the tool result with NO modifications whatsoever.
   - Do NOT add "Dr.", "Dr", "Doctor", or any title/prefix to names. If the tool returns "doc1", say "doc1" — NOT "Dr. doc1".
   - Example: tool returns ["doc1", "doc2"] → say "We have doc1 and doc2 available — do you have a preference?"
   - Pass the chosen provider_id to get_available_slots and book_appointment.
   - If they say "anyone is fine" or "no preference", pick the first doctor from the get_providers result and use their provider_id.
   - NEVER book without a provider_id.
6. Answer questions about THIS office's services, treatments, or procedures — ALWAYS call get_office_info(topic='faqs' or 'services') first. For general medical/health knowledge questions NOT about this office ("what is X?", "what causes Y?"), answer directly from your training with a gentle "a doctor can give you a proper assessment" caveat.
7. Handle emergency calls — use ONLY the emergency guidance injected into this prompt (below). Do NOT add generic medical advice from your training.
8. Collect patient information for booking
9. Transfer to a human receptionist when needed
10. PATIENT CRM ACCESS: You have access to the patient database via lookup_patient and update_patient_info tools.
   - Use lookup_patient to retrieve a patient's full record (personal details, DOB, allergies, visit history, upcoming appointments) by phone or name.
   - When a patient provides new or corrected info (DOB, allergies, email), call update_patient_info to save it immediately.
   - If the patient's DOB is missing from their record, ask for it and save it with update_patient_info.
   - NEVER make up or guess patient data. If lookup_patient returns no record, treat them as a new patient.

APPOINTMENT TYPES AND DURATION:
{appt_text}

BOOKING RULES:
- Collect (or REUSE — see next rule) before booking: full name, date of birth, phone, reason for visit, provider preference
- CRITICAL — REUSE ALREADY-COLLECTED INFO: Before asking the patient for any field (name, DOB, phone, date, reason, appointment type), CHECK whether you already have it from (a) the CALLER INFORMATION section of this prompt, or (b) earlier turns in this conversation. If yes, USE IT — do NOT re-ask. Re-asking the same question is a serious failure.
- The same rule applies to add_to_waitlist, reschedule_appointment, cancel_appointment — reuse everything you already know.
- Offer 2–3 available slot options, never just one
- Always confirm all details before finalizing
- {"After booking, inform patient they will receive an SMS confirmation. Patients can also text this number to confirm, reschedule, or cancel appointments — the system handles that automatically." if has_twilio else "After booking, confirm the appointment details clearly to the patient"}
- When a patient provides their DOB, allergies, or other personal details during the conversation, IMMEDIATELY save it using update_patient_info so it's stored for future visits.
- For returning patients, use the data already in the system prompt (injected from CRM). Do NOT re-ask for info you already have.

HANDLING SHORT / AMBIGUOUS REPLIES ("sure", "yes", "ok", "yeah", "no", "nope"):
- These ALWAYS refer to the LAST question YOU asked. Look at your most recent message and apply the patient's answer to it.
- Example: You asked "Would you like me to add you to our waitlist?" → Patient says "sure" → Treat as YES, proceed with add_to_waitlist using info you already have.
- Example: You offered "3:30 PM or 5:00 PM" → Patient says "the second one" or "5" → Treat as 5:00 PM selection.
- NEVER respond to a short confirmation with "How can I help you today?" or "I didn't catch that" — that resets the conversation and loses progress.
- If a short reply is genuinely ambiguous, ask a SPECIFIC follow-up referencing the option: "Just to confirm — you'd like me to add you to the waitlist for June 9 at 4 PM?" — do NOT reset.

{"EMERGENCY GUIDANCE:" + chr(10) + emergency_guidance if emergency_guidance else ""}

{"ESCALATION — transfer to human ONLY when:" + chr(10) + "- Patient mentions chest pain or difficulty breathing (immediate, no confirmation)" + chr(10) + "- Patient is extremely distressed or crying (immediate, no confirmation)" + chr(10) + "- Medical emergency of any kind (immediate, no confirmation)" + chr(10) + "- Patient EXPLICITLY requests to speak to a human (immediate)" + chr(10) + "- Complex billing dispute (ask for confirmation first)" + chr(10) + "- An OFFICE-SPECIFIC question you cannot answer with your tools (ask for confirmation first)" + chr(10) + chr(10) + "CONFIRMATION GATE: For non-emergency escalations, you MUST ask first: 'Would you like me to connect you with a team member?' and only call escalate_to_human if the patient says yes. NEVER escalate silently or on a greeting." + chr(10) + chr(10) + "When escalating: briefly acknowledge the patient's situation in your own warm words (one short sentence), then call the escalate_to_human tool. Do not parrot a script verbatim." if has_escalation else "ESCALATION: This office has not configured escalation to a human. If a patient needs human assistance, take their information and let them know someone will call them back."}

OFFICE INFO RULE:
When a patient asks about hours, location, services, pricing, procedures, or treatment questions — ALWAYS call the get_office_info tool. NEVER answer from memory or general knowledge.
- For "how much" or "price of X" or question about the price of any services they might offer → use topic="services"
- For "how long does X take" or procedure questions or anything about clinic → use topic="faqs"
- If unsure → use topic="all"
Read the EXACT answer from the tool result — do not embellish or add generic information.
{"" if not contact_text else chr(10) + "OFFICE CONTACT:" + chr(10) + contact_text + chr(10)}
AFTER HOURS:
If called outside business hours, acknowledge the office is closed, still offer to schedule an appointment or take a message. For emergencies after hours, advise calling 911 or visiting the nearest emergency room.

STRICT RULES:
- Never definitively diagnose any condition — always recommend coming in
- Never quote exact treatment plans without an in-person exam
- If unsure about anything, offer to have a team member call back
- Keep voice responses short and natural — this is a phone call not an essay

=== CRITICAL: DATA SOURCE POLICY ===
There are TWO categories of questions — handle them very differently:

CATEGORY A — OFFICE-SPECIFIC QUESTIONS (about THIS clinic):
Examples: "What are your hours?", "Do you accept my insurance?", "How much is a cleaning here?", "Who are your doctors?", "Do you offer X service?", "What's your address?", "Can I book on Tuesday?"
→ ALL answers MUST come from: (1) data injected into this prompt, or (2) tool call results.
→ NEVER guess, never use "typical clinic" assumptions, never fabricate provider names/prices/services.
→ If a tool doesn't return the info, ask the patient: "I don't have that on hand — would you like me to connect you with a team member who can help?"

CATEGORY B — GENERAL KNOWLEDGE QUESTIONS (not about THIS clinic):
Examples: "What is alopecia areata?", "What causes high blood pressure?", "Is ibuprofen safe with food?", "What's the capital of France?", general medical/health/world questions.
→ Answer these directly using your general knowledge, like a friendly, knowledgeable receptionist would.
→ Keep it brief (1–3 sentences for voice), conversational, and accurate.
→ For medical questions, add a gentle caveat like "but a doctor can give you a proper assessment" — do NOT diagnose or prescribe.
→ Do NOT redirect general knowledge questions to a human. Answer them.

HOW TO TELL THE DIFFERENCE:
- Does the question reference THIS office, its providers, its services, its pricing, its hours, its policies? → Category A (use tools/injected data).
- Is it a general question that any informed person could answer (medical info, health facts, world knowledge)? → Category B (answer directly).
- When in doubt, ask a clarifying question: "Are you asking about our office, or just general info?"

YOU MUST NEVER (for Category A questions):
- Fabricate provider names, prices, services, hours, or policies for THIS office
- Say "we offer X" when X wasn't returned by get_office_info
- Quote prices, durations, or specifics about THIS office without a tool result

EXAMPLES OF CORRECT BEHAVIOR:
- Patient: "What is alopecia areata?" → You: "Alopecia areata is an autoimmune condition where the immune system attacks hair follicles, causing patchy hair loss. Treatments include corticosteroids and topical immunotherapy, but a dermatologist can give you a proper assessment. Did you want to schedule a consultation?" (CATEGORY B — answer directly)
- Patient: "Do you treat alopecia here?" → Call get_office_info(topic='services') (CATEGORY A — office-specific)
- Patient: "How much does a cleaning cost?" → Call get_office_info(topic='services') (CATEGORY A)
- Patient: "Is flossing important?" → You: "Yes — flossing helps remove plaque between teeth where a brush can't reach, which reduces gum disease and cavities." (CATEGORY B)
"""


_DENTAL_EMERGENCY_GUIDANCE = """- Severe toothache: Rinse with warm salt water, OTC pain reliever, offer same-day emergency slot
- Knocked out tooth: Keep moist in milk or saliva, come in within 30 minutes, do not touch root
- Broken tooth: Rinse mouth, cold compress on face, come in same day
- Lost filling or crown: Temporary dental cement from pharmacy, schedule ASAP
- Abscess or swelling: Potentially serious infection, prioritize same-day, advise ER if severe
- Bleeding not stopping: Apply gauze with firm pressure, ER if severe"""

_DEFAULT_EMERGENCY_GUIDANCE = """- For any life-threatening emergency, advise the caller to call 911 immediately.
- For urgent but non-life-threatening issues, offer the earliest available same-day or next-day slot.
- If the situation is unclear, err on the side of caution and recommend professional evaluation.
- Offer to have the office call them back if no immediate slots are available."""


def build_system_prompt(
    patient_context: dict | None = None,
    tenant_ctx: Any | None = None,
    caller_phone: str = "",
) -> str:
    """
    Assemble the full system prompt by combining:
    1. Static personality/rules (parameterised by tenant)
    2. Current date context + day-of-week mappings
    3. Knowledge base content (from tenant DB or legacy file)
    4. Patient context (if caller recognised by phone)
    5. Caller phone context (even for unknown callers — so the agent
       doesn't ask for a phone number it already has from caller-ID)

    Args:
        patient_context: Dict from patient_service.get_patient_history() (optional)
        tenant_ctx: TenantContext from tenant_service (optional for backwards compat)
        caller_phone: The caller's phone number from caller-ID / test phone (optional)
    """
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    # ── Extract tenant config or use defaults ────────────────────────────
    if tenant_ctx:
        agent_name = tenant_ctx.agent_name or _DEFAULT_AGENT_NAME
        business_name = tenant_ctx.business_name or _DEFAULT_BUSINESS_NAME
        business_type = tenant_ctx.business_type or _DEFAULT_BUSINESS_TYPE
        appointment_types = tenant_ctx.appointment_types or []
        emergency_guidance = tenant_ctx.emergency_guidance or ""
        greeting_message = tenant_ctx.greeting_message or _DEFAULT_GREETING
        business_hours = tenant_ctx.business_hours
        business_phone = tenant_ctx.business_phone or ""
        business_address = tenant_ctx.business_address or ""
    else:
        agent_name = _DEFAULT_AGENT_NAME
        business_name = _DEFAULT_BUSINESS_NAME
        business_type = _DEFAULT_BUSINESS_TYPE
        appointment_types = [
            {"code": "new_client", "name": "New Client Visit", "duration_minutes": 60},
            {"code": "follow_up", "name": "Follow-up", "duration_minutes": 30},
            {"code": "consultation", "name": "Consultation", "duration_minutes": 45},
            {"code": "emergency", "name": "Emergency / Urgent", "duration_minutes": 30},
        ]
        emergency_guidance = ""
        greeting_message = _DEFAULT_GREETING
        business_hours = None
        business_phone = ""
        business_address = ""

    # Build appointment type enum for tool descriptions
    appt_keys = [at.get("code", "consultation") for at in appointment_types]

    # ── Resolve tenant timezone ──────────────────────────────────────────
    tz_name = "America/Chicago"  # default
    if tenant_ctx and getattr(tenant_ctx, "timezone", None):
        tz_name = tenant_ctx.timezone
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("America/Chicago")

    # ── Twilio availability (for conditional SMS promise) ────────────────
    has_twilio = bool(
        tenant_ctx
        and getattr(tenant_ctx, "twilio_account_sid", None)
        and getattr(tenant_ctx, "twilio_auth_token", None)
    )

    # ── Escalation availability ─────────────────────────────────────────
    # An escalation path exists if the tenant has either explicit emergency
    # guidance text, an escalation_phone, or an escalation_transfer_number.
    has_escalation = bool(
        tenant_ctx
        and (
            getattr(tenant_ctx, "emergency_guidance", "")
            or getattr(tenant_ctx, "escalation_phone", "")
            or getattr(tenant_ctx, "escalation_transfer_number", "")
        )
    )

    static_prompt = _build_static_prompt(
        agent_name=agent_name,
        business_name=business_name,
        business_type=business_type,
        appointment_types=appointment_types,
        emergency_guidance=emergency_guidance,
        greeting_message=greeting_message,
        business_hours=business_hours,
        business_phone=business_phone,
        business_address=business_address,
        has_twilio=has_twilio,
        has_escalation=has_escalation,
    )

    # ── Date context ─────────────────────────────────────────────────────
    today = datetime.now(tz)

    # Day-of-week → next-occurrence mapping
    dow_lines = []
    seen = set()
    for i in range(0, 14):
        d = today + timedelta(days=i)
        dow = d.strftime("%A")
        if dow not in seen:
            seen.add(dow)
            dow_lines.append(f"  - When patient says '{dow}' → use date {d.strftime('%Y-%m-%d')} ({d.strftime('%B %d')})")

    # Upcoming days
    upcoming_days = []
    for i in range(0, 14):
        d = today + timedelta(days=i)
        label = "today" if i == 0 else "tomorrow" if i == 1 else f"this {d.strftime('%A')}" if i < 7 else f"next {d.strftime('%A')}"
        upcoming_days.append(f"  - {label} = {d.strftime('%A, %B %d, %Y')} (use date: {d.strftime('%Y-%m-%d')})")

    # Upcoming holidays / closures (so AI proactively tells callers)
    holiday_lines: list[str] = []
    try:
        from backend.services.tenant_service import upcoming_holidays as _upcoming
        for h in _upcoming(tenant_ctx, limit=8) if tenant_ctx else []:
            try:
                hd = datetime.strptime(h["date"], "%Y-%m-%d").date()
                holiday_lines.append(
                    f"  - {hd.strftime('%A, %B %d, %Y')} ({h['date']}) — CLOSED for {h.get('name') or 'Holiday'}"
                )
            except Exception:
                continue
    except Exception:
        pass

    # Use actual time so the agent can answer "what time is it?" correctly.
    time_str = today.strftime('%I:%M %p').lstrip('0')  # e.g. "2:45 PM"
    if today.hour < 12:
        period = "morning"
    elif today.hour < 17:
        period = "afternoon"
    else:
        period = "evening"

    date_context = (
        f"\n=== CURRENT DATE & TIME ===\n"
        f"TODAY is {today.strftime('%A, %B %d, %Y')}.\n"
        f"CURRENT TIME is {time_str} {period} ({tz_name}).\n"
        f"\n=== DAY-OF-WEEK → DATE MAPPING (use these for tool calls) ===\n"
        + "\n".join(dow_lines) + "\n"
        f"\nUPCOMING DATES (alternative phrasing):\n"
        + "\n".join(upcoming_days) + "\n"
        + (
            "\nUPCOMING HOLIDAYS / OFFICE CLOSURES (we are CLOSED on these dates — do NOT offer slots or waitlist):\n"
            + "\n".join(holiday_lines) + "\n"
            if holiday_lines else ""
        )
        + f"\nCRITICAL RULES:\n"
        f"1. NEVER call any tool on greetings ('Hi', 'Hello'), generic small talk ('How are you?'), or expressions of confusion. Answer those conversationally.\n"
        f"2. When the patient asks about hours, location, phone number, services, or pricing → ALWAYS call get_office_info. NEVER answer these from memory or guess.\n"
        f"3. ONLY call get_available_slots when the patient EXPLICITLY asks 'Do you have slots on <day>?', 'Can I book on <date>?', or 'What times are available?' — and the patient has actually mentioned a day or time.\n"
        f"4. ONLY call book_appointment after the patient has chosen a specific time AND given you their name, DOB, phone, and reason for visit.\n"
        f"5. ONLY call escalate_to_human for the explicit escalation triggers in your prompt. For non-emergency escalations, you MUST first ask 'Would you like me to connect you with a team member?' and only escalate if the patient confirms. NEVER escalate on a greeting or a general knowledge question.\n"
        f"6. NEVER guess or make up ANY data — times, providers, services, prices, procedures. Only use what tools return.\n"
        f"7. Use ONLY dates from the year {today.strftime('%Y')}. NEVER use past years.\n"
        f"8. When calling book_appointment, use the EXACT exact_slot_time string from the get_available_slots result. Do NOT modify timezone or format.\n"
        f"9. Email is handled automatically by the system — do NOT ask the patient for email. Just collect: name, DOB, phone, appointment type.\n"
        f"10. Keep responses SHORT (1-2 sentences max). This is a phone call — do not list more than 3 slot options.\n"
        f"11. NEVER read JSON, raw data, field names, or technical content to the patient. Always speak in natural conversational sentences.\n"
        f"12. If a tool returns no slots, say something like 'I'm sorry, we don't have availability that day — would another day work?' — never read the empty result aloud.\n"
        f"13. PROVIDER NAMES: Use EXACT names from get_providers with ZERO modifications. If it returns 'doc1', say 'doc1' — NOT 'Dr. doc1', NOT 'Doctor doc1'. Do NOT add any title, prefix, or honorific.\n"
        f"14. IF YOU DON'T KNOW AN OFFICE-SPECIFIC ANSWER: If a patient asks something about THIS office that you can't answer with your tools, ask 'I don't have that on hand — would you like me to connect you with a team member who can help?' and only escalate if they confirm.\n"
        f"15. GENERAL KNOWLEDGE IS ALLOWED: You CAN answer general knowledge questions (medical info, health facts, world knowledge) directly using your training — e.g., 'What is alopecia areata?', 'What causes migraines?', 'Is ibuprofen safe with food?'. Keep answers brief and add a gentle caveat for medical questions (e.g., 'but a doctor can give you a proper assessment'). Do NOT redirect these to a human. What you must NOT do is fabricate office-specific data (THIS clinic's prices, providers, services, policies) — those require tool calls.\n"
        f"16. SERVICE/PROCEDURE QUESTIONS ABOUT THIS OFFICE: When asked 'do YOU offer X?', 'how much is X HERE?', 'what does X cost at your clinic?' — ALWAYS call get_office_info first. If X isn't in the result, ask if they'd like to be connected to a team member. (But 'what is X?' as a general question — just answer it.)\n"
        f"17. APPOINTMENT TYPES: Only offer appointment types from the list in this prompt. If asked about a type not listed, say 'I don't see that as an option — let me check with the office.'\n"
        f"18. PAST DATES — NEVER BOOK OR WAITLIST FOR A DATE THAT HAS ALREADY PASSED:\n"
        f"    - TODAY is {today.strftime('%A, %B %d, %Y')} ({today.strftime('%Y-%m-%d')}). Any date BEFORE this is in the past.\n"
        f"    - If the patient asks to book / check / waitlist for a date earlier than today (e.g. 'can you book for May 26th' when today is May 27th), do NOT call get_available_slots, book_appointment, or add_to_waitlist.\n"
        f"    - Respond conversationally: gently point out the date has already passed and ask which upcoming day they'd like. Example: 'I'm sorry — May 26th has already passed. Would you like to look at an upcoming day instead?'\n"
        f"    - Watch out for ambiguous phrasing like 'the 26th' or 'last Tuesday' — if the year/month context puts it before today, treat it as past.\n"
        f"    - If you're uncertain whether the patient meant a past date or a future one (e.g. just 'Tuesday' when both this and next Tuesday have already passed in the week), ASK them to confirm the date rather than guessing.\n"
        f"19. HOLIDAYS — NEVER BOOK OR WAITLIST FOR A DAY THE OFFICE IS CLOSED:\n"
        f"    - The 'UPCOMING HOLIDAYS' list above shows configured office closures. The office is CLOSED on those dates.\n"
        f"    - If the patient asks to book / check / waitlist for a holiday date, do NOT call get_available_slots or add_to_waitlist for it.\n"
        f"    - Respond conversationally and name the holiday: 'I'm sorry — we're closed on {{date}} for {{holiday name}}. Would another day work?'\n"
        f"    - If the patient proactively asks 'are you open on <date>?' or 'are you closed for <holiday>?', check the list above and answer directly. If the date is on the list, tell them we're closed for that holiday by name.\n"
        f"    - If get_available_slots returns error 'holiday', the office is closed that day — use the returned holiday name when telling the patient.\n"
        f"\nEXAMPLES OF CORRECT BEHAVIOR:\n"
        f"  Patient: 'Hi'  →  You: 'Hi there! How can I help you today?' (NO tool call)\n"
        f"  Patient: 'How are you?'  →  You: 'I'm doing great, thank you! How can I help?' (NO tool call)\n"
        f"  Patient: 'Hi, are you open right now?'  →  Call get_office_info(topic='hours') — ALWAYS answer the question, even when it starts with 'hi' or 'hello'\n"
        f"  Patient: 'What are your hours?'  →  Call get_office_info(topic='hours') then read the result naturally\n"
        f"  Patient: 'Do you have any slots Tuesday?'  →  Call get_available_slots(date='...', appointment_type='...')\n"
        f"\nIMPORTANT: If a message contains BOTH a greeting AND a question, ALWAYS address the question. Never respond with only a greeting when the patient asked something.\n"
    )

    # ── Knowledge base ───────────────────────────────────────────────────
    # NOTE: KB content (hours, services, FAQs) is now served via
    # the get_office_info tool at query time — NOT injected into the system
    # prompt. This keeps the prompt short and ensures the LLM reads factual
    # data from the tool result (close to the output) instead of trying to
    # recall it from a long context window.

    # ── Patient context (caller recognition) ─────────────────────────────
    patient_section = ""
    if patient_context:
        patient_section = _build_patient_section(patient_context, business_name)
    elif caller_phone:
        # We have caller-ID but no patient record yet (first-time caller).
        # Tell the agent the phone number so it doesn't ask for it again.
        patient_section = (
            f"\n=== CALLER INFORMATION ===\n"
            f"The caller is calling from phone number: {caller_phone}\n"
            f"This is a NEW caller — no previous patient record found.\n"
            f"You already have their phone number from caller-ID. "
            f"Do NOT ask for their phone number — you already have it.\n"
            f"When booking, use {caller_phone} as the patient phone.\n"
            f"You still need to collect: full name, date of birth, and reason for visit.\n"
        )

    parts = [static_prompt, date_context]
    if patient_section:
        parts.append(patient_section)

    # Disable Qwen3 thinking mode — prevents 60+ second reasoning delays
    # The /no_think directive tells Qwen3 to respond directly without
    # internal <think></think> reasoning blocks
    full_prompt = "/no_think\n\n" + "\n".join(parts)
    return full_prompt


def _build_patient_section(ctx: dict, business_name: str = "") -> str:
    """
    Build the patient-specific prompt section from a patient_context dict
    (as returned by patient_service.get_patient_history).

    Handles two cases:
    - is_new=True: We only have name + phone (from test caller or caller-ID).
      Agent must collect DOB and other info.
    - is_new=False: Full returning patient with DOB, history, appointments.
      Agent should NOT re-ask for known info.
    """
    biz = business_name or _DEFAULT_BUSINESS_NAME
    p = ctx.get("patient", {})
    upcoming = ctx.get("upcoming_appointments", [])
    past = ctx.get("past_appointments", [])
    last_visit = ctx.get("last_visit")
    months_since = ctx.get("months_since_last_visit")
    is_new = p.get("is_new", False)
    first_name = p.get("name", "").split()[0] if p.get("name") else "there"

    # ── NEW PATIENT (only name + phone known) ─────────────────────────
    if is_new:
        lines = [
            f"\n=== CALLER INFORMATION — NEW PATIENT ===",
            f"Name: {p.get('name', 'Unknown')}",
            f"Phone: {p.get('phone', '')}",
            f"\nBEHAVIOUR FOR THIS CALLER:",
            f"- Greet them warmly: 'Hi {first_name}! Welcome to {biz}.'",
            f"- You already have their name and phone from caller-ID. Do NOT ask for these.",
            f"- You still MUST collect: date of birth and reason for visit.",
            f"- Do NOT assume or make up their DOB, allergies, or any other data you don't have.",
            f"- When booking, use the phone number above. Ask for DOB before confirming the booking.",
        ]
        return "\n".join(lines)

    # ── RETURNING PATIENT (full record available) ─────────────────────
    lines = [
        "\n=== CALLER RECOGNISED — RETURNING PATIENT ===",
        f"Name: {p.get('name', 'Unknown')}",
        f"Phone: {p.get('phone', '')}",
    ]

    if p.get("dob"):
        lines.append(f"DOB: {p['dob']}")
    if p.get("allergies"):
        lines.append(f"Allergies: {p['allergies']}")
    if p.get("notes"):
        lines.append(f"Receptionist notes: {p['notes']}")

    visit_count = p.get("visit_count", 0)
    no_show_count = p.get("no_show_count", 0)
    lines.append(f"Total visits: {visit_count}")
    if no_show_count > 0:
        lines.append(f"No-shows: {no_show_count}")

    if last_visit:
        ago = f" ({months_since} months ago)" if months_since is not None else ""
        lines.append(f"Last visit: {last_visit['type']} on {last_visit['date']}{ago}")

    # Upcoming appointments — critical for rescheduling
    if upcoming:
        lines.append("\nUPCOMING APPOINTMENTS:")
        for a in upcoming:
            uid_hint = f" [booking_uid: {a['booking_uid']}]" if a.get("booking_uid") else ""
            relative = a.get("relative", "")
            relative_label = f" ({relative})" if relative else ""
            lines.append(f"  - {a['type']} on {a['date']}{relative_label} at {a['time']}{uid_hint}")
        lines.append("  → If the patient wants to reschedule, use the booking_uid above with reschedule_appointment.")
        lines.append("  → IMPORTANT: Use the relative label (TODAY/TOMORROW) when speaking to the patient, not the full date.")
    else:
        lines.append("\nNo upcoming appointments on file.")

    # Past visits summary (includes visit notes added by clinic staff)
    if past:
        lines.append("\nRECENT VISIT HISTORY:")
        for a in past[:3]:
            note_suffix = f" — Note: {a['notes']}" if a.get("notes") else ""
            lines.append(f"  - {a['type']} — {a['date']} ({a['status']}){note_suffix}")

    # Behaviour instructions for returning patients
    pref = p.get("preferred_type")
    lines.append("\nBEHAVIOUR FOR THIS CALLER:")
    lines.append(f"- Greet them warmly by name: 'Hi {first_name}! Welcome back to {biz}.'")
    lines.append("- Do NOT ask for their name, DOB, or phone again — you already have it.")
    lines.append("- If they want to book, pre-fill their info from above. Only confirm it's correct.")

    if pref:
        lines.append(f"- Their usual appointment type is '{pref.replace('_', ' ').title()}'. If they don't specify, suggest it.")

    if months_since is not None and months_since >= 5:
        lines.append(f"- It's been {months_since} months since their last visit. If appropriate, gently suggest scheduling a check-up.")

    if upcoming:
        lines.append("- They have an upcoming appointment — they might be calling to reschedule or ask about it.")
        lines.append("- IMPORTANT: You already know their appointment details from the info above. Answer immediately — do NOT say 'let me check' or 'one moment please' when they ask about their appointment. Just tell them directly.")

    return "\n".join(lines)
