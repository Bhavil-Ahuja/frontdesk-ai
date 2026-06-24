"""
Seed script — populates the database with realistic demo data for a coaching institute.

Creates:
  - 1 demo tenant (Bright Future Coaching Institute)
  - 3 faculty members
  - 5 callers (students / parents)
  - 15 calls from the past 7 days with varied outcomes
  - 8 confirmed appointments across the next 2 weeks

Run:  python seed_data.py
"""

import asyncio
import random
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from backend.database import engine, async_session, init_db
from backend.models.tenant import Tenant, BusinessType, TenantStatus, PlanTier
from backend.models.provider import Provider
from backend.models.call import Call, CallOutcome
from backend.models.appointment import Appointment, AppointmentStatus, BookedVia
from backend.models.caller import Caller


# ── Demo tenant ──────────────────────────────────────────────────────────────

DEMO_TENANT_SLUG = "bright-future-coaching"

DEMO_TENANT = {
    "slug": DEMO_TENANT_SLUG,
    "business_name": "Bright Future Coaching Institute",
    "business_type": BusinessType.COACHING_INSTITUTE,
    "business_phone": "+919876540100",
    "business_address": "42, Sector 18, Noida, Uttar Pradesh 201301, India",
    "timezone": "Asia/Kolkata",
    "owner_name": "Priya Sharma",
    "owner_email": "priya@brightfuture.edu",
    "owner_phone": "+919876540101",
    "agent_name": "Aria",
    "greeting_message": "Thank you for calling Bright Future Coaching Institute! This is Aria. How can I help you today?",
    "status": TenantStatus.ACTIVE,
    "plan": PlanTier.PROFESSIONAL,
    "demo_mode": True,
    "appointment_types": [
        {"code": "demo_class", "name": "Demo Class", "duration_minutes": 60, "max_concurrent": 5},
        {"code": "counselling", "name": "Counselling Session", "duration_minutes": 45, "max_concurrent": 2},
        {"code": "enrollment", "name": "Enrollment Meeting", "duration_minutes": 30, "max_concurrent": 3},
    ],
    "business_hours": {
        "monday":    {"open": "09:00", "close": "19:00"},
        "tuesday":   {"open": "09:00", "close": "19:00"},
        "wednesday": {"open": "09:00", "close": "19:00"},
        "thursday":  {"open": "09:00", "close": "19:00"},
        "friday":    {"open": "09:00", "close": "19:00"},
        "saturday":  {"open": "10:00", "close": "16:00"},
        "sunday":    None,
    },
    "escalation_phone": "+919876540199",
    "test_caller_phone": "+919876500001",
}

# ── Faculty ───────────────────────────────────────────────────────────────────

FACULTY = [
    {
        "name": "Prof. Anand Mehta",
        "title": "M.Sc. Mathematics",
        "subject": "Mathematics",
        "appointment_types": ["demo_class", "counselling"],
        "demo_time_slots": {
            "monday":    [{"start": "10:00", "end": "11:00"}, {"start": "15:00", "end": "16:00"}],
            "wednesday": [{"start": "10:00", "end": "11:00"}, {"start": "15:00", "end": "16:00"}],
            "friday":    [{"start": "10:00", "end": "11:00"}],
        },
    },
    {
        "name": "Dr. Kavita Rao",
        "title": "Ph.D. Physics",
        "subject": "Physics",
        "appointment_types": ["demo_class", "counselling"],
        "demo_time_slots": {
            "tuesday":   [{"start": "11:00", "end": "12:00"}, {"start": "16:00", "end": "17:00"}],
            "thursday":  [{"start": "11:00", "end": "12:00"}, {"start": "16:00", "end": "17:00"}],
            "saturday":  [{"start": "11:00", "end": "12:00"}],
        },
    },
    {
        "name": "Ms. Deepa Nair",
        "title": "M.A. English",
        "subject": "English & Communication",
        "appointment_types": ["demo_class", "enrollment"],
        "demo_time_slots": {
            "monday":    [{"start": "14:00", "end": "15:00"}],
            "wednesday": [{"start": "14:00", "end": "15:00"}],
            "friday":    [{"start": "14:00", "end": "15:00"}],
            "saturday":  [{"start": "13:00", "end": "14:00"}],
        },
    },
]

