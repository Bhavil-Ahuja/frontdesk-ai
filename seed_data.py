"""
Seed script — populates the database with realistic demo data.

Creates:
  - 5 patients
  - 15 calls from the past 7 days with varied outcomes
  - 8 confirmed appointments across the next 2 weeks
  - 2 escalated calls with realistic transcripts

Run:  python seed_data.py
"""

import asyncio
import random
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from backend.database import engine, async_session, init_db
from backend.models.call import Call, CallOutcome
from backend.models.appointment import Appointment, AppointmentStatus, BookedVia
from backend.models.patient import Patient


# ── Sample patients ───────────────────────────────────────────────────────────

PATIENTS = [
    {
        "name": "Maria Gonzalez",
        "phone": "+15125551001",
        "email": "maria.gonzalez@email.com",
        "dob": "03/15/1985",
        "insurance": "Delta Dental",
        "is_new": False,
    },
    {
        "name": "James Chen",
        "phone": "+15125551002",
        "email": "james.chen@email.com",
        "dob": "11/22/1992",
        "insurance": "Cigna",
        "is_new": False,
    },
    {
        "name": "Emily Thompson",
        "phone": "+15125551003",
        "email": "emily.t@email.com",
        "dob": "07/04/1978",
        "insurance": "BlueCross BlueShield",
        "is_new": True,
    },
    {
        "name": "Robert Williams",
        "phone": "+15125551004",
        "email": "rwilliams@email.com",
        "dob": "01/30/1965",
        "insurance": "Aetna",
        "is_new": False,
    },
    {
        "name": "Sarah Kim",
        "phone": "+15125551005",
        "email": "sarah.kim@email.com",
        "dob": "09/12/1990",
        "insurance": "Humana",
        "is_new": True,
    },
]

# ── Sample transcripts ───────────────────────────────────────────────────────

BOOKING_TRANSCRIPT = [
    {"role": "assistant", "content": "Thank you for calling SmileCare Dental. This is Sarah. How can I help you today?"},
    {"role": "user", "content": "Hi, I'd like to schedule a cleaning appointment please."},
    {"role": "assistant", "content": "Absolutely, I'd be happy to help you schedule a cleaning! Are you an existing patient with us or would this be your first visit?"},
    {"role": "user", "content": "I've been there before, yeah. Last time was about six months ago."},
    {"role": "assistant", "content": "Great, welcome back! Let me look up some available times for you. Could I get your name so I can pull up your information?"},
    {"role": "user", "content": "Sure, it's Maria Gonzalez."},
    {"role": "assistant", "content": "Thank you, Maria. And could you confirm the phone number we have on file?"},
    {"role": "user", "content": "It's 512-555-1001."},
    {"role": "assistant", "content": "Perfect, I've got your information right here. For a routine cleaning, I have a few openings this week. I can offer you Wednesday at 10 AM, Thursday at 2 PM, or Friday at 9 AM. Which works best for you?"},
    {"role": "user", "content": "Thursday at 2 sounds perfect."},
    {"role": "assistant", "content": "Wonderful! I've got you down for a routine cleaning this Thursday at 2 PM. You'll receive a text confirmation shortly. Is there anything else I can help you with?"},
    {"role": "user", "content": "No, that's all. Thank you so much!"},
    {"role": "assistant", "content": "You're welcome, Maria! We'll see you Thursday. Have a great day!"},
]

INQUIRY_TRANSCRIPT = [
    {"role": "assistant", "content": "Thank you for calling SmileCare Dental. This is Sarah. How can I help you today?"},
    {"role": "user", "content": "Hi, I was wondering how much teeth whitening costs?"},
    {"role": "assistant", "content": "Great question! Our in-office professional teeth whitening is $500 to $700 without insurance. The procedure takes about 90 minutes and you'll see results right away. Would you like to schedule a consultation?"},
    {"role": "user", "content": "Hmm, that's a bit more than I expected. Does insurance cover any of it?"},
    {"role": "assistant", "content": "I understand. Unfortunately, most dental insurance plans consider whitening a cosmetic procedure and don't cover it. However, we do accept CareCredit which allows you to break the cost into monthly payments with no interest if paid within the promotional period. Would you like me to share more details about that?"},
    {"role": "user", "content": "No, I think I'll think about it and call back. Thanks for the info."},
    {"role": "assistant", "content": "Of course! Take your time. When you're ready, just give us a call and we'll get you set up. Have a wonderful day!"},
]

ESCALATED_TRANSCRIPT_1 = [
    {"role": "assistant", "content": "Thank you for calling SmileCare Dental. This is Sarah. How can I help you today?"},
    {"role": "user", "content": "I need to talk to someone about my bill. I was charged for something my insurance should have covered."},
    {"role": "assistant", "content": "I'm sorry to hear about the billing concern. I want to make sure we get this resolved for you. Can you tell me a little more about what happened?"},
    {"role": "user", "content": "Yeah, I had a cleaning last month and my insurance was supposed to cover it fully but I got a bill for $180. This is really frustrating."},
    {"role": "assistant", "content": "I completely understand your frustration, and I'm sorry about the confusion. Billing questions with insurance can be tricky, and I want to make sure you get the most accurate help. Let me connect you with one of our team members who specializes in insurance and billing. They'll be able to look into this in detail for you. Please hold for just a moment."},
]

