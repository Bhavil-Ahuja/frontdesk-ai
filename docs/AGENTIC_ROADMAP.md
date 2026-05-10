# Agentic Roadmap — Scheduler.ai

This document outlines the plan to evolve Scheduler.ai from a single voice agent
into a multi-agent platform. The voice agent stays single (latency is king on
a phone call), but background agents handle everything around the call.

---

## Current State (Phase 1) — DONE

Single voice agent handling inbound calls with:
- Caller recognition (patient lookup by phone)
- Appointment booking / rescheduling / cancellation via Cal.com
- SMS confirmations and two-way SMS chat via Twilio
- Automated reminders (24h + 2h before appointment)
- Post-visit follow-ups and Google review solicitation
- Waitlist management with auto-notification
- Smart escalation to humans
- Per-tenant knowledge base, agent personality, and integrations
- Real-time admin dashboard

---

## Phase 2 — Post-Call Agent + Outbound Agent

**Goal:** Automate everything that happens after a call ends and enable proactive
outreach. These are the biggest revenue drivers and don't touch the voice path.

### 2A. Post-Call Processing Agent

Trigger: fires automatically after every call ends.

**Capabilities:**
- **Auto-summarize call** — generate a 2-3 sentence summary from the transcript
  (currently summaries are basic; this agent writes clinical-quality notes)
- **Update patient records** — extract new info mentioned on the call:
  - New allergies mentioned → update patient.allergies
  - Preference changes → update patient.notes
  - Phone/email corrections → update patient record
- **Detect follow-up actions** — parse transcript for promises made:
  - "I'll have someone call you back about billing" → create task for staff
  - "We'll send you the forms" → trigger form email
  - "Let me check with the doctor and get back to you" → create callback task
- **Flag for human review** — if the call had:
  - An escalation that wasn't handled
  - Patient expressed strong dissatisfaction
  - Medical info the agent wasn't sure about
  - Unusually long call (potential confusion/loop)

**Implementation notes:**
- Run as an async background task (similar to current reminder_service loop)
- Use the same Ollama LLM but with a dedicated "post-call analyst" system prompt
- Store results in a new `call_followups` table
- Surface flagged calls in the dashboard with a review queue

**Data model sketch:**
```python
class CallFollowup(Base):
    __tablename__ = "call_followups"

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    call_id = Column(UUID, ForeignKey("calls.id"), nullable=False)
    tenant_id = Column(UUID, ForeignKey("tenants.id"), nullable=False)

    # Auto-generated summary (richer than current call.summary)
    enhanced_summary = Column(Text, nullable=True)

    # Extracted action items
    action_items = Column(JSONB, default=list)
    # e.g. [{"type": "callback", "reason": "billing question", "assigned_to": null}]

    # Patient record updates detected
    patient_updates = Column(JSONB, default=list)
    # e.g. [{"field": "allergies", "old": "", "new": "Penicillin", "auto_applied": false}]

    # Review flags
    needs_review = Column(Boolean, default=False)
    review_reason = Column(String(255), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    reviewed_by = Column(String(255), nullable=True)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
```

---

### 2B. Outbound Agent

Trigger: scheduled campaigns + event-driven (waitlist slot opens, no-show detected).

**Capabilities:**

1. **Recall campaigns** — proactive outreach to patients overdue for a visit
   - Query patients where `months_since_last_visit >= threshold` (configurable per tenant)
   - Send SMS: "Hi Sarah, it's been 6 months since your last visit at Sunrise Clinic. Would you like to schedule a check-up? Reply YES and we'll find a time."
   - If patient replies YES → hand off to booking flow via two-way SMS
   - Track campaign metrics: sent, opened, booked, opted-out

2. **No-show follow-up** — triggered when an appointment is marked as no-show
   - Send SMS within 1 hour: "We missed you today! Would you like to reschedule?"
   - If no response in 24h, send one more follow-up
   - After 2 attempts, stop (no spam)