# ── Sample callers ───────────────────────────────────────────────────────────

CALLERS = [
    {"name": "Rohan Verma",   "phone": "+919876541001", "email": "rohan.verma@email.com",  "dob": "03/15/2007", "is_new": False},
    {"name": "Preethi Iyer",  "phone": "+919876541002", "email": "preethi.i@email.com",    "dob": "11/22/2006", "is_new": False},
    {"name": "Aryan Kapoor",  "phone": "+919876541003", "email": "aryan.kapoor@email.com", "dob": "07/04/2007", "is_new": True},
    {"name": "Sneha Reddy",   "phone": "+919876541004", "email": "sneha.r@email.com",      "dob": "01/30/2006", "is_new": False},
    {"name": "Kiran Sharma",  "phone": "+919876541005", "email": "kiran.s@email.com",      "dob": "09/12/2008", "is_new": True},
]

# ── Sample transcripts ───────────────────────────────────────────────────────

BOOKING_TRANSCRIPT = [
    {"role": "assistant", "content": "Thank you for calling Bright Future Coaching Institute! This is Aria. How can I help you today?"},
    {"role": "user",      "content": "Hi, I'd like to book a demo class for my son in Mathematics."},
    {"role": "assistant", "content": "Absolutely! I'd be happy to arrange a demo class. Prof. Anand Mehta takes our Maths demos. Can I get your son's name and class?"},
    {"role": "user",      "content": "His name is Rohan Verma, he's in Class 11."},
    {"role": "assistant", "content": "Great, Rohan! I have a slot with Prof. Mehta this Wednesday at 10 AM or Friday at 10 AM. Which works better?"},
    {"role": "user",      "content": "Wednesday at 10 sounds perfect."},
    {"role": "assistant", "content": "Wonderful! Rohan is confirmed for a Maths demo class this Wednesday at 10 AM with Prof. Mehta. You'll get a text confirmation shortly. Anything else I can help with?"},
    {"role": "user",      "content": "No, that's all. Thank you!"},
    {"role": "assistant", "content": "You're welcome! We look forward to seeing Rohan on Wednesday. Have a great day!"},
]

INQUIRY_TRANSCRIPT = [
    {"role": "assistant", "content": "Thank you for calling Bright Future Coaching Institute! This is Aria. How can I help you today?"},
    {"role": "user",      "content": "Hi, I wanted to know about your JEE coaching batches and fees."},
    {"role": "assistant", "content": "We offer JEE Main and Advanced batches starting every month. Fees vary by batch size — regular batches are ₹8,000 per month and personal mentoring is ₹15,000. Would you like to book a free counselling session to discuss in detail?"},
    {"role": "user",      "content": "Let me think about it and call back."},
    {"role": "assistant", "content": "Of course! Take your time. We also offer a free demo class so you can experience our teaching style before deciding. Just call us whenever you're ready!"},
]

ESCALATED_TRANSCRIPT_1 = [
    {"role": "assistant", "content": "Thank you for calling Bright Future Coaching Institute! This is Aria. How can I help you today?"},
    {"role": "user",      "content": "I'm very unhappy with the recent batch change. My daughter was moved without notice."},
    {"role": "assistant", "content": "I'm really sorry to hear that — unexpected batch changes can be very disruptive. Let me connect you with our student counsellor who can look into this and resolve it for you right away."},
]

ESCALATED_TRANSCRIPT_2 = [
    {"role": "assistant", "content": "Thank you for calling Bright Future Coaching Institute! This is Aria. How can I help you today?"},
    {"role": "user",      "content": "My son has been really stressed lately and I'm worried. He says the pace is too fast."},
    {"role": "assistant", "content": "Thank you for sharing that — your son's well-being is our top priority. I'd like to connect you with one of our academic counsellors who can assess the situation and suggest the best batch or schedule for him. Shall I transfer you?"},
    {"role": "user",      "content": "Yes please, that would be helpful."},
    {"role": "assistant", "content": "Connecting you now. Please hold for just a moment."},
]