ESCALATED_TRANSCRIPT_2 = [
    {"role": "assistant", "content": "Thank you for calling SmileCare Dental. This is Sarah. How can I help you today?"},
    {"role": "user", "content": "Hi... I'm really nervous. I haven't been to a dentist in like five years and I'm pretty sure I have some serious problems. I'm kind of freaking out."},
    {"role": "assistant", "content": "I really appreciate you reaching out, and please know that you're not alone. Many of our patients feel the same way after time away from the dentist. Whatever is going on, we're here to help and there's no judgment at all."},
    {"role": "user", "content": "I think I might need a lot of work done and I'm just... I don't know if I can handle it. I get really bad anxiety at the dentist."},
    {"role": "assistant", "content": "I hear you, and dental anxiety is incredibly common. We have a wonderful team who is very gentle and understanding. We offer nitrous oxide for comfort, and you can take breaks anytime. I'd love to connect you with our care coordinator who can walk you through everything at your pace. Let me transfer you now. Please hold for just a moment."},
]

EMERGENCY_TRANSCRIPT = [
    {"role": "assistant", "content": "Thank you for calling SmileCare Dental. This is Sarah. How can I help you today?"},
    {"role": "user", "content": "I broke my tooth. It just cracked while I was eating lunch and it's really hurting."},
    {"role": "assistant", "content": "Oh no, I'm sorry that happened! Let me help you right away. First, can you rinse your mouth gently with warm water? And if you have any swelling, a cold compress on the outside of your cheek can help."},
    {"role": "user", "content": "Okay, I'll try that. Can I come in today?"},
    {"role": "assistant", "content": "Absolutely. We prioritize emergencies and I want to get you in as soon as possible. Let me check our schedule. I have an opening at 3:30 PM today. Can you make it in by then?"},
    {"role": "user", "content": "Yes, definitely. I'll be there."},
    {"role": "assistant", "content": "Perfect. Can I get your name and phone number so I can get you checked in?"},
    {"role": "user", "content": "It's James Chen, 512-555-1002."},
    {"role": "assistant", "content": "Got it, James. You're all set for an emergency visit today at 3:30 PM. You'll get a text confirmation shortly. In the meantime, try to avoid chewing on that side and take an over-the-counter pain reliever if needed. We'll take great care of you!"},
]

CANCELLED_TRANSCRIPT = [
    {"role": "assistant", "content": "Thank you for calling SmileCare Dental. This is Sarah. How can I help you today?"},
    {"role": "user", "content": "Hi, I need to cancel my appointment for tomorrow."},
    {"role": "assistant", "content": "Of course, I can help with that. Can I get your name please?"},
    {"role": "user", "content": "Robert Williams."},
    {"role": "assistant", "content": "Thank you, Robert. I see your cleaning appointment for tomorrow at 11 AM. I've gone ahead and cancelled that for you. Would you like to reschedule for another day?"},
    {"role": "user", "content": "Not right now, I'll call back when I know my schedule better."},
    {"role": "assistant", "content": "No problem at all! Just give us a call whenever you're ready and we'll find a time that works. Have a great day, Robert!"},
]

NEW_PATIENT_TRANSCRIPT = [
    {"role": "assistant", "content": "Thank you for calling SmileCare Dental. This is Sarah. How can I help you today?"},
    {"role": "user", "content": "Hi, I just moved to Austin and I'm looking for a new dentist. Do you accept Humana insurance?"},
    {"role": "assistant", "content": "Welcome to Austin! Yes, we absolutely accept Humana. We'd love to have you as a patient! Would you like to schedule your first visit with us?"},
    {"role": "user", "content": "That would be great. What do I need for a first visit?"},
    {"role": "assistant", "content": "For new patients, we do a comprehensive exam along with a cleaning, which takes about 90 minutes. I'll just need your full name, date of birth, phone number, email, and your insurance information. Would you like to get started?"},
    {"role": "user", "content": "Sure! My name is Sarah Kim, date of birth September 12, 1990, phone is 512-555-1005, email is sarah.kim@email.com, and I have Humana."},
    {"role": "assistant", "content": "Perfect, thank you Sarah! Let me check our availability. I have openings next Monday at 9 AM, next Tuesday at 1 PM, or next Wednesday at 10 AM. Which would you prefer?"},
    {"role": "user", "content": "Monday at 9 AM works for me."},
    {"role": "assistant", "content": "Wonderful! You're all set for a new patient exam and cleaning next Monday at 9 AM. Please arrive about 15 minutes early so we can get your paperwork taken care of. You'll receive a text confirmation shortly. Is there anything else I can help with?"},
    {"role": "user", "content": "No, that's everything. Thanks so much!"},
    {"role": "assistant", "content": "You're welcome, Sarah! We're excited to meet you. See you Monday!"},
]


