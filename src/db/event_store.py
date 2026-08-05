# src/db/event_store.py
import asyncpg
import structlog
from uuid import uuid4
from typing import Any, List, Dict

logger = structlog.get_logger()

class EventStoreRepository:
    """
    مستودع الأحداث (Event Store Repository):
    مسؤول عن تخزين واسترجاع أحداث الـ AI Agents في جدول agent_event_log.
    """
    
    def __init__(self, connection: asyncpg.Connection):
        self._conn = connection
    
    async def insert_event(
        self,
        session_id: str,
        agent_name: str,
        event_type: str,
        payload: Dict[str, Any]
    ) -> str:
        """
        إضافة حدث جديد (Append-Only).
        بفضل Type Codec في asyncpg، نمرر الـ dict مباشرة دون الحاجة لـ json.dumps.
        """
        event_id = str(uuid4())
        
        await self._conn.execute(
            """
            INSERT INTO agent_event_log 
                (event_id, session_id, agent_name, event_type, payload)
            VALUES 
                ($1, $2, $3, $4, $5)
            """,
            event_id,
            session_id,
            agent_name,
            event_type,
            payload
        )
        
        logger.info("Event logged successfully", event_id=event_id, event_type=event_type, session_id=session_id)
        return event_id
    
    async def get_session_events(self, session_id: str) -> List[Dict[str, Any]]:
        """
        استرجاع جميع الأحداث الخاصة بجلسة معينة مرتبة زمنياً من الأقدم للأحدث.
        الـ payload يتم فك تشفيرها تلقائياً كـ dict بواسطة asyncpg Type Codec.
        """
        rows = await self._conn.fetch(
            """
            SELECT event_id, session_id, agent_name, event_type, payload, timestamp
            FROM agent_event_log
            WHERE session_id = $1
            ORDER BY timestamp ASC
            """,
            session_id
        )
        
        return [
            {
                "event_id": str(row["event_id"]),
                "session_id": row["session_id"],
                "agent_name": row["agent_name"],
                "event_type": row["event_type"],
                "payload": row["payload"],
                "timestamp": row["timestamp"].isoformat() if row["timestamp"] else None
            }
            for row in rows
        ]
