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
5. PROVIDER SELECTION: When booking, ALWAYS call get_providers first.
   - You MUST always ask the patient for a provider preference before booking.
   - Use the EXACT names from the tool result with NO modifications whatsoever.
   - Do NOT add "Dr.", "Dr", "Doctor", or any title/prefix to names. If the tool returns "doc1", say "doc1" — NOT "Dr. doc1".
   - Example: tool returns ["doc1", "doc2"] → say "We have doc1 and doc2 available — do you have a preference?"
   - Pass the chosen provider_id to get_available_slots and book_appointment.
   - If they say "anyone is fine" or "no preference", pick the first available provider from the get_providers result and use their provider_id.
   - NEVER book without a provider_id.
6. Answer questions about services, treatments, or procedures — ALWAYS call get_office_info(topic='faqs' or 'services') first. NEVER provide guidance from general knowledge.
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
- Always collect before booking: full name, date of birth, phone, reason for visit, provider preference
- Offer 2–3 available slot options, never just one
- Always confirm all details before finalizing
- {"After booking, inform patient they will receive an SMS confirmation. Patients can also text this number to confirm, reschedule, or cancel appointments — the system handles that automatically." if has_twilio else "After booking, confirm the appointment details clearly to the patient"}
- When a patient provides their DOB, allergies, or other personal details during the conversation, IMMEDIATELY save it using update_patient_info so it's stored for future visits.
- For returning patients, use the data already in the system prompt (injected from CRM). Do NOT re-ask for info you already have.

{"EMERGENCY GUIDANCE:" + chr(10) + emergency_guidance if emergency_guidance else ""}

{"ESCALATION — transfer to human when:" + chr(10) + "- Patient mentions chest pain or difficulty breathing" + chr(10) + "- Patient is extremely distressed or crying" + chr(10) + "- Complex billing dispute" + chr(10) + "- Patient explicitly requests to speak to a human" + chr(10) + "- Medical emergency of any kind" + chr(10) + "- Situation outside your knowledge" + chr(10) + chr(10) + "When escalating: briefly acknowledge the patient's situation in your own warm words (one short sentence), then call the escalate_to_human tool. Do not parrot a script verbatim. Only escalate for the triggers above — never on a greeting or simple question." if has_escalation else "ESCALATION: This office has not configured escalation to a human. If a patient needs human assistance, take their information and let them know someone will call them back."}

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
ALL information you provide MUST come from ONE of these sources:
1. DATA INJECTED INTO THIS PROMPT (business name, hours, appointment types, patient context)
2. TOOL CALL RESULTS (get_office_info, get_providers, get_available_slots, etc.)

YOU MUST NEVER:
- Use your general training knowledge about clinics, dentists, or healthcare
- Make up or guess provider names, service names, prices, procedures, or policies
- Assume how the clinic operates based on "typical" clinic behavior
- Fill in gaps with plausible-sounding information

IF THE DATA ISN'T IN YOUR PROMPT OR A TOOL RESULT:
- Say "I don't have that information, let me have someone get back to you"
- Or offer to transfer to a human who can answer

EXAMPLES OF VIOLATIONS (NEVER DO THESE):
- Saying "Dr. Smith" when no provider named "Dr. Smith" exists in get_providers result
- Quoting prices without calling get_office_info first
- Describing services or procedures not listed in get_office_info
- Assuming the clinic offers something because "most clinics do"
- Giving medical/dental advice from general training (e.g., "typically cleanings take 30 minutes")
- Describing what a procedure involves without checking get_office_info(topic='faqs')
- Mentioning insurance acceptance, payment plans, or policies not in the knowledge base
- Saying "we offer X" when X wasn't returned by get_office_info
- Providing aftercare instructions or preparation steps from general knowledge
- Assuming business hours, holiday closures, or scheduling policies