# ── Seed function ─────────────────────────────────────────────────────────────


async def seed():
    """Populate the database with demo data."""
    await init_db()

    async with async_session() as session:
        # Check if data already exists
        result = await session.execute(text("SELECT COUNT(*) FROM patients"))
        if result.scalar() > 0:
            print("⚠ Database already has data. Skipping seed.")
            return

        now = datetime.now(timezone.utc)

        # ── Patients ──────────────────────────────────────────────────────
        patient_records = []
        for p in PATIENTS:
            patient = Patient(
                name=p["name"],
                phone=p["phone"],
                email=p["email"],
                date_of_birth=p["dob"],
                insurance_provider=p["insurance"],
                is_new_patient=p["is_new"],
                first_seen_at=now - timedelta(days=random.randint(30, 365)),
                last_appointment_at=now - timedelta(days=random.randint(1, 60)),
            )
            session.add(patient)
            patient_records.append(patient)
        await session.flush()
        print(f"✓ Created {len(patient_records)} patients")

        # ── Calls (15 over the past 7 days) ───────────────────────────────
        transcripts = [
            (BOOKING_TRANSCRIPT, CallOutcome.BOOKED, "Patient called to schedule a routine cleaning. Booked for Thursday at 2 PM."),
            (INQUIRY_TRANSCRIPT, CallOutcome.INQUIRY, "Patient inquired about teeth whitening pricing. Will call back."),
            (ESCALATED_TRANSCRIPT_1, CallOutcome.ESCALATED, "Patient had a billing dispute regarding insurance coverage. Escalated to billing team."),
            (ESCALATED_TRANSCRIPT_2, CallOutcome.ESCALATED, "Patient with severe dental anxiety needed extra support. Transferred to care coordinator."),
            (EMERGENCY_TRANSCRIPT, CallOutcome.BOOKED, "Emergency call — patient broke a tooth. Booked same-day emergency visit at 3:30 PM."),
            (CANCELLED_TRANSCRIPT, CallOutcome.CANCELLED, "Patient cancelled tomorrow's cleaning appointment. Will reschedule later."),
            (NEW_PATIENT_TRANSCRIPT, CallOutcome.BOOKED, "New patient from out of state. Booked new patient exam for Monday at 9 AM."),
        ]

        call_records = []
        for i in range(15):
            days_ago = random.randint(0, 6)
            hour = random.randint(8, 17)
            started = now - timedelta(days=days_ago, hours=random.randint(0, 8))
            started = started.replace(hour=hour, minute=random.randint(0, 59))
            duration = random.randint(60, 420)

            t_idx = i % len(transcripts)
            transcript, outcome, summary = transcripts[t_idx]

            # Add timestamps to transcript entries
            stamped = []
            for j, entry in enumerate(transcript):
                stamped.append({
                    **entry,
                    "timestamp": (started + timedelta(seconds=j * 15)).isoformat(),
                })

            caller = random.choice(PATIENTS)
            call = Call(
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
            ("Routine Cleaning", 60),
            ("New Patient Exam + Cleaning", 90),
            ("Emergency", 30),
            ("Consultation", 45),
            ("Filling", 60),
            ("Crown Preparation", 90),
            ("Teeth Whitening", 90),
            ("Routine Cleaning", 60),
        ]

        for i, (apt_type, duration) in enumerate(apt_types):
            days_ahead = random.randint(1, 14)
            hour = random.choice([9, 10, 11, 13, 14, 15, 16])
            scheduled = now + timedelta(days=days_ahead)
            scheduled = scheduled.replace(hour=hour, minute=0, second=0, microsecond=0)

            patient = PATIENTS[i % len(PATIENTS)]

            # Link to a call record if the appointment was AI-booked
            linked_call = call_records[i % len(call_records)] if i < 5 else None

            appointment = Appointment(
                cal_booking_id=f"demo-booking-{uuid.uuid4().hex[:8]}",
                cal_booking_uid=f"demo-uid-{uuid.uuid4().hex[:8]}",
                patient_name=patient["name"],
                patient_phone=patient["phone"],
                patient_email=patient["email"],
                date_of_birth=patient["dob"],
                insurance_provider=patient["insurance"],
                appointment_type=apt_type,
                scheduled_at=scheduled,
                duration_minutes=duration,
                status=AppointmentStatus.CONFIRMED,
                booked_via=BookedVia.AI if i < 6 else BookedVia.MANUAL,
                call_id=linked_call.id if linked_call else None,
                notes=f"Demo appointment — {apt_type.lower()}",
            )
            session.add(appointment)

        await session.flush()
        await session.commit()
        print(f"✓ Created {len(apt_types)} appointments")

        print("\n✅ Database seeded successfully!")
        print("   Run the server: python -m backend.main")


if __name__ == "__main__":
    asyncio.run(seed())
