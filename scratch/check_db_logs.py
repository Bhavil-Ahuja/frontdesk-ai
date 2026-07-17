import asyncio
from sqlalchemy import select
from backend.database import async_session
from backend.models.sms_message import SMSMessage

async def check():
    async with async_session() as session:
        result = await session.execute(
            select(SMSMessage).order_by(SMSMessage.created_at.desc()).limit(20)
        )
        msgs = result.scalars().all()
        print(f"Total SMS messages in DB: {len(msgs)}")
        for m in msgs:
            print(f"ID: {m.id} | Caller ID: {m.caller_id} | To: {m.to_number} | Body: {m.body[:60]}... | Created: {m.created_at}")

if __name__ == "__main__":
    asyncio.run(check())