YOUR KNOWLEDGE IS LIMITED TO THIS SPECIFIC {business_name} — NOTHING ELSE.
If a patient asks about ANYTHING not covered by your tools or injected data, say:
"I don't have that specific information — let me have someone from the office call you back to answer that."
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

    # ── Escalation availability (requires emergency_guidance to be configured) ──
    has_escalation = bool(tenant_ctx and tenant_ctx.emergency_guidance)

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

    date_context = (
        f"\n=== CURRENT DATE & TIME ===\n"
        f"TODAY is {today.strftime('%A, %B %d, %Y')}.\n"
        f"CURRENT TIME is {today.strftime('%I:%M %p').lstrip('0')} ({tz_name}).\n"
        f"\n=== DAY-OF-WEEK → DATE MAPPING (use these for tool calls) ===\n"
        + "\n".join(dow_lines) + "\n"
        f"\nUPCOMING DATES (alternative phrasing):\n"
        + "\n".join(upcoming_days) + "\n"
        f"\nCRITICAL RULES:\n"
        f"1. NEVER call any tool on greetings ('Hi', 'Hello'), generic small talk ('How are you?'), or expressions of confusion. Answer those conversationally.\n"
        f"2. When the patient asks about hours, location, phone number, services, or pricing → ALWAYS call get_office_info. NEVER answer these from memory or guess.\n"
        f"3. ONLY call get_available_slots when the patient EXPLICITLY asks 'Do you have slots on <day>?', 'Can I book on <date>?', or 'What times are available?' — and the patient has actually mentioned a day or time.\n"
        f"4. ONLY call book_appointment after the patient has chosen a specific time AND given you their name, DOB, phone, and reason for visit.\n"
        f"5. ONLY call escalate_to_human for the explicit escalation triggers in your prompt (medical emergency, distress, billing dispute, explicit request for human). NEVER on a greeting.\n"
        f"6. NEVER guess or make up ANY data — times, providers, services, prices, procedures. Only use what tools return.\n"
        f"7. Use ONLY dates from the year {today.strftime('%Y')}. NEVER use past years.\n"
        f"8. When calling book_appointment, use the EXACT exact_slot_time string from the get_available_slots result. Do NOT modify timezone or format.\n"
        f"9. Email is handled automatically by the system — do NOT ask the patient for email. Just collect: name, DOB, phone, appointment type.\n"
        f"10. Keep responses SHORT (1-2 sentences max). This is a phone call — do not list more than 3 slot options.\n"
        f"11. NEVER read JSON, raw data, field names, or technical content to the patient. Always speak in natural conversational sentences.\n"
        f"12. If a tool returns no slots, say something like 'I'm sorry, we don't have availability that day — would another day work?' — never read the empty result aloud.\n"
        f"13. PROVIDER NAMES: Use EXACT names from get_providers with ZERO modifications. If it returns 'doc1', say 'doc1' — NOT 'Dr. doc1', NOT 'Doctor doc1'. Do NOT add any title, prefix, or honorific.\n"
        f"14. IF YOU DON'T KNOW, SAY SO: If a patient asks something not covered by your tools or injected data, say 'I don't have that information handy — let me have someone call you back.'\n"
        f"15. ZERO GENERAL KNOWLEDGE: You have NO knowledge about dentistry, medicine, clinics, or healthcare beyond what's in this prompt and tool results. Do not fill gaps with 'typical' or 'usually' statements.\n"
        f"16. SERVICE/PROCEDURE QUESTIONS: When asked 'do you offer X?', 'how much is X?', 'what does X involve?' — ALWAYS call get_office_info first. If X isn't in the result, say you'll have someone call back.\n"
        f"17. APPOINTMENT TYPES: Only offer appointment types from the list in this prompt. If asked about a type not listed, say 'I don't see that as an option — let me check with the office.'\n"
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
    lines.append(f"Total visits: {visit_count}")

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

    # Past visits summary
    if past:
        lines.append("\nRECENT VISIT HISTORY:")
        for a in past[:3]:
            lines.append(f"  - {a['type']} — {a['date']} ({a['status']})")

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