3. **Waitlist auto-booking** — triggered when a cancellation opens a slot
   - Check waitlist for matching appointment_type + date
   - Send SMS to waitlisted patient: "A slot just opened on Tuesday at 2 PM. Reply BOOK to grab it."
   - First responder gets it (FIFO)
   - Already partially built in waitlist_service — needs the outbound trigger

4. **Appointment confirmation calls** (stretch goal)
   - For high-value appointments, make an outbound voice call to confirm
   - "Hi, this is Alex from Sunrise Clinic confirming your appointment tomorrow at 10 AM. Will you be there?"
   - Requires Vapi outbound call API integration

**Implementation notes:**
- New `OutboundCampaign` model to track campaigns
- New `outbound_service.py` with campaign lifecycle: create → schedule → execute → report
- Respect per-tenant settings: opt-out lists, quiet hours, max messages per patient per week
- Dashboard page: campaign builder, metrics, opt-out management

**Data model sketch:**
```python
class OutboundCampaign(Base):
    __tablename__ = "outbound_campaigns"

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID, ForeignKey("tenants.id"), nullable=False)

    name = Column(String(255), nullable=False)         # "6-Month Recall — May 2026"
    campaign_type = Column(String(50), nullable=False)  # "recall", "no_show", "waitlist", "custom"
    status = Column(String(20), default="draft")        # draft, scheduled, running, completed, paused

    # Targeting
    target_criteria = Column(JSONB, default=dict)
    # e.g. {"months_since_last_visit": {"gte": 6}, "appointment_type": "consultation"}

    # Messaging
    message_template = Column(Text, nullable=False)
    channel = Column(String(20), default="sms")  # "sms", "voice" (future)

    # Schedule
    scheduled_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # Metrics
    total_targeted = Column(Integer, default=0)
    total_sent = Column(Integer, default=0)
    total_responded = Column(Integer, default=0)
    total_booked = Column(Integer, default=0)
    total_opted_out = Column(Integer, default=0)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
```

---

## Phase 3 — QA Agent + During-Call Background Agent

**Goal:** Improve quality at scale and add real-time intelligence during calls.
Implement when call volume justifies the investment.

### 3A. QA (Quality Assurance) Agent

Trigger: runs nightly or on-demand against recent call transcripts.

**Capabilities:**

