import asyncio
import uuid
from sqlalchemy import select
from backend.database import async_session
from backend.models.status_history import AppointmentStatusHistory

async def check():
    appt_id = uuid.UUID("4f0057c7-afe4-4103-9440-35a7660e9cd8")
    async with async_session() as session:
        result = await session.execute(
            select(AppointmentStatusHistory)
            .where(AppointmentStatusHistory.appointment_id == appt_id)
            .order_by(AppointmentStatusHistory.created_at.asc())
        )
        entries = result.scalars().all()
        print(f"Total history entries: {len(entries)}")
        for e in entries:
            print(f"Old: {e.old_status} | New: {e.new_status} | Changed by: {e.changed_by} | Note: {e.note} | Created: {e.created_at}")

if __name__ == "__main__":
    asyncio.run(check())
