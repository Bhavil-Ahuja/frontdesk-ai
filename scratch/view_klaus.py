import asyncio
import uuid
from sqlalchemy import select
from backend.database import async_session
from backend.models.appointment import Appointment
from backend.models.caller import Caller
from backend.models.sms_message import SMSMessage

async def view():
    tenant_id = uuid.UUID("fbd472d3-93f2-4087-ad10-708f9ead0077")
    async with async_session() as session:
        result = await session.execute(
            select(Caller).where(Caller.tenant_id == tenant_id, Caller.name.ilike("%klaus%"))
        )
        callers = result.scalars().all()
        print(f"Total callers: {len(callers)}")
        for c in callers:
            print(f"Caller ID: {c.id} | Name: {c.name} | Phone: {c.phone} | Is Test: {c.is_test}")
            # SMS messages
            sms_result = await session.execute(
                select(SMSMessage).where(SMSMessage.caller_id == c.id)
            )
            messages = sms_result.scalars().all()
            print(f"  SMS messages count: {len(messages)}")
            for msg in messages:
                print(f"    - [{msg.direction}] to: {msg.to_number} | body: {msg.body} | created_at: {msg.created_at}")

            # Appointments
            appt_result = await session.execute(
                select(Appointment).where(Appointment.caller_id == c.id)
            )
            appts = appt_result.scalars().all()
            print(f"  Appointments count: {len(appts)}")
            for a in appts:
                print(f"    - ID: {a.id} | Scheduled: {a.scheduled_at} | Status: {a.status} | Booked via: {a.booked_via}")

if __name__ == "__main__":
    asyncio.run(view())