CANCELLED_TRANSCRIPT = [
    {"role": "assistant", "content": "Thank you for calling Bright Future Coaching Institute! This is Aria. How can I help you today?"},
    {"role": "user",      "content": "Hi, I need to cancel tomorrow's demo class for Sneha Reddy."},
    {"role": "assistant", "content": "Of course. I've cancelled Sneha's demo class scheduled for tomorrow. Would you like to reschedule for another day?"},
    {"role": "user",      "content": "Not right now — we'll call back when we're ready."},
    {"role": "assistant", "content": "No problem at all! Just give us a call whenever you're ready and we'll find a time that works. Have a great day!"},
]

NEW_CALLER_TRANSCRIPT = [
    {"role": "assistant", "content": "Thank you for calling Bright Future Coaching Institute! This is Aria. How can I help you today?"},
    {"role": "user",      "content": "Hi, we just moved to Austin and we're looking for coaching for our son for Class 12 Science."},
    {"role": "assistant", "content": "Welcome to Austin! We'd love to have your son join us. We have excellent faculty for Physics, Chemistry, and Maths for Class 12. Would you like to book a free demo class so he can experience our teaching style?"},
    {"role": "user",      "content": "Yes, that sounds great. What do we need to bring?"},
    {"role": "assistant", "content": "Just the student's last report card and a note of any specific topics they'd like covered. Can I get his name and your contact number?"},
    {"role": "user",      "content": "His name is Kiran Sharma, phone is 512-555-1005, email kiran.s@email.com."},
    {"role": "assistant", "content": "Perfect! I have a demo class slot available next Monday at 10 AM with Prof. Mehta for Maths or Tuesday at 11 AM with Dr. Rao for Physics. Which subject first?"},
    {"role": "user",      "content": "Physics with Dr. Rao on Tuesday sounds good."},
    {"role": "assistant", "content": "Wonderful! Kiran is booked for a Physics demo class next Tuesday at 11 AM with Dr. Rao. You'll receive a confirmation text shortly. Welcome aboard!"},
]


# ── Seed function ─────────────────────────────────────────────────────────────