1. **Transcript scoring** — rate each call on:
   - Greeting quality (warm? used patient's name?)
   - Information accuracy (did it give correct hours/pricing?)
   - Booking flow (did it collect all required fields?)
   - Escalation appropriateness (did it escalate when it should have? did it NOT escalate when it should have?)
   - Conversation naturalness (robotic? too long? confused loops?)
   - Overall score: 1-10

2. **Issue detection** — flag specific problems:
   - Agent gave wrong information (compare response to knowledge base)
   - Agent asked for info it already had (patient context wasn't used)
   - Agent failed to book when it could have
   - Agent escalated unnecessarily
   - Conversation entered a loop (repeated same response 3+ times)
   - Prompt leak (agent said something from the system prompt verbatim)

3. **Trend reporting** — weekly digest:
   - Average call quality score trending up/down
   - Most common failure modes
   - Busiest call times
   - Conversion rate: calls → bookings
   - Suggested prompt improvements based on patterns

4. **Prompt tuning suggestions** — analyze failure patterns and suggest:
   - "Patients asking about X aren't getting good answers — add to knowledge base"
   - "Agent is asking for DOB twice in 15% of calls — check patient context injection"
   - "Escalation rate increased 20% this week — review escalation triggers"

**Implementation notes:**
- Separate system prompt optimized for evaluation (not conversation)
- Store scores in a `call_quality_scores` table
- Dashboard page: quality trends, flagged calls, score distribution
- Can run on a cheaper/faster model since it's not real-time

**Data model sketch:**
```python
class CallQualityScore(Base):
    __tablename__ = "call_quality_scores"

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    call_id = Column(UUID, ForeignKey("calls.id"), nullable=False, unique=True)
    tenant_id = Column(UUID, ForeignKey("tenants.id"), nullable=False)

    overall_score = Column(Integer, nullable=False)  # 1-10
    greeting_score = Column(Integer, nullable=True)
    accuracy_score = Column(Integer, nullable=True)
    booking_score = Column(Integer, nullable=True)
    escalation_score = Column(Integer, nullable=True)
    naturalness_score = Column(Integer, nullable=True)

    issues_found = Column(JSONB, default=list)
    # e.g. [{"type": "wrong_info", "detail": "Said hours are 8-5 but KB says 8-6"}]

    suggestions = Column(JSONB, default=list)
    # e.g. [{"type": "kb_gap", "detail": "Patient asked about X-rays, no KB entry"}]

    evaluated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
```

---

### 3B. During-Call Background Agent

Trigger: fires in parallel when the voice agent is handling a call.

**Capabilities:**

1. **Real-time slot pre-fetch** — anticipate scheduling:
   - If patient mentions wanting to book, pre-fetch next 3 days of slots
   - When voice agent calls get_available_slots, result is already cached
   - Shaves 1-2 seconds off the scheduling flow

2. **Sentiment monitoring** — track emotional state during the call:
   - Detect escalating frustration, confusion, or distress
   - Alert the voice agent: "Patient seems frustrated — be extra empathetic"
   - Auto-escalate if sentiment drops below threshold

3. **Context enrichment** — pull external data mid-call:
   - Check EHR/PMS for recent lab results, prescriptions
   - Look up weather (for rescheduling: "I see there's a storm tomorrow...")
   - Check provider schedules for specific availability

**Implementation notes:**
- Requires async event system (websocket or Redis pub/sub between voice agent and background agent)
- Voice agent sends "call_started" event with patient context
- Background agent publishes enrichments that voice agent can optionally use
- Must NEVER block the voice path — all enrichment is fire-and-forget
- Latency budget: background agent results must arrive within 5 seconds to be useful

**Architecture sketch:**
```
Voice Agent (real-time)          Background Agent (parallel)
     │                                    │
     │── call_started(patient_id) ───────▶│
     │                                    │── pre-fetch slots
     │◀── slots_cached ──────────────────│
     │                                    │── monitor sentiment
     │◀── sentiment_alert ───────────────│
     │                                    │
     │── call_ended ─────────────────────▶│
                                          │── hand off to Post-Call Agent
```

---

## Priority Matrix

| Agent | Revenue Impact | Effort | Priority |
|-------|---------------|--------|----------|
| Post-Call Processing (2A) | Medium (reduces staff work) | Low-Medium | **Do first** |
| Outbound — Recall (2B.1) | **High** (reactivates dormant patients) | Medium | **Do second** |
| Outbound — No-show (2B.2) | Medium (recovers lost appointments) | Low | Do with 2B.1 |
| Outbound — Waitlist (2B.3) | Medium (fills cancellations) | Low | Do with 2B.1 |
| QA Agent (3A) | Low (ops efficiency) | Medium | After 500+ calls |
| During-Call Agent (3B) | Medium (faster, smarter calls) | High | After product-market fit |

---

## Technical Considerations

### LLM Strategy
- Voice agent: keep on local Ollama for latency + privacy
- Background agents: can use cloud LLMs (OpenAI, Claude) since they're not real-time
- QA agent: can run on a cheaper model (batch processing, not latency-sensitive)

### Infrastructure
- Phase 2 agents can run in the existing FastAPI process as background tasks
- Phase 3 (especially 3B) likely needs a message broker (Redis/RabbitMQ) for
  real-time inter-agent communication
- Consider Celery or arq for campaign job scheduling in Phase 2B

### Dashboard Pages Needed
- Phase 2A: Call review queue (flagged calls, action items, patient updates)
- Phase 2B: Campaign builder, campaign metrics, opt-out management
- Phase 3A: Quality trends, score distribution, prompt improvement suggestions
- Phase 3B: Real-time call enrichment status (stretch)

---

*Last updated: May 2026*
*Status: Phase 1 complete. Phase 2 next.*
