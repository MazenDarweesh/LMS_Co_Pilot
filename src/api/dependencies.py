# src/api/dependencies.py
import asyncpg
from fastapi import Request, Depends
from src.db.event_store import EventStoreRepository

async def get_db(request: Request) -> asyncpg.Connection:
    """
    محقن اتصال قاعدة البيانات (Database Connection Dependency):
    يستعير اتصالاً من الـ Pool المخزن في app.state.db_pool لكل طلب HTTP
    ويعيده للـ Pool تلقائياً عند انتهاء معالجة الطلب (بفضل استخدام yield).
    """
    async with request.app.state.db_pool.acquire() as connection:
        yield connection

async def get_event_store(
    db: asyncpg.Connection = Depends(get_db)
) -> EventStoreRepository:
    """
    محقن مستودع سجل الأحداث (Event Store Repository Dependency):
    ينشئ ويحقن كائن EventStoreRepository مع تمرير اتصال قاعدة البيانات المناسب.
    """
    return EventStoreRepository(connection=db)