async def seed():
    """Populate the database with demo data for the coaching institute tenant."""
    await init_db()

    async with async_session() as session:
        # ── Check / create demo tenant ────────────────────────────────────
        result = await session.execute(
            text("SELECT id FROM tenants WHERE slug = :slug"),
            {"slug": DEMO_TENANT_SLUG},
        )
        row = result.fetchone()

        if row:
            tenant_id = row[0]
            print(f"✓ Demo tenant already exists (id={tenant_id}). Checking data…")

            # Check if callers already seeded for this tenant
            r2 = await session.execute(
                text("SELECT COUNT(*) FROM callers WHERE tenant_id = :tid"),
                {"tid": tenant_id},
            )
            if r2.scalar() > 0:
                print("⚠  Callers already seeded for this tenant. Skipping.")
                return
        else:
            tenant = Tenant(**DEMO_TENANT)
            session.add(tenant)
            await session.flush()
            tenant_id = tenant.id
            print(f"✓ Created demo tenant '{DEMO_TENANT_SLUG}' (id={tenant_id})")

        # ── Faculty ───────────────────────────────────────────────────────
        faculty_records = []
        for f in FACULTY:
            provider = Provider(
                tenant_id=tenant_id,
                name=f["name"],
                title=f["title"],
                subject=f["subject"],
                appointment_types=f["appointment_types"],
                demo_time_slots=f["demo_time_slots"],
                is_active=True,
            )
            session.add(provider)
            faculty_records.append(provider)
        await session.flush()
        print(f"✓ Created {len(faculty_records)} faculty members")

        # ── Callers ───────────────────────────────────────────────────────
        now = datetime.now(timezone.utc)
        caller_records = []
        for p in CALLERS:
            caller_rec = Caller(
                tenant_id=tenant_id,
                name=p["name"],
                phone=p["phone"],
                email=p["email"],
                date_of_birth=p["dob"],
                is_new_caller=p["is_new"],
                first_seen_at=now - timedelta(days=random.randint(30, 365)),
                last_appointment_at=now - timedelta(days=random.randint(1, 60)),
            )
            session.add(caller_rec)
            caller_records.append(caller_rec)
        await session.flush()
        print(f"✓ Created {len(caller_records)} callers")

        # ── Calls (15 over the past 7 days) ───────────────────────────────
        transcripts = [
            (BOOKING_TRANSCRIPT,    CallOutcome.BOOKED,    "Parent booked a Maths demo class for Rohan Verma with Prof. Mehta on Wednesday at 10 AM."),
            (INQUIRY_TRANSCRIPT,    CallOutcome.INQUIRY,   "Parent inquired about JEE batch fees. Will call back."),
            (ESCALATED_TRANSCRIPT_1,CallOutcome.ESCALATED, "Parent unhappy with batch change. Escalated to student counsellor."),
            (ESCALATED_TRANSCRIPT_2,CallOutcome.ESCALATED, "Parent concerned about student stress. Transferred to academic counsellor."),
            (CANCELLED_TRANSCRIPT,  CallOutcome.CANCELLED, "Parent cancelled demo class for Sneha Reddy. Will reschedule later."),
            (NEW_CALLER_TRANSCRIPT,  CallOutcome.BOOKED,    "New student Kiran Sharma booked Physics demo with Dr. Rao on Tuesday at 11 AM."),
        ]

        call_records = []
        for i in range(15):
            days_ago = random.randint(0, 6)
            hour = random.randint(9, 18)
            started = now - timedelta(days=days_ago, hours=random.randint(0, 8))
            started = started.replace(hour=hour, minute=random.randint(0, 59), second=0, microsecond=0)
            duration = random.randint(60, 420)

            t_idx = i % len(transcripts)
            transcript, outcome, summary = transcripts[t_idx]

            stamped = [
                {**entry, "timestamp": (started + timedelta(seconds=j * 15)).isoformat()}
                for j, entry in enumerate(transcript)
            ]

            caller = random.choice(CALLERS)
            call = Call(
                tenant_id=tenant_id,
                vapi_call_id=f"demo-call-{uuid.uuid4().hex[:12]}",
                caller_number=caller["phone"],
                started_at=started,
                ended_at=started + timedelta(seconds=duration),
                duration_seconds=duration,
                outcome=outcome,
                transcript=stamped,
                summary=summary,
            )
            session.add(call)
            call_records.append(call)

        await session.flush()
        print(f"✓ Created {len(call_records)} call records")

        # ── Appointments (8 across the next 2 weeks) ─────────────────────
        apt_types = [
            ("Demo Class",         60, faculty_records[0]),  # Prof. Mehta — Maths
            ("Counselling Session", 45, faculty_records[0]),
            ("Demo Class",         60, faculty_records[1]),  # Dr. Rao — Physics
            ("Demo Class",         60, faculty_records[2]),  # Ms. Nair — English
            ("Enrollment Meeting", 30, faculty_records[2]),
            ("Counselling Session", 45, faculty_records[1]),
            ("Demo Class",         60, faculty_records[0]),
            ("Demo Class",         60, faculty_records[1]),
        ]

        for i, (apt_type, duration, faculty) in enumerate(apt_types):
            days_ahead = random.randint(1, 14)
            hour = random.choice([9, 10, 11, 13, 14, 15, 16])
            scheduled = (now + timedelta(days=days_ahead)).replace(
                hour=hour, minute=0, second=0, microsecond=0
            )

            caller_data = CALLERS[i % len(CALLERS)]
            linked_call = call_records[i % len(call_records)] if i < 5 else None

            appointment = Appointment(
                tenant_id=tenant_id,
                cal_booking_id=f"demo-booking-{uuid.uuid4().hex[:8]}",
                cal_booking_uid=f"demo-uid-{uuid.uuid4().hex[:8]}",
                student_name=caller_data["name"],
                student_phone=caller_data["phone"],
                student_email=caller_data["email"],
                date_of_birth=caller_data["dob"],
                appointment_type=apt_type,
                scheduled_at=scheduled,
                duration_minutes=duration,
                status=AppointmentStatus.CONFIRMED,
                booked_via=BookedVia.AI if i < 6 else BookedVia.MANUAL,
                provider_id=faculty.id,
                call_id=linked_call.id if linked_call else None,
                notes=f"Demo seed — {apt_type.lower()}",
            )
            session.add(appointment)

        await session.commit()
        print(f"✓ Created {len(apt_types)} appointments")

        print("\n✅ Database seeded successfully!")
        print(f"   Tenant slug : {DEMO_TENANT_SLUG}")
        print(f"   Tenant id   : {tenant_id}")
        print("   Run the server: python -m backend.main")


if __name__ == "__main__":
    asyncio.run(seed())
